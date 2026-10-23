"""Original KG2 field and explicit-protocol compatibility rules.

These are method excerpts, not a reconstruction pipeline. Full reconstruction also
requires the preserved KG1 snapshot and richer V4 curation/evidence tables.
"""
import json, re, math, unicodedata

def num(x):
    try:
        y=float(x);return y if math.isfinite(y) else None
    except (ValueError,TypeError):return None

PROP = {'BET_SSA':'BET_SSA_m2_g','BET_SPECIFIC_SURFACE_AREA':'BET_SSA_m2_g',
        'PORE_VOLUME':'pore_volume_cm3_g','PORE_SIZE':'pore_size_nm','SPECIFIC_CAPACITANCE':'specific_capacitance_F_g',
        'CYCLE_RETENTION':'capacitance_retention_percent','CYCLING_RETENTION':'capacitance_retention_percent',
        'CAPACITY_RETENTION':'capacity_retention_percent','CYCLING_RETENTION_TYPE_UNSPECIFIED':'cycling_retention_percent_type_unspecified',
        'SURFACE_AREA_METHOD_UNSPECIFIED':'surface_area_m2_g_method_unspecified','ELECTROCHEMICAL_SURFACE_AREA':'electrochemical_surface_area_m2_g',
        'ENERGY_DENSITY':'energy_density_Wh_kg','POWER_DENSITY':'power_density_W_kg','AREAL_CAPACITANCE':'areal_capacitance',
        'COULOMBIC_EFFICIENCY':'coulombic_efficiency_percent','CAPACITANCE_LOSS':'capacitance_loss_percent'}

def protocol_compatible(field,a,b):
    """Compare explicit protocol tokens without inventing missing units/conditions."""
    if not a or not b:return True
    def norm(v):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(v)).casefold().replace('−','-').replace('–','-'))
    aa,bb=norm(a),norm(b)
    if aa==bb:return True
    if field=='testing_configuration':
        def cfg(v):
            if re.search(r'(three|3)[-_ ]?electrode',v):return 'three'
            if re.search(r'(two|2)[-_ ]?electrode',v):return 'two'
            return v
        return cfg(aa)==cfg(bb)
    if field=='cycle_count':
        def cycles(v):
            hit=re.match(r'^([\d,]+)',v);n=num(hit[1].replace(',','')) if hit else None
            return n if n and n>0 else None
        ca,cb=cycles(aa),cycles(bb)
        # Zero/000 is an invalid parsed cycle count, not a contradictory known protocol.
        return ca is None or cb is None or ca==cb
    if field in ['current_density','scan_rate']:
        def rate(v):
            hit=re.fullmatch(r'([+]?[\d.]+)([a-z/°^−+\-0-9.]*)',v)
            if not hit:return None
            value=num(hit[1]);unit=hit[2].replace('g-1','/g').replace('g^-1','/g').replace('s-1','/s').replace('s^-1','/s')
            return value,unit
        ra,rb=rate(aa),rate(bb)
        if ra and rb:
            return ra[0]==rb[0] and (not ra[1] or not rb[1] or ra[1]==rb[1])
    return False

def field(n):
    a=json.loads(n['attrs_json'])
    return PROP.get(a.get('property_name'),a.get('property_name','')) if n['type']=='Measurement' else a.get('target_field','')
