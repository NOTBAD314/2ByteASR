"""Durable, content-free phase receipts for Studio projects."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import time

from ..runtime_paths import get_runtime_paths

STAGES = {"download", "json3", "reconstruction", "import", "export", "vad", "enhancement", "lyrics_draft", "song_presence",
          "translation", "proofread", "alignment", "grouping", "re_asr", "recognition", "retry"}
OUTCOMES = {"completed", "partial", "suggestion", "failed", "cancelled", "unchanged"}
SOURCES = {"youtube", "bilibili", "online_media", "json3", "studio", "firered_vad", "yamnet",
           "lightweight_vad", "htdemucs_cpu", "htdemucs_cuda", "whisper", "sylla",
           "qwen_local", "qwen_ultra_aligner", "qwen_aligner", "mfa_aligner", "moss",
           "firered_aed", "paraformer", "cloud_asr", "multiple_backends", "recognition_pipeline",
           "alignment_retry", "grouping_retry", "re_asr_retry"}
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="project-stage-history")
_MODEL_SOURCES = {"qwen_local": "qwen_local", "qwen3-asr": "qwen_local",
                  "qwen_ultra_aligner": "qwen_ultra_aligner",
                  "qwen_aligner": "qwen_aligner", "qwen3-aligner": "qwen_aligner",
                  "mfa_aligner": "mfa_aligner", "moss": "moss", "firered_aed": "firered_aed",
                  "paraformer": "paraformer", "whisper_turbo": "whisper", "api": "cloud_asr"}


def model_execution_receipt(statuses, role):
    """Read executed model routes without copying arbitrary provider details."""
    executed = [row for row in (statuses or {}).values() if isinstance(row, dict) and row.get("role") == role
                and (row.get("completed") or row.get("failed"))]
    complete = [row for row in executed if row.get("completed")]
    failed = any(row.get("failed") for row in executed)
    outcome = ("partial" if failed and complete else "completed" if complete else "failed" if failed else "")
    backends = {_MODEL_SOURCES.get(str(row.get("backend") or ""),
                                  _MODEL_SOURCES.get(str(row.get("model_id") or ""), ""))
                for row in complete or executed}
    source = next(iter(backends)) if len(backends) == 1 else "multiple_backends" if backends and "" not in backends else ""
    return outcome, source


def _project_key(project_id):
    return hashlib.sha256(str(project_id).encode("utf-8")).hexdigest()


def _database():
    return get_runtime_paths().user_data_root / "project-stage-history.sqlite3"


def _write(path, key, stage, outcome, counts):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5) as database:
        database.execute("""CREATE TABLE IF NOT EXISTS project_stages (
            project TEXT NOT NULL, seq INTEGER PRIMARY KEY AUTOINCREMENT, finished REAL NOT NULL,
            stage TEXT NOT NULL, outcome TEXT NOT NULL, counts TEXT NOT NULL
        )""")
        database.execute("CREATE INDEX IF NOT EXISTS project_stage_owner ON project_stages(project, seq)")
        database.execute("CREATE INDEX IF NOT EXISTS project_stage_latest ON project_stages(project, stage, seq)")
        database.execute("INSERT INTO project_stages(project, finished, stage, outcome, counts) VALUES (?, ?, ?, ?, ?)",
                         (key, time.time(), stage, outcome, json.dumps(counts, sort_keys=True)))


def record_stage(project_id, stage, outcome, *, source="", **counts):
    if not project_id or stage not in STAGES or outcome not in OUTCOMES:
        return None
    safe_counts = {key: value for key, value in counts.items()
                   if str(key).isidentifier() and type(value) is int and value >= 0}
    if isinstance(source, str) and source in SOURCES:
        safe_counts["_source"] = source
    return _executor.submit(_write, _database(), _project_key(project_id), stage, outcome, safe_counts)


def _receipt(stage, outcome, counts):
    values = json.loads(counts)
    source = values.pop("_source", None)
    row = dict(stage=stage, outcome=outcome, counts=values)
    if isinstance(source, str) and source in SOURCES:
        row["source"] = source
    return row


def _read(path, key, limit):
    if not path.is_file():
        return []
    # A reader cannot create or modify the history database.
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as database:
            if limit is None:
                rows = database.execute("""SELECT stage, outcome, counts FROM project_stages
                    WHERE seq IN (SELECT MAX(seq) FROM project_stages WHERE project=? GROUP BY stage)
                    ORDER BY seq DESC""", (key,)).fetchall()
            else:
                rows = database.execute("""SELECT stage, outcome, counts FROM project_stages
                    WHERE project=? ORDER BY seq DESC LIMIT ?""", (key, limit)).fetchall()
    except sqlite3.Error:
        return []
    return [_receipt(stage, outcome, counts) for stage, outcome, counts in rows]


def recent_stages(project_id, limit=16):
    return _executor.submit(_read, _database(), _project_key(project_id), max(1, min(64, int(limit))))


def latest_stages(project_id):
    return _executor.submit(_read, _database(), _project_key(project_id), None)


def _read_page(path, key, before, page_size):
    if not path.is_file():
        return [], None
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as database:
            raw = database.execute("""SELECT seq, finished, stage, outcome, counts
                FROM project_stages WHERE project=? AND seq<?
                ORDER BY seq DESC LIMIT ?""", (key, before, page_size + 1)).fetchall()
    except sqlite3.Error:
        return [], None
    next_cursor = raw[page_size - 1][0] if len(raw) > page_size else None
    return [dict(finished=finished, **_receipt(stage, outcome, counts))
            for _, finished, stage, outcome, counts in raw[:page_size]], next_cursor


def stage_page(project_id, before=None, limit=48):
    cursor = (1 << 63) - 1 if before is None else int(before)
    return _executor.submit(_read_page, _database(), _project_key(project_id),
                            cursor, max(1, min(64, int(limit))))
