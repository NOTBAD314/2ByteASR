import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtTest import QTest
from twobyteasr.media.media_intake import parse_media_arguments, validate_media_paths
from twobyteasr.app.single_instance import SingleInstanceGuard
from twobyteasr.app.desktop_intake import DesktopIntake

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])

def test_cli_forms_and_help(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TWOBYTEASR_INVOKER_CWD", raising=False)
    monkeypatch.chdir(tmp_path)
    assert parse_media_arguments([]) == []
    assert parse_media_arguments(["中文 空格.mp4", "😀.wav"]) == [str(tmp_path/"中文 空格.mp4"), str(tmp_path/"😀.wav")]
    assert parse_media_arguments(["--import", "a.mp4", "b.wav"]) == [str(tmp_path/"a.mp4"), str(tmp_path/"b.wav")]
    with pytest.raises(SystemExit) as error:
        parse_media_arguments(["--help"])
    assert error.value.code == 0
    assert "FILE" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        parse_media_arguments(["--not-valid"])

def test_partial_validation(tmp_path):
    a,b=tmp_path/"中文 空格.mp4",tmp_path/"😀.wav"
    a.write_bytes(b"fixture");b.write_bytes(b"fixture")
    empty=tmp_path/"empty.mkv";empty.touch()
    accepted,rejected=validate_media_paths([a,tmp_path/"a.txt",tmp_path/"missing.mp4",b,empty,a])
    assert accepted == [str(a),str(b)]
    assert len(rejected) == 3

def test_one_locked_file_does_not_abort_batch(tmp_path):
    good=tmp_path/"good.wav";good.write_bytes(b"fixture")
    locked=tmp_path/"locked.mp4";locked.write_bytes(b"fixture")
    if os.name != "nt": pytest.skip("Windows exclusive sharing")
    import ctypes
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    k.CreateFileW.restype=ctypes.c_void_p
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=k.CreateFileW(str(locked),0x80000000,0,None,3,0,None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        accepted,rejected=validate_media_paths([locked,good])
        assert accepted==[str(good)] and len(rejected)==1
    finally:k.CloseHandle(handle)

def test_ipc_real_process_unicode_retry_and_crash(tmp_path):
    name="2ByteASR-file-test-"+uuid.uuid4().hex
    receipt=tmp_path/"receipt.json"
    code = """from PySide6.QtCore import QCoreApplication,QTimer
from twobyteasr.app.single_instance import SingleInstanceGuard
import json,sys
from pathlib import Path
app=QCoreApplication([])
g=SingleInstanceGuard(sys.argv[1]);assert g.acquire()
received=[]
def save(paths):
 received.append(paths);Path(sys.argv[2]).write_text(json.dumps(received),encoding='utf-8')
g.paths_received.connect(save);g.enable_receiver()
print('READY',flush=True)
QTimer.singleShot(15000,app.quit)
app.exec()
g.release()
"""
    owner=subprocess.Popen([sys.executable,"-B","-c",code,name,str(receipt)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert owner.stdout.readline().strip()=="READY"
        g=SingleInstanceGuard(name)
        assert not g.acquire()
        paths=["D:/中文 路径/a.mp4", "E:/😀.wav"]
        assert g.forward(paths,request_id="retry")
        assert g.forward(paths,request_id="retry")
        assert g.forward([],request_id="activate")
        assert json.loads(receipt.read_text()) == [paths,[]]
    finally:
        owner.kill();owner.wait(timeout=5)
    deadline=time.monotonic()+3
    while not g.acquire():
        assert time.monotonic()<deadline
        QTest.qWait(25)
    g.release()

def test_async_intake_reuses_media_state_and_defers_while_busy(tmp_path,monkeypatch):
    import twobyteasr.app.desktop_intake as intake
    monkeypatch.setattr(intake,"_remember_media_directory",lambda paths:None)
    class Window(QWidget):
        def __init__(self):
            super().__init__();self.media_paths=[];self._run_in_progress=True;self.worker=None
            self.header_status=QLabel(self);self.refreshes=0
            self._studio_recognition_context={"old_project":True}
        def _refresh_media_summary(self): self.refreshes+=1
    w=Window();receiver=DesktopIntake(w)
    a,b=tmp_path/"a.mp4",tmp_path/"b.wav";a.write_bytes(b"a");b.write_bytes(b"b")
    receiver.submit([str(a)]);QTest.qWait(100)
    assert not w.media_paths
    w._run_in_progress=False
    receiver.submit([str(b)])
    deadline=time.monotonic()+3
    while len(w.media_paths)!=2 and time.monotonic()<deadline:QTest.qWait(20)
    assert w.media_paths==[str(a),str(b)] and w.refreshes==2
    assert w._studio_recognition_context is None
    w.close();w.deleteLater();QTest.qWait(20)

def test_help_does_not_load_pipeline_or_qt():
    result=subprocess.run([sys.executable,"-B","quick_start.py","--help"],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",env={**os.environ,"PYTHONIOENCODING":"utf-8"},timeout=10)
    assert result.returncode==0 and "FILE" in result.stdout
    assert "Traceback" not in result.stderr
