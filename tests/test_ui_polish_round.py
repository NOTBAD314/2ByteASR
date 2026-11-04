"""MAIN UI + GLOSSARY PRODUCT PASS 轮行为测试。

- B3：accordion 整行单击只 toggle 一次，Enter/Space 支持，summary 不双触发
- B2：识别方案状态行 + 唯一恢复动作（缺模型 / API 未配置）
- C：术语库 IA —— 创建游戏在顶部、删除游戏独立、添加术语在列表前、
  搜索默认折叠、内置参考默认折叠、删除术语与删除游戏分离
- D：智能建词无 API 流程（checkbox 禁用 + 提示）
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from twobyteasr.app.ui import (
    CollapsibleFrame,
    MainWindow,
    TermLibraryDialog,
)

ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def _main_window(media=()):
    import subtitle_core as legacy

    return MainWindow(list(media), legacy, object(), None)


# ---------------------------------------------------------------- B3 accordion

def test_accordion_click_anywhere_toggles_exactly_once():
    _app()
    frame = CollapsibleFrame("语音识别增强后端", "fa5s.microphone-alt", expanded=False)
    frame.show()
    QTest.qWaitForWindowExposed(frame)

    # 点击 header 空白区
    header = frame.header
    QTest.mouseClick(header, Qt.MouseButton.LeftButton)
    assert frame._expanded is True, "点击 header 空白区应展开"
    QTest.mouseClick(header, Qt.MouseButton.LeftButton)
    assert frame._expanded is False, "再点应收起"

    # 点击摘要（透明穿透到 header）
    QTest.mouseClick(frame.summary_label, Qt.MouseButton.LeftButton)
    assert frame._expanded is True, "点击摘要应 toggle（经 header 一次）"
    QTest.mouseClick(frame.summary_label, Qt.MouseButton.LeftButton)
    assert frame._expanded is False

    # 点击标题按钮：一次 toggle
    QTest.mouseClick(frame.title_button, Qt.MouseButton.LeftButton)
    assert frame._expanded is True
    frame.deleteLater()


def test_accordion_enter_and_space_toggle_once():
    _app()
    frame = CollapsibleFrame("AI 模型与密钥", "fa5s.project-diagram", expanded=False)
    frame.show()
    frame.header.setFocus()
    QTest.keyClick(frame.header, Qt.Key.Key_Space)
    assert frame._expanded is True, "Space 应展开"
    QTest.keyClick(frame.header, Qt.Key.Key_Return)
    assert frame._expanded is False, "Enter 应收起"
    frame.deleteLater()


def test_accordion_summary_child_does_not_double_toggle():
    _app()
    frame = CollapsibleFrame("高级选项", "fa5s.sliders-h", expanded=False)
    frame.show()
    # summary_label 是 WA_TransparentForMouseEvents：点击直接落到 header，单次。
    toggles = []
    frame.toggled.connect(lambda value: toggles.append(value))
    QTest.mouseClick(frame.summary_label, Qt.MouseButton.LeftButton)
    assert toggles == [True], f"必须只发一次 toggled，实际 {toggles}"
    frame.deleteLater()


# ---------------------------------------------------------------- B2 识别方案（角色卡）

def test_recognition_plan_shows_three_role_cards_and_ready_state(monkeypatch):
    _app()
    import subtitle_core as legacy

    # Pin a fully-ready local environment: the machine's own saved choices
    # (e.g. review backend off) must not leak into this contract test.
    ready_models = {
        "primary_asr_backend": "moss",
        "qwen_asr_backend": "local",
        "firered_asr_backend": "local",
    }
    for key, value in ready_models.items():
        monkeypatch.setitem(legacy.RUNTIME_SETTINGS.setdefault("models", {}), key, value)
    import twobyteasr.app.ui as ui_mod

    monkeypatch.setattr(
        ui_mod,
        "installed_model_keys",
        lambda _root: {"moss", "firered_vad", "speaker_embedding", "qwen_asr", "firered_aed"},
    )
    win = _main_window()
    plan = win.recognition_plan
    assert set(plan.cards) == {"primary", "timeline", "review"}
    for role, card in plan.cards.items():
        assert card.model_label.text(), f"{role} 卡必须显示模型名"
        text = card.model_label.text() + card.status_badge.text() + card.kind_badge.text()
        assert "本地" in text or "在线" in text, f"{role} 卡应标本地/在线"
        assert "已就绪" in card.status_badge.text() or "已配置" in card.status_badge.text()
        assert card.recovery.isHidden(), "全就绪时无恢复动作"
    # CTA 状态条
    assert "已就绪" in win.action_status.text()
    win.close()


def test_recognition_card_recovery_appears_when_api_key_missing(monkeypatch):
    _app()
    for module in ("twobyteasr.app.ui", "twobyteasr.providers.endpoint_editor_ui"):
        monkeypatch.setattr(f"{module}.resolve_api_key", lambda _stage: ("", "missing"))
    monkeypatch.setattr("twobyteasr.app.ui.installed_model_keys", lambda _root: set())
    win = _main_window()
    win.primary_asr_backend.setCurrentIndex(win.primary_asr_backend.findData("api"))
    win._refresh_asr_summary()
    card = win.recognition_plan.cards["primary"]
    assert "未配置" in card.status_badge.text()
    assert not card.recovery.isHidden()
    assert "配置 API" in card.recovery.text()
    win.close()


def test_recognition_card_recovery_points_to_workshop_when_model_missing(monkeypatch):
    _app()
    monkeypatch.setattr("twobyteasr.app.ui.installed_model_keys", lambda _root: set())
    win = _main_window()
    win._refresh_asr_summary()
    card = win.recognition_plan.cards["primary"]
    assert "需要下载" in card.status_badge.text()
    assert not card.recovery.isHidden()
    assert "安装模型" in card.recovery.text()
    win.close()


def test_recognition_card_click_emits_role(monkeypatch):
    _app()
    win = _main_window()
    opened = []
    win.recognition_plan.role_requested.disconnect(win._open_model_picker)
    win.recognition_plan.role_requested.connect(opened.append)
    card = win.recognition_plan.cards["timeline"]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert opened == ["timeline"], "点击角色卡应打开对应角色的 Model Picker"
    # 键盘 Enter / Space 同样触发
    card.setFocus()
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert len(opened) == 2
    QTest.keyClick(card, Qt.Key.Key_Space)
    assert len(opened) == 3
    win.close()


# ---------------------------------------------------------------- C 术语库 IA

def _open_terms(win) -> TermLibraryDialog:
    win.show()
    win._manage_terms()
    _app().processEvents()
    return win.term_library_page.library


def test_glossary_new_game_toolbar_is_above_sidebar_list():
    _app()
    win = _main_window()
    dialog = _open_terms(win)
    # 2026-10-17 redesign: 「新建」 opens the small form above the library list.
    dialog.sidebar_new_button.click()
    _app().processEvents()
    assert dialog.new_library_panel.isVisible()
    assert dialog.game_input.mapTo(dialog, dialog.game_input.rect().topLeft()).y() < \
        dialog.game_list.mapTo(dialog, dialog.game_list.rect().topLeft()).y()
    assert dialog.add_game_button is not None
    assert dialog.delete_game_button is not None
    dialog.close()
    win.close()


def test_glossary_add_term_is_before_lists_and_search_sits_above_the_table():
    _app()
    win = _main_window()
    dialog = _open_terms(win)
    # 添加术语输入在列表区域之前（有词时在列表前；空态时在空态引导前）
    shown = dialog.listing if dialog.listing.isVisible() else dialog.listing_empty
    list_area_top = shown.mapTo(dialog, shown.rect().topLeft()).y()
    assert dialog.term_editor.mapTo(dialog, dialog.term_editor.rect().topLeft()).y() < list_area_top
    # 2026-10-17 redesign: the term search is always shown, in the tool row above the table.
    assert dialog.search.isVisible()
    assert dialog.search.mapTo(dialog, dialog.search.rect().topLeft()).y() < list_area_top
    dialog.close()
    win.close()


def test_glossary_delete_game_and_delete_term_are_separate():
    _app()
    win = _main_window()
    dialog = _open_terms(win)
    # 2026-10-25（用户）：自带词库也能删除（隐藏，可在「新建」里恢复），但仍不能改名
    def _item_for(name):
        for index in range(dialog.game_list.count()):
            item = dialog.game_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) == name:
                return item
        return None

    protected = _item_for("洛克王国：世界")
    if protected:
        dialog.game_list.setCurrentItem(protected)
        _app().processEvents()
        assert dialog.delete_game_button.isEnabled(), "自带词库可删除"
        assert not dialog.rename_game_button.isEnabled(), "自带词库不能改名"
    user_game = _item_for("我的世界")
    if user_game:
        dialog.game_list.setCurrentItem(user_game)
        _app().processEvents()
        assert dialog.delete_game_button.isEnabled(), "用户游戏可删除"
    # 删除所选术语：未选中时禁用
    assert not dialog.remove_terms.isEnabled()
    # 底部动作不含删除游戏语义（文案固定为删除所选术语）
    assert "删除所选术语" in dialog.remove_terms.text()
    dialog.close()
    win.close()


def test_glossary_smart_build_entry_opens_with_game_context(monkeypatch):
    _app()
    from twobyteasr.app.ui import SmartGlossaryDialog

    win = _main_window()
    dialog = _open_terms(win)
    user_game = dialog.game_list.findItems("我的世界", Qt.MatchFlag.MatchExactly)
    if user_game:
        dialog.game_list.setCurrentItem(user_game[0])
    dialog.smart_build_button.click()
    _app().processEvents()
    opened = win._modal_host._current_content
    assert isinstance(opened, SmartGlossaryDialog)
    assert opened.game_name == dialog.state["game"]
    win._modal_host._request_close()
    win.close()


# ---------------------------------------------------------------- D 智能建词

def test_smart_build_without_api_key_disables_ai_enhancement(monkeypatch):
    _app()
    from twobyteasr.app.ui import SmartGlossaryDialog

    def no_key(_stage):
        return "", "missing"

    monkeypatch.setattr("twobyteasr.app.ui.resolve_api_key", no_key)
    monkeypatch.setattr("twobyteasr.providers.endpoint_editor_ui.resolve_api_key", no_key)
    monkeypatch.setattr(
        "twobyteasr.glossary.main_ui_smart_glossary.validate_endpoint",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("缺少 API 密钥")),
    )
    win = _main_window()
    dialog = SmartGlossaryDialog(win, "我的世界")
    dialog.show()
    assert not dialog.ai_check.isEnabled(), "无 API Key 时 AI 增强必须禁用"
    assert "未配置 API" in dialog.ai_status.text()
    # 基础来源仍可用（三 source 卡同层）
    assert set(dialog._source_cards) == {"builtin", "wiki", "pasted"}
    assert all(card.isEnabled() for card in dialog._source_cards.values())
    dialog.close()
    win.close()


def test_smart_build_external_ai_prompt_enters_tsv_preview_flow(monkeypatch):
    app = _app()
    from twobyteasr.app.ui import SmartGlossaryDialog

    monkeypatch.setattr(
        "twobyteasr.glossary.main_ui_smart_glossary.validate_endpoint",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("缺少 API 密钥")),
    )
    win = _main_window()
    dialog = SmartGlossaryDialog(win, "原神")
    dialog.show()
    dialog.copy_ai_prompt_button.click()
    app.processEvents()

    assert "原神" in app.clipboard().text()
    assert "TSV" in app.clipboard().text()
    assert dialog._mode() == "ai_tsv"
    assert not dialog.pasted_editor.isHidden()
    assert dialog.extract_button.text() == "解析并预览"
    dialog.close()
    win.close()


# 2026-10-25 user report: DeepSeek connected, yet 智能建词 said "API 密钥无效" and
# 「配置 API」 led back to the same dialog.

def _smart_dialog_with_key(monkeypatch, *, startup_page="recognition"):
    import subtitle_core as legacy
    from twobyteasr.app.ui import SmartGlossaryDialog

    monkeypatch.setattr("twobyteasr.glossary.main_ui_smart_glossary.validate_endpoint", lambda *a, **k: None)
    win = MainWindow([], legacy, object(), None, startup_page=startup_page)
    return win, SmartGlossaryDialog(win, "鸣潮")


@pytest.mark.parametrize(
    ("code", "text", "has_config"),
    [
        ("unauthorized", "当前 API 密钥无效或未授权", True),
        ("no_balance", "余额不足", True),
        ("rate_limited", "请求太频繁", False),
        ("bad_response", "没有返回完整的整理结果", False),
        ("unavailable", "暂时连不上 AI 服务", False),
    ],
)
def test_smart_build_ai_error_box_names_the_actual_cause(monkeypatch, code, text, has_config):
    _app()
    from twobyteasr.glossary.smart_glossary import AiEnhancementError

    win, dialog = _smart_dialog_with_key(monkeypatch)
    shown = {}

    def capture(message):
        shown["text"] = message.informativeText()
        shown["buttons"] = [button.text() for button in message.buttons()]

    monkeypatch.setattr(dialog, "_exec_dialog", capture)
    dialog._show_ai_error(AiEnhancementError(code, "detail", "https://api.deepseek.com/v1/chat/completions", "deepseek-flash"))
    assert text in shown["text"]
    if code != "unauthorized":
        assert "密钥" not in shown["text"]
    assert ("配置 API" in shown["buttons"]) is has_config
    assert "查看详情" in shown["buttons"] and "继续无 AI 建词" in shown["buttons"]
    dialog.close()
    win.close()


@pytest.mark.parametrize("startup_page", ["recognition", "project_library"])
def test_smart_build_config_api_opens_the_ai_settings_window(monkeypatch, startup_page):
    app = _app()
    from twobyteasr.glossary.smart_glossary import AiEnhancementError

    win, dialog = _smart_dialog_with_key(monkeypatch, startup_page=startup_page)
    dialog.show()

    def click_config(message):
        next(button for button in message.buttons() if button.text() == "配置 API").click()

    monkeypatch.setattr(dialog, "_exec_dialog", click_config)
    dialog._show_ai_error(AiEnhancementError("unauthorized", "HTTP 401", "u", "m"))
    app.processEvents()
    settings = getattr(win, "_ai_settings_dialog", None)
    assert settings is not None and settings.objectName() == "aiSettingsDialog"
    assert settings.isVisible()
    refreshed = []
    monkeypatch.setattr(dialog, "_refresh_ai_state", lambda: refreshed.append(True))
    settings.reject()
    for _ in range(60):  # SpringDialog animates its close before ``finished``
        if refreshed:
            break
        QTest.qWait(50)
    assert refreshed == [True], "关掉 AI 设置后智能建词要重新读取 AI 状态"
    assert win._ai_settings_dialog is None
    dialog.close()
    win.close()


def test_smart_build_pasted_ai_table_is_parsed_as_table_without_ai_call(monkeypatch):
    _app()
    from twobyteasr.glossary import smart_glossary
    from twobyteasr.glossary.main_ui_smart_glossary import SmartGlossaryWorker

    def no_ai(*_args, **_kwargs):
        raise AssertionError("贴进来的 AI 表不再二次 AI 增强")

    monkeypatch.setattr(smart_glossary, "ai_enhance", no_ai)
    text = "标准词\t分类\t别名或常见错写\n玄方地界\t地点\tげんぽうちかい\n今汐\t角色\t金汐\n"
    worker = SmartGlossaryWorker(_FakeLegacy(), "鸣潮", "pasted", text, {"api_key": "k", "url": "u", "model": "m"})
    results = []
    worker.completed.connect(lambda _game, candidates, error: results.append((candidates, error)))
    worker.failed.connect(lambda _game, message: results.append(("failed", message)))
    worker.run()
    (candidates, error), = results
    assert error is None
    assert [(c.term, c.category, c.aliases) for c in candidates] == [
        ("玄方地界", "location", ("げんぽうちかい",)),
        ("今汐", "character", ("金汐",)),
    ]


def test_smart_build_back_returns_the_stepper_to_step_one(monkeypatch):
    _app()
    from twobyteasr.glossary.smart_glossary import GlossaryCandidate

    win, dialog = _smart_dialog_with_key(monkeypatch)
    dialog._candidates = [GlossaryCandidate("今汐", "character", source="pasted")]
    dialog._populate_review()
    assert dialog._step_labels[1].property("active") and dialog.source_summary.isHidden()
    dialog._back_to_sources()
    assert dialog._step_labels[0].property("active") and not dialog._step_labels[1].property("active")
    assert not dialog.source_summary.isHidden()
    dialog.close()
    win.close()


class _FakeLegacy:
    pass
