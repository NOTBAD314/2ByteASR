"""Owned normal-app verification; screen sampling runs on the current desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scale',default='1')
    parser.add_argument('--restart',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--launcher',type=Path)
    parser.add_argument('--gui',type=Path)
    parser.add_argument('--entry-bridge',type=Path)
    args=parser.parse_args()
    if args.launcher and (not args.gui or not args.entry_bridge):
        parser.error('--launcher requires --gui and --entry-bridge')
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        parser.error('Use a new directory under this checkout/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as legacy
    from twobyteasr.projects.studio_project import (StudioCue,StudioMedia,StudioSpeaker,SubtitleProject,SubtitleStyle,save_project)
    from twobyteasr.glossary.translation_terms import normalize, KEY
    fixture=output/'fixture.2byteproj'
    if args.restart:
        shutil.copyfile(args.restart.resolve()/'saved-result.2byteproj',fixture)
        shutil.copyfile(args.restart.resolve()/'saved-result.2byteproj',output/'restart-expected.json')
        shutil.copyfile(args.restart.resolve()/'expected-colors.json',output/'expected-colors.json')
    else:
        legacy.add_learned_mapping('原文日语测试库','アリヌ','アリス',category='角色',origin='手动')
        identity=legacy.resolve_glossary_identity('原文日语测试库')
        media=output/'fixture.mp4'
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-f','lavfi','-i',
            'color=c=0x213c58:s=1280x720:r=24:d=8,drawbox=x=0:y=0:w=640:h=240:color=0xd84265:t=fill,drawbox=x=640:y=0:w=640:h=240:color=0x32b87e:t=fill',
            '-c:v','libx264','-threads','2','-preset','ultrafast','-pix_fmt','yuv420p',str(media)],check=True)
        p=SubtitleProject(StudioMedia(str(media),duration_ms=8000,width=1280,height=720),
            styles=[SubtitleStyle('default','测试字幕',font_size=82,primary_color='#FFFFFFFF',shadow=0)],
            speakers=[StudioSpeaker('S00','主播'),StudioSpeaker('S01','角色甲')],
            cues=[StudioCue('source-1',100,2700,'アリヌが来た',original_text='アリヌが来た',speaker_id='S00'),
                StudioCue('range-4e4aaa9b-236',3100,3700,'',original_text='アリスが待っている',speaker_id='S01'),
                StudioCue('source-3',4200,7000,'アリスを見た',original_text='アリスを見た',speaker_id='S00')],
            glossary_ids=[identity],generation_metadata={'language':{'code':'ja'},KEY:normalize(dict(enabled=True,
                selected_ids=['jp'],libraries=[dict(id='jp',name='日→中指定译名',source_language='ja',target_language='zh-Hans',
                terms=[dict(source='アリス',target='爱丽丝',aliases=['アリヌ'],context='')])]))})
        p.studio_state['bilingual']={'mode':'bilingual','original_scale':1,'translation_scale':1,'layout':'ink_v1'}
        save_project(p,fixture)
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='terms-color-export',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_MAIN_PYTHON=sys.executable,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,
        QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96',PYTHONUTF8='1',
        TWOBYTEASR_TERMS_REOPEN='1' if args.restart else '0', HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    for name in ('TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE','TWOBYTEASR_STARTUP_LEAVE_STUDIO',
                 'TWOBYTEASR_STARTUP_OPEN_STUDIO'):
        env.pop(name,None)
    def source_hashes():
        paths=list((ROOT/'twobyteasr').rglob('*.py'))+[Path(__file__)]
        return {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    before=source_hashes()
    (output/'source-hashes.json').write_text(json.dumps(before,indent=2),'utf8')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.launcher:
        command=[sys.executable,'-B',str(args.entry_bridge.resolve()),'--launcher',str(args.launcher.resolve()),
                 '--gui',str(args.gui.resolve()),'--output',str(output),'--profile',str(output),'--timeout','260']
    with (output/'stdout.log').open('w',encoding='utf8') as stdout,(output/'stderr.log').open('w',encoding='utf8') as stderr:
        process=subprocess.Popen(command,cwd=ROOT,env=env,
            stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        (output/'process.json').write_text(json.dumps(dict(pid=process.pid,desktop='Default',scale=args.scale)),'utf8')
        try: code=process.wait(timeout=260)
        except subprocess.TimeoutExpired:
            # Exact owned test process tree only.
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            raise
    receipt=output/'result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed':False,'error':'missing receipt'}
    result['process_exit']=code
    result['source_unchanged']=before==source_hashes()
    tested=args.gui if args.launcher else args.exe
    if tested:
        result['tested_exe']=str(tested.resolve())
        result['exe_sha256']=hashlib.sha256(tested.read_bytes()).hexdigest()
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['source_unchanged'])
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result.get('checks',[])),error=result.get('error'),output=str(output)),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
