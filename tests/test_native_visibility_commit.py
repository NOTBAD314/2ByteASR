"""Owned HWND handoff protocol with Win32/Qt state fakes; no GUI or player."""
import ctypes
from ctypes import wintypes as W
import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread

from twobyteasr.design import native_visibility_commit as native


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in self.callbacks:
            callback()


class Widget:
    def __init__(self, hwnd, visible=True, created=True):
        self.hwnd = hwnd
        self.visible = visible
        self.created = created
        self.valid = True
        self.forbid_calls = False
        self.destroyed = Signal()

    def _check(self):
        assert self.valid and not self.forbid_calls, "Invalid/reentrant QWidget call"

    def testAttribute(self, _attribute):
        self._check()
        return self.created

    def internalWinId(self):
        self._check()
        return self.hwnd

    def isVisible(self):
        self._check()
        return self.visible

    def isWindow(self):
        self._check()
        return False


class App:
    valid = True

    def __init__(self):
        self.filters = []
        self.operations = []

    def thread(self):
        return QThread.currentThread()

    def installNativeEventFilter(self, filter_):
        self.operations.append("install")
        self.filters.append(filter_)

    def removeNativeEventFilter(self, filter_):
        self.operations.append("remove")
        self.filters.remove(filter_)


class Api:
    def __init__(self, app):
        self.app = app
        self.windows = {}
        self.styles = {}
        self.batches = []
        self.fallbacks = []
        self.fail = False
        self.fail_fallback = False
        self.add(100, parent=0)

    def add(self, hwnd, parent=100, visible=True, pid=None):
        self.windows[hwnd] = native._Identity(hwnd, parent, pid or os.getpid(), 10, "QtOwned")
        self.styles[hwnd] = visible
        return Widget(hwnd, visible)

    def identity(self, hwnd):
        return self.windows.get(hwnd)

    def visible_style(self, hwnd):
        return self.styles[hwnd]

    def batch(self, targets):
        assert not self.app.filters, "Own batch was intercepted"
        assert len({info.parent for info, _visible in targets}) == 1
        self.app.operations.append("batch")
        self.batches.append([(info.hwnd, visible) for info, visible in targets])
        if self.fail:
            raise OSError("controlled EndDeferWindowPos failure")
        for info, visible in targets:
            self.styles[info.hwnd] = visible

    def set_visibility(self, info, visible):
        assert not self.app.filters
        self.fallbacks.append((info.hwnd, visible))
        if not self.fail_fallback:
            self.styles[info.hwnd] = visible
            return True
        return False


@pytest.fixture(autouse=True)
def fake_qobject_validity(monkeypatch):
    monkeypatch.setattr(native, "isValid", lambda obj: obj.valid)


def fixture():
    app = App()
    api = Api(app)
    widget = api.add(11)
    gate = native.NativeVisibilityCommit(_api=api, _application=app)
    return gate, api, app, widget


def message(gate, hwnd, flags, *, message_type=native._CHANGING, kind=b"windows_generic_MSG"):
    pos = native._WindowPos()
    pos.hwnd, pos.flags = hwnd, flags
    msg = W.MSG()
    msg.hWnd, msg.message, msg.lParam = hwnd, message_type, ctypes.addressof(pos)
    assert gate.nativeEventFilter(kind, ctypes.addressof(msg)) == (False, 0)
    return pos.flags


def qt_visibility(gate, api, widget, visible):
    widget.visible = visible
    if api.styles[widget.hwnd] != visible:
        flags = message(gate, widget.hwnd, native._STABLE | (native._SHOW if visible else native._HIDE))
        if flags & (native._SHOW | native._HIDE):
            api.styles[widget.hwnd] = visible


def test_nested_latest_target_commits_once_after_filter_removed():
    gate, api, app, widget = fixture()
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
        with gate.scope([widget]):
            qt_visibility(gate, api, widget, True)
        qt_visibility(gate, api, widget, False)
        assert api.styles[11] and not widget.visible and not api.batches
    assert api.batches == [[(11, False)]]
    assert app.operations == ["install", "remove", "batch"]
    assert gate.last_result["status"] == "committed"


@pytest.mark.parametrize("initial", [False, True])
def test_cancelled_change_without_opposite_message_uses_final_qt_target(initial):
    gate, api, app, widget = fixture()
    widget.visible = api.styles[11] = initial
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, not initial)
        qt_visibility(gate, api, widget, initial)
        assert gate.last_result["deferred_messages"] == 1
    assert api.styles[11] == initial and not api.batches
    assert not app.filters


def test_native_callback_never_calls_qwidget_and_keeps_geometry_flags():
    gate, api, _app, widget = fixture()
    with gate.scope([widget]):
        widget.forbid_calls = True
        flags = message(gate, 11, 0x0012 | native._HIDE)
        widget.forbid_calls = False
        assert flags == 0x0012
        widget.visible = False
    assert api.batches == [[(11, False)]]


def test_exception_commits_and_preserves_original_exception():
    gate, api, app, widget = fixture()
    with pytest.raises(ValueError, match="original"):
        with gate.scope([widget]):
            qt_visibility(gate, api, widget, False)
            raise ValueError("original")
    assert api.batches == [[(11, False)]] and not app.filters


@pytest.mark.parametrize("field,value", [("pid", -1), ("parent", 99),
                                        ("thread", 22), ("window_class", "Foreign"),
                                        ("is_child", False)])
def test_changed_native_identity_is_never_intercepted_or_committed(field, value):
    from dataclasses import replace
    gate, api, _app, widget = fixture()
    with gate.scope([widget]):
        api.windows[11] = replace(api.windows[11], **{field: value})
        assert message(gate, 11, native._HIDE) == native._HIDE
        widget.visible = False
    assert not api.batches


@pytest.mark.parametrize("retirement", ["native_destroy", "invalid_qobject", "new_handle"])
def test_retired_or_replaced_widget_is_not_committed(retirement):
    gate, api, _app, widget = fixture()
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
        if retirement == "native_destroy":
            message(gate, 11, 0, message_type=native._DESTROY)
            api.windows.pop(11)
        elif retirement == "invalid_qobject":
            widget.valid = False
        else:
            widget.hwnd = 12
            api.add(12)
    assert not api.batches


def test_close_during_scope_discards_pending_and_removes_filter():
    gate, api, app, widget = fixture()
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
        gate.close()
        assert not app.filters
        widget.valid = False
    assert not api.batches and gate.last_result["status"] == "closed"
    with gate.scope([widget]):
        pass
    assert not app.filters


def test_owner_destruction_closes_coordinator():
    gate, api, app, widget = fixture()
    owner = Widget(99)
    gate = native.NativeVisibilityCommit(owner, _api=api, _application=app)
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
        owner.destroyed.emit()
    assert not api.batches and not app.filters


def test_new_nested_widget_is_bound_without_native_creation():
    gate, api, app, widget = fixture()
    second = api.add(12)
    with gate.scope([widget]):
        with gate.scope([second]):
            qt_visibility(gate, api, widget, False)
            qt_visibility(gate, api, second, False)
    assert len(api.batches) == 1 and set(api.batches[0]) == {(11, False), (12, False)}
    assert app.operations.count("install") == 1


def test_unsupported_or_uncreated_widget_is_noop():
    gate, api, app, widget = fixture()
    widget.created = False
    with gate.scope([widget]):
        widget.visible = False
    assert not app.operations and not api.batches
    gate = native.NativeVisibilityCommit(_api=None, _application=app)
    with gate.scope([widget]):
        pass
    assert not app.operations


def test_foreign_process_and_toplevel_are_not_bound():
    gate, api, app, _widget = fixture()
    foreign = api.add(33, pid=os.getpid() + 1)
    top = api.add(34, parent=0)
    with gate.scope([foreign, top]):
        assert message(gate, 33, native._HIDE) == native._HIDE
    assert not app.operations and not api.batches


def test_owned_toplevel_with_native_owner_is_not_a_child():
    gate, api, app, widget = fixture()
    widget.isWindow = lambda: True
    with gate.scope([widget]):
        assert message(gate, 11, native._HIDE) == native._HIDE
    assert not app.operations and not api.batches


def test_wrong_thread_is_rejected_before_any_native_action():
    gate, api, app, widget = fixture()
    app.thread = lambda: object()
    with pytest.raises(RuntimeError, match="GUI thread"):
        with gate.scope([widget]):
            pytest.fail("must not enter")
    assert not api.batches and not app.operations


def test_hierarchy_hides_parent_first_and_shows_children_first():
    gate, api, _app, _widget = fixture()
    parent = api.add(20)
    child = api.add(21, parent=20)
    with gate.scope([parent, child]):
        qt_visibility(gate, api, child, False)
        qt_visibility(gate, api, parent, False)
    assert api.batches == [[(20, False)], [(21, False)]]
    api.batches.clear()
    with gate.scope([parent, child]):
        qt_visibility(gate, api, parent, True)
        qt_visibility(gate, api, child, True)
    assert api.batches == [[(21, True)], [(20, True)]]


def test_page_handoff_prepares_new_subtree_then_common_parent_switch_then_old_child_hide():
    gate, api, _app, _widget = fixture()
    old = api.add(20)
    old_child = api.add(21, parent=20)
    new = api.add(30, visible=False)
    new_child = api.add(31, parent=30, visible=False)
    with gate.scope([old, old_child, new, new_child]):
        for widget in (old, old_child):
            qt_visibility(gate, api, widget, False)
        for widget in (new, new_child):
            qt_visibility(gate, api, widget, True)
    assert api.batches[0] == [(31, True)]
    assert set(api.batches[1]) == {(20, False), (30, True)}
    assert api.batches[2] == [(21, False)]


def test_batch_failure_is_explicit_and_guarded_fallback_restores_consistency():
    gate, api, app, widget = fixture()
    api.fail = True
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
    assert gate.last_result["status"] == "fallback"
    assert api.fallbacks == [(11, False)] and not api.styles[11]
    assert not app.filters


def test_failed_fallback_is_error_not_success():
    gate, api, app, widget = fixture()
    api.fail = api.fail_fallback = True
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
    assert gate.last_result["status"] == "error"
    assert api.styles[11] and not app.filters


def test_planning_failure_has_one_recorded_guarded_reconciliation(monkeypatch):
    gate, api, app, widget = fixture()
    def broken_plan(*_args):
        raise RuntimeError("controlled plan failure")
    monkeypatch.setattr(native, "_ordered_groups", broken_plan)
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
    assert not api.batches and api.fallbacks == [(11, False)]
    assert gate.last_result["status"] == "fallback"
    assert gate.last_result["reconcile"] == [{"hwnd": 11, "visible": False, "ok": True}]
    assert not app.filters


def test_native_batch_refuses_different_parents_before_begin():
    api = object.__new__(native._Win32Visibility)
    api.user = SimpleNamespace(BeginDeferWindowPos=lambda _count: pytest.fail("must not begin"))
    with pytest.raises(ValueError, match="one parent"):
        api.batch([(native._Identity(10, 1, 1, 1, "Qt"), False),
                   (native._Identity(11, 2, 1, 1, "Qt"), False)])


def test_native_defer_failure_never_calls_end(monkeypatch):
    api = object.__new__(native._Win32Visibility)
    info = native._Identity(10, 1, 1, 1, "Qt")
    api.identity = lambda _hwnd: info
    api.user = SimpleNamespace(BeginDeferWindowPos=lambda _count: 9,
                               DeferWindowPos=lambda *_args: 0,
                               EndDeferWindowPos=lambda _h: pytest.fail("invalid HDWP"))
    with pytest.raises(OSError):
        api.batch([(info, False)])


def test_post_commit_runs_once_after_outermost_native_commit_and_binding_cleanup():
    gate, api, app, widget = fixture()
    calls = []

    def submitted(receipt):
        assert not app.filters and not gate._bindings and not gate._pending
        assert gate._depth == 0 and not gate._committing
        assert not api.styles[11]
        assert receipt["status"] == "committed"
        app.operations.append("post_commit")
        calls.append(receipt)
        return {"status": "submitted"}

    gate.after_commit = submitted
    with gate.scope([widget]):
        with gate.scope([widget]):
            qt_visibility(gate, api, widget, False)
        assert not calls
    assert len(calls) == 1
    assert app.operations == ["install", "remove", "batch", "post_commit"]
    assert gate.last_result["post_commit"] == {"status": "completed", "result": {"status": "submitted"}}


def test_post_commit_receipt_and_result_cannot_mutate_native_evidence():
    gate, api, _app, widget = fixture()
    outcome = {"status": "submitted", "offset": [4, 5]}

    def observed(receipt):
        receipt["status"] = "rewritten"
        receipt["batches"][0]["ok"] = False
        return outcome

    gate.after_commit = observed
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
    outcome["offset"][0] = 99
    assert gate.last_result["status"] == "committed"
    assert gate.last_result["batches"][0]["ok"] is True
    assert gate.last_result["post_commit"]["result"]["offset"] == [4, 5]


@pytest.mark.parametrize("failed_fallback", [False, True])
def test_post_commit_reports_degraded_native_result_without_relabelling_it(failed_fallback):
    gate, api, app, widget = fixture()
    api.fail = True
    api.fail_fallback = failed_fallback
    calls = []

    def observed(receipt):
        assert not app.filters and not gate._bindings
        assert len(api.fallbacks) == 1
        calls.append(receipt["status"])
        return {"status": "unavailable", "fallback": "repaint_requested"}

    gate.after_commit = observed
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
    expected = "error" if failed_fallback else "fallback"
    assert calls == [expected]
    assert gate.last_result["status"] == expected
    assert gate.last_result["post_commit"]["result"]["status"] == "unavailable"


def test_post_commit_failure_does_not_mask_scope_exception_or_claim_flush_success():
    gate, api, app, widget = fixture()

    def failed(_receipt):
        assert not app.filters
        raise RuntimeError("controlled flush failure")

    gate.after_commit = failed
    with pytest.raises(ValueError, match="scope body"):
        with gate.scope([widget]):
            qt_visibility(gate, api, widget, False)
            raise ValueError("scope body")
    assert gate.last_result["status"] == "committed"
    assert gate.last_result["post_commit"] == {"status": "error", "error": "RuntimeError: controlled flush failure"}
    assert not gate.last_result["errors"]


@pytest.mark.parametrize("close_at", ["body", "native_commit"])
def test_close_before_post_commit_retires_callback(close_at):
    gate, api, _app, widget = fixture()
    gate.after_commit = lambda _receipt: pytest.fail("closed owner must not flush")
    if close_at == "native_commit":
        original = api.batch
        def retire(targets):
            original(targets)
            gate.close()
        api.batch = retire
    with gate.scope([widget]):
        qt_visibility(gate, api, widget, False)
        if close_at == "body":
            gate.close()
    assert gate.last_result["status"] == "closed"
    assert "post_commit" not in gate.last_result


def test_no_visibility_change_and_unsupported_scope_do_not_flush():
    gate, _api, app, widget = fixture()
    gate.after_commit = lambda _receipt: pytest.fail("no native visibility change")
    with gate.scope([widget]):
        pass
    assert gate.last_result["post_commit"]["status"] == "not_needed"
    unsupported = native.NativeVisibilityCommit(after_commit=gate.after_commit, _api=None, _application=app)
    with unsupported.scope([widget]):
        pass
    assert "post_commit" not in unsupported.last_result


def test_navigation_from_post_commit_starts_with_clean_binding_ownership():
    gate, api, _app, first = fixture()
    second = api.add(12)
    seen = []

    def navigate(receipt):
        seen.append(receipt["batches"][0]["targets"][0]["hwnd"])
        if len(seen) == 1:
            with gate.scope([second]):
                qt_visibility(gate, api, second, False)
        return {"status": "submitted"}

    gate.after_commit = navigate
    with gate.scope([first]):
        qt_visibility(gate, api, first, False)
    assert seen == [11, 12]
    assert api.batches == [[(11, False)], [(12, False)]]
    assert gate.last_result["batches"][0]["targets"] == [{"hwnd": 12, "visible": False}]
    assert gate.last_result["post_commit"]["result"]["status"] == "submitted"
