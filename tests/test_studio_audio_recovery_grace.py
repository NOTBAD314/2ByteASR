"""Studio opening tolerates a transient audio-endpoint failure (2026-10-14).

On macOS, reopening a project made the audio endpoint drop once; the engine
rebuilt it about 1 s later, but the readiness gate had already failed 准备音频.
"""
import os
import time
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_endpoint_failure_fails_the_gate_only_after_the_recovery_grace(tmp_path, monkeypatch):
    _app()
    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_readiness import StudioReadiness
    page = SubtitleStudioPage()
    try:
        gate = StudioReadiness(page)
        gate.begin(str(tmp_path / "ghost.2byteproj"))
        gate.steps, gate.hydrated = None, True
        state = {"state": "ENDPOINT_FAILED", "decoder_error": "Audio endpoint disconnected"}
        monkeypatch.setattr(page.audio_engine, "telemetry_snapshot", lambda: dict(state))
        failures = []
        monkeypatch.setattr(gate, "fail", lambda stage, error: failures.append((stage, error)))
        gate._tick()
        assert ("准备音频", "Audio endpoint disconnected") not in failures      # inside the grace
        assert gate._audio_failed_since is not None
        state["state"] = "PAUSED"                                              # recovered
        gate._tick()
        assert gate._audio_failed_since is None
        state["state"] = "ENDPOINT_FAILED"
        gate._tick()
        gate._audio_failed_since = time.monotonic() - gate.AUDIO_RECOVERY_GRACE_S - 1
        gate._tick()
        assert ("准备音频", "Audio endpoint disconnected") in failures         # persisted: fails
        gate.cancel()
    finally:
        page.close_page()
        page.deleteLater()
        _app().processEvents()
