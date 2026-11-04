from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtTest import QTest

from twobyteasr.app.studio_module_preload import StudioModulePreloader

APP=QCoreApplication.instance() or QCoreApplication([])


def test_preload_yields_between_imports_and_duplicate_start_does_not_duplicate_work():
    calls=[];beats=[]
    timer=QTimer();timer.setInterval(1);timer.timeout.connect(lambda:beats.append(len(calls)));timer.start()
    loader=StudioModulePreloader(importer=lambda name:calls.append(name),modules=['qa_one','qa_two','qa_three'])
    finished=[];loader.ready.connect(lambda:finished.append(True))
    loader.start();loader.start()
    QTest.qWait(150);timer.stop()
    assert calls==['qa_one','qa_two','qa_three'] and finished==[True]
    assert 1 in beats and 2 in beats
    loader.start();QTest.qWait(30);assert finished==[True]
    loader.deleteLater()


def test_preload_failure_retains_the_failed_dependency_for_explicit_retry():
    calls=[]
    def load(name):
        calls.append(name)
        if len(calls)==1:raise ImportError('controlled')
    loader=StudioModulePreloader(importer=load,modules=['qa_retry'])
    errors=[];loader.failed.connect(errors.append)
    loader.start();QTest.qWait(40)
    assert len(errors)==1 and not loader.completed and list(loader.pending)==['qa_retry']
    loader.start();QTest.qWait(60)
    assert loader.completed and calls==['qa_retry','qa_retry']
    loader.deleteLater()
