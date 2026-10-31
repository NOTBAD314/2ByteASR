"""The installed venv binds the final patch interpreter and starts there."""
from pathlib import Path
import subprocess,sys,json
from scripts.install_managed_backend import create_pinned_venv


def test_stdlib_creation_uses_fixed_base_and_final_path(tmp_path):
    base=Path(getattr(sys,'_base_executable',sys.executable)).resolve()
    target=tmp_path/'中文 空格'/'main'/'candidate'
    calls=[]
    def run(args,step):
        calls.append((args,step))
        subprocess.run(list(map(str,args)),check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    create_pinned_venv(base,target,run)
    assert '--without-pip' in calls[0][0] and calls[0][0][0]==base
    python=target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    actual=json.loads(subprocess.check_output([str(python),'-I','-c',
        "import sys,json;print(json.dumps(dict(prefix=sys.prefix,base=sys.base_prefix)))"],text=True))
    assert Path(actual['prefix']).resolve()==target.resolve()
    assert Path(actual['base']).resolve()==base.parent
