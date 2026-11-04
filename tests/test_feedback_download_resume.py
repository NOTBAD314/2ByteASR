import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys


def test_complete_stream_part_publishes_without_request(tmp_path):
    # Execute the real external worker module with stdout outside pytest's
    # capture wrapper, exactly as a frozen app's managed Python worker does.
    script=Path(__file__).resolve().parents[1]/'scripts/download_file_fast.py'
    code='''
import hashlib, importlib.util, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('download', sys.argv[1])
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
out=Path(sys.argv[2])/'weight.safetensors'
data=b'valid-complete-weights'*100
part=mod._stream_part_path(out,'source-version')
part.write_bytes(data)
def forbidden(*a,**k):raise AssertionError('A complete authenticated part must not request bytes=size-')
mod._get_with_resolved=forbidden
assert mod.stream_download('https://example.invalid',out,len(data),hashlib.sha256(data).hexdigest(),'source-version')==0
assert out.read_bytes()==data and not part.exists()
'''
    run=subprocess.run([sys.executable,'-B','-c',code,str(script),str(tmp_path)],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr
