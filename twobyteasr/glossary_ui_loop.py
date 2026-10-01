# -*- coding: utf-8 -*-
"""有界面的术语库完整建库闭环（源码与冻结 EXE 同入口）。

``2ByteASR.exe --glossary-update-ui-loop <outdir> [game] [service] [--timeout-s N]
[--isolated-root DIR] [--apply]``

真实 UI（MainWindow→术语库）+ 真实任务管理器 + 真实联网引擎：
发起完整建库 → 任务栏持续可见（截图留证）→ 完成后打开预览（截图留证）。
默认**不点应用**（不写用户词库；任务只落 checkpoint 文件）；
``--isolated-root DIR`` 在导入重模块前重定向 LOCALAPPDATA（配合 ``--apply``
可在隔离副本上做全闭环）。结果 JSON 末行 ``RESULT_JSON: <path>`` 供自动化解析。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: --glossary-update-ui-loop <outdir> [game] [service] [--timeout-s N] [--isolated-root DIR] [--apply]")
        return 2
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    game = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else "绝区零"
    service = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else "grok_account"
    timeout_s = 1200
    apply_at_end = False
    for index, arg in enumerate(argv):
        if arg == "--timeout-s" and index + 1 < len(argv):
            timeout_s = int(argv[index + 1])
        if arg == "--apply":
            apply_at_end = True
        if arg == "--isolated-root" and index + 1 < len(argv):
            # 必须在任何读取 LOCALAPPDATA 的模块初始化前生效。
            os.environ["LOCALAPPDATA"] = str(Path(argv[index + 1]).resolve())

    import subtitle_core as legacy
    from twobyteasr import glossary_task_manager as gtm
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from twobyteasr.ui import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    events: list[dict] = []
    result = {"game": game, "service": service, "ok": False}
    started = time.perf_counter()

    win = MainWindow([], legacy, object(), None)
    win.resize(1520, 940)
    win.show()
    _pump(app, 1200)

    win._manage_terms()
    _pump(app, 600)
    lib = win.term_library_page.library

    target = None
    for index in range(lib.game_list.count()):
        item = lib.game_list.item(index)
        if game in str(item.data(Qt.ItemDataRole.UserRole) or ""):
            target = item
            break
    if target is None:
        result["error"] = f"词库列表没有 {game}"
        _finish(out_dir, result, win, app)
        return 2
    lib.game_list.setCurrentItem(target)
    _pump(app, 1500)

    service_index = lib.ai_service_combo.findData(service)
    if service_index >= 0:
        lib.ai_service_combo.setCurrentIndex(service_index)
        _pump(app, 400)
    result["capability"] = lib.ai_capability_label.text()
    if "支持联网" not in lib.ai_capability_label.text():
        result["error"] = f"所选服务不支持联网：{lib.ai_capability_label.text()}"
        _finish(out_dir, result, win, app)
        return 2

    manager = lib._ensure_task_manager()
    manager.task_progress.connect(
        lambda tid: events.append({
            "at": round(time.perf_counter() - started, 1),
            "stage": manager.get(tid).stage if manager.get(tid) else "",
            "note": manager.get(tid).stage_note if manager.get(tid) else "",
            "candidates": manager.get(tid).candidates if manager.get(tid) else 0,
        })
    )
    lib._start_ai_update("full")
    _pump(app, 800)
    task_id = None
    for task in manager.tasks():
        if task.status in {"queued", "running"}:
            task_id = task.task_id
            break
    if task_id is None:
        result["error"] = "任务未创建"
        _finish(out_dir, result, win, app)
        return 2
    _grab(win, out_dir, "01-task-started.png")

    shots = 0
    last_shot = 0.0
    while time.perf_counter() - started < timeout_s:
        _pump(app, 500)
        task = manager.get(task_id)
        if task is None:
            break
        if task.status not in {"queued", "running"}:
            break
        if time.perf_counter() - last_shot > 60 and shots < 6:
            shots += 1
            last_shot = time.perf_counter()
            _grab(win, out_dir, f"02-running-{shots}.png")

    task = manager.get(task_id)
    if task is None or task.status != "finished":
        result["error"] = f"任务未完成：{task.progress_line() if task else '丢失'}"
        result["events"] = events[-40:]
        _finish(out_dir, result, win, app)
        return 1
    result["elapsed_seconds"] = task.elapsed_seconds()
    result["candidates"] = task.candidates
    result["build_stats"] = task.result.get("build_stats", {}) if task.result else {}
    diffs = (task.result or {}).get("diffs", ()) or ()
    result["diffs_new"] = sum(1 for d in diffs if getattr(d, "change_type", "") == "new")
    result["diffs_alias"] = sum(1 for d in diffs if getattr(d, "change_type", "") == "alias_supplement")
    result["events"] = events[-80:]
    _pump(app, 1000)
    _grab(win, out_dir, "03-finished.png")

    # 打开正式预览（真实联网产出的候选），截图留证；默认不应用。
    lib._on_task_review(task_id)
    _pump(app, 800)
    host = getattr(win, "_modal_host", None)
    review = getattr(host, "_current_content", None) if host else None
    result["review_opened"] = review is not None and type(review).__name__ == "GlossaryUpdateReviewDialog"
    if result["review_opened"]:
        review.model.check_core_verified()
        result["core_checked"] = review.model.checked_count()
        result["review_rows"] = review.model.rowCount()
        _grab(win, out_dir, "04-review.png")
        if apply_at_end:
            review.apply_button.click()
            _pump(app, 1500)
            result["applied"] = True
            _grab(win, out_dir, "05-applied.png")
        else:
            host.hide_content()
            _pump(app, 400)
    result["ok"] = bool(result.get("review_opened"))
    _finish(out_dir, result, win, app)
    return 0 if result["ok"] else 1


def _pump(app, ms: int) -> None:
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.02)


def _grab(win, out_dir: Path, name: str) -> None:
    try:
        win.grab().save(str(out_dir / name))
        print(f"[ui-loop shot] {name}", flush=True)
    except Exception as exc:  # noqa: BLE001 - 截图失败不判失败
        print(f"[ui-loop shot failed] {name}: {exc}", flush=True)


def _finish(out_dir: Path, result: dict, win, app) -> None:
    path = out_dir / "ui-loop-result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    try:
        win.close()
    except Exception:  # noqa: BLE001
        pass
    _pump(app, 400)
    print(f"RESULT_JSON: {path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
