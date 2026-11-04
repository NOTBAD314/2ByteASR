from __future__ import annotations

import os
import json
import ast
import inspect
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.media.media_ingest import (
    MediaIngestResult,
    discover_same_stem_xml,
    ingest_media,
    result_matches_request,
)
from twobyteasr.system.processes import hidden_subprocess_kwargs, run_hidden_subprocess
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.studio.studio_video_track import VideoThumbnailCache


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_hidden_runner_applies_real_windows_launch_contract(monkeypatch):
    captured = {}

    class Completed:
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return Completed()

    completed = run_hidden_subprocess(
        ["ffprobe.exe", "-version"],
        purpose="ffprobe ingest",
        capture_output=True,
        runner=fake_run,
    )

    assert completed.returncode == 0
    assert captured["command"] == ["ffprobe.exe", "-version"]
    expected = hidden_subprocess_kwargs()
    assert set(expected) <= set(captured["kwargs"])
    if os.name == "nt":
        assert captured["kwargs"]["creationflags"]
        assert captured["kwargs"]["startupinfo"].dwFlags


def test_child_process_instrumentation_records_hidden_duration(monkeypatch, tmp_path):
    log = tmp_path / "children.jsonl"
    monkeypatch.setenv("TWOBYTEASR_CHILD_PROCESS_LOG", str(log))

    class Completed:
        returncode = 0

    run_hidden_subprocess(
        ["ffmpeg.exe", "-version"],
        purpose="ffmpeg contract test",
        runner=lambda *_args, **_kwargs: Completed(),
    )

    import time
    deadline=time.monotonic()+2
    while (not log.exists() or not log.stat().st_size) and time.monotonic()<deadline:time.sleep(.01)
    payload = json.loads(log.read_text(encoding="utf-8").strip())
    assert payload["binary"] == "ffmpeg.exe"
    assert payload["purpose"] == "ffmpeg contract test"
    assert payload["hidden"] is True
    assert payload["duration_ms"] >= 0
    assert payload["returncode"] == 0


def test_studio_runtime_has_no_direct_subprocess_launch_calls():
    from twobyteasr.rendering import advanced_preview, advanced_renderer
    from twobyteasr.studio import studio_helpers, studio_reasr, studio_video_track
    from twobyteasr.playback import studio_mpv, waveform_cache
    from twobyteasr.projects import studio_project_controller
    from twobyteasr.exports import studio_render

    offenders = []
    for module in (
        advanced_preview,
        advanced_renderer,
        studio_helpers,
        studio_mpv,
        studio_project_controller,
        studio_reasr,
        studio_render,
        studio_video_track,
        waveform_cache,
    ):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.func.attr in {"run", "Popen"}
            ):
                offenders.append((module.__name__, node.lineno, node.func.attr))
    assert offenders == []


def test_p74c_probe_duration_uses_stream_when_format_is_missing():
    from twobyteasr.media.media_service import probe_duration_ms

    assert probe_duration_ms({"duration": "12.5"}, []) == 12500
    assert probe_duration_ms({}, [
        {"codec_type": "video", "duration": "175.617"},
        {"codec_type": "audio", "duration": "175.6"},
    ]) == 175617
    assert probe_duration_ms({}, [
        {"codec_type": "video", "duration_ts": "2703360", "time_base": "1/15360"},
    ]) == 176000


def test_ingest_result_contains_probe_stat_and_unique_xml(tmp_path):
    media = tmp_path / "Session 01.flv"
    media.write_bytes(b"media")
    xml = tmp_path / "Session 01.xml"
    xml.write_text("<i/>", encoding="utf-8")

    result = ingest_media(
        media,
        generation=7,
        project_token="project-a",
        probe=lambda _path: {
            "duration_ms": 12_345,
            "fingerprint": "abc",
            "width": 1920,
            "height": 1080,
            "fps": 60.0,
            "has_video": True,
            "has_audio": True,
        },
    )

    assert result.source_path == str(media.resolve())
    assert result.generation == 7
    assert result.project_token == "project-a"
    assert result.duration_ms == 12_345
    assert result.width == 1920 and result.height == 1080
    assert result.fps == 60.0
    assert result.has_video is True and result.has_audio is True
    assert result.size == media.stat().st_size
    assert result.mtime_ns == media.stat().st_mtime_ns
    assert result.xml_candidates == (str(xml.resolve()),)
    assert result.auto_xml_path == str(xml.resolve())
    assert result.error == ""


def test_same_stem_xml_ambiguity_never_auto_binds(tmp_path):
    media = tmp_path / "live recording.mp4"
    media.write_bytes(b"media")
    exact = tmp_path / "live recording.xml"
    normalized = tmp_path / "live-recording.xml"
    exact.write_text("<i/>", encoding="utf-8")
    normalized.write_text("<i/>", encoding="utf-8")

    candidates, automatic = discover_same_stem_xml(media)

    assert set(candidates) == {str(exact.resolve()), str(normalized.resolve())}
    assert automatic == ""


def test_stale_ingest_result_does_not_match_new_project_or_source(tmp_path):
    first = tmp_path / "first.flv"
    second = tmp_path / "second.flv"
    result = MediaIngestResult(
        generation=2,
        project_token="project-a",
        source_path=str(first.resolve()),
    )

    assert result_matches_request(result, 2, "project-a", first)
    assert not result_matches_request(result, 3, "project-a", first)
    assert not result_matches_request(result, 2, "project-b", first)
    assert not result_matches_request(result, 2, "project-a", second)


def test_page_ignores_stale_ingest_result(tmp_path):
    app = _app()
    old_media = tmp_path / "old.flv"
    old_media.write_bytes(b"old")
    page = SubtitleStudioPage()
    page.project = SubtitleProject(media=StudioMedia(path=""))
    page._media_ingest_generation = 9
    page._media_ingest_project_token = page.project.project_id
    page._pending_media_path = str(tmp_path / "new.flv")
    stale = MediaIngestResult(
        generation=8,
        project_token=page.project.project_id,
        source_path=str(old_media.resolve()),
        duration_ms=90_000,
        fingerprint="stale",
    )

    page._media_ingest_ready(stale)

    assert page.project.media.path == ""
    assert page.project.media.duration_ms == 0
    assert page.project.media.fingerprint == ""
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_page_accepts_ingest_then_schedules_waveform(monkeypatch, tmp_path):
    app = _app()
    media = tmp_path / "ready.flv"
    media.write_bytes(b"media")
    page = SubtitleStudioPage()
    page.project = SubtitleProject(media=StudioMedia(path=""))
    page.project_path = tmp_path / "ready.2byteproj"
    page._media_ingest_generation = 4
    page._media_ingest_project_token = page.project.project_id
    page._pending_media_path = str(media.resolve())
    loaded = []
    waveform = []
    monkeypatch.setattr(page.video, "load", lambda path, subtitle="", start_seconds=None: loaded.append((path, subtitle)))
    monkeypatch.setattr(page, "_generate_waveform", lambda path: waveform.append(path))
    result = MediaIngestResult(
        generation=4,
        project_token=page.project.project_id,
        source_path=str(media.resolve()),
        duration_ms=5_000,
        width=1280,
        height=720,
        has_video=True,
        has_audio=True,
        size=media.stat().st_size,
        mtime_ns=media.stat().st_mtime_ns,
        fingerprint="ready",
    )

    page._media_ingest_ready(result)
    app.processEvents()

    assert page.project.media.path == str(media.resolve())
    assert page.project.media.duration_ms == 5_000
    assert loaded == [(str(media.resolve()), "")]
    assert waveform == [str(media.resolve())]
    assert page._media_ingest_state == "READY"

    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_begin_ingest_returns_in_loading_state_before_worker(monkeypatch, tmp_path):
    _app()
    media = tmp_path / "slow.flv"
    media.write_bytes(b"media")
    page = SubtitleStudioPage()
    page.project = SubtitleProject(media=StudioMedia(path=""))
    scheduled = []
    monkeypatch.setattr(
        "twobyteasr.studio.studio_ui.QTimer.singleShot",
        lambda delay, *callbacks: scheduled.append((delay, callbacks[-1])),
    )

    page._begin_media_ingest(media)

    assert page._media_ingest_state == "LOADING"
    assert page.project.media.path == ""
    assert page.video_empty_label.text().startswith("正在载入媒体")
    assert len(scheduled) == 1 and scheduled[0][0] == 0
    assert page._media_ingest_thread is None
    page.close_page()
    page.deleteLater()


def test_thumbnail_pending_key_is_deduplicated(monkeypatch, tmp_path):
    started = []

    class FakeThread:
        def __init__(self, *, target, args, **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            started.append(self.args)

    monkeypatch.setattr("twobyteasr.studio.studio_video_track.threading.Thread", FakeThread)
    monkeypatch.setattr(
        VideoThumbnailCache,
        "_disk_path",
        staticmethod(lambda key: tmp_path / f"{key}.jpg"),
    )
    cache = VideoThumbnailCache()

    cache.request("C:/media/live.flv", 12_345, 96)
    cache.request("C:/media/live.flv", 12_345, 96)

    assert len(started) == 1
    assert len(cache._pending) == 1
