"""Speaker names can have their own colour, face and weight (2026-11-20).

Game-style subtitles: the name prefix is drawn with the speaker's own look in
preview, ASS and burn-in, set in the speaker manager as one undoable step.
Unstyled names, the manuscript and the project file stay as before.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from twobyteasr.caption_style.bilingual_layout import project_display_cues
from twobyteasr.caption_style.speaker_names import name_mark
from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                                load_project, save_project)
from twobyteasr.projects.studio_revisions import SpeakerDTO
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.timeline.studio_commands import SetSpeakerCommand

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def p():
    project = SubtitleProject(media=StudioMedia(path='fixture.mp4', duration_ms=3000), cues=[
        StudioCue('a', 0, 1000, '好可怕', speaker_id='S00',
                  appearance_override={'text_marks': [{'start': 0, 'end': 1, 'italic': True}]}),
        StudioCue('b', 1200, 2200, '没事', speaker_id='S01')],
        speakers=[StudioSpeaker('S00', '兔白', name_color='#FF7AA2', name_font='SimHei', name_bold=True),
                  StudioSpeaker('S01', '路人')])
    project.validate()
    project.studio_state['show_speaker_names'] = True
    return project


def _dialogues(project):
    return [line for line in compile_ass(project).splitlines() if line.startswith('Dialogue')]


def test_name_gets_its_own_mark_and_body_marks_move_behind_it(p):
    shown = {c.id: c for c in project_display_cues(p)}
    assert shown['a'].text == '兔白：好可怕'
    assert shown['a'].appearance_override['text_marks'] == [
        {'color': '#FF7AA2', 'font': 'SimHei', 'bold': True, 'start': 0, 'end': 3},
        {'start': 3, 'end': 4, 'italic': True}]
    # An unstyled speaker keeps the earlier display copy: no marks appear.
    assert shown['b'].text == '路人：没事'
    assert not shown['b'].appearance_override.get('text_marks')
    # The manuscript is untouched.
    assert p.cues[0].text == '好可怕'
    assert p.cues[0].appearance_override['text_marks'] == [{'start': 0, 'end': 1, 'italic': True}]


def test_ass_draws_the_name_in_its_colour_and_face_then_returns_to_the_style(p):
    styled, plain = _dialogues(p)
    assert r'{\fnSimHei\b' in styled and r'\1c&HA27AFF&}兔白：' in styled
    body = styled.split('兔白：', 1)[1]
    assert body.startswith(r'{\fn\b') and '好' in body
    assert r'\fn' not in plain and '路人：没事' in plain


def test_hidden_names_draw_no_name_style(p):
    p.studio_state['show_speaker_names'] = False
    styled, _plain = _dialogues(p)
    assert '兔白' not in styled and r'\fnSimHei' not in styled


@pytest.mark.parametrize('order', ['original_first', 'translation_first'])
def test_bilingual_name_line_keeps_the_style_and_translation_marks(p, order):
    p.generation_metadata['translations'] = {'a': 'So scary'}
    p.cues[0].appearance_override['translation'] = {'text_marks': [{'start': 0, 'end': 2, 'bold': True}]}
    p.studio_state['bilingual'] = {'mode': 'bilingual', 'order': order, 'layout': 'ink_v1'}
    view = {c.id: c for c in project_display_cues(p)}
    named = view['a' if order == 'original_first' else 'a#tr']
    other = view['a#tr' if order == 'original_first' else 'a']
    marks = named.appearance_override['text_marks']
    assert named.text.startswith('兔白：')
    assert marks[0] == {'color': '#FF7AA2', 'font': 'SimHei', 'bold': True, 'start': 0, 'end': 3}
    expected_body = ({'start': 3, 'end': 4, 'italic': True} if order == 'original_first'
                     else {'start': 3, 'end': 5, 'bold': True})
    assert marks[1:] == [expected_body]
    assert not other.text.startswith('兔白')
    assert not any(m.get('font') for m in other.appearance_override.get('text_marks', []))


def test_translation_only_mode_marks_the_translated_line(p):
    p.generation_metadata['translations'] = {'a': 'So scary'}
    p.studio_state['bilingual'] = {'mode': 'translation'}
    shown = next(c for c in project_display_cues(p) if c.text.startswith('兔白：'))
    assert shown.text == '兔白：So scary'
    assert shown.appearance_override['text_marks'][0]['color'] == '#FF7AA2'


def test_project_file_writes_name_style_only_when_set(p, tmp_path):
    speakers = p.to_dict()['speakers']
    assert speakers[0]['name_color'] == '#FF7AA2' and speakers[0]['name_bold'] is True
    assert not {'name_color', 'name_font', 'name_bold'} & set(speakers[1])
    save_project(p, tmp_path / 'named.2byteproj')
    reopened = load_project(tmp_path / 'named.2byteproj')
    assert reopened.speakers == p.speakers
    # A project written by an earlier build has no such keys.
    legacy = SubtitleProject.from_dict({**p.to_dict(), 'speakers': [{'id': 'S00', 'name': '兔白'}]})
    assert legacy.speakers[0].name_color == '' and name_mark('S00', legacy.speakers) == {}


def test_fingerprint_and_metadata_records_agree_with_the_file(p, tmp_path):
    from twobyteasr.projects.studio_project import project_content_fingerprint, speaker_record
    save_project(p, tmp_path / 'fp.2byteproj')
    assert project_content_fingerprint(load_project(tmp_path / 'fp.2byteproj')) == project_content_fingerprint(p)
    assert 'name_color' not in speaker_record(p.speakers[1])
    assert speaker_record(p.speakers[0])['name_font'] == 'SimHei'


def test_revision_record_carries_the_name_style(p):
    dto = SpeakerDTO.capture(p.speakers[0])
    assert dto.to_dict()['name_font'] == 'SimHei'
    assert StudioSpeaker(**dto.to_dict()) == p.speakers[0]
    assert set(SpeakerDTO.capture(p.speakers[1]).to_dict()) == {'id', 'name', 'style_id', 'color', 'hidden', 'is_host'}


def test_set_speaker_command_changes_and_undoes_the_name_style(p):
    stack = QUndoStack()
    stack.push(SetSpeakerCommand(p, 'S01', {'name_color': '#9BE37A', 'name_font': 'KaiTi'}))
    assert name_mark('S01', p.speakers) == {'color': '#9BE37A', 'font': 'KaiTi'}
    stack.undo()
    assert name_mark('S01', p.speakers) == {}


def test_dialog_reports_only_changed_fields_and_can_follow_the_caption(p):
    from twobyteasr.studio.speaker_name_style import SpeakerNameStyleDialog
    dialog = SpeakerNameStyleDialog(p, p.speakers[1], '路人', '没事', '#e0809f', True)
    assert dialog.changes() == {} and not dialog.show_names.isVisibleTo(dialog)
    dialog.set_color('#7fd8ff')
    dialog.bold.setChecked(True)
    assert dialog.changes() == {'name_color': '#7FD8FF', 'name_bold': True}
    assert '#7FD8FF' in dialog.preview.text() and '路人：' in dialog.preview.text()
    dialog.speaker_color_button.click()
    assert dialog.changes()['name_color'] == '#E0809F'
    dialog.follow_font.setChecked(False)
    assert dialog.changes()['name_font'] == dialog.font_box.currentFont().family()
    dialog.reset()
    assert dialog.changes() == {}
    styled = SpeakerNameStyleDialog(p, p.speakers[0], '兔白', '', '', False)
    assert styled.show_names.isVisibleTo(styled) and not styled.speaker_color_button.isEnabled()
    styled.follow_color.setChecked(True)
    assert styled.changes() == {'name_color': ''}


@pytest.fixture
def manager(p):
    from twobyteasr.studio.studio_speaker_manager import SpeakerManagerDialog
    page = QWidget()
    page.project = p
    page.undo_stack = QUndoStack(page)
    page._speaker_roles_pending = False
    page._populate_speakers = lambda: None
    page._speaker_structure_changed = lambda: None
    page.selected_cue_ids = lambda: []
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    APP.processEvents()
    yield dialog
    dialog.close()
    page.deleteLater()
    APP.processEvents()


def test_manager_applies_style_and_turns_names_on_in_one_undo_step(manager, monkeypatch):
    from twobyteasr.studio import speaker_name_style
    project = manager.page.project
    project.studio_state['show_speaker_names'] = False

    def accept(dialog):
        dialog.set_color('#FFD166')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(speaker_name_style.SpeakerNameStyleDialog, 'exec', accept)
    manager._open_name_style('S01')
    assert name_mark('S01', project.speakers) == {'color': '#FFD166'}
    assert project.studio_state['show_speaker_names'] is True
    assert manager.page.undo_stack.count() == 1
    assert '#FFD166' in manager.name_preview.text() and '路人：' in manager.name_preview.text()
    manager.page.undo_stack.undo()
    assert name_mark('S01', project.speakers) == {}
    assert not project.studio_state.get('show_speaker_names')


def test_manager_cancel_changes_nothing(manager, monkeypatch):
    from twobyteasr.studio import speaker_name_style
    monkeypatch.setattr(speaker_name_style.SpeakerNameStyleDialog, 'exec', lambda dialog: QDialog.DialogCode.Rejected)
    manager._open_name_style('S00')
    assert manager.page.undo_stack.count() == 0
    assert name_mark('S00', manager.page.project.speakers)['font'] == 'SimHei'


def test_card_menu_offers_the_name_style(manager):
    from PySide6.QtWidgets import QMenu
    menu = QMenu()
    manager._card_fill_more_menu(manager.cards['S00'], menu)
    assert menu.actions()[0].text() == '名字颜色和字体…'
