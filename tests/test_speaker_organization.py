from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker
from twobyteasr.projects.speaker_organization import *


def fixture():
    p=SubtitleProject(media=StudioMedia('demo.mp4',duration_ms=100000),
        speakers=[StudioSpeaker('A'),StudioSpeaker('B')],
        cues=[StudioCue(str(i),i*1000,i*1000+800,'人工文字'+str(i),'A' if i<12 else 'B') for i in range(15)])
    p.generation_metadata['speaker_recovery']={'raw_segments':[
        dict(start=i,end=i+.8,text='原句',speaker='A' if i<11 else 'B') for i in range(14)],
        'processing':{'mode':'ecapa'}}
    return p


def test_legacy_single_keeps_native_labels_overlaps_text_and_styles():
    p=fixture();p.cues[1].start_ms=0
    before=[(c.id,c.text,c.start_ms,c.end_ms,c.style_id) for c in p.cues]
    p.generation_metadata['speaker_recovery']['processing']['mode']='auto'
    apply_new_project_policy(p)
    assert {c.speaker_id for c in p.cues}=={'A','B'}
    assert [(c.id,c.text,c.start_ms,c.end_ms,c.style_id) for c in p.cues]==before
    assert not p.speakers[0].is_host
    assert p.generation_metadata['speaker_recovery']['cue_cache']['B'][-1]['id']=='14'
    assert p.generation_metadata['speaker_organization']['mode']=='native'
    assert all(normalized_speaker_mode(m)=='single' for m in ('auto','provider',None,''))


def test_original_utterance_threshold_deduplicates_and_survives_short_range():
    p=fixture();raw=p.generation_metadata['speaker_recovery']['raw_segments']
    raw.extend(raw[-3:])
    assert utterance_counts(raw)=={'A':11,'B':3}
    apply_new_project_policy(p)
    assert {s.id for s in p.speakers}=={'A',BACKGROUND}
    assert len(p.cues)==15
    from twobyteasr.projects.project_range import set_range
    set_range(p,12000,15000)
    loaded=SubtitleProject.from_dict(p.to_dict())
    assert {s.id for s in loaded.speakers}=={'A',BACKGROUND}


def test_batch_delete_merge_restore_and_undo_redo():
    app=QApplication.instance() or QApplication([])
    p=fixture();stack=QUndoStack();before=p.to_dict()['cues']
    stack.push(organization_command(p,{'A','B'},'merge','A'))
    assert {s.id for s in p.speakers}=={'A'} and len(p.cues)==15
    stack.undo();assert p.to_dict()['cues']==before
    stack.push(organization_command(p,{'B'},'background'))
    assert {c.speaker_id for c in p.cues[-3:]}=={BACKGROUND}
    stack.push(organization_command(p,{BACKGROUND},'main'))
    assert {c.speaker_id for c in p.cues[-3:]}=={'B'}
    stack.push(organization_command(p,{'B'},'delete'))
    assert len(p.cues)==12 and 'B' not in {s.id for s in p.speakers}
    stack.undo();assert len(p.cues)==15
    stack.redo();assert len(p.cues)==12
    loaded=SubtitleProject.from_dict(p.to_dict())
    assert len(loaded.cues)==12
    assert len(loaded.generation_metadata['speaker_organization']['deleted_cues'])==3


def test_candidate_recovery_after_unification_keeps_latest_edited_text():
    from twobyteasr.recognition.speaker_recovery import rebuild_selected_speakers
    p=fixture();state=p.generation_metadata['speaker_recovery']
    state.update(processing={'mode':'single'},allow_raw_recovery=False)
    apply_new_project_policy(p)
    p.cues[0].text='统一轨上的人工修改'
    restored=rebuild_selected_speakers(p,p.generation_metadata['speaker_recovery'],{'A':'main','B':'game'})
    assert len(restored.cues)==15
    assert restored.cues[0].text=='统一轨上的人工修改'
    assert {s.id for s in restored.speakers}=={'A',BACKGROUND}
