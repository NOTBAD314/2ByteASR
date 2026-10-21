"""Audio of one caption, resolved the way export and recognition hear it.

2026-10-10 (proofread workspace, user report "按播放听到完全无关的音频"):
the proofreading page used to seek ``project.media.path`` with the caption's
*timeline* milliseconds. Edited projects place timeline 0 deep inside a source
(and later clips in other files), so every preview played unrelated speech.

A preview here is never computed with a private conversion. The caption's
stable id is looked up in the live project, its range is expressed in the
project timeline, and the clipped audio graph is compiled by the same
``compile_audio_mix`` that renders the recognition input and exports (which
also binds FLV sources to their continuous content clock). Each request
leaves a diagnostic row with the cue, clips, sources and the final range.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

PRE_ROLL_MS = 250
POST_ROLL_MS = 350
SAMPLE_RATE = 48000
CHANNELS = 2


class PreviewUnavailable(RuntimeError):
    """The caption's audio cannot be resolved; never play something else."""


@dataclass
class CuePreviewPlan:
    request_id: str
    project_id: str
    project_revision: str
    cue_id: str
    cue_text: str
    cue_domain: str
    cue_range_ms: tuple[int, int]
    play_range_ms: tuple[int, int]
    layers: list = field(default_factory=list)
    clock: str = "timeline"

    def diagnostic(self):
        a, b = self.play_range_ms

        def played(layer):
            # The part of this clip the preview actually decodes.
            lo, hi = max(a, layer["timeline_in_ms"]), min(b, layer["timeline_out_ms"])
            rate = float(layer.get("playback_rate", 1.0) or 1.0)
            offset = layer["source_in_ms"] - layer["timeline_in_ms"] * rate
            return {"played_timeline_ms": [lo, hi],
                    "played_source_ms": [round(offset + lo * rate), round(offset + hi * rate)]}

        return {"request_id": self.request_id, "project_id": self.project_id,
                "project_revision": self.project_revision, "cue_id": self.cue_id,
                "cue_text": self.cue_text, "cue_domain": self.cue_domain, "clock": self.clock,
                "cue_range_ms": list(self.cue_range_ms), "play_range_ms": list(self.play_range_ms),
                "layers": [{key: layer.get(key) for key in (
                    "clip_id", "audio_clip_id", "asset_id", "track_id", "source_path", "original_source_path",
                    "media_time_contract", "timeline_in_ms", "timeline_out_ms", "source_in_ms",
                    "source_out_ms", "playback_rate", "stream_index", "gain_db")} | played(layer)
                           for layer in self.layers]}


def _revision(project, cue):
    payload = {"cue": [cue.id, int(cue.start_ms), int(cue.end_ms), cue.text, cue.speaker_id],
               "domain": (project.render_settings or {}).get("_cue_domain"),
               "tracks": [[c.id, c.asset_id, c.timeline_in_ms, c.timeline_out_ms, c.source_in_ms, c.source_out_ms,
                           float(getattr(c, "playback_rate", 1.0))]
                          for track in (*project.video_tracks, *project.audio_tracks) for c in track.clips],
               "updated_at": str(getattr(project, "updated_at", ""))}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def caption_timeline_range(project, cue_id):
    """(cue, (start, end), domain) of a stable caption id in project time.

    Timeline-domain projects store captions in project time. Legacy projects
    store source time of the primary media; their visible timeline position
    comes from the same projection Studio's list and export use."""
    cue_id = str(cue_id)
    cue = next((c for c in project.cues if c.id == cue_id), None)
    if cue is None:
        raise PreviewUnavailable("这条字幕已不在当前工程里（可能已被删除或重新断句），请刷新列表")
    domain = (project.render_settings or {}).get("_cue_domain") or "source"
    if domain == "timeline":
        return cue, (int(cue.start_ms), int(cue.end_ms)), "timeline"
    from ..timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    pieces = [item for item in projected_cues(project, domain="timeline")
              if item.id == cue_id or source_cue_id_of(item.id) == cue_id]
    if pieces:
        return cue, (min(p.start_ms for p in pieces), max(p.end_ms for p in pieces)), "timeline_projection"
    return cue, (int(cue.start_ms), int(cue.end_ms)), "source"


def plan_cue_preview(project, cue_id, *, pre_roll_ms=PRE_ROLL_MS, post_roll_ms=POST_ROLL_MS):
    """Resolve which clips/sources play for this caption (no decoding)."""
    from .audio_graph import capture_audio_graph
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    cue, (start, end), domain = caption_timeline_range(project, cue_id)
    if end <= start:
        raise PreviewUnavailable("这条字幕没有有效的时间范围")
    request = uuid.uuid4().hex[:12]
    revision = _revision(project, cue)
    if domain == "source":
        # A legacy caption outside the current edit: its own times address the
        # primary media's content clock directly (the clock it was recognized on).
        source = str(getattr(project.media, "path", "") or "")
        if not source:
            raise PreviewUnavailable("工程没有关联素材文件，无法试听")
        a, b = max(0, start - pre_roll_ms), end + post_roll_ms
        layer = dict(clip_id="", audio_clip_id="", asset_id="", track_id="source", source_path=source,
                     timeline_in_ms=a, timeline_out_ms=b, source_in_ms=a, source_out_ms=b,
                     playback_rate=1.0, gain_db=0.0, stream_index=0, audio_envelopes=[])
        return CuePreviewPlan(request, str(project.project_id), revision, cue.id, cue.text, domain,
                              (start, end), (a, b), [layer], clock="source")
    total = max(int(timeline_duration_ms(project)), end)
    a, b = max(0, start - pre_roll_ms), min(total, end + post_roll_ms)
    layers = []
    for layer in capture_audio_graph(project)["segments"]:
        if layer["timeline_out_ms"] <= a or layer["timeline_in_ms"] >= b:
            continue
        layers.append(copy.deepcopy(layer))
    if not any(layer["timeline_out_ms"] > start and layer["timeline_in_ms"] < end for layer in layers):
        raise PreviewUnavailable("这条字幕所在位置没有可播放的声音（片段被禁用、静音，或素材离线）")
    for layer in layers:
        if not Path(layer["source_path"]).is_file():
            raise PreviewUnavailable(f"找不到素材文件：{layer['source_path']}")
    return CuePreviewPlan(request, str(project.project_id), revision, cue.id, cue.text, domain,
                          (start, end), (a, b), layers)


def preview_command(plan, ffmpeg, *, cancelled=None):
    """ffmpeg arguments producing s16le stereo 48 kHz PCM of the plan range.

    Resolves each source's content clock first (FLV timestamp holes), then
    compiles with the export/recognition mixer at the plan's start."""
    from ..exports.audio_export import compile_audio_mix
    from ..exports.timeline_media import resolve_audio_layers
    layers, receipts = resolve_audio_layers(plan.layers, ffmpeg, cancelled=cancelled)
    plan.layers = layers
    a, b = plan.play_range_ms
    duration = (b - a) / 1000
    job = SimpleNamespace(start_seconds=a / 1000, duration_seconds=duration, video_graph={"duration_ms": b})
    inputs, filters, label = compile_audio_mix(str(ffmpeg), job, layers)
    if not label:
        raise PreviewUnavailable("这段素材没有可用的音轨")
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo:d={duration:.6f}",
            *inputs, "-filter_complex_threads", "1", "-filter_complex", ";".join(filters), "-map", label,
            "-t", f"{duration:.6f}", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"], receipts


def record_preview(row):
    """Append one diagnostic row; never raises."""
    try:
        from ..runtime_paths import user_data_root
        path = user_data_root() / "logs" / "proofread-preview.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
