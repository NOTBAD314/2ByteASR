"""Node-created bundles/profiles are released after exit, error and cancellation."""
from pathlib import Path
import json
import threading
import pytest
from twobyteasr.rendering.advanced_renderer import _run_streaming_process


@pytest.mark.parametrize('mode',['success','failure','cancel'])
def test_real_node_scratch_is_owned_and_cleaned(tmp_path,mode):
    root=Path(__file__).resolve().parents[1]
    node=root/'tools/node/node.exe'
    if not node.is_file():pytest.skip('owned Node runtime unavailable')
    event=threading.Event();seen=[]
    script="""
const fs=require('fs'),os=require('os'),path=require('path');
const root=os.tmpdir();const dir=path.join(root,'remotion-webpack-bundle-owned');
fs.mkdirSync(dir);fs.writeFileSync(path.join(dir,'font-copy.bin'),Buffer.alloc(1024));
console.log(JSON.stringify({root}));
"""+('setInterval(()=>{},1000);' if mode=='cancel' else 'process.exit('+('2' if mode=='failure' else '0')+');')
    def line(value):
        try:data=json.loads(value)
        except ValueError:return
        seen.append(Path(data['root']))
        assert seen[-1].name.startswith('2byteasr-renderer-')
        assert (seen[-1]/'remotion-webpack-bundle-owned/font-copy.bin').is_file()
        if mode=='cancel':event.set()
    if mode=='cancel':
        with pytest.raises(InterruptedError):
            _run_streaming_process([str(node),'-e',script],on_line=line,cancelled=event.is_set)
    else:
        code,_=_run_streaming_process([str(node),'-e',script],on_line=line)
        assert code==(2 if mode=='failure' else 0)
    assert seen and all(not p.exists() for p in seen)
