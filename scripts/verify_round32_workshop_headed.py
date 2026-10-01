"""R32 headed verification: 模型工坊在线 API 分组 + 两个新 API 卡.

- 「在线 API」tab 必须显示全部 6 张 API 卡（原空白）。
- 「主力转写」tab 不再混入 API 卡。
- 新卡 MAI-Transcribe-2 / Qwen-Audio-3.0-ASR-Flash 可见，参考指数渲染。
- 截图 → tmp/shots-round32/ 供 agy 评审。
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHOTS = ROOT / "tmp" / "shots-round32"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.model_workshop import (
    MODELS,
    ModelWorkshopPage,
    _browser_groups,
    model_is_online,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(condition), detail))
    print(f"[R32H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)
    return bool(condition)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(ROOT, {"models": {"qwen_asr_backend": "off"}})
    page.resize(1440, 900)
    page.show()
    app.processEvents()
    from PySide6.QtTest import QTest

    QTest.qWait(300)

    online_keys = {m.key for m in MODELS if model_is_online(m)}

    def visible_cards() -> set[str]:
        return {
            key
            for key, card in page._cards.items()
            if card.isVisibleTo(page)
        }

    # --- 在线 API tab ------------------------------------------------------
    page._set_role("api")
    QTest.qWait(200)
    api_visible = visible_cards()
    check("R1_api_tab_shows_all_online", api_visible == online_keys,
          f"visible={sorted(api_visible)}")
    check("R1_not_empty_label", not page.empty_label.isVisibleTo(page))
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.grab().save(str(SHOTS / "R1-api-tab.png"))
    print(f"[R32H] shot R1-api-tab.png", flush=True)

    # 新卡可见 + 名称正确
    names = {m.key: m.name for m in MODELS}
    check("R2_new_cards_present",
          {"mai_transcribe_2_word", "qwen_audio_asr_flash"} <= api_visible,
          f"mai={names['mai_transcribe_2']} qaf={names['qwen_audio_asr_flash']}")
    elided = {}
    for key in ("mai_transcribe_2_word", "qwen_audio_asr_flash"):
        label = page._cards[key].title_label
        full = getattr(label, "_full_text", None) or label.toolTip() or label.text()
        fm = label.fontMetrics()
        print(f"[R32H] diag {key}: width={label.width()} needed={fm.horizontalAdvance(full)} text={label.text()!r}", flush=True)
        if "…" in label.text():
            elided[key] = label.text()
    check("R2_titles_not_elided", not elided, f"elided={elided}")
    badges = {
        key: page._cards[key].kind_badge.text()
        for key in ("mai_transcribe_2_word", "qwen_api")
    }
    check("R2_badge_compact", all(t == "在线" for t in badges.values()), f"{badges}")

    # --- 主力转写 tab ------------------------------------------------------
    page._set_role("primary")
    QTest.qWait(200)
    primary_visible = visible_cards()
    leaked = primary_visible & online_keys
    check("R3_primary_tab_local_only", not leaked, f"leaked={sorted(leaked)}")
    check("R3_primary_not_empty", bool(primary_visible), f"count={len(primary_visible)}")
    page.grab().save(str(SHOTS / "R3-primary-tab.png"))
    print("[R32H] shot R3-primary-tab.png", flush=True)

    # --- 文字复核 tab（API 卡此前也混入这里） --------------------------------
    page._set_role("review")
    QTest.qWait(200)
    review_visible = visible_cards()
    leaked_review = review_visible & online_keys
    check("R4_review_tab_local_only", not leaked_review, f"leaked={sorted(leaked_review)}")

    # --- 详情面板切到新卡 ----------------------------------------------------
    page._set_role("api")
    QTest.qWait(150)
    page._view_model("mai_transcribe_2_word")
    QTest.qWait(200)
    page.grab().save(str(SHOTS / "R5-mai-detail.png"))
    print("[R32H] shot R5-mai-detail.png", flush=True)
    page._view_model("qwen_audio_asr_flash")
    QTest.qWait(200)
    page.grab().save(str(SHOTS / "R6-qwen-audio-detail.png"))
    print("[R32H] shot R6-qwen-audio-detail.png", flush=True)

    return finish(app, page)


def finish(app, page) -> int:
    try:
        page.close()
    except Exception:
        traceback.print_exc()
    ok = all(flag for _, flag, _ in RESULTS)
    print(f"[R32H] summary ok={ok} total={len(RESULTS)}", flush=True)
    app.processEvents()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
