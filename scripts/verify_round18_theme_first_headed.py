"""Headed verification for round 18: theme-first appearance + AI workshop.

  A. DOOM95 真身接管：应用 doom95 内置主题 → 暂停停在 cue 内 →
     视频层 source_kind == "fidelity"，且画布 fidelity 帧本身带主题设计：
     - 绿色 HUD 框像素（g 优势）存在
     - 枪灰亮字像素（高亮度）存在——不再是黑字
     - 红色泼溅像素（r 优势）存在
  B. AI 字幕工坊：页面入口打开对话框（对话式 UI、无字体/字号参数控件、
     范围语义、欢迎语）；截图。
  C. W4 卡与 AI 面板的工坊入口按钮存在且可见。
  D. 截图存 tmp/r18-verify 供 agy 读图评审。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = ROOT / "tmp" / "realproj" / "real-copy.2byteproj"
SHOTS = ROOT / "tmp" / "r18-verify"

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.web_theme import builtin_web_themes

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R18] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def wait_until(app, predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def color_stats(pixmap):
    """Scan the bottom 34% band: green-HUD / bright-text / red-splat ratios."""
    image = pixmap.toImage()
    width, height = image.width(), image.height()
    top = int(height * 0.66)
    total = green = bright = red = 0
    for y in range(top, height, 3):
        for x in range(0, width, 3):
            color = image.pixelColor(x, y)
            if color is None or color.alpha() < 40:
                continue
            total += 1
            r, g, b = color.red(), color.green(), color.blue()
            if g > 60 and g > r + 25 and g > b + 25:
                green += 1
            if (r + g + b) / 3 > 165:
                bright += 1
            if r > 80 and r > g + 45 and r > b + 45:
                red += 1
    denom = max(1, total)
    return green / denom, bright / denom, red / denom, total


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1700, 940)
    page.show()
    app.processEvents()
    page.open_project(PROJECT, skip_dirty_guard=True)
    if not wait_until(app, lambda: page.project is not None and page.video._startup_state == "READY", 25.0):
        check("project_ready", False, f"startup={page.video._startup_state}")
        return finish(page, app)
    check("project_ready", True, f"cues={len(page.project.cues)}")

    cues = page.project.cues
    target = next((c for c in cues if 30_000 <= c.start_ms <= 60_000), cues[0])
    page.select_cue(target.id)

    # ---- A) DOOM95 fidelity takeover + design pixels ----
    theme = builtin_web_themes()["doom95"].to_dict()
    assert page._apply_web_theme(target.id, theme)
    page._seek((target.start_ms + 500) / 1000.0)
    ok = wait_until(
        app,
        lambda: str(getattr(page, "_advanced_canvas_source_kind", "")) == "fidelity",
        timeout=45.0,
    )
    kind = str(getattr(page, "_advanced_canvas_source_kind", ""))
    check("doom95_fidelity_takes_over", ok, f"source_kind={kind}")
    time.sleep(0.5)
    app.processEvents()
    pixmap = getattr(page, "_advanced_cue_pixmap", None)
    if pixmap is None or pixmap.isNull():
        check("fidelity_pixmap_present", False)
    else:
        check("fidelity_pixmap_present", True, f"{pixmap.width()}x{pixmap.height()}")
        pixmap.save(str(SHOTS / "fidelity-frame.png"))
        green, bright, red, sampled = color_stats(pixmap)
        check("green_hud_pixels", green > 0.004, f"green={green:.4f}")
        check("bright_text_pixels", bright > 0.002, f"bright={bright:.4f}")
        check("red_splat_pixels", red > 0.0005, f"red={red:.4f} sampled={sampled}")

    # ---- B) AI workshop ----
    page._open_web_theme_workshop(target.id)
    dialog = getattr(page, "_web_theme_workshop", None)
    check("workshop_opens", dialog is not None and dialog.isVisible())
    if dialog is not None:
        check("workshop_is_conversational",
              not hasattr(dialog, "_font_combo") and not hasattr(dialog, "_size_spin")
              and dialog._chat is not None and dialog._input is not None)
        check("workshop_welcome", "AI 字幕工坊" in dialog._chat.toPlainText())
        dialog._scope.setCurrentIndex(0)
        check("workshop_scope_current", dialog._target_cue_ids() == [target.id])
        time.sleep(1.6)  # 演示带首帧渐进
        app.processEvents()
        dialog.grab().save(str(SHOTS / "workshop.png"))
        dialog.close()

    # ---- C) entry buttons（各按钮在自己所在的抽屉页上验证可见性）----
    drawer = getattr(page, "context_drawer", None)
    page.select_cue(target.id)
    updater = getattr(page, "_update_web_adjust_visibility", None)
    if callable(updater):
        updater()
    page.ai_suggestion_card.setVisible(True)
    page.ai_refine_row.setVisible(True)
    app.processEvents()

    def _switch_to(predicate):
        if drawer is None:
            return
        for index in range(drawer.count()):
            drawer.setCurrentIndex(index)
            app.processEvents()
            time.sleep(0.05)
            app.processEvents()
            if predicate():
                return

    _switch_to(lambda: bool(getattr(page, "web_adjust_host", None)) and page.web_adjust_host.isVisible())
    check("style_card_workshop_button",
          hasattr(page, "web_adjust_workshop") and page.web_adjust_workshop.isVisible())
    advanced = getattr(page, "web_adjust_host", None)
    if advanced is not None and not advanced.isHidden():
        advanced.parentWidget().grab().save(str(SHOTS / "style-web-adjust.png"))
    _switch_to(lambda: page.ai_suggestion_card.isVisible())
    check("ai_panel_workshop_button",
          hasattr(page, "ai_workshop_button") and page.ai_workshop_button.isVisible())
    page.grab().save(str(SHOTS / "window.png"))

    return finish(page, app)


def finish(page, app) -> int:
    page.close()
    app.processEvents()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n[R18] {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
