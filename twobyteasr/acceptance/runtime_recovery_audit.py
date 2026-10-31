"""Explicit, isolated frozen-entry check of startup, imports and one local VAD."""
import json,os,hashlib,subprocess,sys,traceback,time
from pathlib import Path


def main(directory):
    out=Path(directory).resolve();boundary=Path(os.environ.get('TWOBYTEASR_TEST_ROOT','')).resolve()
    if not os.environ.get('TWOBYTEASR_TEST_ROOT') or not out.is_relative_to(boundary):
        raise RuntimeError('Runtime audit requires its own isolated test root')
    out.mkdir(parents=True,exist_ok=True)
    spec=json.loads((out/'input.json').read_text('utf8'))
    from ..system.environment import deep_preflight,environment_interpreter
    from ..system.processes import sanitized_child_environment
    from ..runtime_paths import detect_install_root
    from ..diagnostics.build_identity import load_build_identity
    result=dict(passed=False,build=load_build_identity().to_dict(),frozen=bool(getattr(sys,'frozen',False)),
        executable=sys.executable,role=spec.get('role','main'))
    try:
        role=result['role']
        if spec.get('repair'):
            from ..environment_repair import repair_roles
            from dataclasses import asdict
            repaired=repair_roles([role]);result['repair']=asdict(repaired)
            if not repaired.ok:raise RuntimeError(repaired.error)
        began=time.perf_counter();probe=deep_preflight(role,use_cache=False)
        result.update(startup_and_dependencies=dict(ok=probe.ok,interpreter=probe.interpreter,problems=probe.problems,detail=probe.detail),preflight_ms=(time.perf_counter()-began)*1000)
        if spec.get('expect_failure'):
            result['passed']=not probe.ok and probe.detail.get('stage')=='python_startup'
        elif probe.ok and spec.get('wav'):
            wav=Path(spec['wav']).resolve();model=Path(spec['model']).resolve()
            if not wav.is_relative_to(boundary) or not model.is_relative_to(boundary):raise ValueError('Audit input outside isolated root')
            files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in model.rglob('*') if p.is_file() and '.cache' not in p.parts}
            root=Path(detect_install_root());worker=root/'workers/firered_vad_worker.py'
            if not worker.is_file():worker=root/'firered_vad_worker.py'
            target=out/'vad.json';command=[environment_interpreter(role),'-I','-X','utf8','-B',str(worker),
                '--wav',str(wav),'--model-dir',str(model),'--output',str(target)]
            env=sanitized_child_environment();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
            started=time.perf_counter();done=subprocess.run(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            unchanged=all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in files.items())
            result['minimal_model_task']=dict(command=command,cwd=str(root),exit_code=done.returncode,
                stdout=done.stdout.decode('utf8',errors='replace'),stderr=done.stderr.decode('utf8',errors='replace'),
                elapsed_ms=(time.perf_counter()-started)*1000,weights_unchanged=unchanged,
                output=json.loads(target.read_text('utf8')) if target.exists() else None)
            result['passed']=done.returncode==0 and target.exists() and unchanged
        else:result['passed']=probe.ok
    except Exception:result['error']=traceback.format_exc()
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if result['passed'] else 1
