"""Replay a saved real I/O task through parsing, result delivery and undo/save."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1];out=a.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):p.error('Use a fresh source/tmp output')
    out.mkdir(parents=True);sys.path.insert(0,str(root))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out);os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install,install_pytest_network_guard
    install();install_pytest_network_guard()
    from twobyteasr.projects.studio_project import load_project,save_project,create_studio_outputs
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot,prepare_recognition_input
    from twobyteasr.recognition.range_recognition import payload_from_result,splice_range,history_entry
    from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
    from twobyteasr.providers.mosi_asr import result_rows
    from twobyteasr.recognition.speaker_evidence import scope_request_speakers
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    import subtitle_core
    QApplication.instance() or QApplication([])
    sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    manifest=json.loads(a.manifest.read_text('utf8'));report=json.loads(a.report.read_text('utf8'))
    source=Path(manifest['project_path']);cached=Path(report['cache']['directory'])
    inputs=[a.manifest,a.report,a.raw,source,cached/'primary_api.json',cached/'firered_primary.json',cached/'polished.json',cached/'final_timing.json']
    signatures={str(f):sha(f) for f in inputs}
    for f in (a.raw,a.raw.parent/'submission-parameters.json',a.manifest,a.report):shutil.copy2(f,out/f.name if f!=a.manifest and f!=a.raw else out/('manifest.json' if f==a.manifest else 'raw-response.json'))
    original_audio=Path(manifest['input_path']);shutil.copy2(original_audio,out/'heard.wav')
    stages=[]
    def stage(name,rows,field='speaker',clock='range-local seconds'):
        values=Counter(str(r.get(field,'unassigned')) for r in rows)
        stages.append(dict(name=name,count=len(rows),speakers=dict(values),identity_count=len(values),clock=clock))
    raw=json.loads(a.raw.read_text('utf8'));stage('provider raw',raw['segments'])
    duration=manifest['duration_ms']/1000
    parsed=scope_request_speakers(result_rows(raw,offset=0,duration=duration),0,1)
    stage('parsed now',parsed)
    for name in ('primary_api','firered_primary','polished','final_timing'):
        data=json.loads((cached/(name+'.json')).read_text('utf8'))['data']
        stage('saved '+name,data)
    primary=json.loads((cached/'primary_api.json').read_text('utf8'))['data']
    assert Counter(r['speaker'] for r in parsed)==Counter(r['speaker'] for r in primary)
    project=load_project(source)
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    sequence=sequence_of(project)
    # I/O points were set in memory for that task, after the last saved file.
    # Restore only those recorded view/range values on our private copy.
    sequence.in_point_ms=manifest['sequence'].get('in_point_ms')
    sequence.out_point_ms=manifest['sequence'].get('out_point_ms')
    before=copy.deepcopy(project.to_dict())
    start,end=manifest['project_range_ms']
    snapshot=capture_recognition_snapshot(project,str(out/'source-copy.2byteproj'),range_ms=(start,end))
    snapshot['requested_range_ms']=[sequence.in_point_ms,sequence.out_point_ms]
    assert snapshot['sequence']==manifest['sequence'],'The saved source graph changed; do not replay onto another edit'
    save_project(project,out/'source-copy.2byteproj')
    regenerated=Path(prepare_recognition_input(snapshot,out/'render-cache',root/'tools/ffmpeg/bin/ffmpeg.exe'))
    audio_identical=sha(regenerated)==sha(original_audio)
    import wave,numpy as np
    def pcm(path):
        with wave.open(str(path),'rb') as w:return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
    heard,expected=pcm(regenerated),pcm(original_audio)
    assert len(heard)==len(expected)==manifest['frames']
    assert np.array_equal(heard,expected),'Replay must hear exactly the same samples'
    cues=subtitle_core.deserialize_cues(json.loads((cached/'final_timing.json').read_text('utf8'))['data'])
    segments=subtitle_core.deserialize_segments(json.loads((cached/'firered_primary.json').read_text('utf8'))['data'])
    from twobyteasr.recognition.recognition_result import media_identity_for_task
    from twobyteasr.recognition.run_context import RuntimeContext
    identity=media_identity_for_task(str(out/'heard.wav'),RuntimeContext())
    metadata=dict(job_id='offline-replay-'+report['job_id'],media_identity=identity,models=report.get('settings',{}).get('models',{}),
        speaker_recovery=dict(raw_segments=primary,processing=dict(mode='native'),source='native'))
    outputs=create_studio_outputs(str(out/'heard.wav'),cues,txt_path='',segments=segments,generation_metadata=metadata,
        recognition_snapshot=snapshot,target_project_path=out/'recognition-results/replay/识别结果.2byteproj')
    delivered=load_project(outputs['project']);info=delivered.generation_metadata['timeline_recognition']['range']
    ids=set(info['cue_ids']);new=[vars(c) for c in delivered.cues if c.id in ids]
    stage('fixed worker delivery',new,'speaker_id','project milliseconds')
    old_path=Path(report['result']['outputs']['project']);old=load_project(old_path)
    old_info=old.generation_metadata['timeline_recognition']['range'];old_ids=set(old_info['cue_ids'])
    stage('original stored delivery',[vars(c) for c in old.cues if c.id in old_ids],'speaker_id','project milliseconds')
    plan=splice_range(project,(start,end),payload_from_result(delivered,info),foreign_speakers=False)
    stack=QUndoStack();stack.push(ReplaceRangeCuesCommand(project,plan,history_entry(plan)))
    applied=save_project(project,out/'applied.2byteproj');reopened=load_project(applied)
    stage('UI splice saved/reopened',[vars(c) for c in reopened.cues if c.id in set(plan.inserted_ids)],'speaker_id','project milliseconds')
    assert len({c['speaker_id'] for c in new})==len({r['speaker'] for r in parsed})==3
    assert all(start<=c['start_ms']<c['end_ms']<=end for c in new)
    removed=set(plan.removed_ids)
    outside=[c for c in before['cues'] if c['id'] not in removed]
    assert [vars(c) for c in reopened.cues if c.id not in set(plan.inserted_ids)]==outside
    stack.undo()
    for key in ('cues','speakers','asr_evidence','studio_state','generation_metadata'):
        assert project.to_dict()[key]==before[key],key
    stack.redo()
    after=project.to_dict()
    assert {c.speaker_id for c in project.cues if c.id in set(plan.inserted_ids)}==set(info['speaker_map'].values())
    unchanged={str(f):sha(f)==signatures[str(f)] for f in inputs};assert all(unchanged.values())
    result=dict(passed=True,new_provider_calls=0,range_ms=[start,end],stages=stages,
        original_mapping=old_info['speaker_map'],fixed_mapping=info['speaker_map'],source_inputs=signatures,
        input_unchanged=unchanged,audio_identical=audio_identical,pcm_samples=len(heard),
        outside_cues_unchanged=len(outside),removed_cues=len(removed),inserted_cues=len(new),undo_restores=True,
        redo_restores=True,save_reopen=True,request_parameters=json.loads((a.raw.parent/'submission-parameters.json').read_text('utf8')),
        limitations=['Saved raw response and real cached alignment/segmentation replay; no new provider recognition or physical listening test'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:result[k] for k in ('passed','range_ms','stages','original_mapping','fixed_mapping')},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
