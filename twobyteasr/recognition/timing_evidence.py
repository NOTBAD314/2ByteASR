"""Aligner receipts kept whole for every recognition task (2026-10-22).

The user asked to keep the time every step produced. The receipt of each
forced-alignment run is the first of those steps: for MFA it holds MFA's
raw word and phone tiers and how every word was split into characters, for
Qwen3 the raw slot predictions, the monotonic repair and the posteriors;
both hold the reliable pieces the pipeline uses next. Receipts are written
next to ``speaker-evidence`` in the media's cache folder (one gzip JSON per
stage, language and aligner; a later run of the same media replaces it).
Recognition never reads them back, and a failed write only loses the file.
"""
from __future__ import annotations

import gzip
import json
import os
import time
import uuid
from pathlib import Path

FOLDER = "timing-evidence"
FORMAT = "2byteasr-aligner-receipt-v1"


def engine_of(payload: dict) -> str:
    return "mfa" if str(payload.get("protocol") or "").startswith("mfa-") else "qwen3"


def receipt_path(folder, stage: str, language: str, payload: dict) -> Path:
    name = f"{stage}-{(str(language) or 'unknown').lower()}-{engine_of(payload)}.json.gz"
    return Path(folder) / name


def save_aligner_payload(folder, stage: str, language: str, payload: dict, **meta) -> str | None:
    """Write ``payload`` (an aligner worker's whole receipt) and return the file path, or None."""
    if not folder or not isinstance(payload, dict):
        return None
    from .run_context import get_runtime_context
    context = get_runtime_context()
    record = {"format": FORMAT, "stage": stage, "language": language, "engine": engine_of(payload),
              "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "job_id": context.job_id if context.identity_task_active else "", **meta, "payload": payload}
    path = receipt_path(folder, stage, language, payload)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False).encode("utf-8")))
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        return None
    return str(path)


def load_receipt(path) -> dict:
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
