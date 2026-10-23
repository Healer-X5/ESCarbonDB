"""Original Stage1 structural contract, extracted without changing function bodies.

The production-navigation runner supplies PAPER_ID and the actual source block/page
sets. Historical single-paper inference and unrelated I/O are deliberately omitted.
"""
import json
import re
PAPER_ID = ''

def recursively_has_key(
    obj,
    forbidden_key: str,
):
    if isinstance(obj, dict):
        if forbidden_key in obj:
            return True

        return any(
            recursively_has_key(
                value,
                forbidden_key,
            )
            for value in obj.values()
        )

    if isinstance(obj, list):
        return any(
            recursively_has_key(
                x,
                forbidden_key,
            )
            for x in obj
        )

    return False

def validate_v04(
    obj,
    *,
    valid_block_ids,
    visual_pages,
    source_pages,
):
    errors = []
    warnings = []

    if not isinstance(obj, dict):
        return {
            "valid": False,
            "errors": [
                "top level is not object"
            ],
            "warnings": [],
        }

    required = [
        "schema_version",
        "paper_id",
        "source_pages",
        "document_assessment",
        "materials",
        "starting_material_candidates",
        "chemical_participant_candidates",
        "sample_code_definitions",
        "uncertainties",
    ]

    for key in required:
        if key not in obj:
            errors.append(
                f"missing key: {key}"
            )

    if obj.get(
        "schema_version"
    ) != "stage1_entity_census_v0_5":
        errors.append(
            "schema_version mismatch"
        )

    if obj.get(
        "paper_id"
    ) != PAPER_ID:
        errors.append(
            "paper_id mismatch"
        )

    if recursively_has_key(
        obj,
        "evidence_text",
    ):
        errors.append(
            (
                "Model output contains forbidden "
                "evidence_text"
            )
        )

    if "evidence" in obj:
        errors.append(
            "Model output contains forbidden evidence array"
        )

    if set(
        obj.get(
            "source_pages",
            [],
        )
    ) != set(source_pages):
        errors.append(
            "source_pages mismatch"
        )

    list_groups = [
        "materials",
        "starting_material_candidates",
        "chemical_participant_candidates",
        "sample_code_definitions",
        "uncertainties",
    ]

    for group in list_groups:
        if not isinstance(
            obj.get(group),
            list,
        ):
            errors.append(
                f"{group} is not list"
            )

    if errors:
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
        }

    valid_block_ids = set(
        valid_block_ids
    )

    visual_pages = set(
        visual_pages
    )

    all_ids = set()

    specs = {
        "materials":
            (
                "candidate_id",
                r"^MAT_C\d{3}$",
            ),

        "starting_material_candidates":
            (
                "candidate_id",
                r"^START_C\d{3}$",
            ),

        "chemical_participant_candidates":
            (
                "candidate_id",
                r"^CHEM_C\d{3}$",
            ),

        "sample_code_definitions":
            (
                "candidate_id",
                r"^SC_C\d{3}$",
            ),

        "uncertainties":
            (
                "uncertainty_id",
                r"^U_C\d{3}$",
            ),
    }

    ids_by_group = {}

    for group, (
        id_field,
        pattern,
    ) in specs.items():

        group_ids = set()

        for i, record in enumerate(
            obj[group]
        ):
            if not isinstance(
                record,
                dict,
            ):
                errors.append(
                    (
                        f"{group}[{i}] "
                        "not object"
                    )
                )
                continue

            rid = record.get(
                id_field
            )

            if not isinstance(
                rid,
                str,
            ) or not re.match(
                pattern,
                rid,
            ):
                errors.append(
                    (
                        f"{group}[{i}] "
                        f"bad {id_field}={rid!r}"
                    )
                )
                continue

            if rid in all_ids:
                errors.append(
                    f"duplicate id {rid}"
                )

            all_ids.add(rid)
            group_ids.add(rid)

        ids_by_group[
            group
        ] = group_ids

    material_ids = (
        ids_by_group[
            "materials"
        ]
    )

    def validate_support(
        record,
        location,
    ):
        refs = record.get(
            "evidence_block_refs",
            [],
        )

        vis = record.get(
            "visual_support_pages",
            [],
        )

        if not isinstance(refs, list):
            errors.append(
                (
                    f"{location}.evidence_block_refs "
                    "not list"
                )
            )
            refs = []

        if not isinstance(vis, list):
            errors.append(
                (
                    f"{location}.visual_support_pages "
                    "not list"
                )
            )
            vis = []

        for ref in refs:
            if ref not in valid_block_ids:
                errors.append(
                    (
                        f"{location} invalid "
                        f"block ref {ref}"
                    )
                )

        for page in vis:
            if page not in visual_pages:
                errors.append(
                    (
                        f"{location} invalid "
                        f"visual page {page}"
                    )
                )

        return refs, vis

    # --------------------------------------------------------------
    # Document assessment
    # --------------------------------------------------------------

    assessment = obj.get(
        "document_assessment"
    )

    if not isinstance(
        assessment,
        dict,
    ):
        errors.append(
            "document_assessment not object"
        )

    else:
        allowed_tri = {
            "YES",
            "NO",
            "UNCLEAR",
        }

        for key in [
            "experimental_material_entities_present",
            "synthesis_or_preparation_present",
            "sample_series_or_codes_present",
            "explicit_chemical_participants_present",
        ]:
            if assessment.get(
                key
            ) not in allowed_tri:
                errors.append(
                    (
                        "document_assessment."
                        f"{key} invalid"
                    )
                )

        refs = assessment.get(
            "assessment_block_refs",
            [],
        )

        vis = assessment.get(
            "visual_support_pages",
            [],
        )

        if not isinstance(refs, list):
            errors.append(
                "assessment_block_refs not list"
            )
            refs = []

        if not isinstance(vis, list):
            errors.append(
                "assessment visual_support_pages not list"
            )
            vis = []

        for ref in refs:
            if ref not in valid_block_ids:
                errors.append(
                    (
                        "assessment invalid "
                        f"block ref {ref}"
                    )
                )

        for page in vis:
            if page not in visual_pages:
                errors.append(
                    (
                        "assessment invalid "
                        f"visual page {page}"
                    )
                )

    # --------------------------------------------------------------
    # Materials
    # --------------------------------------------------------------

    allowed_states = {
        "FINAL_SAMPLE",
        "INTERMEDIATE_MATERIAL",
        "CONTROL_OR_REFERENCE",
        "ELECTRODE_OR_COMPOSITE",
        "UNCLEAR",
    }

    for i, record in enumerate(
        obj["materials"]
    ):
        validate_support(
            record,
            f"materials[{i}]",
        )

        if record.get(
            "material_state"
        ) not in allowed_states:
            errors.append(
                (
                    f"materials[{i}] "
                    "invalid material_state"
                )
            )

        if not str(
            record.get(
                "name_raw",
                "",
            )
        ).strip():
            errors.append(
                (
                    f"materials[{i}] "
                    "empty name_raw"
                )
            )

        codes = record.get(
            "sample_codes"
        )

        if not isinstance(
            codes,
            list,
        ):
            errors.append(
                (
                    f"materials[{i}] "
                    "sample_codes not list"
                )
            )

    # --------------------------------------------------------------
    # Starting materials
    # --------------------------------------------------------------

    for i, record in enumerate(
        obj[
            "starting_material_candidates"
        ]
    ):
        validate_support(
            record,
            (
                "starting_material_candidates"
                f"[{i}]"
            ),
        )

    # --------------------------------------------------------------
    # Chemical participants
    # --------------------------------------------------------------

    allowed_roles = {
        "ACTIVATOR",
        "DOPANT_SOURCE",
        "TEMPLATE_OR_CATALYST",
        "ACID_BASE",
        "SYNTHESIS_SOLVENT",
        "WASHING_AGENT",
        "OTHER_SYNTHESIS_PARTICIPANT",
        "UNCLEAR",
    }

    for i, record in enumerate(
        obj[
            "chemical_participant_candidates"
        ]
    ):
        validate_support(
            record,
            (
                "chemical_participant_candidates"
                f"[{i}]"
            ),
        )

        if record.get(
            "role_hint"
        ) not in allowed_roles:
            errors.append(
                (
                    "chemical_participant_candidates"
                    f"[{i}] invalid role_hint"
                )
            )

    # --------------------------------------------------------------
    # Sample-code definitions
    #
    # Stage 1 V0.5 HARD BOUNDARY:
    # semantic interpretation is deferred to Stage 3.
    # --------------------------------------------------------------

    if obj["sample_code_definitions"] != []:
        errors.append(
            (
                "Stage1 V0.5 requires "
                "sample_code_definitions == []"
            )
        )

    for i, record in enumerate(
        obj[
            "sample_code_definitions"
        ]
    ):
        validate_support(
            record,
            (
                "sample_code_definitions"
                f"[{i}]"
            ),
        )

        mapped = record.get(
            "mapped_material_candidate_id"
        )

        if (
            mapped is not None
            and mapped
            not in material_ids
        ):
            errors.append(
                (
                    f"sample_code_definitions[{i}] "
                    f"invalid material {mapped}"
                )
            )

        params = record.get(
            "encoded_parameters"
        )

        if not isinstance(
            params,
            list,
        ):
            errors.append(
                (
                    f"sample_code_definitions[{i}] "
                    "encoded_parameters not list"
                )
            )

            continue

        for j, parameter in enumerate(
            params
        ):
            if not isinstance(
                parameter,
                dict,
            ):
                errors.append(
                    (
                        "encoded parameter "
                        f"{i}/{j} not object"
                    )
                )
                continue

            refs = parameter.get(
                "parameter_evidence_block_refs"
            )

            if not isinstance(
                refs,
                list,
            ) or not refs:
                errors.append(
                    (
                        "encoded parameter "
                        f"{i}/{j} lacks direct "
                        "block evidence"
                    )
                )
                continue

            for ref in refs:
                if ref not in valid_block_ids:
                    errors.append(
                        (
                            "encoded parameter "
                            f"{i}/{j} invalid "
                            f"block ref {ref}"
                        )
                    )

    # --------------------------------------------------------------
    # Uncertainties
    # --------------------------------------------------------------

    for i, record in enumerate(
        obj["uncertainties"]
    ):
        validate_support(
            record,
            f"uncertainties[{i}]",
        )

    return {
        "valid":
            len(errors) == 0,

        "errors":
            errors,

        "warnings":
            warnings,
    }

def collect_all_block_refs(obj):
    refs = set()

    assessment = obj.get(
        "document_assessment",
        {},
    )

    refs.update(
        assessment.get(
            "assessment_block_refs",
            [],
        )
    )

    for group in [
        "materials",
        "starting_material_candidates",
        "chemical_participant_candidates",
        "sample_code_definitions",
        "uncertainties",
    ]:
        for record in obj.get(
            group,
            [],
        ):
            refs.update(
                record.get(
                    "evidence_block_refs",
                    [],
                )
            )

            if group == "sample_code_definitions":
                for p in record.get(
                    "encoded_parameters",
                    [],
                ):
                    refs.update(
                        p.get(
                            "parameter_evidence_block_refs",
                            [],
                        )
                    )

    return sorted(refs)
