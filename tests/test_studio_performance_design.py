import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.design.studio_qss import StudioComponentTokens, build_studio_component_qss
from twobyteasr.design.ui_theme import theme_definition
from twobyteasr.design.studio_theme import build_studio_qss
from twobyteasr.studio.studio_performance import StudioPerformanceDialog
from twobyteasr.playback.playback_clock import PlaybackClock

# Keep QApplication alive through pytest fixture teardown, as the other Qt modules do.
_APP = QApplication.instance() or QApplication([])


def test_new_component_styles_have_one_owner_and_custom_tokens():
    legacy = Path("twobyteasr/design/studio_theme.py").read_text(encoding="utf-8")
    for name in ("stylePropertyRow", "motionPreset", "timelineTimecodeInput", "mediaPoolSearch"):
        assert "#" + name not in legacy
    for key in ("warm", "slate", "plum", "lavender"):
        theme = theme_definition(key)
        custom = build_studio_component_qss(theme, replace(StudioComponentTokens(), field_height=47))
        assert "min-height: 47px" in custom
        assert theme.text in custom and theme.accent in custom
        assert build_studio_qss(theme).count("QLineEdit#timelineTimecodeInput {") == 1


def test_diagnostics_copy_and_hidden_timer():
    app = _APP
    parent = QWidget()
    parent.video = SimpleNamespace(_playback_clock=PlaybackClock())
    parent.video_compositor = None
    parent._autosave_profile = []
    panel = StudioPerformanceDialog(parent)
    panel.show()
    app.processEvents()
    panel.copy_snapshot()
    payload = json.loads(app.clipboard().text())
    assert payload["clock"]["paused"] is True and payload["decoders"] == {}
    assert "—" in panel.summary.text()
    panel.close()
    assert not panel.timer.isActive()
    parent.close()
    # Delete while Python still owns both wrappers; returning with this
    # parent/child reference cycle can leave Qt's widget registry dangling
    # before the generic teardown enumerates allWidgets on Windows.
    from PySide6.QtCore import QCoreApplication, QEvent
    panel.deleteLater()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_short_capture_restores_probe_and_never_claims_screen_performance():
    from twobyteasr.diagnostics import playback_probe
    parent=QWidget();parent.video=SimpleNamespace(_playback_clock=PlaybackClock());parent.video_compositor=None
    panel=StudioPerformanceDialog(parent)
    before=playback_probe.ENABLED
    panel.start_capture()
    assert playback_probe.ENABLED and panel._capture_timer.isActive()
    panel.capture_tick();panel.finish_capture()
    assert playback_probe.ENABLED==before
    assert panel._capture_report['performance_pass']=='UNVERIFIED'
    assert panel._capture_report['measurement_valid']['desktop'] is False
    assert panel.export_button.isEnabled()
    panel.deleteLater();parent.deleteLater()
    from PySide6.QtCore import QCoreApplication,QEvent
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
