"""Run the normal application and private desktop against owned fixtures."""
from pathlib import Path
import argparse,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--long',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():parser.error('fresh output under tmp required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe';media=out/'fixture.mp4'
    command=[str(ffmpeg),'-v','error','-y','-f','lavfi','-i','testsrc2=size=960x540:rate=30:duration=24',
             '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=24',
             '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)]
    subprocess.run(command,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=24000,width=960,height=540),
        speakers=[StudioSpeaker('S0','甲'),StudioSpeaker('S1','乙')],
        cues=[StudioCue('head',0,2000,'开头','S0'),StudioCue('a',10000,13000,'当前主动字幕','S0'),
              StudioCue('x',11000,15000,'另一个人物同时说话','S1'),StudioCue('b',13000,16000,'相邻字幕','S0'),
              StudioCue('tail',21000,24000,'结尾','S0')])
    project.render_settings['fps']=30;project.studio_state['bilingual_mode']=True
    for cue in project.cues:set_manual(project,cue.id,'Translation '+cue.id)
    fixture=out/'fixture.2byteproj';save_project(project,fixture)
    if args.long:
        longmedia=out/'six-hours.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=2:duration=21600',
            '-c:v','libx264','-preset','ultrafast','-g','12','-pix_fmt','yuv420p','-an',str(longmedia)],
            check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        from copy import deepcopy
        longproject=SubtitleProject(media=StudioMedia(str(longmedia),duration_ms=21600000,width=320,height=180),
            cues=deepcopy(project.cues)+[StudioCue(f'long-{i}',30000+i*3000,32000+i*3000,f'长工程字幕 {i}','S0') for i in range(7000)],
            speakers=deepcopy(project.speakers),styles=deepcopy(project.styles))
        longproject.render_settings['fps']=2;longproject.studio_state['bilingual_mode']=True
        save_project(longproject,out/'long.2byteproj')
    env=os.environ.copy();env.update(QT_QPA_PLATFORM='windows',TWOBYTEASR_ACCEPTANCE_SCENARIO='subtitle-navigation',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    for name in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(name,None)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-X','utf8',str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=360,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    (out/'process-exit.json').write_text(json.dumps(dict(exit_code=code),indent=2),'utf8')
    print(json.dumps(dict(output=str(out),exit=code,passed=result.get('passed'),checks=len(result.get('checks',[])),error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1
if __name__=='__main__':raise SystemExit(main())
