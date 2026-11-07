"""Normal app/private-desktop search and save acceptance; never writes input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--mpv',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--media',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('fresh source/tmp required')
    out.mkdir(parents=True)
    before=hashlib.sha256(args.project.read_bytes()).hexdigest()
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project
    from twobyteasr.subtitle_rules import subtitle_translation as st
    copied=out/'input.2byteproj';shutil.copy2(args.project,copied)
    p=load_project(copied)
    if args.media:
        from dataclasses import asdict
        from twobyteasr.media.media_service import MediaService
        from twobyteasr.timeline.studio_edit_sequence import sequence_of,persist_sequence
        metadata=MediaService().metadata(args.media)
        previous=p.media.path;current=str(args.media.resolve())
        p.media.path=current;p.media.fingerprint=metadata.fingerprint
        p.media.display_name=args.media.name
        p.media.width=metadata.width;p.media.height=metadata.height
        for asset in p.media_pool:
            if asset.canonical_source==previous:
                asset.canonical_source=current;asset.fingerprint=metadata.fingerprint
                asset.video_metadata=asdict(metadata);asset.offline=False
        sequence=sequence_of(p);sequence.source_path=current
        for segment in sequence.segments:
            if segment.source_path==previous:segment.source_path=current
        persist_sequence(p)
    for cue in [p.cues[400],p.cues[2777]]:
        record=st.records_of(p)[cue.id]
        record.update(st._record(record['text']+' 诊断替换标记',cue.text,origin='manual',target=record.get('target','zh-Hans')))
        p.generation_metadata['translations'][cue.id]=record['text']
    save_project(p,copied)
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-search-lag',
        TWOBYTEASR_STARTUP_PROJECT=str(copied),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_MAIN_PYTHON=sys.executable,TWOBYTEASR_MPV=str(args.mpv.resolve()),QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TWOBYTEASR_INVOKER_CWD=str(ROOT))
    from isolated_windows_desktop import run_on_desktop
    command=[sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.baseline:
        baseline=args.baseline.resolve()
        modules={'.'.join(p.relative_to(baseline).with_suffix('').parts):str(p)
            for p in (baseline/'twobyteasr').rglob('*.py') if 'acceptance' not in p.parts
            and (ROOT/p.relative_to(baseline)).is_file() and (ROOT/p.relative_to(baseline)).read_bytes()!=p.read_bytes()}
        entry=out/'baseline_entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            +'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
        command=[sys.executable,'-B',str(entry)]
        (out/'baseline-modules.json').write_text(json.dumps(modules,indent=2),'utf8')
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=300)
    path=out/'result.json';result=json.loads(path.read_text('utf8')) if path.exists() else {'passed':False,'error':'missing receipt'}
    result.update(process_exit=code,input_sha256=before,input_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==before)
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['input_unchanged'])
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','error','process_exit','gui_shutdown','input_unchanged')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
