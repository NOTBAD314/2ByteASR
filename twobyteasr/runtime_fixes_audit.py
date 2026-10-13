"""--runtime-fixes-audit：2026-09-20 三修（日志横滚/子进程UTF-8/失效模型）冻结自检。

源码与冻结 EXE 同链路：在当前进程形态（source 或 frozen）内验证
  1. 隔离模式 Python 子进程经 -X utf8 后中文/日文/emoji/中文路径零乱码；
  2. 运行日志追加与整份重载横向恒最左、纵向追尾（真实 QTextEdit）；
  3. 已下线模型（deepseek-v4-flash-vision-exp）在解析/目录/校验三层被拦。

用法：2ByteASR.exe --runtime-fixes-audit --out <report.json>
不写用户数据；报告落在 --out 指定路径。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


RETIRED = "deepseek-v4-flash-vision-exp"
SAMPLE = "测试中文：主播说话人识别完成 日本語テスト emoji 🎙️ C:\\Users\\测试用户\\视频.mp4"


def _audit_utf8_stdio() -> dict:
    from twobyteasr.processes import python_utf8_command, utf8_worker_environment
    from twobyteasr.runtime_registry import resolve_runtime_python

    python = resolve_runtime_python("main") or sys.executable
    code = f"print({SAMPLE!r})"
    process = subprocess.run(
        python_utf8_command([python, "-I", "-c", code]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=utf8_worker_environment(),
    )
    output = process.stdout or ""
    return {
        "child_python": python,
        "ok": SAMPLE in output and "\ufffd" not in output,
        "sample_roundtrip": SAMPLE in output,
        "replacement_chars": output.count("\ufffd"),
        "returncode": process.returncode,
    }


def _audit_log_left_edge() -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextOption
    from PySide6.QtWidgets import QApplication, QTextEdit

    from twobyteasr.ui import (
        append_log_html_keep_left,
        set_log_html_keep_left,
    )

    app = QApplication.instance() or QApplication([])
    edit = QTextEdit()
    edit.setReadOnly(True)
    edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)
    edit.resize(420, 180)
    edit.show()
    app.processEvents()
    import html as html_mod

    def fragment(text: str) -> str:
        safe = html_mod.escape(text).replace(" ", "&nbsp;")
        return (
            '<div style="margin:1px 0; padding:2px 4px; '
            f'white-space:pre;">{safe}</div>'
        )

    for index in range(300):
        append_log_html_keep_left(
            edit,
            fragment(
                "run-signature 4a1278d069528dbf867d1d77b7149974b317a961328de8fefd70c22088941ada"
                if index % 40 == 3
                else f"[块 {index}/4] 已生成 {index * 100} tokens"
            ),
        )
        if edit.horizontalScrollBar().value() != 0:
            return {"ok": False, "failed_at_line": index}
    app.processEvents()
    tail_follow = (
        edit.verticalScrollBar().value() == edit.verticalScrollBar().maximum()
    )

    hidden = QTextEdit()
    hidden.setReadOnly(True)
    hidden.setWordWrapMode(QTextOption.WrapMode.NoWrap)
    hidden.resize(0, 0)
    append_log_html_keep_left(hidden, fragment("x" * 3000 + " tail"))
    hidden.resize(420, 180)
    hidden.show()
    app.processEvents()

    reloaded = QTextEdit()
    reloaded.setReadOnly(True)
    reloaded.setWordWrapMode(QTextOption.WrapMode.NoWrap)
    set_log_html_keep_left(reloaded, edit.toHtml())
    reloaded.show()
    app.processEvents()

    ok = (
        edit.horizontalScrollBar().value() == 0
        and hidden.horizontalScrollBar().value() == 0
        and reloaded.horizontalScrollBar().value() == 0
        and tail_follow
    )
    result = {
        "ok": ok,
        "append_h": edit.horizontalScrollBar().value(),
        "hidden_then_show_h": hidden.horizontalScrollBar().value(),
        "reload_h": reloaded.horizontalScrollBar().value(),
        "manual_scroll_max": edit.horizontalScrollBar().maximum(),
        "tail_follow": tail_follow,
    }
    for widget in (edit, hidden, reloaded):
        widget.deleteLater()
    return result


def _audit_retired_model() -> dict:
    from twobyteasr.llm_config import (
        model_is_retired,
        resolved_service_values,
        service_model_catalog,
        validate_endpoint,
    )

    settings = {
        "models": {
            "ai_service": "deepseek",
            "provider_profiles": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "model": RETIRED,
                    "protocol": "auto",
                }
            },
        }
    }
    values = resolved_service_values(settings, "deepseek")
    catalog = service_model_catalog(settings, "deepseek")
    try:
        validate_endpoint(
            {
                "provider": "deepseek",
                "model": RETIRED,
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "probe",
            },
            "全文断句模型",
        )
        rejected = False
    except RuntimeError:
        rejected = True
    return {
        "ok": (
            values["model"] != RETIRED
            and RETIRED not in catalog
            and model_is_retired(RETIRED)
            and rejected
        ),
        "resolved_model": values["model"],
        "catalog": list(catalog),
        "validate_rejects_retired": rejected,
    }


def main(argv: list) -> int:
    out_path = ""
    if len(argv) >= 2 and argv[0] == "--out":
        out_path = argv[1]
    report = {
        "packaged": bool(getattr(sys, "frozen", False)),
        "python": sys.executable,
        "utf8_stdio": _audit_utf8_stdio(),
        "log_left_edge": _audit_log_left_edge(),
        "retired_model": _audit_retired_model(),
    }
    report["ok"] = all(
        section["ok"] for section in (
            report["utf8_stdio"],
            report["log_left_edge"],
            report["retired_model"],
        )
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if out_path:
        Path(out_path).write_text(payload, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
