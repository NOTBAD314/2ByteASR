# SPDX-License-Identifier: GPL-3.0-only
"""Run native venv regression before expensive runtime/model preparation."""
import argparse
import importlib.util
import json
import os
import platform
import sys
import unittest
from pathlib import Path
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True,type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location("runtime_identity_tests",root/"tests/test_python_runtime_identity.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    record=dict(passed=result.wasSuccessful(),platform=sys.platform,machine=platform.machine(),
                posix_symlink_behavior_executed=os.name!="nt",tests=result.testsRun,
                failures=len(result.failures),errors=len(result.errors))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2)+"\n",encoding="utf8")
    return 0 if record["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
