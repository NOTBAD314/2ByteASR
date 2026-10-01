"""Reproduce saved-result delivery, edit/play/save and fresh-process reopen."""
import argparse,json,os,sys,subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use new temporary output')
    out.mkdir();report=root/'dist/reference-quality-20260916-r1/2ByteASR/reports/2026-09-16 19-26-09 一起看异环前瞻！_字幕任务报告.json'
    data=json.loads(report.read_text('utf8'));original=Path(data['result']['outputs']['project']);empty=json.loads(original.read_text('utf8'));empty['cues']=[]
    (out/'fixture.2byteproj').write_text(json.dumps(empty,ensure_ascii=False),'utf8')
    (out/'run-config.json').write_text(json.dumps({'original':str(original),'report':str(report)},ensure_ascii=False),'utf8')
    for name in ('local','roaming','temp'):(out/name).mkdir()
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'),
        QT_QPA_PLATFORM='windows',TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='recognition-delivery',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    from twobyteasr.processes import run_hidden_subprocess
    results=[]
    for phase in ('recover','reopen'):
        env['TWOBYTEASR_RECOVERY_PHASE']=phase
        with (out/(phase+'.log')).open('w',encoding='utf8') as log:
            run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150,purpose='local recognition recovery acceptance')
        result=json.loads((out/(phase+'-result.json')).read_text('utf8'));results.append(result)
        if not result['passed']:break
    (out/'result.json').write_text(json.dumps({'passed':len(results)==2 and all(r['passed'] for r in results),'processes':results},ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':len(results)==2 and all(r['passed'] for r in results),'output':str(out)}))
if __name__=='__main__':main()
