import copy
from dataclasses import replace
import pytest

from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
from twobyteasr.caption_style.caption_layer_transform import resolved_values,transform_command
from twobyteasr.caption_style.caption_group_transform import (
    KEY,DEFAULT,GroupTransformCommand,shared_after,apply_all_command)
from twobyteasr.caption_style.bilingual_layout import project_display_cues,materialize_display_project


@pytest.fixture
def project():
    return SubtitleProject(media=StudioMedia('',duration_ms=10000,width=1920,height=1080),
        cues=[StudioCue('first',0,1000,'第一条'),StudioCue('later',5000,7000,'后一条')],
        generation_metadata={'translations':{'first':'First line','later':'Later line'}},
        studio_state={'bilingual':{'mode':'bilingual'}})


def move(project,cue,language,changes):
    command=transform_command(project,[cue.id],language,changes)
    command.redo()
    return command


def test_global_changes_all_and_bilingual_relative_position(project):
    p=project;c=p.cues[0]
    move(p,p.cues[1],'original',{'position_x':333,'position_y':444})
    before={(row.id,lang):resolved_values(p,row,lang) for row in p.cues for lang in ('original','translation')}
    source=before[(c.id,'original')]
    command=GroupTransformCommand(p,shared_after(p,c,'original',{
        'position_x':source['position_x']+100,'position_y':source['position_y']-80}))
    command.redo()
    for row in p.cues:
        for lang in ('original','translation'):
            after=resolved_values(p,row,lang);old=before[(row.id,lang)]
            assert after['position_x']==pytest.approx(old['position_x']+100)
            assert after['position_y']==pytest.approx(old['position_y']-80)
    command.undo()
    assert resolved_values(p,p.cues[1],'original')==before[('later','original')]
    command.redo()
    assert resolved_values(p,c,'original')['position_x']==source['position_x']+100


def test_local_after_global_is_inverse_and_does_not_leak(project):
    p=project;p.studio_state[KEY]=dict(dx=50,dy=-50,sx=1.5,sy=1.5)
    other=resolved_values(p,p.cues[1],'original')
    translation=resolved_values(p,p.cues[0],'translation')
    command=move(p,p.cues[0],'original',{'position_x':345,'position_y':567,'scale_x':175})
    value=resolved_values(p,p.cues[0],'original')
    assert value['position_x']==pytest.approx(345)
    assert value['position_y']==pytest.approx(567)
    assert value['scale_x']==pytest.approx(175)
    assert resolved_values(p,p.cues[1],'original')==other
    assert resolved_values(p,p.cues[0],'translation')==translation
    command.undo()
    assert resolved_values(p,p.cues[1],'original')==other


def test_apply_all_replaces_old_overrides_and_new_cue_inherits(project,tmp_path):
    p=project
    move(p,p.cues[0],'original',{'position_x':480,'position_y':650,'scale_x':135})
    move(p,p.cues[0],'translation',{'position_x':490,'position_y':570,'scale_x':135})
    move(p,p.cues[1],'original',{'position_x':100,'position_y':900})
    baseline=copy.deepcopy(p.to_dict())
    command=apply_all_command(p,p.cues[0]);command.redo()
    for language in ('original','translation'):
        a=resolved_values(p,p.cues[0],language);b=resolved_values(p,p.cues[1],language)
        for key in ('position_x','position_y','scale_x','scale_y'):assert b[key]==pytest.approx(a[key])
    command.undo()
    assert p.cues[1].transform==baseline['cues'][1]['transform']
    command.redo()
    p.cues.append(StudioCue('new',8000,9000,'新增字幕'))
    p.generation_metadata['translations']['new']='New line'
    for language in ('original','translation'):
        a=resolved_values(p,p.cues[0],language);b=resolved_values(p,p.cues[-1],language)
        for key in ('position_x','position_y','scale_x','scale_y'):assert b[key]==pytest.approx(a[key])
    saved=load_project(save_project(p,tmp_path/'中文 重开.2byteproj'))
    for language in ('original','translation'):
        assert resolved_values(saved,saved.cues[-1],language)==resolved_values(p,p.cues[-1],language)
    assert [(c.text,c.start_ms,c.end_ms,c.speaker_id,c.evidence_refs) for c in p.cues[:2]]==[
        (row['text'],row['start_ms'],row['end_ms'],row['speaker_id'],row['evidence_refs']) for row in baseline['cues']]


def test_global_scale_keeps_group_separation_and_export_matches(project):
    p=project;c=p.cues[0]
    a=resolved_values(p,c,'original');t=resolved_values(p,c,'translation')
    GroupTransformCommand(p,shared_after(p,c,'original',{'scale_x':a['scale_x']*1.3})).redo()
    b=resolved_values(p,c,'original');u=resolved_values(p,c,'translation')
    assert b['scale_x']==pytest.approx(a['scale_x']*1.3)
    assert b['scale_y']==pytest.approx(a['scale_y']*1.3)
    assert b['position_y']-u['position_y']==pytest.approx((a['position_y']-t['position_y'])*1.3)
    visible=project_display_cues(p)
    materialized=materialize_display_project(p)
    again=project_display_cues(materialized)
    assert [c.transform for c in visible]==[c.transform for c in again]


def test_speaker_avoidance_offset_survives_apply_all(project):
    p=project
    for cue,y in zip(p.cues,(900,700)):
        cue.transform={'initial_layout':{'version':1,'position_x':960,'position_y':y}}
    command=apply_all_command(p,p.cues[0]);command.redo()
    a=resolved_values(p,p.cues[0],'original');b=resolved_values(p,p.cues[1],'original')
    assert b['position_y']-a['position_y']==pytest.approx(-200)


def test_web_placement_respects_materialized_shared_transform(project):
    from twobyteasr.caption_style.web_placement import cue_placement
    p=project;c=p.cues[0]
    c.transform={'position_x':400,'position_y':700,
                 'web_placement':{'x':.3,'y':.6,'scaleX':1.2,'scaleY':.8}}
    before=cue_placement(p,project_display_cues(p)[0])
    original=resolved_values(p,c,'original')
    GroupTransformCommand(p,shared_after(p,c,'original',{'position_x':original['position_x']+90})).redo()
    after=cue_placement(p,project_display_cues(p)[0])
    assert after['x']==pytest.approx(before['x']+90/1920)
    assert after['scaleX']==before['scaleX']


def test_single_language_snapshot_consumes_shared_transform(project):
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.rendering.ass_compiler import compile_ass_revision
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    p=project;p.studio_state['bilingual']={'mode':'original'}
    p.studio_state[KEY]=dict(dx=45,dy=-55,sx=1.3,sy=1.3)
    expected=resolved_values(p,p.cues[0],'original')
    snap=build_visual_cue_snapshot(p,p.cues[0].id)
    assert snap.position_x==expected['position_x']
    assert snap.position_y==expected['position_y']
    assert snap.scale_x==pytest.approx(1.3)
    ass=compile_ass_revision(StudioRevisionStore(p).render)
    resolved=[line.split(': ',1)[1].split(',') for line in ass.splitlines() if line.startswith('Style: resolved-')]
    assert resolved and all(float(row[11])==130 and float(row[12])==130 for row in resolved)
