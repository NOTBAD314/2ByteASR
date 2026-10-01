"""R33 headed: API 使用链——当前 API 副标题/组合卡标签/MAI 图标/api 方案。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHOTS = ROOT / "tmp" / "shots-round33"

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.model_workshop import MODELS, ModelWorkshopPage
from twobyteasr.recognition_plans import RECOGNITION_PLANS

RESULTS = []


def check(label, condition, detail=""):
    RESULTS.append(bool(condition))
    print(f"[R33H] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    settings = {
        "models": {
            "qwen_asr_backend": "off",
            "primary_asr_backend": "api",
            "qwen_asr_api_provider": "openrouter_word",
            "qwen_asr_api_model": "microsoft/mai-transcribe-2",
            "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
        }
    }
    page = ModelWorkshopPage(ROOT, settings)
    page.resize(1440, 900)
    page.show()
    app.processEvents()
    QTest.qWait(300)

    page._set_role("api")
    QTest.qWait(200)
    check("R1_api_tab_current_label", "OpenRouter" in page.role_subtitle.text()
          and "microsoft/mai-transcribe-2" in page.role_subtitle.text(),
          page.role_subtitle.text())
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.grab().save(str(SHOTS / "R1-api-tab-current.png"))

    # 组合卡（左侧当前组合）primary 行应显示 provider·model
    combo_text = page.combo_model_labels["primary"].text()
    check("R2_combo_label", "OpenRouter" in combo_text and "mai-transcribe-2" in combo_text, combo_text)

    # MAI 图标：不再用 openai.png（用 fa5b.microsoft 回退）
    mai = next(m for m in MODELS if m.key == "mai_transcribe_2")
    check("R3_mai_icon", mai.logo_asset is None and mai.icon_name == "fa5b.microsoft")
    icon = page._cards["mai_transcribe_2_word"].property("icon") if page._cards.get("mai_transcribe_2") else None
    del icon
    page._view_model("mai_transcribe_2_word")
    QTest.qWait(200)
    card = page._cards.get("mai_transcribe_2")
    if card is not None:
        scroll = getattr(page, "cards_scroll", None)
        if scroll is None:
            from PySide6.QtWidgets import QScrollArea

            node = card.parentWidget()
            while node is not None:
                if isinstance(node, QScrollArea):
                    scroll = node
                    break
                node = node.parentWidget()
        if scroll is not None:
            scroll.ensureWidgetVisible(card)
            QTest.qWait(150)
    check("R5_mai_card_visible", card is not None and card.isVisibleTo(page))
    page.grab().save(str(SHOTS / "R3-mai-detail.png"))

    # api 方案存在于识别方案清单
    check("R4_api_plan", "api" in [p.key for p in RECOGNITION_PLANS])

    ok = all(RESULTS)
    print(f"[R33H] summary ok={ok} total={len(RESULTS)}", flush=True)
    try:
        page.close()
    except Exception:
        traceback.print_exc()
    QTimer.singleShot(200, app.quit)
    app.exec()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
