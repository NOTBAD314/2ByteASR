"""Normal MainWindow verification with a retained real project and isolated profile."""
from pathlib import Path
import argparse,json,os,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path);p.add_argument('--scale',default='1')
    p.add_argument('--theme',default='grape')
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh output under source/tmp required')
    out.mkdir(parents=True);shutil.copy2(a.project,out/'real.2byteproj')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,SubtitleProject,StudioCue,StudioSpeaker,save_project
    from twobyteasr.recognition.speaker_roles import KEY,POLICY
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual
    real=load_project(out/'real.2byteproj')
    fixture=SubtitleProject(media=real.media,speakers=[StudioSpeaker(f'S{i}') for i in range(33)],
        cues=[StudioCue('head',5964,7549,'定位片头','S0'),StudioCue('middle',600000,604000,'定位中段','S0'),
              StudioCue('tail',1419000,1420096,'定位片尾','S0')]+[
            StudioCue(f'sub-{i}',30000+i*4000,32000+i*4000,f'次要角色{i}','S'+str(i)) for i in range(1,33)])
    fixture.render_settings['fps']=30;fixture.studio_state['bilingual_mode']=True
    fixture.studio_state[KEY]={'policy':POLICY,'grouped':True,'cap_chosen':True,'cap':1,'expanded':True,
        'auto':{f'S{i}':'secondary' if i else 'main' for i in range(33)}}
    for c in fixture.cues:set_manual(fixture,c.id,'译文 '+c.text)
    save_project(fixture,out/'fixture.2byteproj')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=a.scale,QT_FONT_DPI='96',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='japanese-workspace',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_THEME=a.theme,
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    command=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=300,receipt=out/'result.json')
    print(json.dumps(dict(code=code,output=str(out)),ensure_ascii=False));return code
if __name__=='__main__':raise SystemExit(main())
