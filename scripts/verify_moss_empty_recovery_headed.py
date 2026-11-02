"""Offline normal-window replay, through either source or an isolated EXE."""
from pathlib import Path
import argparse,copy,json,os,sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--audio-only', action='store_true')
    parser.add_argument('--manual-first',action='store_true')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--reopen',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('Choose a fresh directory under source/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import save_project,load_project
    if args.reopen:
        source=args.reopen.resolve()
        if not source.is_relative_to(root/'tmp'):raise ValueError('Reopen only an owned tmp fixture')
        project=load_project(source)
        save_project(project,out/'fixture.2byteproj')
    else:
        import pytest
        from tests.test_moss_recovery_pipeline import run_fixture,legacy_quarantine,DE
        import subprocess
        source=out/('input.wav' if args.audio_only else 'input.mp4')
        if args.audio_only:
            import numpy as np,wave
            # A small nonzero PCM tone makes decode/sink telemetry inspectable.
            audio=(np.sin(np.arange(round(370.361*16000))*2*np.pi*440/16000)*200).astype('<i2')
            with wave.open(str(source),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(audio.tobytes())
        else:
            subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-hide_banner','-loglevel','error','-y',
            '-f','lavfi','-i','color=c=0x30404d:s=320x180:r=10:d=370.361',
            '-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','370.361',
            '-c:v','libx264','-preset','ultrafast','-crf','35','-c:a','aac',str(source)],
            check=True,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        with pytest.MonkeyPatch.context() as boundary:
            project,report,_=run_fixture(out,boundary,DE,source_path=source)
        if not args.manual_first:project,report=legacy_quarantine(project,report)
        (out/'task-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        from twobyteasr.projects.studio_project import save_project
        project.report_path=str(out/'task-report.json')
        save_project(project,out/'fixture.2byteproj')
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,project_settings_path
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(primary_asr_backend='api',qwen_asr_backend='off',firered_asr_backend='off',
        qwen_asr_api_provider='mosi_moss_pro',qwen_asr_api_protocol='mosi_transcriptions',
        qwen_asr_api_model='moss-transcribe-diarize-pro',qwen_asr_api_url='https://api.mosi.cn/v1',speaker_source='native')
    settings['switches'].update(enable_ai_polish=False,use_ai_grouping=False,unified_glm_processing=False,
        enable_qwen_asr_reference=False,enable_firered_boundary_refinement=False)
    cfg=project_settings_path();cfg.parent.mkdir(parents=True,exist_ok=True);cfg.write_text(json.dumps(settings),'utf8')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out/'profile'),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='moss-empty-recovery',TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',
        PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        TWOBYTEASR_STREAM_AUDIO='0',TWOBYTEASR_MOSS_AUDIO_ONLY='1' if args.audio_only else '0',
        TWOBYTEASR_MOSS_VERIFY_REOPEN='1' if args.reopen else '0',
        TWOBYTEASR_MOSS_MANUAL_FIRST='1' if args.manual_first else '0')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=230)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    result['process_exit']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result.get('passed'),checks=len(result.get('checks',[])),phase=result.get('phase'),
        process_exit=code,error=result.get('error','')[-1500:]),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') else 1

if __name__=='__main__':raise SystemExit(main())
