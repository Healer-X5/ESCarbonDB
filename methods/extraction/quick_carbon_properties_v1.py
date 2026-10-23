#!/usr/bin/env python3
"""Fast, provenance-preserving numeric-property mining from frozen Stage1 text block caches.
No model inference, no PDF re-render, no modification of earlier artifacts.
CSV outputs are UTF-8 with BOM for Excel on Windows.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

DEFAULT_ROOT = os.environ.get('CARBON_SOURCE_ROOT', 'inputs/production')
R = re.compile
MEASURE = [
    ('BET_SSA', R(r'(?<![\w.])(?P<value>\d{1,5}(?:\.\d+)?)\s*m\s*\^?\s*2\s*(?:/|\s+)\s*g\s*(?:\^?\s*-\s*1)?\b', re.I), 'm2/g', 10, 10000,
     R(r'\bBET\b|surface\s+area|specific\s+area|\bSSA\b|textur|poros|nitrogen\s+adsorp|N2\s+sorp', re.I)),
    ('PORE_VOLUME', R(r'(?<![\w.])(?P<value>\d{1,3}(?:\.\d+)?)\s*cm\s*\^?\s*3\s*(?:/|\s+)\s*g\s*(?:\^?\s*-\s*1)?\b', re.I), 'cm3/g', 0.01, 20,
     R(r'pore|poros|volume|\bBJH\b|\bDFT\b|adsorp', re.I)),
    ('PORE_SIZE', R(r'(?<![\w.])(?P<value>\d{1,3}(?:\.\d+)?)\s*n\s*m\b', re.I), 'nm', 0.2, 200,
     R(r'pore|poros|mesopore|micropore|pore\s+size|pore\s+diameter|\bPSD\b|\bBJH\b', re.I)),
    ('SPECIFIC_CAPACITANCE', R(r'(?<![\w.])(?P<value>\d{1,5}(?:\.\d+)?)\s*(?:F\s*(?:/|\s+)\s*g\s*(?:\^?\s*-\s*1)?|F\s*g-1)\b', re.I), 'F/g', 0.1, 3000,
     R(r'capacit|electrode|supercapacitor|\bGCD\b|galvanostat|\bCV\b|current\s+density', re.I)),
    ('AREAL_CAPACITANCE', R(r'(?<![\w.])(?P<value>\d{1,6}(?:\.\d+)?)\s*(?:mF|F)\s*(?:/|\s+)\s*cm\s*\^?\s*-?\s*2\b', re.I), 'mF_or_F/cm2', 0.01, 20000,
     R(r'capacit|electrode|supercapacitor|\bGCD\b|\bCV\b', re.I)),
    ('ENERGY_DENSITY', R(r'(?<![\w.])(?P<value>\d{1,5}(?:\.\d+)?)\s*W\s*h\s*(?:/|\s+)\s*kg\s*(?:\^?\s*-\s*1)?\b', re.I), 'Wh/kg', 0.01, 1000,
     R(r'energy|supercapacitor|\bdevice\b|\bRagone\b|\bWh\b', re.I)),
    ('POWER_DENSITY', R(r'(?<![\w.])(?P<value>\d{1,8}(?:\.\d+)?)\s*(?:kW|W)\s*(?:/|\s+)\s*kg\s*(?:\^?\s*-\s*1)?\b', re.I), 'W_or_kW/kg', 0.01, 10000000,
     R(r'power|supercapacitor|\bdevice\b|\bRagone\b|\bW\b', re.I)),
    ('CYCLE_RETENTION', R(r'(?<![\w.])(?P<value>\d{1,3}(?:\.\d+)?)\s*%', re.I), '%', 1, 110,
     R(r'capacitance\s+retention|retention\s+rate|retained|cycling\s+stability|cycle\s+stability|after\s+[\d,]+\s+cycles|cycles\s+.*retention', re.I)),
]
FACT_FIELDS = ['paper_id', 'doi', 'title', 'metric', 'value', 'unit', 'unit_as_printed', 'material_id', 'material_name',
               'binding', 'pdf_page', 'source_block_ref', 'context_block_refs', 'test_condition_hint',
               'evidence_excerpt', 'provenance', 'quality_flag']
MAT_FIELDS = ['paper_id', 'doi', 'material_id', 'material_name', 'sample_codes', 'stage1_source',
              'stage2a_material_status', 'stage2a_source', 'BET_SSA_m2_g', 'PORE_VOLUME_cm3_g', 'PORE_SIZE_nm', 'SPECIFIC_CAPACITANCE_F_g',
              'AREAL_CAPACITANCE', 'ENERGY_DENSITY_Wh_kg', 'POWER_DENSITY', 'CYCLE_RETENTION_percent', 'linked_fact_count']
PAPER_FIELDS = ['paper_id','doi','title','year','stage1_source','stage2a_pass','material_count','all_numeric_facts','linked_numeric_facts',
                'unassigned_numeric_facts','BET_SSA','PORE_VOLUME','PORE_SIZE','SPECIFIC_CAPACITANCE',
                'AREAL_CAPACITANCE','ENERGY_DENSITY','POWER_DENSITY','CYCLE_RETENTION']


def read(path):
    try:
        with open(path, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError, UnicodeError): return None


def normalize(t):
    return unicodedata.normalize('NFKC', t).replace('−','-').replace('–','-').replace('—','-').replace('·',' ').replace('\u00a0',' ')


def rows_from_cache(cache):
    pages = cache.get('pages', {})
    if not isinstance(pages, dict): return []
    result = []
    for page, blist in sorted(pages.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 999999):
        if not isinstance(blist, list): continue
        for b in blist:
            if not isinstance(b, dict): continue
            t = b.get('text','')
            if isinstance(t,str) and t.strip() and b.get('block_id'):
                result.append((int(b.get('page_pdf') or page), str(b['block_id']), t))
    return result


def material_candidates(stage1):
    out = []
    if not isinstance(stage1,dict):return out
    for m in stage1.get('materials',[]):
        if not isinstance(m,dict):continue
        aliases = []
        for key in ('sample_codes','aliases_raw'):
            v=m.get(key,[])
            if isinstance(v,str):v=[v]
            if isinstance(v,list):aliases += [a for a in v if isinstance(a,str)]
        name=m.get('name_raw','')
        if isinstance(name,str):aliases.append(name)
        clean=[]
        for a in aliases:
            a=a.strip()
            # Reject generic labels; do not force paper-level measurements into a sample.
            if 3 <= len(a) <= 80 and not (a.lower() in {'carbon','activated carbon','electrode','sample','graphene','porous carbon'}):
                if a not in clean: clean.append(a)
        out.append({'id':str(m.get('candidate_id','')), 'name':str(name), 'aliases':clean,
                    'codes':m.get('sample_codes',[])})
    return out


def bind(context, mats):
    matches=[]
    for m in mats:
        for a in m['aliases']:
            # Word boundaries work with hyphenated sample codes too.
            pat = r'(?<![\w])'+re.escape(a)+r'(?![\w])'
            if re.search(pat,context,re.I):
                matches.append(m)
                break
    if len(matches)==1:
        m=matches[0]
        return m['id'],m['name'],'DIRECT_NAME_IN_CONTEXT'
    return '','','AMBIGUOUS_MULTIPLE_SAMPLES' if matches else 'PAPER_LEVEL_ONLY'


def condition(text):
    # Store compact original nearby test conditions; do not claim they correspond
    # exactly to the numeric observation without a later scientific review.
    pieces=[]
    for pattern in [r'\b\d+(?:\.\d+)?\s*(?:mA|A)\s*(?:/|\s+)\s*g\s*(?:-\s*1)?\b',
                    r'\b\d+(?:\.\d+)?\s*mV\s*(?:/|\s+)\s*s\s*(?:-\s*1)?\b',
                    r'\b[\d,]+\s*cycles\b', r'\b(?:two|three)[- ]electrode\b']:
        for m in re.finditer(pattern,text,re.I):
            z=m.group(0).strip()
            if z not in pieces:pieces.append(z)
            if len(pieces)>=5:break
    return '; '.join(pieces[:5])


def facts_for_paper(paper, cache, stage1, metadata):
    bs = rows_from_cache(cache)
    mats = material_candidates(stage1)
    out=[]; dedup=set()
    for i,(page,ref,txt) in enumerate(bs):
        body=normalize(txt)
        # primary-block matches only, neighboring blocks for the contextual filter
        prev = normalize(bs[i-1][2])[-180:] if i and bs[i-1][0]==page else ''
        nex = normalize(bs[i+1][2])[:180] if i+1<len(bs) and bs[i+1][0]==page else ''
        blockrefs = [ref]
        if prev:blockrefs.insert(0,bs[i-1][1])
        if nex:blockrefs.append(bs[i+1][1])
        for metric,pattern,unit,lo,hi,keywords in MEASURE:
            for match in pattern.finditer(body):
                try:v=float(match.group('value'))
                except ValueError:continue
                if v<lo or v>hi:continue
                start,end=match.span()
                # A range such as 2-20 nm does not establish 20 nm as a
                # measured characteristic pore size.
                if metric == 'PORE_SIZE' and start>0 and body[start-1] == '-':
                    continue
                near= (prev[-150:]+' '+body[max(0,start-170):min(len(body),end+170)]+' '+nex[:150])
                if not keywords.search(near):continue
                if metric=='PORE_SIZE' and re.search(r'lattice\s+(?:spacing|fringe)|interlayer\s+spacing',near,re.I) and not re.search(r'pore',near,re.I):continue
                if metric=='CYCLE_RETENTION' and not re.search(r'retention|retained|cycl(?:es|ing)',near,re.I):continue
                key=(metric,page,ref,start,round(v,5))
                if key in dedup:continue
                dedup.add(key)
                m_id,m_name,binding=bind(near,mats)
                # When a clause contains multiple values for the same metric,
                # name proximity alone is NOT enough to map values one-to-one.
                nearby_hits = sum(1 for q in pattern.finditer(near))
                if nearby_hits > 1 and m_id:
                    m_id,m_name,binding = '', '', 'MULTIPLE_VALUES_UNRESOLVED_MAPPING'
                # Display evidence is normalized from copied source text; original remains in cache.
                ex=near.strip().replace('\r',' ').replace('\n',' ')
                ex=re.sub(r'\s+',' ',ex)
                detected_unit=body[match.start('value')+len(match.group('value')):end].strip()
                # For kW/kg and F/cm2 preserve printed unit (canonicalization not guessed).
                display_unit=unit
                if metric=='POWER_DENSITY':display_unit='kW/kg' if 'kW' in detected_unit else 'W/kg'
                if metric=='AREAL_CAPACITANCE':display_unit='mF/cm2' if re.search('mF',detected_unit) else 'F/cm2'
                out.append({'paper_id':paper,'doi':metadata.get('doi',''),'title':metadata.get('title',''),
                    'metric':metric,'value':v,'unit':display_unit,'unit_as_printed':detected_unit,
                    'material_id':m_id,'material_name':m_name,'binding':binding,
                    'pdf_page':page,'source_block_ref':ref,'context_block_refs':';'.join(blockrefs),
                    'test_condition_hint':condition(near),'evidence_excerpt':ex[:650],
                    'provenance':str(cache.get('pdf_sha256',''))[:24]+'|'+ref,
                    'quality_flag':('BET_METHOD_NOT_CONFIRMED; ' if metric=='BET_SSA' and not re.search(r'\bBET\b|Brunauer',near,re.I) else '')+'AUTOMATIC_TEXT_CANDIDATE_NOT_SCIENTIFICALLY_REVIEWED'})
    return out,mats


def accepted_stage1(root):
    orig=root/'21_fast_baseline_stage1_v3/papers'
    recovered=root/'22_stage1_offline_recovery_v2/papers'
    for d in sorted(orig.glob('PCSC_*')):
        if not d.is_dir():continue
        p=d.name
        orig_status=read(d/'result.json') or {}
        if orig_status.get('status')=='RAW_CONTRACT_PASS':
            source=d/'stage1_run/stage1_parsed.json'; name='RAW_CONTRACT_PASS'
        else:
            r=read(recovered/(p+'.revalidation_v2.json')) or {}
            if r.get('status')!='RECOVERED_CONTRACT_PASS':continue
            source=root/'22_stage1_offline_recovery_v1/papers'/p/'stage1_recovered.json'
            name='RECOVERED_CONTRACT_PASS'
        if source.is_file():yield p,d,source,name


def check_keys(obj,prefix='',found=None):
    if found is None:found=Counter()
    target=re.compile(r'bet|surface.area|specific.area|pore|poros|capacitance|energy.dens|power.dens|cycl.*retention|electrochem.*perform',re.I)
    if isinstance(obj,dict):
        for k,v in obj.items():
            n=(prefix+'.'+k).strip('.')
            if target.search(k) and not re.search(r'evidence|raw_text|description|input|prompt|reference',k,re.I):
                if isinstance(v,(int,float,str)) and v not in ('',None):found[n]+=1
                elif isinstance(v,(dict,list)) and v:found[n]+=1
            if isinstance(v,(dict,list)) and len(n)<120:check_keys(v,n,found)
    elif isinstance(obj,list):
        for v in obj[:1000]:check_keys(v,prefix+'[]',found)
    return found


def open_csv(path,keys):
    f=path.open('x',newline='',encoding='utf-8-sig')
    w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore')
    w.writeheader();return f,w


def stage2a_for_paper(root, paper):
    # Honor only resolved, successfully validated V1/V2 artifacts.
    candidates = [
        root/'27_stage2a_production_v2/lexical_recovery'/paper,
        root/'27_stage2a_production_v2/papers'/paper,
        root/'26_stage2a_offline_lexical_recovery_v1/papers'/paper,
        root/'25_stage2a_production_v1/papers'/paper,
    ]
    for d in candidates:
        r=read(d/'result.json') or {}
        if r.get('status') not in ('STAGE2A_RESOLVER_PASS','RECOVERED_STAGE2A_RESOLVER_PASS'):
            continue
        resolved=read(d/'stage2a.lifecycle_resolved.json') or {}
        statuses=resolved.get('material_status')
        if isinstance(statuses,dict):
            return {str(k):str(v.get('material_status','')) if isinstance(v,dict) else '' for k,v in statuses.items()},str(d)
    return {},''


def meta_load(root):
    path=root/'00_freeze/corpus/PRODUCTION_NON_GOLD_ELIGIBLE_5728_V1.tsv'
    if not path.is_file():return {}
    with path.open(encoding='utf-8-sig',newline='') as f:
        rdr=csv.DictReader(f,delimiter='\t'); data={}
        for row in rdr:
            p=row.get('paper_id','')
            data[p]={k.lower():v for k,v in row.items() if k}
    return data


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=DEFAULT_ROOT)
    ap.add_argument('--mode',choices=('audit','extract'),default='audit')
    ap.add_argument('--limit',type=int,default=0,help='0 = all accepted Stage1 papers')
    ap.add_argument('--output',default='',help='new output folder; refuse overwrite')
    args=ap.parse_args();root=Path(args.root)
    if not root.is_dir():sys.exit('ROOT_NOT_FOUND: '+str(root))
    if args.limit<0:sys.exit('INVALID_LIMIT')
    metas=meta_load(root)
    selected=list(accepted_stage1(root))
    if args.limit:selected=selected[:args.limit]
    print('STAGE1_ACCEPTED_FILES=',len(selected),flush=True)
    if args.mode=='audit':
        cnt=Counter(); examples=defaultdict(list)
        for idx,(paper,d,stage_path,origin) in enumerate(selected,1):
            objects=[('STAGE1',read(stage_path))]
            for label,pr in [('STAGE2A_V1',root/'25_stage2a_production_v1/papers'/paper/'stage2a.evidence.json'),
                             ('STAGE2A_V2',root/'27_stage2a_production_v2/papers'/paper/'stage2a.evidence.json')]:
                if pr.is_file():objects.append((label,read(pr)))
            for label,obj in objects:
                if not isinstance(obj,(dict,list)):continue
                for k,n in check_keys(obj).items():
                    cnt[(label,k)]+=n
                    if len(examples[(label,k)])<3:examples[(label,k)].append(paper)
            if idx%1000==0:print('AUDITED=',idx,flush=True)
        print('EXISTING_PROPERTY_NAMED_FIELDS=')
        for (label,k),n in cnt.most_common(30):print(' ',label,k,'COUNT',n,'SAMPLES',','.join(examples[(label,k)]))
        if not cnt:print('NONE_IN_CHECKED_STAGE1_STAGE2A_STRUCTURES')
        print('NOTE=Evidence text may include numbers but is not structured as numeric property fields.')
        print('MODEL_CALLS=0; SOURCE_MODIFICATIONS=0')
        return
    out=Path(args.output) if args.output else root/'31_quick_carbon_properties_v1'/('run_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True,exist_ok=False)
    f_f,w_f=open_csv(out/'measurement_facts.csv',FACT_FIELDS)
    f_m,w_m=open_csv(out/'material_summary.csv',MAT_FIELDS)
    f_p,w_p=open_csv(out/'paper_summary.csv',PAPER_FIELDS)
    total=Counter(); count=Counter(); unseen=[]
    try:
        for n,(paper,d,stage_path,origin) in enumerate(selected,1):
            stage=read(stage_path);cache=read(d/'stage1_run/block_cache.json')
            meta=metas.get(paper,{})
            if not isinstance(stage,dict) or not isinstance(cache,dict):
                unseen.append((paper,'STAGE1_OR_CACHE_MISSING'))
                continue
            fs,mats=facts_for_paper(paper,cache,stage,meta)
            lifecycle,life_source=stage2a_for_paper(root,paper)
            bymat=defaultdict(list)
            for x in fs:
                w_f.writerow(x);count[x['metric']]+=1
                if x['material_id']:bymat[x['material_id']].append(x)
            for m in mats:
                x={'paper_id':paper,'doi':meta.get('doi',''),'material_id':m['id'],
                   'material_name':m['name'],'sample_codes':';'.join(str(z) for z in m['codes']) if isinstance(m['codes'],list) else str(m['codes']),
                   'stage1_source':origin, 'stage2a_material_status':lifecycle.get(m['id'],''), 'stage2a_source':life_source}
                linked=bymat.get(m['id'],[])
                x['linked_fact_count']=len(linked)
                for field,metric in [('BET_SSA_m2_g','BET_SSA'),('PORE_VOLUME_cm3_g','PORE_VOLUME'),('PORE_SIZE_nm','PORE_SIZE'),
                       ('SPECIFIC_CAPACITANCE_F_g','SPECIFIC_CAPACITANCE'),('AREAL_CAPACITANCE','AREAL_CAPACITANCE'),
                       ('ENERGY_DENSITY_Wh_kg','ENERGY_DENSITY'),('POWER_DENSITY','POWER_DENSITY'),('CYCLE_RETENTION_percent','CYCLE_RETENTION')]:
                    values=sorted(set(f"{f['value']:g} {f['unit']}" for f in linked if f['metric']==metric))
                    x[field]='; '.join(values[:30])
                w_m.writerow(x)
            metric_counts=Counter(f['metric'] for f in fs)
            w_p.writerow({'paper_id':paper,'doi':meta.get('doi',''),'title':meta.get('title',''),'year':meta.get('year',''),
                          'stage1_source':origin,'stage2a_pass':bool(life_source),'material_count':len(mats),'all_numeric_facts':len(fs),
                          'linked_numeric_facts':sum(bool(f['material_id']) for f in fs),
                          'unassigned_numeric_facts':sum(not f['material_id'] for f in fs),**metric_counts})
            total['paper_rows']+=1;total['material_rows']+=len(mats);total['fact_rows']+=len(fs)
            if fs:total['papers_with_measurements']+=1
            if n%300==0:print(f'PROGRESS {n}/{len(selected)} FACTS={total["fact_rows"]}',flush=True)
    finally:
        for f in (f_f,f_m,f_p):f.close()
    with (out/'skipped_papers.csv').open('x',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['paper_id','reason']);w.writerows(unseen)
    summary={'version':'quick_carbon_properties_v1','accepted_input_count':len(selected),'totals':dict(total),
             'metrics':dict(count),'skipped':len(unseen),'source_authority':'frozen Stage1 block_cache; not full PDF',
             'evidence_policy':'AUTOMATIC_TEXT_CANDIDATE_NOT_SCIENTIFICALLY_REVIEWED',
             'model_calls':0,'source_artifacts_modified':False}
    with (out/'summary.json').open('x',encoding='utf-8') as f:json.dump(summary,f,indent=2,ensure_ascii=False)
    print('\n===== QUICK PROPERTY MINING RESULT =====')
    print('OUTPUT=',out)
    print('PAPERS=',total['paper_rows'],'MATERIALS=',total['material_rows'], 'MEASUREMENT_FACTS=',total['fact_rows'])
    print('PAPERS_WITH_NUMERIC_FACTS=',total['papers_with_measurements'],'SKIPPED=',len(unseen))
    print('METRICS=',dict(count))
    print('MODEL_CALLS=0; ORIGINAL_ARTIFACTS_MODIFIED=FALSE')

if __name__=='__main__':main()
