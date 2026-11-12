"""Screenshot-derived short handoffs and deterministic local slot leases."""
from copy import deepcopy
from types import SimpleNamespace
import json
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

import subtitle_core as core
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project,load_project
from twobyteasr.subtitle_rules.display_continuity import project_handoff_plan,MAX_GAP_MS
from twobyteasr.subtitle_rules.display_timing import short_gap_bridges,protect_project_display_tails
from twobyteasr.timeline.studio_commands import BridgeShortGapsCommand
from twobyteasr.caption_style.collision_layout import project_layout_schedule,ProjectCollisionLayout


@pytest.fixture(scope='module',autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project(gap=100,other=87133):
    return SubtitleProject(media=StudioMedia('',duration_ms=100000),
        speakers=[StudioSpeaker('API_S02'),StudioSpeaker('API_S03')],cues=[
        StudioCue('yes',86717,87133,'是的',speaker_id='API_S02'),
        StudioCue('good',other,87450,'好',speaker_id='API_S03'),
        StudioCue('next',87133+gap,88833,'八连击的月光合奏',speaker_id='API_S02')])


@pytest.mark.parametrize('gap',[1,17,100,200])
@pytest.mark.parametrize('other',[86000,87000,87133,87134])
def test_micro_handoff_keeps_other_speaker_and_never_anticipates_next(gap,other):
    p=project(gap,other)
    before=deepcopy(p.cues)
    ends=project_handoff_plan(p)
    assert ends['yes']==before[2].start_ms
    command=BridgeShortGapsCommand(p,ends);command.redo()
    assert p.cues[0].end_ms==p.cues[2].start_ms
    assert [(c.start_ms,c.text,c.speaker_id) for c in p.cues]==[(c.start_ms,c.text,c.speaker_id) for c in before]
    assert p.cues[1].end_ms==before[1].end_ms
    assert project_handoff_plan(p)=={}


@pytest.mark.parametrize('gap',[201,499,500,501,4000])
def test_larger_pause_needs_positive_continuation_evidence(gap):
    p=project(gap)
    assert 'yes' not in project_handoff_plan(p)
    p.generation_metadata['segmentation_source_spans']={'cues':{
        'yes':{'parts':[{'source_id':1,'char_start':0,'char_end':2}]},
        'next':{'parts':[{'source_id':1,'char_start':2,'char_end':10}]}}}
    assert ('yes' in project_handoff_plan(p))==(gap<=MAX_GAP_MS)


@pytest.mark.parametrize('flag',['protected_end','no_display_extension','display_break','timing_locked'])
def test_explicit_boundaries_are_protected(flag):
    p=project();p.cues[0].transform[flag]=True
    assert 'yes' not in project_handoff_plan(p)


def test_hidden_deleted_or_different_clip_successor_releases_hold():
    p=project();p.cues[2].transform['source_clip_id']='second';p.cues[0].transform['source_clip_id']='first'
    assert 'yes' not in project_handoff_plan(p)
    p.cues=p.cues[:2]
    plan=project_layout_schedule(p)
    assert plan['good'][0][2]==0
    p=project();p.studio_state['subtitle_track_visibility']={'API_S02':False}
    assert project_handoff_plan(p)=={}


def test_screenshot_three_chain_position_and_safe_solo_compaction():
    p=project()
    p.cues.append(StudioCue('later',89000,90000,'下一个单人段',speaker_id='API_S03'))
    plan=project_layout_schedule(p)
    assert plan['yes'][0][2]==plan['next'][0][2]==0
    assert plan['good'][0][2]>0
    assert plan['later'][0][2]==0
    # Applying the actual text hold uses the identical slot plan.
    BridgeShortGapsCommand(p,project_handoff_plan(p)).redo()
    assert project_layout_schedule(p)=={key:[(c.start_ms,c.end_ms,plan[key][0][2])] for c in p.cues for key in [c.id]}


def test_preview_seeks_and_export_use_same_plan():
    p=project();expected=project_layout_schedule(p);cache=ProjectCollisionLayout()
    revision=SimpleNamespace(mapping_revision=1,visual_revision=1)
    for key in ['next','yes','good','next','good']:
        cue=next(c for c in p.cues if c.id==key)
        assert cache.for_cues(p,[cue],revision).offsets[key]==expected[key][0][2]


def test_local_height_envelope_and_locked_position():
    p=project();p.cues[2].text='八连击的\n月光合奏';p.cues[2].transform['font_size']=90
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.caption_style.collision_layout import visual_bounds,shifted_snapshot
    plan=project_layout_schedule(p)
    boxes={c.id:visual_bounds(shifted_snapshot(build_visual_cue_snapshot(p,c.id),plan[c.id][0][2])) for c in p.cues}
    assert plan['yes'][0][2]==plan['next'][0][2]
    assert not boxes['good'].intersects(boxes['next'])
    p.cues[1].transform['position_locked']=True
    assert project_layout_schedule(p)['good'][0][2]==0


def test_undo_save_evidence_and_tail_protection_do_not_reclassify_speech(tmp_path):
    p=project();p.asr_evidence={'yes':{'speaker_id':'API_S02','acoustic_start_ms':86717,'acoustic_end_ms':87133}}
    p.cues[0].evidence_refs=['yes'];p.validate();evidence=deepcopy(p.asr_evidence);before=deepcopy(p.cues)
    stack=QUndoStack();stack.push(BridgeShortGapsCommand(p,project_handoff_plan(p)))
    protected=protect_project_display_tails(p)
    assert p.cues[0].end_ms==87233
    assert any(pair['classification']=='bounded_display_hold' for pair in protected)
    assert p.asr_evidence==evidence
    save_project(p,tmp_path/'saved.2byteproj');loaded=load_project(tmp_path/'saved.2byteproj')
    assert loaded.cues==p.cues and loaded.asr_evidence==evidence
    stack.undo();assert p.cues==before
    stack.redo();assert p.cues[0].end_ms==87233
    p.cues[0].end_ms=87180
    assert 'yes' not in project_handoff_plan(p)


@pytest.mark.parametrize('fps',[23.976,29.97,59.94,60])
def test_runtime_bridge_is_one_shared_frame_and_survives_cache(fps):
    from twobyteasr.subtitle_rules.timing import relock_display_timing
    cues=[core.SubtitleCue(1,86.717,87.133,'是的',speaker='A'),
          core.SubtitleCue(2,87.133,87.450,'好',speaker='B'),
          core.SubtitleCue(3,87.233,88.833,'八连击的月光合奏',speaker='A')]
    relock_display_timing(cues,100,fps)
    assert cues[0].end==cues[2].start
    assert round(cues[0].end*fps)==round(cues[2].start*fps)
    assert cues[2].start>=87.233
    again=core.deserialize_cues(core.serialize_cues(cues));relock_display_timing(again,100,fps)
    assert core.serialize_cues(again)==core.serialize_cues(cues)


def test_selection_cancel_and_maximum_duration():
    p=project();assert project_handoff_plan(p,['good'])=={}
    assert project_handoff_plan(p,progress=lambda *_:False) is None
    p.cues[0].start_ms=82183
    assert 'yes' not in project_handoff_plan(p)


def test_persisted_manual_boundary_matches_preview_and_export():
    p=project()
    p.studio_state['caption_timeline']={'instances':{'yes':{'protected_end':True}}}
    assert 'yes' not in project_handoff_plan(p)
    expected=project_layout_schedule(p)
    assert expected['good'][0][2]==0 and expected['next'][0][2]>0
    revision=SimpleNamespace(mapping_revision=1,visual_revision=1)
    actual=ProjectCollisionLayout().for_cues(p,[p.cues[2]],revision)
    assert actual.offsets['next']==expected['next'][0][2]


def test_hidden_successor_and_source_jump_are_not_leases():
    p=project();p.cues[2].transform['hidden']=True
    assert 'yes' not in project_handoff_plan(p)
    assert project_layout_schedule(p)['good'][0][2]==0
    from twobyteasr.rendering.caption_scene import active_cues
    page=SimpleNamespace(project=p,session=SimpleNamespace(runtime=None),
                         timeline=SimpleNamespace(hidden_speakers=set()),_subtitle_track_visibility={})
    assert [c.id for c in active_cues(page,87250)]==['good']
    assert 'next' not in {c.id for c in p.visible_cues()}
    p=project()
    p.studio_state['caption_timeline']={'instances':{
        'yes':{'source_path':'same.mp4','source_end_ms':1000},
        'next':{'source_path':'same.mp4','source_start_ms':50000}}}
    assert 'yes' not in project_handoff_plan(p)
    assert project_layout_schedule(p)['good'][0][2]==0


def test_headless_worker_and_gui_choose_identical_geometry(tmp_path):
    p=project();p.cues[2].text='八连击的\n月光合奏'
    path=save_project(p,tmp_path/'clock.2byteproj')
    expected=project_layout_schedule(p)
    code=('import json,sys;from twobyteasr.projects.studio_project import load_project;'
          'from twobyteasr.caption_style.collision_layout import project_layout_schedule;'
          'print(json.dumps(project_layout_schedule(load_project(sys.argv[1]))))')
    child=subprocess.run([sys.executable,'-X','utf8','-c',code,str(path)],check=True,capture_output=True,text=True)
    actual=json.loads(child.stdout.strip().splitlines()[-1])
    assert actual=={key:[list(span) for span in value] for key,value in expected.items()}


def test_native_subset_keeps_full_project_slot_context():
    import re
    from twobyteasr.rendering.ass_compiler import compile_ass
    p=project();BridgeShortGapsCommand(p,project_handoff_plan(p)).redo()
    whole=[line for line in compile_ass(p).splitlines() if line.startswith('Dialogue:') and line.endswith('好')]
    subset=[line for line in compile_ass(p,cues=[p.cues[1]]).splitlines() if line.startswith('Dialogue:')]
    positions=lambda lines:[re.findall(r'\\pos\(([^)]+)\)',line) for line in lines]
    assert positions(subset)==positions(whole)


def test_ten_thousand_solo_cues_do_not_replay_the_whole_chain_on_seek(monkeypatch):
    from twobyteasr.caption_style import visual_snapshot
    p=project()
    p.cues=[StudioCue(str(index),index*1000,(index+1)*1000,'连续单人字幕',speaker_id='API_S02') for index in range(10000)]
    def unexpected(*args,**kwargs):
        raise AssertionError('solo seek measured unrelated historical captions')
    monkeypatch.setattr(visual_snapshot,'build_visual_cue_snapshot',unexpected)
    revision=SimpleNamespace(mapping_revision=1,visual_revision=1)
    assert ProjectCollisionLayout().for_cues(p,[p.cues[-1]],revision).offsets=={'9999':0.}


def test_single_focused_reply_keeps_whole_project_bridge_action():
    from twobyteasr.studio.display_handoff_ui import bridge_short_gaps
    p=project();p.render_settings['_cue_domain']='timeline'
    page=SimpleNamespace(project=p,selected_cue_ids=lambda:['good'],undo_stack=QUndoStack(),
                         _changed=lambda *a,**k:None,_show_studio_hint=lambda _:None)
    assert bridge_short_gaps(page)==1
    assert p.cues[0].end_ms==87233


def test_locked_speaker_track_is_not_retimed():
    p=project();p.studio_state['locked_speakers']=['API_S02']
    assert 'yes' not in project_handoff_plan(p)


def test_mixed_renderer_split_retains_native_obstacle_context(monkeypatch):
    from twobyteasr.exports.mixed_caption_export import split_mixed_captions
    from twobyteasr.rendering import advanced_renderer
    from twobyteasr.exports import static_caption_contract
    p=project()
    p.cues=[StudioCue('native',0,5000,'原生字幕',speaker_id='API_S02'),
            StudioCue('static',1000,2000,'静态高级字幕',speaker_id='API_S03'),
            StudioCue('moving',6000,7000,'后续动态字幕',speaker_id='API_S03')]
    monkeypatch.setattr(advanced_renderer,'split_renderer_cues',lambda _:([p.cues[0]],p.cues[1:]))
    monkeypatch.setattr(static_caption_contract,'shared_static_cue',lambda _,cue:cue.id=='static')
    whole=project_layout_schedule(p)
    still,moving=split_mixed_captions(p)
    assert whole['static'][0][2]>0
    assert project_layout_schedule(still)['static']==whole['static']
    assert project_layout_schedule(moving)['native']==whole['native']


def test_static_export_excludes_hidden_instances():
    from twobyteasr.exports.static_caption_export import static_graph_project
    p=project()
    p.style_recipes['default']={'name':'Static','engine':'remotion','motion':{'mode':'none'}}
    assert static_graph_project(p)
    for cue in p.cues:
        cue.transform['hidden']=True
    assert not static_graph_project(p)
