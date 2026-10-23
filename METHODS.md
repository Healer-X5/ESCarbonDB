# Scientific Methods and Reproducibility

This document describes the extraction, structured database, evidence representation, graph rules and scientific analysis retained in the public release. The final sanitized workbook and source-supported graph CSV tables are preserved; the release utilities inspect and export these data without reconstructing the original literature-mining platform.

## Schema-guided scientific extraction

The research workflow uses Qwen3-VL-235B with PDF-page images and deterministic text blocks. `navigation_v1_2.py` reuses the PDF backend and semantic signals in `navigation_v1_1.py`, then applies the retained page qualification/ranking rules. `pdf_blocks_v1.py` records page/block identity and supplies source text for requests and evidence references. Optional `pdftotext` navigation requires that external executable; the PyMuPDF backend is available through the Python requirements.

`stage1_prompt.json` preserves the frozen entity/sample census prompt. It distinguishes material samples, starting materials and synthesis participants, retains explicit sample identities, and requires source block/page references. The prompt does not infer a sample-code parameter from its suffix. The production-navigation request implementation is `run_stage1_cross_smoke_v0_5_prodnav_basev12.py`; it imports the structural validator from `run_stage1_smoke_v0_5.py`, block utilities from `pdf_blocks_v1.py`, and parsing/runtime support from `production_runtime_v1.py`. These imported modules are functional method dependencies. Their versioned filenames are retained to preserve the scientific implementation.

`stage2a_template.json` preserves the lifecycle evidence task and its production, preexisting and ambiguity channels. `stage2a_schema.json` is the previously prepared structural generalization of the per-paper contract: fixed paper/material/block allowlists are omitted from the distributed template, while scientific evidence fields and enums remain. Callers must separately instantiate and validate actual frozen-material and source-block allowlists before inference. `resolve_stage2a_lifecycle_evidence_v0_1.py` validates evidence structure, checks material-key/reference agreement, and applies the retained lifecycle resolution rules. Family evidence requires explicit source support rather than inferred code similarity.

`sanitize_stage1_aliases_v1.py` checks candidate alias phrases against source blocks. `quick_carbon_properties_v1.py` mines numerical property candidates from frozen text-block caches with recorded context and provenance. The workflow therefore includes deterministic text processing alongside multimodal model requests; the release does not imply that every database cell is a direct model response.

Retained scientific navigation, block, lifecycle, alias, contract, retrieval and analysis functions preserve the implementations checked in the preceding release. Portable input adapters and the read-only public CLI are release-support components. No model inference is needed for workbook inspection, graph validation or descriptive summaries.

## Normalization and database representation

The retained text-processing code applies Unicode and typographic normalization to source strings and recognizes explicit scientific units and context. Original values and units, normalized values, property identity, material stage and test conditions remain separate where present in the final workbook. Gravimetric and areal capacitance, carbonization and activation, and different electrochemical protocols must retain their recorded meanings. Missing units, sample attribution or conditions are not a basis for inventing scientific equivalence.

`ESCarbonDB.xlsx` organizes publications, paper-scoped material records, measurements, target-field facts, synthesis input amounts, electrochemical tests, activator/precursor ratios, lifecycle records and evidence. The workbook includes 16 worksheets. `Unassigned_Measurements` preserves observations without resolved material attribution. `Curated_Facts` contains 776 records; its `Analysis_Ready` subset contains 175 facts across 63 publications and 130 material keys. These are recorded curation scopes and are not interchangeable with the complete candidate database or independent experiments.

Publication/material/source-measurement identifiers provide the checked cross-table references. A material is scoped by its paper and material IDs. Alias strings alone do not merge samples. The preserved source workbook contains one duplicate alias-ID group and a source-summary counting difference documented in the README; neither is silently corrected in this release.

`schemas/workbook_schema.json` enumerates the actual columns and record counts of all released worksheets. The corrected `Data_Dictionary` retains 77 definitions applicable to present tables and columns; it is a partial dictionary. Scientific values, experimental conditions, identifiers, units, worksheet order and the corrected dictionary are unchanged from the previously sanitized workbook.

## Knowledge representation and graph rules

The public graph is the existing `source_supported` scope: 66,862 nodes and 130,907 directed edges. Node and edge identifiers, endpoints and nonlocator scientific attributes are retained. `node_types.csv` and `edge_types.csv` describe the 14 node types and 29 relationship types represented in these CSV files. `schemas/graph_ontology.json` defines 14 node types and 31 possible relationship types; the broader ontology does not imply that every type occurs in this public scope.

`methods/graph_rules.py` preserves scientific field mappings and checks for conflicts in explicit testing configurations, cycle counts, current densities and scan rates, using the previously prepared local numerical helper. Unknown conditions do not establish complete protocol equivalence. This file is a method excerpt; complete graph construction also requires the original graph snapshot and richer curation/reconciliation inputs.

`schemas/graph_quality_rules.json` records stable identity, source-supported admission, curated/strict membership and canonical observation principles. Paper-scoped material identities and source references are retained; aliases do not merge samples. Observation consolidation requires explicit pointers and agreement in paper, material, property, value, unit and known protocol/recipe context. Equal numbers alone do not establish the same observation. Synthesis ratios retain denominator material/stage, ratio direction and synthesis-step scope.

Automated source support is distinct from expert verification (`human_expert_verified=0`). The complete candidate SQLite graph is outside this release. `scope.json` describes the public scope and provenance conventions; no public deposit of the complete graph is asserted.

## Evidence handling

Paper, evidence, page and block identifiers preserve the links needed for authorized source inspection. Designated source quotations and private locators were sanitized in the preceding release. The public workbook and graph retain those sanitized representations, including portable `source-record:` provenance labels. These labels do not identify bundled PDFs or downloadable source resources. Scientific evidence links do not by themselves confer access or redistribution rights to source publications.

## Scientific analysis and knowledge-guided retrieval

`scripts/escarbon.py` supplies workbook inspection, reference checks, graph identifier/endpoint checks, graph queries, descriptive strict-scope statistics and GraphML export. The statistics command groups `Analysis_Ready` facts by field and unit, reporting counts, publication/material coverage and finite numeric ranges. These summaries do not establish causal trends or pool incompatible measurement protocols.

The GraphML command loads the public CSV graph as a directed multigraph and preserves CSV attributes and edge IDs. It creates a local derivative for tools such as Gephi; no additional graph copy is bundled. The public CSV graph can be inspected and validated without the complete SQLite graph.

`methods/qa/retrieval.py` preserves read-only canonical-observation/evidence retrieval, protocol checks and same-sample pairing. `analysis.py` contains temperature–capacitance analysis and bounded biomass synthesis recommendations. `run.py` exposes these method excerpts through a command-line adapter. They require the complete external SQLite database, including canonical observations, membership and scope tables that are absent from the public CSV export. They do not reproduce the full original Neo4j/LLM reasoning agent or its generated scientific narratives. Proposed synthesis conditions require experimental validation.

## Reproducibility boundaries

The released workbook, graph and schemas support the documented public inspection, validation, query, descriptive-statistics and GraphML workflows. Source PDFs, original frozen corpus/navigation/state inputs and external model infrastructure are required for extraction. Whole-corpus normalization, targeted source curation, full graph reconstruction, complete SQLite retrieval and exact manuscript figure cohorts/layouts require additional inputs. This release preserves essential methods and usable data without claiming complete reproduction of every scientific experiment or figure.
