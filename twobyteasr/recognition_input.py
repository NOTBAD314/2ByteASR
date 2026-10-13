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


def capture_recognition_snapshot(project, project_path=""):
    from .audio_graph import capture_audio_graph
    from .studio_edit_sequence import sequence_of, timeline_duration_ms
    project = copy.deepcopy(project)
    data = project.to_dict()
    graph = capture_audio_graph(project)
    duration = timeline_duration_ms(project)
    if duration <= 0:
        raise ValueError("当前时间轴为空，无法识别字幕。")
    sources = {}
    for layer in graph["segments"]:
        path = Path(layer["source_path"]).resolve()
        stat = path.stat()
        sources[str(path)] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    identity = {"version": 2, "duration_ms": duration, "audio_graph": graph,
                "sequence": sequence_of(project).to_dict(), "sources": sources}
    return {**identity, "fingerprint": _digest(identity), "project": data,
            "project_id": project.project_id, "project_path": str(project_path),
            "project_revision": project_content_revision(data)}


def project_content_revision(data):
    # Conservative late-result guard: studio_state also contains mixer edits.
    return _digest({k: v for k, v in data.items() if k != "updated_at"})


def prepare_recognition_input(snapshot, cache_root, ffmpeg, *, token=None):
    from .audio_export import audio_mix_arguments
    from .processes import popen_hidden_subprocess, stop_process_tree
    from .timeline_media import resolve_audio_layers, TIME_CONTRACT

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
        ('version', 'duration_ms', 'audio_graph', 'sequence', 'sources', 'media_time_contract', 'media_timebases')})
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
    job = SimpleNamespace(start_seconds=0, duration_seconds=duration,
                          video_graph={"duration_ms": snapshot["duration_ms"]})
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
                      rendered_audio_segments=layers, project_range_ms=[0, snapshot['duration_ms']])
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
    from .studio_project import SubtitleProject
    captured = SubtitleProject.from_dict(copy.deepcopy(snapshot["project"]))
    original = captured.to_dict()
    captured.project_id = uuid.uuid4().hex
    captured.studio_state["project_name"] = f"{Path(snapshot.get('project_path') or '时间轴').stem} · 识别结果"
    captured.studio_state["project_name_automatic"] = True
    captured.studio_state["project_name_origin"] = {"kind": "recognition_result", "parent": Path(snapshot.get("project_path") or "").stem}
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
    from .caption_source_receipts import initialize_recognition_receipts
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
    from .studio_edit_sequence import caption_projection_sequence
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
