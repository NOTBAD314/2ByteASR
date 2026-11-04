"""Opt-in real-window check of 智能建词 AI 增强 (scenario ``smart-glossary-ai``, 2026-10-25).

Driver: scripts/verify_smart_glossary_ai_headed.py. User report (0.8.4 line): DeepSeek connected,
yet 智能建词 → 粘贴资料 said 「当前 API 密钥无效或未授权」 (details: ``unavailable`` / 「AI 没有返回
可读取的增强 JSON」) and 「配置 API」 led back to the same dialog.

A stand-in OpenAI-compatible service runs inside this process on 127.0.0.1 and answers in three
ways, each driven through the real dialog (术语库 → AI 菜单 → 智能建词 → 粘贴资料 → 开始提取):

* ``401``: the box says the key is invalid and offers 「配置 API」, which opens 「AI 智能断句设置」
  over the dialog; cancelling it refreshes the dialog's AI state;
* ``thinking`` (what DeepSeek does when thinking eats the output budget: empty content,
  ``finish_reason=length``): one retry with a larger budget, then a box that says the AI returned no
  complete result, without 「配置 API」 and without the word 密钥; 「查看详情」 names the code and model;
* ``ok``: no box; AI categories and aliases reach the review list; the request asked for JSON.

Then the user's own paste, an AI TSV table with the 「标准词 分类 别名或常见错写」 header, is parsed
as a table (clean terms and aliases) and sends no AI request.

With ``TWOBYTEASR_SMART_GLOSSARY_LIVE_SECRETS`` (driver ``--live-secrets``) a last step uses the real
DeepSeek API through the same dialog (key read-only from that store, never written or logged):
the request to api.deepseek.com carries ``thinking: disabled`` and the answer is used.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIBRARY = "鸣潮验收"
PLAIN_LIST = "今汐\n长离\n角色：椿、吟霖\n声骸\n共鸣解放\n第五章"
USER_TSV = (
    "标准词\t分类\t别名或常见错写\n"
    "玄方地界\t地点\tげんぽうちかい|玄方地界\n"
    "穗波市\t地点\tほなみし|穗波市|ホナミ市\n"
    "石崩れの高地\t地点\t荒石高地|石崩れ高地\n"
    "怨鳥の沼\t地点\t怨鸟泽|怨鳥沼\n"
    "虎口の山脈\t地点\t虎口山脉|虎口山脈\n"
)
LIVE_LIST = "\n".join([
    "今汐", "长离", "忌炎", "吟霖", "椿", "守岸人", "卡提希娅", "漂泊者", "散华", "秧秧",
    "今州", "黎那汐塔", "无冠者", "角", "声骸", "共鸣解放", "变奏技能", "延奏技能", "第五章", "大家好",
])
LIVE_KEY_NAME = "API__deepseek__api.deepseek.com"


class _StandIn(BaseHTTPRequestHandler):
    mode = "ok"
    requests: list = []

    def log_message(self, *_args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._send(200, {"data": [{"id": "standin-flash"}]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        mode = type(self).mode
        type(self).requests.append({"path": self.path, "mode": mode, "body": body})
        if mode == "401":
            self._send(401, {"error": {"message": "Authentication Fails, Your api key is invalid",
                                       "type": "authentication_error"}})
            return
        message = {"role": "assistant", "content": ""}
        finish = "stop"
        if mode == "thinking":
            message["reasoning_content"] = "让我逐个判断这些候选词……" * 400
            finish = "length"
        else:
            user = next(m["content"] for m in body["messages"] if m["role"] == "user")
            terms = [row["term"] for row in json.loads(user.split("：", 1)[1])]
            labels = {"今汐": "角色", "长离": "角色", "椿": "角色", "吟霖": "角色", "声骸": "机制", "共鸣解放": "技能"}
            message["content"] = json.dumps({
                "classify": [{"term": t, "category": labels[t]} for t in terms if t in labels],
                "aliases": [{"term": "今汐", "alias": "金汐"}] if "今汐" in terms else [],
                "noise": [t for t in terms if t == "第五章"],
            }, ensure_ascii=False)
        self._send(200, {"id": "chatcmpl-standin", "model": body.get("model"),
                         "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                         "usage": {"prompt_tokens": 200, "completion_tokens": 120}})


def install_guards() -> None:
    """Loopback only unless the live DeepSeek step was asked for; no automatic model discovery."""
    import socket
    from ..app.ui import EndpointEditor
    EndpointEditor._queue_model_discovery = lambda *a, **kw: None
    if os.environ.get("TWOBYTEASR_SMART_GLOSSARY_LIVE_SECRETS"):
        return
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("External network prohibited in the smart-glossary-ai acceptance")
        return original_connect(sock, address)

    socket.socket.connect = local_only


def _use_service(window, service, base_url, model, secrets):
    """Point 字幕校对 (the stage 智能建词 uses) at one service; keys come from ``secrets``."""
    from ..providers import llm_config
    models = window.legacy.RUNTIME_SETTINGS.setdefault("models", {})
    models["ai_service"] = service
    models.setdefault("provider_profiles", {})[service] = {
        "base_url": base_url, "model": model, "protocol": "auto", "json_mode": True, "structured_output": True}
    for prefix in ("polish", "group"):
        models.update({f"{prefix}_provider": service, f"{prefix}_transport": "openai_compatible",
                       f"{prefix}_base_url": base_url, f"{prefix}_model": model, f"{prefix}_protocol": "auto"})
    llm_config._read_secrets = secrets


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from ..diagnostics.build_identity import load_build_identity
    from ..glossary.main_ui_smart_glossary import SmartGlossaryDialog
    from ..providers import llm_config, network_policy

    app = QApplication.instance()
    output = Path(output)
    # The driver saved the stand-in service and its key in the isolated profile on this port.
    port = int(os.environ.get("TWOBYTEASR_SMART_GLOSSARY_STANDIN_PORT") or 0)
    server = ThreadingHTTPServer(("127.0.0.1", port), _StandIn)
    threading.Thread(target=server.serve_forever, name="smart-glossary-standin", daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    live_secrets = os.environ.get("TWOBYTEASR_SMART_GLOSSARY_LIVE_SECRETS", "")
    original_read = llm_config._read_secrets
    live_posts = []
    original_post = network_policy.post

    def recording_post(url, **kwargs):
        response = original_post(url, **kwargs)
        if "api.deepseek.com" in str(url):
            entry = {"url": str(url), "body": {k: v for k, v in (kwargs.get("json") or {}).items() if k != "messages"},
                     "status": getattr(response, "status_code", None)}
            try:
                payload = response.json()
                choice = payload["choices"][0]
                entry.update(finish_reason=choice.get("finish_reason"), usage=payload.get("usage"),
                             content_length=len(str(choice["message"].get("content") or "")))
            except Exception as exc:  # noqa: BLE001 - evidence only
                entry["parse_error"] = str(exc)[:200]
            live_posts.append(entry)
        return response

    network_policy.post = recording_post

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"passed": False, "identity": load_build_identity().to_dict(), "checks": [],
                           "pid": os.getpid(), "executable": sys.executable, "screenshots": [],
                           "values": {"standin": base_url, "live": bool(live_secrets)}}
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

        def shot(self, name, *overlays):
            """The main window plus any top-level boxes over it, as the user sees them."""
            parts = [(w.mapToGlobal(QPoint(0, 0)), w.grab()) for w in (window, *overlays) if w is not None]
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
            self.result["screenshots"].append(path.name)

        def box(self, title):
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible() and widget.windowTitle().startswith(title):
                    return widget
            return None

        def wait_box(self, title, seconds=30.0):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                found = self.box(title)
                if found is not None:
                    self.found = found
                    return
                yield .1
            self.found = None

        def press(self, widget):
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

        def button(self, box, text):
            return next((b for b in box.buttons() if b.text() == text), None)

        def smart(self):
            content = window._modal_host._current_content
            return content if isinstance(content, SmartGlossaryDialog) else None

        def open_smart(self):
            page = window.term_library_page._ensure_library()
            self.press(page.ai_menu_button)
            yield .6
            if page.smart_build_button.isVisible():
                self.press(page.smart_build_button)
            else:
                page.smart_build_button.click()
            yield 1.2
            self.check("智能建词 opens over the 术语库", self.smart() is not None)

        def extract(self, dialog, text, *, ai=True):
            if not dialog.pasted_editor.isVisible():
                self.press(dialog._source_cards["pasted"])
                yield .3
            dialog.pasted_editor.setPlainText(text)
            if dialog.ai_check.isChecked() != ai:
                self.press(dialog.ai_check)
                yield .3
            self.press(dialog.extract_button)

        def wait_review(self, dialog, seconds=60.0):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not dialog.review_panel.isVisible():
                if self.box("AI 增强不可用") is not None:
                    return
                yield .1

        def back(self, dialog):
            if dialog.back_button.isVisible():
                self.press(dialog.back_button)
                yield .5
                self.check("返回 shows step 1 and the chosen source again",
                           dialog._step_labels[0].property("active") and not dialog._step_labels[1].property("active")
                           and dialog.source_summary.isVisible(), dialog.source_summary.text())

        def run(self):
            yield 1.5
            endpoint = window.legacy.polish_llm_settings()
            self.check("saved settings point 字幕校对 at the stand-in with a key",
                       endpoint.get("url", "").startswith(base_url) and bool(endpoint.get("api_key")),
                       {k: v for k, v in endpoint.items() if k != "api_key"})
            window._manage_terms()
            yield 1.0
            page = window.term_library_page._ensure_library()
            self.press(page.sidebar_new_button)
            yield .4
            page.game_input.setText(LIBRARY)
            self.press(page.add_game_button)
            yield .8
            library_id = window.legacy.resolve_glossary_identity(LIBRARY)
            page.add_game_item(LIBRARY, library_id=library_id, select=True)
            page.refresh_current_game()
            yield .6
            yield from self.open_smart()
            dialog = self.smart()
            self.check("AI 增强 switch is available with the stand-in key", dialog.ai_check.isEnabled(),
                       dialog.ai_status.text())

            # 1) 401: the key really is rejected → 「配置 API」 opens the AI settings window.
            _StandIn.mode = "401"
            yield from self.extract(dialog, PLAIN_LIST)
            yield from self.wait_box("AI 增强不可用")
            box = self.found
            self.check("401: error box appears", box is not None)
            texts = [b.text() for b in box.buttons()] if box else []
            info = box.informativeText() if box else ""
            self.result["values"]["box_401"] = {"text": info, "buttons": texts}
            self.check("401: says the key is invalid", "当前 API 密钥无效或未授权" in info, info)
            self.check("401: offers 配置 API", "配置 API" in texts, texts)
            self.shot("01-401-box", box)
            self.press(self.button(box, "配置 API"))
            yield 1.5
            settings = getattr(window, "_ai_settings_dialog", None)
            self.check("配置 API opens 「AI 智能断句设置」 over 智能建词",
                       settings is not None and settings.isVisible() and settings.objectName() == "aiSettingsDialog",
                       settings.windowTitle() if settings else None)
            self.shot("02-config-api-opens-ai-settings", settings)
            refreshed = []
            original_refresh = dialog._refresh_ai_state
            dialog._refresh_ai_state = lambda: (refreshed.append(True), original_refresh())
            cancel = next((b for b in settings.findChildren(QPushButton) if b.text() == "取消"), None) if settings else None
            self.press(cancel)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and getattr(window, "_ai_settings_dialog", None) is not None:
                yield .1
            self.check("closing the AI settings returns to 智能建词 and re-reads its AI state",
                       refreshed == [True] and self.smart() is dialog, refreshed)
            self.check("basic candidates kept after the AI failure", dialog.review_panel.isVisible()
                       and len(dialog._candidates) >= 5, len(dialog._candidates))
            yield from self.back(dialog)

            # 2) thinking used the whole output budget: honest message, no 配置 API, details name model.
            _StandIn.mode = "thinking"
            before = len(_StandIn.requests)
            yield from self.extract(dialog, PLAIN_LIST)
            yield from self.wait_box("AI 增强不可用")
            box = self.found
            texts = [b.text() for b in box.buttons()] if box else []
            info = box.informativeText() if box else ""
            self.result["values"]["box_thinking"] = {"text": info, "buttons": texts}
            budgets = [r["body"].get("max_tokens") for r in _StandIn.requests[before:]]
            self.result["values"]["thinking_budgets"] = budgets
            self.check("thinking: one retry with a larger budget", budgets == [8192, 16384], budgets)
            self.check("thinking: box says no complete result, not a key problem",
                       box is not None and "没有返回完整的整理结果" in info and "密钥" not in info, info)
            self.check("thinking: no 配置 API button", box is not None and "配置 API" not in texts, texts)
            self.shot("03-thinking-box", box)
            self.press(self.button(box, "查看详情"))
            yield from self.wait_box("AI 增强详情", 10)
            details = self.found
            detail_text = details.text() if details else ""
            self.result["values"]["details_thinking"] = detail_text
            self.check("查看详情 names the code and model",
                       "错误码：bad_response" in detail_text and "模型：standin-flash" in detail_text, detail_text)
            self.shot("04-thinking-details", details)
            if details is not None:
                self.press(details.buttons()[0])
            yield 1.0
            yield from self.back(dialog)

            # 3) a normal answer: no box, categories and aliases applied, JSON requested.
            _StandIn.mode = "ok"
            before = len(_StandIn.requests)
            yield from self.extract(dialog, PLAIN_LIST)
            yield from self.wait_review(dialog)
            self.check("ok: no error box", self.box("AI 增强不可用") is None)
            by_term = {c.term: c for c in dialog._candidates}
            body = _StandIn.requests[-1]["body"] if len(_StandIn.requests) > before else {}
            self.result["values"]["ok_request"] = {k: v for k, v in body.items() if k != "messages"}
            self.result["values"]["ok_candidates"] = [(c.term, c.category, list(c.aliases), c.source)
                                                      for c in dialog._candidates]
            self.check("ok: one request asking for JSON", len(_StandIn.requests) - before == 1
                       and body.get("response_format") == {"type": "json_object"} and body.get("max_tokens") == 8192,
                       self.result["values"]["ok_request"])
            self.check("ok: AI category and alias reach the review list",
                       by_term.get("今汐") is not None and by_term["今汐"].category == "character"
                       and "金汐" in by_term["今汐"].aliases and "ai" in by_term["今汐"].source
                       and "第五章" not in by_term, self.result["values"]["ok_candidates"])
            self.shot("05-ok-review")
            yield from self.back(dialog)

            # 4) the user's own paste: an AI TSV table under 粘贴资料.
            before = len(_StandIn.requests)
            yield from self.extract(dialog, USER_TSV)
            yield from self.wait_review(dialog, 15)
            rows = [(c.term, c.category, list(c.aliases)) for c in dialog._candidates]
            self.result["values"]["tsv_candidates"] = rows
            self.check("pasted AI table: no AI request and no box",
                       len(_StandIn.requests) == before and self.box("AI 增强不可用") is None)
            self.check("pasted AI table: clean terms, categories and aliases", rows[:2] == [
                ("玄方地界", "location", ["げんぽうちかい"]), ("穗波市", "location", ["ほなみし", "ホナミ市"])]
                and len(rows) == 5 and not any("\t" in term or term == "标准词" for term, _c, _a in rows), rows)
            self.shot("06-pasted-ai-table-review")
            yield from self.back(dialog)

            if live_secrets:
                # 5) the real DeepSeek API through the same dialog (opened again after the switch).
                _use_service(window, "deepseek", "https://api.deepseek.com/v1", "deepseek-flash",
                             lambda **_kw: original_read(read_only_path=Path(live_secrets)))
                self.check("live: a DeepSeek key exists in the read-only store",
                           bool(original_read(read_only_path=Path(live_secrets)).get(LIVE_KEY_NAME)))
                window._modal_host._request_close()
                yield 1.0
                yield from self.open_smart()
                dialog = self.smart()
                self.check("live: AI 增强 available with DeepSeek", dialog.ai_check.isEnabled(), dialog.ai_status.text())
                started = time.monotonic()
                yield from self.extract(dialog, LIVE_LIST)
                yield from self.wait_review(dialog, 120)
                seconds = round(time.monotonic() - started, 1)
                box = self.box("AI 增强不可用")
                if box is not None:
                    self.result["values"]["live_box"] = box.informativeText()
                    self.shot("07-live-box", box)
                self.result["values"]["live_posts"] = live_posts
                self.result["values"]["live_seconds"] = seconds
                self.result["values"]["live_candidates"] = [(c.term, c.category, list(c.aliases), c.source)
                                                            for c in dialog._candidates]
                self.check("live: no error box with the real DeepSeek API", box is None)
                self.check("live: request to api.deepseek.com had thinking disabled and JSON mode",
                           bool(live_posts) and live_posts[0]["body"].get("thinking") == {"type": "disabled"}
                           and live_posts[0]["body"].get("response_format") == {"type": "json_object"}, live_posts)
                self.check("live: DeepSeek finished normally", bool(live_posts) and live_posts[-1].get("status") == 200
                           and live_posts[-1].get("finish_reason") == "stop", live_posts[-1:] if live_posts else None)
                self.check("live: AI results applied", any("ai" in c.source for c in dialog._candidates)
                           or any(c.category != "other" for c in dialog._candidates),
                           self.result["values"]["live_candidates"])
                self.shot("08-live-review")
                if box is not None:
                    self.press(self.button(box, "关闭"))
                    yield .5
            window._modal_host._request_close()
            yield 1.0

        def finish(self):
            self.timer.stop()
            server.shutdown()
            network_policy.post = original_post
            checks = self.result["checks"]
            self.result["passed"] = bool(checks) and all(c["passed"] for c in checks) and "error" not in self.result
            path = output / "result.json"
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            def shutdown_done():
                self.result["gui_shutdown"] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            app.aboutToQuit.connect(shutdown_done)
            window.result_exit_code = 0 if self.result["passed"] else 1
            window.close()

    window._smart_glossary_ai_audit = Audit()
