from types import SimpleNamespace
import pytest
from twobyteasr.recognition.service import RunOptions


@pytest.mark.parametrize('running',[True,False])
def test_result_signal_does_not_allow_replacement_before_thread_exit(running):
    from twobyteasr.app.ui import MainWindow
    old=SimpleNamespace(isRunning=lambda:running,wait=lambda timeout:False,
                        deleteLater=lambda:pytest.fail('Unfinished thread was destroyed'))
    window=SimpleNamespace(worker=old)
    with pytest.raises(RuntimeError,match='收尾'):
        MainWindow._launch_pipeline_worker(window,RunOptions())
    assert window.worker is old


def test_failed_new_task_persistence_keeps_previous_thread_object_usable(monkeypatch):
    from twobyteasr.app import ui
    deleted=[]
    old=SimpleNamespace(isRunning=lambda:False,wait=lambda timeout:True,deleteLater=lambda:deleted.append(True))
    window=SimpleNamespace(worker=old,media_paths=['input.wav'],legacy=None,pipeline=None,startup_self_test=None)
    def failed(*args):raise OSError('injected task record write failure')
    monkeypatch.setattr(ui,'PipelineWorker',failed)
    with pytest.raises(OSError):ui.MainWindow._launch_pipeline_worker(window,RunOptions())
    assert not deleted and window.worker is old


def test_same_job_resume_rejects_callbacks_from_previous_attempt():
    from twobyteasr.app.ui import MainWindow
    current,old=object(),object();calls=[]
    window=SimpleNamespace(worker=current,_dispatch_recognition_job=lambda *args:calls.append(args) or True)
    assert MainWindow._dispatch_recognition_attempt(window,old,'same-task','callback','late') is False
    assert MainWindow._dispatch_recognition_attempt(window,current,'same-task','callback','current') is True
    assert len(calls)==1 and calls[0][-1]=='current'
