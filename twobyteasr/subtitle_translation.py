"""Subtitle translation: records, batching, validation.

Sources are the recognised languages (Chinese, Japanese, English); targets are
Simplified/Traditional Chinese, English, Japanese and Korean, any target whose
language differs from the source (2026-10-14; before: Japanese/English ->
Chinese only).

Pure logic (no Qt). The project stores one translation record per cue id in
``generation_metadata["translation_records"]``; the old
``generation_metadata["translations"]`` {cue_id: text} dict stays the render
view that ASS / preview / timeline read, and is rebuilt from the records by
``sync_render_view``.

A record never stores whether it is current. Its status is derived from the
sha of the Japanese text it was made from versus the cue's current text, so
undo/redo of text edits, splits and merges stay correct without the cue
commands knowing about translations.

The provider is injected by the caller (the configured "polish" client); this
module never chooses a model. ``translate`` is synchronous and only reads a
``TranslationSource`` snapshot, so it can run on a worker thread; every
project change goes through ``apply_translation_result`` / ``set_manual``,
which return a (before, after) snapshot pair for one undo command.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

RECORDS_KEY = "translation_records"
RENDER_KEY = "translations"
RECORDS_VERSION = 1
PROMPT_VERSION = "ja-zh-subtitle-v1"
EN_PROMPT_VERSION = "en-zh-subtitle-v1"   # 2026-10-14: English sources
DEFAULT_TARGET = "zh-Hans"
TARGETS = ("zh-Hans", "zh-Hant", "en", "ja", "ko")
# Native names: shown as they are in every UI language, like the UI language menu.
TARGET_LABELS = {"zh-Hans": "简体中文", "zh-Hant": "繁體中文", "en": "English", "ja": "日本語", "ko": "한국어"}
TARGET_LANGUAGE = {"zh-Hans": "zh", "zh-Hant": "zh", "en": "en", "ja": "ja", "ko": "ko"}
SOURCE_LANGUAGES = ("zh", "ja", "en")
LANGUAGE_NAMES = {"zh": "Chinese", "ja": "Japanese", "en": "English", "ko": "Korean"}
# File-name suffix of a translation layer (``stem.<suffix>.srt``).
TARGET_SUFFIX = {"zh-Hans": "zh", "zh-Hant": "zh-Hant", "en": "en", "ja": "ja", "ko": "ko"}


def source_language_of(language: str = "") -> str:
    """The translation source language; projects without a record count as Japanese (the first pair)."""
    return language if language in SOURCE_LANGUAGES else "ja"


def targets_for(language: str = "") -> tuple[str, ...]:
    """Targets offered for a source: every target in another language."""
    source = source_language_of(language)
    return tuple(target for target in TARGETS if TARGET_LANGUAGE[target] != source)


def same_language(language: str, target: str) -> bool:
    """True when ``target`` is the source language itself (nothing to translate)."""
    return TARGET_LANGUAGE.get(normalize_target(target)) == source_language_of(language)


def prompt_version_for(language: str = "", target: str = DEFAULT_TARGET) -> str:
    """Japanese/English -> Chinese keep their prompts; other pairs share one generic prompt."""
    if TARGET_LANGUAGE.get(normalize_target(target)) == "zh":
        return EN_PROMPT_VERSION if language == "en" else PROMPT_VERSION
    return f"{source_language_of(language)}-{normalize_target(target)}-subtitle-v1"
MAX_PREVIOUS = 5
MAX_HISTORY = 50
BATCH_PROBLEM_KEY = "*"
PROVIDER_STAGE = "subtitle_translation"
BUDGET_OPERATION = "polish"
MAX_GLOSSARY_PAIRS_PER_BATCH = 80

UNTRANSLATED = "untranslated"
DONE = "done"
NEEDS_UPDATE = "needs_update"
FAILED = "failed"
MANUAL = "manual"
STATUSES = (UNTRANSLATED, DONE, NEEDS_UPDATE, FAILED, MANUAL)

ORIGIN_AI = "ai"
ORIGIN_MANUAL = "manual"

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["id", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

_SPLIT_ID = re.compile(r"^(?P<parent>.+)-split-[0-9a-f]{8}$")
_TIMESTAMP = re.compile(
    r"-->|\b\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?\b|\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]"
)
_TARGET_ALIASES = {
    "zh-hans": "zh-Hans", "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-sg": "zh-Hans",
    "hans": "zh-Hans", "simplified": "zh-Hans", "简体中文": "zh-Hans",
    "zh-hant": "zh-Hant", "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
    "hant": "zh-Hant", "traditional": "zh-Hant", "繁體中文": "zh-Hant", "繁体中文": "zh-Hant",
    "en": "en", "en-us": "en", "en-gb": "en", "english": "en", "英语": "en", "英文": "en",
    "ja": "ja", "ja-jp": "ja", "jp": "ja", "japanese": "ja", "日语": "ja", "日文": "ja", "日本語": "ja",
    "ko": "ko", "ko-kr": "ko", "kr": "ko", "korean": "ko", "韩语": "ko", "韩文": "ko", "한국어": "ko",
}


# ---------------------------------------------------------------------------
# Small helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_source(text: Any) -> str:
    """Line endings unified and outer whitespace stripped (sha basis)."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def source_sha(text: Any) -> str:
    return hashlib.sha256(normalize_source(text).encode("utf-8")).hexdigest()[:16]


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def clean_translation(text: Any) -> str:
    """Strip each line and drop blank lines (a blank line ends an SRT block)."""
    lines = [line.strip() for line in normalize_source(text).split("\n")]
    return "\n".join(line for line in lines if line)


def normalize_target(target: Any) -> str:
    value = str(target or "").strip()
    if not value:
        return DEFAULT_TARGET
    resolved = _TARGET_ALIASES.get(value.casefold().replace("_", "-"))
    if resolved is None:
        raise ValueError(f"unsupported translation target: {value}")
    return resolved


def normalize_glossary(pairs: Any) -> tuple[tuple[str, str], ...]:
    """(source term, target term) pairs; accepts tuples or mappings."""
    if isinstance(pairs, Mapping):
        pairs = list(pairs.items())
    result: dict[str, str] = {}
    for item in pairs or ():
        if isinstance(item, Mapping):
            ja = item.get("ja", item.get("source", item.get("term", "")))
            zh = item.get("zh", item.get("target", item.get("translation", "")))
        else:
            try:
                ja, zh = item
            except (TypeError, ValueError):
                continue
        ja, zh = str(ja or "").strip(), str(zh or "").strip()
        if ja and zh:
            result[ja] = zh
    return tuple(sorted(result.items()))


def glossary_digest(pairs: Any) -> str:
    normalized = normalize_glossary(pairs)
    return _digest(normalized) if normalized else ""


def _is_hiragana(code: int) -> bool:
    return 0x3041 <= code <= 0x309F


def _is_katakana(code: int) -> bool:
    return 0x30A1 <= code <= 0x30FA or code in (0x30FC, 0x30FD, 0x30FE) or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D


def _is_han(code: int) -> bool:
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0xF900 <= code <= 0xFAFF
            or 0x20000 <= code <= 0x2FA1F)


def script_counts(text: str) -> dict[str, int]:
    counts = {"hiragana": 0, "katakana": 0, "han": 0, "other": 0}
    for char in str(text or ""):
        code = ord(char)
        if char == "々":  # 々 is Japanese-only
            counts["hiragana"] += 1
        elif _is_hiragana(code):
            counts["hiragana"] += 1
        elif _is_katakana(code):
            counts["katakana"] += 1
        elif _is_han(code):
            counts["han"] += 1
        elif unicodedata.category(char).startswith(("L", "N")):
            counts["other"] += 1
    return counts


def _content(text: str) -> str:
    return "".join(
        char.casefold() for char in str(text or "")
        if not char.isspace() and not unicodedata.category(char).startswith(("P", "Z", "S"))
    )


# ---------------------------------------------------------------------------
# Records container


def _metadata(project) -> dict:
    meta = getattr(project, "generation_metadata", None)
    if not isinstance(meta, dict):
        meta = {}
        project.generation_metadata = meta
    return meta


def _empty_container(target: str = DEFAULT_TARGET) -> dict:
    return {"version": RECORDS_VERSION, "target": target, "records": {}, "history": []}


def _valid_container(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("records"), dict)


def records_of(project) -> dict[str, dict]:
    """The stored records (live dict; empty when the project has none)."""
    container = _metadata(project).get(RECORDS_KEY)
    return container["records"] if _valid_container(container) else {}


def container_target(project) -> str:
    container = _metadata(project).get(RECORDS_KEY)
    try:
        return normalize_target(container.get("target")) if _valid_container(container) else DEFAULT_TARGET
    except ValueError:
        return DEFAULT_TARGET


def _record(text: str, source_text: str, *, origin: str, status: str = DONE, target: str = DEFAULT_TARGET,
            model: str = "", provider: str = "", prompt_version: str = "", glossary: str = "",
            context_sha: str = "", previous: Sequence[Mapping] = (), **extra: Any) -> dict:
    record = {
        "text": str(text or ""),
        "source_text": str(source_text or ""),
        "source_sha": source_sha(source_text),
        "origin": origin,
        "status": status,
        "target": target,
        "model": str(model or ""),
        "provider": str(provider or ""),
        "prompt_version": str(prompt_version or ""),
        "glossary_digest": str(glossary or ""),
        "context_sha": str(context_sha or ""),
        "updated_at": _now(),
        "previous": [dict(item) for item in previous][:MAX_PREVIOUS],
    }
    record.update({key: value for key, value in extra.items() if value is not None})
    return record


def _pushed_previous(old: Mapping | None) -> list[dict]:
    if not isinstance(old, Mapping):
        return []
    history = [dict(item) for item in old.get("previous", ()) if isinstance(item, Mapping)]
    if str(old.get("text") or ""):
        entry = {key: old.get(key, "") for key in ("text", "origin", "source_text", "updated_at")}
        history.insert(0, entry)
    return history[:MAX_PREVIOUS]


def _append_history(container: dict, entry: Mapping) -> None:
    history = container.get("history")
    if not isinstance(history, list):
        history = []
    history.append({"at": _now(), **dict(entry)})
    container["history"] = history[-MAX_HISTORY:]


def _migrated_container(meta: Mapping, cues: Sequence) -> tuple[dict | None, bool]:
    """Container after legacy migration/reconciliation, on a copy.

    Returns ``(container_or_None, changed)``. ``None`` means the project has no
    translations at all and nothing is created.
    """
    stored = meta.get(RECORDS_KEY)
    legacy = meta.get(RENDER_KEY)
    legacy = legacy if isinstance(legacy, Mapping) else {}
    if not _valid_container(stored) and not any(str(v or "").strip() for v in legacy.values()):
        return None, False
    container = copy.deepcopy(stored) if _valid_container(stored) else _empty_container()
    changed = not _valid_container(stored)
    container.setdefault("version", RECORDS_VERSION)
    container.setdefault("target", DEFAULT_TARGET)
    if not isinstance(container.get("history"), list):
        container["history"] = []
    records = container["records"]
    texts = {str(cue.id): str(cue.text or "") for cue in cues}
    target = container_target_value(container)
    adopted = 0
    for cue_id, value in legacy.items():
        cue_id, text = str(cue_id), str(value or "")
        if not text.strip():
            continue
        record = records.get(cue_id)
        if not isinstance(record, Mapping):
            # Old {cue_id: text} data: origin unknown -> protected as manual.
            records[cue_id] = _record(text, texts.get(cue_id, ""), origin=ORIGIN_MANUAL, target=target,
                                      legacy=True)
            adopted += 1
        elif cue_id in texts and str(record.get("text") or "") != text:
            # The render view was edited outside the records (legacy command
            # path): that is a manual translation of the current Japanese.
            records[cue_id] = _record(text, texts[cue_id], origin=ORIGIN_MANUAL, target=target,
                                      previous=_pushed_previous(record))
            adopted += 1
    if adopted:
        changed = True
        _append_history(container, {"kind": "migrate", "records": adopted})
    return container, changed


def container_target_value(container: Mapping) -> str:
    try:
        return normalize_target(container.get("target"))
    except ValueError:
        return DEFAULT_TARGET


def migrate(project) -> bool:
    """Create/reconcile records from the legacy render dict. Idempotent.

    Old projects with only ``translations`` get one record per entry with
    origin "manual" and ``legacy: True`` (source sha = current cue text).
    A render-view entry that differs from its record (written by the legacy
    ``SetCueTranslationCommand``) is adopted as a manual edit. Absence from
    the view never deletes a record. Projects without translations are left
    untouched.
    """
    meta = _metadata(project)
    container, changed = _migrated_container(meta, list(getattr(project, "cues", ()) or ()))
    if changed and container is not None:
        meta[RECORDS_KEY] = container
    return changed


def _ensure_container(project) -> dict:
    migrate(project)
    meta = _metadata(project)
    if not _valid_container(meta.get(RECORDS_KEY)):
        meta[RECORDS_KEY] = _empty_container()
    return meta[RECORDS_KEY]


# ---------------------------------------------------------------------------
# Derived status


def status_of(record: Mapping | None, text: str, *, target: str | None = None) -> str:
    if not isinstance(record, Mapping):
        return UNTRANSLATED
    if record.get("status") == FAILED:
        return FAILED
    if not str(record.get("text") or "").strip():
        return UNTRANSLATED
    if str(record.get("source_sha") or "") != source_sha(text):
        return NEEDS_UPDATE
    if target and record.get("target") and str(record.get("target")) != normalize_target(target):
        return NEEDS_UPDATE
    if record.get("origin") == ORIGIN_MANUAL:
        return MANUAL
    return DONE


def cue_status(project, cue, *, target: str | None = None) -> str:
    """untranslated / done / needs_update / failed / manual (derived)."""
    if isinstance(cue, str):
        cue = next((item for item in project.cues if item.id == cue), None)
        if cue is None:
            return UNTRANSLATED
    return status_of(records_of(project).get(cue.id), cue.text, target=target)


def statuses(project, *, target: str | None = None) -> dict[str, str]:
    records = records_of(project)
    return {cue.id: status_of(records.get(cue.id), cue.text, target=target) for cue in project.cues}


def ids_with_status(project, wanted: Iterable[str], *, target: str | None = None) -> list[str]:
    """Cue ids (timeline order, non-empty text) whose status is in ``wanted``."""
    wanted = set(wanted)
    records = records_of(project)
    ordered = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    return [cue.id for cue in ordered if normalize_source(cue.text)
            and status_of(records.get(cue.id), cue.text, target=target) in wanted]


def status_counts(project, *, target: str | None = None) -> dict[str, int]:
    counts = {name: 0 for name in STATUSES}
    records = records_of(project)
    for cue in project.cues:
        if normalize_source(cue.text):
            counts[status_of(records.get(cue.id), cue.text, target=target)] += 1
    return counts


def translation_view(project, *, target: str | None = None) -> dict[str, dict]:
    """{cue_id: {text, status, origin, target}} for current cues (no mutation).

    Uses the migrated/reconciled records without writing them back, so it is
    safe for export and old projects.
    """
    meta = getattr(project, "generation_metadata", None) or {}
    cues = list(getattr(project, "cues", ()) or ())
    container, _changed = _migrated_container(meta, cues)
    records = container["records"] if container else {}
    default_target = container_target_value(container) if container else DEFAULT_TARGET
    view = {}
    for cue in cues:
        record = records.get(cue.id)
        status = status_of(record, cue.text, target=target)
        record = record if isinstance(record, Mapping) else {}
        view[cue.id] = {
            "text": str(record.get("text") or ""),
            "status": status,
            "origin": str(record.get("origin") or ""),
            "target": str(record.get("target") or default_target),
        }
    return view


def sync_render_view(project) -> dict[str, str]:
    """Rewrite ``translations`` = {cue_id: text} for current cues with text.

    needs_update / failed records keep showing their last text (the UI flags
    them). Records of cue ids that are gone stay stored (undo may bring them
    back) but are excluded from the view. Legacy edits of the view are first
    reconciled into the records (``migrate``).
    """
    migrate(project)
    return _rebuild_view(project)


def _rebuild_view(project) -> dict[str, str]:
    records = records_of(project)
    view = {}
    for cue in project.cues:
        record = records.get(cue.id)
        if isinstance(record, Mapping):
            text = str(record.get("text") or "")
            if text.strip():
                view[cue.id] = text
    meta = _metadata(project)
    if view or _valid_container(meta.get(RECORDS_KEY)) or RENDER_KEY in meta:
        meta[RENDER_KEY] = view
    return view


# ---------------------------------------------------------------------------
# Snapshots (one undo command per change)


def snapshot(project) -> dict[str, Any]:
    meta = _metadata(project)
    return {key: copy.deepcopy(meta[key]) if key in meta else None for key in (RECORDS_KEY, RENDER_KEY)}


def restore_snapshot(project, state: Mapping[str, Any]) -> None:
    meta = _metadata(project)
    for key in (RECORDS_KEY, RENDER_KEY):
        value = state.get(key)
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = copy.deepcopy(value)


def set_manual(project, cue_id: str, text: str) -> tuple[dict, dict]:
    """A person's translation of the current Japanese; returns (before, after).

    An empty text clears the translation (status becomes untranslated); the
    replaced text is kept in ``previous``.
    """
    cue_id = str(cue_id)
    cue = next((item for item in project.cues if item.id == cue_id), None)
    if cue is None:
        raise KeyError(cue_id)
    before = snapshot(project)
    container = _ensure_container(project)
    records = container["records"]
    old = records.get(cue_id)
    value = clean_translation(text)
    if (isinstance(old, Mapping) and old.get("origin") == ORIGIN_MANUAL and str(old.get("text") or "") == value
            and old.get("source_sha") == source_sha(cue.text) and old.get("status") != FAILED
            and not old.get("legacy")):
        _rebuild_view(project)
        return before, snapshot(project)
    records[cue_id] = _record(value, cue.text, origin=ORIGIN_MANUAL, target=container_target_value(container),
                              previous=_pushed_previous(old), cleared=True if not value else None)
    _rebuild_view(project)
    return before, snapshot(project)


# ---------------------------------------------------------------------------
# Split / merge semantic mapping


def _receipts(project) -> Mapping:
    state = getattr(project, "studio_state", None) or {}
    timeline = state.get("caption_timeline") if isinstance(state, Mapping) else None
    instances = timeline.get("instances") if isinstance(timeline, Mapping) else None
    return instances if isinstance(instances, Mapping) else {}


def _parent_entry(cue_id: str, record: Mapping) -> dict:
    return {"cue_id": cue_id, "source_text": str(record.get("source_text") or ""),
            "translation": str(record.get("text") or ""), "origin": str(record.get("origin") or "")}


def _candidates(cues: Sequence, records: Mapping, receipts: Mapping, *, target: str | None = None) -> list[dict]:
    ordered = sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    current = {cue.id for cue in ordered}
    split_parents = {match.group("parent") for cue_id in current if (match := _SPLIT_ID.match(cue_id))}

    def has_text(record):
        return isinstance(record, Mapping) and bool(str(record.get("text") or "").strip())

    orphans = [(rid, rec) for rid, rec in records.items()
               if rid not in current and has_text(rec) and normalize_source(rec.get("source_text"))]
    result = []
    for cue in ordered:
        status = status_of(records.get(cue.id), cue.text, target=target)
        if status not in (NEEDS_UPDATE, UNTRANSLATED) or not normalize_source(cue.text):
            continue
        kind, parents = "", []
        match = _SPLIT_ID.match(cue.id)
        if match:
            ancestor = match.group("parent")
            while ancestor:
                if has_text(records.get(ancestor)):
                    parents.append(ancestor)
                    break
                step = _SPLIT_ID.match(ancestor)
                ancestor = step.group("parent") if step else ""
            kind = "split" if parents else ""
        elif status == NEEDS_UPDATE and cue.id in split_parents:
            kind, parents = "split", [cue.id]
        if not kind:
            # Merge: the current text is exactly the concatenation of the
            # source texts of its own record and of records whose cues are gone.
            own = records.get(cue.id)
            pool = ([(cue.id, own)] if has_text(own) else []) + orphans
            remainder, chain = normalize_source(cue.text), []
            while remainder and pool:
                best = None
                for rid, rec in pool:
                    piece = normalize_source(rec.get("source_text"))
                    if piece and remainder.startswith(piece) and rid not in chain and (
                            best is None or len(piece) > len(best[1])):
                        best = (rid, piece)
                if best is None:
                    break
                chain.append(best[0])
                remainder = remainder[len(best[1]):].lstrip()
            if len(chain) >= 2 and not remainder:
                kind, parents = "merge", chain
            else:
                receipt = receipts.get(cue.id) if isinstance(receipts, Mapping) else None
                sources = receipt.get("source_cue_ids") if isinstance(receipt, Mapping) else None
                sources = [str(item) for item in sources or () if str(item)]
                linked = [sid for sid in dict.fromkeys(sources) if has_text(records.get(sid))]
                if len(sources) >= 2 and linked:
                    kind, parents = "merge", linked
        if kind and parents:
            result.append({
                "cue_id": cue.id, "kind": kind, "status": status, "source_text": cue.text,
                "parents": [_parent_entry(pid, records[pid]) for pid in dict.fromkeys(parents)],
            })
    by_parent: dict[str, list[str]] = {}
    for item in result:
        for parent in item["parents"]:
            by_parent.setdefault(parent["cue_id"], []).append(item["cue_id"])
    for item in result:
        item["group"] = list(dict.fromkeys(
            cue_id for parent in item["parents"] for cue_id in by_parent.get(parent["cue_id"], ())))
    return result


def split_merge_candidates(project, *, target: str | None = None) -> list[dict]:
    """needs_update/untranslated cues created by a split or merge.

    Each item: ``{cue_id, kind: "split"|"merge", status, source_text,
    parents: [{cue_id, source_text, translation, origin}], group}``. The parent
    translation is reference only; the caller retranslates these cues (the
    translation is never divided by character ratio nor copied to halves).
    """
    meta = getattr(project, "generation_metadata", None) or {}
    container, _ = _migrated_container(meta, list(project.cues))
    records = container["records"] if container else {}
    return _candidates(list(project.cues), records, _receipts(project), target=target)


# ---------------------------------------------------------------------------
# Snapshot of the project for a worker thread


@dataclass(frozen=True)
class SourceCue:
    id: str
    text: str
    start_ms: int
    end_ms: int
    speaker_id: str
    speaker_name: str
    index: int


@dataclass(frozen=True)
class TranslationSource:
    cues: tuple[SourceCue, ...]
    records: Mapping[str, Mapping]
    references: Mapping[str, tuple[dict, ...]]
    language: str = ""

    def cue(self, cue_id: str) -> SourceCue | None:
        return self._index().get(cue_id)

    def _index(self) -> dict[str, SourceCue]:
        index = self.__dict__.get("_by_id")
        if index is None:
            index = {cue.id: cue for cue in self.cues}
            object.__setattr__(self, "_by_id", index)
        return index


def translation_source(project) -> TranslationSource:
    """Immutable copy of what translation needs; call on the UI thread."""
    speakers = {speaker.id: str(speaker.name or "") for speaker in getattr(project, "speakers", ())}
    ordered = [cue for cue in sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
               if normalize_source(cue.text)]
    cues = tuple(SourceCue(cue.id, str(cue.text), int(cue.start_ms), int(cue.end_ms), str(cue.speaker_id),
                           speakers.get(cue.speaker_id, ""), index) for index, cue in enumerate(ordered))
    meta = getattr(project, "generation_metadata", None) or {}
    container, _ = _migrated_container(meta, list(project.cues))
    records = copy.deepcopy(container["records"]) if container else {}
    references = {item["cue_id"]: tuple(item["parents"])
                  for item in _candidates(list(project.cues), records, _receipts(project))}
    try:
        from .language_rules import project_language
        language = project_language(project)
    except Exception:  # noqa: BLE001 - language is advisory here
        language = ""
    return TranslationSource(cues, records, references, language)


def _as_source(project_or_source) -> TranslationSource:
    if isinstance(project_or_source, TranslationSource):
        return project_or_source
    return translation_source(project_or_source)


# ---------------------------------------------------------------------------
# Batching


@dataclass(frozen=True)
class BatchLine:
    id: str
    text: str
    speaker: str
    translate: bool
    translation: str = ""
    reference: tuple[dict, ...] = ()
    gap_before: bool = False
    speaker_id: str = ""


@dataclass(frozen=True)
class TranslationBatch:
    lines: tuple[BatchLine, ...]

    @property
    def items(self) -> tuple[BatchLine, ...]:
        return tuple(line for line in self.lines if line.translate)

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(line.id for line in self.lines if line.translate)

    @property
    def context(self) -> tuple[BatchLine, ...]:
        return tuple(line for line in self.lines if not line.translate)

    @property
    def source_chars(self) -> int:
        return sum(len(line.text) for line in self.items)

    def source_text(self, cue_id: str) -> str:
        return next((line.text for line in self.lines if line.id == cue_id), "")


def _current_translation(source: TranslationSource, cue: SourceCue,
                         known: Mapping[str, str] | None) -> str:
    if known and cue.id in known:
        return str(known[cue.id])
    record = source.records.get(cue.id)
    if status_of(record, cue.text) in (DONE, MANUAL):
        return str(record.get("text") or "")
    return ""


def _speaker_label(cue: SourceCue) -> str:
    name = cue.speaker_name.strip()
    return name if name and name != cue.speaker_id else ""


def plan_batches(project, cue_ids: Iterable[str] | None, *, max_items: int = 40, max_chars: int = 2400,
                 context_cues: int = 3, known_translations: Mapping[str, str] | None = None
                 ) -> list[TranslationBatch]:
    """Timeline-ordered batches of target cues with read-only neighbours.

    Each batch holds at most ``max_items`` targets and ``max_chars`` source
    characters (a single longer cue gets its own batch). Context = up to
    ``context_cues`` non-target cues before/after each target, with their
    existing current translations.
    """
    source = _as_source(project)
    max_items, context_cues = max(1, int(max_items)), max(0, int(context_cues))
    wanted = None if cue_ids is None else {str(item) for item in cue_ids}
    targets = [cue for cue in source.cues if wanted is None or cue.id in wanted]
    groups: list[list[SourceCue]] = []
    chars = 0
    for cue in targets:
        if not groups or len(groups[-1]) >= max_items or (groups[-1] and chars + len(cue.text) > max_chars):
            groups.append([])
            chars = 0
        groups[-1].append(cue)
        chars += len(cue.text)
    batches = []
    for group in groups:
        target_index = {cue.index for cue in group}
        indexes = set(target_index)
        for cue in group:
            indexes.update(range(max(0, cue.index - context_cues),
                                 min(len(source.cues), cue.index + context_cues + 1)))
        lines, previous = [], None
        for index in sorted(indexes):
            cue = source.cues[index]
            is_target = index in target_index
            lines.append(BatchLine(
                id=cue.id, text=cue.text, speaker=_speaker_label(cue), translate=is_target,
                translation="" if is_target else _current_translation(source, cue, known_translations),
                reference=tuple(source.references.get(cue.id, ())) if is_target else (),
                gap_before=previous is not None and index != previous + 1,
                speaker_id=cue.speaker_id,
            ))
            previous = index
        batches.append(TranslationBatch(tuple(lines)))
    return batches


# ---------------------------------------------------------------------------
# Prompt

_SYSTEM_PROMPT = """你是日语游戏实况视频的字幕翻译。把日语口语字幕翻译成自然、地道的{label}字幕。
规则：
1. 只翻译 lines 里 translate 为 true 的行：每个这样的 id 必须输出且只输出一条译文，按 output_ids 的顺序输出。translate 为 false 的行只是上下文（可能附已有译文 translation），不要输出它们。
2. 不要合并、拆分或调换字幕。一句话被拆成几条时，每条只翻译它自己的原文对应的部分。
3. 不要输出时间码、序号、注释、解释、原文或罗马音，只输出译文本身。
4. 人名、角色名、技能名、道具名等专有名词按 glossary（日文 → 中文）统一译法。glossary 只用于翻译，不表示日文原文有错，不要改写或纠正日文。
5. 保留说话人的语气和情绪（惊叹、吐槽、口头禅），用简短的字幕口吻；语气词意译即可。
6. 译文必须是{label}，不要保留日文假名；无法意译的片假名专有名词可以音译或保留。{script_rule}
7. 带 reference 的行是由一条已翻译字幕拆分或合并而来：reference 给出原来那条（或几条）的日文与译文，只用于保持用词一致；只翻译本行原文的意思，不要照抄整句译文。
只输出 JSON：{{"items":[{{"id":"<原样的 id>","translation":"<译文>"}}]}}"""

_EN_SYSTEM_PROMPT = """你是英语游戏实况视频的字幕翻译。把英语口语字幕翻译成自然、地道的{label}字幕。
规则：
1. 只翻译 lines 里 translate 为 true 的行：每个这样的 id 必须输出且只输出一条译文，按 output_ids 的顺序输出。translate 为 false 的行只是上下文（可能附已有译文 translation），不要输出它们。
2. 不要合并、拆分或调换字幕。一句英文被拆成几条时，每条只翻译它自己的原文对应的部分，语序可以按中文习惯在本条内调整。
3. 不要输出时间码、序号、注释、解释或英文原文，只输出译文本身。
4. 人名、角色名、技能名、道具名等专有名词按 glossary（英文 → 中文）统一译法。glossary 只用于翻译，不表示英文原文有错，不要改写或纠正英文。没有对照的游戏名、角色名用通行中文译名，没有通行译名时保留英文。
5. 保留说话人的语气和情绪（惊叹、吐槽、口头禅、梗），用简短的字幕口吻；俚语、脏话按语气意译，不逐词直译。
6. 译文必须是{label}，不要输出英文整句；GG、OK、HP、DPS 之类缩写和专有名词可以保留。{script_rule}
7. 带 reference 的行是由一条已翻译字幕拆分或合并而来：reference 给出原来那条（或几条）的英文与译文，只用于保持用词一致；只翻译本行原文的意思，不要照抄整句译文。
只输出 JSON：{{"items":[{{"id":"<原样的 id>","translation":"<译文>"}}]}}"""

_SCRIPT_RULES = {
    "zh-Hans": "使用简体字。",
    "zh-Hant": "直接用繁體字書寫（不要先寫簡體再轉換），用詞符合繁體中文讀者習慣。",
}

# Pairs without a Chinese target (2026-10-14): one prompt, written in English
# so every model reads the rules the same way whatever the two languages are.
_GENERIC_SYSTEM_PROMPT = """You translate the subtitles of {source_name} game live-stream videos into natural, idiomatic {target_name} subtitles.
The original subtitles come from automatic speech recognition and may contain small mistakes; translate the most likely intended meaning.
Rules:
1. Translate only the lines whose "translate" is true: output exactly one translation for each such id, in the order of output_ids. Lines with "translate": false are context only (they may carry an existing "translation"); do not output them.
2. Do not merge, split or reorder subtitles. When one sentence is split over several lines, translate only the part in each line's own text; word order may be adjusted inside a line.
3. Output only the translation: no timecodes, numbers, notes, explanations, romanization or original text.
4. Use the glossary ({source_name} -> {target_name}) for names of people, characters, skills and items. It is only for translation; it does not mean the original is wrong, so never rewrite or correct the original. Without a glossary entry use the established {target_name} name; if there is none, keep the original name or transliterate it.
5. Keep the speaker's tone and emotion (exclamations, banter, catchphrases, memes) in short, spoken subtitle style; translate slang by meaning, not word for word.
6. Write the translation in {target_name}. {target_rule} Abbreviations such as GG, OK, HP, DPS may stay as they are.
7. A line with "reference" was split from or merged with already translated subtitles: the reference gives the original line(s) and their translation only to keep the wording consistent. Translate only this line's own text; do not copy the whole reference translation.
Output JSON only: {{"items":[{{"id":"<id unchanged>","translation":"<translation>"}}]}}"""

_TARGET_RULES = {
    "en": "Do not leave Chinese, Japanese or Korean sentences untranslated.",
    "ja": "Write natural Japanese with kana as a Japanese viewer expects; never copy a Chinese sentence as it is.",
    "ko": "Write in Hangul; do not leave Chinese characters or Japanese kana untranslated.",
}


def _batch_glossary(batch: TranslationBatch, pairs: Sequence[tuple[str, str]], source_language: str = "",
                    target: str = DEFAULT_TARGET) -> list[dict]:
    text = "\n".join(line.text for line in batch.lines)
    source_key = source_language_of(source_language)
    target_key = TARGET_LANGUAGE.get(normalize_target(target), "zh")
    if source_key == "en":
        lowered = text.casefold()
        relevant = [{"en": term, target_key: value} for term, value in pairs if term.casefold() in lowered]
    else:
        relevant = [{source_key: term, target_key: value} for term, value in pairs if term in text]
    return relevant[:MAX_GLOSSARY_PAIRS_PER_BATCH]


def build_messages(batch: TranslationBatch, *, target: str = DEFAULT_TARGET, game_context: str = "",
                   glossary_pairs: Any = (), speaker_names: Mapping[str, str] | None = None,
                   source_language: str = "") -> list[dict[str, str]]:
    """System + user messages for one batch (JSON user payload)."""
    target = normalize_target(target)
    label = TARGET_LABELS[target]
    pairs = normalize_glossary(glossary_pairs)
    names = {str(k): str(v) for k, v in (speaker_names or {}).items() if str(v or "").strip()}
    lines = []
    for line in batch.lines:
        row: dict[str, Any] = {"id": line.id, "text": line.text, "translate": line.translate}
        speaker = names.get(line.speaker_id) or line.speaker
        if speaker:
            row["speaker"] = speaker
        if line.gap_before:
            row["gap_before"] = True
        if not line.translate and line.translation:
            row["translation"] = line.translation
        if line.translate and line.reference:
            row["reference"] = [{"text": item.get("source_text", ""), "translation": item.get("translation", "")}
                                for item in line.reference]
        lines.append(row)
    english = source_language == "en"
    chinese_target = TARGET_LANGUAGE[target] == "zh"
    source_name = LANGUAGE_NAMES[source_language_of(source_language)]
    target_name = LANGUAGE_NAMES[TARGET_LANGUAGE[target]]
    payload: dict[str, Any] = {
        "task": (f"{'英语' if english else '日语'}字幕 → {label}字幕" if chinese_target
                 else f"{source_name} subtitles -> {target_name} subtitles"),
        "target_language": label if chinese_target else target_name,
        "target": target,
        "prompt_version": prompt_version_for(source_language, target),
    }
    if str(game_context or "").strip():
        payload["game_context"] = str(game_context).strip()
    glossary = _batch_glossary(batch, pairs, source_language, target)
    if glossary:
        payload["glossary"] = glossary
    payload["lines"] = lines
    payload["output_ids"] = list(batch.target_ids)
    if chinese_target:
        system = (_EN_SYSTEM_PROMPT if english else _SYSTEM_PROMPT).format(label=label,
                                                                          script_rule=_SCRIPT_RULES[target])
    else:
        system = _GENERIC_SYSTEM_PROMPT.format(source_name=source_name, target_name=target_name,
                                               target_rule=_TARGET_RULES[TARGET_LANGUAGE[target]])
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _max_tokens(batch: TranslationBatch) -> int:
    return int(min(8192, 1024 + 2 * batch.source_chars + 24 * len(batch.target_ids)))


# ---------------------------------------------------------------------------
# Validation


def _letters(text: str) -> dict[str, int]:
    """Script counts plus Hangul syllables/jamo and ASCII letters."""
    counts = script_counts(text)
    counts["hangul"] = sum(1 for char in text if 0xAC00 <= ord(char) <= 0xD7A3 or 0x1100 <= ord(char) <= 0x11FF
                           or 0x3130 <= ord(char) <= 0x318F)
    counts["latin"] = sum(1 for char in text if char.isascii() and char.isalpha())
    return counts


def validate_translation(source_text: str, text: str, target: str = DEFAULT_TARGET,
                         source_language: str = "") -> str | None:
    """Reason a single translation is unusable, or None when acceptable."""
    output = clean_translation(text)
    if not output:
        return "empty"
    if _TIMESTAMP.search(output):
        return "timestamp"
    source = normalize_source(source_text)
    target_language = TARGET_LANGUAGE.get(normalize_target(target), "zh")
    if target_language != "zh":
        return _validate_foreign(source, output, target_language, source_language_of(source_language))
    if len(output) > 4 * len(source) + 20:
        return "too_long"
    src = script_counts(source)
    src_kana = src["hiragana"] + src["katakana"]
    if not src_kana and not src["han"]:
        # Latin / digits / symbols only. A short token (GG, OK, a name) may stay
        # as it is; an English sentence (2026-10-14) must come back as Chinese.
        latin = sum(1 for char in source if char.isascii() and char.isalpha())
        if latin < 12 or len(source.split()) < 3:
            return None
        out = script_counts(output)
        if not out["han"]:
            return "echo_source" if _content(output) == _content(source) else "no_chinese"
        out_latin = sum(1 for char in output if char.isascii() and char.isalpha())
        if out_latin > 2 * out["han"] and out_latin >= 12:
            return "english_output"
        return None
    katakana_name = src["katakana"] > 0 and not src["hiragana"] and not src["han"]
    # A kanji-only word is often the same word in Chinese (期待, 反省, 注意).
    kanji_word = src["han"] > 0 and not src_kana
    out = script_counts(output)
    out_kana = out["hiragana"] + out["katakana"]
    source_content, output_content = _content(source), _content(output)
    if output_content == source_content:
        return None if katakana_name or kanji_word else "echo_source"
    if src_kana and len(source_content) >= 4 and source_content in output_content:
        return "echo_source"
    if not out["han"]:
        if katakana_name and not out["hiragana"]:
            return None
        return "japanese_output" if out_kana else "no_chinese"
    if out["hiragana"] >= 2 or out_kana / max(1, out_kana + out["han"]) > 0.5:
        return "japanese_output"
    return None


def _validate_foreign(source: str, output: str, target_language: str, source_language: str) -> str | None:
    """English / Japanese / Korean targets (2026-10-14)."""
    src, out = _letters(source), _letters(output)
    src_cjk = src["han"] + src["hiragana"] + src["katakana"] + src["hangul"]
    # Chinese/Japanese -> English grows about three times in characters.
    factor = 8 if target_language == "en" and src_cjk else 4
    if len(output) > factor * len(source) + 30:
        return "too_long"
    out_kana = out["hiragana"] + out["katakana"]
    # A short Latin token (GG, OK, a name) may stay as it is.
    latin_token = not src_cjk and (src["latin"] < 12 or len(source.split()) < 3)
    if _content(output) == _content(source):
        if latin_token:
            return None
        # A short kanji word is often the same word in Japanese (注意, 期待).
        if target_language == "ja" and source_language == "zh" and src["han"] <= 4 and not src["latin"]:
            return None
        return "echo_source"
    if target_language == "en":
        # A kept name (I love 原神) is fine; untranslated phrases are not.
        cjk = out["han"] + out_kana + out["hangul"]
        if cjk > out["latin"] or (cjk >= 3 and cjk >= 0.3 * (cjk + out["latin"])):
            return "not_english"
        return None
    if target_language == "ko":
        if not out["hangul"]:
            return None if latin_token or not (src_cjk or src["latin"]) else "not_korean"
        if out["han"] + out_kana > out["hangul"]:
            return "not_korean"
        return None
    # Japanese
    if out["hangul"] > out_kana + out["han"]:
        return "not_japanese"
    if not out_kana and not out["han"]:
        if latin_token or not (src_cjk or src["latin"]):
            return None
        return "not_japanese"
    if out["latin"] > 2 * (out_kana + out["han"]) and out["latin"] >= 12:
        return "not_japanese"
    if source_language == "zh" and not out_kana and out["han"] >= 8:
        return "chinese_output"
    return None


def _strip_fences(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        rows = value.splitlines()
        if rows and rows[0].strip().startswith("```"):
            rows = rows[1:]
        if rows and rows[-1].strip() == "```":
            rows = rows[:-1]
        value = "\n".join(rows).strip()
    start, end = value.find("{"), value.rfind("}")
    if value[:1] != "[" and start >= 0 and end > start:
        value = value[start:end + 1]
    return value


def _payload_items(payload: Any) -> list | None:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(_strip_fences(payload.decode("utf-8") if isinstance(payload, bytes) else payload))
        except (ValueError, UnicodeDecodeError):
            return None
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return None
    for key in ("items", "translations", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    if payload and all(isinstance(value, str) for value in payload.values()):
        return [{"id": key, "translation": value} for key, value in payload.items()]
    return None


def validate_response(batch: TranslationBatch, payload: Any, target: str = DEFAULT_TARGET,
                      source_language: str = "") -> tuple[dict[str, str], dict[str, str]]:
    """``(accepted {id: text}, problems {id: reason})`` for one batch.

    Unknown ids are reported under their own id; batch-level notes (order,
    identical duplicates, malformed rows) under ``BATCH_PROBLEM_KEY``. A
    reordered answer is accepted by id.
    """
    expected = list(batch.target_ids)
    expected_set = set(expected)
    accepted: dict[str, str] = {}
    problems: dict[str, str] = {}
    notes: list[str] = []
    items = _payload_items(payload)
    if items is None:
        return {}, {**{cue_id: "malformed_response" for cue_id in expected}, BATCH_PROBLEM_KEY: "malformed_response"}
    seen: dict[str, str] = {}
    order: list[str] = []
    conflicts: set[str] = set()
    for raw in items:
        if not isinstance(raw, Mapping):
            notes.append("malformed_item")
            continue
        cue_id = str(raw.get("id") or "").strip()
        value = raw.get("translation", raw.get("text"))
        text = "" if value is None else str(value)
        if cue_id not in expected_set:
            problems[cue_id or "?"] = "unknown_id"
            continue
        if cue_id in seen:
            if clean_translation(seen[cue_id]) != clean_translation(text):
                conflicts.add(cue_id)
            else:
                notes.append("duplicate_id")
            continue
        seen[cue_id] = text
        order.append(cue_id)
    for cue_id in expected:
        if cue_id in conflicts:
            problems[cue_id] = "duplicate_id"
        elif cue_id not in seen:
            problems[cue_id] = "missing"
        else:
            reason = validate_translation(batch.source_text(cue_id), seen[cue_id], target, source_language)
            if reason:
                problems[cue_id] = reason
            else:
                accepted[cue_id] = clean_translation(seen[cue_id])
    if order != [cue_id for cue_id in expected if cue_id in seen]:
        notes.append("order_mismatch")
    if notes:
        problems[BATCH_PROBLEM_KEY] = ";".join(dict.fromkeys(notes))
    return accepted, problems


# ---------------------------------------------------------------------------
# Cache


def cache_key(source_text: str, context_texts: Sequence[str], *, target: str, model: str, provider: str,
              glossary_digest: str = "", prompt_version: str = PROMPT_VERSION, extra: str = "") -> str:
    """sha256 over every input that can change a translation."""
    parts = {
        "source": normalize_source(source_text),
        "context": [normalize_source(text) for text in context_texts],
        "target": normalize_target(target),
        "model": str(model or ""),
        "provider": str(provider or ""),
        "prompt_version": str(prompt_version or ""),
        "glossary": str(glossary_digest or ""),
        "extra": str(extra or ""),
    }
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def context_texts(source: TranslationSource, cue_id: str, context_cues: int = 3) -> list[str]:
    cue = source.cue(cue_id)
    if cue is None:
        return []
    before = source.cues[max(0, cue.index - context_cues):cue.index]
    after = source.cues[cue.index + 1:cue.index + 1 + context_cues]
    return [item.text for item in before] + ["␞"] + [item.text for item in after]


def _cache_extra(source: TranslationSource, cue_id: str, game_context: str) -> str:
    references = [[item.get("source_text", ""), item.get("translation", "")]
                  for item in source.references.get(cue_id, ())]
    if not references and not str(game_context or "").strip():
        return ""
    return _digest({"game_context": str(game_context or "").strip(), "reference": references})


def cache_lookup(cache: Mapping | None, key: str) -> str:
    if not isinstance(cache, Mapping):
        return ""
    value = cache.get(key)
    if isinstance(value, Mapping):
        value = value.get("text")
    return str(value or "") if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# Translation run


@dataclass
class TranslatedItem:
    cue_id: str
    text: str
    source_text: str
    source_sha: str
    context_sha: str
    cached: bool = False


@dataclass
class TranslationResult:
    target: str
    model: str
    provider: str
    prompt_version: str = PROMPT_VERSION
    glossary_digest: str = ""
    overwrite_manual: bool = False
    overwrite_legacy: bool = False
    requested: tuple[str, ...] = ()
    translations: dict[str, TranslatedItem] = field(default_factory=dict)
    suggestions: dict[str, TranslatedItem] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    skipped_manual: tuple[str, ...] = ()
    cache_hits: list[str] = field(default_factory=list)
    pending: tuple[str, ...] = ()
    requests: int = 0
    cancelled: bool = False
    fatal_error: str = ""
    problems: list[dict] = field(default_factory=list)

    @property
    def succeeded(self) -> tuple[str, ...]:
        return tuple(self.translations)

    def summary(self) -> dict[str, Any]:
        return {
            "target": self.target, "model": self.model, "provider": self.provider,
            "requested": len(self.requested), "succeeded": len(self.translations),
            "suggestions": len(self.suggestions), "failed": len(self.failed),
            "skipped_manual": len(self.skipped_manual), "cache_hits": len(self.cache_hits),
            "pending": len(self.pending), "requests": self.requests, "cancelled": self.cancelled,
            "fatal_error": self.fatal_error,
        }


def _protected(record: Mapping | None, overwrite_manual: bool, overwrite_legacy: bool) -> bool:
    if overwrite_manual or not isinstance(record, Mapping):
        return False
    if record.get("origin") != ORIGIN_MANUAL or not str(record.get("text") or "").strip():
        return False
    return not (overwrite_legacy and record.get("legacy"))


_SPLIT_CATEGORIES = frozenset({"request_too_large", "payload_too_large", "transport_length"})


def _call_provider(provider, messages, *, max_tokens: int, timeout: float, cancel_check):
    kwargs = dict(max_tokens=max_tokens, temperature=0.2, timeout=timeout, stage=PROVIDER_STAGE,
                  cancel_check=cancel_check, operation_kind=BUDGET_OPERATION, enable_thinking=False)
    if callable(getattr(provider, "structured_complete", None)):
        return provider.structured_complete(messages, RESPONSE_SCHEMA, **kwargs)
    return provider.complete(messages, response_format={"type": "json_object"}, json_schema=RESPONSE_SCHEMA,
                             **kwargs)


def translate(project, cue_ids: Iterable[str] | None, provider, *, target: str, game_context: str = "",
              glossary_pairs: Any = (), cancel_check: Callable[[], bool] | None = None,
              progress: Callable[[int, int, str], None] | None = None,
              cache: MutableMapping[str, Any] | None = None, overwrite_manual: bool = False,
              overwrite_legacy: bool = False, suggest_for_manual: bool = True,
              max_items: int = 40, max_chars: int = 2400, context_cues: int = 3, timeout: float = 180.0,
              retry_wait: Callable[[float], bool] | None = None) -> TranslationResult:
    """Translate cues in timeline-ordered batches; never mutates the project.

    ``project`` may be a ``SubtitleProject`` or a ``TranslationSource`` (build
    it with ``translation_source`` on the UI thread before starting a worker).
    ``cue_ids=None`` means every cue with text. Manual records are protected:
    their AI output goes to ``suggestions`` (or is skipped when
    ``suggest_for_manual`` is False) unless ``overwrite_manual``;
    ``overwrite_legacy`` lets AI replace migrated legacy records only.
    Failed/missing items are retried once in half-size batches; successes of a
    batch are kept even when siblings fail. Cancellation keeps finished items.
    """
    from .provider_input_budget import (DETERMINISTIC_FAILURES, InputBudgetError, failure_category,
                                        prepare_input, retry_delay, wait_retry)

    source = _as_source(project)
    target = normalize_target(target)
    source_language = str(getattr(source, "language", "") or "")
    prompt_version = prompt_version_for(source_language, target)
    check = cancel_check or (lambda: False)
    pairs = normalize_glossary(glossary_pairs)
    digest = glossary_digest(pairs)
    model = str(getattr(provider, "model", "") or "")
    provider_id = str(getattr(provider, "provider_id", "") or "")
    speaker_names = {cue.speaker_id: cue.speaker_name for cue in source.cues if cue.speaker_name}
    wanted = None if cue_ids is None else {str(item) for item in cue_ids}
    requested = [cue.id for cue in source.cues if wanted is None or cue.id in wanted]
    result = TranslationResult(target=target, model=model, provider=provider_id, glossary_digest=digest,
                               prompt_version=prompt_version,
                               overwrite_manual=bool(overwrite_manual), overwrite_legacy=bool(overwrite_legacy),
                               requested=tuple(requested))
    result.sources = {cue_id: source.cue(cue_id).text for cue_id in requested}
    protected = [cue_id for cue_id in requested
                 if _protected(source.records.get(cue_id), overwrite_manual, overwrite_legacy)]
    result.skipped_manual = tuple(protected)
    protected_set = set(protected)
    work = [cue_id for cue_id in requested if cue_id not in protected_set or suggest_for_manual]
    total = len(work)
    keys: dict[str, str] = {}
    contexts: dict[str, str] = {}
    fresh: dict[str, str] = {}

    def report(message: str) -> None:
        if progress is not None:
            done = len(result.translations) + len(result.suggestions) + len(result.failed)
            progress(done, total, message)

    def succeed(cue_id: str, text: str, cached: bool) -> None:
        item = TranslatedItem(cue_id, text, result.sources[cue_id], source_sha(result.sources[cue_id]),
                              contexts[cue_id], cached)
        (result.suggestions if cue_id in protected_set else result.translations)[cue_id] = item
        fresh[cue_id] = text
        if cached:
            result.cache_hits.append(cue_id)
        elif cache is not None:
            cache[keys[cue_id]] = {"text": text, "target": target, "model": model, "provider": provider_id,
                                   "prompt_version": prompt_version, "at": _now()}

    for cue_id in work:
        window = context_texts(source, cue_id, context_cues)
        contexts[cue_id] = _digest(window)
        keys[cue_id] = cache_key(result.sources[cue_id], window, target=target, model=model,
                                 provider=provider_id, glossary_digest=digest, prompt_version=prompt_version,
                                 extra=_cache_extra(source, cue_id, game_context))
        hit = cache_lookup(cache, keys[cue_id])
        if hit and validate_translation(result.sources[cue_id], hit, target, source_language) is None:
            succeed(cue_id, clean_translation(hit), True)
    if result.cache_hits:
        report(f"缓存命中 {len(result.cache_hits)} 条")

    def resolved(cue_id: str) -> bool:
        return cue_id in result.translations or cue_id in result.suggestions or cue_id in result.failed

    def note(batch_no: int, problems: Mapping[str, str]) -> None:
        for cue_id, reason in problems.items():
            result.problems.append({"batch": batch_no, "id": cue_id, "reason": reason})

    batch_counter = [0]

    def run(batch: TranslationBatch, retries_left: int) -> None:
        if result.cancelled or result.fatal_error:
            return
        if check():
            result.cancelled = True
            return
        ids = list(batch.target_ids)
        messages = build_messages(batch, target=target, game_context=game_context, glossary_pairs=pairs,
                                  speaker_names=speaker_names, source_language=source_language)
        max_tokens = _max_tokens(batch)
        try:
            prepare_input(messages, schema=RESPONSE_SCHEMA, max_tokens=max_tokens, operation=BUDGET_OPERATION)
        except InputBudgetError:
            split(batch, ids, retries_left, "request_too_large")
            return
        batch_counter[0] += 1
        batch_no = batch_counter[0]
        result.requests += 1
        delay = None
        try:
            payload = _call_provider(provider, messages, max_tokens=max_tokens, timeout=timeout,
                                     cancel_check=check)
        except Exception as exc:  # noqa: BLE001 - classified below, reported per cue
            category = failure_category(exc)
            if category == "cancelled" or check():
                result.cancelled = True
                return
            if category in _SPLIT_CATEGORIES:
                split(batch, ids, retries_left, category)
                return
            from .provider_diagnostics import redact_diagnostics
            reason = f"provider_error:{category}: {str(redact_diagnostics(str(exc)))[:160]}"
            if category in DETERMINISTIC_FAILURES:
                result.fatal_error = reason
                for cue_id in ids:
                    result.failed[cue_id] = reason
                note(batch_no, {cue_id: reason for cue_id in ids})
                return
            accepted, problems = {}, {cue_id: reason for cue_id in ids}
            delay = retry_delay(exc, 1)
        else:
            accepted, problems = validate_response(batch, payload, target, source_language)
        for cue_id, text in accepted.items():
            succeed(cue_id, text, False)
        note(batch_no, problems)
        remaining = [cue_id for cue_id in ids if cue_id not in accepted]
        report(f"已完成 {len(result.translations) + len(result.suggestions)}/{total} 条")
        if not remaining:
            return
        if retries_left > 0:
            if delay:
                waiter = retry_wait or (lambda seconds: wait_retry(seconds, check))
                if not waiter(delay):
                    if check():
                        result.cancelled = True
                        return
            size = max(1, len(ids) // 2)
            for sub in plan_batches(source, remaining, max_items=size, max_chars=max_chars,
                                    context_cues=context_cues, known_translations=fresh):
                run(sub, retries_left - 1)
            return
        for cue_id in remaining:
            result.failed[cue_id] = problems.get(cue_id) or "missing"
        report(f"失败 {len(result.failed)} 条")

    def split(batch: TranslationBatch, ids: list[str], retries_left: int, reason: str) -> None:
        if len(ids) <= 1:
            for cue_id in ids:
                result.failed[cue_id] = reason
            return
        for sub in plan_batches(source, ids, max_items=max(1, len(ids) // 2), max_chars=max_chars,
                                context_cues=context_cues, known_translations=fresh):
            run(sub, retries_left)

    pending = [cue_id for cue_id in work if not resolved(cue_id)]
    report(f"共 {total} 条，待请求 {len(pending)} 条")
    for batch in plan_batches(source, pending, max_items=max_items, max_chars=max_chars,
                              context_cues=context_cues):
        if result.cancelled or result.fatal_error:
            break
        run(batch, 1)
    leftover = [cue_id for cue_id in work if not resolved(cue_id)]
    if result.fatal_error and not result.cancelled:
        for cue_id in leftover:
            result.failed[cue_id] = result.fatal_error
        leftover = []
    result.pending = tuple(leftover)
    report("已取消" if result.cancelled else "完成")
    return result


# ---------------------------------------------------------------------------
# Applying a result (one undo step)


def apply_translation_result(project, result: TranslationResult) -> tuple[dict, dict]:
    """Write a run's results into records + render view; returns (before, after).

    Records that became manual while the run was in flight are not replaced;
    their AI text is moved to ``result.suggestions``. A failed retranslation of
    a cue that still has a current translation keeps it (``last_error`` only).
    """
    before = snapshot(project)
    container = _ensure_container(project)
    records = container["records"]
    container["target"] = result.target
    meta_common = dict(target=result.target, model=result.model, provider=result.provider,
                       prompt_version=result.prompt_version, glossary=result.glossary_digest)
    applied = 0
    for cue_id, item in result.translations.items():
        old = records.get(cue_id)
        if _protected(old, result.overwrite_manual, result.overwrite_legacy):
            result.suggestions.setdefault(cue_id, item)
            continue
        records[cue_id] = _record(item.text, item.source_text, origin=ORIGIN_AI, context_sha=item.context_sha,
                                  previous=_pushed_previous(old), **meta_common)
        applied += 1
    for cue_id, reason in result.failed.items():
        old = records.get(cue_id)
        if _protected(old, result.overwrite_manual, result.overwrite_legacy):
            continue
        source_text = result.sources.get(cue_id, "")
        if (isinstance(old, Mapping) and str(old.get("text") or "").strip() and old.get("status") != FAILED
                and old.get("source_sha") == source_sha(source_text)):
            updated = dict(old)
            updated["last_error"] = reason
            records[cue_id] = updated
            continue
        if isinstance(old, Mapping):
            updated = dict(old)
            updated.update(status=FAILED, error=reason, failed_source_sha=source_sha(source_text),
                           updated_at=_now())
            records[cue_id] = updated
        else:
            records[cue_id] = _record("", source_text, origin=ORIGIN_AI, status=FAILED, error=reason,
                                      **meta_common)
    _append_history(container, {"kind": "ai", **result.summary(), "applied": applied})
    _rebuild_view(project)
    return before, snapshot(project)


def accept_suggestions(project, result: TranslationResult, cue_ids: Iterable[str] | None = None
                       ) -> tuple[dict, dict]:
    """The person accepts AI suggestions for protected (manual) cues.

    Explicit user action: the chosen suggestions replace the manual records
    (old text kept in ``previous``). Returns (before, after).
    """
    chosen = None if cue_ids is None else {str(item) for item in cue_ids}
    before = snapshot(project)
    container = _ensure_container(project)
    records = container["records"]
    meta_common = dict(target=result.target, model=result.model, provider=result.provider,
                       prompt_version=result.prompt_version, glossary=result.glossary_digest)
    accepted = 0
    for cue_id, item in result.suggestions.items():
        if chosen is not None and cue_id not in chosen:
            continue
        old = records.get(cue_id)
        records[cue_id] = _record(item.text, item.source_text, origin=ORIGIN_AI, context_sha=item.context_sha,
                                  previous=_pushed_previous(old), **meta_common)
        accepted += 1
    if accepted:
        _append_history(container, {"kind": "accept_suggestions", "accepted": accepted})
    _rebuild_view(project)
    return before, snapshot(project)


__all__ = [
    "BATCH_PROBLEM_KEY", "DEFAULT_TARGET", "DONE", "FAILED", "MANUAL", "NEEDS_UPDATE", "PROMPT_VERSION",
    "RECORDS_KEY", "RENDER_KEY", "RESPONSE_SCHEMA", "STATUSES", "UNTRANSLATED",
    "BatchLine", "SourceCue", "TranslatedItem", "TranslationBatch", "TranslationResult", "TranslationSource",
    "accept_suggestions", "apply_translation_result", "build_messages", "cache_key", "cache_lookup", "clean_translation",
    "container_target", "context_texts", "cue_status", "glossary_digest", "ids_with_status", "migrate",
    "normalize_glossary", "normalize_target", "plan_batches", "records_of", "restore_snapshot", "set_manual",
    "snapshot", "source_sha", "split_merge_candidates", "status_counts", "status_of", "statuses",
    "sync_render_view", "translate", "translation_source", "translation_view", "validate_response",
    "validate_translation",
]
