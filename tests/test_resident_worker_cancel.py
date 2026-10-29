import threading
import time

from twobyteasr.system.resident_worker import ResidentWorker


def test_cancelled_waiter_does_not_interrupt_the_running_job(monkeypatch):
    worker = ResidentWorker('fixture')
    worker._lock.acquire()
    cancelled, returned = threading.Event(), []
    monkeypatch.setattr(worker, '_ensure_process', lambda: (_ for _ in ()).throw(AssertionError('must not start')))
    thread = threading.Thread(target=lambda: returned.append(worker.call('unused', {}, cancel_check=cancelled.is_set)))
    try:
        thread.start()
        cancelled.set()
        thread.join(1)
        assert not thread.is_alive() and returned == [None]
    finally:
        worker._lock.release()
        thread.join(1)


def test_cancelled_inflight_job_retires_its_worker_before_reuse(monkeypatch):
    worker = ResidentWorker('fixture')
    cancelled, entered = threading.Event(), threading.Event()
    stopped, returned = [], []
    class Process:
        def is_alive(self): return True
    class Connection:
        def poll(self, seconds):
            entered.set()
            time.sleep(.01)
            return False
    worker._process, worker._connection = Process(), Connection()
    monkeypatch.setattr(worker, '_ensure_process', lambda: True)
    monkeypatch.setattr(worker, '_send', lambda *a, **k: None)
    monkeypatch.setattr(worker, '_stop', lambda *, force: stopped.append(force))
    thread = threading.Thread(target=lambda: returned.append(worker.call('fixture', {}, cancel_check=cancelled.is_set)))
    thread.start()
    assert entered.wait(1)
    cancelled.set()
    thread.join(1)
    assert not thread.is_alive() and returned == [None] and stopped == [True]
    assert worker._lock.acquire(blocking=False)
    worker._lock.release()
