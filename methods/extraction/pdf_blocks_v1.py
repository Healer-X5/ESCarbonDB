#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf


BLOCK_VERSION = "pdf_blocks_v1_20261006"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(
                1024 * 1024
            )

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def clean_raw_text(text: str) -> str:
    # Preserve extracted scientific text.
    # Only normalize platform newline/NUL artifacts.
    return (
        text.replace("\x00", " ")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
    )


def extract_block_cache(
    pdf: Path,
    page_numbers: list[int],
) -> dict:
    pdf = Path(pdf)

    if not pdf.is_file():
        raise FileNotFoundError(pdf)

    doc = pymupdf.open(pdf)

    try:
        page_count = len(doc)

        pages = {}

        for page_pdf in page_numbers:
            if not (
                1 <= page_pdf <= page_count
            ):
                raise ValueError(
                    f"Invalid page {page_pdf}"
                )

            page = doc[
                page_pdf - 1
            ]

            raw_blocks = page.get_text(
                "blocks",
                sort=False,
            )

            blocks = []

            for raw in raw_blocks:
                (
                    x0,
                    y0,
                    x1,
                    y1,
                    text,
                    block_no,
                    block_type,
                ) = raw[:7]

                # PyMuPDF block_type 0 = text.
                if int(block_type) != 0:
                    continue

                text = clean_raw_text(
                    text
                )

                if not text:
                    continue

                blocks.append({
                    "x0":
                        round(
                            float(x0),
                            2,
                        ),

                    "y0":
                        round(
                            float(y0),
                            2,
                        ),

                    "x1":
                        round(
                            float(x1),
                            2,
                        ),

                    "y1":
                        round(
                            float(y1),
                            2,
                        ),

                    "block_no_raw":
                        int(block_no),

                    "block_type":
                        int(block_type),

                    "text":
                        text,
                })

            # Stable deterministic ID assignment.
            #
            # Importantly, later scientific evidence relies on
            # the block itself, not on concatenating this order.
            blocks.sort(
                key=lambda b: (
                    round(
                        b["y0"],
                        1,
                    ),
                    round(
                        b["x0"],
                        1,
                    ),
                    b["block_no_raw"],
                )
            )

            for i, block in enumerate(
                blocks,
                start=1,
            ):
                block_id = (
                    f"P{page_pdf:03d}"
                    f"_B{i:03d}"
                )

                block[
                    "block_id"
                ] = block_id

                block[
                    "page_pdf"
                ] = page_pdf

                block[
                    "text_sha256"
                ] = sha256_text(
                    block["text"]
                )

            pages[
                str(page_pdf)
            ] = blocks

    finally:
        doc.close()

    return {
        "block_version":
            BLOCK_VERSION,

        "canonical_pdf_path":
            str(pdf),

        "pdf_sha256":
            sha256_file(pdf),

        "page_numbers":
            list(page_numbers),

        "pages":
            pages,
    }


def block_lookup(
    cache: dict,
) -> dict[str, dict]:
    out = {}

    for blocks in (
        cache[
            "pages"
        ].values()
    ):
        for block in blocks:
            bid = block[
                "block_id"
            ]

            if bid in out:
                raise RuntimeError(
                    (
                        "Duplicate "
                        f"block_id={bid}"
                    )
                )

            out[bid] = block

    return out


def prompt_block_text(
    cache: dict,
    page_numbers: list[int],
) -> str:
    chunks = []

    for page_pdf in page_numbers:
        chunks.append(
            (
                "===== BEGIN "
                f"PAGE_PDF={page_pdf} "
                "TEXT_BLOCKS ====="
            )
        )

        blocks = cache[
            "pages"
        ][str(page_pdf)]

        for block in blocks:
            chunks.append(
                (
                    f"[{block['block_id']}]\n"
                    f"{block['text']}"
                )
            )

        chunks.append(
            (
                "===== END "
                f"PAGE_PDF={page_pdf} "
                "TEXT_BLOCKS ====="
            )
        )

    return "\n\n".join(
        chunks
    )


def write_cache(
    cache: dict,
    path: Path,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            cache,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
