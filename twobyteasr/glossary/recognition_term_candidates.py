"""Reviewable term groups recovered from a project's proofreading receipts."""

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata


@dataclass(frozen=True)
class TermOccurrence:
    source_ref: str
    source_revision: str
    source_span: tuple[int, int]
    cue_id: str
    cue_text: str
    cue_span: tuple[int, int]
    start_ms: int
    end_ms: int
    surface: str


def _key(text):
    return unicodedata.normalize("NFKC", text).casefold()


def _eligible_edit(edit):
    from ..subtitle_rules.polish_disposition import unresolved_edit

    if not unresolved_edit(edit) or edit.get("type") not in {
        "phonetic_correction", "alias_normalization", "id_spelling", "asr_correction"
    }:
        return False
    return all(2 <= len(edit[key]) <= 18 and any(char.isalpha() for char in edit[key])
               and not any(char.isdigit() for char in edit[key]) for key in ("from", "to"))


def project_candidates(project, *, locked_ids=()):
    proposed = defaultdict(set)
    quarantined = defaultdict(int)
    for ref, row in project.asr_evidence.items():
        if not ref.startswith("segment:") or not isinstance(row, dict):
            continue
        detail = (row.get("caption_arbitration") or {}).get("terminology_polish") or {}
        for edit in detail.get("rejected_edits", ()):
            if _eligible_edit(edit):
                proposed[edit["to"]].add(edit["from"])
        for term in detail.get("new_suspects", ()):
            surface = str(term.get("surface") or "") if isinstance(term, dict) else ""
            if 2 <= len(surface) <= 18 and any(char.isalpha() for char in surface):
                proposed[surface].add(surface)
                if term.get("validation_state") == "invalid":
                    quarantined[surface] += 1

    if not proposed:
        return ()
    surfaces = {name for canonical, aliases in proposed.items() for name in {canonical, *aliases}}
    pattern = re.compile("|".join(re.escape(name) for name in sorted(surfaces, key=lambda x: (-len(x), x))))
    from ..studio.studio_text_tools import cue_locked

    positions = defaultdict(list)
    for cue in project.cues:
        if cue_locked(cue, locked_ids) or cue.original_text and cue.text != cue.original_text:
            continue
        for match in pattern.finditer(cue.text):
            if match.group().isascii() and (
                match.start() and re.fullmatch(r"[A-Za-z0-9_]", cue.text[match.start()-1])
                or match.end() < len(cue.text) and re.fullmatch(r"[A-Za-z0-9_]", cue.text[match.end()])
            ):
                continue
            compatible = []
            for ref in cue.evidence_refs:
                row = project.asr_evidence.get(ref, {})
                text = str(row.get("final_text") or row.get("text") or "")
                index = text.find(match.group())
                if index >= 0 and index == text.rfind(match.group()):
                    compatible.append((ref, text, index))
            if len(compatible) != 1:
                continue
            ref, text, index = compatible[0]
            positions[match.group()].append(TermOccurrence(
                ref, sha256(text.encode("utf-8")).hexdigest(), (index, index + len(match.group())),
                cue.id, cue.text, match.span(), cue.start_ms, cue.end_ms, match.group()))

    terms = []
    for canonical, aliases in proposed.items():
        variants = {name: tuple(positions[name]) for name in sorted({canonical, *aliases}) if positions[name]}
        if not variants and not quarantined[canonical]:
            continue
        entity = sha256((project.project_id + "\x00" + _key(canonical)).encode("utf-8")).hexdigest()
        terms.append({"entity_id": entity, "canonical": canonical, "variants": variants,
                      "quarantined": quarantined[canonical]})
    terms.sort(key=lambda row: (-sum(map(len, row["variants"].values())), row["canonical"]))
    return tuple(terms)


def preview_occurrences(project, group, canonical, enabled, *, locked_ids=()):
    from ..studio.studio_text_tools import TextOccurrence, cue_locked

    cues = {cue.id: cue for cue in project.cues}
    for surface in enabled:
        if surface == canonical:
            continue
        for item in group["variants"].get(surface, ()):
            cue = cues.get(item.cue_id)
            evidence = project.asr_evidence.get(item.source_ref, {})
            source = str(evidence.get("final_text") or evidence.get("text") or "")
            left, right = item.source_span
            if (cue is None or cue_locked(cue, locked_ids) or cue.text != item.cue_text
                    or sha256(source.encode("utf-8")).hexdigest() != item.source_revision
                    or source[left:right] != surface):
                continue
            yield TextOccurrence(cue.id, item.start_ms, surface, canonical, item.cue_span,
                reason="辨识术语候选 · 待用户确认", default_selected=True,
                source="recognition_entity_review", baseline=cue.text,
                evidence=f"{item.source_ref} [{left}, {right})")
