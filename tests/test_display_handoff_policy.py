import copy
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.subtitle_rules.display_timing import project_display_tail_plan, protect_project_display_tails
from twobyteasr.timeline.studio_commands import RepairDisplayHandoffsCommand
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker, load_project,save_project,save_autosave


def pair():
    project=SubtitleProject(media=StudioMedia('',duration_ms=60000),speakers=[StudioSpeaker('S03',name='S02'),StudioSpeaker('S02',name='S01')],
        cues=[StudioCue('out',32560,34130,'属于天然那种倒霉体质','S03',evidence_refs=['a']),
              StudioCue('in',34033,35367,'对倒霉体质','S02',evidence_refs=['b'])])
    project.render_settings['fps']=60
    project.asr_evidence={'a':dict(moss_start=32.56,moss_end=34.13,final_timing_owner='MOSS_DEGRADED'),
                          'b':dict(moss_start=34.03,moss_end=35.16,final_timing_owner='MOSS_DEGRADED')}
    project.generation_metadata['speaker_recovery']={'display_labels':{'S02':'S01','S03':'S02'},'vad_intervals':[dict(start=29.95,end=37.52)]}
    project.validate()
    return project


def test_short_source_overlap_is_retained_for_review_without_independent_speakers():
    project=pair()
    ends,audit=project_display_tail_plan(project)
    assert ends=={}
    record=audit['pairs_before'][0]
    assert record['classification']=='source_overlap_unverified'
    assert not record['independently_verified']
    assert record['review_required']
    assert record['raw_labels']==['S03','S02'] and record['display_labels']==['S02','S01']


def test_a_single_word_end_does_not_override_unverified_source_overlap():
    project=pair()
    project.asr_evidence['a']['words']=[dict(word='体质',start_ms=33900,end_ms=34000)]
    ends,audit=project_display_tail_plan(project)
    assert ends=={}
    assert audit['pairs_before'][0]['classification']=='source_overlap_unverified'


def test_independently_verified_simultaneous_speech_remains():
    project=pair()
    for row,start,end in ((project.asr_evidence['a'],32560,34130),(project.asr_evidence['b'],34030,35160)):
        row['speaker_independent']=True
        row['independent_speech_intervals']=[dict(start_ms=start,end_ms=end)]
    ends,audit=project_display_tail_plan(project)
    assert ends=={} and audit['pairs_before'][0]['independently_verified']


def test_repair_undo_redo_save_and_autosave_keep_content_and_raw_evidence(tmp_path):
    app=QApplication.instance() or QApplication([])
    project=pair();evidence=copy.deepcopy(project.asr_evidence)
    project.asr_evidence['a']['moss_end']=34.0
    evidence=copy.deepcopy(project.asr_evidence)
    before=[(c.text,c.style_id,c.speaker_id) for c in project.cues]
    ends,audit=project_display_tail_plan(project)
    stack=QUndoStack();stack.push(RepairDisplayHandoffsCommand(project,ends,audit))
    assert project.cues[0].end_ms==34033
    stack.undo();assert project.cues[0].end_ms==34130
    stack.redo();assert project.cues[0].end_ms==34033
    assert project.asr_evidence==evidence
    assert [(c.text,c.style_id,c.speaker_id) for c in project.cues]==before
    path=save_project(project,tmp_path/'handoff.2byteproj')
    assert load_project(path).cues[0].end_ms==34033
    auto=save_autosave(project,project_path=path,base=tmp_path/'autosave')
    assert load_project(auto).cues[0].end_ms==34033
    from twobyteasr.exports.studio_subtitle_export import compile_srt
    from twobyteasr.rendering.ass_compiler import compile_ass
    assert '00:00:34,033' in compile_srt(project.cues)
    assert ',0:00:34.03,' in compile_ass(project)


def test_web_provider_hard_exits_at_end_without_400ms_tail():
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    project=pair();cue=project.cues[0]
    clock=SimpleNamespace(position=cue.end_ms-1)
    clock.presentation_position_ms=lambda:clock.position
    page=SimpleNamespace(project=project,_cue_lookup={cue.id:cue},_web_live_cue_id=cue.id,
        _cue_timing_preview=None,_playback_mode='source',timeline=SimpleNamespace(playhead_ms=0),
        _renderer_cue_at_playhead=lambda:None,
        video=SimpleNamespace(_playback_clock=clock,playback_position_snapshot=lambda:SimpleNamespace(presentation_media_ms=clock.position,paused=True,playback_rate=1)))
    provider=StudioAdvancedFlowMixin._web_live_time_provider(page)
    assert provider() is not None
    clock.position=cue.end_ms
    assert provider() is None
    clock.position=cue.end_ms+1
    assert provider() is None
