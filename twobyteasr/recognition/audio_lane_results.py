"""One result project from several separately recognized audio tracks.

2026-10-24 (multi-track import): the Studio track picker recognizes each
picked audio track of a multi-track source on its own input. The queue
writes one ordinary result project per track; this module combines them:

* captions the project already had for tracks that were *not* recognized
  now stay as they were (an older run without a source counts as the A lane
  of the primary video track, which is what it heard);
* each track's captions keep their own speakers. Speaker ids get the lane id
  as prefix and names the track's name ("中文配音 · S00"), so "S00" of two
  dubs is never merged into one person; ``studio_state["speaker_audio_sources"]``
  maps every such speaker to its source track (asset, relative ordinal,
  absolute stream index);
* cue ids, evidence keys, translations and caption receipts move together
  when an id has to be renamed.

A track that failed or was cancelled leaves its existing captions alone; the
project records it in ``generation_metadata["audio_stream_recognition"]`` and
preselects it for a retry.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable

SOURCES_KEY = "speaker_audio_sources"
CHOICE_KEY = "recognition_audio_streams"
SUMMARY_KEY = "audio_stream_recognition"


def lane_tag(source: dict) -> str:
    """Short track name for speaker names: the stream title, else '音轨 N'."""
    from ..i18n import tr
    record = source.get("record") or {}
    title = str(record.get("title") or "").strip()
    return title or str(tr("音轨 {number}", number=int(source.get("ordinal", 0)) + 1))


def public_source(source: dict) -> dict:
    """The source identity stored with each speaker (no paths beyond the file)."""
    keys = ("lane_id", "asset_id", "source_path", "source_name", "fingerprint", "ordinal",
            "stream_index", "source_key")
    row = {key: source.get(key) for key in keys}
    record = source.get("record") or {}
    row.update(title=str(record.get("title") or ""), language=str(record.get("language") or ""),
               channels=int(record.get("channels") or 0))
    return row


def primary_source_key(project) -> str:
    """Source of captions recognized before tracks had names: the primary A lane."""
    from ..timeline.audio_stream_lanes import recognizable_lanes, source_key
    from ..timeline.studio_media_pool import primary_video_track_id
    rows = recognizable_lanes(project)
    if not rows:
        return ""
    primary = primary_video_track_id(project)
    lane_id = next((g.audio_track_id for g in project.av_track_groups if g.video_track_id == primary), "")
    row = next((r for r in rows if r["lane_id"] == lane_id), rows[0])
    return source_key(row)


def caption_source_key(project, cue, primary_key: str = "") -> str:
    entry = (project.studio_state.get(SOURCES_KEY) or {}).get(cue.speaker_id)
    return str((entry or {}).get("source_key") or primary_key)


def caption_counts(project, keys: Iterable[str]) -> tuple[int, int]:
    """(captions a run over ``keys`` would replace, captions it keeps)."""
    keys = set(keys)
    primary = primary_source_key(project)
    replaced = sum(caption_source_key(project, cue, primary) in keys for cue in project.cues)
    return replaced, len(project.cues) - replaced


def _unique(wanted: str, used: set[str]) -> str:
    value, index = wanted, 2
    while value in used:
        value = f"{wanted}~{index}"
        index += 1
    used.add(value)
    return value


def _rename(value: Any, cues: dict, evidence: dict, speakers: dict) -> Any:
    """Rename cue/evidence/speaker references inside a receipt or archive row."""
    if isinstance(value, list):
        return [_rename(item, cues, evidence, speakers) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"source_cue_id"} and isinstance(item, str):
            result[key] = cues.get(item, item)
        elif key == "source_cue_ids" and isinstance(item, list):
            result[key] = [cues.get(x, x) for x in item]
        elif key in {"evidence_refs"} and isinstance(item, list):
            result[key] = [evidence.get(x, x) for x in item]
        elif key == "evidence_ref" and isinstance(item, str):
            result[key] = evidence.get(item, item)
        elif key == "speaker_id" and isinstance(item, str):
            result[key] = speakers.get(item, item)
        else:
            result[key] = _rename(item, cues, evidence, speakers)
    return result


def combine_lane_results(snapshot: dict, outputs: list, target, *, job_id: str, problems=(),
                         freeze_lane_captions: bool = False) -> dict:
    """Write the combined result project and return its committed reference.

    ``outputs``: ``(lane_run, project_path)`` of the tracks that finished, in
    the order they ran; ``problems``: ``(lane_run, status, error)``.
    ``freeze_lane_captions``: the track projects hold source-time captions
    (home-page runs); they move to project time first, as opening them in
    Studio would.
    """
    from ..caption_style.subtitle_stacking import initialize_project_layout
    from ..projects.studio_project import (SubtitleProject, load_project, register_recent_project,
                                           save_project, speaker_track_preference, studio_settings_path)
    from ..projects.speaker_names import display_speaker_name
    from ..subtitle_rules.subtitle_translation import RECORDS_KEY, sync_render_view
    from ..timeline.studio_caption_timeline import KEY, ensure_independent_captions
    from .recognition_result import committed_result_reference, stamp_result
    from .speaker_roles import KEY as ROLES_KEY, initialize_for_recognition

    target = Path(target)
    original = SubtitleProject.from_dict(copy.deepcopy(snapshot["project"]))
    # Kept captions move to project time, like every new caption.
    ensure_independent_captions(original)
    lanes = [(run, load_project(path)) for run, path in outputs]
    if freeze_lane_captions:
        for _run, project in lanes:
            ensure_independent_captions(project)
    base_run, base = lanes[0]
    combined = copy.deepcopy(base)
    selected = {run["audio_source"]["source_key"] for run, _project in lanes}
    primary = primary_source_key(original)

    cues, speakers, evidence = [], [], {}
    used_cues, used_speakers = set(), set()
    records, view, instances, archive, names, sources, states, visible = {}, {}, {}, [], {}, {}, {}, {}

    old_sources = original.studio_state.get(SOURCES_KEY) or {}
    old_records = (original.generation_metadata.get(RECORDS_KEY) or {}).get("records") or {}
    old_view = original.generation_metadata.get("translations") or {}
    old_receipts = original.studio_state.get(KEY) or {}
    old_names = (original.generation_metadata.get("speaker_names") or {}).get("entries") or {}
    old_states = original.generation_metadata.get("asr_cue_states") or {}
    old_visible = original.studio_state.get("subtitle_track_visibility") or {}
    kept_speakers: set[str] = set()
    referenced: set[str] = set()
    for cue in original.cues:
        if caption_source_key(original, cue, primary) in selected:
            continue
        cues.append(copy.deepcopy(cue))
        used_cues.add(cue.id)
        kept_speakers.add(cue.speaker_id)
        for ref in cue.evidence_refs:
            if ref in original.asr_evidence:
                evidence[ref] = copy.deepcopy(original.asr_evidence[ref])
        if cue.id in old_records:
            records[cue.id] = copy.deepcopy(old_records[cue.id])
        elif cue.id in old_view:
            view[cue.id] = old_view[cue.id]
        receipt = (old_receipts.get("instances") or {}).get(cue.id)
        if receipt:
            instances[cue.id] = copy.deepcopy(receipt)
            referenced.update(receipt.get("source_cue_ids") or [receipt.get("source_cue_id") or cue.id])
        if cue.id in old_states:
            states[cue.id] = old_states[cue.id]
    archive.extend(copy.deepcopy(row) for row in old_receipts.get("source_archive") or []
                   if isinstance(row, dict) and row.get("id") in referenced)
    # Archived task captions keep their ids too; a new caption never takes one.
    used_cues.update(str(row.get("id")) for row in archive)
    for speaker in original.speakers:
        if speaker.id in kept_speakers:
            speakers.append(copy.deepcopy(speaker))
            used_speakers.add(speaker.id)
            if speaker.id in old_names:
                names[speaker.id] = copy.deepcopy(old_names[speaker.id])
            if speaker.id in old_sources:
                sources[speaker.id] = copy.deepcopy(old_sources[speaker.id])
            if speaker.id in old_visible:
                visible[speaker.id] = old_visible[speaker.id]
    kept_count = len(cues)

    new_cue_ids: list[str] = []
    lane_summary = []
    from ..projects.studio_project import StudioSpeaker
    for run, project in lanes:
        source = run["audio_source"]
        prefix, tag = str(source["lane_id"]), lane_tag(source)
        present = {s.id for s in project.speakers}
        lane_speakers = list(project.speakers) + [
            StudioSpeaker(id=sid) for sid in dict.fromkeys(c.speaker_id for c in project.cues) if sid not in present]
        speaker_map = {s.id: _unique(f"{prefix}-{s.id}", used_speakers) for s in lane_speakers}
        cue_map = {c.id: _unique(c.id if c.id not in used_cues else f"{prefix}-{c.id}", used_cues)
                   for c in project.cues}
        used_evidence = set(evidence)
        evidence_map = {k: _unique(k if k not in used_evidence else f"{prefix}:{k}", used_evidence)
                        for k in project.asr_evidence}
        lane_names = (project.generation_metadata.get("speaker_names") or {}).get("entries") or {}
        lane_visible = project.studio_state.get("subtitle_track_visibility") or {}
        for speaker in lane_speakers:
            clone = copy.deepcopy(speaker)
            clone.id = speaker_map[speaker.id]
            clone.name = f"{tag} · {str(display_speaker_name(project, speaker))}"
            speakers.append(clone)
            names[clone.id] = dict(lane_names.get(speaker.id) or {}, name=clone.name, automatic=False,
                                   raw_label=speaker.id, audio_lane=prefix)
            sources[clone.id] = public_source(source)
            if speaker.id in lane_visible:
                visible[clone.id] = lane_visible[speaker.id]
        for key, value in project.asr_evidence.items():
            evidence[evidence_map[key]] = copy.deepcopy(value)
        lane_records = (project.generation_metadata.get(RECORDS_KEY) or {}).get("records") or {}
        lane_view = project.generation_metadata.get("translations") or {}
        lane_receipts = project.studio_state.get(KEY) or {}
        lane_states = project.generation_metadata.get("asr_cue_states") or {}
        for cue in project.cues:
            clone = copy.deepcopy(cue)
            clone.id = cue_map[cue.id]
            clone.speaker_id = speaker_map[cue.speaker_id]
            clone.evidence_refs = [evidence_map.get(ref, ref) for ref in cue.evidence_refs]
            cues.append(clone)
            new_cue_ids.append(clone.id)
            if cue.id in lane_records:
                records[clone.id] = copy.deepcopy(lane_records[cue.id])
            elif cue.id in lane_view:
                view[clone.id] = lane_view[cue.id]
            receipt = (lane_receipts.get("instances") or {}).get(cue.id)
            if receipt:
                instances[clone.id] = _rename(copy.deepcopy(receipt), cue_map, evidence_map, speaker_map)
            if cue.id in lane_states:
                states[clone.id] = lane_states[cue.id]
        for row in lane_receipts.get("source_archive") or []:
            if isinstance(row, dict):
                renamed = _rename(copy.deepcopy(row), cue_map, evidence_map, speaker_map)
                renamed["id"] = cue_map.get(row.get("id"), row.get("id"))
                archive.append(renamed)
        lane_summary.append({**public_source(source), "status": "success", "cue_count": len(project.cues),
                             "speaker_ids": list(speaker_map.values()),
                             "lane_project": project_path_of(outputs, run),
                             "report_path": str(project.report_path or "")})

    combined.cues = sorted(cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    combined.speakers = speakers
    combined.asr_evidence = evidence
    meta = combined.generation_metadata
    meta["speaker_names"] = {"version": 1, "entries": names}
    container = copy.deepcopy(base.generation_metadata.get(RECORDS_KEY) or original.generation_metadata.get(RECORDS_KEY) or {})
    if records or container:
        container = container or {"version": 1, "target": "", "records": {}, "history": []}
        container["records"] = records
        meta[RECORDS_KEY] = container
    meta["translations"] = view
    if states:
        meta["asr_cue_states"] = states
    meta.pop("asr_replacement_mapping", None)
    inputs = {}
    for _run, project in lanes:
        inputs.update(copy.deepcopy(project.generation_metadata.get("input_source_identities") or {}))
    if inputs:
        # Every track read the same files; the result pins all of them.
        meta["input_source_identities"] = inputs
    timeline = meta.get("timeline_recognition")
    if isinstance(timeline, dict):
        timeline["cue_ids"] = new_cue_ids
        timeline["fingerprint"] = snapshot["fingerprint"]
        timeline["audio_lanes"] = [public_source(run["audio_source"]) for run, _p in lanes]
    meta[SUMMARY_KEY] = {
        "version": 1,
        "lanes": lane_summary,
        "problems": [{**public_source(run["audio_source"]), "status": status, "error": str(error)}
                     for run, status, error in problems],
        "kept_cue_count": kept_count,
    }
    state = combined.studio_state
    state[KEY] = {"version": 1, "instances": instances, "source_archive": archive}
    state[SOURCES_KEY] = sources
    order = list(dict.fromkeys(c.speaker_id for c in combined.cues))
    state["speaker_track_order"] = order + [s.id for s in speakers if s.id not in order]
    state["subtitle_track_visibility"] = visible
    locked = [sid for sid in original.studio_state.get("locked_speakers") or [] if sid in kept_speakers]
    state["locked_speakers"] = locked
    # Next time the picker offers what failed, or else what was recognized.
    state[CHOICE_KEY] = ([run["audio_source"]["source_key"] for run, _s, _e in problems]
                         or [run["audio_source"]["source_key"] for run, _p in lanes])
    state.pop(ROLES_KEY, None)
    combined.render_settings["_cue_domain"] = "timeline"
    if RECORDS_KEY in meta:
        sync_render_view(combined)
    combined.validate()
    initialize_for_recognition(combined, cap=speaker_track_preference())
    if new_cue_ids:
        initialize_project_layout(combined, cue_ids=new_cue_ids, replace=True)
    identity = dict(base.generation_metadata.get("media_identity") or {})
    identity["fingerprint"] = snapshot["fingerprint"]
    identity["audio_lanes"] = [run["audio_source"]["source_key"] for run, _p in lanes]
    stamp_result(combined, target, job_id=job_id, media_identity=identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    for child in ("subtitles", "reports", "source", "autosave", "cache", "preview", "backup", "renders", "exports"):
        (target.parent / child).mkdir(parents=True, exist_ok=True)
    for run, path in outputs:
        srt = Path(path).parent / "subtitles" / "master.srt"
        if srt.is_file():
            (target.parent / "subtitles" / f"{run['audio_source']['lane_id']}.srt").write_bytes(srt.read_bytes())
    save_project(combined, target)
    reference = committed_result_reference(load_project(target), target)
    media = str(original.media.path or "")
    register_recent_project(target, source_media=media, cue_count=len(combined.cues))
    _forget_recent([Path(path) for _run, path in outputs], studio_settings_path())
    return reference


def combine_stream_results(media_path, finished, problems, target, *, job_id: str, base_project: str = "") -> dict:
    """One result project from the picked tracks of a home-page file (2026-10-24).

    ``finished`` / ``problems``: ``(MediaResult, audio_stream_choice)`` of the
    file's picked tracks. Each track's source identity comes from the result
    project's own audio lanes (the A lane of the default stream, a follower
    lane per other stream), so opening the result in Studio and recognizing a
    track again replaces exactly that track's captions. ``base_project``: the
    earlier combined result a retry adds to; its other tracks stay.
    """
    import hashlib
    from ..projects.studio_project import SubtitleProject, load_project
    from ..timeline.audio_stream_lanes import recognizable_lanes, source_key

    lane_projects = [(choice, load_project(item.project_path)) for item, choice in finished]
    base = lane_projects[0][1]
    rows = recognizable_lanes(base)
    wanted = Path(media_path).resolve()

    def source(choice) -> dict:
        row = next((r for r in rows if r["ordinal"] == int(choice["ordinal"])
                    and Path(str(r.get("source_path") or "")).resolve() == wanted), None)
        if row is None:
            # No lane for this stream (the result was written without stream
            # data): the track is still named by its own stream.
            row = {"lane_id": f"A{int(choice['ordinal']) + 1}", "route_id": "", "asset_id": "",
                   "source_path": str(wanted), "source_name": wanted.name,
                   "fingerprint": str(base.media.fingerprint or ""), "follower": int(choice["ordinal"]) > 0}
        lane = {key: row.get(key) for key in ("lane_id", "route_id", "asset_id", "source_path", "source_name",
                                               "fingerprint", "follower")}
        lane.update(ordinal=int(choice["ordinal"]), stream_index=int(choice["stream_index"]),
                    record=dict(choice.get("record") or row.get("record") or {}))
        lane["source_key"] = source_key(lane)
        return lane

    original = None
    if base_project and Path(base_project).is_file():
        try:
            original = load_project(base_project)
        except (OSError, ValueError, TypeError):
            original = None
    if original is None:
        # A first run keeps nothing: an empty project of the same file.
        original = SubtitleProject(media=copy.deepcopy(base.media))
    runs = [{"audio_source": source(choice)} for _item, choice in finished]
    outputs = [(run, Path(item.project_path)) for run, (item, _choice) in zip(runs, finished)]
    failed = [({"audio_source": source(choice)}, item.status, item.error or "没有生成工程")
              for item, choice in problems]
    fingerprint = hashlib.sha256("|".join(
        str(item.media_fingerprint or "") for item, _choice in finished).encode("utf-8")).hexdigest()[:20]
    snapshot = {"project": original.to_dict(), "fingerprint": fingerprint}
    return combine_lane_results(snapshot, outputs, target, job_id=job_id, problems=failed,
                                freeze_lane_captions=True)


def project_path_of(outputs, run) -> str:
    return next((str(path) for item, path in outputs if item is run), "")


def _forget_recent(paths, settings: Path) -> None:
    """Per-track working projects are not results the user opens by hand."""
    try:
        payload = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(payload, dict):
        return
    drop = {str(Path(path).resolve()) for path in paths}
    records = payload.get("recent_projects") or []
    kept = [item for item in records if not (isinstance(item, dict) and str(item.get("path", "")) in drop)]
    if len(kept) != len(records):
        payload["recent_projects"] = kept
        settings.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["CHOICE_KEY", "SOURCES_KEY", "SUMMARY_KEY", "caption_counts", "caption_source_key",
           "combine_lane_results", "combine_stream_results", "lane_tag", "primary_source_key"]
