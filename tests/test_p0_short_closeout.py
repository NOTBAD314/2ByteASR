"""Short, provider-free regressions for the four September 9 P0 defects."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave
import numpy as np
import pytest

@pytest.fixture(autouse=True)
def isolated_cli_logs(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setenv('APPDATA',str(tmp_path/'roaming'))

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def test_separate_mix_retains_longer_lane_after_short_input_eof(tmp_path):
    from twobyteasr.playback.audio_engine import build_audio_mix_command
    from twobyteasr.system.processes import run_hidden_subprocess
    layers=[]
    for index,seconds in enumerate((1,3)):
        path=tmp_path/f'lane{index}.wav'
        samples=(np.sin(np.arange(48000*seconds)*2*np.pi*(440+index*330)/48000)*4000).astype('<i2')
        with wave.open(str(path),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000);stream.writeframes(samples.tobytes())
        layers.append(dict(source_path=str(path),source_ms=0,source_out_ms=seconds*1000))
    command=build_audio_mix_command(Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe',layers,pcm_format='f32le',separate=True)
    result=run_hidden_subprocess(command,purpose='unequal audio lane regression',timeout=10,capture_output=True,check=True)
    pcm=np.frombuffer(result.stdout,dtype='<f4').reshape(-1,4)
    assert len(pcm)==144000
    assert np.max(np.abs(pcm[-4800:,:2]))==0
    assert np.sqrt(np.mean(pcm[-4800:,2:]**2))>.03


def test_cli_drains_large_stderr_and_finishes_json_without_eof(tmp_path):
    from twobyteasr.providers.ai_providers import GrokCLIProvider
    code=tmp_path/'stream.py'
    code.write_text("import json,sys,time\nsys.stderr.write('x'*200000);sys.stderr.flush()\n"
        "value=json.dumps({'brief':{'safe':True},'concepts':[1,2,3]})\n"
        "sys.stdout.write(json.dumps({'event':'step_update','step_update':{'step_type':'agent_response','text_delta':value}}));sys.stdout.flush()\n"
        "time.sleep(20)\n",encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable)
    started=time.monotonic()
    value=provider._run_cli_stream([sys.executable,str(code)],purpose='fixture streaming request',timeout=4,
        complete_json_early=True,on_stream_event=lambda *_:None)
    assert json.loads(value)['brief']['safe']
    assert time.monotonic()-started<4
    assert provider.last_timings['response_complete']


def test_cli_does_not_accept_truncated_json(tmp_path):
    from twobyteasr.providers.ai_providers import GrokCLIProvider,AIProviderError
    code=tmp_path/'truncated.py'
    code.write_text("import json,sys,time\nprint(json.dumps({'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'{\\\"brief\\\":'}}),flush=True)\ntime.sleep(20)\n",encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable)
    with pytest.raises(AIProviderError,match='超时'):
        provider._run_cli_stream([sys.executable,str(code)],purpose='fixture truncated request',timeout=.7,
            complete_json_early=True,on_stream_event=lambda *_:None)
    assert not provider.last_timings.get('response_complete')


def test_broker_requires_login_button_intent(monkeypatch):
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.providers.ai_providers import AIProviderError
    service=ProviderService()
    monkeypatch.setattr(service,'_runtime_for',lambda *a:pytest.fail('must not create login adapter'))
    with pytest.raises(AIProviderError) as error:service.login({},'polish')
    assert error.value.category=='explicit_login_required'


def test_missing_private_node_never_falls_back_to_path(tmp_path,monkeypatch):
    from twobyteasr.system.processes import renderer_node_command,renderer_child_environment
    import shutil
    monkeypatch.setattr(shutil,'which',lambda *_:pytest.fail('system Node fallback'))
    with pytest.raises(RuntimeError,match='Runtime 缺失或损坏'):renderer_node_command(tmp_path/'renderer','service.mjs')
    monkeypatch.setenv('NODE_OPTIONS','--inspect=0.0.0.0:9229')
    assert 'NODE_OPTIONS' not in renderer_child_environment()


def test_concepts_checkpoint_survives_second_request_failure(monkeypatch):
    from tests.test_hero_theme_compiler import setup,design as make_design
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    design=make_design('b')
    design['concepts'][1]['design']['metaphor']='北极熊探看字幕'
    project,settings,calls,traces=setup(monkeypatch,[AIProviderError('second request timed out',category='timeout')])
    stages=[]
    with pytest.raises(AIProviderError) as error:
        studio_ai.request_web_theme_design(project,'cue','北极熊戴滑雪镜，底部透明字幕',settings,
            request_id='c40072-fixture',stage_event_callback=stages.append,resume_design=design)
    checkpoint=error.value.design_checkpoint
    assert len(checkpoint['concepts'])==3 and '北极熊' in json.dumps(checkpoint,ensure_ascii=False)
    assert any(x.get('design')==checkpoint for x in stages)
    assert len({x['request_id'] for x in stages})==1
    assert calls[0][1]['timeout']==pytest.approx(90.,abs=.01)
    assert traces[0]['concepts']==checkpoint['concepts']
    assert error.value.category=='theme_code_timeout'


def test_retry_theme_code_does_not_request_concepts_again(monkeypatch):
    from tests.test_hero_theme_compiler import setup,design as make_design,hero
    from twobyteasr.caption_design import studio_ai
    design=make_design('b')
    project,settings,calls,traces=setup(monkeypatch,[json.dumps(hero(True))])
    result=studio_ai.request_web_theme_design(project,'cue','北极熊',settings,resume_design=design)
    assert len(calls)==1 and result.selected_concept_id=='b'
    assert design['concepts'][1]['name'] in calls[0][0][1]['content']
    assert result.concepts==traces[-1]['concepts']
