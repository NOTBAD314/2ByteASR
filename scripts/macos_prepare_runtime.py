# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a new isolated arm64 CPU model venv without touching other roles."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import venv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime",type=Path,required=True)
    parser.add_argument("--receipt",type=Path,required=True)
    parser.add_argument("--register",action="store_true")
    args=parser.parse_args(argv)
    if sys.platform!="darwin" or platform.machine()!="arm64" or sys.version_info[:2]!=(3,10):
        raise SystemExit("Use native Apple Silicon Python 3.10; this is not a cross-build.")
    target=args.runtime.expanduser().resolve()
    if target.exists(): raise SystemExit("Runtime target exists; choose a new path. No existing runtime was changed.")
    venv.EnvBuilder(with_pip=True).create(target)
    interpreter=target/"bin/python"
    report=args.receipt.with_suffix(".pip-install.json")
    report.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(interpreter),"-m","pip","install","--report",str(report),"-r",str(ROOT/"packaging/macos/requirements-cpu.txt")],check=True)
    subprocess.run([str(interpreter),'-m','pip','check'],check=True)
    from scripts.macos_dependency_contract import verify_native_wheels
    native_lock=ROOT/'packaging/macos/native-dependencies.lock.json'
    verified=verify_native_wheels(json.loads(report.read_text('utf8')),json.loads(native_lock.read_text('utf8')))
    wheel_proof={'native_wheels_verified':verified,'lock_sha256':hashlib.sha256(native_lock.read_bytes()).hexdigest(),
                 'install_report':str(report.resolve())}
    (target/'mac-native-wheels.json').write_text(json.dumps(wheel_proof,indent=2)+'\n',encoding='utf8')
    probe=subprocess.run([str(interpreter),"-c","import torch,funasr; assert (torch.ones(1)+1).item()==2; print(torch.__version__)"],check=True,text=True,capture_output=True)
    installed=subprocess.run([str(interpreter),"-m","pip","freeze","--all"],check=True,text=True,capture_output=True).stdout
    payload={"platform":"darwin","architecture":"arm64","python":str(interpreter),
             "torch":probe.stdout.strip(),"cpu_tensor_probe_passed":True,"model_inference_verified":False,
             "resolved_packages":installed.splitlines(),"install_report":str(report),"registered":False}
    payload['native_wheels_verified']=verified
    if args.register:
        from twobyteasr.platform_macos import configure_macos_paths
        configure_macos_paths(ROOT)
        from twobyteasr.runtime_registry import register_runtime
        register_runtime("main",str(interpreter),source="macos-cpu-experimental")
        payload["registered"]=True
    args.receipt.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CPU runtime prepared:",interpreter)
    return 0


if __name__=="__main__": raise SystemExit(main())
