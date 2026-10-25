import ast
import copy
import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.caption_style.studio_style_controller import StudioStyleController
from twobyteasr.caption_style.studio_style_panel import StudioStylePanelMixin
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_recipe import FillSpec
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def _page(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    project = SubtitleProject(
        media=StudioMedia(
            path=str(tmp_path / "missing.mp4"),
            duration_ms=5_000,
            width=1920,
            height=1080,
        ),
        speakers=[StudioSpeaker("S01", "One"), StudioSpeaker("S02", "Two")],
        styles=[
            SubtitleStyle("default", "Default", font_size=48),
            SubtitleStyle(
                "alternate",
                "Alternate",
                font_family="Arial",
                font_size=72,
                primary_color="#FF99CC",
                bold=True,
                alignment=8,
            ),
        ],
        cues=[
            StudioCue("a", 0, 1_200, "First", speaker_id="S01"),
            StudioCue(
                "b",
                1_400,
                2_600,
                "Second",
                speaker_id="S02",
                style_id="alternate",
            ),
            StudioCue("c", 2_800, 4_000, "Third", speaker_id="S01"),
        ],
    )
    page.project = project
    page.project_path = tmp_path / "style-controller.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.select_cue("a")
    page.undo_stack.clear()
    page.undo_stack.setClean()
    app.processEvents()
    return app, page


def _finish(page):
    app = _app()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def _style_for_cue(page, cue_id):
    cue = page.session._cue_lookup[cue_id]
    return next(style for style in page.session.project.styles if style.id == cue.style_id)


def test_style_controller_is_plain_session_first_collaborator():
    assert not issubclass(StudioStyleController, QObject)
    assert {"page", "session"}.issubset(StudioStyleController.__slots__)
    assert not any(
        isinstance(value, Signal) for value in StudioStyleController.__dict__.values()
    )

    source = inspect.getsource(inspect.getmodule(StudioStyleController))
    assert "from .studio_ui" not in source
    assert "import twobyteasr.studio.studio_ui" not in source
    for forbidden in (
        "QThread",
        "threading",
        "SubtitlePositionOverlay",
        "SubtitleTransformVisualOverlay",
        "SubtitleCoordinateMapper",
        "AdvancedLiveCanvas",
        "WA_NativeWindow",
        "winId",
    ):
        assert forbidden not in source

    tree = ast.parse(source)
    controller = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StudioStyleController"
    )
    forbidden_page_fields = []
    for node in ast.walk(controller):
        if not isinstance(node, ast.Attribute) or node.attr not in {
            "project",
            "project_path",
            "selected_cue_id",
            "_cue_lookup",
            "undo_stack",
        }:
            continue
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "self"
            and value.attr == "page"
        ):
            forbidden_page_fields.append((node.lineno, node.attr))
    assert forbidden_page_fields == []


def test_style_page_wrappers_are_single_call_delegations():
    # Since the studio_ui split the style wrappers live on StudioStylePanelMixin.
    tree = ast.parse(inspect.getsource(inspect.getmodule(StudioStylePanelMixin)))
    page_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StudioStylePanelMixin"
    )
    wrappers = []
    for method in page_class.body:
        if not isinstance(method, ast.FunctionDef) or len(method.body) != 1:
            continue
        statement = method.body[0]
        if not isinstance(statement, (ast.Return, ast.Expr)):
            continue
        call = statement.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        if not (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
            and owner.attr == "style_controller"
        ):
            continue
        wrappers.append((method, call.func.attr))

    assert len(wrappers) >= 60
    for wrapper, controller_name in wrappers:
        assert wrapper.name == controller_name
        assert hasattr(StudioStyleController, controller_name)
        assert not any(
            isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With))
            for node in ast.walk(wrapper)
        )
        assert not any(
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for node in ast.walk(wrapper)
        )


def test_panel_build_and_selected_cue_control_resync(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    assert page.style_controller.page is page
    assert page.style_controller.session is page.session
    assert page.context_drawer.count() == 6
    # Narrow drawers use icons; the complete navigation label remains in the
    # tooltip. Creating the final parent tree earlier also lays this out earlier.
    assert page.context_drawer.tabText(5) in ("", "素材")
    assert page.context_drawer.tabToolTip(5) == "素材"
    assert page.style_scope.currentData() == "selected"
    cue = next(item for item in page.project.cues if item.id == "a")
    style = next(item for item in page.project.styles if item.id == cue.style_id)
    assert page.style_font.currentText() == style.font_family
    assert page.style_font_size.value() == 48

    page.select_cue("b")
    app.processEvents()
    assert page.session.selected_cue_id == "b"
    assert page.style_font.currentText() == "Arial"
    assert page.style_font_size.value() == 72
    assert page.style_bold.isChecked()
    assert page.style_alignment.currentData() == 8
    _finish(page)


def test_style_fields_apply_as_one_undo_and_redo_snapshot(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    before = build_visual_cue_snapshot(page.project, "a")
    page._updating_style_ui = True
    try:
        page.style_font.setEditText("Arial")
        page.style_font_size.setValue(63)
        page.style_spacing.setValue(2)
        page.style_bold.setChecked(True)
        page.style_italic.setChecked(True)
        page.style_underline.setChecked(True)
        page.style_fill_color.setText("#FF112233")
        page._fill_spec = FillSpec.solid("#FF112233")
        page.style_outline_color.setText("#FF445566")
        page.style_outline_width.setValue(4.5)
        page.style_shadow_opacity.setValue(50)
        page.style_shadow_offset_x.setValue(2)
        page.style_shadow_offset_y.setValue(2)
        page.style_shadow_blur.setValue(0)
        page.style_shadow_spread.setValue(0)
        page.style_background.setChecked(True)
        page.style_back_color.setText("#80445566")
        page.style_alignment.setCurrentIndex(page.style_alignment.findData(8))
        page.style_position_x.setValue(640)
        page.style_position_y.setValue(120)
    finally:
        page._updating_style_ui = False

    page._apply_style()
    assert page.undo_stack.count() == 1
    style = _style_for_cue(page, "a")
    assert (
        style.font_family,
        style.font_size,
        style.spacing,
        style.bold,
        style.italic,
        style.underline,
    ) == ("Arial", 63, 2, True, True, True)
    assert (
        style.primary_color,
        style.outline_color,
        style.outline_width,
        style.shadow,
        style.border_style,
        style.back_color,
    ) == ("#FF112233", "#FF445566", 4.5, 2.0, 3, "#80445566")
    assert (style.alignment, style.position_x, style.position_y) == (8, 640, 120)
    applied = build_visual_cue_snapshot(page.project, "a")
    assert applied.shadow["opacity"] == 0.5
    assert applied.shadow["offset_x"] == 2.0
    assert applied.shadow["offset_y"] == 2.0
    assert applied.shadow["blur_radius"] == 0.0
    assert applied.shadow["spread"] == 0.0
    assert applied.stable_hash() != before.stable_hash()

    page.undo_stack.undo()
    assert build_visual_cue_snapshot(page.project, "a").stable_hash() == before.stable_hash()
    page.undo_stack.redo()
    assert build_visual_cue_snapshot(page.project, "a").stable_hash() == applied.stable_hash()
    _finish(page)


def test_gradient_and_motion_each_keep_one_undo_step(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    gradient = FillSpec.linear(
        [
            {"color": "#FFFF0000", "position": 0.0},
            {"color": "#FF0000FF", "position": 1.0},
        ],
        angle=35,
    )
    page._apply_fill_spec(gradient)
    assert page.undo_stack.count() == 1
    cue = page.session._cue_lookup["a"]
    assert page.project.style_recipes[cue.style_id]["colors"]["fill"] == gradient.to_dict()
    page.undo_stack.undo()
    assert page.session._cue_lookup["a"].style_id == "default"

    page.undo_stack.clear()
    index = page.motion_preset.findData("quick_pop")
    page.motion_preset.blockSignals(True)
    page.motion_preset.setCurrentIndex(index)
    page.motion_preset.blockSignals(False)
    page._motion_preset_changed(index)
    assert page.undo_stack.count() == 0  # the current motion UI edits a draft
    page.motion_apply.click()
    assert page.undo_stack.count() == 1
    effect_id = page.session._cue_lookup["a"].effect_id
    assert page.project.effects[effect_id]["entry"]["type"] == "soft_pop"
    assert page.project.effects[effect_id]["entry"]["duration"] == page.effect_duration.value()
    page.undo_stack.undo()
    assert page.session._cue_lookup["a"].effect_id == "none"
    page.undo_stack.redo()
    assert page.session._cue_lookup["a"].effect_id == effect_id
    _finish(page)


def test_stroke_edit_preserves_gradient_fill(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    gradient = FillSpec.linear(
        [
            {"color": "#FFFFAA00", "position": 0.0},
            {"color": "#FF00FF88", "position": 1.0},
        ],
        angle=90,
    )
    page._apply_fill_spec(gradient)
    page.style_outline_width.setValue(10.0)
    page._apply_style()
    cue = page.session._cue_lookup["a"]
    fill = page.project.style_recipes[cue.style_id]["colors"]["fill"]
    assert fill["type"] == "linear-gradient"
    assert fill["angle"] == 90
    assert len(fill["stops"]) == 2
    _finish(page)


def test_preset_create_rename_and_delete_use_existing_store(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    names = iter(("My Style", "Renamed Style"))
    monkeypatch.setattr(page, "_preset_name", lambda *_args: next(names))

    page._new_style_preset()
    user = StylePresetStore().load_user()
    assert len(user) == 1
    style_id = next(iter(user))
    assert page.style_preset.currentData() == style_id

    page._rename_style_preset()
    assert StylePresetStore().load_user()[style_id].name == "Renamed Style"
    page._delete_style_preset()
    assert StylePresetStore().load_user() == {}
    assert page.style_preset.currentData() == "default"
    _finish(page)


def test_multi_scope_and_copy_paste_preserve_non_style_fields(tmp_path, monkeypatch):
    _app_instance, page = _page(tmp_path, monkeypatch)
    selection = page.cue_table.selectionModel()
    selection.clearSelection()
    for cue_id in ("a", "b"):
        row = page.cue_model.row_for_cue_id(cue_id)
        selection.select(
            page.cue_model.index(row, 0),
            selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
        )
    page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
    assert set(page._style_target_ids()) == {"a", "b"}
    # Scope selection applies its current preset as a separate transaction.
    # Selecting the new preset itself applies it once; do not also simulate an
    # unrelated manual inspector commit.
    page.undo_stack.clear()
    page.style_preset.setCurrentIndex(page.style_preset.findData("game"))
    assert page.undo_stack.count() == 1
    assert all(page.session._cue_lookup[cue_id].style_id.startswith("game") for cue_id in ("a", "b"))
    assert page.session._cue_lookup["c"].style_id == "default"
    page.undo_stack.undo()

    page.select_cue("b")
    source = page.session._cue_lookup["b"]
    source_before = copy.deepcopy(source)
    page._copy_subtitle_style()
    page.select_cue("a")
    target_before = copy.deepcopy(page.session._cue_lookup["a"])
    page.undo_stack.clear()
    page._paste_subtitle_style()
    assert page.undo_stack.count() == 1
    target = page.session._cue_lookup["a"]
    assert (target.text, target.start_ms, target.end_ms, target.speaker_id) == (
        target_before.text,
        target_before.start_ms,
        target_before.end_ms,
        target_before.speaker_id,
    )
    assert _style_for_cue(page, "a").font_size == _style_for_cue(page, source_before.id).font_size
    page.undo_stack.undo()
    assert page.session._cue_lookup["a"].style_id == target_before.style_id
    _finish(page)


def test_missing_font_warning_is_visible_without_persisting_fallback(tmp_path, monkeypatch):
    from twobyteasr.exports.preset_application import preset_command
    app, page = _page(tmp_path, monkeypatch)
    command = preset_command(page.project, ['a'], {'id':'missing', 'name':'Missing',
        'font_family':'Missing test face', 'font_weight':900, 'font_style_name':'Heavy'})
    command.redo(); page._load_style_inspector()
    assert 'Missing test face' in page.style_font_warning.text()
    assert not page.style_font_warning.isHidden()
    assert page.style_font.currentText() == 'Missing test face'
    assert _style_for_cue(page,'a').font_family == 'Missing test face'
    assert page.style_preview._resolved_face.family == 'Source Han Sans SC'
    assert page.style_preview._resolved_face.weight == 500
    assert page.style_preview._style.font_family == 'Missing test face'
    command.undo(); page._load_style_inspector()
    assert 'Missing test face' not in page.style_font.currentText()
    _finish(page)


def test_scope_switch_to_speaker_only_changes_future_edit_targets(tmp_path, monkeypatch):
    """2026-10-24: selecting a scope is not itself a style mutation."""
    app, page = _page(tmp_path, monkeypatch)
    try:
        page.select_cue("a")
        index = page.style_preset.findData("game")
        assert index >= 0
        page.style_preset.setCurrentIndex(index)
        app.processEvents()
        # scope 仍是 current：只有 a 换成 game
        assert str(page.session._cue_lookup["a"].style_id).startswith("game")
        assert page.session._cue_lookup["c"].style_id == "default"
        # Changing the scope must preserve the other cue until an explicit edit.
        page.style_scope.setCurrentIndex(page.style_scope.findData("speaker"))
        app.processEvents()
        assert page.session._cue_lookup["c"].style_id == "default"
        assert str(page.session._cue_lookup["a"].style_id).startswith("game")
    finally:
        _finish(page)


def _derived_ids(project):
    from twobyteasr.caption_style.style_cleanup import is_derived_style_id
    return ({style.id for style in project.styles if is_derived_style_id(style.id)}
            | {key for key in project.style_recipes if is_derived_style_id(key)})


def _select(page, cue_ids):
    selection = page.cue_table.selectionModel()
    selection.clearSelection()
    for cue_id in cue_ids:
        row = page.cue_model.row_for_cue_id(cue_id)
        selection.select(page.cue_model.index(row, 0),
                         selection.SelectionFlag.Select | selection.SelectionFlag.Rows)


def test_selected_scope_batch_keeps_one_copy_per_previous_style_and_no_orphans(tmp_path, monkeypatch):
    """2026-10-21 user report: 1,000+ cues + 「已选」 left one dead style per cue;
    every later Enter froze for seconds and memory grew with each edit."""
    app, page = _page(tmp_path, monkeypatch)
    try:
        project = page.project
        extra = [StudioCue(f"x{i}", 4_200 + i * 100, 4_280 + i * 100, f"Extra {i}",
                           speaker_id="S02", style_id="alternate") for i in range(40)]
        project.cues.extend(extra)
        page._cue_lookup = {cue.id: cue for cue in project.cues}
        page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
        page.cue_model.set_project(project)
        page.timeline.set_project(project)
        ids = [cue.id for cue in project.cues]
        styles_before = [style.id for style in project.styles]
        _select(page, ids)
        page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
        app.processEvents()
        assert set(page._style_target_ids()) == set(ids)
        referenced = {cue.style_id for cue in project.cues} | {s.style_id for s in project.speakers}
        copies = {style.id for style in project.styles if "-cue-" in style.id}
        # 41 cues on 'alternate' and 2 on 'default': at most one copy per previous style.
        assert len(copies) <= 2
        assert _derived_ids(project) <= referenced
        page.style_position_y.setValue(page.style_position_y.value() - 40)
        page.style_position_y.editingFinished.emit()
        app.processEvents()
        referenced = {cue.style_id for cue in project.cues} | {s.style_id for s in project.speakers}
        assert _derived_ids(project) <= referenced, "a later apply must not keep dead copies"
        while page.undo_stack.canUndo():
            page.undo_stack.undo()
        assert [style.id for style in project.styles] == styles_before
        while page.undo_stack.canRedo():
            page.undo_stack.redo()
        referenced = {cue.style_id for cue in project.cues} | {s.style_id for s in project.speakers}
        assert _derived_ids(project) <= referenced
    finally:
        _finish(page)


def test_loading_a_project_drops_unused_derived_styles_only(tmp_path):
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    from twobyteasr.projects.studio_project import load_project, save_project
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "missing.mp4"), duration_ms=5_000, width=1920, height=1080),
        speakers=[StudioSpeaker("S01", "One", style_id="game-cue-speaker1")],
        styles=[SubtitleStyle("default", "Default"), SubtitleStyle("game", "Game"),
                SubtitleStyle("game-cue-used00001", "Used"), SubtitleStyle("game-cue-speaker1", "Speaker"),
                *[SubtitleStyle(f"game-cue-dead{i:04d}", "Dead") for i in range(300)]],
        style_recipes={"game": StyleRecipe(name="Game").to_dict(),
                       "game-cue-used00001": StyleRecipe(name="Used").to_dict(),
                       **{f"game-cue-dead{i:04d}": StyleRecipe(name="Dead").to_dict() for i in range(300)}},
        cues=[StudioCue("a", 0, 1_000, "One", speaker_id="S01", style_id="game-cue-used00001"),
              StudioCue("b", 1_200, 2_000, "Two", speaker_id="S01", style_id="game")],
    )
    path = save_project(project, tmp_path / "dead-styles.2byteproj")
    loaded = load_project(path)
    assert [style.id for style in loaded.styles] == ["default", "game", "game-cue-used00001", "game-cue-speaker1"]
    assert set(loaded.style_recipes) == {"game", "game-cue-used00001"}
