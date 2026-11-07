"""First-show stacking must be repaired before protected handoff is tested."""
from types import SimpleNamespace

from twobyteasr.studio.studio_loading import StudioLoadingSession


class Cover:
    def __init__(self, complete=True):
        self.complete = complete
        self.on_top = False
        self.raises = 0
        self.native_cover_owner = object()

    def raise_(self):
        self.raises += 1
        self.on_top = True

    def native_cover_state(self):
        return {'verified': self.complete and self.on_top}

    def repaint(self):
        pass

    def _confirm_native_paint(self, **kwargs):
        pass


def session(complete=True, input_ready=True):
    view = Cover(complete)
    callbacks = []
    failures = []
    page = SimpleNamespace(
        view=view, generation=3, _native_cover_fault='',
        _input_lease=SimpleNamespace(acquire=lambda *args: input_ready),
        _native_callback_complete=False, _native_present_pending=3,
        _native_pending_token=object(), _native_waiting_owner=False,
        _sync_surface=lambda: None, on_present=lambda: callbacks.append('present'),
        native_cover_state=view.native_cover_state,
        _recover_native_cover=failures.append,
    )
    return page, callbacks, failures


def test_first_show_restack_completes_once_before_timeout():
    page, callbacks, failures = session()
    assert StudioLoadingSession._present_behind_native_cover(page, 3)
    assert page._native_cover_authorized_generation == 3
    assert page._native_pending_token is None
    assert StudioLoadingSession._present_behind_native_cover(page, 3)
    assert callbacks == ['present']
    assert not failures


def test_restack_keeps_full_cover_evidence_required():
    page, callbacks, failures = session(complete=False)
    assert not StudioLoadingSession._present_behind_native_cover(page, 3)
    assert page.view.on_top
    assert not callbacks
    assert not failures
    assert not hasattr(page, '_native_cover_authorized_generation')


def test_stale_or_failed_generation_cannot_restack_or_present():
    page, callbacks, failures = session()
    assert not StudioLoadingSession._present_behind_native_cover(page, 2)
    page._native_cover_fault = 'previous failure'
    assert not StudioLoadingSession._present_behind_native_cover(page, 3)
    assert page.view.raises == 0
    assert not callbacks


def test_input_protection_failure_cannot_present_editor():
    page, callbacks, failures = session(input_ready=False)
    assert not StudioLoadingSession._present_behind_native_cover(page, 3)
    assert len(failures) == 1
    assert not callbacks
    assert not hasattr(page, '_native_cover_authorized_generation')
