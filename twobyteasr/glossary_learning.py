"""Persistent, review-first glossary suggestions learned from manual Studio edits."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 3
# One confirmed manual edit is already visible evidence; extra edits only
# raise confidence. (Was 3, which made single corrections invisible.)
DEFAULT_THRESHOLD = 1
MAX_TERM_LENGTH = 12
LEARNABLE_ORIGINS = {"user_manual", "user_edit", "search_replace"}
ORIGIN_LABELS = {
    "user_manual": "手动修改",
    "user_edit": "手动修改",
    "search_replace": "手动查找替换",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_evidence_token() -> str:
    return f"ev-{uuid.uuid4().hex[:16]}"


def glossary_learning_path(base: str | os.PathLike[str] | None = None) -> Path:
    root = Path(base) if base is not None else Path(
        os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    ) / "2ByteASR" / "SubtitleStudioPreview"
    return root / "glossary-learning.json"


def _empty_payload() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "candidates": []}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _clean_term(value: str) -> str:
    return "".join(str(value or "").strip().split())


def _looks_like_term(source: str, target: str) -> bool:
    source = _clean_term(source)
    target = _clean_term(target)
    if not source or not target or source == target:
        return False
    if max(len(source), len(target)) > MAX_TERM_LENGTH:
        return False
    if min(len(source), len(target)) < 2:
        return False
    punctuation = set("，。！？；：,.!?;:\n\r\t()（）[]【】{}<>《》\"'“”‘’、…—")
    if any(char in punctuation for char in source + target):
        return False
    if sum(char.isalnum() or "\u3400" <= char <= "\u9fff" for char in source + target) < 4:
        return False
    return True


def extract_term_replacements(before: str, after: str) -> list[tuple[str, str]]:
    """Extract only compact replacement spans, never whole sentence rewrites."""
    before = str(before or "")
    after = str(after or "")
    if before == after:
        return []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    replacements: list[tuple[str, str]] = []
    changed_characters = 0
    opcodes = matcher.get_opcodes()
    for tag, left_start, left_end, right_start, right_end in opcodes:
        if tag == "equal":
            continue
        source = before[left_start:left_end]
        target = after[right_start:right_end]
        changed_characters += max(len(source), len(target))
        if tag == "replace":
            if not _looks_like_term(source, target) and len(source) == len(target) <= 2:
                # A Chinese proper-name correction often differs by one homophone.
                # Include a small equal context window so 来->莱 becomes 那维来特->那维莱特.
                left_context = min(2, left_start, right_start)
                right_context = min(1, len(before) - left_end, len(after) - right_end)
                trailing = before[left_end:left_end + right_context]
                # Do not absorb a common sentence particle into a three-character name:
                # 星见鸦很强 -> 星见雅很强 should learn 星见鸦 -> 星见雅.
                if trailing in set("很的是了啊吧吗呢在和也都就真又把被给去来"):
                    right_context = 0
                source = before[left_start - left_context:left_end + right_context]
                target = after[right_start - left_context:right_end + right_context]
            if _looks_like_term(source, target):
                replacements.append((_clean_term(source), _clean_term(target)))
    # General rewriting is not terminology evidence even when it contains a short replacement.
    if changed_characters > MAX_TERM_LENGTH or len(replacements) != 1:
        return []
    return replacements


class GlossaryLearningStore:
    def __init__(self, path: str | os.PathLike[str] | None = None, *, threshold: int = DEFAULT_THRESHOLD):
        self.path = Path(path) if path is not None else glossary_learning_path()
        # 单次人工修正即可见（旧版钳到 2 起步导致一次修改完全不可见）。
        self.threshold = max(1, int(threshold))

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return _empty_payload()
        if not isinstance(payload, dict):
            return _empty_payload()
        candidates = payload.get("candidates", [])
        normalized = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            status = str(entry.get("status") or "collecting")
            entry.setdefault("accepted", status == "accepted")
            entry.setdefault("ignored", status == "ignored")
            entry.setdefault("confidence", 0.0)
            entry.setdefault("sources", [entry.get("origin", "user_manual")])
            evidences = entry.get("evidences")
            if not isinstance(evidences, dict) or "evidences" not in entry:
                # v2 payloads kept only a counter: keep the count as one
                # non-revertible legacy evidence so nothing is lost or inflated.
                # (An explicit empty dict means "all evidence reverted".)
                legacy_count = max(1, int(entry.get("occurrence_count", 1) or 1))
                evidences = {
                    f"legacy-{index}": {"at": entry.get("last_seen", _utc_now())}
                    for index in range(min(legacy_count, 12))
                }
            entry["evidences"] = evidences
            entry["occurrence_count"] = len(evidences)
            normalized.append(entry)
        return {
            "schema_version": SCHEMA_VERSION,
            "candidates": normalized,
        }

    def _save(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = SCHEMA_VERSION
        _atomic_write(self.path, payload)

    @staticmethod
    def _identity(source: str, target: str) -> str:
        digest = hashlib.sha256(f"{source}\0{target}".encode("utf-8")).hexdigest()[:16]
        return f"manual-{digest}"

    @staticmethod
    def _recount(entry: dict[str, Any]) -> None:
        count = len(entry.get("evidences") or {})
        entry["occurrence_count"] = count
        entry["confidence"] = round(min(0.99, 0.52 + 0.11 * count), 2)

    def record_manual_edit(
        self,
        before: str,
        after: str,
        *,
        project: str = "",
        speaker: str = "",
        context: str = "",
        origin: str = "user_manual",
        source: str = "studio",
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        origin = str(getattr(origin, "value", origin) or "")
        if origin not in LEARNABLE_ORIGINS:
            return []
        pairs = extract_term_replacements(before, after)
        if not pairs:
            return []
        payload = self.load()
        candidates = payload["candidates"]
        now = _utc_now()
        evidence_token = str(token or new_evidence_token())
        changed: list[dict[str, Any]] = []
        dirty = False
        for source, target in pairs:
            # Reuse an already-observed shorter term when a later context only
            # appends identical sentence text (星见鸦登 -> 星见雅登).
            compact_existing = next(
                (
                    item
                    for item in candidates
                    if source.startswith(str(item.get("original_term", "")))
                    and target.startswith(str(item.get("corrected_term", "")))
                    and source[len(str(item.get("original_term", ""))):]
                    == target[len(str(item.get("corrected_term", ""))):]
                    and len(str(item.get("original_term", ""))) >= 2
                ),
                None,
            )
            if compact_existing is not None:
                source = str(compact_existing["original_term"])
                target = str(compact_existing["corrected_term"])
            identity = self._identity(source, target)
            entry = next((item for item in candidates if item.get("id") == identity), None)
            if entry is None:
                entry = {
                    "id": identity,
                    "original_term": source,
                    "corrected_term": target,
                    "occurrence_count": 0,
                    "projects": [],
                    "speakers": [],
                    "contexts": [],
                    "first_seen": now,
                    "last_seen": now,
                    "origin": origin,
                    "sources": [],
                    "confidence": 0.0,
                    "ignored": False,
                    "accepted": False,
                    "status": "collecting",
                    "evidences": {},
                }
                candidates.append(entry)
            evidences = entry.get("evidences") if isinstance(entry.get("evidences"), dict) else {}
            entry["evidences"] = evidences
            if evidence_token in evidences:
                # Redo / repeated refresh must never count the same edit twice.
                changed.append(dict(entry))
                continue
            dirty = True
            evidences[evidence_token] = {
                "at": now,
                "origin": origin,
                "project": str(project or ""),
                "after_text": str(after or "")[:120],
            }
            if entry.get("status") in {"ignored"}:
                pass  # keep ignored entries ignored; evidence still tracked
            entry["last_seen"] = now
            sources = [str(item) for item in entry.get("sources", []) if str(item).strip()]
            source_label = str(source or origin).strip()
            if source_label and source_label not in sources:
                sources.append(source_label)
            entry["sources"] = sources[-8:]
            self._recount(entry)
            for key, value, limit in (
                ("projects", project, 12),
                ("speakers", speaker, 12),
                ("contexts", context, 6),
            ):
                value = str(value or "").strip()
                values = [str(item) for item in entry.get(key, []) if str(item).strip()]
                if value and value not in values:
                    values.append(value)
                entry[key] = values[-limit:]
            if entry.get("status") in {"collecting", ""} and entry["occurrence_count"] >= self.threshold:
                entry["status"] = "pending"
            changed.append(dict(entry))
        if dirty:
            self._save(payload)
        return changed

    def revert_evidence(self, tokens: list[str], *, cue_after_text: str | None = None) -> int:
        """Undo one or more recorded edits by their evidence tokens.

        ``cue_after_text`` limits the revert to tokens whose recorded resulting
        text no longer holds, so undoing one chain never removes evidence from
        a different edit that still stands. Candidates that lose all evidence
        disappear unless they were already accepted or ignored — an accepted
        confirmation record survives even when its last evidence is undone.
        """
        wanted = {str(token) for token in tokens if str(token).strip()}
        if not wanted:
            return 0
        payload = self.load()
        changed = 0
        survivors: list[dict[str, Any]] = []
        for entry in payload["candidates"]:
            evidences = entry.get("evidences") if isinstance(entry.get("evidences"), dict) else {}
            matched = [
                token
                for token in wanted
                if token in evidences
                and (
                    cue_after_text is None
                    or str(evidences[token].get("after_text") or "") != str(cue_after_text)
                )
            ]
            if not matched:
                survivors.append(entry)
                continue
            for token in matched:
                evidences.pop(token, None)
                changed += 1
            entry["evidences"] = evidences
            self._recount(entry)
            if evidences:
                survivors.append(entry)
                continue
            if entry.get("status") in {"accepted", "ignored"}:
                # Keep the explicit user decision; the evidence ledger is empty
                # but the confirmation/ignore record itself must survive.
                survivors.append(entry)
            # otherwise: no evidence and no user decision -> drop the phantom
        if changed:
            payload["candidates"] = survivors
            self._save(payload)
        return changed

    def pending(self) -> list[dict[str, Any]]:
        return sorted(
            (item for item in self.load()["candidates"] if item.get("status") == "pending"),
            key=lambda item: (-int(item.get("occurrence_count", 0)), str(item.get("last_seen", ""))),
        )

    def ignore(self, candidate_ids: list[str]) -> int:
        wanted = {str(item) for item in candidate_ids}
        payload = self.load()
        count = 0
        for entry in payload["candidates"]:
            if entry.get("id") in wanted and entry.get("status") != "ignored":
                entry["status"] = "ignored"
                entry["ignored_at"] = _utc_now()
                entry["ignored"] = True
                entry["accepted"] = False
                count += 1
        if count:
            self._save(payload)
        return count

    def accept(
        self,
        candidate_ids: list[str],
        glossary_name: str,
        *,
        add_mapping: Callable[..., bool] | None = None,
    ) -> int:
        glossary_name = str(glossary_name or "").strip()
        if not glossary_name:
            raise ValueError("glossary_name is required")
        if add_mapping is None:
            from subtitle_core import add_learned_mapping

            add_mapping = add_learned_mapping
        wanted = {str(item) for item in candidate_ids}
        payload = self.load()
        count = 0
        for entry in payload["candidates"]:
            if entry.get("id") not in wanted or entry.get("status") != "pending":
                continue
            entry_origin = str(entry.get("origin") or "user_manual")
            origin_label = ORIGIN_LABELS.get(entry_origin, "手动修改")
            added = add_mapping(
                glossary_name,
                str(entry.get("original_term", "")),
                str(entry.get("corrected_term", "")),
                category="其他",
                origin=f"Studio {origin_label}（用户确认）",
            )
            # Existing identical mappings are still a successful explicit confirmation.
            entry["status"] = "accepted"
            entry["accepted_at"] = _utc_now()
            entry["accepted_glossary"] = glossary_name
            entry["mapping_added"] = bool(added)
            entry["accepted"] = True
            entry["ignored"] = False
            count += 1
        if count:
            self._save(payload)
        return count
