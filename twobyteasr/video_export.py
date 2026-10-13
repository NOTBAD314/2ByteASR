"""Deterministic media-graph raster pass shared by native/Advanced exports.

Uses the preview's QPainter geometry, RGB key and blend operators at export
resolution. A lossless, range-local intermediate feeds the existing subtitle
and encoder routes. Memory is bounded by active clips, never by video length.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from fractions import Fraction
import json
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .processes import popen_hidden_subprocess
from .export_media import SequentialExportDecoder, probe_media, identity_video_graph
from .clip_time_mapper import project_to_source_exact
from .video_compositor import apply_chroma_key, layer_geometry, _BLEND_COMPOSITION_MODES


def capture_video_graph(project) -> dict:
    from .audio_export import capture_audio_mix
    from .studio_media_pool import validate_media_graph
    from .studio_edit_sequence import timeline_duration_ms
    validate_media_graph(project)
    return dict(media_pool=[asdict(x) for x in project.media_pool],
                audio_mix=capture_audio_mix(project),
                clip_transitions=__import__("copy").deepcopy(project.studio_state.get("clip_transitions", [])),
                video_tracks=[asdict(x) for x in project.video_tracks],
                audio_tracks=[asdict(x) for x in project.audio_tracks],
                width=project.media.width or 1920, height=project.media.height or 1080,
                fps=next((float((a.video_metadata or {}).get("fps") or 0.) for a in project.media_pool
                          if a.canonical_source == project.media.path), 0.),
                duration_ms=timeline_duration_ms(project))


def requires_video_composition(graph: dict) -> bool:
    # Even a single V1 may be hidden, transformed, keyed or use another asset.
    return bool(graph.get("video_tracks"))


def paint_layer(painter: QPainter, width: int, height: int, image: QImage, clip: dict) -> None:
    effects = clip.get("effects") or {}
    chroma = effects.get("chromaKey") or {}
    if chroma.get("enabled"):
        image = apply_chroma_key(image, chroma)
    transform = clip.get("transform") or {}
    local, matrix = layer_geometry(width, height, clip, image.width(), image.height())
    painter.save()
    painter.setOpacity(max(0., min(1., float(transform.get("opacity", 1.)))))
    painter.setCompositionMode(_BLEND_COMPOSITION_MODES.get(effects.get("blendMode", "normal"),
                                                           QPainter.CompositionMode.CompositionMode_SourceOver))
    painter.setTransform(matrix)
    painter.drawImage(local, image)
    painter.restore()


def _audio_arguments(ffmpeg, job) -> list[str]:
    from .studio_render import media_has_audio
    if job.settings.audio_codec == "none":
        return ["-an"]
    if job.video_graph.get("audio_mix") is not None:
        from .audio_export import audio_mix_arguments
        return audio_mix_arguments(ffmpeg, job, job.video_graph["audio_mix"])
    if job.settings.audio_codec == "none" or not media_has_audio(ffmpeg, job.media_path):
        return ["-an"]
    # The raster output is frame-bounded, while source audio keeps the
    # requested time range. Do not extend or stretch it to the video frame end.
    requested_duration = float(job.duration_seconds or max(.001,
        job.video_graph["duration_ms"] / 1000 - float(job.start_seconds or 0.)))
    slices = job.edit_segments
    if slices:
        graph = []
        labels = []
        for i, (a, b) in enumerate(slices):
            graph.append(f"[1:a]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
        graph.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[joined]")
        graph.append(f"[joined]atrim=duration={requested_duration:.6f}[audio]")
        return ["-i", job.media_path, "-filter_complex", ";".join(graph), "-map", "[audio]", "-c:a", "pcm_s16le"]
    return ["-ss", f"{job.start_seconds or 0.:.6f}", "-t", f"{requested_duration:.6f}",
            "-i", job.media_path, "-map", "1:a:0", "-c:a", "pcm_s16le"]


def _video_frame_clock(ffmpeg: Path, job):
    """One output sampling clock for preflight and the actual raster pass."""
    graph = job.video_graph
    fps = float(job.settings.fps or graph.get("fps") or 0.)
    if fps <= 0:
        from .processes import run_hidden_subprocess
        probe = run_hidden_subprocess([str(ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix == ".exe" else "ffprobe")),
                                       "-v", "error", "-select_streams", "v:0", "-show_entries",
                                       "stream=avg_frame_rate", "-of", "json", job.media_path],
                                      purpose="export frame rate", capture_output=True, timeout=10, check=True)
        value = json.loads(probe.stdout)["streams"][0]["avg_frame_rate"]
        fps = float(Fraction(value)) if value != "0/0" else 30.
    start = float(job.start_seconds or 0.)
    duration = float(job.duration_seconds or max(.001, graph["duration_ms"] / 1000 - start))
    frame_count = max(1, math.ceil(duration * fps - 1e-8))
    return fps, start, duration, frame_count


def compose_video(ffmpeg: Path, job, output: Path, *, cancelled=None, progress=None, indexes=None) -> dict:
    from .studio_render import export_progress, STAGE_COMPOSE_VIDEO
    graph = job.video_graph
    width = int(job.settings.width or graph["width"])
    height = int(job.settings.height or graph["height"])
    fps, start, duration, frame_count = _video_frame_clock(ffmpeg, job)
    assets = {x["asset_id"]: x for x in graph["media_pool"]}
    clips = [dict(c,track_id=t["id"]) for t in sorted(graph["video_tracks"], key=lambda t: (t.get("z_index", 0), t["id"]))
             if t.get("enabled", True) for c in t.get("clips", []) if c.get("enabled", True)
             and (assets[c["asset_id"]].get("video_metadata") or {}).get("has_video") is not False]
    from .studio_transitions import transition_windows, transition_gain
    windows = transition_windows(graph, "video")
    clips = [dict(c, **{k:v for k,v in windows.get((c["track_id"],c["id"]),windows.get(c["id"], {})).items() if k != "id"}) for c in clips]
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
               "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}",
               "-r", f"{fps:.9f}", "-i", "pipe:0", *_audio_arguments(ffmpeg, job),
               "-map", "0:v:0", "-c:v", "ffv1", "-level", "3", "-threads", "2",
               "-frames:v", str(frame_count), str(output)]
    decoders = {}
    if indexes is None:
        indexes = {str(Path(a['canonical_source']).resolve()): probe_media(ffmpeg,a['canonical_source'],cancelled=cancelled) for a in graph['media_pool'] if a.get('video_metadata',{}).get('has_video',True)}
    job_id = uuid.uuid4().hex
    output_duration = float(Fraction(frame_count) / Fraction(str(fps)))
    frame_clock = dict(fps=fps, frame_count=frame_count,
        requested_start_seconds=start, requested_duration_seconds=duration,
        duration_seconds=output_duration,
        frame_range=[0, frame_count],
        first_sample_pts=str(Fraction(str(start))),
        last_sample_pts=str(Fraction(str(start)) + Fraction(frame_count - 1) / Fraction(str(fps))),
        output_end_pts=str(Fraction(frame_count) / Fraction(str(fps))),
        audio_range_policy="original requested range; no stretch or extension")
    clock_file = Path(job.output_path).with_suffix('.composition-frame-clock.json')
    clock_file.write_text(json.dumps(dict(frame_clock, status='planned', written_frames=0),
        ensure_ascii=False, indent=2), encoding='utf8')
    receipt_file = Path(job.output_path).with_suffix('.decode-requests.jsonl')
    receipts = receipt_file.open('w',encoding='utf-8')
    errors = output.with_suffix(".stderr")
    done = threading.Event()
    heartbeat = [time.monotonic()]
    preview_at = 0.
    with errors.open("wb") as stderr:
        process = popen_hidden_subprocess(command, purpose="Studio media graph raster export",
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr)
        def monitor():
            while not done.wait(.1):
                if (cancelled and cancelled()) or time.monotonic() - heartbeat[0] > 60:
                    if process.poll() is None:
                        process.kill()
                    return
        watcher = threading.Thread(target=monitor, daemon=True, name="studio-compose-watchdog")
        watcher.start()
        try:
            for index in range(frame_count):
                if cancelled and cancelled():
                    raise InterruptedError("render cancelled")
                timeline_seconds = Fraction(str(start)) + Fraction(index) / Fraction(str(fps))
                timeline_ms = timeline_seconds * 1000
                active = [c for c in clips if c["timeline_in_ms"] <= timeline_ms < c["timeline_out_ms"]]
                active_ids = {c["id"] for c in active}
                for key in list(decoders):
                    if key not in active_ids:
                        decoders.pop(key).close()
                image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.black)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                try:
                    for clip in active:
                        rate = float(clip.get("playback_rate") or 1.)
                        source_seconds = project_to_source_exact(clip, timeline_seconds)
                        path = str(Path(assets[clip['asset_id']]['canonical_source']).resolve())
                        decoder = decoders.get(clip["id"])
                        if decoder is None:
                            decoder = SequentialExportDecoder(indexes[path], cancelled=cancelled)
                            decoders[clip["id"]] = decoder
                        (fw,fh,pixels), receipt = decoder.read(source_seconds,context=dict(export_job_id=job_id,
                            clip_id=clip['id'],timeline_frame_index=index,timeline_pts=str(timeline_seconds),
                            clip_local_pts=str(timeline_seconds-Fraction(clip['timeline_in_ms'],1000)),
                            clip_in=clip['source_in_ms'],clip_out=clip['source_out_ms']))
                        receipts.write(json.dumps(receipt)+'\n')
                        layer = QImage(pixels, fw, fh, fw * 4,
                                       QImage.Format.Format_ARGB32)
                        sampled = dict(clip, transform=dict(clip.get("transform") or {}))
                        sampled["transform"]["opacity"] = float(sampled["transform"].get("opacity",1.)) * transition_gain(clip.get("envelopes",[]),timeline_ms)
                        paint_layer(painter, width, height, layer, sampled)
                finally:
                    painter.end()
                process.stdin.write(image.constBits())
                heartbeat[0] = time.monotonic()
                if job.preview_callback and heartbeat[0] - preview_at >= .5:
                    preview_at = heartbeat[0]
                    job.preview_callback(image.scaled(640, 360, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation), float(timeline_ms), '视频轨合成 · 字幕尚未烧录')
                if progress and (index % max(1, round(fps)) == 0 or index == frame_count - 1):
                    progress(export_progress(STAGE_COMPOSE_VIDEO,
                              message=f"合成视频轨 {index + 1}/{frame_count} 帧", percent=100 * (index + 1) / frame_count,
                              frame=str(index+1), total_frames=frame_count, out_time_us=round(float(timeline_seconds-start)*1000000)))
            process.stdin.close()
            returncode = process.wait(timeout=60)
            if returncode:
                raise RuntimeError(f"视频轨合成失败 ({returncode})")
            clock_file.write_text(json.dumps(dict(frame_clock, status='raster_encoded',
                written_frames=frame_count, encoder_exit_code=returncode),
                ensure_ascii=False, indent=2), encoding='utf8')
        except BaseException as exc:
            if cancelled and cancelled():
                raise InterruptedError("render cancelled") from exc
            details = dict(getattr(exc, 'receipt', {}), export_job_id=job_id,
                timeline_frame_index=locals().get('index'), stderr_tail=errors.read_text(encoding='utf8',errors='replace')[-3000:],
                encoder_exit_code=process.poll(), log_path=str(receipt_file))
            receipts.write(json.dumps(dict(error=details),ensure_ascii=False)+'\n')
            Path(job.output_path).with_suffix('.diagnostic.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf8')
            raise
        finally:
            done.set()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            if process.stdin:
                process.stdin.close()
            watcher.join(timeout=1)
            for decoder in decoders.values():
                decoder.close()
            receipts.close()
    return frame_clock


def composed_video_frame_count(job):
    """Exact video cap for a resolved raster, never for original-media exports."""
    if not job.composition_resolved:
        return None
    clock = (job.export_context or {}).get("composed_video_frame_clock")
    if not clock:
        return None  # Older internal queue entries have no raster clock receipt.
    count = clock.get("frame_count")
    if (isinstance(count, bool) or not isinstance(count, int) or count <= 0
            or abs(float(job.duration_seconds) * float(job.settings.fps) - count) > 1e-6):
        raise ValueError("Resolved composition frame count does not match its output clock")
    return count


@contextmanager
def prepared_video_job(ffmpeg, job, *, cancelled=None, progress=None):
    if not job.video_graph or not requires_video_composition(job.video_graph):
        yield replace(job, video_graph=None)
        return
    from .timeline_media import resolve_video_graph
    job = replace(job, video_graph=resolve_video_graph(job.video_graph, ffmpeg, cancelled=cancelled))
    parent = Path(job.output_path).resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        indexes = preflight_video_job(ffmpeg,job,cancelled=cancelled,progress=progress)
    except Exception as exc:
        if isinstance(exc, InterruptedError):raise
        diagnostic=Path(job.output_path).with_suffix('.diagnostic.json')
        diagnostic.write_text(json.dumps(dict(getattr(exc,'receipt',{}),stage='media_preflight',detail=str(exc)),ensure_ascii=False,indent=2),encoding='utf8')
        raise RuntimeError(f'{exc}\n诊断日志：{diagnostic}') from exc
    if (not job.video_graph.get("clip_transitions") and identity_video_graph(job.video_graph,job.media_path)
            and str(Path(job.media_path).resolve()) in indexes):
        index = indexes[str(Path(job.media_path).resolve())]
        yield replace(job,video_graph=None,edit_segments=(),settings=replace(job.settings,fps=job.settings.fps or float(index.fps)))
        return
    with tempfile.TemporaryDirectory(prefix=".video-composition-", dir=parent) as folder:
        output = Path(folder) / "video.mkv"
        composed = compose_video(Path(ffmpeg), job, output, cancelled=cancelled, progress=progress,indexes=indexes)
        # Original ASS/Advanced timestamps remain in project time; media now
        # starts at the range origin and must not be input-seeked a second time.
        audio = job.settings.audio_codec
        settings = replace(job.settings, fps=composed["fps"],
                           audio_codec=("opus" if job.settings.container == "webm" else "aac") if audio == "copy" else audio)
        yield replace(job, media_path=str(output), settings=settings, edit_segments=(),
                      video_graph=None, composition_resolved=True, duration_seconds=composed["duration_seconds"],
                      export_context=dict(job.export_context or {}, composed_video_frame_clock=composed))


def preflight_video_job(ffmpeg, job, *, cancelled=None, progress=None):
    from .studio_render import export_progress, STAGE_PREPARE_PROJECT
    if progress: progress(export_progress(STAGE_PREPARE_PROJECT,message='检查媒体实际首尾 PTS 与完整可解码性…'))
    graph=job.video_graph;assets={a['asset_id']:a for a in graph['media_pool']};indexes={};receipts=[]
    fps, start, duration, frame_count = _video_frame_clock(Path(ffmpeg), job)
    origin, rate = Fraction(str(start)), Fraction(str(fps))
    from .studio_transitions import transition_windows
    windows=transition_windows(graph,'video')
    for track in graph['video_tracks']:
        if not track.get('enabled',True):continue
        for clip in track.get('clips',[]):
            if not clip.get('enabled',True):continue
            clip=dict(clip,track_id=track['id'])
            clip=dict(clip,**{k:v for k,v in windows.get((track['id'],clip['id']),windows.get(clip['id'],{})).items() if k!='id'})
            asset=assets[clip['asset_id']]
            if asset.get('video_metadata',{}).get('has_video') is False:continue
            # The clip and export are half-open intervals on the exact output
            # frame grid. Neither exclusive out nor a clip outside this range
            # is an actual decoder request for this job.
            first=max(0,math.ceil((Fraction(clip['timeline_in_ms'],1000)-origin)*rate))
            last=min(frame_count-1,math.ceil((Fraction(clip['timeline_out_ms'],1000)-origin)*rate)-1)
            if first>last:
                receipts.append(dict(clip_id=clip['id'],status='not_sampled',
                    reason='no active output frame in requested range',export_start_seconds=start,
                    export_duration_seconds=duration,export_fps=fps,export_frame_count=frame_count))
                continue
            path=str(Path(asset['canonical_source']).resolve())
            try:
                if path not in indexes:indexes[path]=probe_media(ffmpeg,path,cancelled=cancelled)
                media=indexes[path]
            except Exception as exc:
                if isinstance(exc,InterruptedError):raise
                from .export_media import ExportMediaError
                raise ExportMediaError('MEDIA_PREFLIGHT',dict(clip_id=clip['id'],path=path),exc) from exc
            # Positive affine clip mapping is bounded by actual first/last
            # samples. Check representative interior/tail frames as well.
            samples=sorted({first,(first+last)//2,max(first,last-2),max(first,last-1),last})
            for index in samples:
                timeline=origin+Fraction(index)/rate
                value=project_to_source_exact(clip,timeline)
                if value is None:raise RuntimeError('Preflight/raster active-frame disagreement')
                try: target=media.target(value)
                except ValueError as exc:
                    from .export_media import ExportMediaError
                    raise ExportMediaError('CLIP_MAPPING',dict(clip_id=clip['id'],timeline_frame_index=index,
                        timeline_pts=str(timeline),source_ms=float(value)*1000),exc) from exc
                receipts.append(dict(clip_id=clip['id'],source_pts=str(value),resolved_pts=str(target),
                    timeline_frame_index=index,timeline_pts=str(timeline),boundary_clamped=target!=value,
                    boundary_policy='existing MediaIndex.target: at most one source-frame interval; no duration/AV-tail extension',
                    decoded_last_seconds=str(media.last),source_frame_interval=str(media.interval),
                    clip_first_output_frame=first,clip_last_output_frame=last,
                    export_start_seconds=start,export_duration_seconds=duration,export_fps=fps,export_frame_count=frame_count,
                    time_base=str(media.time_base),last_pts=media.pts[-1],frame_count=len(media.pts),probe_seconds=media.elapsed))
    destination=Path(job.output_path).with_suffix('.preflight.json')
    destination.write_text(json.dumps(receipts,indent=2),encoding='utf-8')
    return indexes
