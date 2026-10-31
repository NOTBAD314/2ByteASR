"""AI service endpoint editor (home "AI 模型与密钥" panel) and its background checks.

``EndpointEditor`` edits one stage (polish or group): service, model, key,
CLI login and connection test.  The ``Provider*`` threads run those checks
through ``provider_for_stage``, a seam over the shared provider registry
(tests patch it here).  ``AsrModelsFetchWorker`` lists cloud ASR models for
the main window; ``PromptDialog`` shows the built-in prompts; ``ConnectionTester``
is the older JSON self-test thread; nothing starts it any more, it is kept
only because ``ui.ConnectionTester`` was a public name.

Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports these names.
Code here looks up ``read_api_key``, ``resolve_api_key``, ``validate_endpoint``
and ``GLOBAL_PROVIDER_REGISTRY`` in this module, so tests that fake them for
an editor must patch this module (and ``app.ui`` too when MainWindow code
is under test).
"""
from __future__ import annotations

import copy
import html
import json
import re
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from ..app.main_ui_helpers import _active_theme_definition, _icon
from ..design.main_ui_dialogs import SpringDialog
from ..design.main_ui_popup import FramelessPopupCombo
from ..design.typography import UI_FONT_STACK
from ..design.ui_widgets import AnimatedButton
from ..i18n import apply_ui_language, bind_text, tr
from .ai_providers import AITransport
from .llm_config import (
    activate_ai_service, active_service_values, AI_SERVICE_SPECS, chat_completion_url,
    credential_storage_notice, fetch_openai_compatible_models, get_active_service,
    get_provider_profiles, model_is_retired, normalize_base_url, normalize_provider_profile,
    PROVIDER_PRESETS, read_api_key, resolve_api_key, resolved_service_values, responses_url, messages_url,
    service_model_catalog, session_credentials_enabled, supports_model_discovery,
    update_active_profile, validate_endpoint,
)
from .provider_registry import GLOBAL_PROVIDER_REGISTRY


class _CurrentPageStack(QStackedWidget):
    """Sized by the page on show: the hidden account-login page must not reserve
    height above 测试连接 (2026-10-22; QStackedLayout counts every page)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()


def provider_for_stage(settings, stage):
    """Compatibility seam; all real clients come from the shared registry."""
    return GLOBAL_PROVIDER_REGISTRY.client(stage=stage, settings=settings)


class ConnectionTester(QThread):
    finished_status = Signal(bool, str)

    def __init__(self, endpoint: dict):
        super().__init__()
        self.endpoint = endpoint

    def run(self):
        from subtitle_core import run_llm_json_self_test

        try:
            run_llm_json_self_test(self.endpoint)
            self.finished_status.emit(True, "连接正常 · JSON 结构化输出正常")
        except Exception as exc:
            compact = " ".join(str(exc).split())[:90]
            self.finished_status.emit(False, f"连接失败：{compact}")


class ProviderConnectionTester(QThread):
    finished_status = Signal(bool, str)

    def __init__(
        self,
        settings: dict,
        stage: str,
        *,
        prompt_test: bool = False,
        force_refresh: bool = False,
    ):
        super().__init__()
        from .request_snapshot import freeze_request_settings
        self.settings = freeze_request_settings(settings, stage)
        self.stage = stage
        self.prompt_test = bool(prompt_test)
        self.force_refresh = bool(force_refresh)
        self.models: tuple[str, ...] = ()
        self.timings: dict[str, float | bool] = {}
        self.diagnostics: dict = {}

    def run(self):
        started = time.monotonic()
        provider = None
        import datetime
        def finish(ok, message):
            measured = getattr(provider, 'cli_diagnostics', lambda: {})() if provider is not None else {}
            explicit = {key: self.diagnostics[key] for key in ('category', 'request_succeeded') if key in self.diagnostics}
            self.diagnostics = {**self.diagnostics, **measured, **explicit}
            self.diagnostics['last_tested_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.finished_status.emit(ok, message)
        try:
            provider = provider_for_stage(self.settings, self.stage)
            validate_started = time.monotonic()
            if self.prompt_test:
                schema = {'type': 'object', 'properties': {
                    'ok': {'type': 'boolean', 'const': True},
                    'text': {'type': 'string', 'const': '兔白字幕'}},
                    'required': ['ok', 'text'], 'additionalProperties': False}
                answer = provider.structured_complete([
                    {'role': 'user', 'content': '请只返回 JSON：{"ok":true,"text":"兔白字幕"}。'}],
                    schema, max_tokens=80, temperature=0, timeout=45,
                    cancel_check=self.isInterruptionRequested, stage='connection_test',
                    operation_kind='polish')
                from jsonschema import Draft202012Validator
                Draft202012Validator(schema).validate(answer)
                if self.isInterruptionRequested():
                    finish(False, '连接测试已取消')
                    return
                self.timings = dict(getattr(provider, 'last_timings', {}) or {})
                self.timings['total_seconds'] = time.monotonic() - started
                self.diagnostics.update(request_succeeded=True, category='',
                    auth_evidence='successful_model_request',
                    json_capabilities=provider.json_capabilities())
                mode = provider.structured_output_mode()
                label = '原生 JSON Schema＋本地校验' if mode == 'STRICT_JSON_SCHEMA' else '兼容 JSON／本地校验'
                finish(True, tr('连接测试通过 · 中文 JSON 字段正确 · {value0} · {value1}s',
                    value0=label, value1=f'{self.timings["total_seconds"]:.2f}'))
                return
            # 45s: an Antigravity cold start alone costs 3-10s per CLI call and
            # the readiness probe rides on top; 20s reported healthy sessions
            # as "未登录或不可调用" under load.
            status = provider.validate(
                timeout=45.0,
                cancel_check=self.isInterruptionRequested,
                use_cache=not self.force_refresh,
            )
            self.timings = dict(getattr(provider, "last_timings", {}) or {})
            self.timings["validation_seconds"] = time.monotonic() - validate_started
            self.models = tuple(status.models)
            self.diagnostics = dict(getattr(status, 'diagnostics', {}) or {})
            self.diagnostics['json_capabilities'] = provider.json_capabilities(
                probe=True, cancel_check=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                finish(False, "连接测试已取消")
                return
            measured_readiness = self.timings.get("readiness_request_seconds")
            if measured_readiness is not None and not self.timings.get("cache_hit"):
                self.timings["response_seconds"] = measured_readiness
            self.timings["total_seconds"] = time.monotonic() - started
            cache_note = "缓存状态" if self.timings.get("cache_hit") else "实时检测"
            timing = f"{cache_note} {float(self.timings['validation_seconds']):.2f}s"
            if "response_seconds" in self.timings:
                timing += f" · 模型响应 {float(self.timings['response_seconds']):.2f}s"
            timing += f" · 总计 {float(self.timings['total_seconds']):.2f}s"
            finish(
                bool(status.available and status.authenticated),
                f"{status.message} · {timing}",
            )
        except Exception as exc:
            self.diagnostics['category'] = getattr(exc, 'category', 'provider_error')
            self.diagnostics['request_succeeded'] = False if self.prompt_test else None
            compact = " ".join(str(exc).split())[:120]
            if self.isInterruptionRequested() or "取消" in compact:
                finish(False, "连接测试已取消")
            else:
                elapsed = time.monotonic() - started
                finish(False, f"{str(exc) if getattr(exc, 'category', '') == 'upgrade_required' else compact} · {elapsed:.2f}s")
        finally:
            measured = getattr(provider, 'cli_diagnostics', lambda: {})() if provider is not None else {}
            explicit = {key: self.diagnostics[key] for key in ('category', 'request_succeeded') if key in self.diagnostics}
            self.diagnostics = {**self.diagnostics, **measured, **explicit}
            self.diagnostics['last_tested_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()


class ProviderCLIUpdateWorker(QThread):
    finished_status = Signal(bool, str)

    def __init__(self, settings, stage, plan):
        super().__init__()
        self.settings = copy.deepcopy(settings)
        self.stage = stage
        self.plan = copy.deepcopy(plan)
        self.diagnostics = {}

    def run(self):
        provider = provider_for_stage(self.settings, self.stage)
        try:
            status = provider.update_cli(self.plan, user_confirmed=True, cancel_check=self.isInterruptionRequested)
            self.diagnostics = dict(status.diagnostics)
            self.finished_status.emit(status.request_succeeded is True, status.message)
        except Exception as exc:
            from .provider_diagnostics import redact_diagnostics
            self.diagnostics = provider.cli_diagnostics()
            self.diagnostics.update(category=getattr(exc, 'category', 'cli_update_failed'), request_succeeded=False)
            self.finished_status.emit(False, redact_diagnostics(str(exc)))


class ProviderLoginWorker(QThread):
    finished_status = Signal(bool, str)
    login_progress = Signal(str)

    def __init__(self, settings: dict, stage: str, *, action="login"):
        super().__init__()
        self.settings = settings
        self.stage = stage
        self.action = action

    def run(self):
        try:
            provider = provider_for_stage(self.settings, self.stage)
            login = getattr(provider, "login", None)
            if not callable(login):
                self.finished_status.emit(False, "当前服务不支持 OAuth CLI 登录")
                return

            def emit_progress(message: str) -> None:
                self.login_progress.emit(str(message))

            if self.action == "logout":
                status = provider.logout(cancel_check=self.isInterruptionRequested)
            else:
                status = login(timeout=300.0, on_progress=emit_progress, cancel_check=self.isInterruptionRequested,user_initiated=True)
            self.finished_status.emit(bool(status.available and status.authenticated), status.message)
        except Exception as exc:
            from .provider_diagnostics import redact_diagnostics
            compact = redact_diagnostics(" ".join(str(exc).split())[:300])
            self.finished_status.emit(False, compact)


class ProviderModelDiscoveryWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, settings: dict, stage: str, *, refresh: bool = False, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.stage = stage
        self.refresh = bool(refresh)

    def run(self):
        try:
            provider = provider_for_stage(self.settings, self.stage)
            models = provider.discover_models(
                timeout=20.0,
                cancel_check=self.isInterruptionRequested,
                refresh=self.refresh,
            )
            if self.isInterruptionRequested():
                self.failed.emit("模型发现已取消；可继续手动输入模型 ID")
                return
            if not models:
                self.failed.emit("该 Provider 未返回模型列表，可手动输入模型 ID")
                return
            self.succeeded.emit(list(models))
        except Exception as exc:
            compact = " ".join(str(exc).split())[:220]
            if self.isInterruptionRequested() or "取消" in compact:
                compact = "模型发现已取消；可继续手动输入模型 ID"
            elif "手动输入" not in compact:
                compact += "；可继续手动输入模型 ID"
            self.failed.emit(compact)


class AsrModelsFetchWorker(QThread):
    """Lightweight worker to fetch /v1/models without blocking the UI thread."""
    succeeded = Signal(list)  # list[str]
    failed = Signal(str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        try:
            models = fetch_openai_compatible_models(self.base_url, self.api_key)
            self.succeeded.emit(models)
        except Exception as exc:
            self.failed.emit(str(exc))


class PromptDialog(SpringDialog):
    """AI line-breaking guidance per subtitle language (2026-10-18; was a read-only note).

    Only the guidance part of each grouping prompt is edited here; the
    protocol, protected boundaries, hard limits and verbatim text stay
    program-owned (``subtitle_rules.grouping_request``) and are shown read-only.
    Saved to settings ``grouping_prompts``; an empty or unchanged text means
    the built-in guidance. A running task keeps the settings it started with.
    """

    from ..subtitle_rules.segmentation_profiles import prompt_languages
    LANGUAGES = prompt_languages()

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        from ..design.presentation import button_role
        from ..design.themed_icons import install_themed_icon
        from ..subtitle_rules.grouping_request import CUSTOM_GUIDANCE_MAX_CHARS, default_grouping_guidance
        if settings is None:
            import subtitle_core
            settings = subtitle_core.RUNTIME_SETTINGS
        self._settings = settings
        self._limit = CUSTOM_GUIDANCE_MAX_CHARS
        stored = settings.get("grouping_prompts") if isinstance(settings.get("grouping_prompts"), dict) else {}
        self._stored = dict(stored)
        from ..subtitle_rules.segmentation_profiles import canonical_prompt_values
        stored=canonical_prompt_values(stored)
        self._canonical_stored=stored
        self._restored = set()
        self._defaults = {code: default_grouping_guidance(code) for code, _label in self.LANGUAGES}
        self._drafts = {code: str(stored.get(code) or "").strip() or self._defaults[code]
                        for code, _label in self.LANGUAGES}
        spoken = str((settings.get("subtitle_language") or {}).get("recognition_language") or "")
        from ..subtitle_rules.segmentation_profiles import language_tag, profile_for
        tag=language_tag(spoken)
        self._current = tag if tag in self._drafts and spoken not in ('','auto') else profile_for(tag).code if tag!='und' else 'zh'
        self.setObjectName("groupingPromptDialog")
        bind_text(self, 'AI 断句提示词', property='windowTitle')
        self.resize(820, 680)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame(self)
        header.setObjectName("aiDialogHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(24, 18, 16, 14)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = bind_text(QLabel(), 'AI 断句提示词')
        title.setObjectName("aiDialogTitle")
        subtitle = bind_text(QLabel(), '告诉断句模型在哪里换字幕。可以按自己的习惯改，只影响之后新识别的字幕。')
        subtitle.setObjectName("aiDialogSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        close = button_role(QPushButton(""), "ghost")
        close.setFixedSize(36, 36)
        install_themed_icon(close, "fa5s.times", "secondary")
        bind_text(close, '关闭断句提示词', property='accessibleName')
        bind_text(close, '关闭（不保存修改）', property='toolTip')
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(header)

        body = QWidget(self)
        body.setObjectName("aiDialogBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 16, 24, 12)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(bind_text(QLabel(), '字幕语言'))
        self.language = FramelessPopupCombo()
        for code, label in self.LANGUAGES:
            self.language.addItem(tr(label), code)
        self.language.setCurrentIndex(max(0, self.language.findData(self._current)))
        row.addWidget(self.language)
        row.addStretch(1)
        self.state = QLabel()
        self.state.setObjectName("muted")
        row.addWidget(self.state)
        layout.addLayout(row)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("groupingPromptEditor")
        self.editor.setPlainText(self._drafts[self._current])
        self.editor.setMinimumHeight(260)
        bind_text(self.editor, '断句说明', property='accessibleName')
        layout.addWidget(self.editor, 3)
        fixed_note = QLabel()
        self.fixed_note = fixed_note
        fixed_note.setObjectName("muted")
        fixed_note.setWordWrap(True)
        layout.addWidget(fixed_note)
        self.fixed_toggle = QToolButton()
        self.fixed_toggle.setObjectName("endpointAdvancedToggle")
        self.fixed_toggle.setCheckable(True)
        self.fixed_toggle.setText(tr('查看程序固定的部分'))
        layout.addWidget(self.fixed_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.fixed = QPlainTextEdit()
        self.fixed.setObjectName("groupingPromptFixed")
        self.fixed.setReadOnly(True)
        self.fixed.setMinimumHeight(150)
        self.fixed.hide()
        layout.addWidget(self.fixed, 2)
        outer.addWidget(body, 1)

        footer = QFrame(self)
        footer.setObjectName("aiDialogFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(24, 12, 24, 16)
        foot.setSpacing(10)
        self.restore = button_role(bind_text(QPushButton(), '恢复内置说明'), "secondary")
        foot.addWidget(self.restore)
        foot.addStretch(1)
        self.error = QLabel()
        self.error.setObjectName("statusBad")
        self.error.hide()
        foot.addWidget(self.error)
        cancel = button_role(bind_text(QPushButton(), '取消'), "secondary")
        cancel.clicked.connect(self.reject)
        self.save_button = button_role(bind_text(QPushButton(), '保存'), "primary")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        foot.addWidget(cancel)
        foot.addWidget(self.save_button)
        outer.addWidget(footer)

        self.language.currentIndexChanged.connect(self._switch_language)
        self.editor.textChanged.connect(self._refresh_state)
        self.restore.clicked.connect(self._restore_current)
        self.fixed_toggle.toggled.connect(self._show_fixed)
        self._refresh_fixed()
        self._refresh_state()
        apply_ui_language(self)

    def _switch_language(self, _index):
        self._drafts[self._current] = self.editor.toPlainText()
        self._current = str(self.language.currentData() or "zh")
        self.editor.setPlainText(self._drafts[self._current])
        self._refresh_fixed()

    def _show_fixed(self, shown):
        self.fixed.setVisible(bool(shown))
        self.fixed_toggle.setText(tr('收起程序固定的部分') if shown else tr('查看程序固定的部分'))

    def _refresh_fixed(self):
        from ..subtitle_rules.grouping_request import fixed_grouping_prompt_parts
        head, reminder, tail = fixed_grouping_prompt_parts(self._current)
        self.fixed.setPlainText(f"{head}\n{tr('（这里是上面可以修改的断句说明；改过时程序再加一句：）')}\n{reminder}\n\n{tail}")
        from ..subtitle_rules.segmentation_profiles import profile_for,unit_label
        p=profile_for(self._current)
        self.fixed_note.setText(tr('当前语言 {language}：长度单位 {unit}；建议 {preferred}、软上限 {soft}、上限 {hard}，最多 {lines} 行 / {seconds} 秒。只选合法边界，完整长词超限时保留并提示；显示换行与时间字幕切分分别处理。').format(
            language=self._current,unit=unit_label(self._current),preferred=p.preferred,soft=p.soft_max,hard=p.hard_max,lines=p.lines,seconds=p.max_seconds))

    def _restore_current(self):
        self._restored.add(self._current)
        self.editor.setPlainText(self._defaults[self._current])

    def _refresh_state(self):
        text = self.editor.toPlainText().strip()
        if text != self._defaults[self._current].strip():
            self._restored.discard(self._current)
        builtin = not text or text == self._defaults[self._current].strip()
        too_long = len(text) > self._limit
        self.state.setText(tr('超过 {limit} 字，请删减').format(limit=self._limit) if too_long
                           else tr('内置说明') if builtin else tr('自定义说明'))
        self.restore.setEnabled(not builtin)
        self.save_button.setEnabled(not too_long)

    def guidance_values(self) -> dict:
        """What saving writes: empty for the built-in guidance."""
        self._drafts[self._current] = self.editor.toPlainText()
        values = dict(self._stored)  # preserve unknown/legacy language customizations
        for code, text in self._drafts.items():
            text = text.strip()
            explicit_old = bool(self._canonical_stored.get(code)) and text == str(self._canonical_stored[code]).strip()
            values[code] = "" if code in self._restored or not text or text == self._defaults[code].strip() and not explicit_old else text[:self._limit]
        return values

    def save(self):
        from ..storage.settings import save_runtime_settings
        previous = self._settings.get("grouping_prompts")
        self._settings["grouping_prompts"] = self.guidance_values()
        try:
            save_runtime_settings(self._settings)
        except Exception as exc:
            if previous is None:
                self._settings.pop("grouping_prompts", None)
            else:
                self._settings["grouping_prompts"] = previous
            self.error.setText(tr('保存失败：{error}').format(error=exc))
            self.error.show()
            return
        self.accept()


class EndpointEditor(QFrame):
    connection_tested = Signal(bool)   # 测试连接 finished (2026-10-22: the home page unlocks the AI-only features)
    configuration_edited = Signal()  # explicit Clear can leave the text already empty
    advanced_wanted = Signal()         # a custom service needs its Base URL (the dialog opens 高级设置)
    key_help_requested = Signal()      # 「API Key 是什么？」 beside the key box

    def __init__(self, title: str, accent: str, stage: str, settings: dict):
        super().__init__()
        self.setObjectName("endpointCard")
        self.stage = stage
        self.accent = accent
        models = settings["models"]
        prefix = "polish" if stage == "polish" else "group"
        # Provider profile 是唯一事实源：base/model/protocol 按 active profile
        # 解析（旧扁平字段仅在非跨服务泄漏时参与回退），打开即自愈混合状态。
        self._settings_ref = settings
        GLOBAL_PROVIDER_REGISTRY.bind(settings)
        active = active_service_values(settings, stage=stage)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 13)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("endpointTitle")
        self.title_label.setStyleSheet(f"color: {accent}; font-size: 15px; font-weight: 700;")
        layout.addWidget(self.title_label)
        self._layout = layout
        # 2026-10-22 (design B): the service, key and test come first in plain
        # words; model, address, protocol and output live in the advanced group.
        if stage == "group":
            self.grouping_recommendation = QLabel(self)
            self.grouping_recommendation.setObjectName("groupingRecommendation")
            self.grouping_recommendation.setWordWrap(True)
            bind_text(self.grouping_recommendation,
                "智能断句推荐 DeepSeek。已选服务可继续使用；所有模型都经过相同检查，结果不合格时改用本地断句，可能需要人工检查。")
            self.grouping_recommendation.setProperty("class", "hint")
            # The service list already says 断句推荐; the full note is its hover text.
            self.grouping_recommendation.hide()

        self.service = FramelessPopupCombo()
        for service_id, spec in AI_SERVICE_SPECS.items():
            label = spec["label"]
            if stage == "group" and service_id == "deepseek":
                label += "（断句推荐）"
            self.service.addItem(label, service_id)

        # Compatibility controls remain available to the existing persistence
        # and summary code, but the user selects a concrete service above.
        self.transport = FramelessPopupCombo()
        self.transport.addItem("API", AITransport.OPENAI_COMPATIBLE.value)
        self.transport.addItem("Google Antigravity", AITransport.ANTIGRAVITY_CLI.value)
        self.transport.addItem("Grok Account", AITransport.GROK_CLI.value)
        self.transport.addItem("OpenAI Codex CLI", AITransport.CODEX_CLI.value)
        self.transport.hide()
        current_transport = active["transport"]
        self.transport.setCurrentIndex(max(0, self.transport.findData(current_transport)))
        self.provider = FramelessPopupCombo()
        for key, spec in PROVIDER_PRESETS.items():
            self.provider.addItem(spec["label"], key)
        current_provider = active["provider"]
        self.provider.setCurrentIndex(max(0, self.provider.findData(current_provider)))
        self.provider.hide()
        self.model = FramelessPopupCombo()
        self.model.setEditable(True)
        defaults = list(service_model_catalog(settings, active.get("service", "custom")))
        if not defaults and stage != "group" and active["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            defaults = ["qwen3.7-flash-2026-07-15", "qwen3.7-max", "glm-5.2"]
        self.model.addItems(defaults)
        self.model.setCurrentText(active["model"] or (defaults[0] if defaults else ""))
        self.base_url = QLineEdit(active["base_url"])
        self.base_url.setObjectName("endpointInput")
        self.custom_name = QLineEdit("自定义服务")
        self.custom_name.setObjectName("endpointInput")
        self.protocol = FramelessPopupCombo()
        for label, value in (
            ("Auto", "auto"),
            ("Responses API", "responses"),
            ("Chat Completions", "chat_completions"),
            ("OpenAI-compatible Chat", "openai_compatible_chat"),
        ):
            self.protocol.addItem(label, value)
        protocol_value = active["protocol"] or "auto"
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(protocol_value)))
        self.endpoint_hint = QLabel()
        self.endpoint_hint.setObjectName("fieldHint")
        self.endpoint_hint.setWordWrap(True)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.reveal_key = QToolButton()
        self.reveal_key.setIcon(_icon("fa5s.eye"))
        self.reveal_key.setFixedSize(36, 36)
        self.reveal_key.setCheckable(True)
        bind_text(self.reveal_key, '显示或隐藏 API Key', property='toolTip')
        bind_text(self.reveal_key, '显示或隐藏 API Key', property='accessibleName')
        self.reveal_key.toggled.connect(
            lambda visible: (
                self.key.setEchoMode(
                    QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
                ),
                self.reveal_key.setIcon(
                    _icon("fa5s.eye-slash" if visible else "fa5s.eye")
                ),
            )
        )
        # Provider-scoped key: read by (provider, base_url) so switching models keeps the key.
        prov = current_provider
        burl = active["base_url"]
        existing, source = read_api_key(prov, burl)
        # Legacy fallback is valid only for the historical Bailian preset.
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(stage)
        # P8C-R3.1 三态密钥：UNCHANGED（未输入，保持已存密钥）/ REPLACE（输入新值）/
        # CLEAR（仅点击“清除密钥”按钮）。空输入框永远不等于“删除已有密钥”，
        # placeholder 只是 UI metadata，绝不参与 secret 保存。
        self._key_state = "unchanged"
        self.key.textChanged.connect(self._on_key_text_changed)
        self._show_key_placeholder(existing, source)
        self.clear_key_button = QToolButton()
        self.clear_key_button.setIcon(_icon("fa5s.eraser"))
        self.clear_key_button.setFixedSize(36, 36)
        bind_text(self.clear_key_button, '清除已保存的 API Key（保存时生效；环境变量不受影响）', property='toolTip')
        bind_text(self.clear_key_button, '清除已保存的 API Key', property='accessibleName')
        self.clear_key_button.clicked.connect(self._request_key_clear)
        for button in (self.reveal_key, self.clear_key_button):
            button.setParent(self)
            button.hide()
        from ..design.themed_icons import install_themed_icon
        # Owned by the key box itself (PySide's addAction(icon, position) result
        # did not survive the AI settings dialog closing).
        self._reveal_action = QAction(_icon("fa5s.eye"), "", self.key)
        self.key.addAction(self._reveal_action, QLineEdit.ActionPosition.TrailingPosition)
        install_themed_icon(self._reveal_action, "fa5s.eye", "secondary")
        bind_text(self._reveal_action, '显示或隐藏 API Key', property='toolTip')
        self._reveal_action.triggered.connect(self.reveal_key.toggle)
        self.reveal_key.toggled.connect(lambda visible: install_themed_icon(
            self._reveal_action, "fa5s.eye-slash" if visible else "fa5s.eye", "secondary"))
        self._clear_action = QAction(_icon("fa5s.eraser"), "", self.key)
        self.key.addAction(self._clear_action, QLineEdit.ActionPosition.TrailingPosition)
        install_themed_icon(self._clear_action, "fa5s.eraser", "secondary")
        bind_text(self._clear_action, '清除已保存的 API Key（保存时生效；环境变量不受影响）', property='toolTip')
        self._clear_action.triggered.connect(self.clear_key_button.click)
        self._clear_action.setVisible(bool(existing))
        self.test_button = AnimatedButton("测试连接")
        self.test_button.setObjectName("endpointPrimary")
        # Its width comes from the sheet (min-width) and its label; the language
        # pass's +4 px pin made 重新测试 wider than 测试连接 (10-23).
        self.test_button.setProperty("flexibleWidth", True)
        # Service, key and 测试连接 share one height (2026-10-22): the large
        # control size, full width (the presets otherwise cap a list at 360 px).
        from ..design.presentation import field_width
        field_width(self.service, "expanding", size="large")
        field_width(self.key, "expanding", size="large")
        if stage == "group":
            bind_text(self.test_button,
                "只检查连接与基础响应；连接成功不代表断句结果合格，实际结果仍须通过本地验证。",
                property="toolTip")
        self.status = QLabel("已配置" if existing else "未配置密钥")
        self.status.setObjectName("statusGood" if existing else "statusWarn")
        self.status.setOpenExternalLinks(True)
        self.status.setWordWrap(True)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.key, 1)
        self.api_page = QWidget()
        self.api_page.setObjectName("endpointApiPage")
        form = QFormLayout(self.api_page)
        form.setContentsMargins(0, 0, 0, 0)   # level with the service list and 测试连接
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.custom_name_label = QLabel("Provider 名称")
        form.addRow(self.custom_name_label, self.custom_name)
        self.provider_label = QLabel("服务商预设")
        self.base_url_label = QLabel("Base URL")
        self.protocol_label = QLabel("协议")
        # The step caption 「② 贴上 API Key」 names the key box (2026-10-22).
        self.key_label = QLabel("API 密钥", self.api_page)
        self.key_label.hide()
        self.key_row_host = QWidget()
        self.key_row_host.setLayout(key_row)
        form.addRow(self.key_row_host)
        # Said where people worry: the key never leaves this computer.
        self.key_note = QLabel()
        bind_text(self.key_note, "只存在这台电脑上，已加密")
        if session_credentials_enabled():
            self.key_note.setText(credential_storage_notice())
        self.key_note.setObjectName("endpointKeyNote")
        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.addWidget(self.key_note)
        note_row.addStretch(1)
        self.key_help_button = AnimatedButton("API Key 是什么？")
        self.key_help_button.setObjectName("linkButton")
        self.key_help_button.clicked.connect(self.key_help_requested.emit)
        self.key_help_button.hide()   # the AI settings dialog shows it on its top form
        # Hidden once connected, but its line keeps its height: 测试连接 below must not move (10-23).
        policy = self.key_help_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.key_help_button.setSizePolicy(policy)
        note_row.addWidget(self.key_help_button)
        form.addRow(note_row)

        advanced = QHBoxLayout()
        advanced.setContentsMargins(0, 0, 0, 0)
        self.json_mode = QCheckBox("JSON Mode")
        self.structured_output = QCheckBox("Structured Output")
        self.stream_output = QCheckBox("stream")
        self.json_mode.setChecked(active.get('json_mode', models.get(f'{prefix}_json_mode', True)))
        self.structured_output.setChecked(active.get('structured_output', models.get(f'{prefix}_structured_output', True)))
        self.stream_output.setEnabled(False)
        bind_text(self.stream_output, '当前字幕处理后端使用非流式结构化响应', property='toolTip')
        advanced.addWidget(self.json_mode)
        advanced.addWidget(self.structured_output)
        advanced.addWidget(self.stream_output)
        advanced.addStretch(1)
        self.capabilities_host = QWidget()
        self.capabilities_host.setLayout(advanced)
        self.json_capability_status = QLabel()
        self.json_capability_status.setObjectName('fieldHint')
        self.json_capability_status.setWordWrap(True)

        self.cli_page = QWidget()
        self.cli_page.setObjectName("endpointCliPage")
        cli_layout = QVBoxLayout(self.cli_page)
        cli_layout.setContentsMargins(0, 0, 0, 0)
        cli_layout.setSpacing(7)
        self.cli_status = QLabel("CLI：未检测")
        self.cli_status.setObjectName("endpointCliStatus")
        self.account_status = QLabel("CLI Session：未知")
        self.account_status.setObjectName("endpointAccountStatus")
        self.cli_status.setWordWrap(True)
        self.account_status.setWordWrap(True)
        self.cli_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.account_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        cli_layout.addWidget(self.cli_status)
        cli_layout.addWidget(self.account_status)
        cli_actions = QHBoxLayout()
        self.detect_cli_button = QPushButton("重新检测")
        self.login_button = QPushButton("登录")
        self.install_button = QPushButton("安装帮助")
        self.update_cli_button = QPushButton("更新 CLI / 查看方法")
        self.update_cli_button.clicked.connect(self.start_cli_update)
        for button in (self.detect_cli_button, self.login_button, self.install_button, self.update_cli_button):
            button.setObjectName("endpointSecondary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            cli_actions.addWidget(button)
        cli_layout.addLayout(cli_actions)
        self.logout_button = QPushButton("退出 Codex 登录")
        self.logout_button.setObjectName("endpointSecondary")
        self.logout_button.clicked.connect(lambda: self.start_login(action="logout"))
        self.copy_diagnostics_button = QPushButton("复制诊断信息")
        self.copy_diagnostics_button.setObjectName("endpointSecondary")
        self.copy_diagnostics_button.clicked.connect(self.copy_provider_diagnostics)
        account_actions = QHBoxLayout()
        account_actions.addWidget(self.logout_button)
        account_actions.addWidget(self.copy_diagnostics_button)
        cli_layout.addLayout(account_actions)
        self.diagnostics_toggle = QPushButton('展开诊断详情')
        self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.setObjectName('endpointSecondary')
        self.diagnostics_details = QPlainTextEdit()
        self.diagnostics_details.setObjectName('endpointDiagnostics')
        self.diagnostics_details.setReadOnly(True)
        self.diagnostics_details.setMaximumHeight(180)
        self.diagnostics_details.hide()
        self.diagnostics_toggle.toggled.connect(self.diagnostics_details.setVisible)
        cli_layout.addWidget(self.diagnostics_toggle)
        cli_layout.addWidget(self.diagnostics_details)

        # 2026-10-22 (user: no row may hold a few words across the whole width):
        # one row of three steps — ① service, ② key (or account login), ③ test —
        # each with its one line underneath: the guide, where the key is kept,
        # the test result.
        # 2026-10-13: every provider has its own application guide.
        self.guide_button = QPushButton("申请教程")
        self.guide_button.setObjectName("helpLink")
        self.guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.guide_button, '查看这家服务的申请步骤、官方链接与费用说明', property='toolTip')
        self.guide_button.clicked.connect(self._open_provider_guide)
        self.guide_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.service_label = QLabel("服务")
        self.key_step_label = QLabel("API Key")
        for caption in (self.service_label, self.key_step_label):
            caption.setObjectName("endpointStep")
        self.settings_stack = _CurrentPageStack()
        self.settings_stack.setObjectName("endpointSettingsStack")
        self.settings_stack.addWidget(self.api_page)
        self.settings_stack.addWidget(self.cli_page)
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # 2026-10-22 (design D2 refined): service, key, then the test with its
        # result beside it; the guide and 「模型与地址」 share the last line (the
        # AI settings dialog lends the guide to its left column).
        layout.setSpacing(6)
        layout.addWidget(self.service_label)
        layout.addWidget(self.service)
        layout.addSpacing(4)
        layout.addWidget(self.key_step_label)
        layout.addWidget(self.settings_stack)
        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 4, 0, 0)
        test_row.setSpacing(12)
        test_row.addWidget(self.test_button, 0, Qt.AlignmentFlag.AlignTop)
        test_row.addWidget(self.status, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(test_row)
        self._links_row = QHBoxLayout()
        self._links_row.setContentsMargins(0, 0, 0, 0)
        self._links_row.setSpacing(10)
        self._links_row.addWidget(self.guide_button)
        self._links_row.addStretch(1)
        layout.addLayout(self._links_row)
        self._guide_host = None
        self.model_label = QLabel("模型")
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model, 1)
        self.discover_models_button = QPushButton("刷新列表")
        self.discover_models_button.setObjectName("endpointSecondary")
        bind_text(self.discover_models_button, '后台获取模型列表；不支持时仍可手动输入', property='toolTip')
        model_row.addWidget(self.discover_models_button)
        # 已下线模型的显式提示位：不静默换模型，也绝不把墓碑 id 当正常选项。
        self.model_warning = QLabel()
        self.model_warning.setObjectName("fieldHint")
        self.model_warning.setWordWrap(True)
        self.model_warning.setStyleSheet("color:#f2c66d;")
        self.model_warning.hide()
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("endpointAdvancedToggle")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind_text(self.advanced_toggle, '模型与地址')
        self.advanced_box = QWidget()
        self.advanced_box.setObjectName("endpointAdvancedBox")
        advanced_layout = QVBoxLayout(self.advanced_box)
        advanced_layout.setContentsMargins(0, 4, 0, 0)
        advanced_layout.setSpacing(8)
        # One grid, so model, address and output line up (2026-10-22). 协议 has
        # its own row (2026-10-25): at the end of the model row it made the AI
        # settings dialog wider than its window and cut off its right side.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.capabilities_label = QLabel("输出能力")
        grid.addWidget(self.model_label, 0, 0)
        grid.addLayout(model_row, 0, 1)
        grid.addWidget(self.model_warning, 1, 1)
        grid.addWidget(self.protocol_label, 2, 0)
        grid.addWidget(self.protocol, 2, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.base_url_label, 3, 0)
        grid.addWidget(self.base_url, 3, 1)
        grid.addWidget(self.endpoint_hint, 4, 1)
        grid.addWidget(self.capabilities_label, 5, 0)
        grid.addWidget(self.capabilities_host, 5, 1)
        grid.addWidget(self.json_capability_status, 6, 1)
        grid.setColumnStretch(1, 1)
        advanced_layout.addLayout(grid)
        self.advanced_box.hide()
        self._advanced_hosted = False   # True while the dialog's 高级设置 shows the group
        self._advanced_host = None

        def show_advanced(checked):
            self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            if not self._advanced_hosted:
                self.advanced_box.setVisible(checked)

        self.advanced_toggle.toggled.connect(show_advanced)
        self._links_row.insertWidget(1, self.advanced_toggle)
        layout.addWidget(self.advanced_box)
        self.last_connection_ok = None

        restored_service = active["service"] if active["service"] in AI_SERVICE_SPECS else self._service_for_settings(current_transport, str(current_provider), self.base_url.text())
        self.service.setCurrentIndex(max(0, self.service.findData(restored_service)))
        self.provider.currentIndexChanged.connect(self._provider_or_url_changed)
        self.service.currentIndexChanged.connect(self._service_changed)
        self.base_url.textChanged.connect(self._provider_or_url_changed)
        self.base_url.textChanged.connect(self._refresh_endpoint_hint)
        self.protocol.currentIndexChanged.connect(self._refresh_endpoint_hint)
        self.test_button.clicked.connect(self.test_connection)
        self.detect_cli_button.clicked.connect(self.detect_cli)
        self.login_button.clicked.connect(self.start_login)
        self.install_button.clicked.connect(self.show_install_instructions)
        self.discover_models_button.clicked.connect(
            lambda: self.cancel_model_discovery() if self._model_discovery_running() else self.discover_models(refresh=True)
        )
        self._tester = None
        self._login_worker = None
        self._model_discovery_worker = None
        self._model_discovery_timer = QTimer(self)
        self._model_discovery_timer.setSingleShot(True)
        self._model_discovery_timer.setInterval(650)
        self._model_discovery_timer.timeout.connect(self.discover_models)
        self._connection_started_at = 0.0
        # remember last resolved provider+url to avoid wiping typed key on focus changes
        self._last_key_scope = (str(prov), str(burl))
        self._service_changed(initial=True)
        self._refresh_model_retirement_warning(restored_service)
        # 用户手动改选模型即视为对"重新选择"警告的回应；保存后旧值移除。
        self.model.currentTextChanged.connect(lambda *_: self.model_warning.hide())
        for signal in (
            self.base_url.editingFinished,
            self.key.editingFinished,
            self.protocol.currentIndexChanged,
            self.service.currentIndexChanged,
        ):
            signal.connect(self._queue_model_discovery)
        self._discovery_pending = False
        self.base_url.textChanged.connect(self._invalidate_model_discovery)
        self.key.textChanged.connect(self._invalidate_model_discovery)
        for signal in (self.model.currentTextChanged, self.base_url.textChanged,
                self.key.textChanged, self.protocol.currentIndexChanged,
                self.json_mode.toggled, self.structured_output.toggled):
            signal.connect(self._invalidate_endpoint_tasks)
        self._queue_model_discovery()
        self.refresh_theme_palette()

    def _show_key_placeholder(self, existing, source) -> None:
        """Plain words in the key box (2026-10-22): no storage names in sight, they are the hover text."""
        if existing:
            bind_text(self.key, '已保存；要换就直接粘贴新的 Key', property='placeholderText')
            bind_text(self.key, '已保存的 Key：{value0}', property='toolTip', value0=source)
        else:
            bind_text(self.key, '粘贴 API Key', property='placeholderText')
            self.key.setToolTip("")

    def host_guide(self, layout) -> None:
        """Lend 「申请教程」 to ``layout`` (the AI settings dialog's guide column)."""
        if self._guide_host is layout:
            return
        self.restore_guide()
        self._links_row.removeWidget(self.guide_button)
        self._guide_host = layout
        self.guide_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.guide_button)

    def restore_guide(self) -> None:
        host = self._guide_host
        if host is None:
            return
        self._guide_host = None
        host.removeWidget(self.guide_button)
        self.guide_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        bind_text(self.guide_button, "申请教程")
        self._links_row.insertWidget(0, self.guide_button)

    def has_key(self) -> bool:
        """A key typed here or saved for this service (account logins need none)."""
        if self.values()["transport"] != AITransport.OPENAI_COMPATIBLE.value:
            return True
        if self._key_state == "clear":
            return False
        if self.key.text().strip():
            return True
        prov, burl = self._current_provider_base()
        existing, _source = read_api_key(prov, burl)
        if not existing and prov in {"bailian", "dashscope"}:
            existing = resolve_api_key(self.stage)[0]
        return bool(existing)

    def set_bare(self, bare: bool) -> None:
        """No frame of its own (the AI settings dialog's top form sits beside the guide)."""
        bare = bool(bare)
        if self.property("bare") == bare:
            return
        self.setProperty("bare", bare)
        self._layout.setContentsMargins(*((0, 0, 0, 0) if bare else (14, 12, 14, 13)))
        self.style().unpolish(self)
        self.style().polish(self)

    def set_emphasis(self, *, test: bool, guide: bool) -> None:
        """The one pink button of the moment: 申请教程 without a key, 测试连接 once one is in."""
        for button, strong in ((self.test_button, test), (self.guide_button, guide)):
            if button.property("emphasis") != ("primary" if strong else "secondary"):
                button.setProperty("emphasis", "primary" if strong else "secondary")
                button.style().unpolish(button)
                button.style().polish(button)

    def host_advanced(self, layout) -> None:
        """Show the advanced group (model, address, protocol, output) in ``layout`` — the
        AI settings dialog's own 高级设置 — instead of under this editor."""
        if self._advanced_host is layout:
            return
        self.restore_advanced()
        self._layout.removeWidget(self.advanced_box)
        self._advanced_host = layout
        self._advanced_hosted = True
        self.advanced_toggle.hide()
        layout.addWidget(self.advanced_box)
        self.advanced_box.show()

    def restore_advanced(self) -> None:
        """Put the advanced group back under this editor, behind its own toggle."""
        host = self._advanced_host
        if host is None:
            return
        self._advanced_host = None
        self._advanced_hosted = False
        host.removeWidget(self.advanced_box)
        self._layout.addWidget(self.advanced_box)   # the group is the editor's last block
        self.advanced_toggle.show()
        self.advanced_box.setVisible(self.advanced_toggle.isChecked())

    def _refresh_model_retirement_warning(self, service_id: str = "") -> None:
        """已下线模型的显式告知：编辑器回落默认，但绝不静默沿用墓碑 id。"""
        service_id = str(service_id or getattr(self, "_active_service_id", "") or "custom")
        profile = normalize_provider_profile(
            get_provider_profiles(self._settings_ref).get(service_id, {})
        )
        stored = profile.get("model", "")
        if not stored:
            flat_prefix = self.stage if self.stage in {"polish", "group"} else "polish"
            stored = str(
                self._settings_ref.get("models", {}).get(f"{flat_prefix}_model", "") or ""
            ).strip()
        if model_is_retired(stored):
            bind_text(self.model_warning, '此前选择的模型 {stored} 已不可用，请从当前可用模型中重新选择；保存新选择后旧值会被移除。', stored=stored)
            self.model_warning.show()
        else:
            self.model_warning.hide()

    @staticmethod
    def _service_for_settings(transport: str, provider: str, base_url: str) -> str:
        if transport == AITransport.ANTIGRAVITY_CLI.value:
            return "antigravity"
        if transport == AITransport.GROK_CLI.value:
            return "grok_account"
        if transport == AITransport.CODEX_CLI.value:
            return "codex_cli"
        if provider in AI_SERVICE_SPECS and provider not in {"antigravity", "grok_account"}:
            return provider
        host = str(base_url or "").casefold()
        if "api.openai.com" in host:
            return "openai"
        if "api.deepseek.com" in host:
            return "deepseek"
        if "generativelanguage.googleapis.com" in host:
            return "gemini"
        if "api.x.ai" in host:
            return "xai"
        if "api.anthropic.com" in host:
            return "claude"
        return "custom"

    def _service_changed(self, _index: int = -1, *, initial: bool = False) -> None:
        self._invalidate_endpoint_tasks()
        if hasattr(self, '_model_discovery_timer'):
            self._invalidate_model_discovery()
        service_id = str(self.service.currentData() or "custom")
        spec = AI_SERVICE_SPECS[service_id]
        self._active_service_id = service_id
        transport = str(spec["transport"])
        self.transport.blockSignals(True)
        self.transport.setCurrentIndex(max(0, self.transport.findData(transport)))
        self.transport.blockSignals(False)
        provider = str(spec["provider"])
        provider_index = self.provider.findData(provider)
        if provider_index >= 0:
            self.provider.blockSignals(True)
            self.provider.setCurrentIndex(provider_index)
            self.provider.blockSignals(False)
        is_api = transport == AITransport.OPENAI_COMPATIBLE.value
        self.settings_stack.setCurrentWidget(self.api_page if is_api else self.cli_page)
        self.settings_stack.setMaximumHeight(16777215)
        # A hidden page must not reserve height (QStackedLayout skips Ignored).
        for page in (self.api_page, self.cli_page):
            visible = page is self.settings_stack.currentWidget()
            page.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Preferred if visible else QSizePolicy.Policy.Ignored)
        self.settings_stack.updateGeometry()
        self.custom_name.setVisible(service_id == "custom")
        self.custom_name_label.setVisible(service_id == "custom")
        for widget in (self.base_url_label, self.base_url, self.endpoint_hint, self.protocol, self.protocol_label):
            widget.setVisible(is_api)
        bind_text(self.key_step_label, 'API Key' if is_api else '登录账号')
        if service_id == "custom" and hasattr(self, "advanced_toggle"):
            # A custom service needs its Base URL: open the advanced group.
            self.advanced_toggle.setChecked(True)
            self.advanced_wanted.emit()
        if not initial:
            # 原子切换：Base URL / 模型 / 协议必须一次性按新 Provider 的
            # profile 加载。期间屏蔽这些控件自身的信号，避免旧字段的部分
            # 更新（例如把 Google Base URL 残留进 DeepSeek profile）。
            values = resolved_service_values(self._settings_ref, service_id)
            self.base_url.blockSignals(True)
            self.base_url.setText(values["base_url"])
            self.base_url.blockSignals(False)
            self._load_service_models(service_id, values["model"])
            protocol_index = self.protocol.findData(values["protocol"] or "auto")
            if protocol_index >= 0:
                self.protocol.blockSignals(True)
                self.protocol.setCurrentIndex(protocol_index)
                self.protocol.blockSignals(False)
            self._last_key_scope = (provider, values["base_url"])
            self.json_mode.setChecked(values.get('json_mode', True))
            self.structured_output.setChecked(values.get('structured_output', True))
            self.refresh_secret_status()
            self._queue_model_discovery()
        self._refresh_model_retirement_warning(service_id)
        (bind_text(self.model, '默认模型', property='placeholderText') if not is_api else bind_text(self.model, '模型名称', property='placeholderText'))
        (bind_text(self.login_button, '打开官方 Codex 登录') if service_id == 'codex_cli' else (bind_text(self.login_button, '打开 Google 登录') if service_id == 'antigravity' else bind_text(self.login_button, '管理 Grok 登录')))
        self.logout_button.setVisible(service_id == "codex_cli")
        self.install_button.setVisible(not is_api)
        self.update_cli_button.setVisible(service_id == 'grok_account')
        self.diagnostics_details.clear()
        self.diagnostics_toggle.setChecked(False)
        self.json_mode.setEnabled(True)
        self.structured_output.setEnabled(True)
        bind_text(self.structured_output, 'Structured Output')
        bind_text(self.json_mode, 'JSON 答案始终进行本地校验；CLI 外层事件 JSON 与模型答案 JSON 分别校验。', property='toolTip')
        bind_text(self.structured_output, '启用时优先使用已检测支持的原生 JSON Schema；关闭时使用兼容 JSON／本地校验。', property='toolTip')
        bind_text(self.json_capability_status, '结构化能力：尚未检测；模型列表获取不决定 JSON 能力。')
        bind_text(self.cli_status, 'CLI：未检测')
        (bind_text(self.account_status, 'Antigravity CLI Session：未知') if service_id == 'antigravity' else bind_text(self.account_status, '{value0} Session：未知', value0=spec['label']))
        if is_api:
            self.refresh_secret_status()
        else:
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '请先检测 CLI 与登录状态')
        self._refresh_endpoint_hint()

    def _load_service_models(self, service_id: str, model: str) -> None:
        """模型下拉换成该服务自己的目录（不联网）；选项里绝不留上一家的模型。"""
        items = [item for item in service_model_catalog(self._settings_ref, service_id)
                 if not model_is_retired(item)]
        if model_is_retired(model):
            model = items[0] if items else ""  # 已下线：回落默认，提示由 model_warning 给出
        if model and model not in items:
            items.insert(0, model)  # 保存过的自定义模型仍可选
        previous = self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(items)
        if model:
            self.model.setCurrentText(model)
        else:
            self.model.setCurrentIndex(-1)
            self.model.setEditText("")
        self.model.blockSignals(previous)

    def _transport_changed(self) -> None:
        self._service_changed()

    def _open_provider_guide(self) -> None:
        from dataclasses import replace
        from .api_setup_dialog import ApiSetupDialog
        window = self.window()
        factory = getattr(window, '_api_setup_host', None)
        if factory is None:
            parent = window.parentWidget() if window is not None else None
            factory = getattr(parent.window() if parent is not None else None, '_api_setup_host', None)
        if factory is None:
            return
        host = replace(factory(), open_text_settings=None)
        service_id = str(self.service.currentData() or 'custom')
        ApiSetupDialog(window, host, kind='text', initial=service_id,
                       show_advanced=service_id in {'custom', 'grok_account', 'codex_cli', 'antigravity'}).exec()

    def refresh_theme_palette(self) -> None:
        theme = _active_theme_definition()
        accent = theme.primary_role if self.stage == "polish" else theme.secondary_role
        self.setStyleSheet(f"""
            QFrame#endpointCard {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
            QFrame#endpointCard[bare="true"] {{ background: transparent; border: 0; }}
            QFrame#endpointCard QLabel#endpointKeyNote {{ color: {theme.text_muted}; font-size: 12px; }}
            QFrame#endpointCard QLabel#muted, QFrame#endpointCard QLabel#statusGood, QFrame#endpointCard QLabel#statusWarn {{
                font-size: 13px; font-weight: 500; }}
            QFrame#endpointCard QLabel#muted {{ color: {theme.text_secondary}; }}
            QFrame#endpointCard QLabel#statusGood {{ color: {theme.success}; }}
            QFrame#endpointCard QLabel#statusWarn {{ color: {theme.warning}; }}
            QFrame#endpointCard QLabel#endpointStep {{ color: {theme.text_secondary}; font-size: 12px; font-weight: 700; }}
            QFrame#endpointCard QWidget#endpointAdvancedBox {{ background: transparent; border: 0; }}
            QFrame#endpointCard QLabel {{ color: {theme.text}; background: transparent; }}
            QFrame#endpointCard QLabel#endpointTitle {{ color: {accent}; font-size: 15px; font-weight: 700; }}
            QFrame#endpointCard QLineEdit, QFrame#endpointCard QComboBox {{
                color: {theme.text}; background: {theme.surface_input}; border: 1px solid {theme.border};
                border-radius: 10px; padding: 6px 12px; selection-background-color: {theme.selected};
                min-height: 34px; max-height: 34px;
            }}
            QFrame#endpointCard QLineEdit:focus, QFrame#endpointCard QComboBox:focus {{ border-color: {theme.accent}; }}
            QFrame#endpointCard QPlainTextEdit#endpointDiagnostics {{
                color: {theme.text}; background: {theme.surface_input}; border: 1px solid {theme.border};
                border-radius: 6px; padding: 6px; font-family: {UI_FONT_STACK}; font-size: 12px;
                selection-background-color: {theme.selected};
            }}
            QFrame#endpointCard QPushButton#endpointSecondary {{
                color: {theme.text}; background: {theme.control_background}; border: 1px solid {theme.border};
                border-radius: 6px; padding: 6px 10px;
            }}
            QFrame#endpointCard QPushButton#endpointSecondary:hover {{ background: {theme.control_hover}; border-color: {theme.accent}; }}
            QFrame#endpointCard QPushButton#endpointPrimary {{
                color: {theme.text_on_accent}; background: {theme.accent}; border: 1px solid {theme.accent};
                border-radius: 10px; padding: 0 18px; font-size: 14px; font-weight: 650;
                min-height: 46px; max-height: 46px; min-width: 112px;
            }}
            QFrame#endpointCard QPushButton#endpointPrimary:hover {{
                background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}
            QFrame#endpointCard QPushButton#endpointPrimary[emphasis="secondary"] {{
                color: {theme.text}; background: {theme.control_background}; border: 1px solid {theme.border}; }}
            QFrame#endpointCard QPushButton#endpointPrimary[emphasis="secondary"]:hover {{
                background: {theme.control_hover}; border-color: {theme.border_strong}; }}
            QFrame#endpointCard QPushButton#endpointPrimary:disabled {{ background: {theme.control_background}; color: {theme.text_muted}; border-color: {theme.border}; }}
            QFrame#endpointCard QWidget#endpointApiPage, QFrame#endpointCard QWidget#endpointCliPage,
            QFrame#endpointCard QStackedWidget#endpointSettingsStack {{ background: transparent; border: 0; }}
        """)
        self.title_label.setObjectName("endpointTitle")
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)

    def _current_provider_base(self):
        prov = str(self.provider.currentData() or "custom")
        burl = normalize_base_url(self.base_url.text())
        return prov, burl

    def _refresh_endpoint_hint(self):
        base = normalize_base_url(self.base_url.text())
        protocol = str(self.protocol.currentData() or "auto")
        suffix = ("/messages" if str(self.provider.currentData() or "") == "anthropic"
                  else "/responses" if protocol == "responses" else "/chat/completions")
        bind_text(self.endpoint_hint, "实际请求：{url}", url=base+suffix) if base else bind_text(self.endpoint_hint, "填写 Base URL，程序会按所选协议补全请求路径。")

    def _on_key_text_changed(self, text: str) -> None:
        # Manual editing (including select-all + delete) never clears the
        # stored secret: typing anything = REPLACE, emptying by hand returns
        # to UNCHANGED. Only the explicit "清除密钥" button requests CLEAR.
        if self._key_state == "clear":
            return
        self._key_state = "replace" if text.strip() else "unchanged"
        if text.strip() and self.status.objectName() != "statusWarn":
            self.status.setObjectName("muted")
            bind_text(self.status, '发一条很短的请求，几秒就好')
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        elif not text.strip():
            self.refresh_secret_status()

    def _request_key_clear(self) -> None:
        self._invalidate_endpoint_tasks()
        self._key_state = "clear"
        self.key.clear()
        bind_text(self.key, '将在保存时清除已保存的密钥（环境变量不受影响）', property='placeholderText')
        self.status.setObjectName("statusWarn")
        bind_text(self.status, '已请求清除：点「保存设置」后生效')
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._clear_action.setVisible(False)
        self.configuration_edited.emit()

    def refresh_secret_status(self):
        prov, burl = self._current_provider_base()
        if getattr(self, "_key_state", "unchanged") == "clear":
            return  # keep the "清除已请求" status until save/reload
        existing, source = read_api_key(prov, burl)
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(self.stage)
        self._show_key_placeholder(existing, source)
        self._clear_action.setVisible(bool(existing))
        self.status.setObjectName("statusGood" if existing else "muted")
        (bind_text(self.status, credential_storage_notice() if session_credentials_enabled() else '密钥已保存，测一次就好') if existing else bind_text(self.status, '贴上 Key 后就能测试'))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def accept_saved_configuration(self, settings):
        """Publish before notifications; clearing a saved key is not an edit.

        A test for the same effective configuration may finish after Save.
        Its request snapshot remains private and is checked by the callback.
        """
        from PySide6.QtCore import QSignalBlocker
        from .ai_connection_record import fingerprint, result_for
        self._settings_ref = settings
        with QSignalBlocker(self.key):
            self.key.clear()
            self._key_state = 'unchanged'
        if fingerprint(self._provider_settings(), self.stage) != fingerprint(settings, self.stage):
            # Unified Save also changes the hidden polish form. Leaving that
            # form stale resurrected its old service as soon as either switch
            # was toggled off, even though the settings file already held B.
            from .asr_provider_snapshot import resolve_provider_snapshot
            snapshot = resolve_provider_snapshot(settings, stage=self.stage)
            endpoint = snapshot.endpoint()
            self.restore_profile_values({
                'service': snapshot.profile_id, 'provider': snapshot.provider,
                'transport': snapshot.transport, 'model': snapshot.model,
                'base_url': endpoint.get('base_url', ''), 'protocol': snapshot.protocol,
                'json_mode': snapshot.json_mode, 'structured_output': snapshot.structured_output,
            }, settings)
        tester = getattr(self, '_tester', None)
        if tester is not None and fingerprint(tester.settings, self.stage) != fingerprint(self._provider_settings(), self.stage):
            self._invalidate_endpoint_tasks()
        self.last_connection_ok = result_for(self._provider_settings(), self.stage)
        self.refresh_secret_status()

    def connection_test_running(self, settings=None):
        from .ai_connection_record import fingerprint
        tester = getattr(self, '_tester', None)
        return bool(tester is not None and tester.isRunning()
                    and fingerprint(tester.settings, self.stage)
                    == fingerprint(settings if settings is not None else self._provider_settings(), self.stage))

    def _provider_or_url_changed(self):
        prov, burl = self._current_provider_base()
        # Load provider-scoped key for the new (provider, base). Do not overwrite if user has typed something new.
        existing, source = read_api_key(prov, burl)
        if not existing and prov in {"bailian", "dashscope"}:
            existing, source = resolve_api_key(self.stage)
        # If scope changed, update placeholder; if user already typed in this session, keep it.
        scope = (prov, burl)
        if scope != getattr(self, "_last_key_scope", None):
            self._last_key_scope = scope
            # Only reset placeholder text; do not clear an explicitly typed value.
            typed = self.key.text().strip()
            if not typed:
                self._show_key_placeholder(existing, source)
            # If nothing typed, show hint of existing for this provider/url.
            if not typed and existing:
                self.status.setObjectName("statusGood")
                bind_text(self.status, credential_storage_notice() if session_credentials_enabled() else '密钥已保存（此服务商）')
                self.status.style().unpolish(self.status)
                self.status.style().polish(self.status)

    def values(self) -> dict:
        service_id = str(self.service.currentData() or "custom")
        spec = AI_SERVICE_SPECS[service_id]
        return {
            "service": service_id,
            "transport": str(spec["transport"]),
            "provider": str(spec["provider"]),
            "provider_name": self.custom_name.text().strip() if service_id == "custom" else str(spec["label"]),
            "model": self.model.currentText().strip(),
            "base_url": normalize_base_url(self.base_url.text()),
            "key": self.key.text().strip(),
            "key_state": getattr(self, "_key_state", "unchanged"),
            "protocol": str(self.protocol.currentData() or "auto"),
            "json_mode": self.json_mode.isChecked(),
            "structured_output": self.structured_output.isChecked(),
            "stream": False,
        }

    def restore_profile_values(self, values: dict, settings: dict) -> None:
        """Restore one endpoint without intermediate signals or network work."""
        from PySide6.QtCore import QSignalBlocker
        self._invalidate_model_discovery()
        self._discovery_pending = False
        self._settings_ref = settings
        controls = (self.service, self.provider, self.transport, self.model, self.base_url,
                    self.protocol, self.key, self.custom_name, self.json_mode, self.structured_output)
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            index = self.service.findData(values["service"])
            if index < 0:
                raise ValueError("方案中的 AI 服务不可用")
            self.service.setCurrentIndex(index)
            self._service_changed(initial=True)
            self._load_service_models(values["service"], values["model"])
            self.base_url.setText(values["base_url"])
            self.protocol.setCurrentIndex(max(0, self.protocol.findData(values.get("protocol") or "auto")))
            bind_text(self.custom_name, values.get('provider_name') or '自定义服务')
            self.json_mode.setChecked(values.get("json_mode", True))
            self.structured_output.setChecked(values.get("structured_output", True))
            self.key.clear()
            self._key_state = "unchanged"
            self._last_key_scope = (values["provider"], values["base_url"])
        finally:
            del blockers
        self.refresh_secret_status()
        self._refresh_endpoint_hint()

    def _cli_settings(self) -> dict:
        """Test exactly what Generate will resolve after these edits are saved.

        A bare ``{transport, model}`` dict tested a different resolution path
        than the saved-settings one AI Design uses, so Test could pass on
        Antigravity while Generate left for another transport. Overlay the
        editor selection onto a copy of the live settings and activate the
        selected service in that copy — identical post-save resolution.
        """
        return self._provider_settings()

    def _provider_settings(self) -> dict:
        """Model discovery must resolve the same post-save world as _cli_settings.

        2026-09-04：裸平铺 dict 缺 ``ai_service``/``polish_provider`` 时，
        get_active_service 迁移路径在 group 编辑器（全文断句模型）下回落默认
        grok_account——选 DeepSeek 预设点“刷新模型”却拉到 Grok CLI 的模型列表。
        与连接测试同构：live settings 拷贝 + activate_ai_service 覆盖层。
        """
        values = self.values()
        base = self._settings_ref
        overlay = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
        overlay.setdefault("models", {})
        service_id = str(values.get("service") or "custom")
        if service_id in AI_SERVICE_SPECS:
            activate_ai_service(overlay, service_id, stage=self.stage)
        overlay["models"][f"{self.stage}_transport"] = values["transport"]
        overlay["models"][f"{self.stage}_provider"] = values["provider"]
        overlay["models"][f"{self.stage}_protocol"] = values["protocol"]
        overlay["models"][f"{self.stage}_model"] = values["model"]
        overlay["models"][f"{self.stage}_base_url"] = values["base_url"]
        update_active_profile(overlay, stage=self.stage, base_url=values['base_url'],
                              model=values['model'], protocol=values['protocol'],
                              json_mode=values['json_mode'], structured_output=values['structured_output'])
        # Ephemeral only: persist_ai_configuration never serializes this key.
        overlay["models"][f"{self.stage}_api_key"] = values["key"]
        if overlay.get('switches',{}).get('unified_glm_processing'):
            overlay['models']['group_api_key']=values['key']
            overlay['models']['polish_api_key']=values['key']
        return overlay

    def _model_discovery_identity(self):
        from .model_discovery import identity
        values=self.values()
        key=values['key'] or read_api_key(values['provider'],values['base_url'])[0]
        return identity(values['provider'], values['base_url'], key)+(values['service'],values['protocol'])

    def _invalidate_model_discovery(self, *_):
        self._discovery_epoch = getattr(self, '_discovery_epoch', 0) + 1
        self._model_discovery_timer.stop()
        if self._model_discovery_running():
            self._model_discovery_worker.requestInterruption()
        # Edits invalidate old callbacks immediately; only editingFinished
        # or an explicit refresh initiates network traffic.

    def _model_discovery_done(self, worker):
        if self._model_discovery_worker is worker:
            self._model_discovery_worker=None
            bind_text(self.discover_models_button, '刷新模型')
            self.discover_models_button.setEnabled(True)
            if self._discovery_pending:
                self._discovery_pending=False
                self._queue_model_discovery()
        worker.deleteLater()

    def _queue_model_discovery(self, *_args) -> None:
        if not hasattr(self, "_model_discovery_timer"):
            return
        values = self.values()
        if values["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            if not values["base_url"]:
                return
            stored_key = read_api_key(values["provider"], values["base_url"])[0]
            if not values["key"] and not stored_key:
                return
        self._model_discovery_timer.start()

    def _model_discovery_running(self) -> bool:
        return bool(
            self._model_discovery_worker is not None
            and self._model_discovery_worker.isRunning()
        )

    def discover_models(self, *, refresh: bool = False) -> None:
        if self._model_discovery_running():
            self._discovery_pending=True
            return
        values = self.values()
        if not supports_model_discovery(values.get("service", "custom")):
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '该服务不支持自动获取模型列表；可直接输入模型 ID')
            return
        if values["transport"] == AITransport.OPENAI_COMPATIBLE.value:
            stored_key = read_api_key(values["provider"], values["base_url"])[0]
            if not values["base_url"] or (not values["key"] and not stored_key):
                self.status.setObjectName("statusWarn")
                bind_text(self.status, '填写 Base URL 与 API Key 后可获取模型；也可手动输入模型 ID')
                return
        bind_text(self.discover_models_button, '取消')
        self.status.setObjectName("statusWarn")
        bind_text(self.status, '正在后台获取模型列表…')
        worker = ProviderModelDiscoveryWorker(
            self._provider_settings(),
            self.stage,
            refresh=refresh,
            parent=self,
        )
        self._model_discovery_worker = worker
        scope=self._model_discovery_identity()
        epoch = getattr(self, '_discovery_epoch', 0)
        worker.succeeded.connect(lambda models: self._model_discovery_succeeded(models)
            if epoch==getattr(self, '_discovery_epoch', 0) and scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
        worker.failed.connect(lambda message: self._model_discovery_failed(message)
            if epoch==getattr(self, '_discovery_epoch', 0) and scope==self._model_discovery_identity() and not worker.isInterruptionRequested() else None)
        worker.finished.connect(lambda:self._model_discovery_done(worker))
        worker.start()

    def cancel_model_discovery(self) -> None:
        if not self._model_discovery_running():
            return
        self._model_discovery_worker.requestInterruption()
        self.discover_models_button.setEnabled(False)
        bind_text(self.status, '正在取消模型发现…')

    def _model_discovery_succeeded(self, models: list) -> None:
        current = self.model.currentText().strip()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems([str(item) for item in models])
        if current:
            # 刷新列表绝不悄悄改选择：saved model 仍存在 → 原样保留；
            # 已不存在 → 保留文本但明确提示需要确认（Test 3/4）。
            self.model.setCurrentText(current)
        else:
            self.model.setCurrentIndex(-1)
            self.model.setEditText('')
        self.model.blockSignals(False)
        self._refresh_model_retirement_warning()
        self.discover_models_button.setEnabled(True)
        discovered = [str(item).strip() for item in models]
        if current and discovered and current not in discovered:
            self.status.setObjectName("statusWarn")
            bind_text(self.status, '已发现 {value0} 个模型 · 当前所选不在最新列表中，请确认后保存', value0=len(models))
        else:
            self.status.setObjectName("statusGood")
            bind_text(self.status, '已发现 {value0} 个模型 · 可搜索选择或手动输入', value0=len(models))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _model_discovery_failed(self, message: str) -> None:
        self.discover_models_button.setEnabled(True)
        self.status.setObjectName("statusWarn")
        self.status.setText(str(message))

    def detect_cli(self) -> None:
        service_id = str(self.service.currentData() or "")
        self.detect_cli_button.setEnabled(False)
        bind_text(self.cli_status, 'CLI：检测中…')
        (bind_text(self.account_status, 'Antigravity CLI Session：检测真实请求中…') if service_id == 'antigravity' else bind_text(self.account_status, '{value0} Session：检测中…', value0=str(AI_SERVICE_SPECS[service_id]['label'])))
        self._tester = ProviderConnectionTester(
            self._cli_settings(), self.stage, prompt_test=False, force_refresh=True
        )
        self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._detect_finished))
        self._tester.start()

    def _detect_finished(self, ok: bool, message: str) -> None:
        self.detect_cli_button.setEnabled(True)
        detected_models = tuple(getattr(self._tester, "models", ()) or ())
        if detected_models:
            current_model = self.model.currentText().strip()
            self.model.blockSignals(True)
            self.model.clear()
            self.model.addItems(list(dict.fromkeys(filter(None, (current_model, *detected_models)))))
            self.model.setCurrentText(current_model or detected_models[0])
            self.model.blockSignals(False)
        diagnostics = dict(getattr(self._tester, 'diagnostics', {}) or {})
        self._show_cli_diagnostics(diagnostics, ok=ok, request_test=False)
        installed = bool(diagnostics.get('executable')) if diagnostics else "未安装" not in message and "未检测到" not in message
        self.install_button.setVisible(not installed)
        service_id = str(self.service.currentData() or "")
        prefix = str(AI_SERVICE_SPECS[service_id]["label"]) + " Session"
        if ok and service_id == "codex_cli":
            bind_text(self.login_button, '重新登录或切换账号')
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def copy_provider_diagnostics(self):
        from .provider_diagnostics import redact_diagnostics
        provider=provider_for_stage(self._provider_settings(),self.stage)
        payload=redact_diagnostics({"provider":self.values()["service"],"model":self.model.currentText(),
            "status":self.status.text(),"diagnostics":getattr(self, '_last_cli_diagnostics', {}),
            "trace":provider.invocation_trace()})
        QApplication.clipboard().setText(json.dumps(payload,ensure_ascii=False,indent=2))

    def _show_cli_diagnostics(self, diagnostics, *, ok, request_test):
        from .provider_diagnostics import redact_diagnostics
        diagnostics = redact_diagnostics(diagnostics)
        self._last_cli_diagnostics = diagnostics
        self._show_json_capabilities(diagnostics.get('json_capabilities', {}))
        path = diagnostics.get('executable') or '未检测到'
        version = diagnostics.get('cli_version') or '版本未检测'
        self.cli_status.setText(f'CLI：{version}\n{path}')
        evidence = diagnostics.get('auth_evidence')
        credential = {'model_catalog': '模型目录验证过凭据', 'successful_model_request': '实际请求验证过凭据',
                      'official_auth_error': '官方 CLI 提示未登录'}.get(evidence, '凭据状态未知')
        category = diagnostics.get('category')
        request = ('连接测试通过（中文 JSON）' if ok and request_test else
                   '需更新 CLI；本次请求失败' if category == 'upgrade_required' else
                   '连接测试失败' if request_test else '当前配置真实请求尚未验证')
        tested = diagnostics.get('last_tested_at')
        self.account_status.setText(f'登录/凭据：{credential}\n请求：{request}' + (f' · {tested}' if tested else ''))
        self.update_cli_button.setVisible(str(self.service.currentData()) == 'grok_account')
        self.diagnostics_details.setPlainText(json.dumps(diagnostics, ensure_ascii=False, indent=2))

    def _show_json_capabilities(self, evidence):
        state = evidence.get('state', 'unverified')
        if state == 'verified':
            text = '结构化能力：原生 JSON Schema 已验证；答案同时通过本地校验。'
        elif evidence.get('native_schema'):
            text = '结构化能力：本机 CLI 支持原生 JSON Schema；当前模型尚未通过请求验证。'
        elif state == 'unsupported':
            text = '结构化能力：本机 CLI 未提供原生 Schema；使用兼容 JSON／本地校验。'
        elif state == 'failed':
            text = '结构化能力：检测失败；保留 JSON 选项，可重新检测。'
        else:
            text = '结构化能力：尚未检测；模型列表获取不决定 JSON 能力。'
        bind_text(self.json_capability_status, text)

    def start_cli_update(self):
        settings = self._provider_settings()
        provider = provider_for_stage(settings, self.stage)
        try:
            plan = provider.cli_update_plan()
        except Exception as exc:
            self.status.setText(str(exc))
            return
        target = plan.get('executable') or '未检测到 CLI'
        command = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in plan.get('command', []))
        if not plan.get('supported'):
            QMessageBox.information(self, '查看 CLI 更新方法', f'实际目标：{target}\n\n{plan["message"]}\n\n更新后点击重新检测和测试连接。')
            return
        result = QMessageBox.question(self, '确认更新这份 CLI',
            f'目标路径：{target}\n当前版本：{plan.get("version") or "未检测"}\n动作：{command}\n\n'
            f'{plan["message"]}\n完成后将重新读取路径/版本并执行一次最小普通文本请求。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if result != QMessageBox.StandardButton.Yes:
            return
        self._invalidate_endpoint_tasks()
        self._update_worker = ProviderCLIUpdateWorker(settings, self.stage, plan)
        self._update_worker.finished_status.connect(self._endpoint_callback(self._update_worker, '_update_worker', self._cli_update_finished))
        self.update_cli_button.setEnabled(False)
        self.status.setText('正在更新已确认的 CLI…')
        self._update_worker.start()

    def _cli_update_finished(self, ok, message):
        self.update_cli_button.setEnabled(True)
        self._show_cli_diagnostics(self._update_worker.diagnostics, ok=ok, request_test=True)
        self.status.setObjectName('statusGood' if ok else 'statusWarn')
        self.status.setText(message)

    def start_login(self, _checked=False, *, action="login") -> None:
        if self._login_worker is not None and self._login_worker.isRunning():
            self._login_worker.requestInterruption()
            bind_text(self.status, '正在取消官方登录…')
            return
        bind_text(self.login_button, '取消登录')
        self.logout_button.setEnabled(False)
        (bind_text(self.account_status, '正在启动官方登录窗口…') if action == 'login' else bind_text(self.account_status, '正在退出官方 CLI 登录…'))
        self._login_worker = ProviderLoginWorker(self._cli_settings(), self.stage, action=action)
        self._login_worker.finished_status.connect(self._endpoint_callback(self._login_worker, '_login_worker', self._login_finished))
        self._login_worker.login_progress.connect(self._endpoint_callback(self._login_worker, '_login_worker', self._login_progress))
        self._login_worker.start()

    @staticmethod
    def _linkify(message: str) -> str:
        message = html.unescape(str(message or ""))
        match = re.search(r"https?://[^\s\"'<]+", str(message or ""))
        if not match:
            return message
        url = match.group(0)
        head, _, tail = str(message).partition(url)
        return (
            f"{html.escape(head)}<a href=\"{html.escape(url, quote=True)}\">{html.escape(url)}</a>{html.escape(tail)}"
        )

    def _login_progress(self, message: str) -> None:
        text = str(message or "")
        if text.startswith("http"):
            self.status.setTextFormat(Qt.TextFormat.RichText)
            self.status.setObjectName("statusInfo")
            bind_text(self.status, '在浏览器完成登录即可（窗口会自动收尾，无需保持任何外部窗口）：<br>{value0}', value0=self._linkify(text))
        else:
            self.status.setTextFormat(Qt.TextFormat.PlainText)
            self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _login_finished(self, ok: bool, message: str) -> None:
        self.login_button.setEnabled(True)
        service_id=str(self.service.currentData() or "custom")
        label=str(AI_SERVICE_SPECS[service_id]["label"])
        ((bind_text(self.login_button, '重新登录或切换账号') if ok else bind_text(self.login_button, '打开官方 Codex 登录')) if service_id == 'codex_cli' else bind_text(self.login_button, '打开登录'))
        self.logout_button.setEnabled(True)
        bind_text(self.account_status, f'{label}：' + ('登录流程完成；当前配置请求仍需测试' if ok else '登录未完成，请重新检测'))
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setText(html.unescape(str(message)))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if ok:
            self.discover_models(refresh=True)

    def show_install_instructions(self) -> None:
        service_id = str(self.service.currentData() or "")
        name = str(AI_SERVICE_SPECS.get(service_id, {}).get("label") or "CLI")
        QMessageBox.information(
            self,
            tr('安装 {value0}', value0=name),
            tr('当前未由 2ByteASR 自动安装 {value0}。请从该服务的官方发布渠道安装，完成后回到这里点击“检测 CLI”。\n\n2ByteASR 不读取或保存 OAuth token。', value0=name),
        )

    def test_connection(self):
        values = self.values()
        if values["transport"] != AITransport.OPENAI_COMPATIBLE.value:
            if self._tester is not None and self._tester.isRunning():
                self._tester.requestInterruption()
                self.test_button.setEnabled(False)
                bind_text(self.status, '正在取消测试…')
                return
            self._connection_started_at = time.monotonic()
            self.test_button.setEnabled(True)
            bind_text(self.test_button, '取消测试')
            bind_text(self.status, '正在执行最小连接测试…')
            self._tester = ProviderConnectionTester(self._cli_settings(), self.stage, prompt_test=True)
            self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._connection_finished))
            self._tester.start()
            tester = self._tester
            QTimer.singleShot(5000, lambda: self._show_slow_connection_hint(tester))
            return
        prov = str(self.provider.currentData() or "custom")
        burl = values.get("base_url", "")
        # P8C-R3.1: resolve the scoped secret for the current (provider, base).
        # A dead `'read_api_key' in dir()` check (dir() is the LOCAL namespace,
        # so this was always False) made every Test Connection with an empty
        # input field fail with "当前模型缺少 API 密钥" even while the DPAPI
        # store / environment held a working key. Respect the three widget
        # states: REPLACE uses the typed value, CLEAR tests the post-clear
        # reality (store key ignored, environment still applies), UNCHANGED
        # resolves the stored secret.
        key_state = values.get("key_state", "unchanged")
        if values["key"]:
            key = values["key"]
        elif key_state == "clear":
            key = ""
        else:
            prov_key, _ = read_api_key(prov, burl)
            key = prov_key
        if not key and prov in {"bailian", "dashscope"}:
            key = resolve_api_key(self.stage)[0]
        endpoint = {
            **values,
            "api_key": key,
            "url": responses_url(values["base_url"]) if values.get("protocol") == "responses" else chat_completion_url(values["base_url"]),
        }
        if values.get("provider") == "anthropic":  # Claude: the Messages API (2026-10-18)
            endpoint.update(protocol="anthropic_messages", url=messages_url(values["base_url"]))
        try:
            validate_endpoint(endpoint, "当前模型")
        except RuntimeError as exc:
            self.status.setObjectName("statusWarn")
            self.status.setText(str(exc))
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        self.test_button.setEnabled(False)
        bind_text(self.status, '正在测试…')
        self._tester = ProviderConnectionTester(self._provider_settings(), self.stage, prompt_test=True)
        self._tester.finished_status.connect(self._endpoint_callback(self._tester, '_tester', self._connection_finished))
        self._tester.start()

    def _show_slow_connection_hint(self, tester) -> None:
        if tester is self._tester and tester is not None and tester.isRunning():
            elapsed = max(5, int(time.monotonic() - self._connection_started_at))
            bind_text(self.status, '模型响应较慢，仍在等待… {elapsed} 秒 · 可取消', elapsed=elapsed)

    def _invalidate_endpoint_tasks(self) -> None:
        self.last_connection_ok = None
        self._endpoint_epoch = getattr(self, '_endpoint_epoch', 0) + 1
        for name in ('_tester', '_login_worker', '_update_worker'):
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                # Keep the parentless QThread alive until its native run exits.
                pending = getattr(self, '_retired_endpoint_tasks', set())
                self._retired_endpoint_tasks = pending
                pending.add(worker)
                if hasattr(worker, 'finished'):
                    worker.finished.connect(lambda w=worker, owned=pending: owned.discard(w))
            setattr(self, name, None)
        if hasattr(self, 'test_button'):
            self.test_button.setEnabled(True)
            bind_text(self.test_button, '测试连接')
            self.detect_cli_button.setEnabled(True)
            self.logout_button.setEnabled(True)
            self.update_cli_button.setEnabled(True)

    def _endpoint_callback(self, worker, slot, callback):
        epoch = getattr(self, '_endpoint_epoch', 0)
        identity = self.values()
        from .ai_connection_record import fingerprint
        tested = fingerprint(worker.settings, self.stage) if hasattr(worker, 'settings') else None
        def deliver(*args):
            if (epoch == getattr(self, '_endpoint_epoch', 0)
                    and getattr(self, slot, None) is worker
                    and (fingerprint(self._provider_settings(), self.stage) == tested
                         if tested is not None else self.values() == identity)):
                callback(*args)
        return deliver

    def _connection_finished(self, ok: bool, message: str):
        self.last_connection_ok = bool(ok)
        # 2026-10-22: remembered across restarts; the AI-only features on the home page wait for it.
        try:
            from .ai_connection_record import remember
            tester = getattr(self, '_tester', None)
            tested = tester.settings if tester is not None else self._provider_settings()
            remember(tested, self.stage, ok)
        except Exception:  # noqa: BLE001 - a record that cannot be written only means "test again"
            pass
        self.connection_tested.emit(bool(ok))
        self.test_button.setEnabled(True)
        bind_text(self.test_button, '测试连接')
        if self.values()['transport'] != AITransport.OPENAI_COMPATIBLE.value:
            self._show_cli_diagnostics(dict(getattr(self._tester, 'diagnostics', {}) or {}), ok=ok, request_test=True)
        if ok:
            if str(self.service.currentData()) == "codex_cli":
                bind_text(self.login_button, '重新登录或切换账号')
            try:
                base = GLOBAL_PROVIDER_REGISTRY.settings()
                saved_service = get_active_service(base) if isinstance(base, dict) else "custom"
                if saved_service != str(self.values().get("service") or "custom"):
                    message = f"{message} · 尚未保存：点击保存后 AI 设计才会使用此 Provider"
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
        self.status.setObjectName("statusGood" if ok else "statusWarn")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
