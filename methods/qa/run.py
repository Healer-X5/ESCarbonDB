#!/usr/bin/env python3
"""Release adapter for preserved SQLite QA methods; no LLM/Neo4j replay is claimed."""
from pathlib import Path
import argparse
import json
from retrieval import GraphStore
from analysis import analyze_temperature_capacitance, recommend_biomass_synthesis


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', type=Path, required=True)
    p.add_argument('--task', choices=['temperature', 'design', 'inventory'], required=True)
    a = p.parse_args()
    if not a.database.is_file(): p.error('An independently supplied complete SQLite graph is required')
    store = GraphStore(a.database)
    try:
        if a.task == 'inventory': result = store.inventory()
        elif a.task == 'temperature':
            records = store.retrieve_property_observations(['carbonization_temperature_C', 'specific_capacitance_F_g'])
            result = analyze_temperature_capacitance(records, store.retrieve_evidence(records))
        else:
            precursors = store.retrieve_property_observations(['carbon_precursor'])
            keys = sorted({r['material_key'] for r in precursors})
            records = store.retrieve_property_observations(['carbon_precursor', 'activating_agent',
                'carbonization_temperature_C', 'activation_temperature_C', 'BET_SSA_m2_g',
                'specific_capacitance_F_g', 'activator_to_precursor_mass_ratio'], material_keys=keys)
            result = recommend_biomass_synthesis(precursors, records, store.retrieve_evidence(precursors + records))
        print(json.dumps({'scope':'SQLite method excerpt replay; external database required',
                          'result':result, 'executed_queries':store.actions}, indent=2, allow_nan=False))
    finally: store.db.close()

if __name__ == '__main__': main()
