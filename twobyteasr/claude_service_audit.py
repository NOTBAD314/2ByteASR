"""Opt-in real-window check of the Claude AI service (scenario ``claude-service``, 2026-10-18).

Driver: scripts/verify_claude_service_headed.py (source, or ``--exe`` for a frozen candidate). A local
stand-in for the Anthropic Messages API runs inside this process on 127.0.0.1 (HTTP on the loopback is
allowed for any provider); nothing reaches the internet and no real key is used. Checks, with
screenshots in the output folder:

* 「AI 智能断句设置」lists 「Claude API」; choosing it shows the three Claude models and the
  ``…/v1/messages`` endpoint;
* 测试连接 with a typed key passes through the real dialog: one ``POST /v1/messages`` with
  ``x-api-key``, ``anthropic-version``, streaming, no ``temperature``; 刷新模型 reads ``/v1/models``;
* a 401 from the stand-in is shown as a failed test, not as a pass;
* the 申请教程 button opens the Claude guide;
* the workbench 「AI 设计」 service list offers 「Claude API」 with its models.

The dialog is cancelled: no setting or key is saved.
"""
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANSWER = '{"ok": true, "text": "兔白字幕"}'


class _StandIn(BaseHTTPRequestHandler):
    """Just enough of /v1/messages and /v1/models for the dialog's two buttons."""
    requests = []
    reject = False

    def log_message(self, *_args):
        pass

    def _send(self, status, body, content_type):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("request-id", "req_local_standin")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        type(self).requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
        if self.path.startswith("/v1/models"):
            models = [{"id": name, "type": "model", "display_name": name, "max_input_tokens": 1_000_000,
                       "max_tokens": 128_000, "capabilities": {"image_input": {"supported": True}}}
                      for name in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")]
            self._send(200, json.dumps({"data": models, "has_more": False, "first_id": models[0]["id"],
                                        "last_id": models[-1]["id"]}), "application/json")
        else:
            self._send(404, json.dumps({"type": "error", "error": {"type": "not_found_error", "message": "x"}}),
                       "application/json")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        type(self).requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
        if type(self).reject:
            self._send(401, json.dumps({"type": "error", "error": {"type": "authentication_error",
                                                                   "message": "invalid x-api-key"}}),
                       "application/json")
            return
        events = [
            {"type": "message_start", "message": {"id": "msg_local", "model": body.get("model"),
                                                  "usage": {"input_tokens": 20, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ANSWER}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 12}},
            {"type": "message_stop"},
        ]
        stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
        self._send(200, stream, "text/event-stream")


def install_guards() -> None:
    """Only the loopback is reachable: the stand-in answers, nothing leaves the machine."""
    import socket
    from .ui import EndpointEditor
    EndpointEditor._queue_model_discovery = lambda *a, **kw: None  # 刷新模型 is clicked on purpose
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if address[0] not in {'127.0.0.1', '::1', 'localhost'}:
            raise RuntimeError('External network prohibited in the claude-service acceptance')
        return original_connect(sock, address)

    socket.socket.connect = local_only


def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from .build_identity import load_build_identity

    app = QApplication.instance()
    output = Path(output)
    theme = os.environ.get("TWOBYTEASR_CLAUDE_AUDIT_THEME", "grape")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StandIn)
    threading.Thread(target=server.serve_forever, name="claude-standin", daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"passed": False, "identity": load_build_identity().to_dict(), "checks": [],
                           "pid": os.getpid(), "executable": sys.executable, "screenshots": [], "theme": theme,
                           "values": {"base_url": base_url}}
            self.steps = self.run()
            self.wait_until = 0
            self.busy = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result["checks"].append({"name": name, "passed": bool(value), "detail": detail})

        def tick(self):
            if self.busy or time.monotonic() < self.wait_until:
                return
            self.busy = True
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result["error"] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def shot(self, widget, name):
            path = output / f"{name}.png"
            widget.grab().save(str(path))
            self.result["screenshots"].append(str(path))

        def wait_for(self, predicate, seconds=20.0):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if predicate():
                    return True
                yield .2
            return predicate()

        # ---------------------------------------------------------------- run
        def run(self):
            yield 1.0
            from .theme_manager import apply_theme
            apply_theme(theme)
            window.showNormal()
            window.resize(1600, 1000)
            yield 1.0
            yield from self.settings_dialog()
            yield from self.workbench_selector()

        def settings_dialog(self):
            QTimer.singleShot(0, window._open_ai_settings_dialog)
            dialog = None
            for _ in range(50):
                yield .2
                dialog = getattr(window, "_ai_settings_dialog", None)
                if dialog is not None and dialog.isVisible():
                    break
            self.check("AI 智能断句设置 opened", dialog is not None and dialog.isVisible())
            if dialog is None:
                return
            editors = [e for e in (getattr(window, "group_editor", None), getattr(window, "polish_editor", None))
                       if e is not None and e.isVisibleTo(dialog)]
            editor = editors[0]
            labels = [editor.service.itemText(i) for i in range(editor.service.count())]
            self.result["values"]["services"] = labels
            self.check("the service list offers Claude API", "Claude API" in labels, labels)
            editor.service.setCurrentIndex(editor.service.findData("claude"))
            yield 1.0
            # The list itself fills on 刷新模型 (for every service); the choice is set at once.
            self.check("Claude Opus 5.5 is chosen", editor.model.currentText() == "claude-opus-5-5",
                       editor.model.currentText())
            hint = editor.endpoint_hint.text()
            self.check("the endpoint is the Messages API", hint.rstrip().endswith("/v1/messages"), hint)
            self.shot(dialog, "01-claude-selected")
            # Point this unsaved card at the local stand-in and type a key.
            editor.base_url.setText(base_url)
            editor.key.setText("sk-ant-local-standin")
            yield .8
            _StandIn.requests.clear()
            editor.test_button.click()
            passed = yield from self.wait_for(lambda: "连接测试通过" in editor.status.text(), 25)
            status = editor.status.text()
            posts = [r for r in _StandIn.requests if r["method"] == "POST"]
            self.result["values"]["test_status"] = status
            self.result["values"]["test_request"] = {k: v for k, v in (posts[0] if posts else {}).items()
                                                     if k != "headers"}
            headers = {k.lower(): v for k, v in (posts[0]["headers"] if posts else {}).items()}
            body = posts[0]["body"] if posts else {}
            self.check("测试连接 passes through the real dialog", passed, status)
            self.check("one POST /v1/messages with the Anthropic headers",
                       len(posts) == 1 and posts[0]["path"] == "/v1/messages"
                       and headers.get("x-api-key") == "sk-ant-local-standin"
                       and headers.get("anthropic-version") == "2023-06-01" and "authorization" not in headers,
                       {k: headers.get(k) for k in ("anthropic-version", "anthropic-beta", "content-type")})
            self.check("streaming, no temperature, the chosen model",
                       body.get("stream") is True and "temperature" not in body
                       and body.get("model") == editor.model.currentText(), body.get("model"))
            self.shot(dialog, "02-test-passed")
            editor.discover_models_button.click()
            listed = yield from self.wait_for(lambda: any(r["method"] == "GET" and r["path"].startswith("/v1/models")
                                                          for r in _StandIn.requests), 15)
            yield 1.5
            models = [editor.model.itemText(i) for i in range(editor.model.count())]
            self.result["values"]["models_after_refresh"] = models
            self.check("after 刷新模型 the list holds the three Claude models",
                       {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"} <= set(models), models)
            gets = [r for r in _StandIn.requests if r["method"] == "GET"]
            get_headers = {k.lower(): v for k, v in (gets[0]["headers"] if gets else {}).items()}
            self.check("刷新模型 reads /v1/models with the Anthropic headers",
                       listed and get_headers.get("x-api-key") == "sk-ant-local-standin", [g["path"] for g in gets])
            self.result["values"]["after_refresh_status"] = editor.status.text()
            self.shot(dialog, "03-models-refreshed")
            _StandIn.reject = True
            editor.test_button.click()
            failed = yield from self.wait_for(lambda: "失败" in editor.status.text()
                                              or "401" in editor.status.text(), 25)
            self.result["values"]["rejected_status"] = editor.status.text()
            self.check("a 401 is shown as a failed test", failed and "连接测试通过" not in editor.status.text(),
                       editor.status.text())
            self.shot(dialog, "04-test-rejected")
            _StandIn.reject = False
            before = {id(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
            QTimer.singleShot(0, editor.guide_button.click)  # a modal guide runs its own loop
            yield 2.0
            opened = [w for w in QApplication.topLevelWidgets() if w.isVisible() and id(w) not in before]
            guide_text = " ".join(label.text() for w in opened for label in w.findChildren(QWidget)
                                  if hasattr(label, "text") and isinstance(label.text(), str))[:4000]
            self.check("申请教程 opens the Claude guide", opened and ("Claude" in guide_text or "Anthropic" in guide_text),
                       [type(w).__name__ for w in opened])
            for w in opened:
                self.shot(w, "05-guide")
                (w.reject() if hasattr(w, "reject") else w.close())
            yield .8
            # Cancel: nothing of this audit is saved (a modal question is answered from a timer).
            def answer():
                from PySide6.QtWidgets import QMessageBox
                box = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()),
                           None)
                if box is not None:
                    self.result["values"]["cancel_question"] = box.text()
                    (box.button(QMessageBox.StandardButton.Discard) or box.buttons()[-1]).click()
            QTimer.singleShot(800, answer)
            QTimer.singleShot(0, dialog.reject)
            yield 2.0
            try:
                still_open = dialog.isVisible()
            except RuntimeError:  # already deleted after closing
                still_open = False
            self.check("the dialog closed without saving", not still_open)

        def workbench_selector(self):
            window.open_studio_project(os.environ.get("TWOBYTEASR_STARTUP_PROJECT", ""))
            page = None
            for _ in range(150):
                page = window.built_page("studio")
                if page is not None and page.project is not None:
                    break
                yield .3
            if page is None:
                self.check("workbench opened", False)
                return
            yield 2.0
            for surface in window.findChildren(QWidget, "studioLoadingSurface"):
                surface.hide()
            page.context_drawer.setCurrentIndex(0)
            yield 1.0
            labels = [page.ai_provider.itemText(i) for i in range(page.ai_provider.count())]
            self.result["values"]["workbench_services"] = labels
            self.check("AI 设计 offers Claude API", "Claude API" in labels, labels)
            page.ai_provider.setCurrentIndex(page.ai_provider.findData("claude"))
            yield 1.0
            models = [page.ai_model.itemText(i) for i in range(page.ai_model.count())]
            self.check("AI 设计 lists the Claude models", "claude-opus-5-5" in models, models)
            self.shot(page.context_drawer, "06-workbench-ai-design")
            yield .3

        def finish(self):
            self.timer.stop()
            server.shutdown()
            checks = self.result["checks"]
            self.result["passed"] = bool(checks) and all(c["passed"] for c in checks) and "error" not in self.result
            path = output / "result.json"
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            def shutdown_done():
                self.result["gui_shutdown"] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            app.aboutToQuit.connect(shutdown_done)
            page = window.built_page("studio")
            if page is not None:
                page.undo_stack.setClean()
            window.showNormal()
            window.close()

    window._claude_service_audit = Audit()
