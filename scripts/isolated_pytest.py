"""Offline pytest entry; local renderers and explicitly stubbed providers work."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import uuid
os.environ.setdefault('TWOBYTEASR_TEST_ROOT',str(Path(__file__).resolve().parents[1]/'tmp'/'isolated-tests'/uuid.uuid4().hex))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from twobyteasr.test_isolation import install, install_pytest_network_guard
install()
install_pytest_network_guard()
_popen=subprocess.Popen
class OfflinePopen(_popen):
    def __init__(self,args,*pos,**kwargs):
        command=str(args[0] if isinstance(args,(list,tuple)) else args).lower()
        if Path(command).name in ('grok','grok.exe','grok.cmd','agy','agy.exe','agy.cmd','antigravity','antigravity.exe','antigravity.cmd','codex','codex.exe','codex.cmd'):
            fixture=Path(command).resolve()
            if not fixture.is_relative_to(Path(__file__).resolve().parents[1]/'tmp'):
                raise RuntimeError('Offline regression blocked real account CLI')
        super().__init__(args,*pos,**kwargs)
subprocess.Popen=OfflinePopen
# QSettings' Windows registry backend ignores LOCALAPPDATA. Give each test
# process an INI backend before importing tests that construct any widgets.
import os
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat,QSettings.UserScope,str(Path(os.environ['APPDATA'])/'qsettings'))
import pytest
if __name__=='__main__':
    raise SystemExit(pytest.main(['-q','--no-header',*sys.argv[1:]]))
