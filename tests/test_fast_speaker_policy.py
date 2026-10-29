import copy
import numpy as np
from twobyteasr.recognition.speaker_diarization import has_native_speakers, speech_windows, cluster_windows, assign_identities
from twobyteasr.recognition.speaker_evidence import scope_request_speakers, needs_moss_speakers


def test_native_zero_single_speaker_never_triggers_full_asr():
    rows=scope_request_speakers([dict(start=0,end=1,text='甲',speaker=0)],0,1)
    assert has_native_speakers(rows) and rows[0]['speaker']=='API_0'
    assert not needs_moss_speakers('auto',rows)
    assert not has_native_speakers(scope_request_speakers([dict(speaker=None)],0,1))
    assert not has_native_speakers(rows+scope_request_speakers([dict(speaker=0)],1,2))


def test_conservative_window_clustering_and_exact_words():
    windows=speech_windows([dict(start=0,end=6),dict(start=10,end=16)],16)
    vectors={'0|w':[]}
    for w in windows:
        vectors['0|'+w['speaker']]=[1.,0.] if w['start']<6 else [0.,1.]
    labelled=cluster_windows(windows,vectors)
    assert len({w['speaker'] for w in labelled})==2
    source=[dict(start=1,end=12,text='人工文字',tokens=[dict(start=1,end=2,text='人工'),dict(start=11,end=12,text='文字')],custom='kept')]
    before=copy.deepcopy(source)
    output=assign_identities(source,labelled)
    assert source==before and ''.join(r['text'] for r in output)=='人工文字'
    assert [r['tokens'][0] for r in output]==source[0]['tokens']
    assert all(r['custom']=='kept' for r in output)
    assert len({r['speaker'] for r in output})==2
    # A text/word mismatch must preserve the authored sentence instead of
    # replacing it with stale token text or invented word timing.
    source[0]['text']='人工改过的完整文字'
    output=assign_identities(source,labelled)
    assert len(output)==1 and output[0]['text']==source[0]['text']
    assert (output[0]['start'],output[0]['end'])==(1,12)
    assert output[0]['speaker']=='S00'


def test_fragment_merge_restore_exact_cues_is_idempotent(tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
    from twobyteasr.recognition.speaker_recovery import candidate_snapshot, apply_automatic_candidate_policy, rebuild_selected_speakers, recovery_preview, load_candidate_snapshot
    raw=[dict(start=i*3,end=i*3+2,text='原文',speaker='S01') for i in range(5)]
    raw.append(dict(start=17,end=17.5,text='原文不是人工文字',speaker='S08'))
    p=SubtitleProject(media=StudioMedia('',duration_ms=20000),speakers=[StudioSpeaker('S01'),StudioSpeaker('S08')],
        cues=[StudioCue('main',0,2000,'人工主字幕','S01'),StudioCue('fragment',17000,17500,'人工短句','S08')])
    p.generation_metadata['speaker_recovery']=candidate_snapshot(raw,{'S01','S08'})
    p.generation_metadata['speaker_recovery']['allow_raw_recovery']=False
    from twobyteasr.projects.speaker_organization import apply_new_project_policy
    apply_new_project_policy(p)
    assert [c.id for c in p.cues]==['main','fragment']
    assert {c.speaker_id for c in p.cues}=={'SUBTITLES'}
    state=p.generation_metadata['speaker_recovery']
    assert len(state['cue_cache']['S08'])==1
    roles={'S01':'main','S08':'merge:S01'}
    merged=rebuild_selected_speakers(p,state,roles)
    assert [(c.id,c.text,c.speaker_id) for c in merged.cues]==[('main','人工主字幕','S01'),('fragment','人工短句','S01')]
    merged.cues[1].text='合并后人工修订'
    merged=load_project(save_project(merged,tmp_path/'merged.2byteproj'))
    state=load_candidate_snapshot(merged)
    assert state['roles']==roles and recovery_preview(merged,state,roles)=={'S01':2}
    again=rebuild_selected_speakers(merged,state,roles)
    assert len(again.cues)==2 and again.cues[1].text=='合并后人工修订'
    restored=rebuild_selected_speakers(again,again.generation_metadata['speaker_recovery'],{'S01':'main','S08':'main'})
    assert restored.cues[1].speaker_id=='S08' and restored.cues[1].text=='合并后人工修订'
    assert (restored.cues[1].start_ms,restored.cues[1].end_ms)==(17000,17500)
