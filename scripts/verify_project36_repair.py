"""Normal source/frozen entry, copied project, private desktop and isolated data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--full-export', action='store_true')
    args=parser.parse_args(); out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists(): raise ValueError('Fresh tmp output required')
    out.mkdir(parents=True)
    original=args.project.resolve(); original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.settings import DEFAULT_SETTINGS
    (out/'config/2byteasr_settings.json').write_text(json.dumps(DEFAULT_SETTINGS,ensure_ascii=False),'utf8')
    from PySide6.QtCore import QSettings
    settings=QSettings('2ByteASR','2ByteASR'); settings.setValue('appearance/theme','grape'); settings.sync()
    shutil.copyfile(original,out/'fixture.2byteproj')
    (out/'config.json').write_text(json.dumps(dict(project36=True,full_export=args.full_export)),'utf8')
    env=os.environ.copy(); env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='cue-affix-checks',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        PYTHONUTF8='1',PYTHONIOENCODING='utf8',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'fixture.2byteproj')],cwd=root,env=env,output=out/'process',timeout=1500)
    deadline=time.monotonic()+1500
    while not (out/'result.json').exists() and time.monotonic()<deadline: time.sleep(.2)
    if not (out/'result.json').exists(): raise TimeoutError('No project36 audit result')
    result=json.loads((out/'result.json').read_text('utf8'))
    result['protected_project_unchanged']=hashlib.sha256(original.read_bytes()).hexdigest()==original_hash
    result['launcher_exit']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] and result['protected_project_unchanged'] and code==0 else 1


if __name__=='__main__': raise SystemExit(main())
