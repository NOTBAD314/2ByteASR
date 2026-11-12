"""Known user failures: content retention, explicit text layer and group identity."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker
from twobyteasr.subtitle_rules.review_suggestions import model_suggestions

@pytest.mark.parametrize('text,other',[
 ('えーナノちゃんお弁当なんだ','えナノちゃんお弁当なん'),
 ('ナノちゃんごめん今日はパパッと食べちゃおうか','なのちゃんごめん今日はパパと食べちゃおうか'),
 ('そうじゃなくてそうじゃなくて','そうじゃなくて'),
 ('I did not say that','I did say that'),
 ('这有十五个人','这有个人'),
])
def test_reference_absence_never_becomes_deletion_or_kana_name_patch(text,other):
    rows=model_suggestions(text,[(other,('reference ASR',))])
    assert not rows

@pytest.mark.parametrize('selection',['timeline','canvas'])
@pytest.mark.parametrize('layer',['original','translation'])
def test_e_uses_explicit_layer_and_submission_is_bound(tmp_path,monkeypatch,layer,selection):
    app,p=_page(tmp_path,monkeypatch,[StudioCue('a',0,5000,'そうじゃなくてそうじゃなくて'),StudioCue('b',5100,8000,'次の台詞')])
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual,translation_view
    set_manual(p.project,'a','不是那个 不是那个',target='zh-Hans')
    p.timeline.set_subtitle_layer('translation' if layer=='original' else 'original')
    p.select_cue('a')
    if selection=='canvas':p._remember_canvas_edit_target('a',layer)
    else:p.timeline.set_subtitle_layer(layer)
    assert p.timeline.active_subtitle_layer==layer
    p._edit_subtitle_at_playhead()
    assert p._caption_draft.target.cue_id=='a' and p._caption_draft.target.layer==layer
    assert p.subtitle_edit_input.toPlainText()==('そうじゃなくてそうじゃなくて' if layer=='original' else '不是那个 不是那个')
    p.subtitle_edit_input.setPlainText('edited')
    p.select_cue('b')
    p._commit_canvas_inline_edit()
    assert (p.project.cues[0].text if layer=='original' else translation_view(p.project)['a']['text'])=='edited'
    assert p.project.cues[1].text=='次の台詞'
    p.undo_stack.undo()
    assert p.project.cues[0].text=='そうじゃなくてそうじゃなくて'
    p.undo_stack.redo()
    assert (p.project.cues[0].text if layer=='original' else translation_view(p.project)['a']['text'])=='edited'
    p.close_page();p.deleteLater();app.processEvents()

def test_group_eye_never_hides_members_and_locate_exposes_actual_row(tmp_path,monkeypatch):
    cues=[StudioCue('a',0,5000,'A',speaker_id='S00'),StudioCue('b',0,5000,'B',speaker_id='S01'),StudioCue('c',0,5000,'C',speaker_id='S02')]
    app,p=_page(tmp_path,monkeypatch,cues)
    from twobyteasr.recognition.speaker_roles import decide
    p.project.speakers=[StudioSpeaker('S00'),StudioSpeaker('S01'),StudioSpeaker('S02')]
    p.project.studio_state['speaker_roles']=decide(p.project,manual={'S00':'main','S01':'secondary','S02':'secondary'},expanded=False)
    p.timeline.set_project(p.project)
    from twobyteasr.studio.studio_timeline import button_rect
    row=next(rect for kind,key,rect in p.timeline._row_layout()[3] if kind=='group')
    before=set(p.timeline.hidden_speakers)
    p.timeline._group_header_clicked(button_rect('subtitle','visibility',row).center(),row)
    assert p.timeline.hidden_speakers==before and p.timeline._group_expanded
    p.timeline.set_group_expanded(False)
    p.timeline.reveal_cue('b')
    assert p.timeline._group_expanded
    assert p.timeline._track_layout()[0]['S01']!=p.timeline._track_layout()[0]['S02']
    p.close_page();p.deleteLater();app.processEvents()
