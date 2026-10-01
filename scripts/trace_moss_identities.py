"""Replay a real short worker artifact; clearly separated from new inference."""
import argparse,copy,hashlib,json,os,sys,types,zipfile
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('tmp required')
    out.mkdir(parents=True,exist_ok=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    import subtitle_core as legacy
    from moss_firered_pipeline import _merge_moss_chunks,build_moss_host_primary_segments
    from twobyteasr.speaker_recovery import candidate_snapshot
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project,load_project
    from twobyteasr.speaker_organization import apply_new_project_policy
    from twobyteasr.speaker_evidence import label_summary
    from twobyteasr.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    raw=json.loads(args.worker.read_text('utf8'));events=[]
    legacy.record_run_event=lambda kind,**fields:events.append(dict(kind=kind,**fields))
    canonical=_merge_moss_chunks(copy.deepcopy(raw),48.,legacy)
    from twobyteasr.runtime import RuntimeContext
    ctx=RuntimeContext(speaker_source='moss',expected_speakers=0,dialogue_coverage_mode='all_dialogue')
    # Use raw speech spans here, without claiming a VAD inference. The normal
    # task audit separately executes the real production VAD and finalizer.
    vad=[dict(start=r['start'],end=r['end']) for r in canonical['segments']]
    segments=build_moss_host_primary_segments(copy.deepcopy(canonical),[],vad,48.,legacy,runtime_context=ctx)
    p=SubtitleProject(media=StudioMedia(str(args.worker.parent/'input.wav'),duration_ms=48000),
        cues=[StudioCue(str(i),round(s.start*1000),round(s.end*1000),s.text,s.speaker) for i,s in enumerate(segments)],
        speakers=[StudioSpeaker(s) for s in sorted({s.speaker for s in segments})])
    evidence=candidate_snapshot(canonical['segments'],source='moss');evidence['processing']={'mode':'moss'}
    p.generation_metadata['speaker_recovery']=evidence
    baseline=copy.deepcopy(p)
    with zipfile.ZipFile(root/'tmp/moss-cue-paging-20260928/entry-worktree.zip') as z:
        module=types.ModuleType('twobyteasr.speaker_organization_before');module.__package__='twobyteasr'
        exec(compile(z.read('twobyteasr/speaker_organization.py'),'<entry-baseline>','exec'),module.__dict__)
    module.apply_new_project_policy(baseline)
    apply_new_project_policy(p);save_project(p,out/'fixed.2byteproj');save_project(baseline,out/'before.2byteproj')
    loaded=load_project(out/'fixed.2byteproj')
    exports=export_subtitle_artifacts(loaded,out/'export','moss',SubtitleExportOptions(speaker_mode='per_speaker'))
    result=dict(source='saved real MOSS worker replay; VAD spans supplied from parsed rows',
        artifact_sha256=hashlib.sha256(args.worker.read_bytes()).hexdigest(),
        parsed=[label_summary(c['segments']) for c in raw['chunks']],merged=label_summary(canonical['segments']),
        primary=label_summary(segments),baseline_project=sorted({c.speaker_id for c in baseline.cues}),
        fixed_project=sorted({c.speaker_id for c in loaded.cues}),exports=[str(x.path) for x in exports],events=events)
    (out/'trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='events'},ensure_ascii=False))


if __name__=='__main__':main()
