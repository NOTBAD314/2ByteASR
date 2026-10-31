"""Checksum-bound SRT companions; no internal markers in player-visible text."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..projects.subtitle_import import (IMPORT_KEY, SIDECAR_FORMAT, imported_track,
                                       normalize_language, normalize_speaker, sidecar_path)


def track_language(project, track_id: str, fallback: str = "") -> str:
    track = imported_track(project, track_id)
    return track.get("language", "") if track else fallback


def write_srt_metadata(candidate: Path, project, cues, *, export_id: str,
                       layer: str = "original", source_language: str = "", target: str = "") -> Path:
    from ..subtitle_rules.language_rules import project_language
    from ..subtitle_rules.subtitle_translation import translation_view
    from ..caption_style.bilingual_layout import settings_from_state
    from .studio_subtitle_export import _lookup_translation

    speakers = {s.id: s for s in project.speakers}
    translations = translation_view(project)
    if layer == "display":
        layer = settings_from_state(project.studio_state).mode
    rows = []
    for number, cue in enumerate(sorted(cues, key=lambda c: (c.start_ms, c.end_ms, c.id)), 1):
        track = imported_track(project, cue.speaker_id)
        # A display label is only a speaker code when it is exactly S<n>.
        speaker = speakers.get(cue.speaker_id)
        label = normalize_speaker(speaker.name if speaker else "")
        import re
        sid = track.get("speaker", "") if track else (
            label if re.fullmatch(r"S\d+", label) else normalize_speaker(cue.speaker_id))
        language = track_language(project, cue.speaker_id, source_language or project_language(project) or "")
        role = track.get("role", "independent") if track else "original"
        info = _lookup_translation(translations, cue.id) or {}
        if layer == "translation" or (layer == "bilingual" and info.get("text")):
            role = layer
            language = (target or info.get("target", "")) if layer == "translation" else ""
        original = project.generation_metadata.get(IMPORT_KEY, {}).get("cues", {}).get(cue.id, {})
        association = original.get("association") or (
            dict(export_id=original["export_id"], cue_id=original["source_cue"])
            if original.get("export_id") and original.get("source_cue") else dict(export_id=export_id, cue_id=cue.id))
        rows.append(dict(number=number, start_ms=cue.start_ms, end_ms=cue.end_ms,
                         speaker=sid, language=normalize_language(language), track_id=cue.speaker_id,
                         cue_id=cue.id, role=role, association=association))
    payload = dict(format=SIDECAR_FORMAT, version=1, export_id=export_id,
                   project_id=project.project_id, sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(), rows=rows)
    companion = sidecar_path(candidate)
    companion.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return companion
