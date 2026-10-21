"""Task-owned terminology evidence and literal, deterministic canonicalization.

Canonical spelling is never a lookup key. Only confirmed aliases and safe case
variants execute; fuzzy/reference evidence remains available to review prompts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import cached_property
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from ..recognition.transcript_data import WordUnit


def _text(value: Any) -> str:
    return str(value or "").strip()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def mapping_is_confirmed(mapping: dict[str, Any], *, inferred_manual: bool = False) -> bool:
    """Preserve legacy manual confirmation without promoting explicit false.

    Callers retain their existing provenance rules. Only records known to have
    manual authority may infer confirmation when the old field is absent.
    """
    return bool(mapping.get("confirmed", inferred_manual))


@dataclass(frozen=True)
class TermEntry:
    canonical: str
    aliases: tuple[str, ...] = ()
    confirmed: bool = True
    provenance: str = "user_confirmed"
    category: str = "其他"
    origin: str = "手动"
    priority: int = 20


# Hotword value (2026-10-17). Names are what recognizers miss; a recorded
# mishearing (alias that is not just a case variant) proves the need.
_NAME_CATEGORIES = frozenset(x.casefold() for x in (
    "角色", "人物", "选手 ID", "Boss", "首领", "阵营", "地点", "地名", "生物", "精灵", "模型",
    "character", "person", "player_id", "enemy", "boss", "faction", "location", "region", "spirit"))
_ORDINARY_CATEGORIES = frozenset(x.casefold() for x in (
    "", "其他", "其它", "机制", "玩家用语", "常用词",
    "other", "common", "mechanic", "game_mechanic", "game_system"))


def _hotword_tier(term: TermEntry) -> int:
    """0 builtin (curated order kept), 1 misheard name, 2 name or misheard, 3 other, 4 ordinary."""
    if term.provenance == "builtin":
        return 0
    category = _text(term.category).casefold()
    name = category in _NAME_CATEGORIES
    misheard = any(alias.casefold() != term.canonical.casefold() for alias in term.aliases)
    if name and misheard:
        return 1
    if name or misheard:
        return 2
    return 4 if category in _ORDINARY_CATEGORIES else 3


def recognition_hotwords(snapshot: Any) -> tuple[str, ...]:
    """Ranked hotwords; objects that only carry canonical_terms keep their order."""
    ranked = getattr(snapshot, "hotword_terms", None)
    return tuple(ranked if ranked is not None else getattr(snapshot, "canonical_terms", ()) or ())


@dataclass(frozen=True)
class GlossaryLibrary:
    id: str
    name: str
    revision: str
    terms: tuple[TermEntry, ...] = ()
    reference_terms: tuple[str, ...] = ()
    found: bool = True
    profile_json: str = ""


@dataclass(frozen=True)
class GlossarySnapshot:
    libraries: tuple[GlossaryLibrary, ...] = ()

    @property
    def canonical_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(term.canonical for library in self.libraries
            for term in library.terms if term.confirmed))

    @property
    def hotword_terms(self) -> tuple[str, ...]:
        """``canonical_terms`` reordered for recognition hints, most useful first.

        ASR hint lists keep only their head (Qwen3-ASR 64 terms, MOSS cloud 20,
        Filetrans context 400 characters), and personal mappings are stored in
        (to, from) order, so file order would let Unicode order pick the names.
        Not part of to_dict: the digest and every other consumer are unchanged.
        """
        best: dict[str, tuple[int, int]] = {}
        terms = (term for library in self.libraries for term in library.terms if term.confirmed)
        for index, term in enumerate(terms):
            rank = (_hotword_tier(term), index)
            if term.canonical not in best:
                best[term.canonical] = rank
            elif rank[0] < best[term.canonical][0]:
                best[term.canonical] = (rank[0], best[term.canonical][1])
        return tuple(sorted(best, key=best.__getitem__))

    @cached_property
    def digest(self) -> str:
        # Immutable value; computing it costs ~7 ms and it was recomputed per cue.
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "libraries": [asdict(x) for x in self.libraries]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GlossarySnapshot":
        return cls(tuple(GlossaryLibrary(id=str(x["id"]), name=str(x.get("name", x["id"])),
            revision=str(x.get("revision", "")), found=bool(x.get("found", True)),
            profile_json=str(x.get("profile_json", "")),
            reference_terms=tuple(x.get("reference_terms", ())),
            terms=tuple(TermEntry(**{**row, "aliases": tuple(row.get("aliases", ()))})
                        for row in x.get("terms", ())))
            for x in payload.get("libraries", ())))

    def evidence(self) -> dict[str, Any]:
        spellings = TermResolver(self).canonical_spellings
        aliases, corrections = [], []
        for library in self.libraries:
            for term in library.terms:
                if not term.confirmed:
                    continue
                canonical = spellings.get(term.canonical.casefold(), term.canonical)
                for alias in term.aliases:
                    if alias != canonical:
                        row = {"alias": alias, "canonical": canonical}
                        if row not in aliases:
                            aliases.append(row)
                        correction = {"wrong": alias, "correct": canonical,
                            "category": term.category, "origin": term.origin}
                        if correction not in corrections:
                            corrections.append(correction)
        return {"enabled_glossary_ids": [x.id for x in self.libraries],
            "game_or_content_names": [x.name for x in self.libraries],
            "canonical_terms": list(dict.fromkeys(
                spellings.get(name.casefold(), name) for name in self.canonical_terms)), "aliases": aliases,
            "wrong_to_correct_mappings": corrections,
            "snapshot_digest": self.digest,
            "library_revisions": {x.id: x.revision for x in self.libraries}}

    def summary(self) -> dict[str, Any]:
        resolver = TermResolver(self)
        return {"snapshot_digest": self.digest,
            "libraries": [{"id": x.id, "name": x.name, "revision": x.revision,
                "found": x.found, "confirmed_terms": len({t.canonical for t in x.terms if t.confirmed}),
                "reference_terms": len(x.reference_terms)} for x in self.libraries],
            "effective_terms": resolver.effective_term_count,
            "conflicts": [x.to_dict() for x in resolver.conflicts]}


def snapshot_glossaries(legacy: Any, ids: Iterable[str]) -> GlossarySnapshot:
    """Read once, resolving stable IDs before labels; no live objects retained."""
    profiles = getattr(legacy, "load_game_profiles", lambda: {})() or {}
    games = (getattr(legacy, "load_learned_term_payload", lambda: {})() or {}).get("games", {})
    identity = getattr(legacy, "runtime_game_identity", lambda value: _text(value).casefold())
    resolve = getattr(legacy, "resolve_glossary_identity", lambda value: value)
    libraries = []
    seen = set()
    for selected in ids:
        selected = _text(selected)
        library_id = _text(resolve(selected) or selected)
        if not library_id or library_id in seen:
            continue
        seen.add(library_id)
        entry = games.get(library_id, {})
        if not entry:
            entry = next((row for key, row in games.items() if isinstance(row, dict)
                and _text(row.get("library_id", key)) == library_id), {})
        profile_name, profile = next(((name, row) for name, row in profiles.items()
            if isinstance(row, dict) and str(identity(row.get("identity", name))) == library_id), ("", {}))
        # The term library page writes hidden_reference_terms; hidden_references
        # is the older key. A hidden builtin row is gone from runtime entirely.
        hidden = {_text(x) for key in ("hidden_reference_terms", "hidden_references")
                  for x in entry.get(key, ()) if _text(x)}
        terms = []
        for row in profile.get("terms", ()):
            if not isinstance(row, dict) or not _text(row.get("canonical")):
                continue
            user_verified = any(
                x in _text(row.get("source")) for x in ("user_manual", "user_verified", "manual_srt"))
            # Same rows the page lists as hideable references (builtin_reference_terms_for_game).
            if _text(row["canonical"]) in hidden and not user_verified:
                continue
            # Existing short/contextual aliases still require ASR evidence;
            # only explicitly global builtin aliases are deterministic here.
            explicitly_confirmed = bool(row.get("confirmed")) or user_verified
            aliases = tuple(_text(x) for x in row.get("aliases", ()) if _text(x)) if (
                row.get("replacement_mode") == "global" or explicitly_confirmed) else ()
            terms.append(TermEntry(_text(row["canonical"]), aliases,
                provenance="builtin", category=_text(row.get("category")), origin="官方", priority=10))
        for row in entry.get("mappings", ()):
            if not isinstance(row, dict) or not _text(row.get("to")):
                continue
            provenance = _text(row.get("provenance"))
            # Legacy manual records predate provenance; confirmed=False always
            # wins and candidates/AI records do not acquire manual authority.
            user = provenance == "user_confirmed" or (not provenance and
                (_text(row.get("verification")) == "user_manual" or
                 "user_manual" in row.get("sources", ()) or
                 _text(row.get("origin")) in {"手动", "批量导入", "用户确认"} or
                 (bool(row.get("confirmed")) and _text(row.get("verification")).startswith("user_"))))
            confirmed = mapping_is_confirmed(row, inferred_manual=user) and user
            source = _text(row.get("from"))
            aliases = tuple(dict.fromkeys([source, *[_text(x) for x in row.get("aliases", ())]]))
            aliases = tuple(x for x in aliases if x)
            terms.append(TermEntry(_text(row["to"]), aliases, confirmed,
                provenance or ("user_confirmed" if user else "candidate"),
                _text(row.get("category")) or "其他", _text(row.get("origin")) or "手动", 20))
        references = []
        paths = getattr(legacy, "_profile_lexicon_paths_for", lambda _profile: [])(profile)
        for path in paths:
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                references.extend(_text(x.get("name")) for x in payload.get("entries", ())
                    if isinstance(x, dict) and _text(x.get("name")) and _text(x.get("name")) not in hidden)
            except (OSError, ValueError, TypeError):
                continue
        revision = _text(entry.get("revision")) or _digest({"profile": profile, "entry": entry, "references": references})
        metadata = dict(profile)
        # A library's persisted game field is its domain assignment. Freeze
        # it beside the existing profile, without changing the personal DB or
        # the snapshot's serialized field contract. Generic unlabeled test/
        # project libraries do not acquire a domain from their display title.
        assigned_domain = _text(entry.get('domain')) or _text(entry.get('game')) or profile_name
        if assigned_domain:
            metadata['_content_domain'] = {'id': library_id, 'name': assigned_domain,
                'source': 'saved_library_game'}
        # 2026-10-16 (ADR 0124): the user's own note to AI for this library.
        # Only libraries that have one change their profile_json (and digest).
        note = _text(entry.get('ai_note'))[:AI_NOTE_LIMIT]
        if note:
            metadata['_ai_note'] = note
        libraries.append(GlossaryLibrary(library_id, _text(entry.get("game")) or profile_name or selected,
            revision, tuple(terms), tuple(dict.fromkeys(references)), bool(entry or profile),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True)))
    return GlossarySnapshot(tuple(libraries))


snapshot_enabled_glossaries = snapshot_glossaries

AI_NOTE_LIMIT = 1000


def library_ai_note(library: GlossaryLibrary) -> str:
    """The note the user wrote for AI in this library ('' when none)."""
    try:
        metadata = json.loads(library.profile_json or '{}')
    except (TypeError, ValueError):
        return ''
    return _text(metadata.get('_ai_note')) if isinstance(metadata, dict) else ''


def glossary_ai_notes(snapshot: GlossarySnapshot) -> list[tuple[str, str]]:
    """``(library name, note)`` for every library in the snapshot that has a note."""
    return [(library.name, note) for library in snapshot.libraries if (note := library_ai_note(library))]


def snapshot_from_pairs(pairs: Iterable[tuple[str, str]]) -> GlossarySnapshot:
    return GlossarySnapshot((GlossaryLibrary("explicit-pairs", "明确映射", "1",
        tuple(TermEntry(_text(target), (_text(source),)) for source, target in pairs
            if _text(source) and _text(target))),))


@dataclass(frozen=True)
class TermConflict:
    key: str
    targets: tuple[str, ...]
    library_ids: tuple[str, ...]
    reason: str = "ambiguous_mapping"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TermHit:
    start: int
    end: int
    source: str
    canonical: str
    library_ids: tuple[str, ...]
    reason: str

    @property
    def target(self) -> str:
        return self.canonical

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Resolution:
    text: str
    hits: tuple[TermHit, ...] = ()
    skipped: tuple[TermHit, ...] = ()
    conflicts: tuple[TermConflict, ...] = ()


class TermResolver:
    """Single original-text scan; leftmost longest literal match, explicit conflicts.

    ``script`` (2026-10-19, ADR 0132) is given only for a 繁體 project's checks
    in the workbench: keys are compared with 简/繁 folded (``chinese_script.fold``,
    one character for one, so spans stay valid), targets are written in that
    script, and a spelling that differs from its target only by script is
    already canonical. Without it (recognition, 简体 projects) nothing changes.
    """

    def __init__(self, snapshot: GlossarySnapshot, *, script: str | None = None):
        from ..subtitle_rules import chinese_script
        self.snapshot = snapshot
        self.script = script if script in chinese_script.SCRIPTS else None
        self._fold = chinese_script.fold if self.script else (lambda text: text)
        self._categories = {}
        claims: dict[str, list[tuple[str, str, int]]] = {}
        for library in snapshot.libraries:
            for term in library.terms:
                if not term.confirmed:
                    continue
                target = self._written(term.canonical)
                for source in (term.canonical, *term.aliases):
                    if source:
                        self._categories.setdefault(self._key(source), []).append(term.category)
                        claims.setdefault(self._key(source), []).append((target, library.id, term.priority))
        self._rules: dict[str, tuple[str, tuple[str, ...]]] = {}
        conflicts = {}
        for key, rows in sorted(claims.items()):
            priority = max(row[2] for row in rows)
            top = [row for row in rows if row[2] == priority]
            targets = tuple(sorted({row[0] for row in top}))
            library_ids = tuple(sorted({row[1] for row in top}))
            if len(targets) != 1:
                conflicts[key] = TermConflict(key, targets, library_ids)
            else:
                self._rules[key] = (targets[0], library_ids)
        self._pattern = self._compile(claims)
        # Do not collapse A->B->C. Reject a rule whose target itself changes;
        # canonical conflicts remain unchanged, which is stable on repeat.
        invalid = []
        for key, (target, libraries) in tuple(self._rules.items()):
            if self._scan(target, conflicts).text != target:
                invalid.append((key, target, libraries))
        for key, target, libraries in invalid:
            del self._rules[key]
            conflicts[key] = TermConflict(key, (target,), libraries, "non_terminal_mapping")
        self._conflicts = conflicts
        self.conflicts = tuple(conflicts[x] for x in sorted(conflicts))
        self.effective_term_count = len({target for target, _ in self._rules.values()})

    def _key(self, text: str) -> str:
        return self._fold(text).casefold()

    def _written(self, canonical: str) -> str:
        if not self.script:
            return canonical
        from ..subtitle_rules.chinese_script import convert_text
        return convert_text(canonical, self.script)

    @property
    def canonical_spellings(self) -> dict[str, str]:
        """Unambiguous case spellings from the same resolved priority rules.

        Conflicts and aliases to a different identity are excluded. Consumers
        may merge case variants for recall without deciding authority again.
        """
        return {key: target for key, (target, _) in self._rules.items()
                if key == self._key(target)}

    @staticmethod
    def _compile(keys: Iterable[str]) -> re.Pattern | None:
        alternatives = []
        for key in sorted(keys, key=lambda value: (-len(value), value)):
            prefix = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", key[:1]) else ""
            suffix = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", key[-1:]) else ""
            alternatives.append(prefix + re.escape(key) + suffix)
        return re.compile("|".join(alternatives), re.I | re.ASCII) if alternatives else None

    def _scan(self, text: str, conflicts: dict[str, TermConflict], blocked=None, scene=None) -> Resolution:
        if self._pattern is None:
            return Resolution(text, conflicts=tuple(conflicts.values()))
        pieces, hits, skipped = [], [], []
        cursor = 0
        context = None
        for match in self._pattern.finditer(self._fold(text)):
            source = text[match.start():match.end()]
            key = self._key(source)
            pieces.append(text[cursor:match.start()])
            conflict = conflicts.get(key)
            rule = self._rules.get(key)
            reason = (blocked or {}).get(key, '')
            if scene is not None and rule and not reason:
                from ..recognition.content_scene import alias_context_conflict
                if self.script:
                    # The topic words of the guard are written in 简体: check a 简体 view (same indexes).
                    from ..subtitle_rules.chinese_script import to_simplified
                    context = context if context is not None else to_simplified(text)
                    reason = alias_context_conflict(context, context[match.start():match.end()],
                        to_simplified(rule[0]), category=' '.join(self._categories.get(key, ())), scene=scene,
                        span=match.span())
                else:
                    reason = alias_context_conflict(text, source, rule[0],
                        category=' '.join(self._categories.get(key, ())), scene=scene, span=match.span())
            if reason:
                pieces.append(source)
                skipped.append(TermHit(match.start(), match.end(), source, source,
                    rule[1] if rule else (), reason))
            elif conflict is not None:
                pieces.append(source)
                skipped.append(TermHit(match.start(), match.end(), source, source,
                    conflict.library_ids, conflict.reason))
            elif rule is not None:
                target, libraries = rule
                if self.script and source != target and self._fold(source) == self._fold(target):
                    target = source  # only the script differs: already canonical
                pieces.append(target)
                if source != target:
                    hits.append(TermHit(match.start(), match.end(), source, target, libraries,
                        "case_normalization" if source.casefold() == target.casefold() else "confirmed_alias"))
                else:
                    skipped.append(TermHit(match.start(), match.end(), source, target, libraries, "already_canonical"))
            else:
                pieces.append(source)
            cursor = match.end()
        pieces.append(text[cursor:])
        return Resolution("".join(pieces), tuple(hits), tuple(skipped), tuple(conflicts.values()))

    def resolve(self, text: str, *, scene=None, context_text: str = "") -> Resolution:
        original = str(text)
        conflicts = dict(self._conflicts)
        blocked = {}
        if scene is not None:
            from ..recognition.content_scene import alias_context_conflict, library_domain
            for library in self.snapshot.libraries:
                domain_id, domain_name = library_domain(library)
                different_domain = (getattr(scene, 'source', '') == 'user_selected' and domain_id
                    and domain_id not in scene.domain_ids and domain_name != scene.domain)
                for term in library.terms:
                    for alias in term.aliases:
                        reason = 'alias_domain_conflict' if different_domain else ''
                        if reason:
                            blocked[self._key(alias)] = reason
        result = self._scan(original, conflicts, blocked, scene)
        # Adjacent replacements can create a new larger alias (甲+乙 -> AB).
        # Plan against the original text, rejecting the involved substitutions
        # until their output is stable; never execute a second replacement pass.
        for _ in range(len(result.hits) + 1):
            subsequent = self._scan(result.text, conflicts, blocked, scene)
            if subsequent.text == result.text:
                return result
            output_spans = []
            delta = 0
            for hit in result.hits:
                output_start = hit.start + delta
                output_end = output_start + len(hit.canonical)
                output_spans.append((output_start, output_end, hit))
                delta += len(hit.canonical) - len(hit.source)
            involved = [hit for a, b, hit in output_spans if any(
                next_hit.start < b and a < next_hit.end for next_hit in subsequent.hits)]
            for hit in involved or list(result.hits):
                key = self._key(hit.source)
                conflicts[key] = TermConflict(key, (hit.canonical,), hit.library_ids,
                    "non_idempotent_combination")
            result = self._scan(original, conflicts, blocked, scene)
        return result


def runtime_snapshot(legacy: Any | None = None) -> GlossarySnapshot:
    from ..recognition.run_context import get_runtime_context
    context = get_runtime_context()
    if not context.enable_domain_terms:
        return GlossarySnapshot()
    snapshot = getattr(context, "glossary_snapshot", None)
    if snapshot is not None:
        return snapshot
    if legacy is None:
        import subtitle_core as legacy
    return snapshot_glossaries(legacy, legacy.runtime_enabled_glossary_ids())


def deletion_embedding(source: str, target: str) -> list[int] | None:
    """Source index of each target character when ``target`` only deletes.

    Matched right to left, so of two identical neighbours the later one is
    kept. None when ``target`` is not a strict subsequence of ``source``."""
    if not target or len(target) >= len(source):
        return None
    picks, cursor = [], len(source) - 1
    for char in reversed(target):
        while cursor >= 0 and source[cursor] != char:
            cursor -= 1
        if cursor < 0:
            return None
        picks.append(cursor)
        cursor -= 1
    return picks[::-1]


def remap_words(original: str, text: str, words: Iterable[WordUnit], start: float,
                end: float, confidence: float = .0) -> list[WordUnit]:
    """Transfer whole existing word spans; replacements never invent acoustic anchors."""
    words = list(words)
    compact = lambda value: re.sub(r"\s", "", value)
    source, target = compact(original), compact(text)
    joined = compact("".join(word.text for word in words))
    if joined.casefold() != source.casefold() or len(joined) != len(source):
        return [WordUnit(start, end, text, confidence)] if text else []
    if source.casefold() == target.casefold() and len(source) == len(target):
        result, offset = [], 0
        for word in words:
            count = len(compact(word.text))
            result.append(WordUnit(word.start, word.end, target[offset:offset+count], word.probability))
            offset += count
        return result
    anchors = [word for word in words for _ in compact(word.text)]
    output = []
    kept = deletion_embedding(source, target)
    if kept is not None:
        # Pure deletion (stammer cleanup, removed filler): every remaining
        # character keeps its own spoken anchor; a repeated unit keeps the
        # later, fluent copy (这这次 -> 这次 keeps the 这 spoken before 次).
        output = [(char, anchors[index]) for char, index in zip(target, kept)]
    for op, a, b, c, d in (() if kept is not None else
                           SequenceMatcher(None, source, target, autojunk=False).get_opcodes()):
        if op == "equal":
            output.extend((char, anchors[a+index]) for index, char in enumerate(target[c:d]))
        elif d > c:
            affected = anchors[a:b] or anchors[max(0, a-1):min(len(anchors), a+1)]
            anchor = WordUnit(min(x.start for x in affected) if affected else start,
                max(x.end for x in affected) if affected else end, "", confidence)
            output.extend((char, anchor) for char in target[c:d])
    result = []
    previous = None
    for char, anchor in output:
        if anchor is previous or (result and result[-1].start == anchor.start
                and result[-1].end == anchor.end and result[-1].probability == anchor.probability):
            result[-1].text += char
        else:
            result.append(WordUnit(anchor.start, anchor.end, char, anchor.probability))
        previous = anchor
    return result


def remap_literal_words(original: str, result: Resolution, words: Iterable[WordUnit],
                        start: float, end: float, confidence: float = .0) -> tuple[list[WordUnit], list[dict]]:
    """Map a confirmed spelling to the whole ORIGINAL pronunciation span.

    Explicit literal hit coordinates avoid SequenceMatcher treating characters
    shared with surrounding text as the nickname's acoustic anchors. The ID is
    one indivisible token, regardless of its English spelling length. Partial
    source tokens remain coarse and are never promoted to acoustic alignment.
    """
    words = list(words)
    compact = lambda value: re.sub(r"\s", "", str(value))
    source = compact(original)
    if not words or compact("".join(word.text for word in words)).casefold() != source.casefold():
        return remap_words(original, result.text, words, start, end, confidence), []
    if original.casefold() == result.text.casefold():
        return remap_words(original, result.text, words, start, end, confidence), []
    spans, cursor = [], 0
    for word in words:
        count = len(compact(word.text))
        if count:
            spans.append((cursor, cursor + count, word))
        cursor += count
    mapped, proofs = [], []
    def unchanged(a, b):
        for lo, hi, word in spans:
            left, right = max(a, lo), min(b, hi)
            if left < right:
                mapped.append(WordUnit(word.start, word.end, source[left:right], word.probability))
    cursor = 0
    for hit in result.hits:
        a, b = len(compact(original[:hit.start])), len(compact(original[:hit.end]))
        unchanged(cursor, a)
        affected = [(lo, hi, word) for lo, hi, word in spans if lo < b and a < hi]
        precise = bool(affected) and affected[0][0] == a and affected[-1][1] == b
        audio_start = min(word.start for _, _, word in affected) if affected else start
        audio_end = max(word.end for _, _, word in affected) if affected else end
        mapped.append(WordUnit(audio_start, audio_end, hit.canonical,
                               min(word.probability for _, _, word in affected) if affected else confidence))
        proofs.append({"source": hit.source, "canonical": hit.canonical,
                       "source_start": hit.start, "source_end": hit.end,
                       "audio_start": audio_start, "audio_end": audio_end,
                       "source_words": [{"text": word.text, "start": word.start, "end": word.end}
                                        for _, _, word in affected],
                       "precision": "whole_original_word_span" if precise else "partial_source_token_coarse",
                       "acoustic_verified_spelling": False})
        cursor = b
    unchanged(cursor, len(source))
    return mapped, proofs


def apply_to_segments(segments: list, snapshot: GlossarySnapshot, legacy: Any | None = None) -> list:
    resolver = TermResolver(snapshot)
    from ..recognition.content_scene import runtime_content_scene
    scene = runtime_content_scene()
    changes, scanned, matched, word_case_syncs = [], [], 0, []
    for segment in segments:
        result = resolver.resolve(segment.text, scene=scene)
        matches = [*result.hits, *result.skipped]
        matched += bool(matches)
        scanned.append({"segment_id": segment.segment_id, "match_count": len(matches),
                        "replacement_count": len(result.hits),
                        "matches": [hit.to_dict() for hit in matches]})
        if not result.hits:
            words = list(getattr(segment, "words", ()) or ())
            joined = re.sub(r"\s", "", "".join(word.text for word in words))
            body = re.sub(r"\s", "", segment.text)
            if words and joined != body and joined.casefold() == body.casefold():
                segment.words = remap_words(segment.text, segment.text, words,
                    segment.start, segment.end, segment.confidence)
                word_case_syncs.append(segment.segment_id)
            segment.final_text = segment.text
            continue
        original = segment.text
        words = list(getattr(segment, "words", ()) or ())
        aligned = re.sub(r"\s", "", "".join(x.text for x in words)).casefold() == re.sub(r"\s", "", original).casefold()
        segment.words, span_mappings = remap_literal_words(original, result, words,
            segment.start, segment.end, segment.confidence)
        segment.text = result.text
        segment.final_text = result.text
        case_only = original.casefold() == result.text.casefold()
        source_span_mapped = bool(span_mappings) and all(
            row["precision"] == "whole_original_word_span" for row in span_mappings)
        receipt = {"snapshot_digest": snapshot.digest, "source": original, "result": result.text,
            "hits": [x.to_dict() for x in result.hits],
            "timing": "existing-word-spans" if aligned and words else "segment-only-no-word-alignment",
            "alignment_provenance": "exact_case_only" if case_only else
                "derived_term_source_span" if source_span_mapped else "term_local_mapping",
            "span_mappings": span_mappings, "acoustic_verified_spelling": False,
            "requires_acoustic_alignment": not case_only and not source_span_mapped}
        segment.caption_arbitration.setdefault("terminology_normalization", []).append(receipt)
        changes.append({"segment_id": segment.segment_id, **receipt})
    if legacy is not None:
        legacy.record_run_event("terminology_applied", snapshot_digest=snapshot.digest,
            segment_count=len(changes), replacement_count=sum(len(x["hits"]) for x in changes),
            segment_count_kind="changed_segments_legacy", scanned_segment_count=len(segments),
            matched_segment_count=matched, changed_segment_count=len(changes),
            word_case_sync_count=len(word_case_syncs), word_case_sync_segment_ids=word_case_syncs,
            scanned_term_count=len(resolver._rules), matches=scanned,
            conflicts=[x.to_dict() for x in resolver.conflicts], changes=changes)
    return segments
