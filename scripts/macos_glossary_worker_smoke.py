"""Exercise the real frozen data worker through private pipes, with no GUI."""
from pathlib import Path
import argparse, json, os, subprocess, sys, time, traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_blank_project_macos import audit_boundary, blank_environment

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='darwin':raise SystemExit('Native macOS required')
    out,invoker=audit_boundary(args.output);out.mkdir(parents=True)
    exe=args.app.resolve()/'Contents/MacOS/2ByteASR'
    assert exe.is_file()
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.glossary.terminology import TermEntry,GlossaryLibrary,GlossarySnapshot
    from twobyteasr.glossary.summary_process import evaluate
    env=blank_environment(out,invoker,out/'unused.2byteproj')
    for key in list(env):
        if key.startswith('TWOBYTEASR_ACCEPTANCE_'):env.pop(key)
    result=dict(passed=False,executable=str(exe),rows=[])
    try:
        for size in (2,900):
            terms=tuple(TermEntry(f'规范词{i:04}',aliases=(f'误听{i:04}',)) for i in range(size))
            terms+=tuple(TermEntry(name,aliases=('同一误听',)) for name in ('长离','炽霞'))
            snapshot=GlossarySnapshot((GlossaryLibrary('fixture','仅本次管道验收','1',terms),))
            payload=[snapshot.to_dict()];expected=json.loads(json.dumps(evaluate(payload),ensure_ascii=False))
            started=time.monotonic()
            process=subprocess.run([str(exe),'--glossary-summary-worker'],
                input=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=invoker,env=env,timeout=65)
            (out/f'worker-{size}.stderr.log').write_bytes(process.stderr)
            (out/f'worker-{size}.stdout.json').write_bytes(process.stdout)
            actual=json.loads(process.stdout.decode('utf-8'))
            assert process.returncode==0 and actual=={'summaries':expected}
            result['rows'].append(dict(terms=size+2,seconds=round(time.monotonic()-started,3),
                exit=process.returncode,exact_response=True,conflicts=len(expected[0]['conflicts'])))
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
