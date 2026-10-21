import json
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.caption_style.bilingual_layout import project_display_cues, materialize_display_project
from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
from twobyteasr.studio.speaker_name_controls import SetSpeakerNamesCommand
from twobyteasr.caption_style.word_animation import remap_word_animation, compile_word_ass


@pytest.fixture
def p():
    app=QApplication.instance() or QApplication([])
    project=SubtitleProject(media=StudioMedia(path='fixture.mp4',duration_ms=3000), cues=[
        StudioCue('a',0,1000,'我们走吧',speaker_id='S00'),
        StudioCue('b',1200,2200,'同意',speaker_id='S01')],
        speakers=[StudioSpeaker('S00','小明'),StudioSpeaker('S01','')])
    project.studio_state['show_speaker_names']=True
    yield project


def test_name_toggle_rename_and_no_manuscript_mutation(p):
    original=[c.text for c in p.cues]
    assert [c.text for c in project_display_cues(p)] == ['小明：我们走吧','S01：同意']
    p.speakers[0].name='新名字'
    assert project_display_cues(p)[0].text == '新名字：我们走吧'
    assert [c.text for c in p.cues] == original
    stack=QUndoStack();stack.push(SetSpeakerNamesCommand(p,False))
    assert [c.text for c in project_display_cues(p)] == original
    stack.undo(); assert project_display_cues(p)[0].text.count('新名字：')==1


@pytest.mark.parametrize('order',['original_first','translation_first'])
def test_bilingual_name_once_and_materialization_idempotent(p,order):
    p.generation_metadata['translations']={'a':'Let us go'}
    p.studio_state['bilingual']={'mode':'bilingual','order':order,'layout':'ink_v1'}
    view=project_display_cues(p)
    assert sum(c.text.count('小明：') for c in view)==1
    target=next(c for c in view if c.id==('a' if order=='original_first' else 'a#tr'))
    assert target.text.startswith('小明：')
    materialized=materialize_display_project(p)
    assert sum(c.text.count('小明：') for c in project_display_cues(materialized))==1
    assert p.cues[0].text=='我们走吧'


def test_names_really_export_and_json_keeps_text_distinct(p,tmp_path):
    artifacts=export_subtitle_artifacts(p,tmp_path,'names',SubtitleExportOptions(frozenset({'srt','ass','txt','json'}),'both'))
    for artifact in artifacts:
        text=artifact.path.read_text('utf8')
        if artifact.format=='json':
            rows=json.loads(text)['cues']
            assert all(not row['text'].startswith('小明：') for row in rows)
            assert all(row['display_text'].startswith(row['speaker_name'] or row['speaker_id']) for row in rows)
        elif artifact.speaker_id in ('','S00'):
            assert '小明：' in text
    assert p.cues[0].text=='我们走吧'


def test_prefix_has_no_fake_acoustic_span_and_remap_is_repeatable():
    plan={'mode':'word_reveal','duration_ms':1000,'text':'Hello','static_prefix':'小明：',
          'spans':[{'char_start':0,'char_end':5,'start_ms':200,'end_ms':800,'spoken':'Hello'}]}
    mapped=remap_word_animation(plan,'小明：Hello')
    assert mapped['spans'][0]['char_start']==3
    assert mapped['spans'][0]['start_ms']==200
    again=remap_word_animation(mapped,'小明：Hello')
    assert again['spans']==mapped['spans']
    ass=compile_word_ass(again,'小明：Hello','#FFFFFF')
    assert ass.startswith('小明：') and 'Hello' in ass


def test_long_names_wrap_between_simultaneous_speaker_anchors(p):
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    p.cues[1].start_ms=0
    p.cues[0].transform={'position_x':520,'position_y':950}
    p.cues[1].transform={'position_x':1420,'position_y':950}
    p.speakers[1].name='另一位名字很长很长很长的讲解员'
    view=project_display_cues(p)
    captions=[resolve_caption_style(p.styles,p.speakers,c,p.style_recipes) for c in view]
    assert captions[1].line_count>1
    left,right=captions
    assert left.style.position_x+left.measured_width/2 < right.style.position_x-right.measured_width/2
    assert right.style.position_x+right.measured_width/2 < 1920
    assert p.cues[1].transform=={'position_x':1420,'position_y':950}
    assert p.cues[1].appearance_override=={}
