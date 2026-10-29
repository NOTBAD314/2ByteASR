import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import json
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject,SubtitleStyle,StudioCue,StudioMedia,save_project,load_project
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.rendering.ass_compiler import compile_ass,compile_ass_revision
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
from twobyteasr.recognition.caption_arbitration import arbitrate,project_arbitration
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand,AdoptReviewCandidateCommand,MutationOrigin

MOSS='哦他有送球的他有送球的'
FIRE='这还有送球的还有送球的'
QWEN='啊还有送球的还有送球的'
CURRENT='哦这还有个送球的 还有送球的'


def project():
    p=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=5000),styles=[SubtitleStyle('default','default'),
        SubtitleStyle('base','base',font_family='Source Han Sans SC Heavy',font_size=180,bold=True,shadow=8),
        SubtitleStyle('derived','derived',font_size=52,position_x=960,position_y=980)],
        cues=[StudioCue('c',100,5000,'只要打PVP顺手就给他做完了',style_id='derived',base_preset_id='base',
            appearance_generation=7,appearance_override={'primary_color':'#78C9DD','shadow':6})])
    p.validate();return p


def test_revision_and_persistence_keep_complete_style_identity(tmp_path):
    p=project();store=StudioRevisionStore(p)
    cue=store.render.cues[0]
    assert cue.base_preset_id=='base' and cue.appearance_generation==7
    assert cue.to_dict()['base_preset_id']=='base'
    assert compile_ass(p)==compile_ass_revision(store.render)
    save_project(p,tmp_path/'p.2byteproj'); reopened=load_project(tmp_path/'p.2byteproj')
    assert build_visual_cue_snapshot(p,'c').resolved_caption.style_hash==build_visual_cue_snapshot(reopened,'c').resolved_caption.style_hash


def test_native_preserves_authored_font_size_and_wraps_inside_safe_width():
    p=project();before=copy.deepcopy(p)
    snapshot=build_visual_cue_snapshot(p,'c')
    caption=snapshot.resolved_caption
    assert caption.measured_width <= caption.max_width
    assert not caption.requires_split and caption.line_count==2
    assert caption.style.font_size == 180
    assert caption.style.shadow==6
    assert caption.style.font_family=='Source Han Sans SC Heavy'
    ass=compile_ass(p)
    assert 'WrapStyle: 2' in ass and r'\q2' in ass and r'\N' in ass
    assert snapshot.text.replace('\n','')==p.cues[0].text
    assert caption.style_hash in ass
    assert p.cues==before.cues and p.styles==before.styles
    temporary=caption.style;temporary.font_family='changed'
    assert caption.style.font_family!='changed'
    with pytest.raises(Exception):caption.font_loaded=False


def test_character_consensus_keeps_disputed_prefix_but_accepts_body():
    decision=arbitrate(MOSS,FIRE,QWEN)
    assert decision['selected_text']=='哦还有送球的还有送球的'
    assert decision['reason']=='FireRed+Qwen片段共识'
    assert decision['unresolved_spans']
    assert not decision['acoustic_verified']
    assert all(row['support']==2 for row in decision['accepted_spans'])


def test_unsupported_rewrite_and_numbers_never_become_facts():
    assert arbitrate(MOSS,'这里有一个球类奖励','这种奖励通过比赛即可获得')['selected_text']==MOSS
    assert arbitrate('我有三个球','我有四个球','我有四个球')['selected_text']=='我有三个球'


def test_minimum_font_overflow_splits_data_into_consecutive_cues():
    from twobyteasr.caption_style.resolved_caption_style import split_overlong_caption_commands
    app=QApplication.instance() or QApplication([])
    p=project();text='这是一段非常长的字幕内容'*20;p.cues[0].text=text
    stack=QUndoStack();split_overlong_caption_commands(p,['c'],stack)
    assert len(p.cues)>1
    assert ''.join(cue.text for cue in p.cues)==text
    assert all(a.end_ms==b.start_ms for a,b in zip(p.cues,p.cues[1:]))
    assert all(not resolve_caption_style(p.styles,p.speakers,cue,p.style_recipes).requires_split for cue in p.cues)


@pytest.mark.parametrize('adopt',[False,True])
def test_manual_text_survives_model_refresh_undo_save_reopen(tmp_path,adopt):
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=5000),cues=[StudioCue('c',0,2000,MOSS,evidence_refs=['e'])],asr_evidence={'e':{
        'moss_text':MOSS,'firered_text':FIRE,'qwen_asr_text':QWEN,'final_text':MOSS}})
    p.validate();cue=p.cues[0];stack=QUndoStack()
    command=AdoptReviewCandidateCommand(p,'c',CURRENT,'confirmed') if adopt else SetCueFieldsCommand(p,'c',{'text':CURRENT},'edit')
    stack.push(command)
    assert cue.text==CURRENT
    stack.undo();assert cue.text==MOSS
    stack.redo();assert cue.text==CURRENT
    stack.push(SetCueFieldsCommand(p,'c',{'text':MOSS},'model refresh',origin=MutationOrigin.LLM))
    assert cue.text==CURRENT
    result=project_arbitration(p,cue,apply=True)
    assert result['reason']=='用户手动确认' and cue.text==CURRENT
    save_project(p,tmp_path/'p.2byteproj');p=load_project(tmp_path/'p.2byteproj')
    assert project_arbitration(p,p.cues[0],apply=True)['selected_text']==CURRENT
    assert p.generation_metadata['caption_arbitration']['c'][-1]['candidates']
