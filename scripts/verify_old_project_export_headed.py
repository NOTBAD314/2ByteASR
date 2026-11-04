"""Run old/new/offline export comparisons on a private Windows desktop."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--hold-preview',action='store_true')
    parser.add_argument('--entry-090',action='store_true',help='Execute the exact 0.9.0 release entry method on the current UI host')
    parser.add_argument('--cold-new',action='store_true')
    parser.add_argument('--offline-only',action='store_true')
    parser.add_argument('--exe',type=Path,help='Run the same audit inside this frozen GUI')
    args=parser.parse_args()
    if args.exe and args.entry_090:
        parser.error('The historical source entry replay is source-only')
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('fresh repository tmp output required')
    out.mkdir(parents=True)
    original=args.project.resolve()
    source=original.read_bytes()
    source_sha=hashlib.sha256(source).hexdigest()
    (out/'original.2byteproj').write_bytes(source)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project,SubtitleProject,StudioMedia
    media=out/'reference.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i',
        'color=c=0x223344:size=640x360:rate=25:duration=10','-f','lavfi','-i',
        'sine=frequency=440:sample_rate=48000:duration=10','-c:v','libx264','-preset','ultrafast',
        '-c:a','aac','-shortest',str(media)],check=True)
    old=load_project(out/'original.2byteproj')
    oldpath=old.media.path
    # A controlled relink copy, keeping all legacy fields/cues/recipes. This
    # does not claim to reconstruct the unavailable historical recording.
    old.media.path=str(media)
    for asset in old.media_pool:
        asset.canonical_source=str(media)
        asset.offline=False
    if old.edit_sequence.get('source_path')==oldpath:
        old.edit_sequence['source_path']=str(media)
    for segment in old.edit_sequence.get('segments',[]):
        if segment.get('source_path')==oldpath:segment['source_path']=str(media)
    raw=json.loads(source.decode('utf-8-sig'))
    raw['media']['path']=str(media)
    for asset in raw.get('media_pool',[]):
        asset.update(canonical_source=str(media),offline=False)
    if raw.get('edit_sequence',{}).get('source_path')==oldpath:
        raw['edit_sequence']['source_path']=str(media)
    for segment in raw.get('edit_sequence',{}).get('segments',[]):
        segment['source_path']=str(media)
    (out/'old.2byteproj').write_text(json.dumps(raw,ensure_ascii=False),'utf8')
    new=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=old.media.duration_ms,width=640,height=360),
        cues=copy.deepcopy(old.cues),speakers=copy.deepcopy(old.speakers),styles=copy.deepcopy(old.styles),
        style_recipes=copy.deepcopy(old.style_recipes),generation_metadata=copy.deepcopy(old.generation_metadata),
        asr_evidence=copy.deepcopy(old.asr_evidence))
    save_project(new,out/'new.2byteproj')
    offline=copy.deepcopy(raw)
    offline['media']['path']=str(out/'missing.mp4')
    for asset in offline.get('media_pool',[]):
        asset.update(canonical_source=str(out/'missing.mp4'),offline=True)
    offline.setdefault('edit_sequence',{})['source_path']=str(out/'missing.mp4')
    for segment in offline['edit_sequence'].get('segments',[]):segment['source_path']=str(out/'missing.mp4')
    (out/'offline.2byteproj').write_text(json.dumps(offline,ensure_ascii=False),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='old-project-export',TWOBYTEASR_STARTUP_PROJECT=str(out/'old.2byteproj'),
        TWOBYTEASR_INVOKER_CWD=str(ROOT),PYTHONDONTWRITEBYTECODE='1',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_SIZE='1440x900',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        OLD_EXPORT_BASELINE='1' if args.baseline else '0',
        OLD_EXPORT_COLD_NEW='1' if args.cold_new else '0',
        OLD_EXPORT_OFFLINE_ONLY='1' if args.offline_only else '0',
        OLD_EXPORT_HELD='1' if args.hold_preview else '0',
        HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='localhost,127.0.0.1')
    for key in ('QT_SCALE_FACTOR','QT_FONT_DPI'):env.pop(key,None)
    if args.cold_new:env['TWOBYTEASR_STARTUP_PROJECT']=str(out/'new.2byteproj')
    if args.offline_only:env['TWOBYTEASR_STARTUP_PROJECT']=str(out/'offline.2byteproj')
    entry=out/'entry.py'
    code='import sys,runpy\nsys.path.insert(0,'+repr(str(ROOT))+')\n'
    code+='from twobyteasr.test_isolation import install\ninstall()\n'
    if args.hold_preview:
        code+='from twobyteasr.rendering.ass_compile_actor import AssCompileActor\nAssCompileActor.submit=lambda *a:None\n'
    if args.entry_090:
        import zipfile
        with zipfile.ZipFile(ROOT/'releases/0.9.0/2ByteASR-Source-0.9.0.zip') as release:
            source_file=out/'studio_ui_090.py'
            source_file.write_bytes(release.read('twobyteasr/studio/studio_ui.py'))
        code+='import ast\nfrom twobyteasr.studio import studio_ui\n'
        code+='tree=ast.parse(open('+repr(str(source_file))+',encoding="utf-8").read())\n'
        code+='method=next(m for c in tree.body if isinstance(c,ast.ClassDef) and c.name=="SubtitleStudioPage" for m in c.body if isinstance(m,ast.FunctionDef) and m.name=="_open_render_dialog")\n'
        code+='exec(compile(ast.Module(body=[method],type_ignores=[]),"release-0.9.0-entry","exec"),studio_ui.__dict__)\nstudio_ui.SubtitleStudioPage._open_render_dialog=studio_ui._open_render_dialog\n'
    code+='runpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n'
    entry.write_text(code,'utf8')
    sys.path.insert(0,str(ROOT/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(entry)]
    exit_code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=230)
    result_path=out/'result.json'
    result=json.loads(result_path.read_text('utf8')) if result_path.exists() else dict(error='no result')
    result.update(exit_code=exit_code,source=str(original),source_sha=source_sha,
        source_unchanged=hashlib.sha256(original.read_bytes()).hexdigest()==source_sha,
        hold_preview=args.hold_preview,entry_090=args.entry_090,synthetic_media=str(media))
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(exit_code=exit_code,error=result.get('error'),checks=result.get('checks'),source_unchanged=result['source_unchanged']),ensure_ascii=False))
    return int(exit_code!=0 or not result.get('passed') or not result.get('gui_shutdown') or not result['source_unchanged'])


if __name__=='__main__':raise SystemExit(main())
