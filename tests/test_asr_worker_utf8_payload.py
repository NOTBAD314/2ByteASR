"""Real isolated Python workers, no models/network: launch -> pipes -> UTF-8 JSON."""
import json
import sys
import tempfile

import numpy as np
import pytest


SAMPLE='中文字幕要枪全也日本語'
WORKER='''
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--manifest');p.add_argument('--output');p.add_argument('--model-dir')
a=p.parse_args()
jobs=json.loads(Path(a.manifest).read_text(encoding='utf8'))['jobs']
sample=SAMPLE_LITERAL
probe={'isolated':sys.flags.isolated,'utf8_mode':sys.flags.utf8_mode,
       'stdout_encoding':sys.stdout.encoding,'stderr_encoding':sys.stderr.encoding,
       'sample':sample,'model_imported':any(x in sys.modules for x in ('torch','transformers','fireredasr2s','qwen_asr'))}
print('CHILD_PROBE='+json.dumps(probe,ensure_ascii=False),flush=True)
print('CHILD_PROBE='+json.dumps(probe,ensure_ascii=False),file=sys.stderr,flush=True)
print('STDERR_SAMPLE='+sample,file=sys.stderr,flush=True)
rows=[{'segment_id':job.get('segment_id',i),'text':sample,'confidence':0.9,
       'timestamp':[{'text':sample,'start':0.01,'end':0.09}]} for i,job in enumerate(jobs,1)]
Path(a.output).write_text(json.dumps({'results':rows,'child_probe':probe},ensure_ascii=False),encoding='utf8')
'''.replace('SAMPLE_LITERAL',repr(SAMPLE))


@pytest.mark.parametrize('stage',['firered','qwen'])
def test_actual_production_launcher_keeps_child_streams_and_json_utf8(tmp_path,monkeypatch,stage):
    from twobyteasr.recognition import asr, cache
    # These substitute only model content/runtime location. The actual
    # launchers, Popen, pipe readers and JSON loader execute unchanged.
    worker_name='firered_aed_worker.py' if stage=='firered' else 'qwen_asr_worker.py'
    (tmp_path/worker_name).write_text(WORKER,encoding='utf8')
    monkeypatch.setattr(asr,'SCRIPT_DIR',str(tmp_path))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:sys.executable)
    monkeypatch.setattr(asr,'_raise_if_queue_cancelled',lambda:None)
    monkeypatch.setattr(asr,'build_qwen_asr_context',lambda *a:'')
    original_temporary_directory=tempfile.TemporaryDirectory
    monkeypatch.setattr(asr.tempfile,'TemporaryDirectory',lambda **kwargs:
        original_temporary_directory(dir=str(tmp_path),**kwargs))
    events=[]
    monkeypatch.setattr(cache,'record_run_event',lambda event,**values:events.append({'event':event,**values}))
    audio=np.zeros(1600,dtype=np.float32)
    if stage=='firered':
        result=asr._transcribe_firered_worker(audio,.1,str(tmp_path/'no-model'))
        assert result['segments'][0]['text']==SAMPLE
        assert result['segments'][0]['tokens'][0]['text']==SAMPLE
        event=next(row for row in events if row['event']=='FIRERED_PROCESS')
        stdout,stderr=event['FIRERED_STDOUT'],event['FIRERED_STDERR']
    else:
        result=asr._transcribe_qwen_worker(audio,[{'start':0.,'end':.1,'audio':[audio]}],str(tmp_path/'no-model'))
        assert result[0]['text']==SAMPLE
        event=next(row for row in events if row['event']=='QWEN3-ASR_PROCESS')
        # Qwen deliberately stores stderr only in its process receipt. The
        # child reports both stdio encodings there; FireRed covers its actual
        # decoded stdout plus stderr. No production telemetry fields added.
        stdout,stderr='',event['QWEN_STDERR']
    assert SAMPLE in stderr and (stage=='qwen' or SAMPLE in stdout)
    assert '\ufffd' not in stdout+stderr
    probe=json.loads(next(line.removeprefix('CHILD_PROBE=') for line in stderr.splitlines() if line.startswith('CHILD_PROBE=')))
    assert probe['isolated']==1 and probe['utf8_mode']==1
    assert probe['stdout_encoding'].lower().replace('-','')=='utf8'
    assert probe['stderr_encoding'].lower().replace('-','')=='utf8'
    assert not probe['model_imported']
    exited=[row for row in events if row['event']=='asr_worker_exited']
    assert len(exited)==1 and exited[0]['returncode']==0 and exited[0]['readers_stopped']
