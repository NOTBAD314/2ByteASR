import os,subprocess,sys


def test_new_worker_uses_frozen_models_switches_and_performance_before_core_import(tmp_path):
    code='''
import copy,json,sys
from twobyteasr.storage import settings
from twobyteasr.recognition.queue_process import install_settings_snapshot
assert 'subtitle_core' not in sys.modules
snapshot=copy.deepcopy(settings.DEFAULT_SETTINGS)
snapshot['models'].update(primary_asr_backend='api',qwen_asr_backend='off',firered_asr_backend='off')
snapshot['switches'].update(enable_ai_polish=False,use_ai_grouping=False)
snapshot['performance']['cloud_batch_workers']=2
previous=settings.load_runtime_settings
restore=install_settings_snapshot(json.dumps(snapshot))
import subtitle_core as core
assert core.PRIMARY_ASR_BACKEND=='api'
assert core.QWEN_ASR_BACKEND=='off' and core.FIRERED_ASR_BACKEND=='off'
assert core.RUNTIME_SETTINGS['switches']['enable_ai_polish'] is False
assert core.RUNTIME_SETTINGS['performance']['cloud_batch_workers']==2
assert core.RUNTIME_SETTINGS_PATH=='本次任务配置快照'
restore()
assert settings.load_runtime_settings is previous
print('snapshot-ok')
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],capture_output=True,text=True,encoding='utf-8',
        env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(tmp_path)),timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'snapshot-ok' in result.stdout
