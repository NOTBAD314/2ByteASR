import os

from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from twobyteasr.recognition.service import MediaResult, QueueResult
from twobyteasr.app.ui import (
    AMBER,
    CORAL,
    GREEN,
    SURFACE,
    CompletionDialog,
    FramelessPopupCombo,
    ProgressPhaseCard,
    _ComboPopup,
    _completion_notification_spec,
    parse_ai_game_terms,
    persist_ai_configuration,
    request_ai_game_terms,
    term_library_game_names,
)


APP = QApplication.instance() or QApplication([])


def test_active_phase_color_feedback_uses_a_low_frequency_timer():
    app = QApplication.instance() or QApplication([])
    card = ProgressPhaseCard("fa5s.wave-square", "本地识别", "转写与主播", AMBER)
    card.set_state("active")

    assert card._pulse.interval() == 900
    assert card._pulse.timerType() == Qt.TimerType.CoarseTimer
    assert card._pulse.isActive()
    card.set_state("done")
    assert not card._pulse.isActive()
    card.deleteLater()
    app.processEvents()


def test_elapsed_timer_uses_precise_short_heartbeat(monkeypatch):
    # The concrete timer is built in MainWindow; its contract is intentionally
    # source-level here so the test does not require loading models or settings UI.
    from pathlib import Path

    source = (Path(__file__).parents[1] / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    assert "setTimerType(Qt.TimerType.PreciseTimer)" in source
    assert "self._progress_timer.setInterval(200)" in source


def test_ai_form_can_be_saved_without_starting_a_subtitle_run(monkeypatch):
    calls = []
    saved_keys = []

    class FakeLegacy:
        def configure_runtime_llms(self, models, **kwargs):
            calls.append((models, kwargs))

    monkeypatch.setattr("twobyteasr.app.ui.resolve_api_key", lambda stage: ("", "未配置"))
    monkeypatch.setattr(
        "twobyteasr.app.ui.read_api_key",
        lambda _provider, _base_url="": ("", "未配置"),
    )
    monkeypatch.setattr(
        "twobyteasr.app.ui.save_api_key_for",
        lambda provider, base_url, key: saved_keys.append((provider, base_url, key)),
    )
    polish = {
        "provider": "custom",
        "model": "custom-polish",
        "base_url": "https://polish.example/v1",
        "key": "",
    }
    group = {
        "provider": "bailian",
        "model": "qwen3.7-flash-2026-07-15",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key": "new-local-key",
    }

    result = persist_ai_configuration(
        FakeLegacy(),
        polish,
        group,
        unified=True,
        share_key=True,
        require_ready=False,
    )

    assert not result["missing_keys"]
    assert calls[0][0]["polish_provider"] == "bailian"
    assert calls[0][0]["polish_model"] == "qwen3.7-flash-2026-07-15"
    assert calls[0][0]["group_model"] == "qwen3.7-flash-2026-07-15"
    assert calls[0][1]["group_key"] == "new-local-key"
    assert calls[0][1]["unified_glm_processing"] is True
    saved_scope = (
        "bailian",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "new-local-key",
    )
    assert saved_keys == [saved_scope, saved_scope]


def test_ai_grouping_can_be_disabled_without_group_key(monkeypatch):
    calls = []

    class FakeLegacy:
        def configure_runtime_llms(self, models, **kwargs):
            calls.append((models, kwargs))

    monkeypatch.setattr(
        "twobyteasr.app.ui.resolve_api_key",
        lambda stage: ("polish-key", "env:test") if stage == "polish" else ("", "missing"),
    )
    monkeypatch.setattr(
        "twobyteasr.app.ui.read_api_key",
        lambda _provider, _base_url="": ("", "未配置"),
    )
    polish = {
        "provider": "bailian",
        "model": "polish-model",
        "base_url": "https://polish.example/v1",
        "key": "",
    }
    group = {
        "provider": "bailian",
        "model": "unused-group-model",
        "base_url": "https://group.example/v1",
        "key": "",
    }

    result = persist_ai_configuration(
        FakeLegacy(),
        polish,
        group,
        unified=True,
        share_key=True,
        require_ready=True,
        use_ai_grouping=False,
    )

    assert result["missing_keys"] == ()
    assert calls[0][1]["use_ai_grouping"] is False
    assert calls[0][1]["unified_glm_processing"] is False
    assert calls[0][1]["share_key"] is False


def test_ui_has_explicit_ai_save_action_independent_of_start():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    assert 'AnimatedButton("保存 AI 配置")' in source
    assert "self.save_ai_button.clicked.connect" in source
    assert "require_ready=True" in source


def test_ui_has_nonblocking_verified_update_flow():
    from pathlib import Path

    app_dir = Path(__file__).parents[1] / "twobyteasr" / "app"
    # The update threads moved to update_dialog.py on 2026-10-15.
    source = "".join((app_dir / name).read_text(encoding="utf-8") for name in ("ui.py", "update_dialog.py"))
    assert 'AnimatedButton("检查更新")' in source
    assert "class UpdateCheckWorker(QThread)" in source
    assert "class UpdateDownloadWorker(QThread)" in source
    assert "launch_update_helper(Path(package_path), checksum" in source


def test_model_workshop_has_obvious_header_return_action():
    source = (Path(__file__).parents[1] / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    assert 'AnimatedButton("返回字幕识别")' in source
    assert 'self.return_recognition_button.setObjectName("outline")' in source
    assert "self.return_recognition_button.setVisible(" in source
    assert "self.term_library_page" in source


def test_term_library_indexes_games_without_requiring_main_page_selection():
    import twobyteasr.app.ui as ui_module
    from twobyteasr.glossary.main_ui_glossary import (
        term_library_game_names as canonical_term_library_game_names,
    )

    class FakeLegacy:
        BUILTIN_GAME_PROFILES = ("绝区零", "洛克王国：世界")

        @staticmethod
        def canonicalize_runtime_game_name(value):
            return str(value or "").strip()

        @staticmethod
        def runtime_game_identity(value):
            return str(value or "").replace("：", "").replace(":", "").lower()

        @staticmethod
        def load_game_profiles():
            return {"明日方舟": {}}

        @staticmethod
        def load_runtime_game_history():
            return ["原神", "绝区零"]

        @staticmethod
        def load_learned_term_payload():
            return {"games": {"arknightsendfield": {"game": "明日方舟终末地"}}}

    assert ui_module.term_library_game_names is canonical_term_library_game_names
    assert term_library_game_names is canonical_term_library_game_names
    assert term_library_game_names(FakeLegacy(), "") == [
        "绝区零",
        "洛克王国：世界",
        "明日方舟",
        "原神",
        "明日方舟终末地",
    ]


def test_ai_game_terms_are_bounded_deduplicated_and_source_reviewable():
    payload = """前言\n{"terms":[
        {"term":"三月七","category":"角色","sources":["https://example.com/1"]},
        {"term":"三月七","category":"重复","sources":[]},
        {"term":"  开拓者  ","category":"角色","sources":["http://unsafe.test"]},
        {"term":"x","category":"无效","sources":[]}
    ]}\n结尾"""

    assert parse_ai_game_terms(payload) == [
        {"term": "三月七", "category": "角色", "sources": ["https://example.com/1"]},
        {"term": "开拓者", "category": "角色", "sources": []},
    ]


def test_ai_game_term_search_forces_bailian_web_search():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"terms":[{"term":"星穹列车","category":"阵营","sources":["https://example.com"]}]}'
                        }
                    }
                ]
            }

    class FakeRequests:
        @staticmethod
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

    result = request_ai_game_terms(
        {
            "provider": "bailian",
            "model": "qwen3.7-flash",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "api_key": "secret",
        },
        "崩坏：星穹铁道",
        requests_module=FakeRequests,
    )

    assert result[0]["term"] == "星穹列车"
    assert calls[0][1]["json"]["enable_search"] is True
    assert calls[0][1]["json"]["search_options"]["forced_search"] is True
    assert "崩坏：星穹铁道" in calls[0][1]["json"]["messages"][1]["content"]


def test_ai_game_term_search_accepts_other_openai_compatible_models_without_bailian_flags():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"terms":[{"term":"巡猎星神","category":"设定","sources":[]}]}'
                        }
                    }
                ]
            }

    class FakeRequests:
        @staticmethod
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

    result = request_ai_game_terms(
        {
            "provider": "custom",
            "model": "deepseek-chat",
            "base_url": "https://api.example.com/v1",
            "url": "https://api.example.com/v1/chat/completions",
            "api_key": "secret",
        },
        "崩坏：星穹铁道",
        requests_module=FakeRequests,
    )

    assert result[0]["term"] == "巡猎星神"
    assert calls[0][0] == "https://api.example.com/v1/chat/completions"
    assert calls[0][1]["json"]["model"] == "deepseek-chat"
    assert "enable_search" not in calls[0][1]["json"]
    assert "不确定的词不要输出" in calls[0][1]["json"]["messages"][1]["content"]


def test_term_library_current_game_marker_is_based_on_selected_game():
    import importlib
    import inspect

    import twobyteasr.app.ui as ui_module

    term_library_dialog = ui_module.TermLibraryDialog
    implementation = importlib.import_module(term_library_dialog.__module__)
    assert ui_module.TermLibraryDialog is implementation.TermLibraryDialog
    source = inspect.getsource(term_library_dialog)
    # C 轮重排：术语库为独立 TermLibraryDialog 类。语义保持：
    # - 当前游戏标记基于 identity 比较（列表项按 canonical identity 去重）
    # - 用于本批字幕按钮文案区分已用/可用
    # - 创建游戏在顶部 toolbar（+ 按钮），与智能建词入口分离
    # - 删除当前游戏独立于删除所选术语
    assert "identity = self._game_identity(game_name)" in source
    assert "self._game_identity(item.data(Qt.ItemDataRole.UserRole)) == identity" in source
    assert '"✓ 已用于本批字幕" if is_current else "用于本批字幕"' in source
    assert "self.add_game_button" in source
    assert "self.delete_game_button" in source
    assert "def open_smart_build" in source
    assert "self.remove_terms" in source


def test_completion_notification_distinguishes_success_and_failure():
    success = QueueResult(
        (MediaResult("ok.mp4", "success", srt_path="ok.srt"),),
        elapsed_seconds=1.0,
    )
    title, message, _icon, details = _completion_notification_spec(success)
    assert title == "字幕生成完成"
    assert "成功生成 1 个素材" in message
    assert "结果页" in details

    failed = QueueResult(
        (MediaResult("bad.mp4", "failed", error="synthetic failure"),),
        elapsed_seconds=1.0,
    )
    title, message, _icon, details = _completion_notification_spec(failed)
    assert title == "字幕生成失败"
    assert "失败 1 个" in message
    assert "bad.mp4：synthetic failure" in details

    empty_error = QueueResult(
        (MediaResult("empty.mp4", "failed", error=""),),
        elapsed_seconds=1.0,
    )
    _title, _message, _icon, details = _completion_notification_spec(empty_error)
    assert "未提供错误详情" not in details
    assert "请查看完整运行日志" in details


def test_start_button_avoids_blocking_cuda_preflight_and_keeps_vmware_guidance():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    hardware_source = (Path(__file__).parents[1] / "twobyteasr" / "system" / "hardware.py").read_text(encoding="utf-8")
    assert "We intentionally skip _ensure_runtime_environment() and _ensure_cuda_runtime()" in source
    assert "from twobyteasr.system.environment import fast_preflight" in source
    assert "普通 VMware 虚拟机" in hardware_source
    assert "通常不需要另外安装完整 CUDA Toolkit" in hardware_source


def test_qwen_backend_explains_tradeoffs_and_links_official_api_key_tutorial():
    root = Path(__file__).parents[1]
    source = (root / "twobyteasr" / "app" / "ui.py").read_text(encoding="utf-8")
    launcher = (root / "launcher" / "2ByteASRConfigure.cs").read_text(encoding="utf-8")
    bootstrap = (root / "scripts" / "bootstrap_install.ps1").read_text(encoding="utf-8")
    downloader = (root / "scripts" / "download_models.ps1").read_text(encoding="utf-8")
    assert "API（更快、免下载，需配置 Key）" in source
    assert "本地 Qwen3-ASR 1.7B（更准确，约 4.7 GB）" in source
    assert "本地 Qwen 通常识别更准确" in source
    assert "API 帮助" in source
    assert "查看完整教程" in source
    assert "https://help.aliyun.com/zh/model-studio/get-api-key" in source
    for text in (launcher, bootstrap, downloader):
        assert "不推荐" not in text
        assert "精度更高" in text


def test_combo_popup_uses_stable_rounded_geometry_with_lightweight_motion():
    import importlib
    import inspect
    from pathlib import Path

    import twobyteasr.app.ui as ui_module

    implementation = importlib.import_module(FramelessPopupCombo.__module__)
    assert ui_module.FramelessPopupCombo is implementation.FramelessPopupCombo
    assert ui_module._ComboPopup is implementation._ComboPopup
    assert _ComboPopup is implementation._ComboPopup
    source = inspect.getsource(implementation._ComboPopup)
    assert "Project-owned popup; never creates Qt's black private combo container" in source
    # 2026-10-26: transparent around the rounded list (an opaque window showed
    # square corners); same sheet, rows and placement as every dropdown.
    assert "self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)" in source
    assert "below_rect(" in source and "style_popup(self)" in source
    assert "self.clearMask()" in source
    assert "Qt.WindowType.NoDropShadowWindowHint" in source
    facade_source = (Path(__file__).parents[1] / "twobyteasr" / "app" / "main_ui_branding.py").read_text(encoding="utf-8")
    assert facade_source.index("if APP_ICON_SOURCE_PATH.is_file()") < facade_source.index("if APP_ICON_PATH.is_file()")

    app = QApplication.instance() or QApplication([])
    combo = FramelessPopupCombo()
    combo.addItems(["中文", "English", "日本語"])
    combo.resize(240, 42)
    combo.show()
    combo.showPopup()
    app.processEvents()
    assert combo._popup.isVisible()
    assert combo._popup.mask().isEmpty()
    assert combo._popup._animation is not None
    assert combo._popup._animation.duration() == 180
    assert combo._popup.geometry().size() == combo._popup._target_geometry().size()
    combo.hidePopup()
    assert combo._popup._animation is None
    combo.close()
    combo.deleteLater()
    app.processEvents()


def test_combo_popup_reduced_motion_is_immediate(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setProperty("reduceMotion", True)
    combo = FramelessPopupCombo()
    combo.addItems(["中文", "English"])
    combo.resize(240, 42)
    combo.show()
    combo.showPopup()
    app.processEvents()
    assert combo._popup.isVisible()
    assert combo._popup._animation is None
    assert combo._popup.windowOpacity() == 1.0
    combo.hidePopup()
    combo.close()
    app.setProperty("reduceMotion", False)
    combo.deleteLater()
    app.processEvents()


def test_combo_ignores_wheel_selection_changes_until_clicked():
    class WheelEvent:
        ignored = False

        def ignore(self):
            self.ignored = True

    app = QApplication.instance() or QApplication([])
    combo = FramelessPopupCombo()
    combo.addItems(["自动", "1", "2"])
    combo.setCurrentIndex(1)
    event = WheelEvent()
    combo.wheelEvent(event)
    assert event.ignored is True
    assert combo.currentIndex() == 1
    combo.deleteLater()
    app.processEvents()


def test_term_manager_is_searchable_complete_and_supports_batch_import():
    import importlib
    import inspect

    import twobyteasr.app.ui as ui_module

    term_library_dialog = ui_module.TermLibraryDialog
    implementation = importlib.import_module(term_library_dialog.__module__)
    assert ui_module.TermLibraryDialog is implementation.TermLibraryDialog
    source = inspect.getsource(term_library_dialog)
    assert "术语库与学习记录" in source
    assert "搜索词条" in source  # 2026-10-17 redesign v2: the term search sits in the tool row
    assert 'AnimatedButton("批量导入")' in source
    assert "builtin_names[:300]" not in source


def test_completion_dialog_requests_attention_when_window_is_in_background():
    from pathlib import Path

    app_dir = Path(__file__).parents[1] / "twobyteasr" / "app"
    # CompletionDialog moved to completion_dialog.py on 2026-10-15.
    source = "".join((app_dir / name).read_text(encoding="utf-8") for name in ("ui.py", "completion_dialog.py"))
    assert "QApplication.beep()" in source
    assert "QApplication.alert(self, 0)" in source
    assert "WindowStaysOnTopHint" in source
    assert source.count("self._show_task_notification(") >= 2
    assert 'AnimatedButton("完成并返回主菜单")' in source
    assert "close.clicked.connect(self._return_to_main_menu)" in source


def test_completion_dialog_has_theme_stable_light_surface_and_status_colors():
    app = QApplication.instance() or QApplication([])
    success = CompletionDialog(
        "字幕生成完成",
        "已成功生成 1 个素材的字幕。",
        QMessageBox.Icon.Information,
        "可以在结果页查看字幕。",
    )
    failed = CompletionDialog(
        "字幕生成失败",
        "本批任务已结束。",
        QMessageBox.Icon.Critical,
        "sample.mp4：测试错误",
    )

    assert success.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert success.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not success.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert success.card.header is not None
    assert success.card.body is not None
    assert success.card.footer is not None
    # The completion surface must carry the active theme's tokens; a saved
    # non-warm user theme must not leak a hard-coded cream card either.
    from twobyteasr.design.theme_manager import theme_key
    from twobyteasr.design.ui_theme import theme_definition

    active = theme_definition(theme_key())
    assert active.surface in success.card.styleSheet()
    assert success.card.graphicsEffect() is None
    assert success.accent == active.success
    assert success.status_badge.text() == "处理完成"
    assert success.title_label.text() == "字幕生成完成"
    assert success.confirm_button.text() == "知道了"
    assert failed.accent == active.danger
    assert failed.status_badge.text() == "需要处理"
    assert "测试错误" in failed.details_label.text()

    success.deleteLater()
    failed.deleteLater()
    app.processEvents()
