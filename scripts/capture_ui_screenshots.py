"""UI 验收截图（开发工具，不参与应用发布逻辑）。

用法（在项目根目录）：
    .venv-main\\Scripts\\python.exe scripts\\capture_ui_screenshots.py

输出：screenshots/ui-density/<场景>_<宽>x<高>.png，共 14 张：
    main / main_accordion / workshop_primary / workshop_timeline /
    glossary_default / glossary_add_game / smart_source / smart_review /
    smart_ai_401 × 1366x768 / 1920x1080
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout  # noqa: E402

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.smart_glossary import (  # noqa: E402
    AiEnhancementError,
    GlossaryCandidate,
)
from twobyteasr.model_workshop import ModelPickerPanel  # noqa: E402

OUT_DIR = Path(
    os.environ.get("TWO_BYTE_ASR_UI_SHOT_DIR", ROOT / "screenshots" / "ui-density")
)
SIZES = ((1366, 768), (1920, 1080))


def _temp_media() -> str:
    folder = Path(tempfile.mkdtemp(prefix="2byteasr_preview_"))
    path = folder / "示例素材.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000)
    return str(path)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    media = _temp_media()

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    window = ui.MainWindow(
        [media],
        subtitle_core,
        moss_firered_pipeline,
        {"id": "preview", "checks": 0},
    )
    window.game_box.setCurrentText("我的世界")
    window.show()
    app.processEvents()

    def capture(widget, name: str, width: int, height: int) -> bool:
        widget.resize(width, height)
        app.processEvents()
        target = OUT_DIR / f"{name}_{width}x{height}.png"
        ok = widget.grab().save(str(target), "PNG")
        print(f"{target.name}: {'OK' if ok else 'FAIL'}")
        return ok

    # 1. Main UI（三角色卡 + 词库 chips + AI 智能断句 + CTA 状态条）
    for width, height in SIZES:
        capture(window, "main", width, height)

    # 2. Main：AI 智能断句 tile 展开
    window.setting_tiles["ai"].setChecked(True)
    window.ai_panel.set_expanded(True, animate=False)
    app.processEvents()
    for width, height in SIZES:
        capture(window, "main_tiles", width, height)
    window.setting_tiles["ai"].setChecked(False)
    window.ai_panel.set_expanded(False, animate=False)

    # 2a. 首页共享 Model Picker
    model_picker = ui.SpringDialog(window)
    model_picker.resize(860, 680)
    model_picker_layout = QVBoxLayout(model_picker)
    model_picker_layout.addWidget(ModelPickerPanel(window.workshop_page, "primary", model_picker))
    model_picker.show()
    app.processEvents()
    for width, height in SIZES:
        capture(model_picker, "model_picker_primary", width, height)
    model_picker.close()

    # 2b. 多词库选择器
    picker = ui.GlossaryPickerDialog(window)
    picker.show()
    app.processEvents()
    for width, height in SIZES:
        capture(picker, "glossary_picker", width, height)
    picker.close()

    # 工坊（保留上一轮验收）
    window._open_model_workshop()
    window.workshop_page._set_role("primary")
    window.workshop_page._view_model("moss")
    for width, height in SIZES:
        capture(window, "workshop_primary", width, height)
    window.workshop_page._set_role("timeline")
    window.workshop_page._view_model("firered")
    for width, height in SIZES:
        capture(window, "workshop_timeline", width, height)

    # 识别记录：真实读取 reports/*.json
    window._open_recognition_history()
    for width, height in SIZES:
        capture(window, "recognition_history", width, height)

    # 回到设置页
    window._return_to_settings()

    # 3. Term Library resident page (the real production route)
    window._manage_terms()
    app.processEvents()
    terms_dialog = window.term_library_page.library
    for index in range(terms_dialog.game_list.count()):
        terms_dialog.game_list.setCurrentRow(index)
        app.processEvents()
        if terms_dialog.listing.model().rowCount():
            break
    for width, height in SIZES:
        capture(window, "term_library_page", width, height)

    # 4. Glossary add game state（顶部 toolbar 输入态）
    terms_dialog.game_input.setText("星穹铁道")
    terms_dialog.game_input.setFocus()
    app.processEvents()
    for width, height in SIZES:
        capture(window, "term_library_add_game", width, height)
    window._return_to_settings()

    # 5. Smart glossary source selection
    smart = ui.SmartGlossaryDialog(window, "我的世界")
    smart.show()
    app.processEvents()
    for width, height in SIZES:
        capture(smart, "smart_source", width, height)

    # 5b. Smart glossary source selection（无 API Key：AI 增强禁用 + 提示）
    original_validate = ui.validate_endpoint

    def _no_key(*_args, **_kwargs):
        raise RuntimeError("缺少 API 密钥")

    ui.validate_endpoint = _no_key  # type: ignore[assignment]
    try:
        smart_nokey = ui.SmartGlossaryDialog(window, "我的世界")
        smart_nokey.show()
        app.processEvents()
        for width, height in SIZES:
            capture(smart_nokey, "smart_source_nokey", width, height)
        smart_nokey.close()
    finally:
        ui.validate_endpoint = original_validate  # type: ignore[assignment]

    # 6. Smart glossary candidate review（注入真实 builtin 候选）
    smart._candidates = [
        GlossaryCandidate("史蒂夫", "character", source="builtin", confidence=0.9),
        GlossaryCandidate("末影人", "enemy", source="builtin", confidence=0.9),
        GlossaryCandidate("钻石剑", "weapon", source="builtin", confidence=0.9),
        GlossaryCandidate("苦力怕", "enemy", source="builtin", confidence=0.9),
        GlossaryCandidate("附魔台", "item", source="builtin", confidence=0.9),
        GlossaryCandidate("下界", "location", source="builtin", confidence=0.9),
        GlossaryCandidate("末地", "location", source="builtin", confidence=0.9),
    ]
    smart._populate_review()
    app.processEvents()
    for width, height in SIZES:
        capture(smart, "smart_review", width, height)

    # 7. AI 401 friendly failure（_exec_dialog 换成非阻塞 show 后直接 grab message）
    smart._exec_dialog = lambda dialog: (
        dialog.show(),
        app.processEvents(),
    )
    message = smart._show_ai_error(
        AiEnhancementError("unauthorized", "HTTP 401：API Key 无效或未授权。", "https://api.deepseek.com")
    )
    app.processEvents()
    for width, height in SIZES:
        capture(message, "smart_ai_401", width, height)
    message.close()
    smart.close()

    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
