from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
from twobyteasr.local_models import model_workshop as w
from twobyteasr.local_models.model_state_events import task_transition,active_task


def test_operation_failure_releases_only_its_owned_state(monkeypatch,tmp_path):
    app=QApplication.instance() or QApplication([])
    model=next(m for m in w.MODELS if m.key=='qwen_aligner')
    dialog=w.ModelDownloadDialog(tmp_path,model,operation='verify')
    task_transition(dialog,['qwen_ultra_aligner'],'loading',active=True,operation='verify')
    calls=[];dialog.completed.connect(lambda ok,msg:calls.append((ok,msg)))
    monkeypatch.setattr(dialog,'_notify_result_sound',lambda *a:None)
    dialog._finish_with_error('controlled interpreter unavailable')
    assert active_task('qwen_ultra_aligner') is None
    assert calls==[(False,'controlled interpreter unavailable')]
    dialog.deleteLater();app.processEvents()


@pytest.mark.parametrize('paused,code,outcome',[(False,0,'success'),(False,1,'failure'),(True,1,'cancelled')])
def test_completion_failure_and_cancellation_reach_terminal(monkeypatch,tmp_path,paused,code,outcome):
    app=QApplication.instance() or QApplication([])
    model=next(m for m in w.MODELS if m.key=='qwen_aligner')
    dialog=w.ModelDownloadDialog(tmp_path,model,operation='verify')
    dialog._paused=paused;dialog._phase='ready' if code==0 else 'loading';dialog._started_at=1.;dialog._stage_started=1.
    monkeypatch.setattr(dialog,'_read_output',lambda:None)
    monkeypatch.setattr(dialog,'_notify_result_sound',lambda *a:None)
    monkeypatch.setattr(dialog,'_actionable_failure_message',lambda code:'controlled failure')
    task_transition(dialog,['qwen_ultra_aligner'],'loading',active=True,operation='verify')
    calls=[];dialog.completed.connect(lambda ok,msg:calls.append(ok))
    dialog._finished_v2(code,QProcess.ExitStatus.NormalExit)
    assert active_task('qwen_ultra_aligner') is None
    assert calls==[outcome=='success']
    assert dialog.start_button.isEnabled()
    dialog.deleteLater();app.processEvents()


def test_mfa_environment_repair_does_not_request_shared_main_rebuild():
    model=next(m for m in w.MODELS if m.key=='mfa_aligner');called=[]
    owner=NS(process=NS(state=lambda:QProcess.ProcessState.NotRunning),model=model,operation='verify',_repair_requested=True,_finished_ok=True,start=lambda:called.append(1))
    w.ModelDownloadDialog._rebuild_runtime(owner)
    assert owner.operation=='prepare' and owner._repair_requested is False and called==[1]
