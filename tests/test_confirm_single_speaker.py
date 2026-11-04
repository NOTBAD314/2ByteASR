import copy

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, SubtitleStyle, save_project, load_project
from twobyteasr.projects.single_speaker import confirm_single_speaker_command

APP=QApplication.instance() or QApplication([])


def fixture():
    p=SubtitleProject(media=StudioMedia('',duration_ms=10000),
        speakers=[StudioSpeaker('R001_S01',name='主播',style_id='red'),StudioSpeaker('LOCAL_S01',style_id='blue')],
        styles=[SubtitleStyle('default','Default'),SubtitleStyle('red','Red',primary_color='#ff0000'),SubtitleStyle('blue','Blue',font_size=70)],
        cues=[StudioCue('a',0,2000,'原文一',speaker_id='R001_S01',style_id='red'),
              StudioCue('b',3000,5000,'人工改过的原文',speaker_id='LOCAL_S01',style_id='blue',appearance_override={'outline_width':7})],
        generation_metadata={'translations':{'a':'translation one','b':'translation two'},
                             'speaker_recovery':{'roles':{'R001_S01':'unconfirmed','LOCAL_S01':'unconfirmed'},'raw_segments':[{'speaker':'LOCAL_S01','start':3,'end':5,'text':'原稿'}]},
                             'speaker_organization':{}})
    p.validate()
    return p


def test_explicit_confirmation_keeps_text_timing_translation_style_and_undo(tmp_path):
    p=fixture();before=copy.deepcopy(p.to_dict());stack=QUndoStack()
    command=confirm_single_speaker_command(p);stack.push(command)
    assert not command.error
    assert {c.speaker_id for c in p.cues}=={'R001_S01'} and len(p.speakers)==1
    assert p.generation_metadata['translations']==before['generation_metadata']['translations']
    for cue,old in zip(p.cues,before['cues']):
        for key in ('id','start_ms','end_ms','text','original_text','style_id','appearance_override','transform','effect_id'):
            assert getattr(cue,key)==old[key]
    saved=save_project(p,tmp_path/'one.2byteproj');reopened=load_project(saved)
    assert len(reopened.speakers)==1
    assert reopened.generation_metadata['speaker_organization']['single_speaker_confirmation']['members']==['LOCAL_S01','R001_S01']
    assert reopened.generation_metadata['speaker_organization']['single_speaker_confirmation']['cue_origins']=={'a':'R001_S01','b':'LOCAL_S01'}
    stack.undo()
    assert [c.speaker_id for c in p.cues]==['R001_S01','LOCAL_S01']
    assert p.generation_metadata.get('speaker_organization',{})==before['generation_metadata']['speaker_organization']
    stack.redo();assert len(p.speakers)==1 and not command.error


def test_unknown_target_or_single_label_cannot_make_a_second_identity():
    p=fixture()
    with pytest.raises(ValueError):confirm_single_speaker_command(p,target_id='missing')
    p.speakers=p.speakers[:1]
    with pytest.raises(ValueError):confirm_single_speaker_command(p)


def test_local_and_cloud_labels_participate_in_acoustic_evidence_without_number_equivalence():
    from twobyteasr.recognition.scoped_voiceprint import label_scope, sample_windows, proposals
    rows=[{'speaker':label,'start':offset+i*4,'end':offset+i*4+3,'text':'voice'}
          for label,offset in [('LOCAL_S01',0),('R001_S01',40),('R002_S01',80)] for i in range(4)]
    samples=sample_windows(rows)
    assert {s['label'] for s in samples}=={'LOCAL_S01','R001_S01','R002_S01'}
    assert label_scope('LOCAL_S01')!=(label_scope('R001_S01'))
    # Two aliases of the first real identity, a second distinct identity with
    # the same local number. The identity decision uses vectors, not S01.
    vectors={'0|'+label+suffix:([1.,0.] if label!='R002_S01' else [0.,1.])
             for label in ('LOCAL_S01','R001_S01','R002_S01') for suffix in ('#w','#0','#1')}
    report=proposals(rows,samples,vectors)
    assert report['automatic_groups']==[['LOCAL_S01','R001_S01']]
    assert not any('R002_S01' in g for g in report['groups'])
