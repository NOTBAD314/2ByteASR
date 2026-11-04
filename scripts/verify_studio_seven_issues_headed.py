"""Launch the normal desktop entry with owned copies and isolated configuration."""
import argparse,copy,json,os,shutil,sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seek-cache',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp') or not args.seek_cache.resolve().is_relative_to(root/'tmp'):
        raise ValueError('Fresh owned tmp output and owned seek cache required')
    out.mkdir(parents=True);project=out/'current-194.2byteproj';shutil.copy2(args.project,project)
    current=json.loads(project.read_text('utf-8'));gap=copy.deepcopy(current)
    # Explicit reconstruction, not an undiscovered user autosave: retained original
    # opening clip + 23ms gap + current saved body matches the logged 458655ms state.
    first=copy.deepcopy(gap['video_tracks'][0]['clips'][0]);first.update(id='diagnostic-original-opening',source_in_ms=3088977,
        source_out_ms=3092366,timeline_in_ms=0,timeline_out_ms=3389)
    for kind in ['video_tracks','audio_tracks']:
        for track in gap[kind]:
            for clip in track['clips']:
                clip['timeline_in_ms']+=3412;clip['timeline_out_ms']+=3412
    gap['video_tracks'][0]['clips'].insert(0,first)
    audio=copy.deepcopy(gap['audio_tracks'][0]['clips'][0]);audio.update(id='diagnostic-original-audio',
        linked_video_clip_id=first['id'],source_in_ms=3088977,source_out_ms=3092366,timeline_in_ms=0,timeline_out_ms=3389)
    gap['audio_tracks'][0]['clips'].insert(0,audio)
    source_path=current['media']['path']
    gap['edit_sequence']['segments']=[dict(id=c['id'],source_path=next(a.get('canonical_source') or a.get('source_path') or a.get('path',source_path)
        for a in gap['media_pool'] if a.get('asset_id',a.get('id'))==c['asset_id']),**{k:c[k] for k in ['source_in_ms','source_out_ms','timeline_in_ms','timeline_out_ms']})
        for c in gap['video_tracks'][0]['clips']]
    for cue in gap['cues']:cue['start_ms']+=3412;cue['end_ms']+=3412
    gap['studio_state']['playhead_ms']=0;gap['studio_state']['project_name']='诊断副本 · 23ms 空隙重建'
    gapfile=out/'gap-reconstruction.2byteproj';gapfile.write_text(json.dumps(gap,ensure_ascii=False,indent=2),'utf-8')
    variants=[]
    for gap_ms in (0,1,17,23,500,2000):
        variant=copy.deepcopy(gap);delta=gap_ms-23
        for kind in ('video_tracks','audio_tracks'):
            for track in variant[kind]:
                for clip in track['clips']:
                    if not clip['id'].startswith('diagnostic-original'):
                        clip['timeline_in_ms']+=delta;clip['timeline_out_ms']+=delta
        for segment in variant['edit_sequence']['segments'][1:]:
            segment['timeline_in_ms']+=delta;segment['timeline_out_ms']+=delta
        for cue in variant['cues']:cue['start_ms']+=delta;cue['end_ms']+=delta
        path=out/f'gap-{gap_ms}ms.2byteproj';path.write_text(json.dumps(variant,ensure_ascii=False),'utf-8')
        variants.append(dict(path=str(path),duration=gap_ms,start=3389,end=3389+gap_ms))
    raw=json.loads(Path(current['report_path']).read_text('utf-8'))
    events=[e for e in raw['events'] if e.get('stage')=='grouped' and e.get('event') in {'asr_provider_request','cloud_batch_completed'}]
    spec=dict(project=str(project),gap_project=str(gapfile),gap_start=3389,gap_end=3412,gap_variants=variants,
        gap_origin='explicit reconstruction; current saved project has zero gap; original user log matches duration',
        grouping_node=[{k:v for k,v in e.items() if k in ['event','batch_index','batch_id','result_origin','fallback_reason','http_status','model','validator_result','source_ids']} for e in events])
    (out/'input.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),'utf-8')
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='seven-issues',
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_SEEK_CACHE_ROOT=str(args.seek_cache.resolve()),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.exe and args.exe.resolve()==root/'2ByteASR.exe':
        command=[sys.executable,str(root/'scripts/verify_desktop_entry_bridge.py'),str(out),json.dumps(command)]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=900)
    result=json.loads((out/'result.json').read_text('utf-8')) if (out/'result.json').exists() else dict(passed=False)
    result['process_exit']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(output=str(out),checks=[(x['name'],x['passed']) for x in result.get('checks',[])],error=result.get('error'),exit=code),ensure_ascii=False))
    return 0 if result.get('passed') and code==0 and result.get('gui_shutdown') else 1


if __name__=='__main__':raise SystemExit(main())
