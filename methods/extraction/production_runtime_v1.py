#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
from typing import Any

import requests


# ======================================================================
# RUNTIME IDENTITY
# ======================================================================

RUNTIME_VERSION = "production_runtime_v1_20261006"

MODEL_ID = "qwen3-vl-235b"

VLLM_BASE_URL = os.environ.get("CARBON_LLM_BASE_URL", "http://localhost:8000").rstrip("/")

CHAT_COMPLETIONS_URL = (
    VLLM_BASE_URL
    + "/v1/chat/completions"
)

NAVIGATION_VERSION = (
    "navigation_v1_2_20261006"
)

NAVIGATION_SHA256 = (
    "6339c387ae8cb0dd2fe0abbc42398109194bb3a45b08aeb286eb9234a080fb3e"
)

ALLOWED_LIFECYCLE_STATES = {
    "PENDING",
    "RUNNING",
    "COMPLETE",
    "FAILED",
    "NEEDS_ADVANCED_REVIEW",
}

ALLOWED_STAGES = {
    "STAGE0_NAVIGATION",
    "STAGE1_ENTITY_CENSUS",
    "STAGE2_PROCESS_GRAPH",
    "STAGE3_OMISSION_FOCUS",
    "STAGE4_SCHEMA_MAPPING",
    "STAGE5_VERIFIER",
    "VALIDATION",
    "COMPLETE",
}

HARD_CASE_FOLLOWUPS = {
    "CODEX_GRAPH_RECONSTRUCTION",
    "CODEX_TABLE_EXTRACTION",
    "CODEX_SAMPLE_SERIES_REVIEW",
    "MANUAL_PDF_REVIEW",
}


# ======================================================================
# BASIC HELPERS
# ======================================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def canonical_json_bytes(
    obj: Any,
) -> bytes:
    return (
        json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(
    data: bytes,
) -> str:
    return hashlib.sha256(
        data
    ).hexdigest()


def sha256_text(
    text: str,
) -> str:
    return sha256_bytes(
        text.encode("utf-8")
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


# ======================================================================
# CONSERVATIVE JSON PARSER
#
# Allowed:
#   1. direct JSON
#   2. whole-response Markdown JSON fence removal
#   3. deterministic prefix/suffix removal around ONE valid JSON value
#
# Forbidden:
#   - guessing missing braces
#   - reconstructing truncated JSON
#   - inventing values
#   - changing numeric/scientific contents
# ======================================================================

@dataclass
class ParseResult:
    ok: bool
    value: Any | None
    method: str
    error: str | None


def _direct_parse(
    text: str,
) -> ParseResult:
    try:
        return ParseResult(
            ok=True,
            value=json.loads(text),
            method="DIRECT_JSON",
            error=None,
        )

    except Exception as e:
        return ParseResult(
            ok=False,
            value=None,
            method="DIRECT_JSON",
            error=(
                f"{type(e).__name__}: "
                f"{e}"
            ),
        )


def parse_json_conservative(
    text: str,
) -> ParseResult:
    if text is None:
        return ParseResult(
            False,
            None,
            "NONE",
            "content is None",
        )

    text = (
        text
        .lstrip("\ufeff")
        .strip()
    )

    if not text:
        return ParseResult(
            False,
            None,
            "EMPTY",
            "empty content",
        )

    # --------------------------------------------------------------
    # 1. Direct JSON
    # --------------------------------------------------------------

    direct = _direct_parse(text)

    if direct.ok:
        return direct

    # --------------------------------------------------------------
    # 2. Whole Markdown code fence
    # --------------------------------------------------------------

    lines = text.splitlines()

    if (
        len(lines) >= 3
        and lines[0].strip().lower()
        in {
            "```json",
            "```",
        }
        and lines[-1].strip()
        == "```"
    ):
        inner = "\n".join(
            lines[1:-1]
        ).strip()

        fenced = _direct_parse(
            inner
        )

        if fenced.ok:
            fenced.method = (
                "WHOLE_CODE_FENCE_REMOVED"
            )

            return fenced

    # --------------------------------------------------------------
    # 3. Prefix/suffix removal
    #
    # Use JSONDecoder.raw_decode from first JSON opener.
    # Do not alter JSON itself.
    # --------------------------------------------------------------

    starts = [
        x
        for x in (
            text.find("{"),
            text.find("["),
        )
        if x >= 0
    ]

    if not starts:
        return ParseResult(
            False,
            None,
            "NO_JSON_START",
            direct.error,
        )

    start = min(starts)

    candidate = text[start:]

    decoder = json.JSONDecoder()

    try:
        value, end = (
            decoder.raw_decode(
                candidate
            )
        )

    except Exception as e:
        return ParseResult(
            False,
            None,
            "PREFIX_SUFFIX_FAILED",
            (
                f"{type(e).__name__}: "
                f"{e}"
            ),
        )

    suffix = (
        candidate[end:]
        .strip()
    )

    # Markdown fence is harmless.
    if suffix == "```":
        suffix = ""

    # Reject a second apparent JSON object/array.
    if (
        "{" in suffix
        or "[" in suffix
    ):
        return ParseResult(
            False,
            None,
            "MULTIPLE_JSON_VALUES",
            (
                "additional JSON-like "
                "content after first value"
            ),
        )

    return ParseResult(
        True,
        value,
        "PREFIX_SUFFIX_REMOVED",
        None,
    )


# ======================================================================
# SQLITE
# ======================================================================

def connect_db(
    db_path: Path,
) -> sqlite3.Connection:
    con = sqlite3.connect(
        db_path,
        timeout=60,
    )

    con.row_factory = (
        sqlite3.Row
    )

    con.execute(
        "PRAGMA foreign_keys=ON"
    )

    con.execute(
        "PRAGMA journal_mode=WAL"
    )

    con.execute(
        "PRAGMA synchronous=NORMAL"
    )

    con.execute(
        "PRAGMA busy_timeout=60000"
    )

    return con


def init_db_schema(
    con: sqlite3.Connection,
) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_state (
            paper_id TEXT PRIMARY KEY,

            processing_order INTEGER
                NOT NULL UNIQUE,

            c4b_stratum TEXT
                NOT NULL,

            canonical_pdf_path TEXT
                NOT NULL,

            lifecycle_state TEXT
                NOT NULL,

            current_stage TEXT
                NOT NULL,

            attempt_count INTEGER
                NOT NULL DEFAULT 0,

            last_error TEXT,

            navigation_version TEXT,
            navigation_sha256 TEXT,

            prompt_bundle_version TEXT,
            runtime_version TEXT
                NOT NULL,

            manifest_sha256 TEXT,

            created_at_utc TEXT
                NOT NULL,

            updated_at_utc TEXT
                NOT NULL
        );

        CREATE INDEX IF NOT EXISTS
            idx_paper_state_lifecycle
        ON paper_state(
            lifecycle_state,
            processing_order
        );

        CREATE INDEX IF NOT EXISTS
            idx_paper_state_stage
        ON paper_state(
            current_stage,
            processing_order
        );


        CREATE TABLE IF NOT EXISTS call_log (
            call_id TEXT PRIMARY KEY,

            paper_id TEXT
                NOT NULL,

            stage TEXT
                NOT NULL,

            attempt INTEGER
                NOT NULL,

            created_at_utc TEXT
                NOT NULL,

            completed_at_utc TEXT,

            model TEXT,

            request_path TEXT
                NOT NULL,

            response_path TEXT,

            meta_path TEXT
                NOT NULL,

            request_sha256 TEXT
                NOT NULL,

            input_sha256 TEXT,

            prompt_sha256 TEXT,

            http_status INTEGER,

            latency_seconds REAL,

            finish_reason TEXT,

            prompt_tokens INTEGER,

            completion_tokens INTEGER,

            total_tokens INTEGER,

            parse_status TEXT,

            validation_status TEXT,

            error_type TEXT,

            error_message TEXT,

            FOREIGN KEY(paper_id)
                REFERENCES paper_state(
                    paper_id
                )
        );

        CREATE INDEX IF NOT EXISTS
            idx_call_log_paper_stage
        ON call_log(
            paper_id,
            stage,
            attempt
        );


        CREATE TABLE IF NOT EXISTS hard_case_queue (
            hard_case_id TEXT PRIMARY KEY,

            paper_id TEXT
                NOT NULL,

            failed_stage TEXT
                NOT NULL,

            hard_case_reason TEXT
                NOT NULL,

            attempt_count INTEGER
                NOT NULL,

            last_error TEXT,

            finish_reason TEXT,

            coverage_completed TEXT,

            candidate_count INTEGER,

            ambiguous_count INTEGER,

            validation_failures TEXT,

            recommended_followup TEXT
                NOT NULL,

            created_at_utc TEXT
                NOT NULL,

            resolved INTEGER
                NOT NULL DEFAULT 0,

            resolution_note TEXT,

            FOREIGN KEY(paper_id)
                REFERENCES paper_state(
                    paper_id
                )
        );

        CREATE INDEX IF NOT EXISTS
            idx_hard_case_unresolved
        ON hard_case_queue(
            resolved,
            paper_id
        );


        CREATE TABLE IF NOT EXISTS event_log (
            event_id INTEGER
                PRIMARY KEY AUTOINCREMENT,

            paper_id TEXT,

            event_type TEXT
                NOT NULL,

            from_state TEXT,

            to_state TEXT,

            stage TEXT,

            message TEXT,

            created_at_utc TEXT
                NOT NULL
        );
        """
    )

    con.commit()


def set_meta(
    con: sqlite3.Connection,
    key: str,
    value: Any,
) -> None:
    if not isinstance(
        value,
        str,
    ):
        value = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )

    con.execute(
        """
        INSERT INTO meta(
            key,
            value
        )
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value
        """,
        (
            key,
            value,
        ),
    )


def log_event(
    con: sqlite3.Connection,
    *,
    paper_id: str | None,
    event_type: str,
    from_state: str | None = None,
    to_state: str | None = None,
    stage: str | None = None,
    message: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO event_log(
            paper_id,
            event_type,
            from_state,
            to_state,
            stage,
            message,
            created_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            event_type,
            from_state,
            to_state,
            stage,
            message,
            utc_now(),
        ),
    )


def transition_paper(
    con: sqlite3.Connection,
    *,
    paper_id: str,
    lifecycle_state: str,
    current_stage: str,
    last_error: str | None = None,
    increment_attempt: bool = False,
) -> None:
    if (
        lifecycle_state
        not in ALLOWED_LIFECYCLE_STATES
    ):
        raise ValueError(
            "Invalid lifecycle_state: "
            + lifecycle_state
        )

    if (
        current_stage
        not in ALLOWED_STAGES
    ):
        raise ValueError(
            "Invalid current_stage: "
            + current_stage
        )

    row = con.execute(
        """
        SELECT
            lifecycle_state,
            current_stage,
            attempt_count
        FROM paper_state
        WHERE paper_id=?
        """,
        (paper_id,),
    ).fetchone()

    if row is None:
        raise KeyError(
            paper_id
        )

    old_state = (
        row["lifecycle_state"]
    )

    attempt = int(
        row["attempt_count"]
    )

    if increment_attempt:
        attempt += 1

    now = utc_now()

    con.execute(
        """
        UPDATE paper_state
        SET
            lifecycle_state=?,
            current_stage=?,
            attempt_count=?,
            last_error=?,
            updated_at_utc=?
        WHERE paper_id=?
        """,
        (
            lifecycle_state,
            current_stage,
            attempt,
            last_error,
            now,
            paper_id,
        ),
    )

    log_event(
        con,
        paper_id=paper_id,
        event_type="STATE_TRANSITION",
        from_state=old_state,
        to_state=lifecycle_state,
        stage=current_stage,
        message=last_error,
    )

    con.commit()


def enqueue_hard_case(
    con: sqlite3.Connection,
    *,
    paper_id: str,
    failed_stage: str,
    hard_case_reason: str,
    attempt_count: int,
    recommended_followup: str,
    last_error: str | None = None,
    finish_reason: str | None = None,
    coverage_completed: str | None = None,
    candidate_count: int | None = None,
    ambiguous_count: int | None = None,
    validation_failures: Any | None = None,
) -> str:
    if (
        recommended_followup
        not in HARD_CASE_FOLLOWUPS
    ):
        raise ValueError(
            "Invalid recommended_followup"
        )

    hard_case_id = (
        "HC_"
        + uuid.uuid4().hex
    )

    validation_json = (
        None
        if validation_failures
        is None
        else json.dumps(
            validation_failures,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    con.execute(
        """
        INSERT INTO hard_case_queue(
            hard_case_id,
            paper_id,
            failed_stage,
            hard_case_reason,
            attempt_count,
            last_error,
            finish_reason,
            coverage_completed,
            candidate_count,
            ambiguous_count,
            validation_failures,
            recommended_followup,
            created_at_utc
        )
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            hard_case_id,
            paper_id,
            failed_stage,
            hard_case_reason,
            attempt_count,
            last_error,
            finish_reason,
            coverage_completed,
            candidate_count,
            ambiguous_count,
            validation_json,
            recommended_followup,
            utc_now(),
        ),
    )

    transition_paper(
        con,
        paper_id=paper_id,
        lifecycle_state=(
            "NEEDS_ADVANCED_REVIEW"
        ),
        current_stage=failed_stage,
        last_error=last_error,
    )

    return hard_case_id


# ======================================================================
# RETRY CLASSIFICATION
#
# This classifies failures only.
#
# Exact attempt limits and token budgets will be supplied by the later
# frozen execution policy; they are deliberately NOT hard-coded here.
# ======================================================================

def classify_retry(
    *,
    http_status: int | None,
    finish_reason: str | None,
    parse_ok: bool | None,
    exception_type: str | None,
) -> str:
    if exception_type in {
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectionError",
    }:
        return "RETRY_TRANSPORT"

    if http_status in {
        408,
        409,
        425,
        429,
        500,
        502,
        503,
        504,
    }:
        return "RETRY_HTTP"

    if finish_reason == "length":
        return "ESCALATE_OUTPUT_TOKEN_BUDGET"

    if (
        parse_ok is False
        and finish_reason
        not in {
            "length",
            None,
        }
    ):
        return "RETRY_STRUCTURED_OUTPUT"

    if (
        http_status is not None
        and 400 <= http_status < 500
    ):
        return "NON_RETRYABLE_HTTP"

    return "NO_AUTOMATIC_RETRY"


# ======================================================================
# RAW CALL STORE + vLLM CLIENT
#
# Exact HTTP request bytes are saved BEFORE sending.
# Exact raw response bytes are saved BEFORE semantic parsing.
# ======================================================================

class VLLMClient:

    def __init__(
        self,
        *,
        root: Path,
        db_path: Path,
        timeout_seconds: int = 600,
    ):
        self.root = root
        self.raw_root = (
            root
            / "04_raw_llm"
        )

        self.db_path = (
            db_path
        )

        self.timeout_seconds = (
            timeout_seconds
        )

    def call_chat(
        self,
        *,
        paper_id: str,
        stage: str,
        attempt: int,
        payload: dict,
        prompt_sha256: str | None,
        input_sha256: str | None,
    ) -> dict:

        if stage not in ALLOWED_STAGES:
            raise ValueError(
                "Unknown stage: "
                + stage
            )

        call_id = (
            "CALL_"
            + uuid.uuid4().hex
        )

        call_dir = (
            self.raw_root
            / paper_id
            / stage
            / f"attempt_{attempt:02d}_{call_id}"
        )

        call_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        request_path = (
            call_dir
            / "request.json"
        )

        response_path = (
            call_dir
            / "response.raw"
        )

        meta_path = (
            call_dir
            / "meta.json"
        )

        request_bytes = (
            canonical_json_bytes(
                payload
            )
        )

        request_path.write_bytes(
            request_bytes
        )

        request_sha256 = (
            sha256_bytes(
                request_bytes
            )
        )

        created_at = utc_now()

        con = connect_db(
            self.db_path
        )

        try:
            con.execute(
                """
                INSERT INTO call_log(
                    call_id,
                    paper_id,
                    stage,
                    attempt,
                    created_at_utc,
                    model,
                    request_path,
                    meta_path,
                    request_sha256,
                    input_sha256,
                    prompt_sha256,
                    parse_status,
                    validation_status
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    call_id,
                    paper_id,
                    stage,
                    attempt,
                    created_at,
                    payload.get(
                        "model"
                    ),
                    str(request_path),
                    str(meta_path),
                    request_sha256,
                    input_sha256,
                    prompt_sha256,
                    "NOT_PARSED",
                    "NOT_VALIDATED",
                ),
            )

            con.commit()

        finally:
            con.close()

        started = time.monotonic()

        http_status = None
        response_bytes = b""
        error_type = None
        error_message = None
        response_json = None
        finish_reason = None
        usage = {}
        response_model = None

        try:
            resp = requests.post(
                CHAT_COMPLETIONS_URL,
                data=request_bytes,
                headers={
                    "Content-Type":
                        "application/json",
                },
                timeout=self.timeout_seconds,
            )

            http_status = (
                resp.status_code
            )

            response_bytes = (
                resp.content
            )

            # Save raw bytes before any interpretation.
            response_path.write_bytes(
                response_bytes
            )

            try:
                response_json = (
                    json.loads(
                        response_bytes.decode(
                            "utf-8"
                        )
                    )
                )

            except Exception:
                response_json = None

            if isinstance(
                response_json,
                dict,
            ):
                response_model = (
                    response_json.get(
                        "model"
                    )
                )

                usage = (
                    response_json.get(
                        "usage"
                    )
                    or {}
                )

                choices = (
                    response_json.get(
                        "choices"
                    )
                    or []
                )

                if choices:
                    finish_reason = (
                        choices[0].get(
                            "finish_reason"
                        )
                    )

        except Exception as e:
            error_type = (
                type(e).__name__
            )

            error_message = str(e)

            # Preserve an empty raw-response artifact
            # so the call directory is structurally complete.
            response_path.write_bytes(
                response_bytes
            )

        latency = (
            time.monotonic()
            - started
        )

        completed_at = utc_now()

        meta = {
            "call_id":
                call_id,

            "paper_id":
                paper_id,

            "stage":
                stage,

            "attempt":
                attempt,

            "created_at_utc":
                created_at,

            "completed_at_utc":
                completed_at,

            "endpoint":
                CHAT_COMPLETIONS_URL,

            "request_sha256":
                request_sha256,

            "input_sha256":
                input_sha256,

            "prompt_sha256":
                prompt_sha256,

            "http_status":
                http_status,

            "latency_seconds":
                latency,

            "finish_reason":
                finish_reason,

            "model_requested":
                payload.get(
                    "model"
                ),

            "model_returned":
                response_model,

            "usage": {
                "prompt_tokens":
                    usage.get(
                        "prompt_tokens"
                    ),

                "completion_tokens":
                    usage.get(
                        "completion_tokens"
                    ),

                "total_tokens":
                    usage.get(
                        "total_tokens"
                    ),
            },

            "error_type":
                error_type,

            "error_message":
                error_message,

            "request_path":
                str(request_path),

            "response_path":
                str(response_path),
        }

        meta_path.write_bytes(
            canonical_json_bytes(
                meta
            )
        )

        con = connect_db(
            self.db_path
        )

        try:
            con.execute(
                """
                UPDATE call_log
                SET
                    completed_at_utc=?,
                    response_path=?,
                    http_status=?,
                    latency_seconds=?,
                    finish_reason=?,
                    prompt_tokens=?,
                    completion_tokens=?,
                    total_tokens=?,
                    error_type=?,
                    error_message=?,
                    model=COALESCE(?, model)
                WHERE call_id=?
                """,
                (
                    completed_at,
                    str(response_path),
                    http_status,
                    latency,
                    finish_reason,
                    usage.get(
                        "prompt_tokens"
                    ),
                    usage.get(
                        "completion_tokens"
                    ),
                    usage.get(
                        "total_tokens"
                    ),
                    error_type,
                    error_message,
                    response_model,
                    call_id,
                ),
            )

            con.commit()

        finally:
            con.close()

        return {
            "call_id":
                call_id,

            "call_dir":
                str(call_dir),

            "request_path":
                str(request_path),

            "response_path":
                str(response_path),

            "meta_path":
                str(meta_path),

            "http_status":
                http_status,

            "finish_reason":
                finish_reason,

            "usage":
                usage,

            "response_json":
                response_json,

            "error_type":
                error_type,

            "error_message":
                error_message,

            "latency_seconds":
                latency,
        }


def extract_assistant_content(
    response_json: dict,
) -> str | None:
    try:
        choices = (
            response_json.get(
                "choices"
            )
            or []
        )

        if not choices:
            return None

        message = (
            choices[0].get(
                "message"
            )
            or {}
        )

        content = (
            message.get(
                "content"
            )
        )

        if isinstance(
            content,
            str,
        ):
            return content

        return None

    except Exception:
        return None


def update_call_parse_status(
    db_path: Path,
    *,
    call_id: str,
    parse_status: str,
) -> None:
    con = connect_db(
        db_path
    )

    try:
        con.execute(
            """
            UPDATE call_log
            SET parse_status=?
            WHERE call_id=?
            """,
            (
                parse_status,
                call_id,
            ),
        )

        con.commit()

    finally:
        con.close()
