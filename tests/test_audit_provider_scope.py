import threading
import pytest

from twobyteasr.acceptance.studio_acceptance_audit import _audit_provider_scope, _audit_submit_gate


def test_only_scoped_glossary_call_can_reach_provider_queue():
    calls=[]
    gate=_audit_submit_gate(lambda value:calls.append(value), 'glossary-execution')
    with pytest.raises(RuntimeError):gate('background')
    _audit_provider_scope.public_glossary=True
    errors=[]
    def background():
        try:gate('another thread')
        except RuntimeError:errors.append('denied')
    try:
        gate('authorized')
        worker=threading.Thread(target=background);worker.start();worker.join()
        with pytest.raises(RuntimeError):
            _audit_submit_gate(lambda:calls.append('other scenario'), 'nemotron-workshop')()
    finally:_audit_provider_scope.public_glossary=False
    with pytest.raises(RuntimeError):gate('after scope')
    assert calls==['authorized'] and errors==['denied']
