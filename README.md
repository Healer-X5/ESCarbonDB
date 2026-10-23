# Large Language Models for Knowledge Reconstruction and Intelligent Design of Carbon Materials for Energy Storage

This repository contains an evidence-linked structured carbon-material database, a source-supported knowledge graph, essential scientific extraction methods, data analysis utilities, and knowledge-guided retrieval code. The research framework connects literature screening, schema-guided Qwen3-VL-235B extraction, terminology and unit normalization, sample attribution, evidence handling, and graph representation for porous-carbon electrodes in energy storage, particularly electric double-layer capacitors.

## Repository contents

```text
ESCarbonDB.xlsx                   Final sanitized scientific workbook (16 worksheets)
KnowledgeGraph/
  nodes.csv                      Public nodes and attributes
  edges.csv                      Directed relationships and attributes
  node_types.csv                 Public node-type definitions and counts
  edge_types.csv                 Public relationship-type definitions and counts
  scope.json                     Released graph scope and provenance conventions
methods/extraction/              Extraction implementations, prompts and lifecycle schema
methods/graph_rules.py           Scientific field and protocol mapping rules
methods/qa/                      SQLite retrieval, analysis and command-line adapter
scripts/escarbon.py              Workbook/graph inspection, validation, queries and summaries
schemas/
  workbook_schema.json           Actual worksheet columns and record counts
  graph_ontology.json            Scientific node and relationship definitions
  graph_quality_rules.json       Graph admission and observation policies
METHODS.md                       Scientific methods and reproducibility boundaries
LICENSE                          MIT License for original source code
LICENSE-DATA.md                  CC BY 4.0 notice for original research datasets
requirements.txt                 Python dependencies
.gitignore                       Local inputs and generated-output exclusions
SHA256SUMS.txt                    Checksums of every other released file
README.md                        This guide
```

## Installation and integrity

Use Python 3.13 (the release checks used Python 3.13.5). Run the commands below from the repository root.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
sha256sum -c SHA256SUMS.txt
```

## ESCarbonDB

Open `ESCarbonDB.xlsx` in a spreadsheet application or read it with `openpyxl`. The workbook covers 5,728 publications and 25,721 paper-scoped material records. Publications, materials, measurements, synthesis inputs, electrochemical tests and evidence are linked through their recorded identifiers. Material IDs must be interpreted with their paper IDs; material names and aliases alone do not establish identity across publications.

Scientific fields include precursors and activating agents, carbonization and activation temperatures, BET specific surface area, pore volume and pore size, capacitance, energy/power density, cycling retention, input amounts and activator-to-precursor ratios. Measurement values retain their units, sample attribution, test conditions and source references. Unassigned measurements remain distinct from measurements linked to a material.

| Worksheet | Records excluding header |
|---|---:|
| Summary | 6 |
| Papers | 5,728 |
| Materials | 25,721 |
| Material_Coverage | 25,721 |
| Measurements | 78,471 |
| Unassigned_Measurements | 65,837 |
| Target_Field_Facts | 97,782 |
| Curated_Facts | 776 |
| Analysis_Ready | 175 |
| MaterialAliases | 63,305 |
| Synthesis_Input_Amounts | 3,158 |
| ElectrochemicalTests | 375 |
| Activator_Precursor_Ratios | 1,185 |
| Evidence | 76,148 |
| Data_Dictionary | 77 |
| Lifecycle | 25,418 |

`Curated_Facts` and `Analysis_Ready` are narrower curation scopes, not counts of independent experiments. The strict worksheet spans 63 publications and 130 material keys. The corrected `Data_Dictionary` retains 77 applicable definitions; it is partial, while `schemas/workbook_schema.json` lists every distributed column.

The sanitized workbook is preserved without changing scientific values, identifiers, units or relationships. Designated source-quotation fields contain a notice; paper, evidence, page and block identifiers remain. Portable `source-record:` labels identify provenance and are not downloadable files. Two preserved source characteristics matter for reuse: `Summary.facts_assigned=19001` differs from the 19,185 target facts with nonempty `material_id`, and one duplicate `MaterialAliases.alias_id` group remains. Consumers should use the actual tables and should not assume alias IDs alone are unique.

```bash
python scripts/escarbon.py inspect
python scripts/escarbon.py validate
python scripts/escarbon.py statistics --output outputs/strict_summary
```

Validation scans workbook references and graph integrity. Statistics report field/unit counts, publication/material coverage and numeric ranges from `Analysis_Ready`; rows are facts and unlike electrochemical protocols are not pooled. Output paths must be new.

Example workbook access:

```python
from openpyxl import load_workbook
wb = load_workbook("ESCarbonDB.xlsx", read_only=True, data_only=True)
rows = iter(wb["Analysis_Ready"].values)
columns = next(rows)
capacitances = [dict(zip(columns, row)) for row in rows
               if row[columns.index("target_field")] == "specific_capacitance_F_g"]
print(len(capacitances))  # 5 facts; retain their testing conditions
wb.close()
```

## Public knowledge graph

The `source_supported` graph contains **66,862 nodes and 130,907 directed relationships**, representing 14 node types and 29 relationship types. `nodes.csv` uses unique `id` values with type, paper/material provenance and attributes; `edges.csv` uses unique `id` values, `source`, `target`, relationship `type` and attributes. `properties_json` retains structured scientific properties. The CSV type summaries describe this released scope. The ontology defines 14 node types and 31 possible relationship types; two relationship types are absent from the public scope.

Nodes represent papers, materials, aliases, measurements, scientific facts, evidence, synthesis inputs, substances, processes and related scientific entities. Relationships such as `FROM_PAPER`, `HAS_FACT`, `HAS_MEASUREMENT`, `SUPPORTED_BY`, `TESTED_UNDER` and `DERIVED_FROM` connect scientific records and their support. Automated source support is not blanket expert verification (`human_expert_verified=0`).

```bash
python scripts/escarbon.py validate
python scripts/escarbon.py query --paper-id PCSC_005407 --limit 3
python scripts/escarbon.py graphml --output outputs/source_supported.graphml
```

The GraphML command generates a local interchange file from the released CSV tables, preserving IDs, endpoints and CSV attributes. Open that directed graph in Gephi for visualization. A pre-generated GraphML copy and exact manuscript visualization layouts are not included; generated files may exceed ordinary Git file-size limits.

Example graph loading:

```python
import csv
import networkx as nx
G = nx.MultiDiGraph()
with open("KnowledgeGraph/nodes.csv", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        G.add_node(row.pop("id"), **row)
with open("KnowledgeGraph/edges.csv", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        key, source, target = row.pop("id"), row.pop("source"), row.pop("target")
        G.add_edge(source, target, key=key, **row)
print(G.number_of_nodes(), G.number_of_edges())  # 66862 130907
```

## Scientific methods and knowledge-guided retrieval

The extraction code preserves page navigation, PDF text blocks, the frozen Stage1 prompt, the production-navigation request implementation and response validation, lifecycle evidence contracts/resolution, alias evidence checks, and numerical candidate mining. Normalization and graph rules preserve sample identity, units, scientific conditions and evidence links. See `METHODS.md` for scope and provenance.

`navigation_v1_2.py` imports `navigation_v1_1.py`; the production-navigation runner imports `production_runtime_v1.py`, `pdf_blocks_v1.py` and `run_stage1_smoke_v0_5.py`. These versioned support modules remain necessary despite their historical filenames. `stage1_prompt.json`, `stage2a_template.json` and `stage2a_schema.json` retain the prompt and schema contracts; `sanitize_stage1_aliases_v1.py`, `resolve_stage2a_lifecycle_evidence_v0_1.py` and `quick_carbon_properties_v1.py` document distinct processing steps.

```bash
python methods/extraction/navigation_v1_2.py --help
python methods/extraction/run_stage1_cross_smoke_v0_5_prodnav_basev12.py --help
python methods/extraction/resolve_stage2a_lifecycle_evidence_v0_1.py --help
python methods/extraction/quick_carbon_properties_v1.py --help
```

Extraction requires authorized source PDFs, compatible frozen corpus/navigation/state inputs and external Qwen3-VL-235B inference infrastructure. `CARBON_SOURCE_ROOT` selects caller-supplied inputs and `CARBON_LLM_BASE_URL` selects the inference service. The generalized lifecycle schema must be instantiated with the actual material and source-block allowlists before inference.

`methods/qa/retrieval.py` and `analysis.py` preserve evidence retrieval, canonical observation handling, same-sample temperature–capacitance analysis and bounded biomass synthesis recommendations. `run.py` provides a read-only adapter. These SQLite methods require the separately supplied **complete SQLite knowledge graph**, including observation and scope tables; the five public graph files do not supply that workflow.

With a compatible external database, set `ESCARBON_KG_DATABASE` to its location and run:

```bash
python methods/qa/run.py --database "$ESCARBON_KG_DATABASE" --task temperature
python methods/qa/run.py --database "$ESCARBON_KG_DATABASE" --task design
```

Proposed synthesis conditions remain hypotheses requiring experimental validation.

## Scientific limitations

Original PDFs, verbatim source quotations, model weights, original inference/cache inputs and the complete SQLite graph are not distributed. Full extraction needs source documents and external model infrastructure; complete graph reconstruction and the original Neo4j/LLM case studies need additional inputs. Some manuscript figures require specific observation cohorts, source data or layout choices that are not supplied, so exact reproduction of every figure is not claimed. The manuscript reports an independent evaluation of information extraction performance; the underlying annotation records and evaluation scripts are not distributed in this repository.

## Citation and release

Use the project title above with the author-approved article citation and versioned repository identifier when available. The following publication metadata remain to be supplied:

- GitHub repository URL: **to be supplied after upload**.
- Article DOI and formal citation: **to be supplied when available**.
- Release version: **to be assigned by the authors**.

No separate graph deposit is asserted. The workbook and graph edge CSV exceed 25 MiB; use Git CLI or GitHub Desktop to upload the repository. Every released file is below 100 MiB.

## License

Original source code is licensed under the **MIT License**; see [LICENSE](LICENSE).

Original research datasets, including [ESCarbonDB.xlsx](ESCarbonDB.xlsx) and the original data in [KnowledgeGraph/](KnowledgeGraph/), are licensed under **Creative Commons Attribution 4.0 International (CC BY 4.0)**; see [LICENSE-DATA.md](LICENSE-DATA.md) and the [official legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en).

Third-party copyrighted content is not automatically relicensed. Third-party software and source-publication content retain their respective rights and applicable licenses.

The copyright notices use `2026 Jiang Wang and contributors`.
