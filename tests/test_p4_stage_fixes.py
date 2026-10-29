"""P4 stage regression tests: style apply pipeline, selection lock,
find/replace, two-layer strokes, fill editor reopen."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.studio.studio_find_replace import (
    FindReplaceDialog,
    replace_all,
    replace_next,
)
from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_recipe import FillSpec


def _app():
    return QApplication.instance() or QApplication([])


def _make_page(tmp_path, cue_count=4):
    cues = [
        StudioCue(f"c{index}", index * 3000, index * 3000 + 1500, f"句子 {index}", speaker_id="S01")
        for index in range(cue_count)
    ]
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=60_000),
        cues=cues,
    )
    path = save_project(project, tmp_path / "studio.2byteproj")
    page = SubtitleStudioPage()
    _app().processEvents()
    page.open_project(path)
    _app().processEvents()
    return page


def _resolved(page, cue_id):
    project = page.session.project
    cue = next(cue for cue in project.cues if cue.id == cue_id)
    return next(style for style in project.styles if style.id == cue.style_id)


def test_p4_apply_style_scope_all_changes_every_cue(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    page.select_cue("c0")
    app.processEvents()
    page.style_scope.setCurrentIndex(page.style_scope.findData("all"))
    page.style_font_size.setValue(72.0)
    page.style_fill_color.setText("#FF24C0A0")
    page._apply_style()
    app.processEvents()
    assert {_resolved(page, cue_id).font_size for cue_id in ("c0", "c1", "c2", "c3")} == {72.0}
    assert {_resolved(page, cue_id).primary_color for cue_id in ("c0", "c1", "c2", "c3")} == {"#FF24C0A0"}
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_preset_switch_loads_pristine_definition_and_applies(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    page.select_cue("c0")
    app.processEvents()
    store = StylePresetStore()
    others = [preset_id for preset_id in store.all() if preset_id != "default"]
    assert others, "store must expose at least one non-default preset"

    target = others[0]
    preset = store.all()[target]
    page.style_preset.setCurrentIndex(page.style_preset.findData(target))
    app.processEvents()
    page._preset_activated(page.style_preset.currentIndex())
    app.processEvents()
    style = _resolved(page, "c0")
    assert style.font_size == preset.font_size
    assert style.primary_color.upper() == preset.primary_color.upper()
    assert style.font_family == preset.font_family

    # Drift the project copy via a scope=all edit, switch away and back:
    # the dropdown must reload the pristine preset, not the mutated copy.
    page.style_scope.setCurrentIndex(page.style_scope.findData("all"))
    page.style_font_size.setValue(88.0)
    page._apply_style()
    app.processEvents()
    page.style_preset.setCurrentIndex(page.style_preset.findData(target))
    page.style_preset.setCurrentIndex(page.style_preset.findData("default"))
    app.processEvents()
    assert page.style_font_size.value() == store.all()["default"].font_size
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_fill_editor_reopens_with_saved_color(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    page.select_cue("c0")
    app.processEvents()
    page._fill_spec = FillSpec.solid("#FF31A8FF")
    dialog = page._new_fill_editor_dialog(page._fill_spec.to_dict(), page)
    color = dialog.picker.color()
    assert color.rgb() == QColor("#FF31A8FF").rgb() and color.alpha() == 255
    dialog.deleteLater()


def test_p5_alpha_slider_left_is_opaque():
    from PySide6.QtCore import QPointF
    from twobyteasr.design.color_picker import AlphaSlider
    from twobyteasr.studio.studio_ui import FillEditorDialog

    app = _app()
    slider = AlphaSlider()
    slider.resize(200, 24)
    values = []
    slider.alphaChanged.connect(values.append)
    slider._apply(QPointF(2, 12))
    assert values[-1] >= 240, values
    slider._apply(QPointF(198, 12))
    assert values[-1] <= 15, values
    dialog = FillEditorDialog({
        "type": "linear-gradient",
        "stops": [
            {"color": "#FFFFFFFF", "position": 0.0},
            {"color": "#80D2FF20", "position": 1.0},
        ],
    })
    dialog.mode_group.button(1).setChecked(True)
    dialog._select_gradient_stop(1)
    assert dialog.picker.color().alpha() == 0x80
    assert dialog.gradient.opacity_spin.value() == 50
    dialog.picker.set_color(QColor(210, 255, 32, 218))
    assert QColor(dialog.gradient._selected.color).alpha() == 218
    dialog.deleteLater()
    app.processEvents()


def test_p51_fill_editor_professional_picker_layout():
    from PySide6.QtWidgets import QRadioButton
    from twobyteasr.design.color_picker import rgb_to_yuv, yuv_to_rgb
    from twobyteasr.studio.studio_ui import FillEditorDialog

    app = _app()
    dialog = FillEditorDialog("#80FF4DA3")
    dialog.resize(560, 680)
    dialog.show()
    app.processEvents()
    assert dialog.picker.hue_slider._vertical
    assert dialog.picker.hue_slider.height() >= dialog.picker.hue_slider.width()
    radios = dialog.picker.findChildren(QRadioButton)
    assert len(radios) >= 12
    assert dialog.picker.plate is not None
    assert dialog.picker.color().alpha() == 0x80
    assert dialog.mode_combo.currentIndex() == 0
    assert not dialog.gradient.isVisible()
    dialog.mode_group.button(1).setChecked(True)
    app.processEvents()
    assert dialog.gradient.isVisible()
    assert dialog._angle_host.isVisible()
    dialog.mode_group.button(2).setChecked(True)
    app.processEvents()
    assert dialog.gradient.isVisible()
    assert not dialog._angle_host.isVisible()
    red = QColor(255, 32, 64)
    y, u, v = rgb_to_yuv(red.red(), red.green(), red.blue())
    r, g, b = yuv_to_rgb(y, u, v)
    assert abs(r - 255) <= 2 and abs(g - 32) <= 2 and abs(b - 64) <= 2
    dialog.picker.set_color(QColor(12, 200, 90, 255))
    assert dialog.picker.rgb_spins[1].value() == 200
    dialog.picker._channel_radios["rgb_r"].setChecked(True)
    assert dialog.picker._mode == "rgb_r"
    dialog.deleteLater()
    app.processEvents()


def test_p51_ai_design_uses_user_endpoint(monkeypatch, tmp_path):
    from twobyteasr.caption_design.studio_ai import request_style_design
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.caption_style.style_presets import StylePresetStore
    from twobyteasr.caption_style.motion_library import MotionPresetStore
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    captured = {}

    fake_payload = json.dumps({
        "name": "纸片手写",
        "engine": "remotion",
        "typography": {"fontFamily": "Microsoft YaHei UI", "fontSize": 50, "bold": True},
        "colors": {"fill": "#FFFFF4E8"},
        "outline": {"color": "#FF222222", "width": 2.5, "layers": [
            {"color": "#FF222222", "width": 3.0},
        ]},
        "effects": {"glow": {"color": "#66FFFFFF", "blur": 4, "opacity": 0.2}},
        "motion": {"entrance": {"type": "soft_fade", "duration_ms": 280}, "exit": {"type": "soft_fade", "duration_ms": 160}},
    })

    class _FakeProvider:
        def structured_complete(self, messages, schema, **kwargs):
            captured["stage"] = kwargs.get("stage")
            captured["schema"] = schema
            return json.loads(fake_payload)

    def fake_provider_for_stage(settings, stage):
        captured["settings"] = settings
        captured["provider_stage"] = stage
        return _FakeProvider()

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", fake_provider_for_stage)
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=4000),
        cues=[StudioCue("c0", 0, 1000, "去哪里玩好玩的呢")],
    )
    suggestion = request_style_design(project, "c0", "手工纸片感字幕", {"models": {}})
    assert captured["provider_stage"] == "polish"
    assert isinstance(captured["settings"], dict) and "models" in captured["settings"]
    assert captured["stage"] == "studio_visual_design"
    assert captured["schema"] is not None
    # The legacy single-recipe fixture no longer satisfies the current
    # three-variant schema; studio_ai must degrade explicitly instead of
    # pretending the provider call succeeded.
    assert suggestion.provider_succeeded is False


def test_p4_manual_selection_lock_blocks_follow_steal(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    page.select_cue("c0")
    app.processEvents()
    page._timeline_cue_clicked("c2")
    assert page.selected_cue_id == "c2"
    page._position_changed(0.5)  # playhead inside c0
    assert page.selected_cue_id == "c2", "follow must not steal manual selection"
    page._position_changed(6.5)
    page._position_changed(9.5)
    assert page.selected_cue_id == "c2"
    assert page.active_cue_id == "c3"
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_find_replace_all_next_and_undo(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    page.select_cue("c0")
    app.processEvents()
    originals = [cue.text for cue in page.session.project.cues]

    total, cue_count = replace_all(page, needle="句子", replacement="台词", scope="all")
    assert (total, cue_count) == (4, 4)
    assert [cue.text for cue in page.session.project.cues] == [text.replace("句子", "台词") for text in originals]
    page.session.undo_stack.undo()
    assert [cue.text for cue in page.session.project.cues] == originals
    page.session.undo_stack.redo()
    assert [cue.text for cue in page.session.project.cues] == [text.replace("句子", "台词") for text in originals]

    page.session.undo_stack.undo()
    assert replace_next(page, needle="句子", replacement="台词", scope="all")
    assert page.session.project.cues[0].text == originals[0].replace("句子", "台词", 1)
    assert page.session.selected_cue_id == "c0"
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_find_replace_dialog_counts_and_scopes(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    dialog = FindReplaceDialog(page, page)
    dialog.find_edit.setText("句子")
    dialog.replace_edit.setText("台词")
    app.processEvents()
    assert dialog.status_label.text() == "匹配 4 条字幕 · 4 处"
    dialog._do_replace_all()
    assert all(cue.text.startswith("台词") for cue in page.session.project.cues)
    dialog.deleteLater()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_batch_replace_text_command_undo_redo(tmp_path):
    app = _app()
    page = _make_page(tmp_path)
    originals = [cue.text for cue in page.session.project.cues]
    command = BatchReplaceTextCommand(
        page.session.project,
        {cue.id: cue.text + "!" for cue in page.session.project.cues},
        needle="",
        changed=page._changed,
    )
    page.session.undo_stack.push(command)
    assert [cue.text for cue in page.session.project.cues] == [text + "!" for text in originals]
    page.session.undo_stack.undo()
    assert [cue.text for cue in page.session.project.cues] == originals
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_two_layer_stroke_end_to_end(tmp_path):
    app = _app()
    page = _make_page(tmp_path, cue_count=3)
    page.select_cue("c0")
    app.processEvents()
    page.style_scope.setCurrentIndex(page.style_scope.findData("all"))
    app.processEvents()
    page.style_outline_width.setValue(4.0)
    page.style_outline_color.setText("#FF000000")
    page.style_outline2.setChecked(True)
    page.style_outline2_color.setText("#FFFFFFFF")
    page.style_outline2_width.setValue(2.0)
    page._apply_style()
    app.processEvents()

    style = _resolved(page, "c1")
    assert style.outline_color == "#FF000000" and style.outline_width == 4.0
    assert style.outline2_color == "#FFFFFFFF" and style.outline2_width == 2.0
    assert [layer["width"] for layer in style.stroke_layers()] == [4.0, 2.0]
    # Qt preview receives both layers
    assert len(page.style_preview._strokes) == 2

    # Save/reload keeps the second layer (schema-stable optional fields).
    save_project(page.session.project, tmp_path / "studio.2byteproj")
    reloaded = next(
        style for style in load_project(tmp_path / "studio.2byteproj").styles
        if style.id == "default"
    )
    assert reloaded.outline2_color == "#FFFFFFFF" and reloaded.outline2_width == 2.0

    # Disabling collapses back to the single-layer contract.
    page.style_outline2.setChecked(False)
    page._apply_style()
    app.processEvents()
    collapsed = _resolved(page, "c2")
    assert collapsed.outline2_width == 0.0 and collapsed.outline2_color == ""
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_ass_export_uses_widest_stroke_layer(tmp_path):
    app = _app()
    page = _make_page(tmp_path, cue_count=1)
    page.style_scope.setCurrentIndex(page.style_scope.findData("all"))
    app.processEvents()
    page.style_outline_width.setValue(2.0)
    page.style_outline_color.setText("#FFFF0000")
    page.style_outline2.setChecked(True)
    page.style_outline2_color.setText("#FF000000")
    page.style_outline2_width.setValue(5.0)
    page._apply_style()
    app.processEvents()

    from twobyteasr.rendering.ass_compiler import compile_ass

    line = next(
        item for item in compile_ass(page.session.project).splitlines()
        if item.startswith("Style:")
    )
    fields = line.split(",", 1)[1].split(",")
    # Widest layer (black, width 5) is the closest single-ASS-outline approximation.
    assert fields[4] == "&H00000000"
    assert fields[15] == "5"
    page.close_page()
    page.deleteLater()
    app.processEvents()


def test_p4_output_switches_default_off_in_settings():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS

    switches = DEFAULT_SETTINGS["switches"]
    assert switches["output_jianying_txt"] is False
    assert switches["output_speaker_tracks"] is False
