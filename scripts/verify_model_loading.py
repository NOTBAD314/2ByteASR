"""Verify the cumulative model/settings delivery on a private Windows desktop."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cycles',default='20');p.add_argument('--exe',type=Path);p.add_argument('--scale',default='1')
    p.add_argument('--record',action='store_true');p.add_argument('--no-trace',action='store_true')
    p.add_argument('--native-dpi',action='store_true');p.add_argument('--probe-delay',default='0')
    p.add_argument('--probe-fail',action='store_true');args=p.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use a fresh source/tmp directory')
    out.mkdir(parents=True);(out/'startup.2byteproj').write_text('{}','utf8')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96',
        TWOBYTEASR_MODEL_CYCLES=args.cycles,TWOBYTEASR_ACCEPTANCE_SCENARIO='model-loading',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'startup.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_TEST_ROOT=str(out/'profile'),LOCALAPPDATA=str(out/'profile/local'),APPDATA=str(out/'profile/roaming'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    env.update(TWOBYTEASR_MODEL_RECORD='1' if args.record else '0',
        TWOBYTEASR_WINDOW_TRACE='0' if args.no_trace else '1',
        TWOBYTEASR_MODEL_PROBE_DELAY=args.probe_delay,TWOBYTEASR_MODEL_PROBE_FAIL='1' if args.probe_fail else '0')
    if args.native_dpi:
        for key in ('QT_SCALE_FACTOR','QT_ENABLE_HIGHDPI_SCALING','QT_FONT_DPI'):
            env.pop(key,None)
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=240,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    if args.record and result.get('passed'):
        import subprocess
        for record in result.get('recordings',[]):
            folder=out/record['name'];frames=json.loads((folder/'frames.json').read_text('utf8'))
            lines=[]
            for index,row in enumerate(frames):
                lines.append("file '"+row['file']+"'")
                if index+1<len(frames):lines.append('duration '+str(max(.001,(frames[index+1]['elapsed_ms']-row['elapsed_ms'])/1000)))
            (folder/'concat.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
            subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-f','concat','-safe','0',
                '-i',str(folder/'concat.txt'),'-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-fps_mode','vfr',
                '-c:v','libx264','-preset','fast','-pix_fmt','yuv420p',str(out/(record['name']+'.mp4'))],
                check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    print(json.dumps(dict(exit_code=code,passed=result.get('passed'),checks=result.get('checks_passed'),output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1
if __name__=='__main__':raise SystemExit(main())
