"""Read-only, logged retrieval of canonical KG observations and bounded subgraphs."""
from pathlib import Path
import collections
import os
import json
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[2]
KG_ROOT = ROOT.parent
DB = Path(os.environ.get('ESCARBON_KG_DATABASE', str(ROOT / 'KnowledgeGraph/kg.sqlite')))
FIELDS = {
    'carbonization_temperature_C', 'specific_capacitance_F_g', 'BET_SSA_m2_g',
    'carbon_precursor', 'activating_agent', 'activation_temperature_C',
    'activator_to_precursor_mass_ratio', 'pore_volume_cm3_g', 'pore_size_nm',
    'energy_density_Wh_kg', 'power_density_W_kg', 'capacitance_retention_percent',
}
PROTOCOL = ['testing_configuration', 'electrolyte', 'current_density', 'scan_rate',
            'voltage_window', 'capacitance_mass_basis', 'measurement_method']


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def csvout(path, rows, fields=None):
    import csv
    rows = list(rows)
    fields = fields or list(dict.fromkeys(k for r in rows for k in r)) or ['record_id']
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()})


class GraphStore:
    def __init__(self, path=DB):
        self.path = Path(path).resolve()
        self.db = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')
        self.actions = []

    def query(self, name, sql, params=()):
        start = time.monotonic()
        rows = [dict(r) for r in self.db.execute(sql, params)]
        self.actions.append(dict(operation=name, sql=sql, parameters=list(params),
                                 returned_rows=len(rows), elapsed_seconds=round(time.monotonic()-start, 4)))
        return rows

    def inventory(self):
        return {name: self.query(name, sql) for name, sql in {
            'node_scope_counts': 'SELECT scope,COUNT(*) AS count FROM graph_scope_nodes GROUP BY scope',
            'edge_scope_counts': 'SELECT scope,COUNT(*) AS count FROM graph_scope_edges GROUP BY scope',
            'observation_quality_counts': '''SELECT target_field,COUNT(*) AS canonical,
                SUM(source_supported) AS source_supported,SUM(strict_ready) AS strict_ready,
                SUM(members) AS source_representations FROM observations GROUP BY target_field''',
            'strict_fact_count': 'SELECT COUNT(*) AS count FROM observations WHERE strict_ready=1',
            'strict_task_unique_coverage': '''SELECT target_field,COUNT(*) AS observations,
                COUNT(DISTINCT paper_id) AS publications,
                COUNT(DISTINCT paper_id||'|'||material_id) AS material_samples
                FROM observations WHERE strict_ready=1 GROUP BY target_field''',
        }.items()}

    def retrieve_property_observations(self, fields, paper_ids=None, material_keys=None):
        if not fields or not set(fields) <= FIELDS:
            raise ValueError('Property fields must come from the scientific field allowlist')
        sql = '''SELECT o.*,n.source_table,n.source_record_id,n.attrs_json
                 FROM observations o JOIN nodes n ON n.id=o.representative_node_id
                 WHERE o.source_supported=1 AND o.target_field IN (''' + ','.join('?' for _ in fields) + ')'
        params = list(fields)
        if paper_ids:
            sql += ' AND o.paper_id IN (' + ','.join('?' for _ in paper_ids) + ')'
            params += list(paper_ids)
        # Keys are values, never SQL fragments. Empty selection must return no records.
        if material_keys is not None:
            if not material_keys:
                sql += ' AND 0=1'
            else:
                sql += " AND (o.paper_id||'|'||o.material_id) IN (" + ','.join('?' for _ in material_keys) + ')'
                params += list(material_keys)
        sql += ' ORDER BY o.paper_id,o.material_id,o.target_field,o.observation_id'
        rows = self.query('retrieve_property_observations', sql, params)
        result = []
        for r in rows:
            attrs = json.loads(r.pop('attrs_json'))
            r['attributes'] = attrs
            r['material_key'] = r['paper_id'] + '|' + r['material_id']
            for k in ['fact_id', 'sample_name', 'source_sample_label', 'evidence_id', 'source_page',
                      'verification_status', 'attribution_status', 'thermal_process', 'chemical_role',
                      'synthesis_step_id', 'material_stage', 'condition_evidence_ids'] + PROTOCOL:
                r[k] = attrs.get(k) or attrs.get('v4_' + k) or ''
            r['text_value'] = attrs.get('normalized_value') or attrs.get('original_value') or ''
            result.append(r)
        return result

    def retrieve_materials(self, keys):
        return self.nodes_by_ids(['Material:' + key.replace('|', ':') for key in sorted(set(keys))])

    def retrieve_papers(self, ids):
        rows = self.nodes_by_ids(['Paper:' + p for p in sorted(set(ids))])
        return {r['paper_id']: r['attributes'] for r in rows}

    def nodes_by_ids(self, ids):
        if not ids:
            return []
        result = []
        for offset in range(0, len(ids), 400):
            part = ids[offset:offset+400]
            rows = self.query('retrieve_nodes', 'SELECT * FROM nodes WHERE id IN (' + ','.join('?' for _ in part) + ')', part)
            for r in rows:
                r['attributes'] = json.loads(r.pop('attrs_json'))
            result += rows
        return result

    def retrieve_members(self, ids):
        result = []
        for offset in range(0, len(ids), 400):
            part = ids[offset:offset+400]
            result += self.query('retrieve_observation_members', 'SELECT * FROM observation_members WHERE observation_id IN (' + ','.join('?' for _ in part) + ')', part)
        return result

    def retrieve_evidence(self, records):
        ids = set()
        for r in records:
            a = r.get('attributes', r)
            for k in ['evidence_id', 'condition_evidence_ids', 'v4_evidence_ids', 'source_evidence_id']:
                ids.update(x.strip() for x in str(a.get(k, '')).split(';') if x.strip())
        # Follow actual graph edges as well as explicit source evidence pointers.
        nodes = [r['representative_node_id'] for r in records if r.get('representative_node_id')]
        for offset in range(0, len(nodes), 400):
            part = nodes[offset:offset+400]
            es = self.query('retrieve_evidence_links', 'SELECT target FROM edges WHERE type=? AND source IN (' + ','.join('?' for _ in part) + ')', ['SUPPORTED_BY'] + part)
            ids.update(e['target'].removeprefix('Evidence:') for e in es)
        return self.nodes_by_ids(['Evidence:' + x for x in sorted(ids)])

    def retrieve_synthesis_conditions(self, keys):
        if not keys:
            return []
        rows = self.query('retrieve_synthesis_conditions',
            "SELECT * FROM nodes WHERE source_supported=1 AND type IN (?,?,?) AND (paper_id||'|'||material_id) IN (" + ','.join('?' for _ in keys) + ')',
            ['SynthesisStep', 'SynthesisCondition', 'SynthesisInput'] + list(keys))
        for r in rows:
            r['attributes'] = json.loads(r.pop('attrs_json'))
        return rows

    def build_evidence_subgraph(self, node_ids):
        ids = sorted(set(node_ids))
        if not ids:
            return {'nodes': [], 'edges': []}
        # Induced graph: no paper-level co-occurrence added as a scientific path.
        edges = self.query('build_evidence_subgraph',
            'SELECT * FROM edges WHERE source_supported=1 AND source IN (' + ','.join('?' for _ in ids) + ') AND target IN (' + ','.join('?' for _ in ids) + ')', ids+ids)
        for e in edges:
            e['attributes'] = json.loads(e.pop('attrs_json'))
        return {'nodes': self.nodes_by_ids(ids), 'edges': edges}


def evidence_is_resolved(record, evidence_ids):
    return bool(record.get('evidence_id')) and 'Evidence:' + record['evidence_id'] in evidence_ids


def strict_record(record, evidence_ids):
    return (record['strict_ready'] == 1 and record['source_supported'] == 1
            and record['verification_status'] == 'AUTO_PDF_CONFIRMED'
            and record['attribution_status'].startswith('EXPLICIT_PDF')
            and bool(record['material_id']) and evidence_is_resolved(record, evidence_ids))


def missing_protocol(rows):
    keys = ['testing_configuration', 'electrolyte', 'voltage_window', 'capacitance_mass_basis']
    result = {k: sum(not r.get(k) for r in rows) for k in keys}
    result['current_density_and_scan_rate'] = sum(not r.get('current_density') and not r.get('scan_rate') for r in rows)
    return result


def retrieve_same_sample_pairs(temperatures, capacitances):
    by_key = collections.defaultdict(list)
    for r in temperatures:
        by_key[r['material_key']].append(r)
    return [(t, p) for p in capacitances for t in by_key[p['material_key']]]


def parse_question(question):
    import re
    text = question.lower()
    biomass = bool(re.search(r'biomass|bio-derived|gelatin|生物质|明胶', text))
    synthesis = bool(re.search(r'design|synthesi|strategy|pathway|制备|合成|设计', text))
    temp = bool(re.search(r'carboni[sz]ation|pyrolysis|碳化', text)) and bool(re.search(r'temperatur|温度', text))
    capacitance = bool(re.search(r'capacitance|比电容|电容', text))
    if biomass and synthesis:
        intent = 'biomass_design'
    elif temp and capacitance:
        intent = 'temperature_capacitance'
    else:
        intent = 'property_evidence'
    aliases = {
        'BET_SSA_m2_g': r'\bbet\b|surface area|比表面积',
        'specific_capacitance_F_g': r'capacitance|比电容',
        'carbonization_temperature_C': r'carboni[sz]ation|pyrolysis|碳化',
        'activation_temperature_C': r'activation temperature|活化温度',
        'activating_agent': r'activat|活化', 'carbon_precursor': r'precursor|biomass|前驱体|生物质',
        'pore_volume_cm3_g': r'pore volume|孔容', 'pore_size_nm': r'pore size|孔径',
        'energy_density_Wh_kg': r'energy density|能量密度',
        'power_density_W_kg': r'power density|功率密度',
        'capacitance_retention_percent': r'retention|cycling|循环|保持率',
    }
    fields = [k for k, pattern in aliases.items() if re.search(pattern, text)]
    return dict(intent=intent, mapped_fields=fields, biomass_required=biomass)


def classify_biomass(name):
    """Conservative lexical screen; unknown origins remain unknown, never inferred."""
    import re
    name = name.lower().strip()
    if re.search(r'gelatin|chitosan|chitin|human hair|bone|silk|fish|egg|animal|collagen|feather', name):
        return 'animal_or_marine_biopolymer'
    if re.search(r'lignin|cellulose|starch|rice husk|rice straw|wheat straw|bagasse|bamboo|sawdust|wood|cotton|shell|peel|cattail|waste tea|leaf|leaves|corncob|corn cob|hemp|flour|potato|yam|seaweed|algae', name):
        return 'plant_or_algal_biomass'
    if re.search(r'EDTA|edta|resorcinol|formaldehyde|phenol|polyacrylonitrile|zif-|graphene|melamine|aniline|pyrrole|coal|pitch|lignite', name):
        return 'non_biomass_or_synthetic'
    return 'origin_unresolved'
