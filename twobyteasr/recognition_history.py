"""Recognition history backed by the existing per-media JSON reports."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import qtawesome as qta
from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from twobyteasr.i18n import current_language, translate
from twobyteasr.ui_navigation import NAVIGATION_QSS, style_workspace_page_title
from twobyteasr.ui_theme import (
    AMBER,
    AMBER_SOFT,
    BACKGROUND,
    BORDER,
    CORAL,
    GREEN,
    GREEN_SOFT,
    GREEN_SUBTLE,
    INK,
    MUTED,
    SURFACE,
    SURFACE_MUTED,
)

from .i18n import bind_text, tr
from .recognition_outcome import (
    OUTCOME_VERSION, RecognitionOutcome, normalize_recognition_outcome, review_severity,
)


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "bearer",
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{12,}|(?:sk|key|token)[-_][a-z0-9._-]{12,})"
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    if normalized.endswith(("_count", "_counts", "_source")):
        return False
    return normalized in {"token", "headers", "cookies"} or any(
        part in normalized for part in _SENSITIVE_KEY_PARTS
    )


def redact_report_payload(value: Any) -> Any:
    """Recursively remove credentials from both expected and legacy reports."""
    if isinstance(value, dict):
        return {
            str(key): "<已隐藏>" if _sensitive_key(key) else redact_report_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_report_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_report_payload(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("<已隐藏>", value)
    return value


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _date_value(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for pattern in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.min


def _display_date(value: object) -> str:
    parsed = _date_value(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed != datetime.min else str(value or "未知")


_PRIMARY_NAMES = {
    "moss": "MOSS",
    "firered": "FireRed",
    "qwen_local": "Qwen3-ASR",
    "firered_llm": "FireRedASR2-LLM",
    "qwen_asr": "Qwen3-ASR",
    "whisper_turbo": "Whisper Turbo",
    "sensevoice": "SenseVoice",
    "paraformer": "Paraformer",
    "funasr_nano": "Fun-ASR Nano",
    "api": "在线 API",
    "off": "未启用",
}
_TIMELINE_NAMES = {
    "local": "FireRed",
    "firered": "FireRed",
    "qwen_aligner": "Qwen Aligner",
    "whisper_turbo": "Whisper Turbo",
    "paraformer": "Paraformer",
    "off": "未启用",
}
_REVIEW_NAMES = {
    "local": "Qwen3-ASR",
    "api": "Qwen3-ASR API",
    "whisper_turbo": "Whisper Turbo",
    "sensevoice": "SenseVoice",
    "funasr_nano": "Fun-ASR Nano",
    "off": "未启用",
}


def _inferred_primary(stages: list[Any]) -> str:
    labels = " ".join(str(_dict(stage).get("label", "")) for stage in stages).casefold()
    for needle, label in (
        ("moss", "MOSS"),
        ("sensevoice", "SenseVoice"),
        ("paraformer", "Paraformer"),
        ("whisper", "Whisper Turbo"),
        ("fun-asr", "Fun-ASR Nano"),
        ("qwen3", "Qwen3-ASR"),
        ("firered", "FireRed"),
    ):
        if needle in labels:
            return label
    return "未知"


_SEVERITIES = ("error", "warning", "review", "info", "debug")


def _review_severity(item: dict[str, Any]) -> str:
    return review_severity(item)


def _severity_summary(payload: dict[str, Any]) -> tuple[dict[str, int], tuple[str, ...], tuple[str, ...]]:
    outcome = normalize_recognition_outcome(payload)
    return dict(outcome.severity_counts), outcome.problems, outcome.review_notes


class _RecordFacts:
    """Severity helpers shared by full report records and list summaries."""

    def severity_count(self, severity: str) -> int:
        return dict(self.severity_counts).get(severity, 0)

    @property
    def anomaly_count(self) -> int:
        return self.severity_count("error") + self.severity_count("warning")

    @property
    def review_count(self) -> int:
        return self.severity_count("review")

    @property
    def has_anomaly(self) -> bool:
        return self.anomaly_count > 0 or self.status in {"failed", "cancelled", "skipped", "partial", "unknown"}


@dataclass(frozen=True)
class RecognitionRecord(_RecordFacts):
    """One fully parsed report (detail view, opening a result, audits)."""

    path: Path
    payload: dict[str, Any]
    media_name: str
    completed_at: str
    completed_sort: datetime
    elapsed_seconds: float
    media_seconds: float
    primary_model: str
    timeline_model: str
    review_model: str
    ai_model: str
    glossary_count: int
    status: str
    status_label: str
    problems: tuple[str, ...]
    severity_counts: tuple[tuple[str, int], ...]
    review_notes: tuple[str, ...]
    outcome: RecognitionOutcome

    @property
    def cue_count(self) -> int:
        return int(_dict(self.payload.get("result")).get("cue_count") or 0)


_RecognitionRecordCache = dict[
    Path, tuple[int, int, RecognitionRecord | None, str | None, int]
]


def parse_recognition_report(path: Path) -> RecognitionRecord:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("报告顶层不是 JSON 对象")
    media = _dict(payload.get("media"))
    settings = _dict(payload.get("settings"))
    models = _dict(settings.get("models"))
    profile = _dict(settings.get("content_profile"))
    switches = _dict(settings.get("switches"))
    result = _dict(payload.get("result"))
    stages = _list(payload.get("stages"))

    primary_backend = str(models.get("primary_asr_backend") or "")
    primary = _PRIMARY_NAMES.get(primary_backend, primary_backend) if primary_backend else _inferred_primary(stages)
    timeline_backend = str(models.get("firered_asr_backend") or "off")
    timeline = _TIMELINE_NAMES.get(timeline_backend, timeline_backend)
    review_backend = str(models.get("qwen_asr_backend") or "off")
    review = _REVIEW_NAMES.get(review_backend, review_backend)

    ai_enabled = switches.get("use_ai_grouping") is not False
    ai_model = str(models.get("group_model") or models.get("polish_model") or "") if ai_enabled else ""
    enabled_ids = _list(profile.get("enabled_glossary_ids"))
    glossary_count = len({str(item) for item in enabled_ids if str(item).strip()})
    if not glossary_count and profile.get("domain_terms") and str(profile.get("game") or "").strip():
        glossary_count = 1

    outcome = normalize_recognition_outcome(payload)
    status = outcome.core_status
    status_label = outcome.status_label
    severity_counts = dict(outcome.severity_counts)
    problems, review_notes = outcome.problems, outcome.review_notes
    finished = payload.get("finished_at") or payload.get("started_at") or path.stat().st_mtime
    if isinstance(finished, (int, float)):
        completed_sort = datetime.fromtimestamp(float(finished))
        completed_at = completed_sort.strftime("%Y-%m-%d %H:%M")
    else:
        completed_sort = _date_value(finished)
        completed_at = _display_date(finished)

    return RecognitionRecord(
        path=Path(path),
        payload=payload,
        media_name=str(media.get("name") or Path(path).name.replace("_字幕任务报告.json", "")),
        completed_at=completed_at,
        completed_sort=completed_sort,
        elapsed_seconds=float(result.get("elapsed_seconds") or 0),
        media_seconds=float(
            result.get("audio_seconds")
            or media.get("duration_seconds")
            or media.get("duration")
            or 0
        ),
        primary_model=primary or "未知",
        timeline_model=timeline or "未知",
        review_model=review or "未知",
        ai_model=ai_model,
        glossary_count=glossary_count,
        status=status,
        status_label=status_label,
        problems=problems,
        severity_counts=tuple((key, severity_counts[key]) for key in _SEVERITIES),
        review_notes=review_notes,
        outcome=outcome,
    )


def _record_identity(record: RecognitionRecord) -> tuple[str, str, str]:
    """Stable task identity: file stem plus media plus start time.

    One task's multi-stage report is a single file, so this never splits it.
    The same report copied into a second root (same stem and started_at) is
    one record, while a genuinely re-run media gets a new started_at (and the
    previous run is archived under a timestamped stem) and stays separate.
    """
    media = record.payload.get("media") if isinstance(record.payload, dict) else {}
    media_path = str(media.get("path") or record.media_name) if isinstance(media, dict) else record.media_name
    started = str(record.payload.get("started_at") or record.completed_sort.isoformat())
    task_id = str(record.payload.get("task_id") or record.payload.get("run_id") or "").strip()
    return (task_id or record.path.stem, media_path, started)


def load_recognition_records(
    report_root: Path,
    *,
    extra_roots: tuple[Path, ...] | list[Path] = (),
    cache: _RecognitionRecordCache | None = None,
) -> tuple[list[RecognitionRecord], list[str]]:
    records: list[RecognitionRecord] = []
    errors: list[str] = []
    active_cache: _RecognitionRecordCache = {}
    roots: list[Path] = [Path(report_root)]
    for extra in extra_roots:
        extra = Path(extra)
        if extra not in roots:
            roots.append(extra)
    seen_identities: set[tuple[str, str, str]] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*_字幕任务报告.json"):
            mtime_ns: int | None = None
            size: int | None = None
            try:
                stat = path.stat()
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size
                cached = cache.get(path) if cache is not None else None
                if cached is not None and cached[:2] == (mtime_ns, size) and len(cached) > 4 and cached[4] == OUTCOME_VERSION:
                    record, error = cached[2], cached[3]
                elif size > 12 * 1024 * 1024:
                    raise ValueError("报告超过 12 MB")
                else:
                    record = parse_recognition_report(path)
                    error = None
                active_cache[path] = (mtime_ns, size, record, error, OUTCOME_VERSION)
                if record is not None:
                    identity = _record_identity(record)
                    if identity in seen_identities:
                        continue
                    seen_identities.add(identity)
                    records.append(record)
                elif error:
                    errors.append(error)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                error = f"{path.name}: {exc}"
                errors.append(error)
                if mtime_ns is not None and size is not None:
                    active_cache[path] = (mtime_ns, size, None, error, OUTCOME_VERSION)
    if cache is not None:
        cache.clear()
        cache.update(active_cache)
    records.sort(key=lambda item: item.completed_sort, reverse=True)
    return records, errors


def discover_legacy_report_roots() -> list[Path]:
    """Known locations that may hold reports from previous installs.

    Bounded to the app's own directories (never a whole-drive scan): previous
    ``dist-prev-*`` backups created by staged rebuilds. In source mode they sit
    next to the repo root (= install root); in frozen mode the install root is
    ``<repo>/dist/2ByteASR`` so the backups hang two levels up.
    """
    roots: list[Path] = []
    try:
        from .runtime_paths import detect_install_root

        install = detect_install_root()
        bases = [install, install.parent.parent]
    except Exception:
        bases = [Path.cwd()]
    seen: set[Path] = set()
    for base in bases:
        try:
            for candidate in sorted(base.glob("dist-prev-*/reports")):
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                if candidate.is_dir():
                    roots.append(resolved)
        except OSError:
            continue
    return roots


def _report_started_at(path: Path) -> str:
    """Cheap identity probe: read only the head of the JSON document."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return ""
    match = re.search(r'"started_at"\s*:\s*"([^"]+)"', head)
    return match.group(1) if match else ""


def repair_recognition_history(
    target_root: Path,
    *,
    extra_roots: tuple[Path, ...] | list[Path] = (),
) -> dict:
    """Import reports found in legacy roots into the stable root (copy, never move).

    One bad file must not abort the import; originals always stay untouched.
    """
    import shutil

    target = Path(target_root)
    target.mkdir(parents=True, exist_ok=True)
    existing: set[tuple[str, str]] = set()
    for path in target.glob("*_字幕任务报告.json"):
        started = _report_started_at(path)
        existing.add((path.stem, started))
    roots = [Path(root) for root in extra_roots if Path(root) != target]
    from . import reporting

    roots.extend(discover_legacy_report_roots())
    if reporting.LEGACY_REPORT_ROOTS:
        roots.extend(
            root for root in reporting.LEGACY_REPORT_ROOTS if root != target
        )
    result = {"found": 0, "imported": 0, "duplicates": 0, "failed": 0, "failed_files": []}
    seen_sources: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = sorted(root.glob("*_字幕任务报告.json"))
        except OSError:
            continue
        for path in paths:
            if path in seen_sources:
                continue
            seen_sources.add(path)
            result["found"] += 1
            started = _report_started_at(path)
            key = (path.stem, started)
            if key in existing:
                result["duplicates"] += 1
                continue
            try:
                if path.stat().st_size > 12 * 1024 * 1024:
                    raise ValueError("报告超过 12 MB")
                json.loads(path.read_text(encoding="utf-8", errors="strict"))
            except (OSError, ValueError) as exc:
                result["failed"] += 1
                result["failed_files"].append(f"{path.name}: {exc}")
                continue
            destination = target / path.name
            if destination.exists():
                stamp = re.sub(r"\D", "", started)[:14] or time.strftime("%Y%m%d%H%M%S")
                destination = target / f"{path.stem}_{stamp}{path.suffix}"
            try:
                shutil.copyfile(path, destination)
                existing.add(key)
                result["imported"] += 1
                sibling = path.with_name(path.stem + ".txt")
                if sibling.exists():
                    shutil.copyfile(
                        sibling, destination.with_name(destination.stem + ".txt")
                    )
            except OSError:
                result["failed"] += 1
                result["failed_files"].append(path.name)
    return result


# ---------------------------------------------------------------- list index
# 2026-10-12: the history list shows light summaries only. A full report is
# parsed once per (path, mtime_ns, size, outcome version) and its summary is
# persisted in the cache folder (never inside the reports folder), so a later
# start only stats the report files. The index is rebuildable: losing it
# costs one background re-read of the reports.
HISTORY_INDEX_SCHEMA = 1
HISTORY_INDEX_NAME = "recognition-history-index.json"
REPORT_GLOB = "*_字幕任务报告.json"
_MAX_REPORT_BYTES = 12 * 1024 * 1024
# Changed reports this small are read at once (a just-finished task shows up
# without a second pass); larger or more of them go to a background thread.
_INLINE_PARSE_BYTES = 192 * 1024
_INLINE_PARSE_BUDGET_S = 0.04
_INLINE_DETAIL_BYTES = 256 * 1024


@dataclass(frozen=True)
class RecognitionSummary(_RecordFacts):
    """What one history card shows. Never holds the report payload."""

    path: Path
    media_name: str
    completed_at: str
    completed_sort: datetime
    elapsed_seconds: float
    media_seconds: float
    cue_count: int
    primary_model: str
    timeline_model: str
    review_model: str
    ai_model: str
    glossary_count: int
    status: str
    status_label: str
    problems: tuple[str, ...]
    severity_counts: tuple[tuple[str, int], ...]
    identity: tuple[str, str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "media_name": self.media_name, "completed_at": self.completed_at,
            "completed_sort": self.completed_sort.isoformat(), "elapsed_seconds": self.elapsed_seconds,
            "media_seconds": self.media_seconds, "cue_count": self.cue_count,
            "primary_model": self.primary_model, "timeline_model": self.timeline_model,
            "review_model": self.review_model, "ai_model": self.ai_model,
            "glossary_count": self.glossary_count, "status": self.status, "status_label": self.status_label,
            "problems": list(self.problems), "severity_counts": [list(item) for item in self.severity_counts],
            "identity": list(self.identity),
        }

    @classmethod
    def from_json(cls, path: Path, data: dict[str, Any]) -> "RecognitionSummary":
        return cls(
            path=Path(path), media_name=str(data["media_name"]), completed_at=str(data["completed_at"]),
            completed_sort=datetime.fromisoformat(str(data["completed_sort"])),
            elapsed_seconds=float(data["elapsed_seconds"]), media_seconds=float(data["media_seconds"]),
            cue_count=int(data["cue_count"]), primary_model=str(data["primary_model"]),
            timeline_model=str(data["timeline_model"]), review_model=str(data["review_model"]),
            ai_model=str(data["ai_model"]), glossary_count=int(data["glossary_count"]),
            status=str(data["status"]), status_label=str(data["status_label"]),
            problems=tuple(str(item) for item in data["problems"]),
            severity_counts=tuple((str(key), int(value)) for key, value in data["severity_counts"]),
            identity=tuple(str(item) for item in data["identity"]),
        )


def summarize_record(record: RecognitionRecord) -> RecognitionSummary:
    return RecognitionSummary(
        path=record.path, media_name=record.media_name, completed_at=record.completed_at,
        completed_sort=record.completed_sort, elapsed_seconds=record.elapsed_seconds,
        media_seconds=record.media_seconds, cue_count=record.cue_count, primary_model=record.primary_model,
        timeline_model=record.timeline_model, review_model=record.review_model, ai_model=record.ai_model,
        glossary_count=record.glossary_count, status=record.status, status_label=record.status_label,
        problems=tuple(record.problems), severity_counts=tuple(record.severity_counts),
        identity=_record_identity(record),
    )


def summarize_report(path: Path) -> RecognitionSummary:
    """Parse one report and keep only what the list shows (payload dropped)."""
    return summarize_record(parse_recognition_report(path))


def default_history_index_path() -> Path:
    from .runtime_paths import user_data_root

    return user_data_root() / "cache" / HISTORY_INDEX_NAME


def list_report_files(roots) -> tuple[list[tuple[Path, int, int]], list[str]]:
    """Report files with (mtime_ns, size): the only per-file I/O of a refresh."""
    listing: list[tuple[Path, int, int]] = []
    errors: list[str] = []
    for root in roots:
        root = Path(root)
        try:
            if not root.is_dir():
                continue
            paths = list(root.glob(REPORT_GLOB))
        except OSError as exc:
            errors.append(f"{root}: {exc}")
            continue
        for path in paths:
            try:
                stat = path.stat()
            except OSError as exc:
                errors.append(f"{path.name}: {exc}")
                continue
            listing.append((path, int(stat.st_mtime_ns), int(stat.st_size)))
    return listing, errors


def parse_listed_report(path: Path, mtime_ns: int, size: int):
    """(path, mtime_ns, size, summary, error, cacheable) for one listed file."""
    try:
        if size > _MAX_REPORT_BYTES:
            raise ValueError("报告超过 12 MB")
        return path, mtime_ns, size, summarize_report(path), None, True
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Content errors stay cached until the file changes.
        return path, mtime_ns, size, None, f"{path.name}: {exc}", True
    except OSError as exc:
        # Locked, still being written or gone: read again next time.
        return path, mtime_ns, size, None, f"{path.name}: {exc}", False


class RecognitionHistoryIndex:
    """Persisted list summaries keyed by path + mtime_ns + size + OUTCOME_VERSION."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path is not None else None
        self.entries: dict[str, tuple[int, int, RecognitionSummary | None, str | None]] = {}
        self.dirty = False
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.path is None:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if (not isinstance(payload, dict) or payload.get("schema") != HISTORY_INDEX_SCHEMA
                or payload.get("outcome_version") != OUTCOME_VERSION):
            return
        rows = payload.get("entries")
        for key, row in (rows.items() if isinstance(rows, dict) else ()):
            try:
                summary = RecognitionSummary.from_json(Path(key), row["summary"]) if row.get("summary") else None
                error = str(row["error"]) if row.get("error") else None
                if summary is None and error is None:
                    continue
                self.entries.setdefault(str(key), (int(row["mtime_ns"]), int(row["size"]), summary, error))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue

    def lookup(self, path: Path, mtime_ns: int, size: int):
        row = self.entries.get(str(path))
        return row if row is not None and row[0] == mtime_ns and row[1] == size else None

    def put(self, path: Path, mtime_ns: int, size: int, summary, error) -> None:
        self.entries[str(path)] = (int(mtime_ns), int(size), summary, error)
        self.dirty = True

    def payload(self, keep: set[str]) -> dict[str, Any]:
        entries = {}
        for key, (mtime_ns, size, summary, error) in self.entries.items():
            if key not in keep:
                continue
            row: dict[str, Any] = {"mtime_ns": mtime_ns, "size": size}
            if summary is not None:
                row["summary"] = summary.to_json()
            else:
                row["error"] = error
            entries[key] = row
        return {"schema": HISTORY_INDEX_SCHEMA, "outcome_version": OUTCOME_VERSION, "entries": entries}

    @staticmethod
    def write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass


def assemble_summaries(listing, index: RecognitionHistoryIndex):
    """Records for a listing: the current summary, else the previous one of a
    report that changed and is being re-read. Deduplicated like the loader."""
    records: list[RecognitionSummary] = []
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for path, mtime_ns, size in listing:
        row = index.entries.get(str(path))
        if row is None:
            continue
        summary, error = row[2], row[3]
        if summary is not None:
            if summary.identity in seen:
                continue
            seen.add(summary.identity)
            records.append(summary)
        elif error and row[0] == mtime_ns and row[1] == size:
            errors.append(error)
    records.sort(key=lambda item: item.completed_sort, reverse=True)
    return records, errors


HISTORY_QSS = NAVIGATION_QSS + f"""
QWidget#historyRoot {{ background: {BACKGROUND}; color: {INK}; }}
QFrame#historySidebar {{ background: {SURFACE_MUTED}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#historyContent {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QWidget#historyListHost {{ background: transparent; }}
QFrame#historyCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#historyCard:hover {{ background: #fffaf2; border-color: #b9cdb4; }}
QLabel#historyTitle {{ color: {INK}; font-size: 23px; font-weight: 700; font-family: "Source Han Sans SC", "思源黑体", "Microsoft YaHei UI"; }}
QLabel#historyItemTitle {{ color: {INK}; font-size: 15px; font-weight: 700; }}
QLabel#historyPipeline {{ color: {INK}; font-size: 13px; font-weight: 600; }}
QLabel#historyMuted {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
QFrame#historyMetric {{ background: #f7f3eb; border: 1px solid #ebe2d5; border-radius: 9px; }}
QLabel#historyMetricLabel {{ color: {MUTED}; font-size: 10px; font-weight: 600; }}
QLabel#historyMetricValue {{ color: {INK}; font-size: 12px; font-weight: 700; }}
QFrame#historyPipelineStrip {{ background: {GREEN_SUBTLE}; border: 1px solid #d4e1cf; border-radius: 10px; }}
QLabel#historyMetaChip {{ background: #f4f0e7; color: #59574f; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 600; }}
QLabel#historyMetaChipWarn {{ background: {AMBER_SOFT}; color: #8b612b; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#historyMetaChipReview {{ background: #fbefda; color: #8a6125; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#historyStatusGood {{ background: {GREEN_SOFT}; color: {GREEN}; border-radius: 9px; padding: 4px 9px; font-weight: 700; }}
QLabel#historyStatusWarn {{ background: {AMBER_SOFT}; color: #8b612b; border-radius: 9px; padding: 4px 9px; font-weight: 700; }}
QLabel#historyStatusError {{ background: #f6e5e0; color: {CORAL}; border-radius: 9px; padding: 4px 9px; font-weight: 700; }}
QPushButton#historyPrimary {{ background: {GREEN}; color: white; border: 1px solid {GREEN}; border-radius: 10px; padding: 8px 14px; font-weight: 700; }}
QPushButton#historyPrimary:hover {{ background: #43754b; }}
QPushButton#historySecondary {{ background: {SURFACE}; color: {INK}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 13px; font-weight: 600; }}
QPushButton#historySecondary:hover {{ background: {GREEN_SUBTLE}; border-color: #9fbd9f; }}
QPushButton#historyDetails {{ background: #eef5eb; color: {GREEN}; border: 1px solid #b9cdb4; border-radius: 10px; padding: 8px 14px; font-weight: 700; }}
QPushButton#historyDetails:hover {{ background: #e1eddd; border-color: #8eaf8e; }}
QPushButton#historyRawToggle {{ background: transparent; color: #a85f52; border: 1px solid #d6a297; border-radius: 9px; padding: 7px 11px; font-weight: 600; }}
QPushButton#historyRawToggle:hover {{ background: #fbefeb; border-color: #bf7d70; }}
QLineEdit#historySearch {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 10px; }}
QPlainTextEdit#historyRaw {{ background: #202522; color: #d8ddd8; border: 1px solid #3f4943; border-radius: 10px; padding: 10px 12px; selection-background-color: #496256; }}
QTableWidget#historyStages {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: {BORDER}; selection-background-color: {GREEN_SOFT}; }}
QHeaderView::section {{ background: #f5f0e7; color: {MUTED}; border: 0; border-bottom: 1px solid {BORDER}; padding: 8px; font-weight: 600; }}
QLabel#historySummaryPill {{ background: #f4f0e7; color: #59574f; border-radius: 9px; padding: 4px 9px; font-size: 11px; font-weight: 600; }}
QLabel#historyReviewPill {{ background: #fbefda; color: #8a6125; border-radius: 9px; padding: 4px 9px; font-size: 11px; font-weight: 700; }}
QLabel#historyStageStatusGood {{ background: #e5f0e2; color: #47734c; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#historyStageStatusWarn {{ background: #fbefda; color: #8a6125; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#historyStageStatusError {{ background: #f6e5e0; color: #a95447; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
QLabel#historyResourcePill {{ background: #f3f1ec; color: #66645d; border-radius: 7px; padding: 3px 7px; font-size: 11px; }}
QFrame#historyInfoSection {{ background: #faf8f3; border: 1px solid #ebe3d7; border-radius: 11px; }}
QFrame#historyReviewSection {{ background: #fffaf0; border: 1px solid #ead3a8; border-left: 3px solid #c89543; border-radius: 11px; }}
QLabel#historySectionTitle {{ color: {INK}; font-size: 14px; font-weight: 700; }}
QLabel#historyConfigKey {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QLabel#historyConfigValue {{ color: {INK}; font-size: 12px; font-weight: 600; }}
"""


# retheme_qss 的全局字面量表覆盖了标准暖色调；这里补齐识别记录页特有的
# 状态色/边框色到语义 token，让四种主题下都不残留浅色硬编码。
_HISTORY_TOKEN_OVERRIDES = {
    # hover/边框（绿系）
    "#b9cdb4": "border_strong",
    "#d4e1cf": "border",
    "#8eaf8e": "accent",
    "#eef5eb": "accent_soft",
    "#e1eddd": "accent_soft",
    "#e5f0e2": "accent_soft",
    "#47734c": "accent",
    # 面板/中性的填充与文字
    "#ebe2d5": "border",
    "#ebe3d7": "border",
    "#f4f0e7": "timeline",
    "#f3f1ec": "panel",
    "#59574f": "text_muted",
    "#66645d": "text_muted",
    # 警示（琥珀系）
    "#8b612b": "warning",
    "#8a6125": "warning",
    "#fbefda": "warning_soft",
    "#ead3a8": "warning_soft",
    "#c89543": "warning",
    "#fffaf0": "surface_elevated",
    # 危险（珊瑚系）
    "#f6e5e0": "danger_soft",
    "#a95447": "danger",
    "#a85f52": "danger",
    "#d6a297": "danger",
    "#fbefeb": "danger_soft",
    "#bf7d70": "danger",
    # 原始 JSON 查看器（刻意保持深色代码面）
    "#202522": "media",
    "#3f4943": "border_strong",
    "#d8ddd8": "text_secondary",
    "#496256": "selected",
}


def build_history_page_qss(theme=None) -> str:
    from twobyteasr.qss_retheme import retheme_qss
    from twobyteasr.theme_manager import theme_key
    from twobyteasr.ui_theme import theme_definition

    # theme_definition() 无参时返回默认主题而非当前主题；必须经 theme_key() 解析。
    active = theme or theme_definition(theme_key())
    qss = HISTORY_QSS
    for literal, token in _HISTORY_TOKEN_OVERRIDES.items():
        qss = qss.replace(literal, getattr(active, token, literal))
    from twobyteasr.design.semantic_qss import build_semantic_qss
    return retheme_qss(qss, active) + build_semantic_qss(active)


def _duration_label(seconds: float) -> str:
    """Human-readable media/run duration without long decimal-heavy prose."""
    value = max(0.0, float(seconds or 0))
    if value >= 60:
        whole = int(round(value))
        return f"{whole // 60}:{whole % 60:02d}"
    if not value:
        return translate("未记录", current_language())
    unit = "seconds" if current_language() == "en" else "秒"
    return f"{value:.1f} {unit}"


class HistoryMetric(QFrame):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("historyMetric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(1)
        eyebrow = QLabel(label)
        eyebrow.setObjectName("historyMetricLabel")
        number = QLabel(value)
        number.setObjectName("historyMetricValue")
        layout.addWidget(eyebrow)
        layout.addWidget(number)


class HistoryCard(QFrame):
    requested = Signal(object)

    def __init__(self, record: RecognitionRecord, parent=None):
        super().__init__(parent)
        language = current_language()
        self.record = record
        self.setObjectName("historyCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(record.media_name)
        title.setObjectName("historyItemTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        status = QLabel(translate(record.status_label, language))
        status.setObjectName(
            "historyStatusError" if record.status_label == "失败" else
            ("historyStatusWarn" if record.status in {"partial", "unknown", "cancelled"} else "historyStatusGood")
        )
        top.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
        button = QPushButton(translate("查看详情", language))
        button.setObjectName("historyDetails")
        button.clicked.connect(lambda: self.requested.emit(record))
        top.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top)

        metrics = QHBoxLayout()
        metrics.setSpacing(6)
        metrics.addWidget(HistoryMetric(translate("完成时间", language), record.completed_at))
        metrics.addWidget(HistoryMetric(translate("总耗时", language), _duration_label(record.elapsed_seconds)))
        if record.media_seconds:
            metrics.addWidget(HistoryMetric(translate("素材时长", language), _duration_label(record.media_seconds)))
        cue_count = int(getattr(record, "cue_count", 0) or 0)
        if cue_count:
            metrics.addWidget(HistoryMetric("字幕", f"{cue_count} 条"))
        metrics.addStretch(1)
        layout.addLayout(metrics)

        pipeline_box = QFrame()
        pipeline_box.setObjectName("historyPipelineStrip")
        pipeline_layout = QHBoxLayout(pipeline_box)
        pipeline_layout.setContentsMargins(10, 6, 10, 6)
        pipeline_layout.setSpacing(7)
        role = QLabel(translate("模型链路", language))
        role.setObjectName("historyMuted")
        pipeline_layout.addWidget(role)
        pipeline = QLabel(f"{record.primary_model}  →  {record.timeline_model}  →  {record.review_model}")
        pipeline.setObjectName("historyPipeline")
        pipeline_layout.addWidget(pipeline, 1)
        layout.addWidget(pipeline_box)

        metadata = QHBoxLayout()
        metadata.setSpacing(6)
        ai = f"AI: {record.ai_model}" if language == "en" and record.ai_model else (
            f"AI：{record.ai_model}" if record.ai_model else translate("AI：未启用", language)
        )
        metadata_items = [
            (ai, False),
            (f"{record.glossary_count} " + ("term libraries" if language == "en" else "个词库"), False),
        ]
        if record.review_count:
            metadata_items.append((
                f"{record.review_count} " + ("review items" if language == "en" else "項目" if language == "ja" else "项待检查"),
                False,
            ))
        if record.anomaly_count:
            metadata_items.append((
                f"{record.anomaly_count} " + ("issues" if language == "en" else "个问题"),
                True,
            ))
        for text, warning in metadata_items:
            chip = QLabel(text)
            is_review = text.endswith(("项待检查", "review items", "項目"))
            chip.setObjectName(
                "historyMetaChipWarn" if warning else
                ("historyMetaChipReview" if is_review else "historyMetaChip")
            )
            metadata.addWidget(chip)
        metadata.addStretch(1)
        layout.addLayout(metadata)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.requested.emit(self.record)
        super().mouseReleaseEvent(event)


class _ProportionalStageTable(QTableWidget):
    _ratios = (0.46, 0.14, 0.13, 0.27)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(0, self.viewport().width())
        for column, ratio in enumerate(self._ratios):
            self.setColumnWidth(column, max(60, int(width * ratio)))


_RAW_HIGHLIGHT_MAX_LINES = 20000


class _JsonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._formats = {}
        for name, color in {
            "key": "#83c7df", "string": "#9fce9c", "number": "#e1b96c",
            "literal": "#c7a0df", "null": "#8f9992", "punctuation": "#c9ceca",
        }.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[name] = fmt

    def highlightBlock(self, text: str):
        for name, pattern in (
            ("string", r'"(?:\\.|[^"\\])*"'),
            ("key", r'"(?:\\.|[^"\\])*"(?=\s*:)'),
            ("number", r'(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'),
            ("literal", r'\b(?:true|false)\b'),
            ("null", r'\bnull\b'),
            ("punctuation", r'[{}\[\],:]'),
        ):
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), self._formats[name])


def _history_section(title: str, object_name: str = "historyInfoSection") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(object_name)
    box = QVBoxLayout(frame)
    box.setContentsMargins(13, 11, 13, 12)
    box.setSpacing(7)
    heading = QLabel()
    bind_text(heading, title)
    heading.setObjectName("historySectionTitle")
    box.addWidget(heading)
    return frame, box


def _history_pill(text: str, object_name: str = "historySummaryPill") -> QLabel:
    label = QLabel()
    bind_text(label, text)
    label.setObjectName(object_name)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


def _history_table_pill(text: str, object_name: str, tooltip: str = "") -> QWidget:
    host = QWidget()
    box = QHBoxLayout(host)
    box.setContentsMargins(6, 3, 6, 3)
    label = _history_pill(text, object_name)
    if tooltip:
        label.setToolTip(tooltip)
    box.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
    box.addStretch(1)
    return host


def _history_config_row(label: str, value: str, *, translate_value=False) -> QWidget:
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(10)
    key = QLabel()
    bind_text(key, label)
    key.setObjectName("historyConfigKey")
    key.setWordWrap(True)
    key.setFixedWidth(118)
    content = QLabel(value)
    if translate_value or hasattr(value, "source"):
        bind_text(content, value)
    content.setObjectName("historyConfigValue")
    content.setWordWrap(True)
    content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.addWidget(key)
    box.addWidget(content, 1)
    return row


def _history_model_name(role: str, record: RecognitionRecord, models: dict[str, Any]) -> str:
    if role == "primary":
        return "MOSS-Transcribe-Diarize" if record.primary_model == "MOSS" else record.primary_model
    if role == "timeline":
        return "FireRedASR2-AED" if record.timeline_model == "FireRed" else record.timeline_model
    qwen_model = str(models.get("qwen_asr_model") or "")
    match = re.search(r"Qwen3-ASR-([\d.]+B)", qwen_model, re.IGNORECASE)
    if record.review_model == "Qwen3-ASR" and match:
        return f"Qwen3-ASR {match.group(1)}"
    return record.review_model


class RecognitionHistoryDetail(QWidget):
    """Product summary with the complete report isolated in a developer view."""

    result_requested = Signal(object)

    def __init__(self, record: RecognitionRecord, parent=None):
        super().__init__(parent)
        self.record = record
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(13)

        title = QLabel(record.media_name)
        title.setObjectName("historyTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        result = _dict(record.payload.get("result"))
        summary = QHBoxLayout()
        summary.setSpacing(6)
        status_object = (
            "historyStatusError" if record.status_label == "失败" else
            ("historyStatusWarn" if record.status in {"partial", "unknown", "cancelled"} else "historyStatusGood")
        )
        summary.addWidget(_history_pill(record.status_label, status_object))
        summary.addWidget(_history_pill(tr("本文件耗时 {duration}", duration=_duration_label(record.elapsed_seconds))))
        if record.media_seconds:
            summary.addWidget(_history_pill(tr("素材时长 {duration}", duration=_duration_label(record.media_seconds))))
        cue_count = int(result.get("cue_count") or 0)
        if cue_count:
            summary.addWidget(_history_pill(tr("{count} 条字幕", count=cue_count)))
        if record.outcome.review_issue_count:
            summary.addWidget(_history_pill(tr("{count} 项待检查问题", count=record.outcome.review_issue_count), "historyReviewPill"))
        summary.addStretch(1)
        layout.addLayout(summary)

        outcome_section, outcome_box = _history_section("处理结果")
        outcome_box.addWidget(_history_config_row("核心处理", record.outcome.status_label, translate_value=True))
        outcome_box.addWidget(_history_config_row("文字校对", record.outcome.polish_label, translate_value=True))
        outcome_box.addWidget(_history_config_row("联网核验", record.outcome.search_label, translate_value=True))
        if record.outcome.search_reason:
            reason = QLabel()
            bind_text(reason, record.outcome.search_reason)
            reason.setObjectName("historyMuted")
            reason.setWordWrap(True)
            outcome_box.addWidget(reason)
        if record.outcome.processed_records:
            outcome_box.addWidget(_history_config_row("处理记录", tr("{count} 条处理记录", count=record.outcome.processed_records)))
        outcome_box.addWidget(_history_config_row("实际接受修改", tr("{count} 处文字修改", count=record.outcome.accepted_edits)))
        if record.outcome.review_issue_count:
            outcome_box.addWidget(_history_config_row("待检查问题", tr("{count} 项检查问题", count=record.outcome.review_issue_count)))
        if record.outcome.result_usable and _dict(result.get("outputs")).get("project"):
            self.open_result_button = QPushButton()
            bind_text(self.open_result_button, "打开识别结果")
            self.open_result_button.setObjectName("historyPrimary")
            self.open_result_button.setToolTip(str(result["outputs"]["project"]))
            self.open_result_button.clicked.connect(lambda: self.result_requested.emit(record))
            outcome_box.addWidget(self.open_result_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(outcome_section)

        stages = _list(record.payload.get("stages"))
        self.stage_table = _ProportionalStageTable(len(stages), 4)
        self.stage_table.setObjectName("historyStages")
        self.stage_table.setHorizontalHeaderLabels(["阶段", "状态", "耗时", "资源"])
        self.stage_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stage_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stage_table.verticalHeader().hide()
        self.stage_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stage_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        status_labels = {
            "completed": ("完成", "historyStageStatusGood"),
            "fallback": ("降级", "historyStageStatusWarn"),
            "failed": ("失败", "historyStageStatusError"),
            "skipped": ("跳过", "historyStageStatusWarn"),
        }
        for row, stage_value in enumerate(stages):
            stage = _dict(stage_value)
            label = str(stage.get("label") or f"阶段 {stage.get('index', row + 1)}")
            self.stage_table.setItem(row, 0, QTableWidgetItem(label))
            raw_status = str(stage.get("status") or "unknown").lower()
            status_text, status_name = status_labels.get(raw_status, (raw_status or "未知", "historyResourcePill"))
            self.stage_table.setCellWidget(
                row, 1, _history_table_pill(status_text, status_name)
            )
            self.stage_table.setItem(row, 2, QTableWidgetItem(_duration_label(float(stage.get("elapsed_seconds") or 0))))
            resource_text = str(stage.get("resource") or "—")
            self.stage_table.setCellWidget(
                row, 3, _history_table_pill(resource_text, "historyResourcePill", resource_text)
            )
            self.stage_table.setRowHeight(row, 28)
        table_height = (
            self.stage_table.horizontalHeader().height()
            + sum(self.stage_table.rowHeight(row) for row in range(len(stages)))
            + self.stage_table.frameWidth() * 2
        )
        self.stage_table.setFixedHeight(max(58, table_height))
        layout.addWidget(self.stage_table)

        settings = _dict(record.payload.get("settings"))
        models = _dict(settings.get("models"))
        switches = _dict(settings.get("switches"))
        profile = _dict(settings.get("content_profile"))
        config, config_box = _history_section("本次配置")
        config_values = [
            ("主力转写", _history_model_name("primary", record, models)),
            ("时间轴", _history_model_name("timeline", record, models)),
            ("文字复核", _history_model_name("review", record, models)),
        ]
        if record.ai_model:
            provider = str(models.get("polish_provider") or models.get("group_provider") or "").strip()
            base_url = str(models.get("polish_base_url") or models.get("group_base_url") or "").lower()
            provider_label = "DeepSeek" if "deepseek" in provider.lower() or "deepseek" in base_url else provider
            config_values.append(("AI", f"{provider_label} · {record.ai_model}" if provider_label else record.ai_model))
        if "enabled_glossary_ids" in profile or profile.get("domain_terms"):
            config_values.append(("词库", f"{record.glossary_count} 个"))
        coverage = switches.get("dialogue_coverage_mode")
        if coverage:
            config_values.append(("对白覆盖", {
                "all_dialogue": "全部对白", "host_priority": "主播优先", "host_only": "仅主播",
            }.get(str(coverage), str(coverage))))
        for key, value in config_values:
            if str(value).strip() and str(value) not in {"未知", "未启用"}:
                config_box.addWidget(_history_config_row(key, str(value)))
        layout.addWidget(config)

        outputs = _dict(result.get("outputs"))
        output_items = []
        if outputs.get("txt"):
            output_items.append("TXT ✓")
        if outputs.get("srt"):
            output_items.append("SRT ✓")
        track_count = len(_list(outputs.get("speaker_outputs")))
        if track_count:
            output_items.append(f"分轨 SRT · {track_count}")
        if output_items:
            output, output_box = _history_section("输出")
            output_row = QHBoxLayout()
            output_row.setSpacing(6)
            for item in output_items:
                output_row.addWidget(_history_pill(item))
            output_row.addStretch(1)
            output_box.addLayout(output_row)
            layout.addWidget(output)

        if record.problems:
            warning = QLabel("警告 / Error\n" + "\n".join(f"• {item}" for item in record.problems))
            warning.setObjectName("historyStatusError" if record.status_label == "失败" else "historyStatusWarn")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        review_items = [
            _dict(item) for item in _list(record.payload.get("review_items"))
            if _review_severity(_dict(item)) == "review"
        ]
        if review_items:
            review, review_box = _history_section(tr("可复核信息 {count} 项", count=len(review_items)), "historyReviewSection")
            for category, count in Counter(str(item.get("category") or "待复核项") for item in review_items).most_common():
                review_box.addWidget(_history_config_row(category, tr("{count} 项问题", count=count)))
            segment_items = [item for item in review_items if any(item.get(key) not in (None, "") for key in ("cue_id", "segment_id", "timestamp", "text"))]
            if segment_items:
                self.review_detail_button = QPushButton("展开分段详情")
                self.review_detail_button.setObjectName("historySecondary")
                review_box.addWidget(self.review_detail_button, 0, Qt.AlignmentFlag.AlignLeft)
                review_details = QLabel()
                review_details.setObjectName("historyMuted")
                review_details.setWordWrap(True)
                review_details.hide()
                review_box.addWidget(review_details)

                def toggle_review_details(_checked=False, items=segment_items, label=review_details):
                    # Long evidence lists are only formatted when asked for.
                    if not label.text():
                        label.setText("\n".join(
                            f"• {item.get('category') or '待复核项'} · "
                            f"{item.get('cue_id', item.get('segment_id', item.get('timestamp', '')))} · "
                            f"{item.get('text') or item.get('message') or item.get('detail') or ''}"
                            for item in items
                        ))
                    label.setVisible(not label.isVisible())
                    (bind_text(self.review_detail_button, '收起分段详情') if label.isVisible()
                     else bind_text(self.review_detail_button, '展开分段详情'))
                self.review_detail_button.clicked.connect(toggle_review_details)
            layout.addWidget(review)

        raw_actions = QHBoxLayout()
        self.raw_button = QPushButton("</> 查看原始 JSON")
        self.raw_button.setObjectName("historyRawToggle")
        self.copy_button = QPushButton("复制 JSON")
        self.copy_button.setObjectName("historySecondary")
        self.copy_button.hide()
        raw_actions.addWidget(self.raw_button)
        raw_actions.addWidget(self.copy_button)
        raw_actions.addStretch(1)
        layout.addLayout(raw_actions)

        # The redacted JSON text, its editor and the highlighter are built on
        # the first "查看原始 JSON" (a 3 MB report is ~110k lines to format,
        # load and highlight); opening the details only shows the summary.
        self._raw_text: str | None = None
        self._details_layout = layout
        self.summary_ready = True
        self.raw_button.clicked.connect(self._toggle_raw)
        self.copy_button.clicked.connect(self._copy_raw)

    @property
    def raw_text(self) -> str:
        if self._raw_text is None:
            self._raw_text = json.dumps(redact_report_payload(self.record.payload), ensure_ascii=False, indent=2)
        return self._raw_text

    def _ensure_raw_view(self) -> QPlainTextEdit:
        view = vars(self).get("raw_view")
        if view is not None:
            return view
        view = QPlainTextEdit()
        view.setObjectName("historyRaw")
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setFont(QFont("Cascadia Mono", 10))
        view.setPlainText(self.raw_text)
        view.setMinimumHeight(300)
        view.hide()
        if view.document().blockCount() <= _RAW_HIGHLIGHT_MAX_LINES:
            # QSyntaxHighlighter re-highlights the whole document at once.
            self._raw_highlighter = _JsonHighlighter(view.document())
        self._details_layout.addWidget(view)
        if self.window().property("_uiZoomApplied") is not None:
            from .ui_zoom import apply_to
            apply_to(view)
        self.raw_view = view
        return view

    def _toggle_raw(self):
        view = self._ensure_raw_view()
        visible = not view.isVisible()
        view.setVisible(visible)
        self.copy_button.setVisible(visible)
        (bind_text(self.raw_button, '</> 收起原始 JSON') if visible else bind_text(self.raw_button, '</> 查看原始 JSON'))

    def _copy_raw(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.raw_text)


class RecognitionHistoryPage(QWidget):
    recognition_requested = Signal()
    workshop_requested = Signal()
    terms_requested = Signal()
    result_requested = Signal(object)
    # (generation, payload) from the background report reader.
    _parsed = Signal(int, object)
    _repaired = Signal(object)
    # (request id, parsed record or None, error) from the detail reader.
    _detail_loaded = Signal(int, object, object)

    PAGE_SIZE = 20

    def __init__(self, report_root: Path, parent=None, *, extra_roots: tuple[Path, ...] | list[Path] = (),
                 index_path: Path | None = None):
        super().__init__(parent)
        self.report_root = Path(report_root)
        self.extra_roots = [Path(root) for root in extra_roots if Path(root) != self.report_root]
        self.records: list[RecognitionSummary] = []
        self._display: list[RecognitionSummary] = []
        self._cards: list[HistoryCard] = []
        self._cards_by_path: dict[Path, HistoryCard] = {}
        self._card_rows: dict[HistoryCard, QWidget] = {}
        self._index = RecognitionHistoryIndex(default_history_index_path() if index_path is None else index_path)
        # Older audits clear this mapping to force a re-read of every report.
        self._record_cache = self._index.entries
        self._listing: list[tuple[Path, int, int]] = []
        self._list_errors: list[str] = []
        self._errors: list[str] = []
        self._rendered_language = ""
        self._generation = 0
        self._jobs: set[object] = set()
        self._inflight: set[tuple[str, int, int]] = set()
        self._transient: dict[str, str] = {}
        self._job_counter = 0
        self._more_scheduled = False
        self._render_pending = False
        self._shown_once = False
        self._built_limit = self.PAGE_SIZE
        self._notice = ""
        self._repairing = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_index)
        self._parsed.connect(self._on_parsed)
        self._repaired.connect(self._on_repaired)
        # Open detail dialogs waiting for their report, by request id. The
        # worker thread only ever sees the page signal, the id and the path;
        # it never holds the dialog or any of its children.
        self._detail_requests: dict[int, object] = {}
        self._detail_request_counter = 0
        self._detail_loaded.connect(self._on_detail_loaded)
        self.setObjectName("historyRoot")
        from .ui_zoom import set_sheet
        set_sheet(self, build_history_page_qss())
        self._build()
        self.refresh()

    def restore_active_navigation(self):
        self.nav.set_active("history")

    def refresh_theme_palette(self) -> None:
        from .ui_zoom import set_sheet
        set_sheet(self, build_history_page_qss())

    def background_busy(self) -> bool:
        """True while reports are being read or the index written."""
        return bool(self._jobs) or self._save_timer.isActive()

    def _roots(self) -> list[Path]:
        roots = [Path(self.report_root)]
        for extra in self.extra_roots:
            if Path(extra) not in roots:
                roots.append(Path(extra))
        return roots

    def _build(self):
        from .ui_navigation import WorkspaceSidebar

        language = current_language()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        sidebar = WorkspaceSidebar("history", object_name="historySidebar")
        nav = sidebar.navigation
        nav.recognition_requested.connect(self.recognition_requested)
        nav.workshop_requested.connect(self.workshop_requested)
        nav.terms_requested.connect(self.terms_requested)
        self.nav = nav
        self.sidebar = sidebar
        side = sidebar.body
        side.addStretch(1)
        self.summary = QLabel()
        self.summary.setObjectName("historyMuted")
        self.summary.setWordWrap(True)
        side.addWidget(self.summary)
        outer.addWidget(sidebar)

        content = QFrame()
        content.setObjectName("historyContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(10)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(translate("识别记录", language))
        title.setObjectName("historyTitle")
        style_workspace_page_title(title)
        title_box.addWidget(title)
        note = QLabel(translate("从现有字幕任务 JSON 报告汇总；详情按需展开，密钥不会显示。", language))
        note.setObjectName("historyMuted")
        title_box.addWidget(note)
        header.addLayout(title_box, 1)
        self.repair_button = QPushButton(translate("重新扫描 / 修复记录索引", language))
        self.repair_button.setObjectName("historySecondary")
        self.repair_button.setIcon(qta.icon("fa5s.database", color=GREEN))
        bind_text(self.repair_button, translate('从旧安装目录等已知位置找回历史识别报告（复制到稳定目录，不改动原始文件）', language), property='toolTip')
        self.repair_button.clicked.connect(self._repair_records)
        header.addWidget(self.repair_button)
        refresh = QPushButton(translate("刷新记录", language))
        refresh.setObjectName("historySecondary")
        refresh.setIcon(qta.icon("fa5s.sync-alt", color=GREEN))
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        body.addLayout(header)
        self.search = QLineEdit()
        self.search.setObjectName("historySearch")
        bind_text(self.search, translate('搜索素材、模型、AI 或状态', language), property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        body.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll = scroll
        host = QWidget()
        host.setObjectName("historyListHost")
        self.cards_layout = QVBoxLayout(host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.empty = QFrame()
        self.empty.setObjectName("historyInfoSection")
        self.empty.setMinimumHeight(220)
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setContentsMargins(24, 28, 24, 28)
        empty_layout.addStretch(1)
        self.empty_title = QLabel(translate("还没有识别记录", language))
        self.empty_title.setObjectName("historyItemTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_note = QLabel(
            translate("完成第一条字幕任务后，任务状态、模型组合和审核结果会出现在这里。", language)
        )
        self.empty_note.setObjectName("historyMuted")
        self.empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_note.setWordWrap(True)
        empty_layout.addWidget(self.empty_note)
        self.empty_start = QPushButton(translate("开始识别", language))
        self.empty_start.setObjectName("historyPrimary")
        self.empty_start.setIcon(qta.icon("fa5s.play", color="white"))
        self.empty_start.clicked.connect(self.recognition_requested)
        empty_layout.addWidget(self.empty_start, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self.cards_layout.addWidget(self.empty)
        # Cards are built a page at a time as the list scrolls; search and the
        # record count always cover every record (data-level filter).
        self.more_button = QPushButton()
        self.more_button.setObjectName("historySecondary")
        self.more_button.clicked.connect(self._show_more)
        self.more_button.hide()
        self.cards_layout.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.cards_layout.addStretch(1)
        scroll.setWidget(host)
        scroll.verticalScrollBar().valueChanged.connect(self._maybe_show_more)
        scroll.verticalScrollBar().rangeChanged.connect(lambda _low, _high: self._maybe_show_more())
        body.addWidget(scroll, 1)
        outer.addWidget(content, 1)

    # ------------------------------------------------------------- loading
    def refresh(self):
        """Re-read the report folders (explicit refresh, language change, task end).

        Only reports whose path / mtime / size changed are parsed: small ones
        at once within a short budget, the rest in a background thread.
        """
        self._reload(inline_budget=_INLINE_PARSE_BUDGET_S)

    def _reload(self, *, inline_budget: float = 0.0, force: bool = False) -> None:
        self._index.load()
        self._generation += 1
        generation = self._generation
        listing, list_errors = list_report_files(self._roots())
        self._listing, self._list_errors = listing, list_errors
        pending: list[tuple[Path, int, int]] = []
        deadline = time.perf_counter() + max(0.0, inline_budget)
        for path, mtime_ns, size in listing:
            if not force and self._index.lookup(path, mtime_ns, size) is not None:
                continue
            if (str(path), mtime_ns, size) in self._inflight:
                continue
            if not force and size <= _INLINE_PARSE_BYTES and time.perf_counter() < deadline:
                self._store(parse_listed_report(path, mtime_ns, size))
            else:
                pending.append((path, mtime_ns, size))
        if pending:
            self._start_parse(generation, pending)
        elif self._index.dirty:
            self._save_timer.start()
        self._render()

    def _store(self, row) -> None:
        path, mtime_ns, size, summary, error, cacheable = row
        if cacheable:
            self._index.put(path, mtime_ns, size, summary, error)
            self._transient.pop(str(path), None)
        else:
            # A locked or vanished file is reported but never cached; the
            # next refresh reads it again.
            self._transient[str(path)] = error

    def _new_job(self, kind: str):
        self._job_counter += 1
        job = (kind, self._job_counter)
        self._jobs.add(job)
        return job

    def _start_parse(self, generation: int, pending) -> None:
        job = self._new_job("parse")
        for path, mtime_ns, size in pending:
            self._inflight.add((str(path), mtime_ns, size))
        signal = self._parsed

        def work():
            rows, last = [], time.perf_counter()
            try:
                for path, mtime_ns, size in pending:
                    rows.append(parse_listed_report(path, mtime_ns, size))
                    if time.perf_counter() - last > 0.25:
                        signal.emit(generation, {"job": job, "rows": rows, "final": False})
                        rows, last = [], time.perf_counter()
            finally:
                try:
                    signal.emit(generation, {"job": job, "rows": rows, "final": True,
                                             "pending": [(str(p), m, s) for p, m, s in pending]})
                except RuntimeError:
                    pass  # the page was closed meanwhile

        threading.Thread(target=work, daemon=True, name="history-report-reader").start()

    def _check_on_entry(self) -> None:
        """Entering the page: stat the report folders off the GUI thread and
        read only new or changed reports (a finished, failed or cancelled task
        shows up without a full rescan)."""
        if any(job[0] == "entry" for job in self._jobs):
            return
        generation = self._generation
        job = self._new_job("entry")
        known = {key: (row[0], row[1]) for key, row in self._index.entries.items()}
        inflight = set(self._inflight)
        roots = self._roots()
        signal = self._parsed

        def work():
            listing, errors, rows = [], [], []
            try:
                listing, errors = list_report_files(roots)
                for path, mtime_ns, size in listing:
                    key = str(path)
                    if known.get(key) == (mtime_ns, size) or (key, mtime_ns, size) in inflight:
                        continue
                    rows.append(parse_listed_report(path, mtime_ns, size))
            finally:
                try:
                    signal.emit(generation, {"job": job, "rows": rows, "final": True,
                                             "listing": listing, "list_errors": errors})
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True, name="history-entry-check").start()

    def _on_parsed(self, generation: int, payload) -> None:
        for row in payload.get("rows", ()):
            self._store(row)
        if payload.get("final"):
            self._jobs.discard(payload.get("job"))
            for key in payload.get("pending", ()):
                self._inflight.discard(tuple(key))
            if payload.get("save"):
                return
            if self._index.dirty:
                self._save_timer.start()
        if "listing" in payload:
            if generation != self._generation:
                return  # a newer reload owns the listing; its rows were kept
            if payload["listing"] == self._listing and payload["list_errors"] == self._list_errors \
                    and not payload.get("rows"):
                return
            self._listing, self._list_errors = payload["listing"], payload["list_errors"]
        elif not payload.get("rows") and not payload.get("final"):
            return
        if self._shown_once and not self.isVisible():
            # The user left the page: keep the data, build cards when shown.
            self._render_pending = True
            return
        self._render()

    def _save_index(self) -> None:
        if self._jobs:
            self._save_timer.start()
            return
        if not self._index.dirty or self._index.path is None:
            return
        self._index.dirty = False
        payload = self._index.payload({str(path) for path, _mtime, _size in self._listing})
        target = self._index.path
        job = self._new_job("save")
        signal = self._parsed

        def work():
            try:
                RecognitionHistoryIndex.write(target, payload)
            except OSError:
                pass  # a cache: the next change writes it again
            finally:
                try:
                    signal.emit(-1, {"job": job, "rows": [], "final": True, "save": True})
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True, name="history-index-writer").start()

    # ------------------------------------------------------------- display
    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_once:
            QTimer.singleShot(0, self._check_on_entry)
        self._shown_once = True
        if self._render_pending:
            QTimer.singleShot(0, self._render)

    def _render(self) -> None:
        self._render_pending = False
        records, errors = assemble_summaries(self._listing, self._index)
        listed = {str(path) for path, _mtime, _size in self._listing}
        errors = [*self._list_errors, *errors,
                  *(error for key, error in self._transient.items() if key in listed)]
        language = current_language()
        if (
            records == self.records
            and errors == self._errors
            and language == self._rendered_language
        ):
            self._update_summary()
            self._apply_filter()
            return
        present = {record.path: record for record in records}
        for path, card in list(self._cards_by_path.items()):
            if present.get(path) != card.record or language != self._rendered_language:
                self._detach_card(card)
        self.records = records
        self._errors = errors
        self._rendered_language = language
        self._update_summary()
        self._apply_filter()

    def _update_summary(self) -> None:
        language = current_language()
        loading = sum(1 for _key in self._inflight)
        errors = self._errors
        if language == "en":
            summary = (
                f"{len(self.records)} task records\n"
                f"{sum(record.has_anomaly for record in self.records)} with warnings or anomalies"
            )
            if errors:
                summary += f"\n{len(errors)} unreadable files"
        else:
            summary = (
                f"{len(self.records)} 条任务记录\n"
                f"{sum(record.has_anomaly for record in self.records)} 条含警告或异常"
            ) + (f"\n{len(errors)} 个文件无法读取" if errors else "")
        if loading:
            summary += "\n" + tr("正在读取 {count} 份报告…", count=loading)
        if self._notice:
            summary += "\n" + self._notice
        self.summary.setText(summary)
        # Each unreadable file is named; the page itself stays usable.
        self.summary.setToolTip("\n".join(errors[:12]) + ("\n…" if len(errors) > 12 else ""))

    def _detach_card(self, card: HistoryCard) -> None:
        row = self._card_rows.pop(card, card)
        self._cards_by_path.pop(card.record.path, None)
        self.cards_layout.removeWidget(row)
        row.hide()
        row.setParent(None)
        if row is not card:
            card.setParent(None)
        row.deleteLater()
        card.deleteLater()

    def _make_card(self, record) -> HistoryCard:
        card = HistoryCard(record)
        card.setMaximumWidth(16777215)
        card.setMinimumWidth(520)
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        card.requested.connect(self._show_detail)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addWidget(card, 1)
        self._card_rows[card] = row
        self._cards_by_path[record.path] = card
        if self.property("_uiZoomApplied") is not None:
            # The page was scaled before this card existed.
            from .ui_zoom import apply_to
            apply_to(row)
        return card

    @staticmethod
    def _haystack(record) -> str:
        return " ".join(
            (
                record.media_name,
                record.primary_model,
                record.timeline_model,
                record.review_model,
                record.ai_model,
                record.status_label,
                *record.problems,
            )
        ).casefold()

    def _search_changed(self, _text=""):
        self._built_limit = self.PAGE_SIZE
        self._apply_filter()

    def _apply_filter(self, _text=""):
        query = self.search.text().strip().casefold()
        display = [record for record in self.records if not query or query in self._haystack(record)]
        self._display = display
        wanted = display[:self._built_limit]
        cards: list[HistoryCard] = []
        for index, record in enumerate(wanted):
            card = self._cards_by_path.get(record.path)
            if card is not None and card.record != record:
                self._detach_card(card)
                card = None
            if card is None:
                card = self._make_card(record)
            row = self._card_rows[card]
            if self.cards_layout.indexOf(row) != index:
                self.cards_layout.insertWidget(index, row)
            if row.isHidden():
                row.show()
            cards.append(card)
        wanted_paths = {record.path for record in wanted}
        for path, card in self._cards_by_path.items():
            if path not in wanted_paths:
                row = self._card_rows.get(card, card)
                if not row.isHidden():
                    row.hide()
        self._cards = cards
        remaining = len(display) - len(wanted)
        if remaining > 0:
            self.more_button.setText(tr("显示更多（还有 {count} 条）", count=remaining))
            self.more_button.show()
        else:
            self.more_button.hide()
        if not display and self.records:
            bind_text(self.empty_title, translate('没有符合搜索条件的记录', current_language()))
            bind_text(self.empty_note, translate('换个关键词，或清空搜索查看全部任务记录。', current_language()))
            self.empty_start.hide()
        else:
            bind_text(self.empty_title, translate('还没有识别记录', current_language()))
            bind_text(self.empty_note, translate('完成第一条字幕任务后，任务状态、模型组合和审核结果会出现在这里。', current_language()))
            self.empty_start.show()
        self.empty.setVisible(not display)

    def _show_more(self) -> None:
        self._more_scheduled = False
        if len(self._display) <= self._built_limit:
            return
        self._built_limit += self.PAGE_SIZE
        self._apply_filter()

    def _maybe_show_more(self, _value=None) -> None:
        if len(self._display) <= self._built_limit or not self.isVisible():
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() <= self.scroll.viewport().height() and not self._more_scheduled:
            self._more_scheduled = True
            QTimer.singleShot(0, self._show_more)

    # ------------------------------------------------------------- repair
    def _repair_records(self):
        if self._repairing:
            return
        language = current_language()
        self._repairing = True
        self.repair_button.setEnabled(False)
        bind_text(self.repair_button, translate('正在扫描…', language))
        from . import reporting

        target = self.report_root
        extra = [
            *self.extra_roots,
            *(
                reporting.REPORT_ROOT,
                *(reporting.LEGACY_REPORT_ROOTS or ()),
            ),
        ]
        job = self._new_job("repair")
        signal = self._repaired

        def work():
            try:
                result = repair_recognition_history(target, extra_roots=extra)
            except Exception as exc:  # noqa: BLE001 - shown to the user, never fatal
                result = {"found": 0, "imported": 0, "duplicates": 0, "failed": 1, "failed_files": [str(exc)]}
            result["job"] = job
            try:
                signal.emit(result)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="history-repair").start()

    def _on_repaired(self, result) -> None:
        self._jobs.discard(result.pop("job", None))
        self._repairing = False
        language = current_language()
        self.repair_button.setEnabled(True)
        bind_text(self.repair_button, translate('重新扫描 / 修复记录索引', language))
        if language == "en":
            summary = (
                f"Found {result['found']} legacy reports · imported {result['imported']}"
                f" · duplicates {result['duplicates']} · failed {result['failed']}"
            )
        else:
            summary = (
                f"找到旧报告 {result['found']} 份：新导入 {result['imported']}、"
                f"重复 {result['duplicates']}、失败 {result['failed']}"
            )
        if result.get("failed_files"):
            summary += "（" + "、".join(result["failed_files"][:3]) + "…）"
        self._notice = summary
        # Explicit repair rebuilds the summary index from every report, in the
        # background; the current cards stay until fresh summaries arrive.
        self._reload(force=True)

    # ------------------------------------------------------------- details
    def _show_detail(self, record):
        from twobyteasr.ui import SpringDialog

        dialog = SpringDialog(self)
        language = current_language()
        bind_text(dialog, f"{translate('识别记录', language)}｜{record.media_name}", property='windowTitle')
        dialog.resize(880, 700)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        placeholder = QLabel(tr("正在读取报告…"))
        placeholder.setObjectName("historyMuted")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        scroll.setWidget(placeholder)
        layout.addWidget(scroll, 1)
        close = QPushButton(translate("关闭", language))
        close.setObjectName("historyPrimary")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

        def install(full, error):
            from shiboken6 import isValid
            if not isValid(dialog) or not isValid(scroll):
                return
            if full is None:
                if isValid(placeholder):
                    placeholder.setText(tr("无法读取这份报告：{error}", error=error or ""))
                return
            detail = RecognitionHistoryDetail(full)
            detail.result_requested.connect(lambda selected: (dialog.accept(), self.result_requested.emit(selected)))
            scroll.setWidget(detail)
            if dialog.property("_uiZoomApplied") is not None:
                from .ui_zoom import apply_to
                apply_to(detail)

        request = None
        if isinstance(record, RecognitionRecord):
            install(record, None)
        else:
            # Only the selected report is read; a large one off the GUI thread.
            path = Path(record.path)
            try:
                size = path.stat().st_size
            except OSError as exc:
                size, early_error = -1, f"{path.name}: {exc}"
            else:
                early_error = None

            def load():
                try:
                    if size > _MAX_REPORT_BYTES:
                        raise ValueError("报告超过 12 MB")
                    return parse_recognition_report(path), None
                except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
                    return None, f"{path.name}: {exc}"

            if early_error is not None:
                install(None, early_error)
            elif size <= _INLINE_DETAIL_BYTES:
                install(*load())
            else:
                self._detail_request_counter += 1
                request = self._detail_request_counter
                self._detail_requests[request] = install
                signal = self._detail_loaded

                def work(request=request, signal=signal, load=load):
                    full, error = load()
                    try:
                        signal.emit(request, full, error)
                    except RuntimeError:
                        pass  # the page itself is gone

                threading.Thread(target=work, daemon=True, name="history-detail-reader").start()
        dialog.exec()
        if request is not None:
            # Closed before the report arrived: a late result is dropped.
            self._detail_requests.pop(request, None)
        # Each opened report used to stay alive as a hidden child dialog of the
        # page (~150 widgets and the whole report text per opening).
        dialog.deleteLater()

    def _on_detail_loaded(self, request: int, full, error) -> None:
        """Queued on the GUI thread; installs only into a dialog still open."""
        install = self._detail_requests.pop(request, None)
        if install is not None:
            install(full, error)
