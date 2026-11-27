"""Exercise the packaged API settings widget with an isolated loopback service."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import sleep


def main(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(root / "profile")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..providers.endpoint_editor_ui import EndpointEditor
    from ..storage.settings import DEFAULT_SETTINGS
    from copy import deepcopy

    receipts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply({"data": [{"id": "relay-a"}, {"id": "relay-b"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            receipts.append({key: body[key] for key in ("thinking", "reasoning_effort") if key in body})
            self.reply({"choices": [{"finish_reason": "stop", "message": {
                "content": '{"ok":true,"text":"兔白字幕"}', "reasoning_details": [{"type": "reasoning.encrypted"}]}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 10, "reasoning_tokens": 4}})

        def reply(self, packet):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(packet).encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    app = QApplication.instance() or QApplication(["2ByteASR"])
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["models"].update(ai_service="custom", polish_provider="custom", polish_base_url=base,
                              polish_model="relay-a", provider_profiles={"custom": {"base_url": base, "model": "relay-a"}})
    settings["switches"]["unified_glm_processing"] = False
    editor = EndpointEditor("AI 模型与密钥", "#4064b4", "polish", settings)
    editor.show()
    editor.advanced_toggle.setChecked(True)
    editor.resize(640, 810)
    checks = {}

    def require(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    error = ""
    try:
        QTest.qWait(200)
        require("headed_windows_platform", app.platformName() == "windows" and editor.isVisible())
        require("default_off", editor.reasoning_mode.currentData() == "off")
        editor.thinking_protocol.setCurrentIndex(editor.thinking_protocol.findData("deepseek_combined"))
        expected = {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}
        require("wire_preview", json.loads(editor.reasoning_preview.toPlainText()) == expected)
        editor.model.setCurrentText("relay-b")
        require("model_scope_isolated", editor.thinking_protocol.currentData() == "auto")
        editor.model.setCurrentText("relay-a")
        require("model_scope_restored", editor.thinking_protocol.currentData() == "deepseek_combined")
        editor.reasoning_custom.setPlainText('{"thinking":{"type":"enabled"}}')
        require("invalid_custom_blocks_probe", not editor.reasoning_probe.isEnabled())
        editor.reasoning_custom.clear()
        from PySide6.QtCore import Qt
        completed = []
        editor.connection_tested.connect(completed.append)
        QTest.mouseClick(editor.reasoning_probe, Qt.MouseButton.LeftButton)
        for _ in range(600):
            if completed:
                break
            app.processEvents()
            sleep(0.05)
        require("probe_completed", completed == [True])
        require("one_exact_http_request", receipts == [expected])
        require("thinking_warning_shown", "仍返回思考证据" in editor.reasoning_status.text() and
                "4" in editor.reasoning_status.text())
        image = editor.grab()
        require("window_pixels_saved", image.save(str(root / "api-reasoning.png")))
    except Exception as exc:
        error = str(exc)
        editor.grab().save(str(root / "api-reasoning-failed.png"))
    finally:
        if editor._tester is not None:
            editor._tester.requestInterruption()
            editor._tester.wait(5000)
        editor.close()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(2)
    identity = load_build_identity()
    (root / "result.json").write_text(json.dumps({
        "checks": checks, "error": error, "dispatched_parameters": receipts,
        "platform": app.platformName(), "status": editor.status.text(), "test_category": getattr(editor._tester, "diagnostics", {}).get("category"), "build": identity.git_sha, "executable": sys.executable,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if error else 0



