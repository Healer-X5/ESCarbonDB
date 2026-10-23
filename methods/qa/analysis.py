"""Deterministic eligibility, counts, and scientific summaries."""
import collections
import json
from retrieval import strict_record, retrieve_same_sample_pairs, missing_protocol, classify_biomass

DEFAULT_POLICY = {
    'cohort': 'KG v2 strict-ready canonical observations with resolved evidence and explicit sample attribution',
    'high_capacitance_threshold_F_g': 300.0,
    'threshold_comparison': '>=',
    'threshold_reason': 'Transparent round screening cutoff, not a universal material standard; fixed before querying and never tuned to an optimum.',
    'temperature_bin_edges_C': [0, 500, 600, 700, 800, 900, 1000, 1500],
    'bin_semantics': 'left closed, right open; last bin includes its right endpoint',
    'representative_rule': 'One observation per material and complete protocol group, including current density or scan rate. Exact-protocol repeats use observation_id as a deterministic tie-break, never the largest capacitance. Preserve every original observation and never pool different currents as independent material samples.',
    'compatibility_fields': ['testing_configuration','electrolyte','voltage_window','capacitance_mass_basis','measurement_method','current_density','scan_rate'],
    'inference_policy': 'Descriptive counts only; no regression, confidence intervals, causal claim, or global optimum for sparse publication coverage.',
}


def group_key(r):
    return tuple(r.get(k, '') for k in DEFAULT_POLICY['compatibility_fields'])


def analyze_temperature_capacitance(records, evidence, policy=None):
    policy = policy or DEFAULT_POLICY
    evidence_ids = {e['id'] for e in evidence}
    ts = [r for r in records if r['target_field']=='carbonization_temperature_C']
    cs = [r for r in records if r['target_field']=='specific_capacitance_F_g']
    excluded = []
    strict_t, strict_c = [], []
    for r in records:
        reasons = []
        if not r['strict_ready']: reasons.append('NOT_IN_STRICT_READY_COHORT')
        if not strict_record(r, evidence_ids) and r['strict_ready']: reasons.append('EVIDENCE_OR_EXPLICIT_ATTRIBUTION_INCOMPLETE')
        if r['numeric_value'] is None or r['numeric_value'] <= 0: reasons.append('MISSING_OR_NONPOSITIVE_VALUE')
        expected = 'C' if r['target_field']=='carbonization_temperature_C' else 'F/g'
        if r['unit'] != expected: reasons.append('UNIT_MISMATCH')
        if r['target_field']=='carbonization_temperature_C' and r.get('thermal_process') not in ('', 'CARBONIZATION'):
            reasons.append('NOT_CARBONIZATION')
        if reasons:
            excluded.append(dict(observation_id=r['observation_id'],material_key=r['material_key'],target_field=r['target_field'],exclusion_reasons=reasons))
        elif r['target_field']=='carbonization_temperature_C': strict_t.append(r)
        else: strict_c.append(r)
    candidate_pairs = retrieve_same_sample_pairs(ts, cs)
    strict_pairs = retrieve_same_sample_pairs(strict_t, strict_c)
    eligible, rejected_pairs = [], []
    by_temp = collections.defaultdict(set)
    for t in strict_t: by_temp[t['material_key']].add(t['numeric_value'])
    for t, c in strict_pairs:
        reasons = []
        if len(by_temp[t['material_key']])!=1: reasons.append('CONFLICTING_SAME_SAMPLE_TEMPERATURES')
        if missing_protocol([c]) != {k:0 for k in missing_protocol([c])}: reasons.append('INCOMPLETE_MEASUREMENT_PROTOCOL')
        if not c['measurement_method']: reasons.append('MISSING_MEASUREMENT_METHOD')
        if t['sample_name'] != c['sample_name']: reasons.append('SAMPLE_LABEL_DISAGREEMENT')
        if t['material_stage']!='FINAL_SAMPLE' or c['material_stage']!='FINAL_SAMPLE': reasons.append('MATERIAL_STAGE_MISMATCH')
        if reasons:
            rejected_pairs.append(dict(temperature_observation_id=t['observation_id'],capacitance_observation_id=c['observation_id'],exclusion_reasons=reasons))
            continue
        eligible.append(dict(paper_id=c['paper_id'],material_id=c['material_id'],material_key=c['material_key'],sample_name=c['sample_name'],
            temperature_C=t['numeric_value'],specific_capacitance_F_g=c['numeric_value'],
            temperature_observation_id=t['observation_id'],capacitance_observation_id=c['observation_id'],
            temperature_fact_id=t['fact_id'],capacitance_fact_id=c['fact_id'],
            temperature_evidence_id=t['evidence_id'],capacitance_evidence_id=c['evidence_id'],
            temperature_process='CARBONIZATION',temperature_unit='C',capacitance_unit='F/g',
            **{k:c[k] for k in DEFAULT_POLICY['compatibility_fields']},
            high_capacitance=c['numeric_value']>=policy['high_capacitance_threshold_F_g']))
    representatives = {}
    for r in sorted(eligible, key=lambda r:r['capacitance_observation_id']):
        representatives.setdefault((r['material_key'],group_key(r)),r)
    reps = sorted(representatives.values(),key=lambda r:(group_key(r),r['temperature_C'],r['material_key']))
    # A sample measured under different protocols stays in distinct groups; groups are never pooled.
    groups = collections.defaultdict(list)
    for r in reps: groups[group_key(r)].append(r)
    bins = []
    edges = policy['temperature_bin_edges_C']
    for gid,(key,rows) in enumerate(sorted(groups.items()),1):
        for i,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
            members = [r for r in rows if lo <= r['temperature_C'] < hi or (i==len(edges)-2 and r['temperature_C']==hi)]
            high = [r for r in members if r['high_capacitance']]
            bins.append(dict(group_id=gid,low_C=lo,high_C=hi,
                eligible_observations=len(members),eligible_materials=len({r['material_key'] for r in members}),
                eligible_papers=len({r['paper_id'] for r in members}),high_observations=len(high),
                high_materials=len({r['material_key'] for r in high}),high_papers=len({r['paper_id'] for r in high}),
                empirical_high_fraction=len(high)/len(members) if members else None))
    used_t={r['temperature_observation_id'] for r in eligible}
    unused_t=[r for r in strict_t if r['observation_id'] not in used_t]
    for r in unused_t:
        excluded.append(dict(observation_id=r['observation_id'],material_key=r['material_key'],target_field=r['target_field'],exclusion_reasons=['NO_ELIGIBLE_SAME_SAMPLE_CAPACITANCE']))
    reasons=collections.Counter(reason for r in excluded for reason in r['exclusion_reasons'])
    return dict(policy=policy,retrieved_records=len(records),raw_source_representations=sum(r['members'] for r in records),
        unique_observations=len({r['observation_id'] for r in records}),unique_materials=len({r['material_key'] for r in records}),
        unique_papers=len({r['paper_id'] for r in records}),source_supported_temperatures=len(ts),source_supported_capacitances=len(cs),
        strict_temperature_observations=len(strict_t),strict_capacitance_observations=len(strict_c),
        source_supported_same_key_pair_candidates=len(candidate_pairs),strict_same_sample_pair_candidates=len(strict_pairs),
        valid_same_sample_pairs=len(eligible),eligible_observations=len(reps),eligible_materials=len({r['material_key'] for r in reps}),
        eligible_papers=len({r['paper_id'] for r in reps}),compatible_measurement_groups=len(groups),
        high_capacitance_materials=len({r['material_key'] for r in reps if r['high_capacitance']}),
        missing_conditions_source_supported=missing_protocol(cs),missing_conditions_strict=missing_protocol(strict_c),
        exclusions=excluded,exclusion_reason_counts=dict(reasons),excluded_canonical_records=len(excluded),
        pair_exclusions=rejected_pairs,eligible=eligible,representatives=reps,bins=bins,
        measurement_groups=[dict(group_id=i,protocol=dict(zip(DEFAULT_POLICY['compatibility_fields'],key)),materials=len(rows),papers=len({r['paper_id'] for r in rows})) for i,(key,rows) in enumerate(sorted(groups.items()),1)])


def recommend_biomass_synthesis(precursors, records, evidence):
    eids={e['id'] for e in evidence}
    categories=collections.Counter(classify_biomass(r['text_value']) for r in precursors)
    biomass=[r for r in precursors if classify_biomass(r['text_value']) in ('plant_or_algal_biomass','animal_or_marine_biopolymer')]
    strict_precursors=[r for r in biomass if strict_record(r,eids)]
    by_key=collections.defaultdict(dict)
    for r in records:
        if strict_record(r,eids): by_key[r['material_key']].setdefault(r['target_field'],[]).append(r)
    paths=[]
    for p in strict_precursors:
        facts=by_key[p['material_key']]
        types=sorted(set(facts)|{'carbon_precursor'})
        paths.append(dict(paper_id=p['paper_id'],material_id=p['material_id'],material_key=p['material_key'],sample_name=p['sample_name'],precursor=p['text_value'],biomass_category=classify_biomass(p['text_value']),
            evidence_category='SOURCE_SUPPORTED_PARTIAL_SYNTHESIS_PATHWAY',fields=types,
            fact_ids=[p['fact_id']]+[r['fact_id'] for v in facts.values() for r in v if r['fact_id']!=p['fact_id']],
            evidence_ids=sorted({p['evidence_id']}|{r['evidence_id'] for v in facts.values() for r in v}),
            complete_KG_path='specific_capacitance_F_g' in facts))
    return dict(precursor_screen_records=len(precursors),precursor_category_counts=dict(categories),
        biomass_screen_observations=len(biomass),biomass_screen_materials=len({r['material_key'] for r in biomass}),
        biomass_screen_papers=len({r['paper_id'] for r in biomass}),
        retrieved_records=len(records),unique_observations=len({r['observation_id'] for r in records}),
        unique_materials=len({r['material_key'] for r in records}),unique_papers=len({r['paper_id'] for r in records}),
        strict_biomass_precursor_materials=len({r['material_key'] for r in strict_precursors}),
        strict_biomass_precursor_papers=len({r['paper_id'] for r in strict_precursors}),
        strict_partial_paths=len(paths),strict_complete_performance_paths=sum(p['complete_KG_path'] for p in paths),
        evidence_paths=paths,classification_limit='Lexical screening is conservative and is not independent PDF certification of every biomass label. Unknown origins are retained as unresolved.',
        high_target_F_g=300,high_target_met_by_strict_complete_path=False)
