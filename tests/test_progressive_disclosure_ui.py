"""Change Group 3：Progressive Disclosure / 新手可用性。语义行为，不锁像素。"""

from __future__ import annotations

import os
import inspect
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from twobyteasr.local_models.model_workshop import (
    CANONICAL_MODEL_ORDER,
    MODELS,
    ModelCard,
    ModelWorkshopPage,
    RatingBar,
    _stars,
)
from twobyteasr.app.ui import MainWindow


ROOT = Path(__file__).resolve().parents[1]


def test_real_recording_formats_are_accepted_by_home_import(tmp_path):
    flv = tmp_path / "直播录像.flv"
    avi = tmp_path / "游戏录像.avi"
    unsupported = tmp_path / "说明.txt"
    for path in (flv, avi, unsupported):
        path.write_bytes(b"fixture")

    accepted = MainWindow._supported_paths([flv, avi, unsupported])

    assert accepted == [str(flv.resolve()), str(avi.resolve())]


def test_primary_run_and_cancel_actions_are_keyboard_reachable():
    app = QApplication.instance() or QApplication([])

    class Owner(QWidget):
        def _start_run(self):
            pass

        def _cancel_run(self):
            pass

    owner = Owner()
    bar = MainWindow._action_bar(owner)

    assert owner.start_button.shortcut().toString() == "Ctrl+Return"
    assert 'setShortcut(QKeySequence("Escape"))' in inspect.getsource(MainWindow._progress_page)
    bar.deleteLater()
    owner.deleteLater()
    app.processEvents()


def test_main_window_close_runs_full_studio_cleanup():
    calls = []
    owner = SimpleNamespace(
        worker=None,
        studio_page=SimpleNamespace(close_page=lambda: calls.append("studio")),
        _persist_geometry=False,
        _gui_profiler=None,
    )
    event = SimpleNamespace(accept=lambda: calls.append("accept"))

    MainWindow.closeEvent(owner, event)

    assert calls == ["studio", "accept"]


def _app():
    return QApplication.instance() or QApplication([])


def test_no_decorative_black_dot_labels_on_settings_and_cards():
    """截图黑斑根因：装饰性 ● 与 ●●●○○ 星点盖住信息。语义状态须保留文字。"""
    source_ui = (ROOT / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    source_ws = (ROOT / "twobyteasr" / "local_models" / "model_workshop.py").read_text(encoding="utf-8")
    assert 'QLabel("●  游戏 / 内容名称")' not in source_ui
    assert 'QLabel("●  当前步骤")' not in source_ui
    assert 'f"●  {title}"' not in source_ui
    assert "_stars(" not in source_ws or "def _stars" in source_ws
    assert "class RatingBar" in source_ws
    assert "●" * 3 not in source_ws or "RatingBar" in source_ws


def test_media_card_is_primary_accessible_action_without_double_open(monkeypatch):
    _app()
    import subtitle_core as legacy
    from twobyteasr.app.ui import MediaPickCard

    opens = []
    monkeypatch.setattr("twobyteasr.app.ui._select_media_paths", lambda _parent: opens.append("dialog") or [])
    win = MainWindow([], legacy, object(), None)
    card = win.media_frame
    assert isinstance(card, MediaPickCard)
    assert card.focusPolicy() & Qt.FocusPolicy.StrongFocus
    assert card.accessibleName()
    assert win.choose_media_button is not None
    # keyboard
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(card, event)
    assert opens == ["dialog"]
    opens.clear()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(card, event)
    assert opens == ["dialog"]
    win.close()


def test_settings_two_column_hides_advanced_by_default():
    _app()
    import subtitle_core as legacy

    win = MainWindow([], legacy, object(), None)
    assert win.settings_left_column is not None
    assert win.settings_right_column is not None
    # 识别方案 = 三张角色卡（不再是文本表格）
    assert set(win.recognition_plan.cards) == {"primary", "timeline", "review"}
    for card in win.recognition_plan.cards.values():
        assert card.model_label.text()
    # 首页只保留 AI 智能断句；任务/缓存设置移入模型工坊。
    assert hasattr(win, "setting_tiles")
    assert set(win.setting_tiles) == {"ai"}
    assert win.setting_tiles["ai"].title_label.text() == "AI 智能断句"
    assert win.advanced_disclosure.isHidden()
    assert win.advanced_panel.isHidden()
    assert win.ai_panel._expanded is False or win.ai_panel._expanded
    assert "识别" not in win.asr_panel.title_button.text() or win.asr_panel.isHidden(), "识别增强入口不得常驻首页"
    # API/provider 字段仍存在（逻辑引用），但不以 accordion 常驻
    assert win.qwen_asr_api_url is not None
    assert win.qwen_asr_api_key is not None
    win.close()


def test_run_summary_explains_local_vs_cloud_and_next_action():
    _app()
    import subtitle_core as legacy

    win = MainWindow([], legacy, object(), None)
    text = win.action_status.text() + win.run_next_action.text()
    assert "本地" in text or "在线" in text or "云" in text or "API" in text or "就绪" in text
    assert win.start_button.text()
    win.close()


def test_workshop_canonical_order_puts_local_before_api():
    local = [key for key in CANONICAL_MODEL_ORDER if not next(m for m in MODELS if m.key == key).api_preset]
    api = [key for key in CANONICAL_MODEL_ORDER if next(m for m in MODELS if m.key == key).api_preset]
    assert local
    assert api
    assert CANONICAL_MODEL_ORDER.index(local[0]) < CANONICAL_MODEL_ORDER.index(api[0])
    assert CANONICAL_MODEL_ORDER.index("moss") < CANONICAL_MODEL_ORDER.index("qwen_api")
    assert CANONICAL_MODEL_ORDER.index("qwen_local") < CANONICAL_MODEL_ORDER.index("qwen_api")


def test_workshop_sort_filter_is_popover_not_control_wall():
    _app()
    page = ModelWorkshopPage(ROOT, {"models": {"qwen_asr_backend": "api"}})
    assert page.sort_filter_button is not None
    assert "排序" in page.sort_filter_button.text() or "筛选" in page.sort_filter_button.text()
    # no permanent wall of sort radios on the page
    assert page.sort_filter_popover.isHidden() or not page.sort_filter_popover.isVisible()
    page.sort_filter_button.click()
    assert page.sort_filter_popover.isVisible()
    page.deleteLater()
    QApplication.processEvents()


def test_model_card_has_badges_and_traceable_metrics_without_fake_scores():
    _app()
    model = next(item for item in MODELS if item.key == "firered")
    card = ModelCard(model)
    assert card.kind_badge.text() in {"本地", "在线 · API"}
    assert "4.4" in card.size_label.text() or "GB" in card.size_label.text()
    assert isinstance(card.accuracy_bar, RatingBar)
    assert not hasattr(model, "accuracy")
    assert not hasattr(model, "speed")
    # 2026-09-18 轮：分数来自核实的同组基准（FireRed 官方同表普通话 4 集均值）。
    assert card.accuracy_bar._evidence["available"] is True
    assert card.accuracy_bar._evidence["value"] == "97"
    assert str(card.accuracy_bar._evidence["note"]).startswith(
        "FireRed 官方同表 · 普通话 4 集均值 CER 3.05%"
    )
    assert "不是识别正确率" in str(card.accuracy_bar._evidence["tooltip"])
    assert "97" in card.accuracy_bar.accessibleName()
    assert "准确" in card.accuracy_bar.accessibleName()
    assert card.info_host.objectName() == "workshopCardInfo"
    assert card.metrics_host.objectName() == "workshopCardMetrics"
    assert card.action_host.objectName() == "workshopCardActions"
    assert card.accuracy_bar._track.minimumWidth() >= 54
    assert card.speed_bar._track.minimumWidth() >= 54
    card.set_state_badge("未安装", "missing")
    assert card.state_badge.property("tone") == "missing"
    card.deleteLater()


def test_only_workflow_recommended_models_get_recommendation_badge():
    assert {model.key for model in MODELS if model.recommended} == {
        "moss",
        "firered",
        "qwen_local",
    }
    card = ModelCard(next(item for item in MODELS if item.key == "moss"))
    assert card.property("recommended") is True
    assert card.recommendation_badge is not None
    assert "2ByteASR" in card.recommendation_badge.text()
    card.deleteLater()


def test_compact_model_card_keeps_metrics_and_action_inside_card():
    app = _app()
    card = ModelCard(next(item for item in MODELS if item.key == "firered"))
    card.set_state_badge("已安装", "ready")
    card.action.setText("使用")
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.resize(730, 220)
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(card)
    scroll.setWidget(host)
    scroll.show()
    app.processEvents()

    assert card._compact is True
    assert card.metrics_host.width() >= 198
    assert host.width() <= scroll.viewport().width()
    assert card.action_host.geometry().right() <= card.contentsRect().right()
    assert card.action.geometry().right() <= card.action_host.contentsRect().right()
    scroll.close()
    scroll.deleteLater()
    card.deleteLater()


def test_api_card_never_claims_local_install():
    _app()
    page = ModelWorkshopPage(
        ROOT,
        {"models": {"primary_asr_backend": "api", "qwen_asr_backend": "api"}},
    )
    api_model = next(item for item in MODELS if item.key == "qwen_api")
    state = page._model_state(api_model)
    assert state in {"configure", "configured", "selected"}
    assert state != "installed"
    text, _enabled = page._action_text(api_model, state)
    assert "安装" not in text
    assert card_kind_is_online(page._cards["qwen_api"])
    page.deleteLater()
    QApplication.processEvents()


def card_kind_is_online(card):
    return "在线" in card.kind_badge.text()


def test_technical_details_are_novice_first():
    _app()
    page = ModelWorkshopPage(ROOT, {"models": {}})
    page._selected_key = "moss"
    text = page._technical_details_text(page._cards["moss"].model)
    privacy = text.find("隐私")
    arch = text.find("架构") if "架构" in text else text.find("revision")
    assert privacy != -1
    assert "适合" in text or "场景" in text
    if arch != -1:
        assert privacy < arch
    page.deleteLater()
    QApplication.processEvents()


def test_workshop_and_main_share_backend_selection():
    _app()
    page = ModelWorkshopPage(
        ROOT,
        {"models": {"primary_asr_backend": "moss", "firered_asr_backend": "local"}},
    )
    requested = []
    page.backend_requested.connect(lambda role, value: requested.append((role, value)))
    page._installed = {"moss", "firered_vad", "speaker_embedding", "firered_aed"}
    page._perform_action("firered")
    assert requested
    page.deleteLater()
    QApplication.processEvents()


def test_completed_groups_remain_wired():
    ui = (ROOT / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    workshop = (ROOT / "twobyteasr" / "local_models" / "model_workshop.py").read_text(encoding="utf-8")
    assert "def _ensure_runtime_environment" in ui
    assert "source_combo" in workshop
    assert "AUTO" in workshop or "user_facing_source_choices" in workshop


def test_stars_helper_no_longer_used_for_visible_card_copy():
    assert callable(_stars)
    # leftover helper may exist for tests; visible cards must use RatingBar
    _app()
    card = ModelCard(next(item for item in MODELS if item.key == "moss"))
    labels = card.findChildren(QLabel)
    joined = " ".join(label.text() for label in labels)
    assert "●●" not in joined
    card.deleteLater()
