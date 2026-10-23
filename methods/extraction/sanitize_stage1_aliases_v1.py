#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path


SANITIZER_VERSION = (
    "sanitize_stage1_aliases_v1_20261006"
)


def sha256_file(
    path: Path,
) -> str:
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


def normalize_raw_phrase(
    text: str,
) -> str:
    """
    Normalize only extraction/layout artifacts.

    IMPORTANT:
    - no stemming
    - no singular/plural normalization
    - no synonym expansion
    - no scientific-name rewriting
    """

    text = unicodedata.normalize(
        "NFKC",
        str(text),
    )

    text = text.replace(
        "\u00ad",
        "",
    )

    # Join PDF line-end hyphenation only.
    text = re.sub(
        r"([A-Za-z0-9])-"
        r"\s*\n\s*"
        r"([A-Za-z0-9])",
        r"\1\2",
        text,
    )

    for char in [
        "−",
        "–",
        "—",
        "‐",
    ]:
        text = text.replace(
            char,
            "-",
        )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return (
        text
        .strip()
        .lower()
    )


def raw_phrase_occurs(
    alias: str,
    source_text: str,
) -> bool:
    """
    Require an actual normalized phrase occurrence.

    Word boundaries prevent:
        material
    from matching:
        materials

    Thus grammatical model rewriting is not accepted as raw evidence.
    """

    alias_n = normalize_raw_phrase(
        alias
    )

    source_n = normalize_raw_phrase(
        source_text
    )

    if not alias_n:
        return False

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(
            alias_n
        )
        + r"(?![a-z0-9])"
    )

    return (
        re.search(
            pattern,
            source_n,
        )
        is not None
    )


def build_block_lookup(
    cache: dict,
) -> dict[str, dict]:
    lookup = {}

    for blocks in (
        cache[
            "pages"
        ].values()
    ):
        for block in blocks:
            bid = block[
                "block_id"
            ]

            if bid in lookup:
                raise RuntimeError(
                    (
                        "Duplicate block ID: "
                        f"{bid}"
                    )
                )

            lookup[
                bid
            ] = block

    return lookup


def sanitize_stage1_aliases(
    parsed: dict,
    block_cache: dict,
):
    canonical = copy.deepcopy(
        parsed
    )

    lookup = build_block_lookup(
        block_cache
    )

    audit_records = []

    totals = {
        "input_aliases":
            0,

        "kept_supported_raw":
            0,

        "removed_redundant":
            0,

        "removed_unsupported":
            0,

        "removed_empty":
            0,
    }

    for material in canonical.get(
        "materials",
        [],
    ):
        mid = str(
            material.get(
                "candidate_id",
                "",
            )
        )

        name_raw = str(
            material.get(
                "name_raw",
                "",
            )
        )

        sample_codes = [
            str(x)
            for x in (
                material.get(
                    "sample_codes"
                )
                or []
            )
        ]

        aliases = [
            str(x)
            for x in (
                material.get(
                    "aliases_raw"
                )
                or []
            )
        ]

        refs = (
            material.get(
                "evidence_block_refs"
            )
            or []
        )

        unknown_refs = [
            ref
            for ref in refs
            if ref not in lookup
        ]

        if unknown_refs:
            raise RuntimeError(
                (
                    f"{mid}: unknown "
                    "evidence block refs "
                    f"{unknown_refs}"
                )
            )

        cited_source = "\n".join(
            lookup[ref]["text"]
            for ref in refs
        )

        n_name = (
            normalize_raw_phrase(
                name_raw
            )
        )

        n_codes = {
            normalize_raw_phrase(
                code
            )
            for code in sample_codes
        }

        kept = []

        seen_kept = set()

        for alias in aliases:
            totals[
                "input_aliases"
            ] += 1

            n_alias = (
                normalize_raw_phrase(
                    alias
                )
            )

            if not n_alias:
                status = (
                    "REMOVED_EMPTY"
                )

                totals[
                    "removed_empty"
                ] += 1

            elif (
                n_alias == n_name
                or n_alias in n_codes
            ):
                status = (
                    "REMOVED_REDUNDANT_"
                    "WITH_NAME_OR_CODE"
                )

                totals[
                    "removed_redundant"
                ] += 1

            elif raw_phrase_occurs(
                alias,
                cited_source,
            ):
                if n_alias in seen_kept:
                    status = (
                        "REMOVED_REDUNDANT_"
                        "DUPLICATE_ALIAS"
                    )

                    totals[
                        "removed_redundant"
                    ] += 1

                else:
                    status = (
                        "KEPT_SUPPORTED_RAW_ALIAS"
                    )

                    totals[
                        "kept_supported_raw"
                    ] += 1

                    kept.append(
                        alias
                    )

                    seen_kept.add(
                        n_alias
                    )

            else:
                status = (
                    "REMOVED_UNSUPPORTED_"
                    "MODEL_PARAPHRASE"
                )

                totals[
                    "removed_unsupported"
                ] += 1

            audit_records.append({
                "candidate_id":
                    mid,

                "name_raw":
                    name_raw,

                "alias_input":
                    alias,

                "status":
                    status,

                "evidence_block_refs":
                    list(refs),
            })

        material[
            "aliases_raw"
        ] = kept

    audit = {
        "sanitizer_version":
            SANITIZER_VERSION,

        "paper_id":
            parsed.get(
                "paper_id"
            ),

        "policy": {
            "raw_alias_requires":
                (
                    "exact normalized phrase "
                    "occurrence in cited "
                    "PDF text block"
                ),

            "normalization_allows": [
                "Unicode NFKC",
                "PDF soft-hyphen removal",
                "PDF line-end dehyphenation",
                "hyphen glyph normalization",
                "whitespace normalization",
                "case folding",
            ],

            "normalization_forbids": [
                "stemming",
                "singular/plural conversion",
                "synonym substitution",
                "semantic paraphrase",
                "scientific-name rewriting",
            ],

            "raw_model_output":
                "never modified",

            "canonical_output":
                (
                    "unsupported aliases "
                    "removed deterministically"
                ),
        },

        "totals":
            totals,

        "records":
            audit_records,
    }

    return (
        canonical,
        audit,
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--parsed",
        required=True,
    )

    parser.add_argument(
        "--block-cache",
        required=True,
    )

    parser.add_argument(
        "--canonical-out",
        required=True,
    )

    parser.add_argument(
        "--audit-out",
        required=True,
    )

    args = parser.parse_args()

    parsed_path = Path(
        args.parsed
    )

    cache_path = Path(
        args.block_cache
    )

    canonical_out = Path(
        args.canonical_out
    )

    audit_out = Path(
        args.audit_out
    )

    parsed = json.loads(
        parsed_path.read_text(
            encoding="utf-8"
        )
    )

    cache = json.loads(
        cache_path.read_text(
            encoding="utf-8"
        )
    )

    canonical, audit = (
        sanitize_stage1_aliases(
            parsed,
            cache,
        )
    )

    canonical_out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit_out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    canonical_out.write_text(
        json.dumps(
            canonical,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
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

    print(
        "sanitizer_version =",
        SANITIZER_VERSION,
    )

    print(
        "paper_id =",
        parsed.get(
            "paper_id"
        ),
    )

    print(
        "raw_parsed_sha256 =",
        sha256_file(
            parsed_path
        ),
    )

    print(
        "block_cache_sha256 =",
        sha256_file(
            cache_path
        ),
    )

    print(
        "canonical_out =",
        canonical_out,
    )

    print(
        "canonical_sha256 =",
        sha256_file(
            canonical_out
        ),
    )

    print(
        "audit_out =",
        audit_out,
    )

    print(
        "audit_sha256 =",
        sha256_file(
            audit_out
        ),
    )

    print()
    print(
        "alias_totals =",
        audit[
            "totals"
        ],
    )


if __name__ == "__main__":
    main()
