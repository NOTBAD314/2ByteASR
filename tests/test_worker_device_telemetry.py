import pytest

from twobyteasr.recognition.asr import _reported_worker_device


@pytest.mark.parametrize('text,expected',[
    ('[2BYTEASR_FUNASR] {"event":"loading","device":"cpu"}', 'cpu'),
    ('[2BYTEASR_FIRERED_AED] {"event":"device","kind":"mps"}\n'
     '[2BYTEASR_FIRERED_AED] {"event":"model_dtype","device":"mps:0"}', 'mps:0'),
    ('[2BYTEASR_QWEN] {"event":"loading","device":"cuda:0"}', 'cuda:0'),
    ('[2BYTEASR_FUNASR] {"event":"completed"}', 'unknown'),
    ('[2BYTEASR_FUNASR] not-json\n[2BYTEASR_FUNASR] []', 'unknown'),
])
def test_device_requires_actual_worker_report(text,expected):
    assert _reported_worker_device(text)==expected


def test_cpu_only_readiness_does_not_label_available_mps_as_execution():
    import sys
    from scripts.validate_prepared_model import _DEVICE_PROBE
    import json
    import subprocess
    program="""
import sys,types,os
sys.platform='darwin'
os.environ['2BYTEASR_CPU_ONLY']='1'
torch=types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda:False),
    backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda:True)))
sys.modules['torch']=torch
"""+_DEVICE_PROBE
    result=subprocess.run([sys.executable,'-I','-c',program],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'cuda':False,'apple_gpu':False,'device':'cpu'}
