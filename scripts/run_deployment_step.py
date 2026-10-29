"""Bound one managed download/load child; keep live output and exit status."""
import argparse
from pathlib import Path
import subprocess
import sys

for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):
        stream.reconfigure(encoding='utf-8',errors='replace')

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from twobyteasr.system.deployment import run_command


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',required=True)
    parser.add_argument('--component',required=True)
    parser.add_argument('--timeout',required=True,type=int)
    parser.add_argument('script',choices=('run_repository_download.py','validate_prepared_model.py'))
    args,remaining=parser.parse_known_args()
    try:
        run_command([sys.executable,'-I','-X','utf8','-B',Path(__file__).parent/args.script,*remaining],
                    cwd=root,phase=args.phase,component=args.component,timeout=args.timeout)
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    except (TimeoutError,RuntimeError,OSError) as exc:
        print(str(exc),flush=True)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
