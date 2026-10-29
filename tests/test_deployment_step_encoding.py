"""The outer supervisor must emit UTF-8 even when -I ignores Python env vars."""
import json
from pathlib import Path
import subprocess
import sys


def test_isolated_deployment_supervisor_keeps_chinese_component_and_paths(tmp_path):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-I',str(root/'scripts/run_deployment_step.py'),
        '--phase','model_loading','--component','中文验证','--timeout','10',
        'validate_prepared_model.py','--root',str(tmp_path/'中文缺失目录'),'--model','moss'],
        cwd=root,capture_output=True,timeout=30)
    output=result.stdout.decode('utf8')
    assert result.returncode!=0
    events=[json.loads(line.split('] ',1)[1]) for line in output.splitlines() if line.startswith('[2BYTEASR_DEPLOY] ')]
    assert events[0]['component']=='中文验证'
    assert events[-1]['state']=='failed'
    assert '中文缺失目录' in output
