"""Render handoff evidence through a chosen product checkout."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--no-masks',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh source/tmp output.')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    sys.path.insert(0,str(args.source_root.resolve()))
    from twobyteasr.test_isolation import install,install_pytest_network_guard
    install();install_pytest_network_guard()
    spec=importlib.util.spec_from_file_location('continuity_render',ROOT/'twobyteasr/acceptance/continuity_render_audit.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.run(args.project.resolve(),output,args.source_root.resolve(),masks=not args.no_masks)
    print(json.dumps(dict(passed=result['passed'],checks=result['checks'],core_offsets=result['core_offsets']),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
