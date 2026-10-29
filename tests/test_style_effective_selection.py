"""Actual selected subtitles and field-only style edits share one command."""
import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from tests.test_studio_style_controller import _page, _finish
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.timeline.selection_scope import SelectionScope
from twobyteasr.projects.studio_project import load_project, save_project


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, widget = _page(tmp_path, monkeypatch)
    yield widget
    _finish(widget)


def visuals(project):
    return {cue.id: copy.deepcopy(resolve_cue_visual(project, cue).style) for cue in project.cues}


def choose(page, kind):
    if kind == "single":
        page.select_cue("a")
        return {"a"}
    if kind == "multi":
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(["a", "b"], "a"))
        return {"a", "b"}
    if kind == "all":
        page._select_all_timeline_cues()
        return {"a", "b", "c"}
    page.timeline.select_speakers(["S01"])
    return {"a", "c"}


@pytest.mark.parametrize("kind", ["single", "multi", "all", "group"])
@pytest.mark.parametrize("field,value", [("font_size", 91), ("outline_width", 4.5)])
def test_selection_applies_only_the_edited_field(page, tmp_path, kind, field, value):
    selected = choose(page, kind)
    before = visuals(page.project)
    count = page.undo_stack.count()
    control = getattr(page, "style_" + field)
    control.setValue(value)
    page._commit_style_now()
    after = visuals(page.project)
    for cue_id, previous in before.items():
        expected = copy.deepcopy(previous)
        if cue_id in selected:
            setattr(expected, field, value)
        # Materialized style identity can change; appearance must not.
        expected.id, expected.name = after[cue_id].id, after[cue_id].name
        assert after[cue_id] == expected, (cue_id, field, kind)
    assert page.undo_stack.count() == count + 1
    page.undo_stack.undo()
    assert visuals(page.project) == before
    page.undo_stack.redo()
    assert visuals(page.project) == after
    destination = tmp_path / "roundtrip.2byteproj"
    save_project(page.project, destination)
    assert visuals(load_project(destination)) == after


def test_selected_scope_uses_canonical_scope_when_table_is_filtered(page):
    page.cue_controller.apply_selection_scope(SelectionScope.explicit(["a", "b"], "a"))
    # Mirroring only rows that are visible must not redefine the selection.
    model = page.cue_table.selectionModel()
    model.blockSignals(True)
    model.clearSelection()
    model.blockSignals(False)
    page._updating_style_ui = True
    page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
    page._updating_style_ui = False
    assert set(page._style_target_ids()) == {"a", "b"}


def test_new_multiselection_updates_scope_without_applying_style(page):
    page.style_scope.setCurrentIndex(page.style_scope.findData("current"))
    before = visuals(page.project)
    count = page.undo_stack.count()
    page.cue_controller.apply_selection_scope(SelectionScope.explicit(["a", "b"], "a"))
    assert page.style_scope.currentData() == "selected"
    assert page.undo_stack.count() == count
    assert visuals(page.project) == before


@pytest.mark.parametrize("field,value", [
    ("font_family", "Microsoft YaHei UI"), ("primary_color", "#FF12468A"),
    ("outline_color", "#FF987654"), ("alignment", 6), ("bold", True),
    ("italic", True), ("underline", True), ("spacing", 3),
    ("outline2_width", 3.5), ("outline2_color", "#FFCC8800"),
])
def test_other_controls_keep_each_cues_other_fields(page, field, value):
    choose(page, "multi")
    if field.startswith('outline2_'):
        page.style_outline2.setChecked(True)
    before = visuals(page.project)
    if field == 'font_family':
        page.style_font.commit_family(value)
    elif field.endswith('color'):
        control = {'primary_color': page.style_fill_color,
                   'outline_color': page.style_outline_color,
                   'outline2_color': page.style_outline2_color}[field]
        page._set_style_color(control, value)
    elif field == 'alignment':
        page.style_alignment.setCurrentIndex(page.style_alignment.findData(value))
    elif field in {'bold', 'italic', 'underline'}:
        getattr(page, 'style_'+field).setChecked(value)
    else:
        getattr(page, 'style_'+field).setValue(value)
        page._commit_style_now()
    after = visuals(page.project)
    for cue_id in before:
        if cue_id == 'c':
            assert after[cue_id] == before[cue_id]
            continue
        assert getattr(after[cue_id], field) == value
        for preserved in ('font_size', 'primary_color', 'outline_color', 'alignment', 'shadow'):
            if preserved != field:
                assert getattr(after[cue_id], preserved) == getattr(before[cue_id], preserved)


@pytest.mark.parametrize('expanded', [False, True])
@pytest.mark.parametrize('locked', [False, True])
def test_secondary_group_members_include_folded_cues_and_exclude_locks(page, expanded, locked):
    from twobyteasr.projects.studio_project import StudioSpeaker
    from twobyteasr.recognition.speaker_roles import decide
    page.project.speakers.append(StudioSpeaker('S03', 'Third speaker'))
    page.project.cues[2].speaker_id = 'S03'
    page.project.studio_state['speaker_roles'] = decide(
        page.project, manual={'S01':'main', 'S02':'secondary', 'S03':'secondary'}, expanded=expanded)
    page.timeline.reindex_project()
    assert set(page.timeline._group_members) == {'S02', 'S03'}
    assert page.timeline._group_collapsed() == (not expanded)
    if locked:
        page.timeline.locked_speakers.add('S03')
    page.timeline.select_speakers(page.timeline._group_members)
    targets = {'b'} if locked else {'b', 'c'}
    assert set(page._style_target_ids()) == targets
    before = visuals(page.project)
    page.style_font_size.setValue(83)
    page._commit_style_now()
    page._set_style_color(page.style_outline_color, '#FF112244')
    for cue_id, style in visuals(page.project).items():
        if cue_id in targets:
            assert style.font_size == 83 and style.outline_color == '#FF112244'
            assert style.font_family == before[cue_id].font_family
        else:
            assert style == before[cue_id]


@pytest.mark.parametrize('scope', [SelectionScope.all(3, 'a'), SelectionScope.row_range(0, 1, active_id='a')])
def test_compact_selection_survives_commit_and_inspector_refresh(page, scope):
    page.cue_controller.apply_selection_scope(scope)
    page.style_font_size.setValue(79)
    page._commit_style_now()
    assert page.selection_model.scope == scope
    assert page.timeline.selection_scope == scope
    assert set(page._style_target_ids()) == set(scope.materialize(['a', 'b', 'c']))


def test_color_dialog_focus_does_not_shrink_selection_or_commit_mixed_values(page):
    choose(page, 'multi')
    before = visuals(page.project)
    chosen = set(page._style_target_ids())
    page.show()
    page.context_drawer.setCurrentIndex(1)
    def accept_picker():
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        assert set(page._style_target_ids()) == chosen
        dialog.picker.set_color(QColor('#FF123456'))
        buttons = dialog.findChild(QDialogButtonBox)
        QTest.mouseClick(buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
    QTimer.singleShot(30, accept_picker)
    page._open_style_color_dialog(page.style_outline_color)
    assert set(page._style_target_ids()) == chosen
    for cue_id, style in visuals(page.project).items():
        assert style.font_size == before[cue_id].font_size
        assert style.outline_color == ('#ff123456' if cue_id in chosen else before[cue_id].outline_color).upper()


def test_shadow_opacity_patch_keeps_each_cues_shape_and_other_styles(page):
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    for cue, opacity, x, blur in [(page.project.cues[0], .3, 2, 4), (page.project.cues[1], .7, 8, 12)]:
        style = resolve_cue_visual(page.project, cue).style
        recipe = page._base_recipe_for_style(style)
        recipe.outline['shadow'] = {'opacity': opacity, 'offset_x': x, 'offset_y': 3,
                                     'blur_radius': blur, 'spread': 1, 'strength': x}
        page.project.style_recipes[cue.style_id] = recipe.to_dict()
    choose(page, 'multi')
    before = {cue.id: build_visual_cue_snapshot(page.project, cue.id) for cue in page.project.cues}
    page.style_shadow_opacity.setValue(51)
    page._commit_style_now()
    for cue in page.project.cues:
        after = build_visual_cue_snapshot(page.project, cue.id)
        assert after.font_family == before[cue.id].font_family
        assert after.font_size == before[cue.id].font_size
        if cue.id == 'c':
            assert after.shadow == before[cue.id].shadow
            continue
        assert after.shadow['opacity'] == .51
        for key in ('offset_x', 'offset_y', 'blur_radius', 'spread'):
            assert after.shadow[key] == before[cue.id].shadow[key]


def test_clock_observation_and_row_seek_do_not_replace_manual_multiselection(page, monkeypatch):
    choose(page, 'multi')
    monkeypatch.setattr(page, '_seek', lambda seconds: page.cue_controller.sync_playhead_target(round(seconds*1000), force=True))
    page.cue_controller.table_activated(page.cue_model.index(1, 3))
    assert set(page.selected_cue_ids()) == {'a', 'b'}
    assert page.session.selected_cue_id == 'b'
    assert page.session.observed_playhead_target_id == 'b'
    page.cue_controller.sync_playhead_target(3000, force=True)
    assert set(page._style_target_ids()) == {'a', 'b'}
    page.cue_controller.cancel_selection()
    assert page.selected_cue_ids() == []


def test_timeline_select_all_keeps_its_existing_locked_track_rule(page):
    page.timeline.locked_speakers.add('S02')
    page.timeline.select_all_clips()
    assert set(page._style_target_ids()) == {'a', 'c'}
    page.style_font_size.setValue(67)
    page._commit_style_now()
    assert visuals(page.project)['b'].font_size == 72


def test_glow_toggle_commits_once_without_a_delayed_duplicate(page):
    choose(page, 'multi')
    count = page.undo_stack.count()
    page.style_glow.setChecked(True)
    QTest.qWait(page._style_debounce_timer.interval()+30)
    assert page.undo_stack.count() == count+1


@pytest.mark.parametrize('kind', ['single', 'multi', 'all', 'group'])
def test_fill_editor_commit_uses_the_same_effective_selection(page, kind):
    from twobyteasr.caption_style.style_recipe import FillSpec
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    targets = choose(page, kind)
    before = visuals(page.project)
    count = page.undo_stack.count()
    page._apply_fill_spec(FillSpec.solid('#FF6688AA'))
    for cue_id, style in visuals(page.project).items():
        if cue_id not in targets:
            assert style == before[cue_id]
            continue
        assert build_visual_cue_snapshot(page.project, cue_id).fill['color'] == '#FF6688AA'
        for field in ('font_family', 'font_size', 'outline_color', 'outline_width', 'alignment', 'shadow'):
            assert getattr(style, field) == getattr(before[cue_id], field)
    assert page.undo_stack.count() == count+1
    page.undo_stack.undo()
    assert visuals(page.project) == before


def test_size_edit_preserves_existing_overrides_and_updates_only_same_named_transform(page, tmp_path):
    a, b = page.project.cues[:2]
    a.appearance_override = {'primary_color':'#FF123456', 'outline_width':7}
    a.transform = {'font_size':93, 'position_x':321, 'position_y':654, 'rotation':12}
    b.base_preset_id = 'alternate'
    b.appearance_override = {'primary_color':'#FF654321', 'outline_color':'#FF998877'}
    b.transform = {'scale_x':80, 'scale_y':90}
    choose(page, 'multi')
    before = visuals(page.project)
    old_transforms = {cue.id:copy.deepcopy(cue.transform) for cue in page.project.cues}
    page.style_font_size.setValue(77)
    page._commit_style_now()
    after = visuals(page.project)
    for cue_id in ('a','b'):
        assert after[cue_id].font_size == 77
        for field in ('font_family','primary_color','outline_color','outline_width','position_x','position_y','scale_x','scale_y'):
            assert getattr(after[cue_id],field) == getattr(before[cue_id],field)
        expected=copy.deepcopy(old_transforms[cue_id])
        if 'font_size' in expected:
            expected['font_size']=77
        assert page.session._cue_lookup[cue_id].transform == expected
    path=tmp_path/'overrides.2byteproj'
    save_project(page.project,path)
    assert visuals(load_project(path)) == after
    page.undo_stack.undo()
    assert visuals(page.project) == before
    assert {cue.id:cue.transform for cue in page.project.cues} == old_transforms
