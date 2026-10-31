"""Immutable, timeline-local recognition input and non-destructive delivery.

The rendered WAV is the media seen by *every* pipeline branch and cache.
No worker writes back to the source project. Results retain the edit graph;
their cues use the captured timeline, with an explicit projection contract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _graph_sources(graph):
    sources = {}
    for layer in graph["segments"]:
        path = Path(layer["source_path"]).resolve()
        stat = path.stat()
        sources[str(path)] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return sources


def capture_recognition_snapshot(project, project_path="", *, lanes=None, lane=None, range_ms=None):
    """See ``_capture``; ``lane`` alone hears one picked lane in a single run
    (仅本地识别: its transcript is stored apart, nothing is replaced).

    ``range_ms`` (2026-10-25, 只重新识别这一段): only this stretch of the
    timeline mix is heard; the result replaces the captions there
    (``range_recognition``)."""
    if range_ms is not None:
        if lanes or lane is not None:
            raise ValueError("只识别一段时不能同时选择音轨。")
        return _capture(project, project_path, range_ms=range_ms)
    if lane is None:
        return _capture(project, project_path, lanes=lanes)
    snapshot = _capture(project, project_path, lanes=[lane])
    run = snapshot.pop("audio_lanes")[0]
    snapshot.pop("audio_lanes_digest", None)
    snapshot.update(audio_graph=run["audio_graph"], sources=run["sources"], audio_source=run["audio_source"])
    identity = {k: snapshot[k] for k in ("version", "duration_ms", "audio_graph", "sequence", "sources", "audio_source")}
    snapshot["fingerprint"] = _digest(identity)
    return snapshot


def _capture(project, project_path="", *, lanes=None, range_ms=None):
    """Freeze what one recognition run hears.

    Without ``lanes`` the input is the timeline mix (as before). With
    ``lanes`` (rows of ``timeline.audio_stream_lanes.recognizable_lanes``,
    2026-10-24) every picked audio lane gets its own graph, sources and
    fingerprint under ``audio_lanes``: one lane, one input, one result, so
    two dubs are never mixed into one recognition.
    """
    from ..playback.audio_graph import capture_audio_graph, capture_lane_audio_graph
    from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
    project = copy.deepcopy(project)
    data = project.to_dict()
    duration = timeline_duration_ms(project)
    if duration <= 0:
        raise ValueError("当前时间轴为空，无法识别字幕。")
    sequence = sequence_of(project).to_dict()
    snapshot = {"project": data, "project_id": project.project_id, "project_path": str(project_path),
                "project_revision": project_content_revision(data)}
    if not lanes:
        graph = capture_audio_graph(project)
        identity = {"version": 2, "duration_ms": duration, "audio_graph": graph,
                    "sequence": sequence, "sources": _graph_sources(graph)}
        if range_ms is not None:
            start, end = int(range_ms[0]), int(range_ms[1])
            if start < 0 or end > duration or end <= start:
                raise ValueError("要识别的这一段超出了时间轴，请重新设置入点和出点。")
            identity.update(duration_ms=end - start, range_ms=[start, end])
        return {**identity, "fingerprint": _digest(identity), **snapshot}
    from ..timeline.audio_stream_lanes import source_key
    runs = []
    for row in lanes:
        lane_id = str(row["lane_id"])
        graph = capture_lane_audio_graph(project, lane_id)
        if not graph["segments"]:
            raise ValueError(f"音轨 {lane_id} 在当前时间轴上没有可识别的声音（片段被停用或不在剪辑范围内）。")
        source = {key: row.get(key) for key in ("lane_id", "route_id", "asset_id", "source_path", "source_name",
                                                 "fingerprint", "ordinal", "stream_index", "follower")}
        source["record"] = dict(row.get("record") or {})
        source["source_key"] = source_key(row)
        identity = {"version": 2, "duration_ms": duration, "audio_graph": graph,
                    "sequence": sequence, "sources": _graph_sources(graph), "audio_source": source}
        runs.append({**identity, "fingerprint": _digest(identity)})
    sources = {}
    for run in runs:
        sources.update(run["sources"])
    identity = {"version": 2, "duration_ms": duration, "audio_graph": runs[0]["audio_graph"],
                "sequence": sequence, "sources": sources,
                "audio_lanes_digest": _digest([run["fingerprint"] for run in runs])}
    return {**identity, "fingerprint": _digest(identity), "audio_lanes": runs, **snapshot}


def lane_snapshots(snapshot):
    """One self-contained snapshot per picked lane ([snapshot] for a mix run)."""
    runs = snapshot.get("audio_lanes") or []
    if not runs:
        return [snapshot]
    shared = {k: v for k, v in snapshot.items() if k not in {"audio_lanes", "audio_lanes_digest"}}
    return [{**shared, **copy.deepcopy(run), "lane_index": index, "lane_total": len(runs)}
            for index, run in enumerate(runs, 1)]


def range_identity_keys(snapshot):
    """Extra identity keys of a range run (two stretches of one length never share a cache)."""
    return ("range_ms",) if snapshot.get("range_ms") else ()


def project_content_revision(data):
    # Conservative late-result guard: studio_state also contains mixer edits.
    return _digest({k: v for k, v in data.items() if k != "updated_at"})


def prepare_recognition_input(snapshot, cache_root, ffmpeg, *, token=None):
    from ..exports.audio_export import audio_mix_arguments
    from ..system.processes import popen_hidden_subprocess, stop_process_tree
    from ..exports.timeline_media import resolve_audio_layers, TIME_CONTRACT

    def cancelled():
        if token is not None:
            token.raise_if_cancelled()
        return False

    # Resolve BEFORE accepting a cached task WAV. v1 cached timestamp-domain
    # seeks are not compatible even when path, edit list and duration match.
    layers, timebases = resolve_audio_layers(snapshot['audio_graph']['segments'],
                                            ffmpeg, cancelled=cancelled)
    snapshot.update(version=2, media_time_contract=TIME_CONTRACT, media_timebases=timebases)
    snapshot['fingerprint'] = _digest({k: snapshot[k] for k in
        ('version', 'duration_ms', 'audio_graph', 'sequence', 'sources', 'media_time_contract', 'media_timebases')
        + range_identity_keys(snapshot)})
    range_start, range_end = snapshot.get('range_ms') or (0, snapshot['duration_ms'])
    root = Path(cache_root) / "timeline-inputs" / snapshot["fingerprint"]
    root.mkdir(parents=True, exist_ok=True)
    target, manifest = root / "timeline.wav", root / "input.json"
    expected_frames = round(snapshot["duration_ms"] * 16)
    for source, identity in snapshot["sources"].items():
        stat = Path(source).stat()
        if (stat.st_size, stat.st_mtime_ns) != (identity["size"], identity["mtime_ns"]):
            raise RuntimeError(f"识别启动后素材已改变：{source}")
    if target.is_file() and manifest.is_file():
        try:
            prior = json.loads(manifest.read_text(encoding="utf-8"))
            with wave.open(str(target), "rb") as wav:
                valid = (wav.getnframes() == expected_frames and wav.getframerate() == 16000
                         and wav.getnchannels() == 1 and wav.getsampwidth() == 2)
            if (valid and prior.get("fingerprint") == snapshot["fingerprint"]
                    and prior.get('media_time_contract') == TIME_CONTRACT
                    and prior.get('audio_sha256') == _file_sha256(target)):
                return str(target)
        except (OSError, ValueError, wave.Error):
            pass
    duration = snapshot["duration_ms"] / 1000
    # A range run hears only [range_start, range_end) of the timeline mix.
    job = SimpleNamespace(start_seconds=range_start / 1000, duration_seconds=duration,
                          video_graph={"duration_ms": range_end})
    args = audio_mix_arguments(str(ffmpeg), job, layers)
    if args == ["-an"]:
        args = ["-map", "0:a:0", "-c:a", "pcm_s16le"]
    temporary = root / f"timeline-{uuid.uuid4().hex}.wav"
    command = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
               f"anullsrc=r=16000:cl=mono:d={duration:.6f}", *args,
               "-t", f"{duration:.6f}", "-ac", "1", "-ar", "16000", str(temporary)]
    (root / "render-command.json").write_text(json.dumps(command, ensure_ascii=False), encoding="utf-8")
    try:
        # File stderr avoids a full pipe deadlock during long media decoding.
        with (root / "render.log").open("w", encoding="utf-8") as log:
            proc = popen_hidden_subprocess(command, purpose="timeline recognition audio", stdout=subprocess.DEVNULL, stderr=log)
            try:
                while True:
                    if token is not None:
                        token.raise_if_cancelled()
                    try:
                        code = proc.wait(timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    stop_process_tree(proc)
        if code:
            raise RuntimeError(f"时间轴音频准备失败，请查看 {root / 'render.log'}")
        with wave.open(str(temporary), "rb") as wav:
            if wav.getnframes() != expected_frames:
                raise RuntimeError(f"时间轴音频长度与剪辑快照不一致：{wav.getnframes()} != {expected_frames}，已停止识别。")
        os.replace(temporary, target)
        public = {k: v for k, v in snapshot.items() if k != "project"}
        public.update(input_path=str(target), sample_rate=16000, channels=1,
                      frames=expected_frames, time_domain="timeline", audio_sha256=_file_sha256(target),
                      rendered_audio_segments=layers, project_range_ms=[range_start, range_end])
        manifest.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)
    finally:
        temporary.unlink(missing_ok=True)


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def attach_timeline_result(result, snapshot):
    """Return an independent result project without changing source data."""
    from ..projects.studio_project import SubtitleProject
    captured = SubtitleProject.from_dict(copy.deepcopy(snapshot["project"]))
    original = captured.to_dict()
    captured.project_id = uuid.uuid4().hex
    captured.studio_state["project_name"] = f"{Path(snapshot.get('project_path') or '时间轴').stem} · 识别结果"
    captured.studio_state["project_name_automatic"] = True
    captured.studio_state["project_name_origin"] = {"kind": "recognition_result", "parent": Path(snapshot.get("project_path") or "").stem}
    if snapshot.get("range_ms"):
        return _attach_range_result(captured, result, snapshot)
    captured.cues = result.cues
    # These cues are a new recognition result. Anonymous ids cannot inherit
    # the previous task's host identity or hidden-track state.
    captured.speakers = copy.deepcopy(result.speakers)
    speaker_ids = [s.id for s in captured.speakers]
    order = result.studio_state.get('speaker_track_order', [])
    captured.studio_state['speaker_track_order'] = list(dict.fromkeys(
        [sid for sid in order if sid in speaker_ids] + speaker_ids))
    captured.studio_state['subtitle_track_visibility'] = copy.deepcopy(
        result.studio_state.get('subtitle_track_visibility', {}))
    # Speaker roles belong to the new result's speakers, never the old ones.
    if result.studio_state.get('speaker_roles'):
        captured.studio_state['speaker_roles'] = copy.deepcopy(result.studio_state['speaker_roles'])
    else:
        captured.studio_state.pop('speaker_roles', None)
    if captured.studio_state.get('last_selected_cue') not in {c.id for c in result.cues}:
        captured.studio_state.pop('last_selected_cue', None)
    captured.generation_metadata.pop('speaker_recovery_error', None)
    captured.asr_evidence = result.asr_evidence
    captured.report_path = result.report_path
    captured.original_outputs = copy.deepcopy(result.original_outputs)
    captured.generation_metadata = {**captured.generation_metadata, **result.generation_metadata,
        "timeline_recognition": {"fingerprint": snapshot["fingerprint"],
            "media_time_contract": snapshot.get('media_time_contract', 'legacy-v1'),
            "media_timebases": copy.deepcopy(snapshot.get('media_timebases', {})),
            "source_project_id": snapshot["project_id"],
            "source_project_path": snapshot["project_path"],
            "source_project_revision": snapshot["project_revision"],
            "duration_ms": snapshot["duration_ms"], "sequence": snapshot["sequence"],
            "cue_ids": [cue.id for cue in result.cues],
            "original_cues": original["cues"], "original_speakers": original["speakers"]}}
    from ..timeline.caption_source_receipts import initialize_recognition_receipts
    prior_domain = captured.render_settings.get('_cue_domain')
    initialize_recognition_receipts(captured, result)
    if prior_domain != 'timeline':
        # Retain source-domain projection for legacy consumers until the
        # existing independent-caption migration runs at Studio open.
        if prior_domain is None:
            captured.render_settings.pop('_cue_domain', None)
        else:
            captured.render_settings['_cue_domain'] = prior_domain
    return captured


# Metadata about the captions and speakers themselves: a range run's values
# describe its own anonymous result, so the captured project keeps its own.
_RANGE_KEPT_METADATA = ("translations", "translation_records", "speaker_names", "asr_cue_states",
                        "asr_replacement_mapping", "cue_forced_alignment", "speaker_recovery",
                        "speaker_recovery_error", "transcript_acceptance")


def _attach_range_result(captured, result, snapshot):
    """2026-10-25 (只重新识别这一段): the captured project with only the range replaced.

    The written result is the whole captured project with the range's new
    captions spliced in, which is also what the Studio's undoable
    replacement produces from it; speakers, styles, the edit and every caption
    outside the range stay as captured. ``timeline_recognition["range"]``
    names the new captions for the Studio.
    """
    from .range_recognition import apply_plan, cue_signature, history_entry, range_payload, splice_range
    start, end = (int(value) for value in snapshot["range_ms"])
    kept = {key: copy.deepcopy(captured.generation_metadata[key])
            for key in _RANGE_KEPT_METADATA if key in captured.generation_metadata}
    metadata = {**captured.generation_metadata, **result.generation_metadata}
    for key in _RANGE_KEPT_METADATA:
        metadata.pop(key, None)
    metadata.update(kept)
    captured.report_path = result.report_path
    captured.original_outputs = copy.deepcopy(result.original_outputs)
    info = {"fingerprint": snapshot["fingerprint"],
            "media_time_contract": snapshot.get('media_time_contract', 'legacy-v1'),
            "media_timebases": copy.deepcopy(snapshot.get('media_timebases', {})),
            "source_project_id": snapshot["project_id"],
            "source_project_path": snapshot["project_path"],
            "source_project_revision": snapshot["project_revision"],
            "duration_ms": snapshot["duration_ms"], "sequence": snapshot["sequence"],
            "range_ms": [start, end]}
    captured.generation_metadata = {**metadata, "timeline_recognition": info}
    # Input fingerprints repeat on a retry. Speaker labels belong to this
    # result task, so use its persistent project identity as well.
    import hashlib
    task = str(result.generation_metadata.get('job_id') or result.project_id)
    prefix = 'range-' + hashlib.sha256(task.encode('utf8')).hexdigest()[:12]
    payload = range_payload(result, start, end, prefix=prefix, span_project=captured)
    plan = splice_range(captured, (start, end), payload, foreign_speakers=True)
    if result.generation_metadata.get('transcript_acceptance'):
        from .language_recovery_project import inherit_range_appearance
        inherit_range_appearance(captured, plan)
    info["cue_ids"] = list(plan.inserted_ids)
    info["range"] = {"window_ms": [start, end], "requested_ms": list(snapshot.get("requested_range_ms") or (start, end)),
                     "cue_ids": list(plan.inserted_ids), "replaced_cue_ids": list(plan.removed_ids),
                     "replaced_signature": cue_signature(captured, plan.removed_ids),
                     "speaker_map": dict(plan.speaker_map),
                     "speaker_identity_policy": "task-scoped-unconfirmed",
                     "speaker_task_id": task}
    apply_plan(captured, plan, history_entry(plan, snapshot.get("requested_range_ms"),
                                             fingerprint=snapshot["fingerprint"]))
    if captured.studio_state.get('last_selected_cue') not in {c.id for c in captured.cues}:
        captured.studio_state.pop('last_selected_cue', None)
    return captured


def matching_recognition_segments(current, previous, old):
    """Match an instance and its split descendants, never just a filename.

    Legacy splits lack ancestry. Recover only unchanged affine pieces inside
    exactly one captured instance; never guess moved or ambiguous pieces.
    """
    known = {s['id'] for s in previous}
    for seg in current.segments:
        if seg.source_path != old['source_path']:
            continue
        if seg.id == old['id'] or old['id'] in current.segment_lineage.get(seg.id, []):
            yield seg
            continue
        if seg.id in known or seg.id in current.segment_lineage:
            continue
        candidates = []
        for origin in previous:
            if origin['source_path'] != seg.source_path:
                continue
            rate = (origin['source_out_ms']-origin['source_in_ms']) / max(1,origin['timeline_out_ms']-origin['timeline_in_ms'])
            if rate <= 0 or not (origin['source_in_ms'] <= seg.source_in_ms < seg.source_out_ms <= origin['source_out_ms']):
                continue
            a = origin['timeline_in_ms']+(seg.source_in_ms-origin['source_in_ms'])/rate
            b = origin['timeline_in_ms']+(seg.source_out_ms-origin['source_in_ms'])/rate
            if abs(a-seg.timeline_in_ms) <= 1 and abs(b-seg.timeline_out_ms) <= 1:
                candidates.append(origin['id'])
        if candidates == [old['id']]:
            yield seg


def project_recognized_cues(project, *, domain):
    """Map snapshot-local cues through the current sequence (including rate).

    Instance IDs take precedence over source ranges, so a repeated source is
    never multiplied merely because it appears twice in the captured edit.
    """
    from ..timeline.studio_edit_sequence import caption_projection_sequence
    info = project.generation_metadata.get("timeline_recognition")
    if not info:
        return None
    current = caption_projection_sequence(project)
    previous = info["sequence"].get("segments", [])
    fields = ("id", "source_path", "source_in_ms", "source_out_ms", "timeline_in_ms", "timeline_out_ms")
    same_mapping = [tuple(getattr(s,k) for k in fields) for s in current.segments] == [
        tuple(s[k] for k in fields) for s in previous]
    if domain == "timeline" and same_mapping:
        # A cue crossing a cut already has valid task time. Splitting it into
        # two copies would repeat the whole text and inflate export counts.
        return sorted(copy.deepcopy(project.cues),key=lambda c:(c.start_ms,c.end_ms,c.id))
    output = []
    owners = {}
    for cue in project.cues:
        # Cues authored in the result project share its captured timeline.
        uncovered = [(cue.start_ms, cue.end_ms)]
        for old in previous:
            a, b = max(cue.start_ms, old["timeline_in_ms"]), min(cue.end_ms, old["timeline_out_ms"])
            if b <= a:
                continue
            uncovered = [(left, right) for x, y in uncovered
                         for left, right in ((x, min(y, a)), (max(x, b), y)) if right > left]
            old_rate = (old["source_out_ms"]-old["source_in_ms"])/max(1,old["timeline_out_ms"]-old["timeline_in_ms"])
            sa = old["source_in_ms"]+(a-old["timeline_in_ms"])*old_rate
            sb = old["source_in_ms"]+(b-old["timeline_in_ms"])*old_rate
            for seg in matching_recognition_segments(current, previous, old):
                left, right = max(sa, seg.source_in_ms), min(sb, seg.source_out_ms)
                if right <= left:
                    continue
                rate = seg.source_duration_ms/max(1, seg.duration_ms)
                item = copy.deepcopy(cue)
                item.id = f"{cue.id}#{seg.id}"
                if domain == "source":
                    item.start_ms, item.end_ms = round(left), round(right)
                else:
                    item.start_ms = round(seg.timeline_in_ms+(left-seg.source_in_ms)/rate)
                    item.end_ms = round(seg.timeline_in_ms+(right-seg.source_in_ms)/rate)
                output.append(item)
                owners[id(item)] = cue.id
        # Preserve every part outside the captured V1 coverage, including the
        # independent tail of a cue crossing a V1 boundary. No ownership can
        # be inferred for these pieces from a primary-video-only snapshot.
        for index, (a, b) in enumerate(uncovered):
            item = copy.deepcopy(cue)
            item.start_ms, item.end_ms = a, b
            item.id = cue.id if (a, b) == (cue.start_ms, cue.end_ms) else f'{cue.id}#gap-{index}'
            output.append(item)
            owners[id(item)] = cue.id
    # A pure cut must not restart a crossing sentence at the cut. Join only
    # contiguous fragments of one canonical cue; never rewrite authored data.
    grouped = {}
    for item in output:
        grouped.setdefault(owners[id(item)], []).append(item)
    joined = []
    originals = {c.id:c for c in project.cues}
    for canonical_id, pieces in grouped.items():
        merged = []
        for item in sorted(pieces, key=lambda c:(c.start_ms,c.end_ms,c.id)):
            if merged and item.start_ms <= merged[-1].end_ms + 1:
                merged[-1].end_ms = max(merged[-1].end_ms, item.end_ms)
            elif not any(p.start_ms == item.start_ms and p.end_ms == item.end_ms for p in merged):
                merged.append(item)
        original = originals[canonical_id]
        if domain == 'timeline' and len(merged) == 1 and (merged[0].start_ms,merged[0].end_ms) == (original.start_ms,original.end_ms):
            merged[0].id = original.id
        joined.extend(merged)
    return sorted(joined, key=lambda c: (c.start_ms, c.end_ms, c.id))
