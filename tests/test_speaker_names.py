import copy
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioSpeaker, StudioCue, save_project, load_project
from twobyteasr.projects.speaker_names import default_names


def test_legacy_collision_does_not_merge_and_survives_reorder_reopen(tmp_path):
    p = SubtitleProject(media=StudioMedia(path=''), speakers=[StudioSpeaker('NEMO_00'), StudioSpeaker('S00'),
        StudioSpeaker('NEMO_01', name='主播', color='#112233', hidden=True)],
        cues=[StudioCue('a',0,1000,'20 20',speaker_id='NEMO_00'),
              StudioCue('b',1000,2000,'2.0',speaker_id='S00')])
    p.validate()
    assert {s.id:s.name for s in p.speakers} == {'NEMO_00':'S01','S00':'S00','NEMO_01':'主播'}
    frozen = copy.deepcopy(p.to_dict())
    p.cues[0].start_ms=3000;p.cues[0].end_ms=4000;p.cues.reverse();p.validate()
    assert p.speakers == SubtitleProject.from_dict(frozen).speakers
    save_project(p,tmp_path/'names.2byteproj');reopened=load_project(tmp_path/'names.2byteproj')
    assert reopened.speakers==p.speakers
    assert reopened.speakers[2].hidden and reopened.speakers[2].color=='#112233'
    assert {c.id:(c.speaker_id,c.text) for c in reopened.cues}=={'a':('NEMO_00','20 20'),'b':('S00','2.0')}


def test_custom_canonical_name_reserved_and_new_sessions_are_distinct():
    a=SubtitleProject(media=StudioMedia(path=''), speakers=[StudioSpeaker('NEMO_00'),StudioSpeaker('host',name='S00')])
    b=SubtitleProject(media=StudioMedia(path=''), speakers=[StudioSpeaker('NEMO_00')])
    a.validate();b.validate()
    assert a.speakers[0].name=='S01' and b.speakers[0].name=='S00'
    assert a.generation_metadata['speaker_names']['entries']['NEMO_00']['scope'] != b.generation_metadata['speaker_names']['entries']['NEMO_00']['scope']
    a.speakers[0].name='嘉宾';a.validate();assert a.speakers[0].name=='嘉宾'


def test_legacy_recovery_alias_conflict_allocates_without_merging():
    p=SubtitleProject(media=StudioMedia(path=''), speakers=[StudioSpeaker('NEMO_00',name='S00'),StudioSpeaker('S00')],
        generation_metadata={'speaker_recovery':{'display_labels':{'NEMO_00':'S00'}}})
    p.validate();assert [s.name for s in p.speakers]==['S01','S00']


def test_new_export_uses_persistent_names(tmp_path):
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    p=SubtitleProject(media=StudioMedia(path=''), speakers=[StudioSpeaker('NEMO_01')],cues=[StudioCue('a',0,1000,'20 20',speaker_id='NEMO_01')])
    p.validate()
    artifacts=export_subtitle_artifacts(p,tmp_path,'test',SubtitleExportOptions(speaker_mode='per_speaker'))
    assert len(artifacts)==1 and artifacts[0].path.name=='test_S00.srt'
    assert artifacts[0].speaker_id=='NEMO_01'
    assert '20 20' in artifacts[0].path.read_text('utf-8-sig')


def test_raw_backend_labels_never_identified_by_suffix():
    assert default_names(['NEMO_00','S00','speaker_0'])=={'S00':'S00','NEMO_00':'S01','speaker_0':'S02'}


def test_new_tasks_start_at_zero_and_unknown_is_not_a_person():
    from types import SimpleNamespace
    from twobyteasr.projects.studio_project import project_from_runtime_cues
    cues=[SimpleNamespace(start=i,end=i+1,text='20 20',speaker=raw) for i,raw in enumerate(['S01','S02','UNASSIGNED'])]
    p=project_from_runtime_cues('missing.wav',cues,generation_metadata={'speaker_recovery':{'processing':{'mode':'nemotron'}}})
    assert {s.id:s.name for s in p.speakers}=={'S01':'S00','S02':'S01','UNASSIGNED':'待确认'}
    assert [c.text for c in p.cues]==['20 20']*3


def test_restored_legacy_identity_keeps_its_allocated_name():
    p=SubtitleProject(media=StudioMedia(path=''),speakers=[StudioSpeaker('NEMO_01')])
    p.validate();p.speakers[0].name='NEMO_01';p.validate()
    assert p.speakers[0].name=='S00'
