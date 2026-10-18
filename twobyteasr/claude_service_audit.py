"""Opt-in real-window check of the Claude AI service (scenario ``claude-service``, 2026-10-18).

Driver: scripts/verify_claude_service_headed.py (source, or ``--exe`` for a frozen candidate). A local
stand-in for the Anthropic Messages API runs inside this process on 127.0.0.1 (HTTP on the loopback is
allowed for any provider); nothing reaches the internet and no real key is used. Checks, with
screenshots in the output folder:

* with ``TWOBYTEASR_CLAUDE_AUDIT_RETIRED`` (driver ``--retired-saved-model``) the dialog opens straight
  on DeepSeek whose saved model is retired: the 模型 dropdown neither lists nor chooses it, the service
  default is chosen and the 「已不可用」 warning names it (fixed 2026-10-18);
* in the same run the saved settings never resolve to the retired id: request endpoint, recognition
  snapshot and the home 「AI 智能断句」 card all name the service's model, also with 同一云端模型
  switched off (driver ``--not-unified``, where 全文断句 reads the flat ``group_model``; fixed
  2026-10-18), and typing the retired id into the editable 模型 box only marks the draft as
  「配置未通过保存校验」 (it used to raise from ``_refresh_ai_summary``) while 保存设置 refuses it with
  the 「已不可用」 message and saves nothing;
* 「AI 智能断句设置」lists 「Claude API」; choosing it shows the three Claude models and the
  ``…/v1/messages`` endpoint;
* switching 阿里云百炼 → Claude API → xAI → DeepSeek → Gemini, the opened 模型 dropdown lists each
  service's own catalog at once, with model discovery switched off (fixed 2026-10-18: it used to keep
  the previous service's ``qwen3.7-…`` items until 刷新模型);
* 测试连接 with a typed key passes through the real dialog: one ``POST /v1/messages`` with
  ``x-api-key``, ``anthropic-version``, streaming, no ``temperature``; 刷新模型 reads ``/v1/models``;
* a 401 from the stand-in is shown as a failed test, not as a pass;
* the 申请教程 button opens the Claude guide;
* the workbench 「AI 设计」 service list offers 「Claude API」 with its models, and switching services
  there also lists only the new service's models.

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

        def composite(self, base, overlays, name):
            """One picture of a window and its open popups (separate top-level windows)."""
            from PySide6.QtCore import QPoint, QRect, Qt
            from PySide6.QtGui import QPainter, QPixmap
            parts = [(w.mapToGlobal(QPoint(0, 0)), w.grab()) for w in (base, *overlays)]
            area = QRect()
            for origin, pixmap in parts:
                area = area.united(QRect(origin, pixmap.deviceIndependentSize().toSize()))
            ratio = parts[0][1].devicePixelRatio()
            canvas = QPixmap(area.size() * ratio)
            canvas.setDevicePixelRatio(ratio)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            for origin, pixmap in parts:
                painter.drawPixmap(origin - area.topLeft(), pixmap)
            painter.end()
            path = output / f"{name}.png"
            canvas.save(str(path))
            self.result["screenshots"].append(str(path))

        def service_switches(self, dialog, editor):
            """The opened 模型 dropdown follows the 「AI 服务」 choice (automatic model discovery is off)."""
            from .llm_config import service_model_catalog
            switches = []
            for step, service_id in enumerate(("bailian", "claude", "xai", "deepseek", "gemini", "claude")):
                editor.service.setCurrentIndex(editor.service.findData(service_id))
                yield .6
                expected = list(service_model_catalog(editor._settings_ref, service_id))
                items = [editor.model.itemText(i) for i in range(editor.model.count())]
                editor.model.showPopup()
                yield .8
                popup = editor.model._popup
                shown = popup.isVisible()
                listed = [popup.listing.item(row).text() for row in range(popup.listing.count())]
                self.composite(dialog, [popup] if shown else [], f"00-{step}-{service_id}-dropdown")
                editor.model.hidePopup()
                yield .3
                entry = {"service": service_id, "items": items, "dropdown": listed,
                         "chosen": editor.model.currentText(), "dropdown_open": shown}
                switches.append(entry)
                foreign = [m for m in listed if service_id != "bailian" and m.startswith("qwen")]
                self.check(f"switched to {service_id}: the open dropdown lists its own models",
                           shown and expected and items == expected and listed == expected and not foreign
                           and editor.model.currentText() in expected, entry)
            self.result["values"]["service_switches"] = switches

        def retired_open(self, dialog, editor, retired):
            """Opened straight on DeepSeek whose saved model is retired (the EndpointEditor open path)."""
            from .llm_config import service_model_catalog
            warning = editor.model_warning.text() if editor.model_warning.isVisibleTo(dialog) else ""
            items = [editor.model.itemText(i) for i in range(editor.model.count())]
            entry = {"service": editor.service.currentData(), "items": items,
                     "chosen": editor.model.currentText(), "warning": warning}
            self.shot(dialog, "00-retired-open")
            editor.model.showPopup()
            yield .8
            popup = editor.model._popup
            shown = popup.isVisible()
            entry["dropdown"] = [popup.listing.item(row).text() for row in range(popup.listing.count())]
            entry["dropdown_open"] = shown
            self.composite(dialog, [popup] if shown else [], "00-retired-open-dropdown")
            editor.model.hidePopup()
            yield .3
            self.result["values"]["retired_open"] = entry
            expected = list(service_model_catalog(editor._settings_ref, "deepseek"))
            self.check("opened on DeepSeek with a retired saved model: not listed, the service default chosen",
                       entry["service"] == "deepseek" and shown and expected and items == expected
                       and entry["dropdown"] == expected and retired not in items
                       and entry["chosen"] == expected[0], entry)
            self.check("the 已不可用 warning names the retired model", retired in warning and "已不可用" in warning,
                       warning)

        def retired_saved_state(self, retired):
            """Saved settings with the retired id: every runtime resolution names the service's model."""
            from .asr_provider_snapshot import resolve_provider_snapshot
            from .llm_config import effective_ai_identity, endpoint_from_settings, resolved_service_values
            if getattr(window, "_recognition_page_deferred", False):
                window._ensure_recognition_page()  # the home AI card lives on the recognition page
                yield 1.0
            settings = window.legacy.RUNTIME_SETTINGS
            expected = resolved_service_values(settings, "deepseek")["model"]
            resolved = {}
            for stage in ("polish", "group"):
                resolved[stage] = {"request": endpoint_from_settings(settings, stage)["model"],
                                   "snapshot": resolve_provider_snapshot(settings, stage=stage).model,
                                   "identity": effective_ai_identity(settings, stage)["model"]}
            texts = self.home_texts()
            entry = {"unified": bool(settings.get("switches", {}).get("unified_glm_processing")),
                     "group_model_saved": settings.get("models", {}).get("group_model"),
                     "expected": expected, "resolved": resolved, **texts}
            self.result["values"]["retired_saved"] = entry
            self.shot(window, "00-retired-home")
            self.check("saved retired model: request, recognition snapshot and summary resolve to the service model",
                       expected and expected != retired
                       and all(model == expected for stage in resolved.values() for model in stage.values()), entry)
            # Without a key the card reads 没填 API Key; the saved summary names the model either way. Before the
            # fix it named the retired id and, as the editors showed the default, claimed an unsaved draft.
            self.check("the home AI card names the service model, no retired id and no phantom draft",
                       retired not in texts["tile"] and retired not in texts["panel_summary"]
                       and expected in texts["panel_summary"] and "未保存草稿" not in texts["panel_summary"]
                       and texts["chips"].get("saved") != "有未保存的修改", texts)
            yield .2

        def home_texts(self):
            chips = getattr(window, "_ai_state_chips", {}) or {}
            return {"tile": window.setting_tiles["ai"].summary_label.text(),
                    "panel_summary": window.ai_panel.summary_label.text(),
                    "chips": {name: chip.text() for name, chip in chips.items() if not chip.isHidden()}}

        def retired_typed(self, dialog, editor, retired):
            """The retired id typed into the editable 模型 box, then 保存设置."""
            from PySide6.QtWidgets import QMessageBox
            from .llm_config import service_model_catalog
            settings_before = json.dumps(window.legacy.RUNTIME_SETTINGS.get("models", {}), sort_keys=True,
                                         default=str)
            hooked, raised = [], ""
            previous_hook = sys.excepthook
            sys.excepthook = lambda kind, value, _tb: hooked.append(f"{kind.__name__}: {value}")
            try:
                line = editor.model.lineEdit()
                line.selectAll()
                line.insert(retired)  # currentTextChanged -> _refresh_ai_summary, as typing does
                yield .8
                try:
                    window._refresh_ai_summary()
                except Exception as exc:  # what used to escape (and stop the app at startup)
                    raised = f"{type(exc).__name__}: {exc}"
            finally:
                sys.excepthook = previous_hook
            texts = self.home_texts()
            entry = {"typed": editor.model.currentText(), "slot_exceptions": hooked, "raised": raised,
                     "has_draft": getattr(window, "_ai_has_draft", None), **texts}
            self.shot(dialog, "00-retired-typed")
            self.shot(window, "00-retired-typed-home")
            self.check("a typed retired id raises nothing from the summary preview", not hooked and not raised, entry)
            self.check("the draft is reported as 配置未通过保存校验",
                       "配置未通过保存校验" in texts["panel_summary"] and entry["has_draft"] is True
                       and texts["chips"].get("saved") == "有未保存的修改", entry)
            refused = {}

            def answer():
                box = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()),
                           None)
                if box is not None:
                    refused["text"] = box.text()
                    self.shot(box, "00-retired-save-refused")
                    (box.button(QMessageBox.StandardButton.Ok) or box.buttons()[0]).click()
            QTimer.singleShot(1200, answer)
            QTimer.singleShot(0, window.ai_dialog_save_button.click)  # the warning box runs its own loop
            yield 2.5
            entry["save_refused"] = refused.get("text", "")
            entry["save_status"] = window.ai_save_status.text()
            settings_after = json.dumps(window.legacy.RUNTIME_SETTINGS.get("models", {}), sort_keys=True,
                                        default=str)
            self.check("保存设置 refuses the typed retired id and saves nothing",
                       retired in entry["save_refused"] and "已不可用" in entry["save_refused"]
                       and dialog.isVisible() and settings_after == settings_before, entry)
            default = list(service_model_catalog(editor._settings_ref, "deepseek"))[0]
            line = editor.model.lineEdit()
            line.selectAll()
            line.insert(default)
            yield .8
            texts = self.home_texts()
            entry["after_reselect"] = texts
            self.check("choosing an available model again clears 配置未通过保存校验",
                       "配置未通过保存校验" not in texts["panel_summary"], texts)
            self.result["values"]["retired_typed"] = entry

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
            retired = os.environ.get("TWOBYTEASR_CLAUDE_AUDIT_RETIRED", "")
            if retired:
                yield from self.retired_saved_state(retired)
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
            retired = os.environ.get("TWOBYTEASR_CLAUDE_AUDIT_RETIRED", "")
            if retired:
                yield from self.retired_open(dialog, editor, retired)
                yield from self.retired_typed(dialog, editor, retired)
            yield from self.service_switches(dialog, editor)  # ends on Claude API
            editor.service.setCurrentIndex(editor.service.findData("claude"))
            yield 1.0
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
            from .llm_config import service_model_catalog
            switches = []
            for service_id in ("bailian", "deepseek", "claude"):
                page.ai_provider.setCurrentIndex(page.ai_provider.findData(service_id))
                yield 1.0
                models = [page.ai_model.itemText(i) for i in range(page.ai_model.count())]
                expected = list(service_model_catalog(page.runtime_settings, service_id))
                switches.append({"service": service_id, "items": models, "chosen": page.ai_model.currentText()})
                self.check(f"AI 设计 switched to {service_id}: only its own models",
                           expected and models == expected and page.ai_model.currentText() in expected
                           and (service_id == "bailian" or not any(m.startswith("qwen") for m in models)),
                           switches[-1])
            self.result["values"]["workbench_switches"] = switches
            self.check("AI 设计 lists the Claude models", "claude-opus-5-5" in models, models)
            page.ai_model.showPopup()
            yield .8
            view = page.ai_model.view().window()
            self.composite(page.context_drawer, [view] if view.isVisible() else [], "06-workbench-ai-design")
            page.ai_model.hidePopup()
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
