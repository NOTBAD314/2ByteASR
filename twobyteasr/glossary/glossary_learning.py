"""Persistent, review-first glossary suggestions learned from manual Studio edits."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from functools import wraps

from .learning_review import storage_lock


SCHEMA_VERSION = 4
# One confirmed manual edit is already visible evidence; extra edits only
# raise confidence. (Was 3, which made single corrections invisible.)
DEFAULT_THRESHOLD = 1
MAX_TERM_LENGTH = 12
ENGLISH_FUNCTION_WORDS = frozenset("i me my we us our you your he him his she her it its they them their this that these those a an the and or but is are was were am be been do does did yes no ok okay".split())
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
    return " ".join(str(value or "").strip().split())


def _looks_like_term(source: str, target: str) -> bool:
    source = _clean_term(source)
    target = _clean_term(target)
    if not source or not target or source == target:
        return False
    if max(len(source), len(target)) > MAX_TERM_LENGTH:
        return False
    punctuation = set("，。！？；：,.!?;:\n\r\t()（）[]【】{}<>《》\"'“”‘’、…—")
    if any(char in punctuation for char in source + target):
        return False
    if not any(char.isalnum() for char in source) or not any(char.isalnum() for char in target):
        return False
    return True


def extract_term_replacements(before: str, after: str, *, canonical_terms=()) -> list[tuple[str, str]]:
    """Extract only compact replacement spans, never whole sentence rewrites."""
    before = str(before or "")
    after = str(after or "")
    if before == after:
        return []
    # Formatting changes do not become rules. Keep symbols in names such as C++.
    if "".join(before.split()) == "".join(after.split()):
        return []
    from .glossary_autosave import glossary_pairs, _ordinary_language, _contains_ordinary_word, _posseg
    from ..subtitle_rules.stutter_cleanup import _tokens, word_frequency, word_tag, NOUN_TAGS, ORDINARY_WORD_FREQ
    anchored = glossary_pairs(before, after, canonical_terms)
    if anchored:
        return anchored
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    replacements: list[tuple[str, str]] = []
    changed_characters = 0
    opcodes = matcher.get_opcodes()
    changed = [row for row in opcodes if row[0] != "equal"]
    if len(changed) == 1:
        _tag, a, b, c, d = changed[0]
        token_pattern = r"[A-Za-z][A-Za-z0-9_+#-]*"
        old_token = next((match for match in re.finditer(token_pattern, before)
                          if match.start() <= a and b <= match.end()), None)
        new_token = next((match for match in re.finditer(token_pattern, after)
                          if match.start() <= c and d <= match.end()), None)
        if old_token is not None and new_token is not None:
            source, target = old_token.group(), new_token.group()
            if source.casefold() in ENGLISH_FUNCTION_WORDS or target.casefold() in ENGLISH_FUNCTION_WORDS:
                return []
            identifier = any(char.isupper() or char.isdigit() or char in "+#_" for char in source + target)
            if (identifier and _looks_like_term(source, target)
                    and before[:old_token.start()] == after[:new_token.start()]
                    and before[old_token.end():] == after[new_token.end():]):
                return [(source, target)]
    for tag, left_start, left_end, right_start, right_end in opcodes:
        if tag == "equal":
            continue
        source = before[left_start:left_end]
        target = after[right_start:right_end]
        changed_characters += max(len(source), len(target))
        if tag == "replace":
            ordinary_rewrite = any(a < left_end and left_start < b and len(word) > 1
                and word_frequency(word) >= ORDINARY_WORD_FREQ and word_tag(word) not in NOUN_TAGS
                for word, a, b in _tokens(before))
            if ordinary_rewrite:
                continue
            if len(source) == len(target) <= 2 and (left_start or left_end < len(before)):
                # A Chinese proper-name correction often differs by one homophone.
                # Include a small equal context window so 来->莱 becomes 那维来特->那维莱特.
                left_context = min(2, left_start, right_start)
                right_context = min(1, len(before) - left_end, len(after) - right_end)
                trailing = before[left_end:left_end + right_context]
                # Do not absorb a common sentence particle into a three-character name:
                # 星见鸦很强 -> 星见雅很强 should learn 星见鸦 -> 星见雅.
                if trailing in set("很的是了啊吧吗呢在和也都就真又把被给去来はがのをにでとへもや"):
                    right_context = 0
                source = before[left_start - left_context:left_end + right_context]
                target = after[right_start - left_context:right_end + right_context]
            from ..subtitle_rules.pronouns import is_pronoun_swap
            if is_pronoun_swap(source, target):
                # 他 → 她 is a context decision, never a term (2026-10-15).
                continue
            if _looks_like_term(source, target):
                old_start, new_start = before.find(source), after.find(target)
                target_tokens = _posseg(target)
                whole_name = len(target_tokens) == 1 and target_tokens[0][1] in {"nr", "nrt", "nrfg", "ns", "nt"}
                if source[:1] in "我你他她它您咱俺" and not whole_name:
                    continue
                if len(source) == len(target) == 1 and source == before and target == after:
                    from ..subtitle_rules.stutter_cleanup import CLOSED
                    if source not in CLOSED and target not in CLOSED:
                        replacements.append((source, target))
                    continue
                if (_ordinary_language(before, old_start, old_start + len(source))
                        or _ordinary_language(after, new_start, new_start + len(target))
                        or _contains_ordinary_word(after, new_start, new_start + len(target))):
                    continue
                replacements.append((_clean_term(source), _clean_term(target)))
    # General rewriting is not terminology evidence even when it contains a short replacement.
    if changed_characters > MAX_TERM_LENGTH or len(replacements) != 1:
        return []
    return replacements


def _locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with storage_lock(self.path):
            return method(self, *args, **kwargs)
    return wrapped


class GlossaryLearningStore:
    def __init__(self, path: str | os.PathLike[str] | None = None, *, threshold: int = DEFAULT_THRESHOLD):
        self.path = Path(path) if path is not None else glossary_learning_path()
        # 单次人工修正即可见（旧版钳到 2 起步导致一次修改完全不可见）。
        self.threshold = max(1, int(threshold))

    def load(self, *, strict=False) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return _empty_payload()
        except (OSError, ValueError, TypeError):
            if strict:
                raise
            return _empty_payload()
        if not isinstance(payload, dict):
            if strict:
                raise ValueError("学习候选文件格式无效，未写入")
            return _empty_payload()
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValueError("学习候选列表格式无效，未写入")
        normalized = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            status = str(entry.get("status") or "collecting")
            if entry.get("auto_saved") and not entry.get("confirmation_action"):
                entry.setdefault("previous_auto_acceptance", {
                    key: entry[key] for key in ("status", "accepted_at", "accepted_glossary") if key in entry
                })
                status = "ignored" if entry.get("ignored") else "pending"
                entry.update(status=status, accepted=False)
                entry.setdefault("glossary_id", str(entry.get("accepted_glossary") or ""))
            entry.setdefault("scope", "original")
            entry.setdefault("language", "und")
            entry.setdefault("glossary_id", "")
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
    def _identity(source: str, target: str, glossary_id="", language="und", scope="original") -> str:
        value = f"{source}\0{target}"
        if glossary_id or language != "und" or scope != "original":
            value += f"\0{glossary_id}\0{language}\0{scope}"
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return f"manual-{digest}"

    @staticmethod
    def _recount(entry: dict[str, Any]) -> None:
        count = len(entry.get("evidences") or {})
        entry["occurrence_count"] = count
        entry["confidence"] = round(min(0.99, 0.52 + 0.11 * count), 2)

    @_locked
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
        glossary_id: str = "",
        glossary_ids=(),
        language: str = "und",
        scope: str = "original",
        canonical_terms=(),
        existing_pairs=(),
    ) -> list[dict[str, Any]]:
        origin = str(getattr(origin, "value", origin) or "")
        if origin not in LEARNABLE_ORIGINS:
            return []
        # A translated-text correction does not prove a directional translation
        # pair. Keep its manual terminology editor as the explicit entry point.
        if scope != "original":
            return []
        source_label = str(source or origin).strip()
        pairs = [pair for pair in extract_term_replacements(before, after, canonical_terms=canonical_terms)
                 if pair not in set(existing_pairs)]
        if not pairs:
            return []
        payload = self.load(strict=True)
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
                    if str(item.get("glossary_id", "")) == str(glossary_id)
                    and sorted(item.get("glossary_ids", ())) == sorted(glossary_ids)
                    and item.get("language", "und") == language and item.get("scope", "original") == scope
                    and source.startswith(str(item.get("original_term", "")))
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
            binding = glossary_id or (json.dumps(sorted(glossary_ids)) if glossary_ids else "")
            identity = self._identity(source, target, binding, language, scope)
            entry = next((item for item in candidates if item.get("id") == identity
                          or identity in item.get("dedupe_keys", ())), None)
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
                    "glossary_id": str(glossary_id),
                    "glossary_ids": list(glossary_ids),
                    "language": str(language),
                    "scope": str(scope),
                }
                candidates.append(entry)
            if entry.get("status") in {"accepted", "ignored"}:
                changed.append(dict(entry))
                continue
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
        return len(self.revert_evidence_tokens(tokens, cue_after_text=cue_after_text))

    @_locked
    def revert_evidence_tokens(self, tokens: list[str], *, cue_after_text: str | None = None) -> list[str]:
        """``revert_evidence`` that names the tokens it removed (2026-10-15:
        undoing an automatically saved glossary fix removes its rows too).

        An entry accepted automatically (``auto_saved``) is no user decision:
        it disappears with its last evidence like a collecting candidate."""
        wanted = {str(token) for token in tokens if str(token).strip()}
        if not wanted:
            return []
        payload = self.load(strict=True)
        reverted: list[str] = []
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
                reverted.append(token)
            entry["evidences"] = evidences
            self._recount(entry)
            if evidences:
                survivors.append(entry)
                continue
            if entry.get("status") in {"accepted", "ignored"} or entry.get("legacy_mapping"):
                # Keep the explicit user decision; the evidence ledger is empty
                # but the confirmation/ignore record itself must survive.
                survivors.append(entry)
            # otherwise: no evidence and no user decision -> drop the phantom
        if reverted:
            payload["candidates"] = survivors
            self._save(payload)
        return reverted

    def mark_auto_saved(self, source: str, target: str, glossary_id: str) -> bool:
        """Compatibility guard for old extensions. Automatic acceptance is retired."""
        return False

    def pending(self) -> list[dict[str, Any]]:
        return sorted(
            (item for item in self.load()["candidates"] if item.get("status") == "pending"),
            key=lambda item: (-int(item.get("occurrence_count", 0)), str(item.get("last_seen", ""))),
        )

    @_locked
    def ignore(self, candidate_ids: list[str]) -> int:
        wanted = {str(item) for item in candidate_ids}
        payload = self.load(strict=True)
        count = 0
        for entry in payload["candidates"]:
            if entry.get("id") in wanted and entry.get("status") in {"pending", "collecting"}:
                entry["status"] = "ignored"
                entry["ignored_at"] = _utc_now()
                entry["ignored"] = True
                entry["accepted"] = False
                count += 1
        if count:
            self._save(payload)
        return count

    @_locked
    def accept(
        self,
        candidate_ids: list[str],
        glossary_name: str,
        *,
        add_mapping: Callable[..., bool | str] | None = None,
    ) -> int:
        glossary_name = str(glossary_name or "").strip()
        if not glossary_name:
            raise ValueError("glossary_name is required")
        if add_mapping is None:
            from subtitle_core import confirm_learning_candidate

            add_mapping = confirm_learning_candidate
        wanted = {str(item) for item in candidate_ids}
        payload = self.load(strict=True)
        count = 0
        self.errors = []
        self.added_count = 0
        for entry in payload["candidates"]:
            if entry.get("id") not in wanted or entry.get("status") != "pending":
                continue
            entry_origin = str(entry.get("origin") or "user_manual")
            origin_label = ORIGIN_LABELS.get(entry_origin, "手动修改")
            destination = str(entry.get("glossary_id") or glossary_name)
            try:
                if entry.get("scope", "original") != "original":
                    raise ValueError("译文候选需要在对应语言方向的译名词库中确认")
                if destination != glossary_name:
                    raise ValueError("所选候选的目标词库不同，请分别处理或先编辑目标词库")
                added = add_mapping(
                    destination,
                    str(entry.get("original_term", "")),
                    str(entry.get("corrected_term", "")),
                    category="其他",
                    origin=f"Studio {origin_label}（用户确认）",
                )
                if not added:
                    raise ValueError("未能核实正式映射写入成功，候选已保留")
            except (OSError, ValueError, TypeError) as exc:
                entry["last_error"] = str(exc)
                self.errors.append(str(exc))
                self._save(payload)
                continue
            entry["status"] = "accepted"
            entry["accepted_at"] = _utc_now()
            entry["accepted_glossary"] = glossary_name
            entry["mapping_added"] = added != "exists"
            self.added_count += int(entry["mapping_added"])
            entry["accepted"] = True
            entry["ignored"] = False
            entry["confirmation_action"] = "learning_review"
            entry.pop("last_error", None)
            count += 1
            # Save each completed item. Retry can verify an already-written rule
            # if the following candidate-ledger write was interrupted.
            self._save(payload)
        return count

    @_locked
    def edit_candidate(self, candidate_id, source, target, glossary_id):
        source, target = _clean_term(source), _clean_term(target)
        source = source or target
        if not target or not glossary_id:
            raise ValueError("请填写规范词、误识别写法和目标词库")
        payload = self.load(strict=True)
        entry = next((row for row in payload["candidates"] if row.get("id") == candidate_id
                      and row.get("status") == "pending"), None)
        if entry is None:
            raise ValueError("候选已处理，请刷新后重试")
        if entry.get("scope", "original") != "original":
            raise ValueError("请在对应语言方向的译名词库中编辑")
        key = self._identity(source, target, glossary_id, entry.get("language", "und"), "original")
        duplicate = next((row for row in payload["candidates"] if row is not entry and
                         (row.get("id") == key or key in row.get("dedupe_keys", ()))), None)
        if duplicate is not None:
            raise ValueError("该目标词库已有相同候选或处理记录")
        dedupe_keys = entry.setdefault("dedupe_keys", [])
        if key not in dedupe_keys:
            dedupe_keys.append(key)
        entry.update(original_term=source, corrected_term=target, glossary_id=str(glossary_id))
        entry.pop("last_error", None)
        self._save(payload)

    @_locked
    def sync_legacy(self, legacy):
        """Copy proven automatic rows into review, retaining the original bytes' fields.

        Original formal rows stay recoverable in their existing file. The common
        confirmation predicate excludes them immediately, including before this
        review screen has ever opened. A user's new explicit decision wins.
        """
        from .learning_review import requires_review
        payload = self.load(strict=True)
        changed = False
        for library_id, library in legacy.load_learned_term_payload(strict=True).get("games", {}).items():
            for row in library.get("mappings", ()):
                if not isinstance(row, dict) or not requires_review(row):
                    continue
                source, target = str(row.get("from") or ""), str(row.get("to") or "")
                if not source or not target:
                    continue
                identity = self._identity(source, target, library_id)
                old = next((item for item in payload["candidates"] if
                            (item.get("glossary_id") == library_id
                             and item.get("original_term") == source and item.get("corrected_term") == target)
                            or item.get("id") == identity), None)
                if old is not None:
                    continue
                status = "ignored" if row.get("review_status") == "ignored" else "pending"
                payload["candidates"].append(dict(id=identity, original_term=source, corrected_term=target,
                    status=status, accepted=False, ignored=status == "ignored", glossary_id=library_id,
                    glossary_ids=[library_id], language="und", scope="original", origin="legacy_auto",
                    sources=[row.get("origin", "历史检查")], legacy_mapping=dict(row), evidences={},
                    occurrence_count=0, first_seen=_utc_now(), last_seen=_utc_now()))
                changed = True
        if changed:
            self._save(payload)
