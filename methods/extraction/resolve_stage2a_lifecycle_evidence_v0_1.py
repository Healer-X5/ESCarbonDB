#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import jsonschema


VERSION = (
    "stage2a_lifecycle_evidence_resolver_v0_1_20261006"
)


def load(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def write(path: Path, obj):
    path.write_text(
        json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def sha(path: Path):
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def resolve_material(record):
    production = record[
        "production_evidence"
    ]

    preexisting = record[
        "preexisting_evidence"
    ]

    ambiguity = record[
        "ambiguity_evidence"
    ]

    p = len(production)
    e = len(preexisting)

    if p > 0 and e == 0:
        status = "produced_in_graph"
        reason_code = (
            "POSITIVE_PRODUCTION_EVIDENCE"
        )

    elif p == 0 and e > 0:
        status = "external_or_preexisting"
        reason_code = (
            "POSITIVE_PREEXISTING_EVIDENCE"
        )

    elif p > 0 and e > 0:
        status = "unresolved"
        reason_code = (
            "CONFLICTING_LIFECYCLE_EVIDENCE"
        )

    else:
        status = "unresolved"
        reason_code = (
            "INSUFFICIENT_LIFECYCLE_EVIDENCE"
        )

    return {
        "stage1_material_ref":
            record[
                "stage1_material_ref"
            ],

        "material_status":
            status,

        "reason_code":
            reason_code,

        "production_evidence_count":
            p,

        "preexisting_evidence_count":
            e,

        "ambiguity_evidence_count":
            len(ambiguity),

        "production_evidence_refs":
            sorted({
                x[
                    "evidence_ref"
                ]
                for x in production
            }),

        "preexisting_evidence_refs":
            sorted({
                x[
                    "evidence_ref"
                ]
                for x in preexisting
            }),

        "ambiguity_evidence_refs":
            sorted({
                x[
                    "evidence_ref"
                ]
                for x in ambiguity
            }),
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--evidence",
        required=True,
    )

    parser.add_argument(
        "--schema",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    args = parser.parse_args()

    evidence_path = Path(
        args.evidence
    )

    schema_path = Path(
        args.schema
    )

    output_path = Path(
        args.output
    )

    evidence = load(
        evidence_path
    )

    schema = load(
        schema_path
    )

    jsonschema.Draft202012Validator(
        schema
    ).validate(
        evidence
    )

    material_evidence = evidence[
        "material_evidence"
    ]

    # Release structural schema accepts different paper-specific material maps.
    # The key and the explicit reference must still identify the same material.
    for material_ref, record in material_evidence.items():
        if material_ref != record["stage1_material_ref"]:
            raise ValueError("Material map key and stage1_material_ref disagree")

    resolved = {
        material_ref:
            resolve_material(
                material_evidence[
                    material_ref
                ]
            )
        for material_ref in sorted(
            material_evidence
        )
    }

    result = {
        "resolver_version":
            VERSION,

        "paper_id":
            evidence[
                "paper_id"
            ],

        "source_evidence_sha256":
            sha(
                evidence_path
            ),

        "schema_sha256":
            sha(
                schema_path
            ),

        "material_status":
            resolved,
    }

    write(
        output_path,
        result,
    )

    counts = {}

    for item in resolved.values():
        status = item[
            "material_status"
        ]

        counts[
            status
        ] = (
            counts.get(
                status,
                0,
            )
            + 1
        )

    print(
        "resolver_version =",
        VERSION,
    )

    print(
        "status_counts =",
        counts,
    )

    print(
        "output =",
        output_path,
    )

    print(
        "output_sha256 =",
        sha(
            output_path
        ),
    )

    print(
        "STAGE2A_LIFECYCLE_RESOLVER=PASS"
    )


if __name__ == "__main__":
    main()
