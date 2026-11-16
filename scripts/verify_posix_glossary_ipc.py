"""Same delayed reader and large request against exact R5 and fixed transport."""
from pathlib import Path
import argparse,importlib.util,json,subprocess,sys,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    out=a.output.resolve();assert 'tmp' in out.parts and not out.exists();out.mkdir(parents=True)
    assert sys.platform=='darwin'
    from twobyteasr.glossary import summary_process as fixed
    from twobyteasr.system import processes
    original=subprocess.check_output(['git','show','95fff3eeb5337f160a1fa6f5c2cd493e2b0c8ccd:twobyteasr/glossary/summary_process.py'],cwd=ROOT)
    old=out/'old-summary.py';old.write_bytes(original)
    spec=importlib.util.spec_from_file_location('twobyteasr.glossary._r5_transport',old)
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    child=('import time,json,sys;time.sleep(.4);data=json.load(sys.stdin);'
           'print(json.dumps({"summaries":[{"received":len(data[0]["blob"])}]}))')
    def launch(_command,*,purpose,own_process_tree,**kwargs):
        return subprocess.Popen([sys.executable,'-X','utf8','-c',child],**kwargs)
    processes.popen_hidden_subprocess=launch
    class Snapshot:
        def to_dict(self):return {'blob':'字'*(512*1024)}
    rows=[];checks=0
    for name,module in [('legacy',legacy),('fixed',fixed)]:
        cancel=threading.Event();timer=threading.Timer(1.2,cancel.set);timer.start();start=time.monotonic()
        complete=False
        try:complete=module.summarize([Snapshot()],cancel)==[{'received':512*1024}]
        except RuntimeError:pass
        finally:timer.cancel();timer.join(timeout=.2)
        good=complete if name=='fixed' else not complete
        assert good
        checks+=1;rows.append(dict(stage=name+(':complete' if complete else ':expected-stop'),seconds=round(time.monotonic()-start,4)))
    (out/'phase-events.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    (out/'phase-result.json').write_text(json.dumps(dict(passed=True,checks=checks)),encoding='utf-8')
    print(json.dumps(dict(passed=True,checks=checks)),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
