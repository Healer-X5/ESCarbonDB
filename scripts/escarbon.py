#!/usr/bin/env python3
"""Release-support tools: read-only inspection, validation, retrieval and strict summaries.

These utilities were prepared for this release; they are not the original mining
or graph-construction pipeline. Outputs require a new, explicitly named directory.
"""
from pathlib import Path
from collections import Counter
import argparse
import csv
import json
import sqlite3
import math
import openpyxl

ROOT = Path(__file__).resolve().parents[1]


def sheet_rows(wb, name):
    rows = wb[name].iter_rows(values_only=True)
    headers = next(rows)
    for row in rows:
        if any(v is not None for v in row):
            yield dict(zip(headers, row))


def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def new_output(path):
    p = Path(path).resolve()
    # Explicitly forbid writing in the release's immutable data locations.
    if p == ROOT or ROOT / 'KnowledgeGraph' in p.parents or p == ROOT / 'KnowledgeGraph':
        raise ValueError('Choose a new output directory outside the data locations')
    p.mkdir(parents=True, exist_ok=False)
    return p


def inspect(root):
    w = openpyxl.load_workbook(root/'ESCarbonDB.xlsx', read_only=True, data_only=True)
    try:
        return {'worksheets': {s.title: {'dimension_rows_excluding_header': s.max_row-1,
                                       'columns': s.max_column} for s in w},
                'note': 'Worksheet dimensions; validate scans actual records.'}
    finally:
        w.close()


def validate(root, sqlite_path=None):
    w = openpyxl.load_workbook(root/'ESCarbonDB.xlsx', read_only=True, data_only=True)
    counts, refs, key_issues = {}, {}, {}
    paper_ids, materials, measurements, curated, ready = set(), set(), set(), set(), set()
    try:
        for name in w.sheetnames:
            n = 0
            keys = Counter()
            issues = Counter()
            for r in sheet_rows(w, name):
                n += 1
                p, m = r.get('paper_id'), r.get('material_id')
                if name == 'Papers': paper_ids.add(p)
                elif name == 'Materials': materials.add((p,m))
                elif name == 'Measurements': measurements.add(r['measurement_id'])
                elif name == 'Curated_Facts': curated.add(r['fact_id'])
                elif name == 'Analysis_Ready': ready.add(r['fact_id'])
                if p and paper_ids and p not in paper_ids: issues['unknown_paper'] += 1
                if m and materials and (p,m) not in materials: issues['unknown_material'] += 1
                if r.get('source_measurement_id') and r['source_measurement_id'] not in measurements:
                    issues['unknown_source_measurement'] += 1
                if name == 'Materials': key = (p,m)
                elif name == 'Synthesis_Input_Amounts':
                    key = r.get('amount_id') or r.get('input_id')
                elif name == 'ElectrochemicalTests': key = (r['test_id'],r['fact_id'])
                else:
                    key_col = {'Papers':'paper_id','Measurements':'measurement_id',
                               'Target_Field_Facts':'fact_id','Curated_Facts':'fact_id',
                               'Analysis_Ready':'fact_id','MaterialAliases':'alias_id',
                               'Evidence':'evidence_id','Lifecycle':'lifecycle_id',
                               'Activator_Precursor_Ratios':'ratio_id'}.get(name)
                    key = r.get(key_col) if key_col else None
                if key: keys[key] += 1
            counts[name] = n
            refs[name] = dict(issues)
            if any(v > 1 for v in keys.values()):
                key_issues[name] = {'duplicate_key_groups': sum(v > 1 for v in keys.values())}
    finally:
        w.close()
    nodes = {r['id'] for r in csv_rows(root/'KnowledgeGraph/nodes.csv')}
    node_rows = sum(1 for _ in csv_rows(root/'KnowledgeGraph/nodes.csv'))
    edges, edge_ids, dangling = 0, set(), 0
    for r in csv_rows(root/'KnowledgeGraph/edges.csv'):
        edges += 1
        edge_ids.add(r['id'])
        dangling += r['source'] not in nodes or r['target'] not in nodes
    result = {'workbook_record_counts': counts, 'reference_issues': refs,
              'duplicate_key_groups': key_issues,
              'analysis_ready_subset_curated': ready <= curated,
              'graph': {'nodes':node_rows,'edges':edges,'duplicate_node_ids':node_rows-len(nodes),
                        'duplicate_edge_ids':edges-len(edge_ids),'dangling_edges':dangling},
              'note':'Duplicate source aliases and test identifiers are documented; no data are corrected.'}
    if sqlite_path:
        p = Path(sqlite_path).resolve()
        with sqlite3.connect(p.as_uri()+'?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            result['sqlite_integrity'] = db.execute('PRAGMA integrity_check').fetchall()
            for kind, ids in [('nodes',nodes),('edges',edge_ids)]:
                actual = {r[0] for r in db.execute('SELECT id FROM graph_scope_'+kind+' WHERE scope=?',('source_supported',))}
                result['graph']['sqlite_scope_'+kind+'_match'] = actual == ids
    return result


def query(root, paper_id, material_id=None, field=None, limit=20):
    selected = {}
    for r in csv_rows(root/'KnowledgeGraph/nodes.csv'):
        if r['paper_id'] != paper_id: continue
        if material_id and r['material_id'] != material_id: continue
        props = json.loads(r['properties_json'])
        if field and props.get('target_field', props.get('property_name')) != field: continue
        r['properties'] = props
        r.pop('properties_json')
        selected[r['id']] = r
        if len(selected) >= limit: break
    edges = []
    for r in csv_rows(root/'KnowledgeGraph/edges.csv'):
        if r['source'] in selected and r['type'] in ['SUPPORTED_BY','HAS_FACT','HAS_MEASUREMENT','TESTED_UNDER']:
            edges.append(r)
    return {'scope':'source_supported','nodes':list(selected.values()),'outgoing_evidence_or_fact_edges':edges,
            'note':'Read-only evidence pointers. This release-support query is not the original LLM-agent workflow.'}


def statistics(root, output):
    out = new_output(output)
    w = openpyxl.load_workbook(root/'ESCarbonDB.xlsx', read_only=True, data_only=True)
    try: rows = list(sheet_rows(w,'Analysis_Ready'))
    finally: w.close()
    grouped = {}
    for r in rows:
        grouped.setdefault((r['target_field'],r['unit'] or ''),[]).append(r)
    summary = []
    for (field,unit),rs in sorted(grouped.items()):
        vals = []
        for r in rs:
            try:
                v = float(r['numeric_value'])
                if math.isfinite(v): vals.append(v)
            except (TypeError,ValueError): pass
        summary.append({'field':field,'unit':unit,'facts':len(rs),
                        'papers':len({r['paper_id'] for r in rs}),
                        'materials':len({(r['paper_id'],r['material_id']) for r in rs}),
                        'numeric_count':len(vals),'minimum':min(vals) if vals else None,
                        'maximum':max(vals) if vals else None})
    with (out/'strict_summary.csv').open('x',newline='',encoding='utf-8') as f:
        wr=csv.DictWriter(f,fieldnames=list(summary[0]));wr.writeheader();wr.writerows(summary)
    (out/'scope.json').write_text(json.dumps({'input':'ESCarbonDB.xlsx:Analysis_Ready',
        'facts':len(rows),'papers':len({r['paper_id'] for r in rows}),
        'materials':len({(r['paper_id'],r['material_id']) for r in rows}),
        'assumptions':'Descriptive coverage only. Rows are facts, not independent experiments. Units kept separate; no causal, optimum, or comparable-protocol inference.'},indent=2)+'\n')
    return {'output':str(out),'summary':summary}


def graphml(root, output):
    """Lossless string-attribute interchange from the two canonical CSV tables."""
    import networkx as nx
    if output.exists():
        raise ValueError('Choose a new output filename')
    g = nx.MultiDiGraph(scope='source_supported')
    for r in csv_rows(root/'KnowledgeGraph/nodes.csv'):
        node_id = r.pop('id')
        g.add_node(node_id, **r)
    for r in csv_rows(root/'KnowledgeGraph/edges.csv'):
        edge_id, source, target = r.pop('id'), r.pop('source'), r.pop('target')
        if source not in g or target not in g:
            raise ValueError('Dangling endpoint')
        g.add_edge(source, target, key=edge_id, **r)
    output.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(g, output, encoding='utf-8')
    return {'nodes': g.number_of_nodes(), 'edges': g.number_of_edges(),
            'output': str(output), 'scope': 'source_supported'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT,help='Release root')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('inspect')
    g=sub.add_parser('graphml');g.add_argument('--output',type=Path,required=True)
    v=sub.add_parser('validate');v.add_argument('--sqlite',type=Path)
    q=sub.add_parser('query');q.add_argument('--paper-id',required=True);q.add_argument('--material-id');q.add_argument('--field');q.add_argument('--limit',type=int,default=20)
    s=sub.add_parser('statistics');s.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='inspect':r=inspect(a.root)
    elif a.command=='graphml':r=graphml(a.root,a.output)
    elif a.command=='validate':r=validate(a.root,a.sqlite)
    elif a.command=='query':
        if a.limit<1:p.error('--limit must be positive')
        r=query(a.root,a.paper_id,a.material_id,a.field,a.limit)
    else:r=statistics(a.root,a.output)
    print(json.dumps(r,indent=2,default=str))

if __name__=='__main__':main()
