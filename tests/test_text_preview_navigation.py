"""Preview selection may navigate without blessing an unrelated mutation."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio.studio_cue_controller import StudioCueController
from twobyteasr.studio.studio_find_replace import FindReplaceDialog
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.projects.studio_session import StudioSession

APP = QApplication.instance() or QApplication([])


class Page(QWidget):
    def __init__(self):
        super().__init__()
        project = SubtitleProject(media=StudioMedia(path='isolated.mp4'), cues=[
            StudioCue('a', 100, 1000, 'AliasAlpha上场了', speaker_id='S01'),
            StudioCue('b', 1200, 2200, 'AliasAlpha走了', speaker_id='S01')])
        project.validate()
        self.session = StudioSession(project=project, selected_cue_id='a', undo_stack=QUndoStack(self))
        self.controller = SimpleNamespace(session=self.session, _select_cue_ui=self._select)

    def _select(self, cue_id, **_kwargs):
        self.session.selected_cue_id = cue_id

    def select_cue(self, cue_id):
        # Exercise the production selection transaction without constructing
        # playback/model widgets that this text-dialog test does not need.
        StudioCueController._select_cue_transaction(self.controller, cue_id)

    def selected_cue_ids(self):
        return [self.session.selected_cue_id]

    def _changed(self):
        pass

    def _show_studio_hint(self, _text):
        pass


def preview(page):
    dialog = FindReplaceDialog(page)
    dialog.find_edit.setText('AliasAlpha')
    dialog.replace_edit.setText('Canonical7')
    dialog._search_timer.stop()
    dialog._do_preview()
    dialog.show()
    APP.processEvents()
    assert dialog.preview.count() == 2
    return dialog


def click_second(dialog):
    item = dialog.preview.item(1)
    dialog.preview.scrollToItem(item)
    APP.processEvents()
    rect = dialog.preview.visualItemRect(item)
    QTest.mouseClick(dialog.preview.viewport(), Qt.LeftButton, pos=rect.center())
    APP.processEvents()


def test_mouse_preview_navigation_then_checked_apply_is_one_undo():
    page = Page()
    dialog = preview(page)
    project = page.session.project
    before = [(cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues]
    try:
        binding_revision = dialog._preview_binding.revision
        click_second(dialog)
        assert page.session.selected_cue_id == 'b'
        assert state_for(project).revision > binding_revision
        assert dialog._preview_binding.matches(project)
        QTest.keyClick(dialog.preview, Qt.Key_Space)
        assert dialog.preview.item(0).checkState() == Qt.Checked
        assert dialog.preview.item(1).checkState() == Qt.Unchecked
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert [cue.text for cue in project.cues] == ['Canonical7上场了', 'AliasAlpha走了']
        assert [(cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues] == [row[1:] for row in before]
        assert page.session.undo_stack.count() == 1
        page.session.undo_stack.undo()
        assert [(cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues] == before
        page.session.undo_stack.redo()
        assert [cue.text for cue in project.cues] == ['Canonical7上场了', 'AliasAlpha走了']
    finally:
        dialog.close()
        page.close()


@pytest.mark.parametrize('domain', [DirtyDomain.CUE_CONTENT, DirtyDomain.CUE_TIMING,
    DirtyDomain.MEDIA_POOL, DirtyDomain.PROJECT_METADATA])
def test_external_revision_before_preview_navigation_stays_rejected(domain):
    page = Page()
    dialog = preview(page)
    project = page.session.project
    try:
        # The revision fence also rejects metadata/media/timing changes even
        # when a fixture's visible text remains identical.
        with state_for(project).transaction(project, action_id='external_edit', dirty=domain):
            pass
        click_second(dialog)
        assert not dialog._preview_binding.matches(project)
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert [cue.text for cue in project.cues] == ['AliasAlpha上场了', 'AliasAlpha走了']
        assert page.session.undo_stack.count() == 0
        assert '工程或文字已改变' in dialog.status_label.text()
    finally:
        dialog.close()
        page.close()


def test_selection_callback_that_changes_text_is_not_rebound():
    page = Page()
    dialog = preview(page)
    project = page.session.project
    try:
        def mutate_while_selecting(cue_id):
            with state_for(project).transaction(project, action_id='select_cue',
                    dirty=DirtyDomain.CUE_SELECTION | DirtyDomain.CUE_CONTENT,
                    affected_cue_ids=('a', 'b'), selection_after=cue_id):
                project.cues[0].text = '人工修改'
                page.session.selected_cue_id = cue_id
        page.select_cue = mutate_while_selecting
        click_second(dialog)
        assert not dialog._preview_binding.matches(project)
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert project.cues[0].text == '人工修改'
        assert page.session.undo_stack.count() == 0
    finally:
        dialog.close()
        page.close()


@pytest.mark.parametrize('mutation', ['manual_position', 'keyframe', 'style', 'ai_timing'])
def test_actual_edit_data_during_selection_cannot_be_blessed(mutation):
    page = Page()
    dialog = preview(page)
    project = page.session.project
    try:
        def edit_data(cue_id):
            with state_for(project).transaction(project, action_id='select_cue',
                    dirty=DirtyDomain.CUE_SELECTION | DirtyDomain.TRANSFORM,
                    affected_cue_ids=('a', 'b'), selection_after=cue_id):
                if mutation == 'manual_position':
                    project.cues[0].transform['position'] = {'x': 260, 'y': 170}
                elif mutation == 'keyframe':
                    project.cues[0].transform['keyframes'] = [{'time_ms': 100, 'x': 260}]
                elif mutation == 'style':
                    project.styles[0].font_size += 3
                else:
                    project.cues[0].end_ms += 35
                page.session.selected_cue_id = cue_id
        page.select_cue = edit_data
        click_second(dialog)
        assert not dialog._preview_binding.matches(project)
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert project.cues[0].text == 'AliasAlpha上场了'
        assert page.session.undo_stack.count() == 0
        assert '工程或文字已改变' in dialog.status_label.text()
    finally:
        dialog.close()
        page.close()


@pytest.mark.parametrize('operation', ['manual_position', 'ai_timing'])
def test_production_edit_command_before_navigation_remains_protected(operation):
    import copy
    from twobyteasr.timeline.studio_commands import BatchTimingCommand, SetCueFieldsCommand
    page = Page()
    dialog = preview(page)
    project = page.session.project
    try:
        if operation == 'manual_position':
            command = SetCueFieldsCommand(project, 'a', {'transform': {
                'position': {'x': 260, 'y': 170},
                'keyframes': [{'time_ms': 100, 'x': 260}]}},
                text='手动字幕位置', changed=page._changed)
        else:
            command = BatchTimingCommand(project, {'a': (135, 1035)},
                'AI 时间建议', page._changed)
        page.session.undo_stack.push(command)
        edited = copy.deepcopy(project.cues)
        click_second(dialog)
        assert not dialog._preview_binding.matches(project)
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert project.cues == edited
        assert page.session.undo_stack.count() == 1
        assert '工程或文字已改变' in dialog.status_label.text()
    finally:
        dialog.close()
        page.close()
