"""P5.2: product naming, editor visibility, encoder probe, export presets."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.exports.export_presets import PRODUCT_PRESETS
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.exports.studio_render import PROBE_FRAME_SIZE, probe_encoder_detail
from twobyteasr.design.studio_theme import BRAND_DISPLAY_NAME
from twobyteasr.studio.studio_ui import FillEditorDialog, SubtitleStudioPage
from twobyteasr.i18n import translate


def _app():
    return QApplication.instance() or QApplication([])


def test_brand_display_name_is_stable_across_locales():
    assert BRAND_DISPLAY_NAME == "优兔泊"
    assert translate("优兔泊", "en") == "优兔泊"
    assert translate("优兔泊", "ja") == "优兔泊"
    assert translate("继续字幕编辑", "en") == "Continue subtitle editing"


def test_library_copy_and_library_button(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    page = SubtitleStudioPage()
    page.show()
    page.show_project_hub()
    assert page.project_library_title.text() == "继续字幕编辑"
    assert page.project_library_brand.text() == "工程库"
    assert page.filename.text() == "优兔泊"
    assert hasattr(page, "studio_library_button")
    assert page.studio_library_button.isVisible()
    assert not page.studio_back_button.isVisible()
    page.close_page()
    page.deleteLater()


def test_fill_editor_fits_current_full_color_controls():
    _app()
    dialog = FillEditorDialog("#FFFF4DA3")
    assert dialog.minimumWidth() == 620
    assert dialog.picker.fields_host().width() <= 210
    dialog.deleteLater()


def test_encoder_probe_uses_safe_frame_size():
    assert "64x64" not in PROBE_FRAME_SIZE
    width, height = (int(part) for part in PROBE_FRAME_SIZE.split("x"))
    assert width >= 640 and height >= 360
    detail = probe_encoder_detail("ffmpeg", "libx264")
    assert detail["functional"] is True
    assert detail["frame_size"] == PROBE_FRAME_SIZE


def test_product_presets_include_custom():
    ids = {item["id"] for item in PRODUCT_PRESETS}
    assert {"recommended", "fast", "high", "small", "av1", "custom"} <= ids


def test_export_close_restores_studio_editor(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    path = save_project(
        SubtitleProject(
            media=StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=2000),
            cues=[StudioCue("c0", 0, 1000, "hi")],
        ),
        tmp_path / "p52.2byteproj",
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    page.workspace_splitter.hide()
    page._close_export_workspace()
    assert page.export_workspace is None
    assert not page.workspace_splitter.isHidden()
    page.close_page()
    page.deleteLater()
