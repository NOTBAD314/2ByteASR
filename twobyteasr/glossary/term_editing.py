"""Edit a selected library through its existing mappings/reference overrides.

One atomic write per edit. Undo restores only the affected library and refuses
to overwrite a later external change. No project caption is modified here.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from .terminology import GlossarySnapshot, snapshot_glossaries


@dataclass(frozen=True)
class LibraryTerm:
    library_id: str
    library_name: str
    canonical: str
    aliases: tuple[str, ...]
    category: str
    builtin: bool
    digest: str


def library_terms(snapshot):
    records = []
    for library in snapshot.libraries:
        grouped = {}
        try:
            raw = json.loads(library.profile_json or "{}")
        except ValueError:
            raw = {}
        profiles = {row.get("canonical"): row for row in raw.get("terms", ()) if isinstance(row, dict)}
        for term in library.terms:
            if not term.confirmed:
                continue
            value = grouped.setdefault(term.canonical, {"aliases": set(), "category": term.category, "builtin": False})
            value["aliases"].update(term.aliases)
            value["builtin"] |= term.provenance == "builtin"
        for name in library.reference_terms:
            grouped.setdefault(name, {"aliases": set(), "category": "参考词", "builtin": True})["builtin"] = True
        digest = GlossarySnapshot((library,)).digest
        for canonical, value in grouped.items():
            # Show the actual configured aliases, including contextual builtin
            # aliases which the literal resolver intentionally does not execute.
            if value["builtin"]:
                value["aliases"].update(profiles.get(canonical, {}).get("aliases", ()))
            aliases = tuple(sorted({a for a in value["aliases"] if a and a != canonical}, key=str.casefold))
            records.append(LibraryTerm(library.id, library.name, canonical, aliases,
                                       value["category"], value["builtin"], digest))
    return sorted(records, key=lambda r: (r.canonical.casefold(), r.library_name, r.library_id))


@dataclass
class LibraryEdit:
    library_id: str
    before: dict | None
    after: dict

    def undo(self, legacy):
        payload = legacy.load_learned_term_payload(strict=True)
        games = payload.setdefault("games", {})
        if games.get(self.library_id) != self.after:
            raise ValueError("词库随后已在别处修改，无法直接撤销；请刷新后检查该词条")
        if self.before is None:
            games.pop(self.library_id, None)
        else:
            games[self.library_id] = copy.deepcopy(self.before)
        legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)


def edit_term(legacy, record, canonical=None, aliases=(), *, delete=False):
    snapshot = snapshot_glossaries(legacy, (record.library_id,))
    if snapshot.digest != record.digest:
        raise ValueError("词库已在别处更新，请刷新后重新打开词条")
    canonical = str(canonical or "").strip()
    aliases = tuple(dict.fromkeys(str(a).strip() for a in aliases if str(a).strip() and str(a).strip() != canonical))
    if not delete and (not canonical or any(c in canonical for c in "\r\n")):
        raise ValueError("请填写一行规范词")
    if not delete and canonical != record.canonical and any(
            t.canonical != record.canonical and t.canonical.casefold() == canonical.casefold() for t in library_terms(snapshot)):
        raise ValueError("这个词库已存在该规范词，请直接编辑已有词条")
    payload = legacy.load_learned_term_payload(strict=True)
    games = payload.setdefault("games", {})
    before = copy.deepcopy(games.get(record.library_id))
    entry = games.setdefault(record.library_id, {"game": record.library_name, "mappings": []})
    mappings = [row for row in entry.get("mappings", ()) if row.get("to") != record.canonical]
    if record.builtin:
        hidden = set(entry.get("hidden_reference_terms", ())) | {record.canonical}
        entry["hidden_reference_terms"] = sorted(hidden)
    if not delete:
        for alias in (canonical, *aliases):
            if any(str(row.get("from", "")).casefold() == alias.casefold()
                   and str(row.get("to", "")).casefold() != canonical.casefold() for row in mappings):
                raise ValueError(f"别名冲突：{alias} 已指向另一个规范词，请先编辑该映射")
        prior = next((row for row in (before or {}).get("mappings", ()) if row.get("to") == record.canonical), {})
        inherited = next((term for lib in snapshot.libraries for term in lib.terms
                          if term.canonical == record.canonical), None)
        mappings.extend({"from": alias, "to": canonical, "category": record.category,
                         "origin": "手动", "confirmed": True, "provenance": "user_confirmed",
                         "correction_enabled": prior.get("correction_enabled", getattr(inherited,"correction_enabled",True)),
                         "emphasis_enabled": prior.get("emphasis_enabled", getattr(inherited,"emphasis_enabled",False))} for alias in (canonical, *aliases))
    entry["mappings"] = mappings
    legacy._touch_glossary_entry(entry, record.library_id)
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    return LibraryEdit(record.library_id, before, copy.deepcopy(entry))
