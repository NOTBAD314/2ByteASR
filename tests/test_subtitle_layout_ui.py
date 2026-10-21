"""Offline Qt review uses the real scoped layout and presentation undo command."""
from copy import deepcopy
from dataclasses import asdict

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.studio.subtitle_layout_ui import SubtitleLayoutPreview, open_layout_preview


@pytest.fixture(scope='module', autouse=True)
def app():
    value = QApplication.instance() or QApplication([])
    yield value


class Page(QWidget):
    def __init__(self, project):
        super().__init__()
        self.project = project
        self.undo_stack = QUndoStack(self)
        self.changes, self.hints = 0, []

    def _changed(self):self.changes += 1
    def _show_studio_hint(self, message):self.hints.append(message)


@pytest.fixture
def page():
    project = SubtitleProject(media=StudioMedia('missing-fixture.mp4', duration_ms=5000),
        styles=[SubtitleStyle('default', 'Default', font_size=64, outline_width=4, shadow=0)],
        cues=[StudioCue('a', 0, 2000, '先说一句'), StudioCue('b', 500, 2500, '另一句插话'),
              StudioCue('manual', 200, 2600, '手动字幕', transform={'position_x':800, 'position_y':900}),
              StudioCue('animated', 3000, 4000, '有关键帧', transform={
                  'keyframes':{'position_y':[{'time_ms':0, 'value':888}, {'time_ms':100, 'value':800}]}})])
    value = Page(project)
    yield value
    value.close()


def test_preview_and_cancel_never_modify_project_or_undo(page):
    before = deepcopy(asdict(page.project))
    dialog = open_layout_preview(page, [cue.id for cue in page.project.cues])
    assert dialog is page._subtitle_layout_preview
    assert dialog.table.rowCount() == 4 and dialog.command is not None
    assert dialog.table.item(2, 4).text() == '手动位置'
    assert '已保护' in dialog.table.item(2, 5).text()
    assert dialog.table.item(3, 4).text() == '关键帧'
    assert asdict(page.project) == before and page.undo_stack.count() == page.changes == 0
    dialog.reset_manual.setChecked(True)
    assert asdict(page.project) == before and page.undo_stack.count() == 0
    dialog.reject()
    assert asdict(page.project) == before and page.undo_stack.count() == 0


def test_apply_is_one_real_undo_edit_and_default_scope_protects_authored_cues(page):
    before = deepcopy(page.project.cues)
    dialog = SubtitleLayoutPreview(page, [cue.id for cue in page.project.cues])
    assert set(dialog.command.after) == {'a', 'b'}
    reviewed = {key:deepcopy(value[4]) for key, value in dialog.command.after.items()}
    assert dialog.apply()
    assert page.undo_stack.count() == 1 and page.changes == 1
    assert {cue.id:cue.transform for cue in page.project.cues[:2]} == reviewed
    assert page.project.cues[2:] == before[2:]
    page.undo_stack.undo()
    assert [cue.transform for cue in page.project.cues] == [cue.transform for cue in before]
    assert [(cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in page.project.cues] == [
        (cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in before]


def test_explicit_manual_reset_keeps_keyframes_and_unselected_cues(page):
    cue = page.project.cues[2]
    cue.transform['keyframes'] = deepcopy(page.project.cues[3].transform['keyframes'])
    before = deepcopy(page.project.cues)
    dialog = SubtitleLayoutPreview(page, ['manual'])
    assert not dialog.apply_button.isEnabled() and dialog.command is None
    dialog.reset_manual.setChecked(True)
    assert dialog.apply_button.isEnabled() and set(dialog.command.after) == {'manual'}
    assert dialog.apply()
    assert 'position_x' not in cue.transform and 'position_y' not in cue.transform
    assert cue.transform['keyframes'] == before[2].transform['keyframes']
    assert 'initial_layout' in cue.transform
    assert all(current == old for current, old in zip(page.project.cues, before) if current.id != 'manual')
    page.undo_stack.undo()
    assert cue.transform == before[2].transform


@pytest.mark.parametrize('change', ['project', 'cue_object', 'time', 'transform', 'style', 'project_id'])
def test_stale_preview_refuses_one_commit_after_model_change(page, change):
    dialog = SubtitleLayoutPreview(page, ['a', 'b'])
    if change == 'project':page.project = deepcopy(page.project)
    elif change == 'cue_object':page.project.cues[0] = deepcopy(page.project.cues[0])
    elif change == 'time':page.project.cues[0].end_ms += 40
    elif change == 'transform':page.project.cues[0].transform['position_x'] = 100
    elif change == 'style':page.project.styles[0].font_size += 2
    else:page.project.project_id = 'different-project'
    changed = deepcopy(asdict(page.project))
    assert dialog.apply() is False
    assert page.hints and page.undo_stack.count() == page.changes == 0
    assert asdict(page.project) == changed


def test_unknown_scope_has_no_action_and_empty_project_is_safe(page):
    dialog = SubtitleLayoutPreview(page, ['missing-cue'])
    assert dialog.table.rowCount() == 0 and not dialog.apply_button.isEnabled()
    page.project = None
    assert open_layout_preview(page, ['a']) is None
