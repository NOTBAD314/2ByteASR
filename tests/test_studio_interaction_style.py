"""A scope click replays only the current user's bound style action."""
import copy
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from tests.test_presentation_scope_contract import page, values
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.scoped_style import effective_layer_style
from twobyteasr.timeline.selection_scope import SelectionScope
from twobyteasr.projects.studio_project import save_project, load_project


PATCH = dict(id='interaction-preset', name='测试预设', font_size=63., outline_color='#FFFF8800',
             outline_width=7., position_x=280., position_y=430., scale_x=125., scale_y=135.)


def choose(page, monkeypatch, patch=PATCH):
    monkeypatch.setattr(StylePresetStore, 'load_patch', lambda *_: copy.deepcopy(patch))
    page.style_preset.addItem('测试预设', patch['id'])
    index = page.style_preset.findData(patch['id'])
    page.style_preset.setCurrentIndex(index)
    page.style_preset.activated.emit(index)


def click_scope(page, scope):
    button = page.style_scope._buttons[page.style_scope.findData(scope)]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(max(1, button.width()-3), button.height()//2))


def select_one(page):
    page.cue_controller.apply_selection_scope(SelectionScope.explicit(['stable-0'], 'stable-0'))


@pytest.mark.parametrize('scope', ['speaker', 'all', 'selected'])
@pytest.mark.parametrize('preset_first', [True, False])
def test_scope_and_preset_orders_apply_identical_targets(page, monkeypatch, scope, preset_first):
    if scope != 'selected': select_one(page)
    wanted = {c.id for c in page.project.cues if scope != 'speaker' or c.speaker_id == 'A'}
    if scope == 'selected': wanted = {'stable-'+str(i) for i in range(21)}
    if preset_first:
        choose(page, monkeypatch); click_scope(page, scope)
    else:
        click_scope(page, scope); choose(page, monkeypatch)
    assert page.style_scope.currentData() == scope
    assert {c.id for c in page.project.cues if effective_layer_style(page.project,c,'original').font_size == 63.} == wanted
    assert str(len(wanted)) in page.style_scope_summary.text()
    count = page.undo_stack.count()
    click_scope(page, scope)
    assert page.undo_stack.count() == count


def test_geometry_toggle_uses_saved_pose_then_new_scope_and_one_undo(page, monkeypatch):
    select_one(page)
    before = values(page); other = values(page,'translation')
    choose(page, monkeypatch)
    assert all(values(page)[key][field] == old[field] for key,old in before.items()
               for field in ('position_x','position_y','scale_x','scale_y'))
    page.caption_transform_panel.edit('position_x',40.);page.caption_transform_panel.finish_field('position_x')
    page.style_apply_geometry.setChecked(True)
    assert values(page)['stable-0']['position_x'] == 280.
    before_all = values(page)
    count = page.undo_stack.count()
    click_scope(page,'all')
    assert page.undo_stack.count() == count+1
    assert all(row['position_x']==280. and row['scale_y']==135. for row in values(page).values())
    assert values(page,'translation') == other
    after = values(page)
    page.undo_stack.undo();assert values(page)==before_all
    page.undo_stack.redo();assert values(page)==after
    page.style_apply_geometry.setChecked(False)
    assert values(page)==after


def test_blue_edit_extends_preset_but_not_other_properties_or_layer(page, monkeypatch, tmp_path):
    select_one(page);other = values(page,'translation')
    choose(page,monkeypatch)
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    click_scope(page,'speaker')
    for cue in page.project.cues:
        style=effective_layer_style(page.project,cue,'original')
        if cue.speaker_id=='A':assert QColor(style.outline_color)==QColor('#0066FF') and style.font_size==63.
    assert values(page,'translation')==other
    saved=save_project(page.project,tmp_path/'color.2byteproj'); reopened=load_project(saved)
    for cue in reopened.cues:
        if cue.speaker_id=='A':assert QColor(effective_layer_style(reopened,cue,'original').outline_color)==QColor('#0066FF')


def test_panel_swatch_rehydrates_after_undo_and_reselection(page):
    select_one(page)
    before=QColor(page.style_outline_color.text())
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    button=page.style_outline_swatch.findChild(page._style_color_button_type())
    assert button._color==QColor('#0066FF')
    page.undo_stack.undo()
    assert QColor(page.style_outline_color.text())==before
    assert button._color==before


def test_scope_survives_selection_and_old_action_does_not_cross_cue(page, monkeypatch):
    select_one(page);choose(page,monkeypatch);click_scope(page,'speaker')
    page.select_cue('stable-1')
    assert page.style_scope.currentData()=='speaker'
    before=copy.deepcopy(page.project.cues)
    click_scope(page,'all')
    assert page.project.cues==before


def test_mixed_scope_color_is_explicit(page):
    select_one(page)
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    click_scope(page,'all')  # expand the one explicit field
    page.select_cue('stable-1')
    page.project.cues[1].appearance_override['outline_color']='#FFFF0000'
    page._load_style_inspector()
    button=page.style_outline_swatch.findChild(page._style_color_button_type())
    assert '混合' in button.toolTip()


def test_partial_preset_keeps_missing_geometry_axes(page,monkeypatch):
    before=values(page)
    page.style_apply_geometry.setChecked(True)
    choose(page,monkeypatch,dict(id='partial',name='部分变换',scale_x=150.,outline_width=9.))
    after=values(page)
    for key in ['stable-'+str(i) for i in range(21)]:
        assert after[key]['scale_x']==150.
        for field in ('scale_y','position_x','position_y','rotation'):
            assert after[key][field]==before[key][field]


def test_frozen_geometry_fast_path_equals_measured_bilingual_layout(page,monkeypatch):
    from twobyteasr.caption_style.caption_layer_transform import GeometryBatch,resolved_values
    choose(page,monkeypatch)
    batch=GeometryBatch(page.project)
    for cue in page.project.cues[:21]:
        for language in ('original','translation'):
            assert batch.values(cue,language)==resolved_values(page.project,cue,language,geometry_only=True)


def test_scope_ignores_filter_and_resolves_merged_ids_without_names(page,monkeypatch):
    select_one(page)
    page.project.cues[2].speaker_id='legacy-A'
    page.project.generation_metadata['speaker_recovery']={'roles':{'legacy-A':'merge:A','A':'main','B':'main'}}
    page.project.studio_state['locked_cue_ids']=['stable-4']
    page.cue_search.setText('测试字幕0')
    choose(page,monkeypatch);click_scope(page,'speaker')
    from twobyteasr.studio.presentation_scope import capture_scope
    scope=capture_scope(page)
    assert len(scope.cue_ids)==12 and scope.locked_ids==('stable-4',)
    assert 'stable-2' in scope.cue_ids and 'stable-1' not in scope.cue_ids
    assert '12' in page.style_scope_summary.text() and '锁定 1' in page.style_scope_summary.text()
    page.timeline.locked_speakers={'A'}
    locked=capture_scope(page)
    assert not locked.cue_ids and len(locked.locked_ids)==13  # includes legacy-A on the merged lane


def test_only_edited_property_expands_and_last_rapid_action_wins(page):
    select_one(page)
    before={c.id:effective_layer_style(page.project,c,'original').font_size for c in page.project.cues}
    page._set_style_color(page.style_outline_color,'#FFFF0000')
    page._set_style_color(page.style_outline_color,'#FF0066FF')
    click_scope(page,'all')
    for cue in page.project.cues:
        style=effective_layer_style(page.project,cue,'original')
        assert QColor(style.outline_color)==QColor('#0066FF')
        assert style.font_size==before[cue.id]


def test_picker_cancel_preserves_data_swatch_and_opening_value(page,monkeypatch):
    from PySide6.QtCore import QTimer
    select_one(page);page._set_style_color(page.style_outline_color,'#FF0066FF')
    before=copy.deepcopy(page.project.cues); count=page.undo_stack.count()
    original=page._create_style_color_dialog
    def create(editor):
        dialog=original(editor)
        assert dialog.selectedColor()==QColor('#0066FF')
        def cancel():
            dialog.picker.set_color(QColor('#FF0000'))
            dialog.reject()
        QTimer.singleShot(10,cancel)
        return dialog
    monkeypatch.setattr(page,'_create_style_color_dialog',create)
    page._open_style_color_dialog(page.style_outline_color)
    assert page.project.cues==before and page.undo_stack.count()==count
    assert QColor(page.style_outline_color.text())==QColor('#0066FF')
