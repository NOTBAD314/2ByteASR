"""Normal source/EXE after-cleanup UI, explicit actual roots, no real writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def prepare(output,inventory_path,project,protected_files):
    output=Path(output).absolute();inventory_path=Path(inventory_path).absolute();project=Path(project).absolute()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh owned tmp output required')
    # Profile redirection precedes all imports that can initialize product state.
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output),TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.real_storage_after_audit import PATH_KEYS,small_file_fingerprint
    from twobyteasr.storage.storage_service import safe_path
    if not safe_path(output,(ROOT/'tmp',)):raise ValueError('Output ancestor contains a link')
    raw=inventory_path.read_bytes();inventory=json.loads(raw.decode('utf8'));roots=inventory['roots']
    if any(not isinstance(roots[key],str) or not Path(roots[key]).is_absolute() for key in PATH_KEYS):raise ValueError('Explicit absolute RuntimePaths inventory required')
    user=Path(roots['user_data_root'])
    for key in ('cache_root','project_root','config_root','log_root','temp_root'):
        if not Path(roots[key]).is_relative_to(user):raise ValueError('Actual root outside explicit user boundary: '+key)
    if project.suffix.lower()!='.2byteproj':raise ValueError('Explicit current project required')
    files=[user/'storage/cache.sqlite3',user/'storage/cache.sqlite3-wal',user/'storage/cache.sqlite3-shm',
        user/'storage/policy.json',user/'storage/last-cleanup.json',user/'SubtitleStudioPreview/settings.json',
        user/'SubtitleStudioPreview/library-index.json',project,*map(Path,protected_files)]
    paths=list(dict.fromkeys(str(path.absolute()) for path in files))
    if len(paths)>128:raise ValueError('Small explicit protected baseline only')
    baseline={path:small_file_fingerprint(path) for path in paths}
    if not baseline[str(user/'storage/cache.sqlite3')]['exists'] or not baseline[str(project)]['exists']:raise ValueError('Actual cache database and current project must exist')
    if sum(row.get('size',0) for row in baseline.values())>128*1024*1024:raise ValueError('Protected baseline total exceeds small-file bound')
    payload=json.loads(project.read_text('utf-8-sig'))
    if payload.get('schema_version')!=1 or not isinstance(payload.get('cues'),list):raise ValueError('Current project identity unknown')
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    seed=output/'input'/'blank-seed.2byteproj';seed.parent.mkdir(parents=True);save_project(SubtitleProject(media=StudioMedia(path='')),seed)
    manifest=dict(schema_version=1,roots={key:roots[key] for key in PATH_KEYS},inventory_sha256=hashlib.sha256(raw).hexdigest(),
        protected_before=baseline,current_project=str(project),current_project_id=payload['project_id'],current_cue_count=len(payload['cues']),
        seed=str(seed),expected_deleted_count=32720,expected_logical_removed_bytes=10204468789,historical_after_logical_bytes=7737307092,
        scope='Normal Home Settings Storage; actual scan and last receipt read-only; current project/explicit libraries fingerprinted only')
    (output/'real-storage-after-input.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    return manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--protected-file',type=Path,action='append',default=[])
    parser.add_argument('--exe',type=Path);parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();output=args.output.absolute();manifest=prepare(output,args.inventory,args.project,args.protected_file)
    if args.prepare_only:print(json.dumps(dict(prepared=True,output=str(output),protected_files=len(manifest['protected_before']))));return 0
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='real-storage-after',
        TWOBYTEASR_STARTUP_PROJECT=manifest['seed'],TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        QT_QPA_PLATFORM='windows',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO','QT_SCALE_FACTOR','QT_FONT_DPI','QT_ENABLE_HIGHDPI_SCALING','QT_SCALE_FACTOR_ROUNDING_POLICY'):
        env.pop(key,None)
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.absolute())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    process_error=None
    try:code=run_on_desktop(command,cwd=ROOT,env=env,output=output/'process',timeout=420)
    except Exception:code=None;process_error=traceback.format_exc()
    receipt=output/'real-storage-after-result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False,error='No actual after-storage receipt')
    if process_error:
        result.update(passed=False,process_error=process_error);result.setdefault('error',process_error)
    progress=output/'real-storage-after-progress.json'
    if progress.is_file():result['last_progress']=json.loads(progress.read_text('utf8'))
    result['thread_stacks']='real-storage-after-thread-stacks.log'
    from twobyteasr.acceptance.real_storage_after_audit import small_file_fingerprint
    after={}
    for path in manifest['protected_before']:
        try:after[path]=small_file_fingerprint(path)
        except (OSError,ValueError) as exc:after[path]=dict(error=str(exc))
    result.update(process_exit=code,protected_after_process=after,protected_unchanged_after_process=after==manifest['protected_before'])
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result.get('provider_calls')==0 and result['protected_unchanged_after_process'])
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],output=str(output),checks=len(result.get('checks',[])),total_logical_bytes=result.get('total_logical_bytes'),error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
