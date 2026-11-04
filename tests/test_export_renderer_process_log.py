import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('exported', [False, True])
def test_renderer_export_logs_actual_ffmpeg_child_stderr_without_consuming_frame_stdout(tmp_path, exported):
    root = Path(__file__).resolve().parents[1]
    node = root/'tools/node/node.exe'
    if not node.is_file():
        pytest.skip('bundled Node unavailable')
    log = tmp_path/'children.jsonl'
    env = dict(os.environ, TWOBYTEASR_CHILD_PROCESS_LOG=str(log))
    env.pop('TWOBYTEASR_EXPORT_JOB_ID', None)
    env.pop('TWOBYTEASR_EXPORT_STDERR_ROOT', None)
    if exported:
        env.update(TWOBYTEASR_EXPORT_JOB_ID='frozen-job', TWOBYTEASR_EXPORT_STDERR_ROOT=str(tmp_path))
    script = """
const cp=require('node:child_process'), {EventEmitter}=require('node:events');
const calls=[];
cp.spawn=(command,args,opts)=>{calls.push({command,args,opts});
 const child=new EventEmitter();child.pid=321;
 child.stdout=new EventEmitter();child.stderr=new EventEmitter();return child;};
require(POLICY);
const child=cp.spawn('ffmpeg.exe',['-i','frozen.mov','-c:v','prores_ks','alpha.mov'],{cwd:'.'});
child.stderr.emit('data',Buffer.from('rc=alpha actual stderr\\n'));
child.stderr.emit('end');child.emit('exit',7,null);
process.stdout.write(JSON.stringify({calls,stdoutListeners:child.stdout.listenerCount('data')}));
""".replace('POLICY', json.dumps(str(root/'renderer/process_policy.cjs')))
    result = subprocess.run([str(node), '-e', script], env=env, capture_output=True, text=True,
        encoding='utf-8', check=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    evidence = json.loads(result.stdout)
    assert evidence['stdoutListeners'] == 0
    records = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    started = next(x for x in records if x['phase']=='start')
    assert started['command'] == [evidence['calls'][0]['command'], *evidence['calls'][0]['args']]
    assert next(x for x in records if x['phase']=='exit')['returncode'] == 7
    if exported:
        assert started['job_id'] == 'frozen-job'
        assert started['cwd'] == '.'
        assert (tmp_path/'renderer-321.stderr.log').read_text() == 'rc=alpha actual stderr\n'
    else:
        assert not (tmp_path/'renderer-321.stderr.log').exists()
