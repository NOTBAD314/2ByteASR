"""Run the normal source/EXE entry with isolated projects, settings and Qt input."""
import argparse, json, os, shutil, sys, time
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--restart-from',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh tmp directory required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.settings import DEFAULT_SETTINGS
    (out/'config/2byteasr_settings.json').write_text(json.dumps(DEFAULT_SETTINGS,ensure_ascii=False),'utf8')
    if args.restart_from:
        shutil.copytree(args.restart_from/'qsettings',out/'qsettings',dirs_exist_ok=True)
    from PySide6.QtCore import QSettings
    settings=QSettings('2ByteASR','2ByteASR');settings.setValue('appearance/theme','grape');settings.sync()
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project
    from twobyteasr.studio_edit_sequence import sequence_of
    from twobyteasr.processes import run_hidden_subprocess
    assets=root/'tmp/cue-affix-inspector-20260929/assets';assets.mkdir(parents=True,exist_ok=True)
    media=assets/'playback.mp4'
    if not media.exists():
        run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
            'color=c=navy:s=640x360:r=30:d=24','-f','lavfi','-i',
            'sine=frequency=440:sample_rate=48000:duration=24','-c:v','libx264','-preset','ultrafast',
            '-g','30','-c:a','aac','-shortest',media],check=True,timeout=60,purpose='cue editing fixture')
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=24000,width=640,height=360),
        speakers=[StudioSpeaker('S01','同名'),StudioSpeaker('S02','同名')],cues=[
        StudioCue('a',10000,12000,'原文 20 20','S01'),StudioCue('b',15000,17000,'下一条 30','S02')])
    p.validate();p.video_tracks[0].locked=sequence_of(p).video_track_locked=False
    p.studio_state['layout']={'context_tab':1}
    save_project(p,out/'fixture.2byteproj')
    (out/'config.json').write_text(json.dumps({'restart':bool(args.restart_from)}),'utf8')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='cue-affix-checks',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        PYTHONUTF8='1',PYTHONIOENCODING='utf8',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'fixture.2byteproj')],cwd=root,env=env,output=out/'process',timeout=420)
    end=time.monotonic()+420
    while not (out/'result.json').exists() and time.monotonic()<end:time.sleep(.2)
    result=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),
        'launcher_exit':code,'identity':result['identity']},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
