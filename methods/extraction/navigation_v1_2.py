#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path


# ======================================================================
# Reuse the already-tested V1.1 PDF backend + semantic signal extraction.
#
# V1.2 changes ONLY candidate qualification/ranking.
# ======================================================================

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import navigation_v1_1 as base


NAVIGATION_VERSION = "navigation_v1_2_20261006"


def qualify_page(signals: dict) -> tuple[str, list[str]]:
    strong = signals["strong_signal_counts"]
    flags = signals["flags"]
    sections = signals["section_anchors"]

    procedure = strong["procedure"]
    synthesis = strong["synthesis_words"]
    sequence = strong["sequence"]
    conditions = strong["conditions"]
    quantities = strong["quantities"]
    reagents = strong["reagents"]
    naming = strong["sample_naming"]
    schematic = strong["schematic_preparation"]

    reasons = []

    # ------------------------------------------------------------------
    # Hard negative gates
    #
    # A page detected as reference/acknowledgements can still survive
    # ONLY when it independently contains strong procedural evidence.
    # This handles pages where references begin after a real methods
    # paragraph on the same PDF page.
    # ------------------------------------------------------------------

    if (
        flags["reference_like"]
        and procedure == 0
        and schematic == 0
        and conditions == 0
        and quantities == 0
    ):
        return (
            "EXCLUDED",
            ["reference_like_without_procedure"],
        )

    if (
        flags["acknowledgements"]
        and procedure == 0
        and schematic == 0
        and conditions == 0
        and quantities == 0
    ):
        return (
            "EXCLUDED",
            ["acknowledgements_without_procedure"],
        )

    # ------------------------------------------------------------------
    # PRIMARY
    # ------------------------------------------------------------------

    if procedure >= 2:
        reasons.append("multiple_procedural_sentences")

    if schematic >= 1:
        reasons.append("synthesis_or_preparation_schematic")

    if sections and procedure >= 1:
        reasons.append("method_section_plus_procedure")

    if (
        conditions >= 1
        and quantities >= 1
        and synthesis >= 2
        and (
            reagents >= 1
            or sequence >= 1
        )
    ):
        reasons.append(
            "condition_quantity_synthesis_cooccurrence"
        )

    if (
        naming >= 1
        and (
            procedure >= 1
            or conditions >= 1
            or quantities >= 1
        )
    ):
        reasons.append(
            "sample_naming_with_procedural_context"
        )

    if reasons:
        return "PRIMARY", reasons

    # ------------------------------------------------------------------
    # SUPPORT
    #
    # IMPORTANT:
    # synthesis words or reagent names alone are intentionally
    # insufficient.
    # ------------------------------------------------------------------

    support_reasons = []

    if (
        sections
        and synthesis >= 2
        and (
            sequence >= 2
            or conditions >= 1
            or quantities >= 1
        )
    ):
        support_reasons.append(
            "method_section_with_process_context"
        )

    if (
        conditions >= 2
        and synthesis >= 2
        and (
            sequence >= 1
            or reagents >= 1
        )
    ):
        support_reasons.append(
            "multiple_conditions_with_synthesis_context"
        )

    if (
        naming >= 1
        and synthesis >= 1
    ):
        support_reasons.append(
            "sample_naming_with_synthesis_context"
        )

    if support_reasons:
        return "SUPPORT", support_reasons

    # ------------------------------------------------------------------
    # Everything else remains searchable in cached text,
    # but is NOT an automatic LLM candidate page.
    # ------------------------------------------------------------------

    exclusion = []

    if flags["introduction"]:
        exclusion.append("introduction_without_procedure")

    if flags["results_section"]:
        exclusion.append("results_without_procedure")

    if (
        signals["negative_signal_counts"]["electrochemistry"]
        >= 4
    ):
        exclusion.append("electrochemistry_dominant")

    if (
        signals["negative_signal_counts"]["characterization"]
        >= 5
    ):
        exclusion.append("characterization_dominant")

    if synthesis > 0:
        exclusion.append(
            "synthesis_words_without_procedural_support"
        )

    if reagents > 0:
        exclusion.append(
            "reagent_mentions_without_procedural_support"
        )

    if not exclusion:
        exclusion.append(
            "insufficient_procedural_evidence"
        )

    return "EXCLUDED", exclusion


def build_navigation(
    paper_id: str,
    pdf: Path,
):
    (
        backend,
        texts,
        metrics,
        backend_metrics,
        errors,
    ) = base.choose_backend(pdf)

    pages = []

    for page_pdf, text in enumerate(
        texts,
        start=1,
    ):
        signals = base.score_page(text)

        candidate_class, reasons = (
            qualify_page(signals)
        )

        pages.append({
            "page_pdf":
                page_pdf,

            "char_count":
                len(text.strip()),

            "text_sha256":
                base.sha256_text(text),

            "navigation_score":
                signals["navigation_score"],

            "candidate_class":
                candidate_class,

            "candidate_reasons":
                reasons,

            "strong_signal_counts":
                signals["strong_signal_counts"],

            "negative_signal_counts":
                signals["negative_signal_counts"],

            "flags":
                signals["flags"],

            "section_anchors":
                signals["section_anchors"],

            "raw_code_candidates":
                signals["raw_code_candidates"],

            "text":
                text,
        })

    primary = sorted(
        [
            x
            for x in pages
            if x["candidate_class"] == "PRIMARY"
        ],
        key=lambda x: (
            -x["navigation_score"],
            x["page_pdf"],
        ),
    )

    support = sorted(
        [
            x
            for x in pages
            if x["candidate_class"] == "SUPPORT"
        ],
        key=lambda x: (
            -x["navigation_score"],
            x["page_pdf"],
        ),
    )

    candidates = (
        primary
        + support
    )[:12]

    candidate_pages = [
        x["page_pdf"]
        for x in candidates
    ]

    vision_pages = (
        candidate_pages[:8]
    )

    return {
        "navigation_version":
            NAVIGATION_VERSION,

        "base_signal_version":
            base.NAVIGATION_VERSION,

        "created_at_utc":
            base.utc_now(),

        "paper_id":
            paper_id,

        "canonical_pdf_path":
            str(pdf),

        "pdf_realpath":
            str(pdf.resolve()),

        "pdf_size_bytes":
            pdf.stat().st_size,

        "pdf_sha256":
            base.sha256_file(pdf),

        "source_authority":
            "canonical_pdf",

        "selected_text_backend":
            backend,

        "selected_text_metrics":
            metrics,

        "backend_metrics":
            backend_metrics,

        "backend_errors":
            errors,

        "primary_pages_ranked": [
            x["page_pdf"]
            for x in primary
        ],

        "support_pages_ranked": [
            x["page_pdf"]
            for x in support
        ],

        "candidate_pages_ranked":
            candidate_pages,

        "future_vision_candidate_pages":
            vision_pages,

        "candidate_counts": {
            "PRIMARY":
                len(primary),

            "SUPPORT":
                len(support),

            "EXCLUDED":
                sum(
                    x["candidate_class"]
                    == "EXCLUDED"
                    for x in pages
                ),
        },

        "pages":
            pages,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--paper-id",
        required=True,
    )

    parser.add_argument(
        "--pdf",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    args = parser.parse_args()

    paper_id = (
        args.paper_id
        .strip()
        .upper()
    )

    pdf = Path(args.pdf)
    output = Path(args.output)

    obj = build_navigation(
        paper_id,
        pdf,
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"

    with gzip.open(
        output,
        "wt",
        encoding="utf-8",
        compresslevel=6,
    ) as f:
        f.write(payload)

    print("NAVIGATION_RESULT=PASS")
    print("paper_id=" + paper_id)
    print(
        "backend="
        + obj["selected_text_backend"]
    )
    print(
        "quality="
        + str(
            obj[
                "selected_text_metrics"
            ]["quality"]
        )
    )
    print(
        "primary_pages="
        + str(
            obj["primary_pages_ranked"]
        )
    )
    print(
        "support_pages="
        + str(
            obj["support_pages_ranked"]
        )
    )
    print(
        "candidate_pages="
        + str(
            obj["candidate_pages_ranked"]
        )
    )
    print(
        "candidate_counts="
        + str(
            obj["candidate_counts"]
        )
    )
    print(
        "output="
        + str(output)
    )


if __name__ == "__main__":
    main()
