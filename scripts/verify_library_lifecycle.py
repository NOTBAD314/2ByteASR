"""Isolated library lifecycle replay; original projects/configuration are read only."""
import argparse,json,os,shutil,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',type=Path);parser.add_argument('--scenario',default='baseline')
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    assert out.is_relative_to(root/'tmp') and not out.exists()
    out.mkdir(parents=True)
    original=Path(os.environ['LOCALAPPDATA'])/'2ByteASR'
    settings_path=original/'SubtitleStudioPreview/settings.json'
    settings=json.loads(settings_path.read_text('utf-8-sig'))
    original_root=Path(settings['project_root']);dest=out/'library'
    index=json.loads(settings_path.with_name('library-index.json').read_text('utf-8-sig'))
    paths={str(p) for p in original_root.rglob('*.2byteproj') if not set(p.relative_to(original_root).parts)&{'autosave','autosaves','backup','backups','recovery','recoveries','checkpoints','tmp','temp'} and not any(x in p.name for x in ('.autosave','.previous','.backup','.checkpoint'))}
    paths.update(str(row['path']) for row in settings.get('recent_projects',[]) if isinstance(row,dict))
    mapping={};copies=[]
    for value in sorted(paths):
        p=Path(value)
        if not p.is_file():continue
        rel=p.relative_to(original_root) if p.is_relative_to(original_root) else Path('external')/str(len(mapping))/p.name
        target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        mapping[str(p)]=str(target);copies.append(dict(original=str(p),copy=str(target),size=p.stat().st_size))
    covers=set()
    for row in list(index.get('projects',{}).values())+settings.get('recent_projects',[]):
        if isinstance(row,dict) and row.get('cover_path'):covers.add(row['cover_path'])
    for value in covers:
        p=Path(value)
        if p.is_file() and p.is_relative_to(original_root):
            target=dest/p.relative_to(original_root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target);mapping[str(p)]=str(target)
    def remap(value):
        if isinstance(value,dict):return {mapping.get(k,k):remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        if isinstance(value,str):return mapping.get(value,value)
        return value
    settings=remap(settings);settings['project_root']=str(dest)
    settings.setdefault('studio_preferences',{}).update(auto_cover=False,recovery_policy='official')
    profile=out/'local/2ByteASR/SubtitleStudioPreview';profile.mkdir(parents=True)
    (profile/'settings.json').write_text(json.dumps(settings,ensure_ascii=False),'utf-8')
    (profile/'library-index.json').write_text(json.dumps(remap(index),ensure_ascii=False),'utf-8')
    (out/'inputs.json').write_text(json.dumps(copies,ensure_ascii=False,indent=2),'utf-8')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='library-lifecycle' if args.exe else 'review-editor',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_SIZE='1400x900',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        TWOBYTEASR_NAVIGATION_TRACE='1',LIBRARY_LIFECYCLE_SCENARIO=args.scenario,TWOBYTEASR_INVOKER_CWD=str(root))
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    env['TWOBYTEASR_STARTUP_PROJECT']=next(row['copy'] for row in copies if 'p-ce9127' in row['original'])
    if args.baseline:env['LIBRARY_BASELINE_SOURCE']=str(args.baseline.resolve())
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'scripts/library_lifecycle_entry.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=600)
    print(json.dumps(dict(exit_code=code,output=str(out)),ensure_ascii=False))
    return code
if __name__=='__main__':raise SystemExit(main())
