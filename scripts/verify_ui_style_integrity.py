"""Normal-entry three-page appearance checks with isolated synthetic projects."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path)
    p.add_argument('--reference-root',type=Path);p.add_argument('--scale',type=float,default=1.75)
    p.add_argument('--wide',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh source/tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioMedia,StudioCue,SubtitleProject,save_project,studio_settings_path,project_library_root
    from twobyteasr.system.processes import run_hidden_subprocess
    media=out/'fixture.mp4'
    run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-f','lavfi','-i',
        'testsrc2=size=960x540:rate=12:duration=8','-f','lavfi','-i','sine=frequency=440:duration=8',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac','-shortest',str(media)],check=True,purpose='UI style fixture')
    records=[]
    library=project_library_root().resolve()
    if not library.is_relative_to(out):raise RuntimeError('Test library must be inside the isolated output')
    for index in range(2):
        folder=library/('p-style-'+str(index));folder.mkdir(parents=True);(folder/'preview').mkdir()
        pr=SubtitleProject(StudioMedia(str(media),duration_ms=8000,width=960,height=540),cues=[StudioCue('c'+str(i),i*1800,i*1800+1600,'这是第'+str(i)+'条样式检查字幕') for i in range(3)])
        save_project(pr,folder/'project.2byteproj')
        run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-i',str(media),'-frames:v','1',str(folder/'preview/project-cover.jpg')],check=True,purpose='UI style cover')
        records.append(dict(path=str(folder/'project.2byteproj'),name='样式检查工程'+str(index),cue_count=3,duration_ms=8000,cover_path='preview/project-cover.jpg',last_opened='2026-11-11T12:00:00'))
    import shutil
    shutil.copyfile(library/'p-style-0/project.2byteproj',out/'input.2byteproj')
    (out/'fixture-path.json').write_text(json.dumps(dict(project=str(library/'p-style-0/project.2byteproj'))),'utf-8')
    settings=studio_settings_path();settings.parent.mkdir(parents=True,exist_ok=True);settings.write_text(json.dumps(dict(recent_projects=records),ensure_ascii=False),'utf-8')
    import ctypes
    user=ctypes.windll.user32;user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    old=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4));native=user.GetDpiForSystem()/96;user.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(a.scale/native),PYTHONUTF8='1',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='ui-style-integrity',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'input.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='0',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if a.wide:env.update(STYLE_AUDIT_WIDTH='2100',STYLE_AUDIT_HEIGHT='1120')
    if a.reference_root:
        # Plain-Python reference only. No code is injected into a frozen EXE.
        runner=out/'reference_runner.py'
        runner.write_text('''import os,sys,importlib.util
from pathlib import Path
base=Path(os.environ['STYLE_REFERENCE_ROOT']);sys.path.insert(0,str(base))
from twobyteasr.test_isolation import install
install()
import twobyteasr.acceptance
spec=importlib.util.spec_from_file_location('twobyteasr.acceptance.ui_style_integrity_audit',os.environ['STYLE_AUDIT_FILE'])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.install()
from PySide6.QtWidgets import QApplication
from twobyteasr.app.ui import MainWindow,_register_bundled_fonts,_app_font
from twobyteasr.design.theme_manager import apply_theme
import subtitle_core
app=QApplication([]);_register_bundled_fonts();app.setFont(_app_font());apply_theme('sand',app)
w=MainWindow([],subtitle_core,object(),None);w.show();m.start(w,Path(os.environ['TWOBYTEASR_ACCEPTANCE_DIR']))
app.exec();r=__import__('json').loads((Path(os.environ['TWOBYTEASR_ACCEPTANCE_DIR'])/'result.json').read_text('utf-8'))
os._exit(0 if r['passed'] else 1)
''','utf-8')
        env.update(STYLE_REFERENCE_ROOT=str(a.reference_root.resolve()),STYLE_AUDIT_FILE=str(ROOT/'twobyteasr/acceptance/ui_style_integrity_audit.py'))
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop([sys.executable,'-B',str(runner)],cwd=ROOT,env=env,output=out/'process',timeout=300)
    else:
        from audit_launch_bridge import run_audit_on_desktop
        cmd=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
        code=run_audit_on_desktop(cmd,cwd=ROOT,env=env,output=out,timeout=360,receipt=out/'result.json')
    r=json.loads((out/'result.json').read_text('utf-8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(passed=r.get('passed'),exit=code,checks=len(r.get('checks',[])),qss_errors=len(r.get('qss_errors',[])),errors=r.get('errors')),ensure_ascii=False))
    return code or (0 if r.get('passed') else 1)
if __name__=='__main__':raise SystemExit(main())
