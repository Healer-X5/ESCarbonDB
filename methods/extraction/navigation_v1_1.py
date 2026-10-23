#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import statistics
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


NAVIGATION_VERSION = "navigation_v1_1_20261006"


# ======================================================================
# Strong semantic anchors
# ======================================================================

SECTION_RE = re.compile(
    r"(?i)\b"
    r"(?:\d+(?:\.\d+){0,3}\.?\s*)?"
    r"("
    r"experimental(?:\s+section|\s+procedures?)?|"
    r"materials?\s+and\s+methods?|"
    r"sample\s+preparation|"
    r"materials?\s+preparation|"
    r"preparation\s+of\s+[A-Za-z0-9_-]+|"
    r"synthesis(?:\s+of\s+[A-Za-z0-9_-]+)?|"
    r"fabrication(?:\s+of\s+[A-Za-z0-9_-]+)?|"
    r"carbonization|carbonisation|"
    r"activation"
    r")\b"
)

PROCEDURE_RE = re.compile(
    r"(?i)\b("
    r"(?:was|were|is|are)\s+"
    r"(?:first\s+|then\s+|subsequently\s+)?"
    r"(?:mixed|stirred|heated|dried|washed|filtered|"
    r"carbonized|carbonised|activated|annealed|calcined|"
    r"pyrolyzed|pyrolysed|immersed|dissolved|ground|"
    r"impregnated|centrifuged|treated)|"
    r"(?:mixed|stirred|heated|dried|washed|filtered|"
    r"carbonized|carbonised|activated|annealed|calcined|"
    r"pyrolyzed|pyrolysed|immersed|dissolved|ground|"
    r"impregnated|centrifuged|treated)\s+"
    r"(?:at|for|under|with|in|using)|"
    r"(?:placed|transferred|put)\s+"
    r"(?:into|in)\s+"
    r"(?:a|the)?\s*"
    r"(?:furnace|autoclave|oven)"
    r")\b"
)

SYNTHESIS_WORD_RE = re.compile(
    r"(?i)\b("
    r"synthesi[sz](?:e|ed|ing|ation)?|"
    r"prepar(?:e|ed|ation)|"
    r"fabricat(?:e|ed|ion)|"
    r"carboni[sz](?:e|ed|ation)|"
    r"pyroly(?:sis|ze|zed|se|sed)|"
    r"activat(?:e|ed|ion)|"
    r"hydrothermal|solvothermal|"
    r"calcination|calcined|"
    r"anneal(?:ed|ing)?"
    r")\b"
)

SEQUENCE_RE = re.compile(
    r"(?i)\b("
    r"subsequently|"
    r"followed by|"
    r"after which|"
    r"thereafter|"
    r"finally|"
    r"then|"
    r"resulting material|"
    r"resulting product"
    r")\b"
)

CONDITION_RE = re.compile(
    r"(?i)("
    r"\d+(?:\.\d+)?\s*(?:°\s*C|℃)|"
    r"\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours)\b|"
    r"\d+(?:\.\d+)?\s*(?:min|mins|minute|minutes)\b|"
    r"\d+(?:\.\d+)?\s*°?\s*C\s*min(?:-1|⁻¹)|"
    r"\b(?:N2|Ar|nitrogen|argon)\s+(?:atmosphere|flow)|"
    r"\bunder\s+(?:N2|Ar|nitrogen|argon)\b"
    r")"
)

QUANTITY_RE = re.compile(
    r"(?i)\b"
    r"\d+(?:\.\d+)?\s*"
    r"(?:mg|g|kg|μg|ug|mL|ml|L|μL|ul|mol|mmol)"
    r"\b"
)

SAMPLE_NAMING_RE = re.compile(
    r"(?i)\b("
    r"denoted as|"
    r"designated as|"
    r"referred to as|"
    r"labeled as|"
    r"labelled as|"
    r"named as|"
    r"hereafter referred to as"
    r")\b"
)

SCHEMATIC_PREP_RE = re.compile(
    r"(?i)("
    r"schematic\s+(?:illustration|diagram).*?"
    r"(?:preparation|synthesis|fabrication)|"
    r"(?:preparation|synthesis|fabrication)\s+route|"
    r"synthetic\s+route"
    r")"
)

REAGENT_RE = re.compile(
    r"(?i)\b("
    r"KOH|NaOH|HCl|H3PO4|ZnCl2|KCl|NaCl|"
    r"FeCl3|CuCl2|Cu(?:NO3)2|"
    r"ethanol|methanol|deionized water|distilled water|"
    r"urea|melamine|resorcinol|formaldehyde"
    r")\b"
)


# ======================================================================
# Negative / competing-section signals
# ======================================================================

REFERENCE_HEADING_RE = re.compile(
    r"(?im)^\s*(?:\d+\s*[.)]?\s*)?"
    r"references?\s*$"
)

REFERENCE_STYLE_RE = re.compile(
    r"(?i)("
    r"\b(?:19|20)\d{2}[a-z]?\b.*?"
    r"(?:doi|vol\.|pp\.|et al\.)"
    r")"
)

ACK_RE = re.compile(
    r"(?i)\backnowledg(?:e)?ments?\b"
)

INTRO_RE = re.compile(
    r"(?i)\b(?:1\.?\s*)?introduction\b"
)

RESULTS_RE = re.compile(
    r"(?i)\bresults?(?:\s+and\s+discussion)?\b"
)

ELECTROCHEM_RE = re.compile(
    r"(?i)\b("
    r"electrochemical|"
    r"cyclic voltammetry|"
    r"\bCV\b|"
    r"galvanostatic|"
    r"charge.discharge|"
    r"\bGCD\b|"
    r"electrochemical impedance|"
    r"\bEIS\b|"
    r"specific capacitance|"
    r"current density|"
    r"scan rate|"
    r"energy density|"
    r"power density|"
    r"cycling stability"
    r")\b"
)

CHARACTERIZATION_RE = re.compile(
    r"(?i)\b("
    r"SEM|FE-SEM|TEM|HRTEM|"
    r"XRD|XPS|Raman|FTIR|"
    r"BET|Brunauer.Emmett.Teller|"
    r"nitrogen adsorption|"
    r"pore size distribution"
    r")\b"
)


# ======================================================================
# Raw token detector
#
# IMPORTANT:
# These candidates NEVER add score by themselves.
# ======================================================================

RAW_CODE_RE = re.compile(
    r"\b"
    r"[A-Z][A-Z0-9]{0,7}"
    r"(?:[-_][A-Z0-9]{1,10}){1,4}"
    r"\b"
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def sha256_text(text: str):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def normalize_text(text: str):
    return (
        text.replace("\x00", " ")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
    )


def text_metrics(page_texts):
    chars = [
        len(x.strip())
        for x in page_texts
    ]

    n = len(chars)

    gt20 = sum(
        x > 20
        for x in chars
    )

    gt100 = sum(
        x > 100
        for x in chars
    )

    total = sum(chars)

    median = (
        float(statistics.median(chars))
        if chars else 0.0
    )

    c20 = gt20 / n if n else 0
    c100 = gt100 / n if n else 0

    if (
        n
        and c100 >= 0.80
        and total >= 3000
        and median >= 150
    ):
        quality = "GOOD"

    elif (
        n
        and c20 >= 0.50
        and total >= 1000
    ):
        quality = "WEAK"

    else:
        quality = "FAILED"

    return {
        "page_count": n,
        "pages_gt20_chars": gt20,
        "pages_gt100_chars": gt100,
        "coverage_gt20_chars":
            round(c20, 6),
        "coverage_gt100_chars":
            round(c100, 6),
        "total_chars": total,
        "median_chars_per_page": median,
        "quality": quality,
    }


def extract_pymupdf(pdf: Path):
    import pymupdf

    doc = pymupdf.open(pdf)

    texts = []

    try:
        for page in doc:
            texts.append(
                normalize_text(
                    page.get_text(
                        "text",
                        sort=True,
                    ) or ""
                )
            )

    finally:
        doc.close()

    return texts


def extract_pdftotext(
    pdf: Path,
    expected_pages=None,
):
    exe = shutil.which("pdftotext")

    if not exe:
        raise RuntimeError(
            "pdftotext unavailable"
        )

    cp = subprocess.run(
        [
            exe,
            "-layout",
            "-enc",
            "UTF-8",
            str(pdf),
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    if cp.returncode != 0:
        raise RuntimeError(
            cp.stderr.decode(
                "utf-8",
                errors="replace",
            )[:1000]
        )

    text = normalize_text(
        cp.stdout.decode(
            "utf-8",
            errors="replace",
        )
    )

    pages = text.split("\f")

    if pages and not pages[-1].strip():
        pages.pop()

    if expected_pages:
        if len(pages) < expected_pages:
            pages += [""] * (
                expected_pages - len(pages)
            )

        elif len(pages) > expected_pages:
            pages = (
                pages[:expected_pages - 1]
                + [
                    "\n".join(
                        pages[
                            expected_pages - 1:
                        ]
                    )
                ]
            )

    return pages


def choose_backend(pdf: Path):
    errors = []

    try:
        p_text = extract_pymupdf(pdf)
        p_metrics = text_metrics(p_text)

    except Exception as e:
        p_text = []
        p_metrics = {
            "quality": "FAILED",
            "page_count": 0,
            "total_chars": 0,
        }

        errors.append({
            "backend": "pymupdf",
            "error": repr(e),
        })

    if p_metrics["quality"] == "GOOD":
        return (
            "pymupdf",
            p_text,
            p_metrics,
            {"pymupdf": p_metrics},
            errors,
        )

    try:
        t_text = extract_pdftotext(
            pdf,
            p_metrics.get("page_count") or None,
        )

        t_metrics = text_metrics(t_text)

    except Exception as e:
        t_text = []
        t_metrics = {
            "quality": "FAILED",
            "page_count": 0,
            "total_chars": 0,
        }

        errors.append({
            "backend": "pdftotext",
            "error": repr(e),
        })

    rank = {
        "FAILED": 0,
        "WEAK": 1,
        "GOOD": 2,
    }

    if (
        rank[t_metrics["quality"]]
        >
        rank[p_metrics["quality"]]
        or (
            rank[t_metrics["quality"]]
            ==
            rank[p_metrics["quality"]]
            and
            t_metrics.get(
                "total_chars", 0
            )
            >
            p_metrics.get(
                "total_chars", 0
            ) * 1.15
        )
    ):
        return (
            "pdftotext",
            t_text,
            t_metrics,
            {
                "pymupdf": p_metrics,
                "pdftotext": t_metrics,
            },
            errors,
        )

    return (
        "pymupdf",
        p_text,
        p_metrics,
        {
            "pymupdf": p_metrics,
            "pdftotext": t_metrics,
        },
        errors,
    )


def inline_sections(text: str):
    results = []

    for m in SECTION_RE.finditer(text):
        s = re.sub(
            r"\s+",
            " ",
            m.group(0),
        ).strip()

        if s not in results:
            results.append(s)

    return results[:20]


def score_page(text: str):
    procedure_n = len(
        PROCEDURE_RE.findall(text)
    )

    synthesis_n = len(
        SYNTHESIS_WORD_RE.findall(text)
    )

    sequence_n = len(
        SEQUENCE_RE.findall(text)
    )

    condition_n = len(
        CONDITION_RE.findall(text)
    )

    quantity_n = len(
        QUANTITY_RE.findall(text)
    )

    reagent_n = len(
        REAGENT_RE.findall(text)
    )

    naming_n = len(
        SAMPLE_NAMING_RE.findall(text)
    )

    schematic_n = len(
        SCHEMATIC_PREP_RE.findall(text)
    )

    sections = inline_sections(text)

    raw_codes = sorted(
        set(
            RAW_CODE_RE.findall(text)
        )
    )[:60]

    electrochem_n = len(
        ELECTROCHEM_RE.findall(text)
    )

    char_n = len(
        CHARACTERIZATION_RE.findall(text)
    )

    reference_heading = bool(
        REFERENCE_HEADING_RE.search(text)
    )

    reference_style_n = len(
        REFERENCE_STYLE_RE.findall(text)
    )

    acknowledgements = bool(
        ACK_RE.search(text)
    )

    introduction = bool(
        INTRO_RE.search(text)
    )

    results_section = bool(
        RESULTS_RE.search(text)
    )

    # --------------------------------------------------------------
    # Positive synthesis score
    # --------------------------------------------------------------

    score = 0

    score += min(
        len(sections),
        3,
    ) * 28

    score += min(
        procedure_n,
        10,
    ) * 8

    score += min(
        synthesis_n,
        10,
    ) * 4

    score += min(
        sequence_n,
        8,
    ) * 4

    score += min(
        condition_n,
        12,
    ) * 3

    score += min(
        quantity_n,
        12,
    ) * 2

    score += min(
        reagent_n,
        10,
    ) * 3

    score += min(
        naming_n,
        5,
    ) * 10

    score += min(
        schematic_n,
        3,
    ) * 20

    # Co-occurrence bonus:
    # actual synthesis pages normally combine several
    # independent signals.
    strong_groups = sum([
        procedure_n > 0,
        synthesis_n > 0,
        condition_n > 0,
        quantity_n > 0,
        reagent_n > 0,
        sequence_n > 0,
        naming_n > 0,
    ])

    if strong_groups >= 5:
        score += 25

    elif strong_groups >= 4:
        score += 15

    elif strong_groups >= 3:
        score += 8

    # --------------------------------------------------------------
    # Negative competing-section score
    # --------------------------------------------------------------

    reference_like = (
        reference_heading
        or reference_style_n >= 8
    )

    if reference_like:
        if procedure_n == 0:
            score -= 90
        else:
            score -= 50

    if acknowledgements:
        if procedure_n == 0:
            score -= 45
        else:
            score -= 20

    # Electrochemistry is NOT a synthesis process.
    if electrochem_n >= 4:
        if procedure_n == 0:
            score -= 40
        elif procedure_n <= 1:
            score -= 20

    # Characterization-heavy pages should not dominate
    # synthesis-page discovery.
    if char_n >= 5:
        if procedure_n == 0:
            score -= 28
        elif procedure_n <= 1:
            score -= 12

    if introduction:
        if procedure_n == 0:
            score -= 20

    if results_section:
        if (
            procedure_n == 0
            and len(sections) == 0
        ):
            score -= 15

    score = max(
        int(score),
        0,
    )

    return {
        "navigation_score": score,

        "strong_signal_counts": {
            "procedure": procedure_n,
            "synthesis_words": synthesis_n,
            "sequence": sequence_n,
            "conditions": condition_n,
            "quantities": quantity_n,
            "reagents": reagent_n,
            "sample_naming": naming_n,
            "schematic_preparation":
                schematic_n,
        },

        "negative_signal_counts": {
            "electrochemistry":
                electrochem_n,
            "characterization":
                char_n,
            "reference_style":
                reference_style_n,
        },

        "flags": {
            "reference_like":
                reference_like,
            "acknowledgements":
                acknowledgements,
            "introduction":
                introduction,
            "results_section":
                results_section,
        },

        "section_anchors":
            sections,

        "raw_code_candidates":
            raw_codes,
    }


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
    ) = choose_backend(pdf)

    pages = []

    for page_pdf, text in enumerate(
        texts,
        1,
    ):
        s = score_page(text)

        pages.append({
            "page_pdf":
                page_pdf,

            "char_count":
                len(text.strip()),

            "text_sha256":
                sha256_text(text),

            "navigation_score":
                s["navigation_score"],

            "strong_signal_counts":
                s["strong_signal_counts"],

            "negative_signal_counts":
                s["negative_signal_counts"],

            "flags":
                s["flags"],

            "section_anchors":
                s["section_anchors"],

            "raw_code_candidates":
                s["raw_code_candidates"],

            "text":
                text,
        })

    ranked = sorted(
        pages,
        key=lambda x: (
            -x["navigation_score"],
            x["page_pdf"],
        ),
    )

    positive = [
        x
        for x in ranked
        if x["navigation_score"] > 0
    ]

    candidate_pages = [
        x["page_pdf"]
        for x in positive[:12]
    ]

    vision_pages = (
        candidate_pages[:8]
    )

    return {
        "navigation_version":
            NAVIGATION_VERSION,

        "created_at_utc":
            utc_now(),

        "paper_id":
            paper_id,

        "canonical_pdf_path":
            str(pdf),

        "pdf_realpath":
            str(pdf.resolve()),

        "pdf_size_bytes":
            pdf.stat().st_size,

        "pdf_sha256":
            sha256_file(pdf),

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

        "candidate_pages_ranked":
            candidate_pages,

        "future_vision_candidate_pages":
            vision_pages,

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
        "candidate_pages="
        + str(
            obj[
                "candidate_pages_ranked"
            ]
        )
    )
    print("output=" + str(output))


if __name__ == "__main__":
    main()
