"""Canonical JSON text of frozen persistence revisions, reused by identity.

2026-10-22 (report-eb10 stage 1): every autosave thawed the whole frozen
project back into dicts (~0.3-0.6 s on 2090 cues with 50 MB of recognition
evidence) and encoded all of it again (~0.3 s), in a Python thread that kept
the editor waiting for the GIL. Frozen values are immutable and the revision
store shares unchanged ones between revisions, so the text of a frozen value
seen in the previous autosave is still its text: only changed rows, cues and
fields are encoded now.

The output is the same text ``studio_project._canonical_json`` produces from
``revision.to_payload()`` (compact, sorted keys), so files and content
fingerprints do not change. A part is a list of string pieces; writing and
hashing piece by piece never builds one 60 MB string.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from .studio_revisions import FrozenBlob, FrozenMap, PersistenceRevision, freeze_json, thaw_json

# studio_state keys a content fingerprint ignores (studio_project).
FINGERPRINT_IGNORED_STATE = frozenset({"last_opened", "review_risks", "review_confirmations", "cue_statuses"})
FINGERPRINT_IGNORED_KEYS = frozenset({"autosave", "updated_at", "created_at", "project_id"})


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty(value: Any) -> str:
    """The formal project file's encoding of one value at nesting level 0."""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


class FrozenTextCache:
    """Text of frozen containers and revision DTOs from this and the last use.

    Entries hold the object itself, so its ``id`` cannot be reused while the
    entry lives. ``finish()`` keeps only what the latest revision used.
    ``encoder`` is ``dump`` (autosave) or ``pretty`` (formal save).
    """

    def __init__(self, encoder=dump) -> None:
        self._encoder = encoder
        self._previous: dict[int, tuple[object, str]] = {}
        self._current: dict[int, tuple[object, str]] = {}
        self.encoded = 0
        self.reused = 0

    def _lookup(self, value, make) -> str:
        key = id(value)
        hit = self._current.get(key) or self._previous.get(key)
        if hit is not None and hit[0] is value:
            self._current[key] = hit
            self.reused += 1
            return hit[1]
        text = make()
        self._current[key] = (value, text)
        self.encoded += 1
        return text

    def frozen(self, value) -> str:
        """``encoder(thaw_json(value))``."""
        if isinstance(value, (FrozenMap, FrozenBlob)) or (isinstance(value, tuple) and value):
            return self._lookup(value, lambda: self._encoder(thaw_json(value)))
        return self._encoder(thaw_json(value))

    def dto(self, value) -> str:
        """``encoder(value.to_dict())`` for an immutable revision DTO."""
        return self._lookup(value, lambda: self._encoder(value.to_dict()))

    def finish(self) -> None:
        self._previous, self._current = self._current, {}

    def known(self, value) -> bool:
        hit = self._current.get(id(value)) or self._previous.get(id(value))
        return hit is not None and hit[0] is value

    def prefetch(self, values, *, minimum: int = 256) -> int:
        """Encode uncached blobs in the resident worker (stall stage 3).

        The first autosave or formal save of a session encodes every evidence
        row (0.5-1.7 s of Python on 2090 cues, competing with the GUI thread
        for the GIL). The worker does that work; the caller only pickles the
        bytes. Skipped when few are missing or the worker is busy or off.
        """
        missing = [value for value in values if isinstance(value, FrozenBlob) and not self.known(value)]
        if len(missing) < minimum:
            return 0
        from ..system.resident_worker import shared_worker
        worker = shared_worker()
        if worker is None:
            return 0
        texts = worker.call("twobyteasr.projects.frozen_json_text:encode_blobs",
                            (self._encoder is pretty, [(value.data, value.plain) for value in missing]),
                            wait=False)
        if not isinstance(texts, list) or len(texts) != len(missing):
            return 0
        for value, text in zip(missing, texts):
            self._current[id(value)] = (value, text)
        self.encoded += len(missing)
        return len(missing)


def encode_blobs(request) -> list[str]:
    """Resident-worker job: text of each ``(data, plain)`` FrozenBlob."""
    pretty_text, blobs = request
    encoder = pretty if pretty_text else dump
    return [encoder(thaw_json(FrozenBlob(data, plain))) for data, plain in blobs]


def _key(name: str) -> str:
    return json.dumps(name, ensure_ascii=False) + ":"


def frozen_part(value, cache: FrozenTextCache, *, skip: Iterable[str] = ()) -> list[str]:
    """``_canonical_json(thaw_json(value), 1)`` as pieces (children cached)."""
    skipped = frozenset(skip)
    if isinstance(value, FrozenMap):
        items = [(key, item) for key, item in value.items if key not in skipped]
        if not items:
            return ["{}"]
        pieces = ["{"]
        for index, (key, item) in enumerate(items):
            if index:
                pieces.append(",")
            pieces.append(_key(key))
            pieces.append(cache.frozen(item))
        pieces.append("}")
        return pieces
    if isinstance(value, tuple) and value:
        pieces = ["["]
        for index, item in enumerate(value):
            if index:
                pieces.append(",")
            pieces.append(cache.frozen(item))
        pieces.append("]")
        return pieces
    if isinstance(value, FrozenBlob) and not skipped:
        # Depth-1 canonical text of a whole value equals its compact dump.
        return [cache.frozen(value)]
    if isinstance(value, FrozenBlob):
        return frozen_part(freeze_json(thaw_json(value)), cache, skip=skipped)
    return [dump(thaw_json(value))]


def _dto_list_part(values, cache: FrozenTextCache) -> list[str]:
    if not values:
        return ["[]"]
    pieces = ["["]
    for index, value in enumerate(values):
        if index:
            pieces.append(",")
        pieces.append(cache.dto(value))
    pieces.append("]")
    return pieces


def _plain_part(value) -> list[str]:
    from .studio_project import _canonical_json
    return [_canonical_json(value, 1)]


def persistence_parts(revision: PersistenceRevision, cache: FrozenTextCache) -> dict[str, list[str]]:
    """Canonical text pieces of each ``revision.to_payload()`` value."""
    parts = {
        "media": _plain_part(revision.media.to_dict()),
        "cues": _dto_list_part(revision.cues, cache),
        "speakers": _dto_list_part(revision.speakers, cache),
        "styles": _dto_list_part(revision.styles, cache),
        "glossary_ids": _plain_part(list(revision.glossary_ids)),
        "report_path": [dump(revision.report_path)],
        "project_id": [dump(revision.project_id)],
        "created_at": [dump(revision.created_at)],
        "updated_at": [dump(revision.updated_at)],
        "schema_version": [dump(revision.schema_version)],
    }
    for name in ("media_pool", "video_tracks", "audio_tracks", "av_track_groups", "effects", "style_recipes",
                 "generation_metadata", "asr_evidence", "edit_history", "render_settings", "original_outputs",
                 "studio_state", "edit_sequence"):
        parts[name] = frozen_part(getattr(revision, name), cache)
    return parts


def object_pieces(parts: dict[str, list[str]]) -> list[str]:
    """Pieces of ``{"key":part,...}`` with keys sorted, as ``_join_canonical_object``."""
    pieces = ["{"]
    for index, key in enumerate(sorted(parts)):
        if index:
            pieces.append(",")
        pieces.append(_key(key))
        pieces.extend(parts[key])
    pieces.append("}")
    return pieces


def pretty_map_pieces(value: FrozenMap, cache: FrozenTextCache, level: int) -> list[str]:
    """``pretty(thaw_json(value))`` as written for a value at nesting ``level``
    (children indented one level deeper), as pieces; children from ``cache``."""
    if not value.items:
        return ["{}"]
    pad = "  " * (level + 1)
    pieces = ["{\n"]
    for index, (key, item) in enumerate(value.items):
        if index:
            pieces.append(",\n")
        pieces.append(pad + json.dumps(key, ensure_ascii=False) + ": ")
        pieces.append(cache.frozen(item).replace("\n", "\n" + pad))
    pieces.append("\n" + "  " * level + "}")
    return pieces


def pretty_document_pieces(payload: dict, frozen: dict, cache: FrozenTextCache) -> list[str]:
    """``json.dumps(payload, indent=2, sort_keys=True) + "\\n"`` as pieces.

    ``frozen`` maps some top-level keys to frozen values whose thawed content
    equals ``payload[key]``; their text comes from ``cache``.
    """
    pieces = ["{\n"]
    for index, key in enumerate(sorted(payload)):
        if index:
            pieces.append(",\n")
        pieces.append("  " + json.dumps(key, ensure_ascii=False) + ": ")
        value = frozen.get(key)
        if isinstance(value, FrozenMap):
            pieces.extend(pretty_map_pieces(value, cache, 1))
        else:
            text = cache.frozen(value) if value is not None else pretty(payload[key])
            pieces.append(text.replace("\n", "\n  "))
    pieces.append("\n}\n")
    return pieces


def fingerprint_pieces(revision: PersistenceRevision, parts: dict[str, list[str]],
                       cache: FrozenTextCache) -> list[str]:
    """Pieces whose UTF-8 SHA-256 is ``_content_fingerprint_payload(payload)``."""
    selected = {key: part for key, part in parts.items() if key not in FINGERPRINT_IGNORED_KEYS}
    if isinstance(revision.studio_state, FrozenMap):
        selected["studio_state"] = frozen_part(revision.studio_state, cache, skip=FINGERPRINT_IGNORED_STATE)
    return object_pieces(selected)
