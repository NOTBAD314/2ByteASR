"""Normal source/daily EXE, isolated config, QWindow events and real playback."""
import argparse,json,os,shutil,sys,time
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--recognize',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Fresh tmp directory required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.settings import DEFAULT_SETTINGS
    import copy
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['switches'].update(use_ai_grouping=False,unified_glm_processing=False,
        enable_qwen_asr_reference=False)
    settings['models'].update(primary_asr_backend='moss',firered_asr_backend='off',
        qwen_asr_backend='off',speaker_source='single')
    (out/'config/2byteasr_settings.json').write_text(json.dumps(settings,ensure_ascii=False),'utf8')
    from twobyteasr.processes import run_hidden_subprocess
    assets=root/'tmp/moss-cue-paging-20260928/assets';assets.mkdir(parents=True,exist_ok=True)
    media=assets/'playback.mp4'
    if not media.exists():
        run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
            'color=c=navy:s=640x360:r=30:d=34','-f','lavfi','-i',
            'sine=frequency=440:sample_rate=48000:duration=34','-c:v','libx264','-preset','ultrafast',
            '-g','30','-c:a','aac','-shortest',media],check=True,timeout=60,purpose='paging playback fixture')
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
    from twobyteasr.studio_edit_sequence import sequence_of
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=34000,width=640,height=360),cues=[
        StudioCue('target',10000,12000,'原文 20','S01'),StudioCue('next',14000,16000,'下一条 30','S02')])
    p.validate();p.video_tracks[0].locked=sequence_of(p).video_track_locked=False
    save_project(p,out/'fixture.2byteproj')
    from twobyteasr.studio_media_pool import create_video_track,add_video_clip
    multi=copy.deepcopy(p);create_video_track(multi,'V2')
    add_video_clip(multi,'V2',multi.video_tracks[0].clips[0].asset_id,timeline_in_ms=0)
    save_project(multi,out/'video-context.2byteproj')
    env=os.environ.copy()
    if args.recognize:
        for name in ('MOSS-Transcribe-Diarize','FireRedVAD','spkrec-ecapa-voxceleb'):
            shutil.copytree(root/'models'/name,out/'models'/name,dirs_exist_ok=True)
        for role,source in [('main',root/'.venv-main'),('moss',root/'.venv-moss')]:
            target=out/'local/2ByteASR/runtimes'/role
            run_hidden_subprocess([source/'Scripts/python.exe','-m','venv','--without-pip',target],check=True,timeout=60,
                purpose='isolated role interpreter')
            (target/'Lib/site-packages/qa-dependencies.pth').write_text(
                'import site; site.addsitedir('+repr(str(source/'Lib/site-packages'))+')\n','utf8')
            env['TWOBYTEASR_'+role.upper()+'_PYTHON']=str(target/'Scripts/python.exe')
        shutil.copy2(root/'tmp/moss-cue-paging-20260928/model/input.wav',out/'speech.wav')
        p=SubtitleProject(media=StudioMedia(str(out/'speech.wav'),duration_ms=48000),
            cues=[StudioCue('prior',0,1000,'原工程副本')])
        from twobyteasr.studio_helpers import probe_media_identity
        from twobyteasr.studio_project import hydrate_media_contract
        hydrate_media_contract(p,probe_media_identity(str(out/'speech.wav')),source_path=str(out/'speech.wav'))
        p.validate();save_project(p,out/'speech.2byteproj')
    (out/'config.json').write_text(json.dumps({'recognize':args.recognize}),'utf8')
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='moss-cue-paging',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONIOENCODING='utf8',
        PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'fixture.2byteproj')],cwd=root,env=env,output=out/'process',timeout=900)
    # The daily root launcher exits before its child. Wait for that child's
    # own receipt rather than attributing a launcher exit to GUI success.
    end=time.monotonic()+900
    while not (out/'result.json').exists() and time.monotonic()<end:time.sleep(.2)
    result=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),
        'launcher_exit':code,'identity':result['identity']},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
