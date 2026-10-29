"""Headed production exports: VFR, mixed frame rates and failed clock validation."""
from pathlib import Path
import json
import time
import wave


def run(output):
    import av
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from ..projects.project_range import set_range
    from ..timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    from ..timeline.studio_media_pool import sync_primary_video_track_from_sequence
    from ..exports.export_timeline import write_export_ass
    from ..exports.studio_export_ui import StudioExportWorkspace
    from ..exports import studio_render
    from ..system.platform_media import ffmpeg_tool
    from ..system.processes import run_hidden_subprocess
    from ..design.theme_manager import apply_application_theme
    from .blank_project_audit import _capture

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, "grape")
    ffmpeg = Path(ffmpeg_tool())
    studio_render.scan_encoder_capabilities(ffmpeg)
    result = {"scope": "source; private Windows desktop; generated media; real export UI", "cases": []}

    def command(args):
        return run_hidden_subprocess([str(ffmpeg), "-v", "error", "-y", *map(str, args)],
            purpose="export clock acceptance", check=True, capture_output=True, timeout=60)

    sources = {}
    for name, rate in [("vfr", "60"), ("cinema", "24000/1001")]:
        source = output / (name + ".mp4")
        filters = ["select='if(lt(t,4),not(mod(n,2)),1)'"] if name == "vfr" else []
        filters += [
            "drawbox=x=0:y=0:w=30:h=30:color=white:t=fill:enable='between(mod(t,1),0.4,0.52)'",
            "drawbox=x=40:y=0:w=40:h=30:color=0xFF0000:t=fill:enable='gte(t,2)'",
            "drawbox=x=40:y=0:w=40:h=30:color=0x00FF00:t=fill:enable='gte(t,4)'",
            "drawbox=x=40:y=0:w=40:h=30:color=0x0000FF:t=fill:enable='gte(t,6)'"]
        command(["-f", "lavfi", "-i", f"color=c=0x204080:s=320x180:r={rate}:d=8",
            "-f", "lavfi", "-i",
            r"aevalsrc=if(between(mod(t\,1)\,0.4\,0.52)\,0.5*sin(2*PI*800*t)\,0):s=48000:d=8",
            "-vf", ",".join(filters), "-fps_mode:v", "vfr", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "10", "-c:a", "aac", "-b:a", "192k", source])
        sources[name] = source

    def project_for(mixed):
        project = SubtitleProject(media=StudioMedia(str(sources["vfr"]), duration_ms=8000, width=320, height=180),
            cues=[StudioCue(str(i), i*1000+600, i*1000+850, "SYNC") for i in range(8)])
        project.validate()
        project.styles[0].primary_color = "#FF0000"
        project.styles[0].font_size = 120
        segments = [VideoSegment("first", str(sources["vfr"]), 0, 4000, 0, 4000),
                    VideoSegment("second", str(sources["cinema"]), 4000, 8000, 4000, 8000)] if mixed else [
                    VideoSegment("all", str(sources["vfr"]), 0, 8000, 0, 8000)]
        sequence = EditSequence(source_path=str(sources["vfr"]), source_duration_ms=8000, segments=segments)
        store_sequence(project, sequence)
        sync_primary_video_track_from_sequence(project, sequence)
        for asset in project.media_pool:
            asset.video_metadata["fps"] = 45 if asset.canonical_source == str(sources["vfr"]) else 24000/1001
        if mixed:
            project.generation_metadata["timeline_recognition"] = {"sequence": sequence.to_dict()}
        return project

    def inspect(path, start, duration, folder):
        flashes, caption_errors, color_errors = [], [], []
        with av.open(str(path)) as media:
            rate = float(media.streams.video[0].average_rate)
            frames = 0
            for frame in media.decode(video=0):
                frames += 1
                at = float(frame.pts * frame.time_base) + start
                rgb = frame.to_ndarray(format="rgb24")
                if rgb[:20, :20].mean() > 210:
                    flashes.append(at)
                present = np.sum((rgb[50:, :, 0] > 150) & (rgb[50:, :, 1] < 100) &
                                 (rgb[50:, :, 2] < 100)) > 10
                # Compare the authored half-open interval, clipped by the export range.
                wanted = any(max(start, i+.6) <= at < min(start+duration, i+.85) for i in range(8))
                if present != wanted:
                    caption_errors.append(min(abs(at-boundary) for i in range(8)
                                              for boundary in (max(start, i+.6), min(start+duration, i+.85))))
                expected = 0 if at < 2 else 1 if at < 4 else 2 if at < 6 else 3
                pixel = rgb[10:20, 50:60].mean(axis=(0, 1))
                actual = 0 if max(pixel) < 180 else 1+int(np.argmax(pixel))
                if actual != expected:
                    color_errors.append(min(abs(at-boundary) for boundary in (2, 4, 6)))
        command(["-i", path, "-vn", "-ac", "1", "-ar", "48000", folder/"audio.wav"])
        with wave.open(str(folder/"audio.wav"), "rb") as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")/32768
        events = []
        for i in range(8):
            onset = i + .4
            if not start+.1 < onset < start+duration-.2:
                continue
            visible = min(flashes, key=lambda t: abs(t-onset))
            left, right = round((onset-start-.06)*48000), round((onset-start+.15)*48000)
            hits = np.flatnonzero(np.abs(pcm[left:right]) > .12)
            heard = (left+int(hits[0]))/48000+start if len(hits) else None
            events.append(dict(expected=onset, visible=visible, heard=heard))
        # Two independently quantized frame clocks: source (at least 23.976) and export.
        tolerance = 1001/24000 + 1/rate + .003
        detail = dict(fps=rate, frames=frames, audio_duration=len(pcm)/48000, events=events,
                      max_caption_boundary_error=max(caption_errors, default=0),
                      max_color_boundary_error=max(color_errors, default=0), tolerance=tolerance)
        assert max(caption_errors, default=0) <= tolerance, detail
        assert max(color_errors, default=0) <= tolerance, detail
        assert abs(len(pcm)/48000-duration) < .06, detail
        assert len(events) >= 4, detail
        assert all(e["heard"] is not None and abs(e["visible"]-e["expected"]) <= tolerance
                   and abs(e["heard"]-e["expected"]) < .02 for e in events), detail
        return detail

    cases = [("vfr-cpu-source-range", False, 0, "libx264", 2.137, 4.573),
             ("vfr-nvenc-60-full", False, 60, "h264_nvenc", 0, 8),
             ("mixed-cpu-source-range", True, 0, "libx264", 2.137, 4.573),
             ("mixed-nvenc-60-full", True, 60, "h264_nvenc", 0, 8),
             ("broken-mkv-blocked", False, 0, "libx264", 0, 8)]
    for name, mixed, fps, encoder, start, duration in cases:
        folder = output/name
        folder.mkdir()
        project = project_for(mixed)
        set_range(project, round(start*1000), round((start+duration)*1000))
        ass = folder/"captions.ass"
        write_export_ass(project, ass)
        window = StudioExportWorkspace(project, str(ass))
        window.resize(1440, 900)
        window.show()
        QTest.qWait(100)  # Let the normal deferred preference restore finish first.
        deadline = time.monotonic()+15
        while window.encoder.findData(encoder) < 0 and time.monotonic() < deadline:
            QTest.qWait(50)
        assert window.encoder.findData(encoder) >= 0, encoder
        window.directory.setText(str(folder))
        window.filename.setText("result")
        window.filename_prefix.setText("")
        window.filename_suffix.setText("")
        window.extension.setCurrentIndex(window.extension.findData("mkv" if name.startswith("broken") else "mp4"))
        window.encoder.setCurrentIndex(window.encoder.findData(encoder))
        window.encoder_preset.setCurrentIndex(window.encoder_preset.findData("fastest"))
        window.resolution.setCurrentIndex(window.resolution.findData((0, 0)))
        window.fps.setCurrentIndex(window.fps.findData(float(fps)))
        QTest.qWait(150)
        _capture(window, folder/"setup.png")
        old_command = studio_render.build_render_command
        broken = name.startswith("broken")
        try:
            if broken:
                bad = folder/"bad-encoder.mkv"
                command(["-i", sources["vfr"], "-vf", "setpts=PTS/2", "-fps_mode:v", "passthrough",
                         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", bad])
                def bad_encoder(executable, job):
                    return [str(executable), "-v", "error", "-y", "-i", str(bad),
                            "-map", "0", "-c", "copy", "-progress", "pipe:1", job.output_path]
                studio_render.build_render_command = bad_encoder
            window._start()
            deadline = time.monotonic()+90
            while window._running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)  # Yield the GIL to the real export worker and pipe readers.
                if not (folder/"processing.png").exists() and not window.render_preview.pixmap().isNull():
                    _capture(window, folder/"processing.png")
            assert not window._running, "export timed out"
            QTest.qWait(200)
            _capture(window, folder/"finished.png")
            job = window._last_job
            assert job.settings.encoder == encoder, (name, job.settings)
            assert job.settings.fps == fps, (name, job.settings)
            assert Path(job.output_path).suffix == ('.mkv' if broken else '.mp4')
            item = dict(name=name, start=start, duration=duration, requested_encoder=encoder,
                        settings_encoder=job.settings.encoder, passed=False)
            if broken:
                assert "视频实际时间轴" in window._last_failure, window._last_failure
                assert not Path(job.output_path).exists()
                assert "output_path" not in job.completion_metadata
                item.update(passed=True, error=window._last_failure.split("\n")[0])
            else:
                assert Path(job.output_path).is_file(), getattr(window, "_last_failure", "output missing")
                item.update(inspect(Path(job.output_path), start, duration, folder), passed=True)
                item["diagnostics_path"] = job.completion_metadata.get("diagnostics_path")
            result["cases"].append(item)
            (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
        finally:
            studio_render.build_render_command = old_command
            window.close()
            QTest.qWait(50)
    result["passed"] = all(case["passed"] for case in result["cases"])
    (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    return 0
