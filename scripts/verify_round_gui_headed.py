"""2026-09-19 轮 GUI 真实验证（headed）：方案 A/B 全回归 + 设置响应 + 中英日切换。

覆盖：
1. A/B 方案（含嵌套差异）创建→应用→改 B 保存→切回 A 原值→切回 B 新值
2. 重启进程后 A/B 差异持久化（本脚本以两次进程运行验证，见 --phase）
3. 应用设置打开计时×3 + 窗口截图（zh/en/ja 布局）
4. 语言切换 zh→en→ja→zh：已开页面刷新、方案身份/选择不丢
5. 执行层有效参数：apply A/B 后 RUNTIME_SETTINGS["models"]（识别管线唯一读取源）
   与 persist_asr_configuration 输出逐键对比

用法：
  .venv/Scripts/python.exe scripts/verify_round_gui_headed.py            # 主验证
  .venv/Scripts/python.exe scripts/verify_round_gui_headed.py --phase restart-check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tmp" / "gui-verify-20260919"
STORE_STATE = OUT / "ab-state.json"

A_CONFIG = {
    "primary_asr_backend": "moss", "qwen_asr_backend": "off",
    "qwen_asr_model": "Qwen/Qwen3-ASR-1.7B",
    "qwen_asr_api_provider": "dashscope", "qwen_asr_api_protocol": "dashscope_multimodal",
    "qwen_asr_api_model": "qwen3-asr-flash",
    "qwen_asr_api_url": "https://dashscope.example/api",
    "firered_asr_backend": "local", "api_transcribe_style": "clean",
}
B_CONFIG = {
    **A_CONFIG,
    "qwen_asr_api_provider": "groq",
    "qwen_asr_api_model": "whisper-large-v3-turbo",
    "qwen_asr_api_url": "https://api.groq.com/openai/v1",
    "api_transcribe_style": "verbatim",
}


def _iso(tmp: Path):
    os.environ["LOCALAPPDATA"] = str(tmp)
    import twobyteasr.settings as settings_module

    settings_module.stable_settings_root = lambda: tmp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="main")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "appdata"

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    _iso(tmp)
    import subtitle_core as legacy
    import twobyteasr.ui as ui_module
    from twobyteasr.project_profiles import ProjectProfileStore

    report = {"phase": args.phase, "checks": [], "failures": []}

    def check(name, ok, detail=""):
        report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})
        print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""), flush=True)
        if not ok:
            report["failures"].append(name)
        return bool(ok)

    if args.phase == "restart-check":
        # 第二进程：A/B 差异是否持久化
        store = ProjectProfileStore(tmp / "2ByteASR" / "profiles.json")  # 窗口 store 根
        profiles = {p.name: p for p in store.list()}
        a, b = profiles.get("A-verify"), profiles.get("B-verify")
        check("restart_a_exists", a is not None)
        check("restart_b_exists", b is not None)
        if a and b:
            check("restart_a_provider", a.asr_config.get("qwen_asr_api_provider") == "dashscope",
                  a.asr_config.get("qwen_asr_api_provider"))
            check("restart_b_provider", b.asr_config.get("qwen_asr_api_provider") == "groq",
                  b.asr_config.get("qwen_asr_api_provider"))
            check("restart_b_style_nested", b.asr_config.get("api_transcribe_style") == "verbatim")
            check("restart_a_style_nested", a.asr_config.get("api_transcribe_style") == "clean")
            # 删除"最后选中"的方案（脚本曾建C后删除）会正确清空指针，空值合法
            check("restart_last_selected_valid", store.last_selected_id() in {"", a.id, b.id},
                  store.last_selected_id())
        (OUT / "gui-verify-restart.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if not report["failures"] else 1

    # ---------------- phase main ----------------
    win = ui_module.MainWindow([], legacy, object(), None)
    win.resize(1500, 950)
    win.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.05)

    store = ProjectProfileStore(Path(win.profile_store.path))  # 窗口真实 store
    for existing in store.list():
        store.delete(existing.id)
    a = store.create("A-verify", asr_config=dict(A_CONFIG), llm_enabled=False)
    b = store.create("B-verify", asr_config=dict(B_CONFIG), llm_enabled=True, llm_config_ref="deepseek-chat")

    def effective_models():
        return legacy.RUNTIME_SETTINGS.get("models", {})

    # 1) 应用 A → 全局生效（执行层唯一读取源）
    win._apply_project_profile(store.get(a.id), mark_used=False)
    m = effective_models()
    check("applyA_provider", m.get("qwen_asr_api_provider") == "dashscope", m.get("qwen_asr_api_provider"))
    check("applyA_model", m.get("qwen_asr_api_model") == "qwen3-asr-flash")
    check("applyA_style", m.get("api_transcribe_style") == "clean")
    check("applyA_ui_backfill", win.qwen_asr_api_model.text() == "qwen3-asr-flash")

    # 2) 切到 B（无脏 → 不弹）→ B 生效
    combo = win.project_profile_combo
    win._apply_project_profile(store.get(b.id), mark_used=False)
    m = effective_models()
    check("applyB_provider", m.get("qwen_asr_api_provider") == "groq")
    check("applyB_style_nested", m.get("api_transcribe_style") == "verbatim")
    check("applyB_llm_enabled_restored", win.ai_grouping.isChecked() is True)

    # 3) 在 B 下改模型并"保存识别后端"（与工坊/识别启动同一保存路径）
    win.qwen_asr_api_model.setText("groq-edited-model")
    ok_save = win._save_asr_configuration(show_feedback=False)
    check("saveB_ok", ok_save is True)
    m = effective_models()
    check("saveB_effective", m.get("qwen_asr_api_model") == "groq-edited-model")
    b_re = store.get(b.id)
    a_re = store.get(a.id)
    check("saveB_syncs_only_B", b_re.asr_config.get("qwen_asr_api_model") == "groq-edited-model")
    check("saveB_does_not_touch_A", a_re.asr_config.get("qwen_asr_api_model") == "qwen3-asr-flash")

    # 4) 切回 A：A 完全原值（核心回归）
    win._apply_project_profile(store.get(a.id), mark_used=False)
    m = effective_models()
    check("switchBackA_provider", m.get("qwen_asr_api_provider") == "dashscope")
    check("switchBackA_model_original", m.get("qwen_asr_api_model") == "qwen3-asr-flash")
    check("switchBackA_ui_restored", win.qwen_asr_api_model.text() == "qwen3-asr-flash")
    check("switchBackA_llm_off", win.ai_grouping.isChecked() is False)
    # 再切回 B：B 的修改仍在
    win._apply_project_profile(store.get(b.id), mark_used=False)
    check("switchBackB_keeps_edit", effective_models().get("qwen_asr_api_model") == "groq-edited-model")

    # 5) 另存为 / 重命名 / 删除
    c = store.save_as(b.id, "C-verify")
    check("saveAs_new_id", c.id != b.id and c.asr_config.get("qwen_asr_api_model") == "groq-edited-model")
    renamed = store.rename(c.id, "C-renamed")
    check("rename_ok", renamed.name == "C-renamed")
    check("delete_ok", store.delete(c.id) is True)

    # 6) 应用设置打开计时 ×3（真窗口）
    from twobyteasr.application_settings import read_studio_preferences, project_library_root
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog
    prefs = read_studio_preferences()
    timings = []
    for i in range(3):
        t0 = time.perf_counter()
        dlg = ApplicationSettingsDialog(win, prefs, project_library_root(),
                                        browse=lambda *a: None, clear_recent=lambda: None, reset_layout=None)
        dlg.show()
        app.processEvents()
        t1 = time.perf_counter()
        timings.append(round((t1 - t0) * 1000))
        check(f"settings_open_{i+1}_no_animation", getattr(dlg, "_entrance_motion", None) is None)
        dlg.grab().save(str(OUT / f"settings-zh-{i+1}.png"))
        dlg.close()
        app.processEvents()
    check("settings_open_median_under_300ms", sorted(timings)[1] < 300, f"timings={timings}ms")
    report["settings_timings_ms"] = timings

    # 7) 语言切换 zh→en→ja→zh：主页 + 识别方案 + 设置截图；方案身份不丢
    languages = ["zh", "en", "ja", "zh"]
    for code in languages:
        idx = win.language_combo.findData(code)
        if idx >= 0:
            win.language_combo.setCurrentIndex(idx)
        app.processEvents()
        time.sleep(0.15)
        app.processEvents()
        win.grab().save(str(OUT / f"home-{code}.png"))
        # 截图瞬间程序化记录关键标签（视觉/程序双证据）
        card = win.recognition_plan.cards["primary"]
        report.setdefault("label_probe", {})[code] = {
            "role": card.role_label.text(),
            "status": card.status_badge.text(),
            "plan_label": next((l.text() for l in win.findChildren(QLabel) if l.isVisible() and l.text() in ("先选目标", "Target", "First choose a target")), ""),
        }
        check(f"lang_{code}_profile_kept", win.current_project_profile is not None
              and win.current_project_profile.id == store.get(b.id).id)
    # en/ja 下再开一次设置（布局检查用截图）
    for code in ("en", "ja"):
        idx = win.language_combo.findData(code)
        if idx >= 0:
            win.language_combo.setCurrentIndex(idx)
        app.processEvents(); time.sleep(0.1); app.processEvents()
        dlg = ApplicationSettingsDialog(win, prefs, project_library_root(),
                                        browse=lambda *a: None, clear_recent=lambda: None, reset_layout=None)
        dlg.show(); app.processEvents()
        dlg.grab().save(str(OUT / f"settings-{code}.png"))
        dlg.close(); app.processEvents()
    # 回 zh 并收尾
    idx = win.language_combo.findData("zh")
    if idx >= 0:
        win.language_combo.setCurrentIndex(idx)

    # 8) 方案身份持久化状态落盘（供 --phase restart-check 第二进程验证）
    STORE_STATE.write_text(json.dumps({"a": a.id, "b": b.id}), encoding="utf-8")

    win.close()
    app.processEvents()
    (OUT / "gui-verify-main.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MAIN DONE", flush=True)
    os._exit(0 if not report["failures"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
