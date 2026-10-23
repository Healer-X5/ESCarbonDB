#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import gzip
import json
import sqlite3
import sys
from pathlib import Path
import os

import pandas as pd
import pymupdf
import requests


ROOT = Path(os.environ.get("CARBON_SOURCE_ROOT", "inputs/production"))

CODE = Path(__file__).resolve().parent

sys.path.insert(
    0,
    str(CODE),
)

import production_runtime_v1 as rt
import pdf_blocks_v1 as pb
import run_stage1_smoke_v0_5 as base


CORPUS = (
    ROOT
    / "00_freeze/corpus/"
    "PRODUCTION_NON_GOLD_ELIGIBLE_5728_V1.tsv"
)

PROMPT_BUNDLE = CODE / "stage1_prompt.json"

PRODUCTION_DB = (
    ROOT
    / "01_state/"
    "production_state.sqlite"
)

NAV_DIR = (
    ROOT
    / "09_reports/"
    "../02_navigation_cache"
)


EXPECTED_PROMPT_SHA256 = "7f71c8f8349cffd211ca2d4f6f69e46df22ae36ad5cd75d1cb6fe1073aa5e62b"

EXPECTED_BLOCK_CODE_SHA256 = (
    "438f84aa337686bd8743af9448937e18"
    "80d8d3b128a765ed178c332bf174b47e"
)


def require(
    cond,
    message,
):
    if not cond:
        raise RuntimeError(
            message
        )


def production_counts():
    con = sqlite3.connect(PRODUCTION_DB.resolve().as_uri() + "?mode=ro", uri=True)

    try:
        return {
            "papers":
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM paper_state
                    """
                ).fetchone()[0],

            "calls":
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM call_log
                    """
                ).fetchone()[0],

            "hard":
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM hard_case_queue
                    """
                ).fetchone()[0],

            "events":
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM event_log
                    """
                ).fetchone()[0],
        }

    finally:
        con.close()


def png_data_url(
    path: Path,
) -> str:
    return (
        "data:image/png;base64,"
        + base64.b64encode(
            path.read_bytes()
        ).decode("ascii")
    )


def render_pages(
    pdf: Path,
    pages: list[int],
    dpi: int,
    out_dir: Path,
    paper_id: str,
):
    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    doc = pymupdf.open(
        pdf
    )

    outputs = {}

    try:
        for page_pdf in pages:
            page = doc[
                page_pdf - 1
            ]

            pix = page.get_pixmap(
                dpi=dpi,
                alpha=False,
            )

            out = (
                out_dir
                / (
                    f"{paper_id}_"
                    f"p{page_pdf:03d}_"
                    f"{dpi}dpi.png"
                )
            )

            pix.save(
                out
            )

            outputs[
                page_pdf
            ] = out

    finally:
        doc.close()

    return outputs


def derive_text_pages(
    candidate_pages: list[int],
    page_count: int,
    radius: int,
):
    wanted = {
        1
    }

    for page_pdf in candidate_pages:
        for q in range(
            page_pdf - radius,
            page_pdf + radius + 1,
        ):
            if (
                1
                <= q
                <= page_count
            ):
                wanted.add(q)

    return sorted(
        wanted
    )


def configure_base_globals(
    *,
    paper_id: str,
    smoke: Path,
):
    # base.validate_v04 uses PAPER_ID.
    base.PAPER_ID = (
        paper_id
    )

    base.PRODUCTION_DB = (
        PRODUCTION_DB
    )

    base.SMOKE = smoke

    base.SMOKE_DB = (
        smoke
        / "smoke_state.sqlite"
    )

    base.RENDER_DIR = (
        smoke
        / "rendered_pages"
    )

    base.BLOCK_CACHE = (
        smoke
        / "block_cache.json"
    )

    base.PARSED_OUT = (
        smoke
        / "stage1_parsed.json"
    )

    base.VALIDATION_OUT = (
        smoke
        / "stage1_validation.json"
    )

    base.MATERIALIZED_EVIDENCE_OUT = (
        smoke
        / "materialized_text_evidence.json"
    )

    base.ASSISTANT_CONTENT_OUT = (
        smoke
        / "assistant_content.txt"
    )


def generic_semantic_audit(
    parsed: dict,
    *,
    block_lookup: dict,
    materialized: list,
):
    errors = []
    warnings = []

    # --------------------------------------------------------------
    # Stage boundary
    # --------------------------------------------------------------

    if (
        parsed.get(
            "sample_code_definitions"
        )
        != []
    ):
        errors.append(
            (
                "Stage1 V0.5 requires "
                "sample_code_definitions == []"
            )
        )

    # --------------------------------------------------------------
    # Entity support
    # --------------------------------------------------------------

    for group in [
        "materials",
        "starting_material_candidates",
        "chemical_participant_candidates",
    ]:
        for i, record in enumerate(
            parsed.get(
                group,
                [],
            )
        ):
            refs = (
                record.get(
                    "evidence_block_refs"
                )
                or []
            )

            visual = (
                record.get(
                    "visual_support_pages"
                )
                or []
            )

            if (
                not refs
                and not visual
            ):
                errors.append(
                    (
                        f"{group}[{i}] "
                        "has no text-block or "
                        "visual support"
                    )
                )

    # --------------------------------------------------------------
    # Detect exact duplicate sample-code assignment
    # --------------------------------------------------------------

    code_owner = {}

    for material in parsed.get(
        "materials",
        [],
    ):
        mid = material.get(
            "candidate_id"
        )

        for code in (
            material.get(
                "sample_codes"
            )
            or []
        ):
            if code in code_owner:
                errors.append(
                    (
                        f"sample code {code!r} "
                        "assigned to multiple "
                        f"materials: "
                        f"{code_owner[code]}, "
                        f"{mid}"
                    )
                )

            else:
                code_owner[
                    code
                ] = mid

    # --------------------------------------------------------------
    # Materialized evidence must be exact programmatic block text
    # --------------------------------------------------------------

    for ev in materialized:
        bid = ev[
            "block_id"
        ]

        source = (
            block_lookup.get(
                bid
            )
        )

        if source is None:
            errors.append(
                (
                    "materialized unknown "
                    f"block {bid}"
                )
            )

            continue

        if (
            ev[
                "evidence_text"
            ]
            != source[
                "text"
            ]
        ):
            errors.append(
                (
                    f"{bid}: evidence "
                    "text mutated"
                )
            )

        if (
            ev[
                "text_sha256"
            ]
            != source[
                "text_sha256"
            ]
        ):
            errors.append(
                (
                    f"{bid}: evidence "
                    "SHA mismatch"
                )
            )

    return {
        "valid":
            len(errors) == 0,

        "errors":
            errors,

        "warnings":
            warnings,

        "material_count":
            len(
                parsed.get(
                    "materials",
                    [],
                )
            ),

        "starting_material_count":
            len(
                parsed.get(
                    "starting_material_candidates",
                    [],
                )
            ),

        "chemical_participant_count":
            len(
                parsed.get(
                    "chemical_participant_candidates",
                    [],
                )
            ),

        "sample_code_definition_count":
            len(
                parsed.get(
                    "sample_code_definitions",
                    [],
                )
            ),

        "distinct_sample_codes":
            len(
                code_owner
            ),

        "materialized_text_evidence_count":
            len(
                materialized
            ),
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--paper-id",
        required=True,
    )

    parser.add_argument(
        "--expected-tier",
        required=True,
        choices=[
            "LOW",
            "MED",
            "HIGH",
        ],
    )

    parser.add_argument(
        "--smoke-dir",
        required=True,
    )

    args = parser.parse_args()

    paper_id = (
        args.paper_id
        .strip()
        .upper()
    )

    expected_tier = (
        args.expected_tier
        .strip()
        .upper()
    )

    smoke = Path(
        args.smoke_dir
    )

    smoke.mkdir(
        parents=True,
        exist_ok=True,
    )

    configure_base_globals(
        paper_id=paper_id,
        smoke=smoke,
    )

    smoke_db = (
        smoke
        / "smoke_state.sqlite"
    )

    block_cache_path = (
        smoke
        / "block_cache.json"
    )

    parsed_out = (
        smoke
        / "stage1_parsed.json"
    )

    validation_out = (
        smoke
        / "stage1_validation.json"
    )

    materialized_out = (
        smoke
        / "materialized_text_evidence.json"
    )

    assistant_out = (
        smoke
        / "assistant_content.txt"
    )

    audit_out = (
        smoke
        / "generic_semantic_audit.json"
    )

    # --------------------------------------------------------------
    # Frozen identities
    # --------------------------------------------------------------

    require(
        rt.sha256_file(
            PROMPT_BUNDLE
        )
        ==
        EXPECTED_PROMPT_SHA256,
        (
            "V0.5 prompt hash changed."
        ),
    )

    require(
        rt.sha256_file(
            CODE
            / "pdf_blocks_v1.py"
        )
        ==
        EXPECTED_BLOCK_CODE_SHA256,
        (
            "pdf_blocks_v1.py "
            "hash changed."
        ),
    )

    # --------------------------------------------------------------
    # Production safety
    # --------------------------------------------------------------

    before = (
        production_counts()
    )

    require(
        before
        == {
            "papers": 5728,
            "calls": 0,
            "hard": 0,
            "events": 0,
        },
        (
            "Production DB dirty: "
            f"{before}"
        ),
    )

    # --------------------------------------------------------------
    # Corpus
    # --------------------------------------------------------------

    df = pd.read_csv(
        CORPUS,
        sep="\t",
    )

    rows = df[
        df["paper_id"]
        == paper_id
    ]

    require(
        len(rows) == 1,
        (
            f"Production corpus lookup "
            f"count={len(rows)} "
            f"for {paper_id}"
        ),
    )

    row = rows.iloc[0]

    actual_tier = (
        str(
            row[
                "c4b_stratum"
            ]
        )
        .strip()
        .upper()
    )

    require(
        actual_tier
        == expected_tier,
        (
            f"tier mismatch: "
            f"expected={expected_tier}, "
            f"actual={actual_tier}"
        ),
    )

    processing_order = int(
        row[
            "processing_order"
        ]
    )

    pdf = Path(
        row[
            "canonical_pdf_path"
        ]
    )

    require(
        pdf.is_file(),
        (
            f"Missing canonical PDF "
            f"{pdf}"
        ),
    )

    # --------------------------------------------------------------
    # Frozen Stage0 navigation
    # --------------------------------------------------------------

    nav_path = (
        NAV_DIR
        / (
            f"{paper_id}."
            "navigation.v1_2.json.gz"
        )
    )

    require(
        nav_path.is_file(),
        (
            "Missing frozen Stage0 "
            f"navigation: {nav_path}"
        ),
    )

    with gzip.open(
        nav_path,
        "rt",
        encoding="utf-8",
    ) as f:
        nav = json.load(f)

    require(
        nav[
            "paper_id"
        ]
        == paper_id,
        "Navigation paper mismatch",
    )

    require(
        nav[
            "navigation_version"
        ]
        ==
        "navigation_v1_2_20261006",
        (
            "Navigation version "
            "mismatch"
        ),
    )

    require(
        nav[
            "selected_text_metrics"
        ][
            "quality"
        ]
        == "GOOD",
        (
            "Navigation text quality "
            "not GOOD"
        ),
    )

    candidate_pages = list(
        nav[
            "candidate_pages_ranked"
        ]
    )

    require(
        len(candidate_pages) > 0,
        "No Stage0 candidate pages",
    )

    bundle = json.loads(
        PROMPT_BUNDLE.read_text(
            encoding="utf-8"
        )
    )

    radius = int(
        bundle[
            "render_candidate"
        ][
            "text_neighbor_radius"
        ]
    )

    page_count = int(
        nav[
            "selected_text_metrics"
        ][
            "page_count"
        ]
    )

    text_pages = (
        derive_text_pages(
            candidate_pages,
            page_count,
            radius,
        )
    )

    vision_cap = int(
        bundle[
            "render_candidate"
        ][
            "vision_candidate_cap"
        ]
    )

    vision_pages = (
        candidate_pages[
            :vision_cap
        ]
    )

    print(
        "paper_id =",
        paper_id,
    )

    print(
        "tier =",
        actual_tier,
    )

    print(
        "processing_order =",
        processing_order,
    )

    print(
        "pdf =",
        pdf,
    )

    print(
        "navigation_candidates =",
        candidate_pages,
    )

    print(
        "text_pages =",
        text_pages,
    )

    print(
        "vision_pages =",
        vision_pages,
    )

    # --------------------------------------------------------------
    # Deterministic block cache
    # --------------------------------------------------------------

    cache = (
        pb.extract_block_cache(
            pdf,
            text_pages,
        )
    )

    pb.write_cache(
        cache,
        block_cache_path,
    )

    lookup = (
        pb.block_lookup(
            cache
        )
    )

    block_text = (
        pb.prompt_block_text(
            cache,
            text_pages,
        )
    )

    print(
        "block_version =",
        cache[
            "block_version"
        ],
    )

    print(
        "block_count =",
        len(lookup),
    )

    # --------------------------------------------------------------
    # Prompt
    # --------------------------------------------------------------

    user_text = (
        bundle[
            "user_template"
        ]
        .format(
            paper_id=
                paper_id,

            source_pages_json=
                json.dumps(
                    text_pages
                ),

            block_text_block=
                block_text,

            vision_page_list=
                json.dumps(
                    vision_pages
                ),
        )
    )

    prompt_sha256 = (
        rt.sha256_text(
            bundle[
                "system_prompt"
            ]
            + "\n\n"
            + user_text
        )
    )

    input_sha256 = (
        rt.sha256_text(
            (
                cache[
                    "pdf_sha256"
                ]
                + "|"
                + cache[
                    "block_version"
                ]
                + "|"
                + ",".join(
                    str(x)
                    for x in text_pages
                )
                + "|"
                + ",".join(
                    str(x)
                    for x in vision_pages
                )
            )
        )
    )

    render_dpi = int(
        bundle[
            "render_candidate"
        ][
            "dpi"
        ]
    )

    rendered = (
        render_pages(
            pdf,
            vision_pages,
            render_dpi,
            smoke
            / "rendered_pages",
            paper_id,
        )
    )

    content = [
        {
            "type":
                "text",

            "text":
                user_text,
        }
    ]

    for page_pdf in vision_pages:
        content.append({
            "type":
                "text",

            "text":
                (
                    "VISUAL "
                    f"PAGE_PDF={page_pdf}"
                ),
        })

        content.append({
            "type":
                "image_url",

            "image_url": {
                "url":
                    png_data_url(
                        rendered[
                            page_pdf
                        ]
                    )
            },
        })

    cfg = bundle[
        "generation_candidate"
    ]

    payload = {
        "model":
            cfg[
                "model"
            ],

        "messages": [
            {
                "role":
                    "system",

                "content":
                    bundle[
                        "system_prompt"
                    ],
            },
            {
                "role":
                    "user",

                "content":
                    content,
            },
        ],

        "temperature":
            cfg[
                "temperature"
            ],

        "top_p":
            cfg[
                "top_p"
            ],

        "max_tokens":
            cfg[
                "max_tokens"
            ],

        "stream":
            False,
    }

    # --------------------------------------------------------------
    # Fresh isolated smoke DB
    # --------------------------------------------------------------

    require(
        not smoke_db.exists(),
        (
            "Smoke DB already exists. "
            "Do not rerun silently."
        ),
    )

    con = rt.connect_db(
        smoke_db
    )

    try:
        rt.init_db_schema(
            con
        )

        now = rt.utc_now()

        con.execute(
            """
            INSERT INTO paper_state(
                paper_id,
                processing_order,
                c4b_stratum,
                canonical_pdf_path,
                lifecycle_state,
                current_stage,
                attempt_count,
                navigation_version,
                navigation_sha256,
                prompt_bundle_version,
                runtime_version,
                created_at_utc,
                updated_at_utc
            )
            VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                paper_id,
                processing_order,
                actual_tier,
                str(pdf),
                "PENDING",
                "STAGE1_ENTITY_CENSUS",
                0,
                rt.NAVIGATION_VERSION,
                rt.NAVIGATION_SHA256,
                bundle[
                    "prompt_bundle_version"
                ],
                rt.RUNTIME_VERSION,
                now,
                now,
            ),
        )

        rt.set_meta(
            con,
            "purpose",
            (
                "STAGE1_V0_5_"
                "CROSS_SMOKE"
            ),
        )

        rt.set_meta(
            con,
            "prompt_bundle_sha256",
            EXPECTED_PROMPT_SHA256,
        )

        con.commit()

    finally:
        con.close()

    # --------------------------------------------------------------
    # vLLM identity
    # --------------------------------------------------------------

    health = requests.get(
        rt.VLLM_BASE_URL
        + "/health",
        timeout=20,
    )

    require(
        health.status_code
        == 200,
        "vLLM health failed",
    )

    models = requests.get(
        rt.VLLM_BASE_URL
        + "/v1/models",
        timeout=20,
    )

    require(
        models.status_code
        == 200,
        "/v1/models failed",
    )

    model_ids = [
        x.get("id")
        for x in (
            models.json()
            .get(
                "data",
                []
            )
        )
    ]

    require(
        "qwen3-vl-235b"
        in model_ids,
        (
            "qwen3-vl-235b "
            f"not served: {model_ids}"
        ),
    )

    # --------------------------------------------------------------
    # EXACTLY ONE CALL
    # --------------------------------------------------------------

    print()
    print("=" * 72)
    print(
        "STAGE1 V0.5 CROSS-SMOKE"
    )
    print(
        "EXACTLY ONE CHAT COMPLETION"
    )
    print("=" * 72)

    client = rt.VLLMClient(
        root=smoke,
        db_path=smoke_db,
        timeout_seconds=600,
    )

    result = client.call_chat(
        paper_id=paper_id,
        stage="STAGE1_ENTITY_CENSUS",
        attempt=1,
        payload=payload,
        prompt_sha256=prompt_sha256,
        input_sha256=input_sha256,
    )

    print(
        "call_id =",
        result[
            "call_id"
        ],
    )

    print(
        "http_status =",
        result[
            "http_status"
        ],
    )

    print(
        "finish_reason =",
        result[
            "finish_reason"
        ],
    )

    print(
        "usage =",
        result[
            "usage"
        ],
    )

    print(
        "latency_seconds =",
        result[
            "latency_seconds"
        ],
    )

    print(
        "raw_call_dir =",
        result[
            "call_dir"
        ],
    )

    require(
        result[
            "error_type"
        ]
        is None,
        (
            f"{result['error_type']}: "
            f"{result['error_message']}"
        ),
    )

    require(
        result[
            "http_status"
        ]
        == 200,
        "Non-200 HTTP",
    )

    assistant_content = (
        rt.extract_assistant_content(
            result[
                "response_json"
            ]
        )
    )

    require(
        isinstance(
            assistant_content,
            str,
        ),
        "No assistant content",
    )

    assistant_out.write_text(
        assistant_content,
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # Parse
    # --------------------------------------------------------------

    parsed_result = (
        rt.parse_json_conservative(
            assistant_content
        )
    )

    print(
        "parse_ok =",
        parsed_result.ok,
    )

    print(
        "parse_method =",
        parsed_result.method,
    )

    print(
        "parse_error =",
        parsed_result.error,
    )

    rt.update_call_parse_status(
        smoke_db,
        call_id=result[
            "call_id"
        ],
        parse_status=(
            (
                "PASS:"
                + parsed_result.method
            )
            if parsed_result.ok
            else
            (
                "FAIL:"
                + parsed_result.method
            )
        ),
    )

    require(
        parsed_result.ok,
        (
            "JSON parse failed: "
            f"{parsed_result.error}"
        ),
    )

    parsed = (
        parsed_result.value
    )

    parsed_out.write_text(
        json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # V0.5 structural contract
    # --------------------------------------------------------------

    validation = (
        base.validate_v04(
            parsed,
            valid_block_ids=(
                lookup.keys()
            ),
            visual_pages=(
                vision_pages
            ),
            source_pages=(
                text_pages
            ),
        )
    )

    validation_out.write_text(
        json.dumps(
            validation,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    con = rt.connect_db(
        smoke_db
    )

    try:
        con.execute(
            """
            UPDATE call_log
            SET validation_status=?
            WHERE call_id=?
            """,
            (
                (
                    "PASS"
                    if validation[
                        "valid"
                    ]
                    else
                    "FAIL"
                ),
                result[
                    "call_id"
                ],
            ),
        )

        con.commit()

    finally:
        con.close()

    print(
        "contract_valid =",
        validation[
            "valid"
        ],
    )

    print(
        "contract_errors =",
        validation[
            "errors"
        ],
    )

    print(
        "contract_warnings =",
        validation[
            "warnings"
        ],
    )

    require(
        validation[
            "valid"
        ],
        (
            "Stage1 V0.5 "
            "contract failed"
        ),
    )

    # --------------------------------------------------------------
    # Materialize exact cited blocks
    # --------------------------------------------------------------

    refs = (
        base.collect_all_block_refs(
            parsed
        )
    )

    materialized = []

    for i, ref in enumerate(
        refs,
        start=1,
    ):
        block = lookup[
            ref
        ]

        materialized.append({
            "evidence_id":
                f"EVB_{i:03d}",

            "block_id":
                ref,

            "page_pdf":
                block[
                    "page_pdf"
                ],

            "evidence_source":
                "TEXT_BLOCK",

            "evidence_text":
                block[
                    "text"
                ],

            "text_sha256":
                block[
                    "text_sha256"
                ],

            "bbox": [
                block["x0"],
                block["y0"],
                block["x1"],
                block["y1"],
            ],
        })

    materialized_out.write_text(
        json.dumps(
            materialized,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    # --------------------------------------------------------------
    # Generic semantic audit
    # --------------------------------------------------------------

    audit = generic_semantic_audit(
        parsed,
        block_lookup=lookup,
        materialized=materialized,
    )

    audit_out.write_text(
        json.dumps(
            audit,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(
        "GENERIC CROSS-SMOKE AUDIT"
    )
    print("=" * 72)

    print(
        json.dumps(
            audit,
            ensure_ascii=False,
            indent=2,
        )
    )

    # --------------------------------------------------------------
    # Production safety
    # --------------------------------------------------------------

    after = (
        production_counts()
    )

    require(
        after == before,
        (
            "Production DB changed\n"
            f"before={before}\n"
            f"after={after}"
        ),
    )

    print()
    print(
        "PRODUCTION_DB_UNCHANGED=PASS"
    )

    print(
        "production_counts =",
        after,
    )

    # --------------------------------------------------------------
    # Human/scientific review output
    # --------------------------------------------------------------

    print()
    print("=" * 72)
    print(
        "STAGE1 V0.5 CROSS-SMOKE SUMMARY"
    )
    print("=" * 72)

    print()
    print("Materials:")

    for x in parsed.get(
        "materials",
        [],
    ):
        print(
            " ",
            x.get(
                "candidate_id"
            ),
            repr(
                x.get(
                    "name_raw"
                )
            ),
            "codes=",
            x.get(
                "sample_codes"
            ),
            "state=",
            x.get(
                "material_state"
            ),
            "blocks=",
            x.get(
                "evidence_block_refs"
            ),
            "visual=",
            x.get(
                "visual_support_pages"
            ),
        )

    print()
    print(
        "Starting materials:"
    )

    for x in parsed.get(
        "starting_material_candidates",
        [],
    ):
        print(
            " ",
            x.get(
                "candidate_id"
            ),
            repr(
                x.get(
                    "name_raw"
                )
            ),
            "blocks=",
            x.get(
                "evidence_block_refs"
            ),
        )

    print()
    print(
        "Chemical participants:"
    )

    for x in parsed.get(
        "chemical_participant_candidates",
        [],
    ):
        print(
            " ",
            x.get(
                "candidate_id"
            ),
            repr(
                x.get(
                    "name_raw"
                )
            ),
            "role=",
            x.get(
                "role_hint"
            ),
            "blocks=",
            x.get(
                "evidence_block_refs"
            ),
        )

    print()
    print(
        "Sample-code definitions =",
        parsed.get(
            "sample_code_definitions"
        ),
    )

    print()
    print(
        "Uncertainties:"
    )

    for x in parsed.get(
        "uncertainties",
        [],
    ):
        print(
            " ",
            x.get(
                "uncertainty_id"
            ),
            x.get(
                "issue_type"
            ),
            repr(
                x.get(
                    "description"
                )
            ),
            "blocks=",
            x.get(
                "evidence_block_refs"
            ),
        )

    # --------------------------------------------------------------
    # Print exact cited source blocks for scientific review
    # --------------------------------------------------------------

    print()
    print("=" * 72)
    print(
        "CITED SOURCE BLOCKS"
    )
    print("=" * 72)

    for ref in refs:
        b = lookup[
            ref
        ]

        print()
        print(
            f"[{ref}] "
            f"PAGE={b['page_pdf']} "
            f"SHA256={b['text_sha256']}"
        )

        print(
            b[
                "text"
            ]
        )

    print()
    print("=" * 72)
    print(
        "FULL PARSED STAGE1 V0.5 JSON"
    )
    print("=" * 72)

    print(
        json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print("=" * 72)

    if audit[
        "valid"
    ]:
        print(
            "STAGE1_V05_CROSS_SMOKE="
            "GENERIC_PASS"
        )

    else:
        print(
            "STAGE1_V05_CROSS_SMOKE="
            "GENERIC_FAIL"
        )

    print(
        "PROMPT_HASH="
        + EXPECTED_PROMPT_SHA256
    )

    print(
        "EXACT_CHAT_COMPLETION_CALLS=1"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()
