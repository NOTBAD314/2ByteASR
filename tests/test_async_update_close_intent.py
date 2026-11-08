"""A successful deferred save must resume the intended update shutdown."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('updating', [False, True])
def test_close_continuation_retains_the_captured_update_intent(updating):
    from twobyteasr.app.ui import MainWindow
    pending = []
    prepared = object() if updating else None
    guard = SimpleNamespace(confirm=lambda action, **options: pending.append(options['on_saved']) or False)
    studio = SimpleNamespace(project_controller=SimpleNamespace(dirty_guard=guard))
    closed = []
    window = SimpleNamespace(_pending_update=prepared, _prepare_glossary_for_task=lambda:True)
    window.close = lambda: closed.append(window._pending_update)
    assert not MainWindow._confirm_application_close(window, studio, False)
    assert not closed and len(pending) == 1
    # The initial rejected close has cleared the transient handoff flag.
    window._pending_update = None
    pending[0]()
    assert closed == [prepared]
