"""AI subtitle design panel: provider selection, suggestion requests,
variant previews, and applying AI-designed styles for Subtitle Studio."""

from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import (QTimer, Qt)
from PySide6.QtGui import (QPixmap)
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout)
from .advanced_live_renderer import (composite_live_scene_layers, composition_pivot_for_snapshot, render_live_layers)
from .advanced_renderer import AdvancedRendererBackend
from .llm_config import (AI_SERVICE_SPECS, activate_ai_service, active_service_values, resolved_service_values, service_model_catalog, supports_model_discovery, update_active_profile)
from .provider_registry import GLOBAL_PROVIDER_REGISTRY
from .settings import save_runtime_settings
from .studio_ai import (
    AIDesignStage,
    AIDesignSuggestion,
    request_style_design,
    request_style_revision,
    request_web_theme_design,
    style_recipe_for_prompt,
)
from .studio_cards import AIDesignVariantCard
from .studio_commands import cue_by_id
from .studio_project import studio_data_root
from .studio_theme import apply_secondary_surface_theme
from .style_recipe import (StyleRecipe, VisualStyleRecipe, route_recipe)
from .visual_design_graph import (VisualDesignGraph, graph_from_style_recipe, normalize_motion_graph_to_cue)
from .visual_snapshot import build_visual_cue_snapshot

from .i18n import join_text, bind_text

from .i18n import tr


def provider_for_stage(settings, stage):
    """Resolve a provider client; tests patch this seam to inject fakes."""
    return GLOBAL_PROVIDER_REGISTRY.client(stage=stage, settings=settings)


def _revision_feedback_dialog(parent, index: int) -> tuple[str, bool]:
    """Lightweight one-round revision input; not a chat system."""
    dialog = QDialog(parent)
    bind_text(dialog, '微调设计 · 方案 {value0}', property='windowTitle', value0=chr(65 + index))
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)
    hint = QLabel(
        "告诉 AI 怎么改这一稿（只改你提到的部分）：\n"
        "例如：金属感再重一点 / 文字不要黄色 / 边框更复杂 / "
        "减少齿轮 / 入场再快一点 / 保留文字，只改背景"
    )
    hint.setWordWrap(True)
    editor = QPlainTextEdit()
    bind_text(editor, '输入修改要求…', property='placeholderText')
    editor.setMinimumHeight(96)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
    )
    bind_text(buttons.button(QDialogButtonBox.StandardButton.Ok), '生成修订版')
    bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(hint)
    layout.addWidget(editor)
    layout.addWidget(buttons)
    dialog.resize(440, 240)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return editor.toPlainText().strip(), accepted

class StudioAIFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _refresh_ai_design_target(self):
        label = getattr(self, 'ai_design_target_label', None)
        if label is None:
            return
        from .studio_design_target import design_cue
        cue = design_cue(self.project, self.selected_cue_id)
        if cue is None:
            bind_text(label, '当前设计对象：未选择字幕（视频片段不能生成字幕设计）')
        else:
            bind_text(label, '当前设计对象：{value0} · {value1:.3f}–{value2:.3f} 秒', value0=cue.text[:48], value1=cue.start_ms / 1000, value2=cue.end_ms / 1000)
            bind_text(label, '多选时为当前活动字幕；应用范围由下方选项决定。', property='toolTip')

    def _theme_drafts(self):
        value = getattr(self, '_theme_draft_coordinator', None)
        if value is None:
            from .studio_theme_draft import StudioThemeDraftController
            value = self._theme_draft_coordinator = StudioThemeDraftController(self)
        return value

    def _request_ai_suggestion(self) -> None:
        self._refresh_ai_design_target()
        # Cancellation must work even if selection changed during generation.
        if self._ai_request_active:
            self._launch_ai_suggestion()
            return
        pending = getattr(self, '_ai_preparing_request', None)
        if pending:
            self._ai_preparing_request = None
            self._ai_start_feedback(pending, 'cancelled', '已取消准备，可重新生成')
            return
        context = dict(request_id=uuid.uuid4().hex, cue_id=str(self.selected_cue_id or ''),
                       started=time.monotonic(), worker_started=False, cache_used=False)
        from .studio_design_target import DesignTarget
        target = DesignTarget.capture(self)
        self._ai_click_target = target
        if hasattr(self, 'ai_prompt'):
            self._commit_ai_design_provider_selection(persist=True)
            self._ai_click_options = dict(request_id=context['request_id'],
                prompt=self.ai_prompt.toPlainText(),
                scope=self.ai_effect_scope.currentData() if hasattr(self, 'ai_effect_scope') else 'fullscreen',
                wait=self.ai_wait_mode.currentData(),
                candidate_mode=self.ai_candidate_mode.currentData(),
                candidate_concurrency=self.ai_candidate_concurrency.currentData(),
                settings=copy.deepcopy(GLOBAL_PROVIDER_REGISTRY.settings()))
        self._ai_preparing_request = context
        self._ai_start_feedback(context, 'preparing', '正在准备设计…')
        project = self.project

        def prepare():
            if self._ai_preparing_request is not context:
                return
            try:
                if self.project is not project or project is None:
                    raise ValueError('请先打开字幕工程，再生成设计。')
                if not project.cues:
                    raise ValueError('工程中没有字幕。请先生成、导入或添加一条字幕。')
                cue = target.cue if target is not None else None
                if cue is None:
                    raise ValueError('请先在时间轴或字幕列表中选中一条字幕，再点击“生成字幕设计”。')
                if not cue.text.strip():
                    raise ValueError('所选字幕没有文字。请先输入字幕正文，再生成设计。')
                if not target.matches(self):
                    raise ValueError('设计对象已改变或删除，请确认目标后重新生成。')
                if self.selected_cue_id != cue.id:
                    raise ValueError('字幕选择已改变，请确认目标后重新生成。')
                self._launch_ai_suggestion(request_id=context['request_id'])
                self._ai_start_feedback(context, 'started', '')
            except Exception as exc:
                drafts = getattr(self, '_theme_draft_coordinator', None)
                if drafts is not None and drafts.current and drafts.current.request_id == context['request_id']:
                    drafts._failed(drafts.operation, str(exc), 'preparation_failed')
                self._ai_start_feedback(context, 'failed', str(exc))
            finally:
                if self._ai_preparing_request is context:
                    self._ai_preparing_request = None
        QTimer.singleShot(0, prepare)

    def _ai_start_feedback(self, context, status, message):
        context.update(status=status, message=message, worker_started=status == 'started',
                       elapsed_seconds=round(time.monotonic()-context['started'], 3))
        self._ai_last_start = context
        self._studio_trace('AI_DESIGN_START', **context)
        # Persist the identity before Provider/worker creation, including failures
        # which have no ThemeDraft yet. No prompt or credentials are recorded.
        try:
            root = studio_data_root()/'logs/theme-starts'
            root.mkdir(parents=True, exist_ok=True)
            (root/(context['request_id']+'.json')).write_text(json.dumps(context,ensure_ascii=False,indent=2), 'utf8')
        except OSError:
            pass
        if status == 'started':
            console = getattr(self, 'ai_stream_console', None)
            if console is not None:
                bind_text(console, '正在生成设计…\n请求：{value0}', property='placeholderText', value0=context['request_id'])
            return
        preparing = status == 'preparing'
        if not preparing:
            self._ai_request_active = False
            if self._ai_cancel_event is not None:
                self._ai_cancel_event.set()
            self._ai_cancel_event = None
            self._set_ai_input_sections_visible(True)
        self.ai_generate.setEnabled(True)
        (bind_text(self.ai_generate, '取消准备') if preparing else bind_text(self.ai_generate, '生成字幕设计'))
        self._show_ai_progress_bar(preparing)
        self.ai_suggestion_card.show()
        (bind_text(self.ai_suggestion_title, '正在准备设计') if preparing else bind_text(self.ai_suggestion_title, '设计尚未生成'))
        self.ai_confidence.setText(message)
        self.ai_preview.setPlainText(message+'\n请求：'+context['request_id'])
        self._show_studio_hint(message)
        self._scroll_ai_panel_into_view(self.ai_generate)

    def _launch_ai_suggestion(self, *, request_id=None) -> None:
        if self._ai_request_active:
            drafts = getattr(self, '_theme_draft_coordinator', None)
            if drafts is not None and drafts.phase in {'PROVIDER','RENDERING','EXPORTING'}:
                drafts.cancel()
                return
            if self._ai_cancel_event is not None:
                self._ai_cancel_event.set()
            self.ai_generate.setEnabled(False)
            bind_text(self.ai_generate, '取消中…')
            bind_text(self.ai_confidence, '正在取消 Provider 请求')
            self._studio_trace(
                "AI_DESIGN_CANCEL_REQUESTED",
                generation=self._ai_request_generation,
            )
            return
        options = getattr(self, '_ai_click_options', {})
        options = options if request_id and options.get('request_id') == request_id else {}
        if not options:
            self._commit_ai_design_provider_selection(persist=True)
        cue_id = self.selected_cue_id
        raw_user_prompt = options.get('prompt', self.ai_prompt.toPlainText())
        instruction = raw_user_prompt.strip() or "柔和清晰的对白字幕"
        scope = "fullscreen"
        combo = getattr(self, "ai_effect_scope", None)
        if combo is not None:
            scope = str(combo.currentData() or "subtitle")
        scope = str(options.get('scope', scope))
        if scope == "fullscreen":
            instruction += ("；【效果范围：动效丰富视频画面】场景元素可分布整个画面，"
            "入场出场可以做全屏级的大动效（全屏扫过/物件飞越/装置占满一侧），"
            "元素位置不局限在字幕附近")
        else:
            instruction += ("；【效果范围：特效字幕】所有场景元素集中在字幕附近的"
            "底部区域（画面下方约 1/4），画面左右与上方保持干净不遮挡视频")
        self._ai_last_instruction = instruction
        # A fresh generate replaces the triple; old per-slot revisions no
        # longer map to anything.
        self._ai_variant_revisions.clear()
        self._pending_web_theme = None
        wrap = getattr(self, "ai_web_theme_storyboard_wrap", None)
        if wrap is not None:
            wrap.setVisible(False)
        self._stop_storyboard_animation()
        refine_row = getattr(self, "ai_refine_row", None)
        if refine_row is not None:
            refine_row.setVisible(False)
        project = self.project
        self._ai_request_generation += 1
        generation = self._ai_request_generation
        cancel_event = threading.Event()
        self._ai_cancel_event = cancel_event
        self._ai_request_active = True
        self.ai_generate.setEnabled(True)
        bind_text(self.ai_generate, '取消生成')
        self.ai_empty_state.hide()
        self._show_ai_progress_bar(True)
        self._set_ai_input_sections_visible(False)
        self._scroll_ai_panel_into_view()
        # 2026-09-02（用户反馈）：不弹独立窗口——进度只保留 AI 面板内嵌
        # （进度条 + 输出流控制台）。独立窗仅在曾被打开过时复用显示。
        if getattr(self, "_ai_generation_window", None) is not None and self._ai_generation_window.isVisible():
            self._ai_generation_window.begin()
        if hasattr(self, "ai_suggestion_card"):
            self.ai_suggestion_card.show()
        bind_text(self.ai_suggestion_title, '正在生成视觉方案')
        bind_text(self.ai_confidence, '正在构建并校验三套视觉方案')
        self.ai_preview.setPlainText("正在生成设计草稿...")
        fallback_button = getattr(self, "ai_use_local_fallback", None)
        if fallback_button is not None:
            fallback_button.hide()

        def report_stage(stage: str) -> None:
            self.ai_stage_signal.emit(generation, str(stage))

        route_combo = getattr(self, "ai_route", None)
        # 十六轮：渲染路线选择器已从 UI 移除（唯一路线=网页主题）；combo
        # 缺失时缺省必须是 "web"——回落 "graph" 会走回旧原语图路线。
        route = str(route_combo.currentData() or "web") if route_combo is not None else "web"
        if route == "web":
            settings_snapshot = copy.deepcopy(options.get('settings', GLOBAL_PROVIDER_REGISTRY.settings()))
            settings_snapshot.setdefault('models',{})['ai_design_wait_mode'] = options.get('wait', self.ai_wait_mode.currentData())
            mode=options.get('candidate_mode','single')
            settings_snapshot['models'].update(ai_design_mode=mode,ai_design_candidate_count=1 if mode=='single' else 3,
                ai_design_concurrency=options.get('candidate_concurrency',2),
                ai_design_max_repair_calls=options.get('max_repairs',settings_snapshot['models'].get('ai_design_max_repair_calls',2)))
            selection = GLOBAL_PROVIDER_REGISTRY.selection(settings_snapshot, stage='polish')
            drafts = self._theme_drafts()
            if not selection.model:
                raise ValueError('当前 Provider 没有选择模型，请在 AI 设计面板选择模型后重试。')
            draft = drafts.begin(generation, cue_id, scope, selection.provider, selection.model, request_id=request_id)
            drafts.settings = copy.deepcopy(settings_snapshot)
            from .theme_generation_policy import ThemeGenerationLimits
            drafts.provider_budget = ThemeGenerationLimits.from_settings(settings_snapshot['models']).concepts
            provider_operation = drafts.operation
            target = getattr(self, '_ai_click_target', None)
            request_project = copy.deepcopy(drafts.request_project)
            render_root = drafts.root/'compiler'
            cancel_event = drafts.cancel_event
            self._ai_cancel_event = cancel_event
            bind_text(self.ai_confidence, '设计文字与框线 → 生成候选 → 实际动画预览')
            self.ai_preview.setPlainText("正在生成美术规格与视觉方向...")

            def web_work():
                try:
                    reference=self._capture_ai_vision_frame(generation,cancel_event)
                    from .theme_draft import validate_draft_frames
                    def validate(theme, remaining):
                        return validate_draft_frames(draft.with_theme(theme),render_root/uuid.uuid4().hex,
                            cancel_check=cancel_event.is_set,deadline_seconds=remaining,
                            progress=lambda value:drafts.stage.emit(provider_operation,value))
                    suggestion = request_web_theme_design(
                        request_project,
                        cue_id,
                        instruction,
                        settings_snapshot,
                        effect_scope=scope,request_id=draft.request_id,render_validator=validate,
                        concepts_only=True,candidate_cancel_check=lambda ident:ident in drafts.cancelled_candidates,
                        reference_frames=(reference,) if reference else (),
                        raw_user_prompt=raw_user_prompt,ledger_root=render_root.parent/'creative',
                        cancel_check=lambda: not drafts.provider_request_current(provider_operation,generation,cancel_event),
                        stage_callback=report_stage,
                        stage_event_callback=lambda event:drafts.compiler_event.emit(provider_operation,event),
                        on_stream_text=lambda chunk: self.ai_stream_line_signal.emit(
                            generation, str(chunk)
                        ),
                    )
                    if generation == self._ai_request_generation and not cancel_event.is_set():
                        self.ai_web_theme_signal.emit(generation, cue_id, suggestion)
                except Exception as exc:
                    if generation == self._ai_request_generation and not cancel_event.is_set():
                        if getattr(exc,'preview_theme',None):
                            drafts.recoverable_failure.emit(provider_operation,exc.preview_theme,str(exc),getattr(exc,'category','render_error'))
                        else:
                            drafts.failed.emit(provider_operation, str(exc), getattr(exc,'category','provider_error'))

            self._ai_worker = threading.Thread(target=web_work, daemon=True, name="studio-ai-web")
            self._ai_worker.start()
            return

        def work():
            # 旧原语图路线没有流式进度；给它一个总时长硬顶（两阶段 CLI 各
            # 最多几分钟，超时即取消并回退），避免"15 分钟无反馈"的卡死观感。
            graph_deadline = time.monotonic() + 480.0

            def graph_cancel() -> bool:
                if cancel_event.is_set() or self._close_requested:
                    return True
                if time.monotonic() > graph_deadline:
                    report_stage("STALL_TIMEOUT")
                    return True
                return False

            try:
                suggestion = request_style_design(
                    project,
                    cue_id,
                    instruction,
                    GLOBAL_PROVIDER_REGISTRY.settings(),
                    cancel_check=graph_cancel,
                    stage_callback=report_stage,
                    vision_frame_supplier=lambda: self._capture_ai_vision_frame(
                        generation, cancel_event
                    ),
                )
                if generation == self._ai_request_generation and not cancel_event.is_set():
                    self.ai_ready_signal.emit(suggestion)
            except Exception as exc:
                if generation == self._ai_request_generation:
                    self.ai_failed_signal.emit(str(exc))

        threading.Thread(target=work, daemon=True, name="studio-ai").start()

    def _refresh_ai_design_provider_summary(self) -> None:
        provider = getattr(self, "ai_provider", None)
        label = getattr(self, "ai_provider_capabilities", None)
        if provider is None or label is None:
            return
        spec = AI_SERVICE_SPECS.get(
            str(provider.currentData() or "custom"), AI_SERVICE_SPECS["custom"]
        )
        caps = set(spec.get("capabilities", ()))
        is_codex = str(provider.currentData())=="codex_cli"
        if is_codex:
            client = provider_for_stage(self.runtime_settings,"polish")
            manifest = client.capabilities()
            bind_text(label, ('原生 JSON Schema' if manifest.structured_output else 'CLI 能力待检测') + ' · ' + ('当前模型支持图片' if manifest.vision else '图片能力待模型目录确认 · 文字上下文'))
        else:
            bind_text(label, '服务能力声明（尚未实测）：{value0}', value0=join_text((tr('结构化输出'), tr('图片' if 'vision' in caps else '文字上下文'))))
        for name in ("ai_cli_login","ai_cli_logout"):
            button=getattr(self,name,None)
            if button is not None:button.setVisible(is_codex)
        try:
            selection = GLOBAL_PROVIDER_REGISTRY.selection(self.runtime_settings, stage="polish")
            configured, source = GLOBAL_PROVIDER_REGISTRY.credential(selection)
        except (OSError, RuntimeError, TypeError, ValueError):
            configured, source = False, "未配置"
        credential = getattr(self, "ai_provider_credential", None)
        if credential is not None:
            provider_label = str(spec.get("label") or provider.currentText() or "Provider")
            (bind_text(credential, '{value0} 凭据已配置（连接状态另行检测）', value0=tr(provider_label)) if configured else bind_text(credential, '{value0} 未配置', value0=tr(provider_label)))
            bind_text(credential, str(source or ''), property='toolTip')
        settings_button = getattr(self, "ai_provider_settings", None)
        if settings_button is not None:
            settings_button.setVisible(not configured)
        badge = getattr(self, "ai_provider_status", None)
        if badge is not None:
            badge.setVisible(bool(configured))
        health = getattr(self, "ai_provider_health", None)
        if health is not None:
            health.hide()

    def _open_ai_provider_settings(self) -> None:
        """Open the one Home provider editor, then rebind its live settings."""
        host = self.window()
        opener = getattr(host, "_open_ai_from_workshop", None)
        if callable(opener):
            opener()
        legacy = getattr(host, "legacy", None)
        live = getattr(legacy, "RUNTIME_SETTINGS", None)
        if isinstance(live, dict):
            self.runtime_settings = live
            GLOBAL_PROVIDER_REGISTRY.bind(live)
        self._reload_ai_provider_selection()

    def _reload_ai_provider_selection(self):
        live=getattr(getattr(self.window(),"legacy",None),"RUNTIME_SETTINGS",self.runtime_settings)
        if not isinstance(live,dict) or not hasattr(self,"ai_model"):return
        self.runtime_settings=live
        values=active_service_values(live,stage="polish")
        service=str(values.get("service") or "custom")
        self.ai_provider.blockSignals(True)
        self.ai_provider.setCurrentIndex(max(0,self.ai_provider.findData(service)))
        self.ai_provider.blockSignals(False)
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        self.ai_model.addItems(list(service_model_catalog(live,service)))
        self.ai_model.setCurrentText(str(values.get("model") or ""))
        self.ai_model.blockSignals(False)
        self._refresh_ai_design_provider_summary()
        self._start_ai_provider_probe(service)

    def _ai_operation_registry(self):
        from .request_operations import RequestOperations
        if not hasattr(self, '_ai_operations'):
            self._ai_operations = RequestOperations()
        return self._ai_operations

    def _ai_cli_account_action(self,action):
        if str(self.ai_provider.currentData())!="codex_cli":return
        old=self._ai_operation_registry().current.get('account')
        if old is not None and not old.done:
            old.cancel.set()
            if action == 'login':
                self._apply_ai_provider_status("CANCELLED","正在取消官方登录…")
                return
        self._ai_provider_probe_generation+=1
        generation=self._ai_provider_probe_generation
        operation=self._ai_operation_registry().begin('account',generation)
        event=operation.cancel
        self._ai_cli_login_running=True
        bind_text(self.ai_cli_login, '取消登录')
        self._apply_ai_provider_status("REQUESTING", "正在启动官方登录窗口…")
        client=provider_for_stage(GLOBAL_PROVIDER_REGISTRY.bind(self.runtime_settings),"polish")
        def work():
            try:
                if action=="logout":status=client.logout(cancel_check=event.is_set)
                else:status=client.login(user_initiated=True,cancel_check=event.is_set,on_progress=lambda message:
                    self.ai_provider_progress_signal.emit(generation,str(message)))
                state="SESSION READY" if status.authenticated else "AUTH REQUIRED"
                message=status.message
            except Exception as exc:
                state="CANCELLED" if event.is_set() else "ERROR"
                from .provider_diagnostics import redact_diagnostics
                message=redact_diagnostics(str(exc))
            self.ai_provider_probe_signal.emit(generation,state,message,{'request_id':operation.request_id,'models':()})
        threading.Thread(target=work,daemon=True,name="studio-codex-account").start()

    def _ai_design_provider_changed(self, _index: int = -1) -> None:
        provider = getattr(self, "ai_provider", None)
        model = getattr(self, "ai_model", None)
        if provider is None or model is None:
            return
        service_id = str(provider.currentData() or "custom")
        # The provider registry owns both the catalog and selected profile
        # model. Never carry the previous provider's model across a switch.
        values = resolved_service_values(self.runtime_settings, service_id)
        candidates = list(service_model_catalog(self.runtime_settings, service_id))
        if values.get("model") and str(values["model"]) not in candidates:
            candidates.insert(0, str(values["model"]))
        model.blockSignals(True)
        model.clear()
        for model_id in dict.fromkeys(item for item in candidates if item):
            model.addItem(model_id, model_id)
        model.setCurrentText(str(values.get("model") or (candidates[0] if candidates else "")))
        model.blockSignals(False)
        self._commit_ai_design_provider_selection(persist=True, provider_changed=True)
        self._refresh_ai_design_provider_summary()
        self._start_ai_provider_probe(service_id,refresh_models=True)

    def _ai_design_model_changed(self, _value: str = "") -> None:
        self._commit_ai_design_provider_selection(persist=True)
        cancel = getattr(self, "_ai_provider_probe_cancel", None)
        if cancel is not None: cancel.set()
        self._ai_provider_probe_cancel = None
        self._ai_provider_probe_generation += 1
        bind_text(self.ai_test_connection, '测试连接')
        self._refresh_ai_design_provider_summary()
        self._apply_ai_provider_status("UNKNOWN", "模型已切换；下次请求使用当前选择")

    def _start_ai_provider_probe(self, service_id: str, *, force=False, refresh_models=False) -> None:
        kind='models' if refresh_models else 'test' if force else 'detect'
        old=self._ai_operation_registry().current.get(kind)
        cancel=old.cancel if old is not None else None
        running=old is not None and not old.done and not cancel.is_set()
        if running:
            cancel.set()
            if force and service_id==getattr(self,"_ai_provider_probe_service",None):
                self._ai_provider_probe_generation+=1
                self._ai_provider_probe_cancel=None
                bind_text(self.ai_test_connection, '测试连接')
                self._apply_ai_provider_status("CANCELLED","检测已取消；保留当前模型选择")
                return
        self._ai_provider_probe_generation+=1
        generation=self._ai_provider_probe_generation
        self._ai_provider_probe_service=service_id
        settings=GLOBAL_PROVIDER_REGISTRY.bind(self.runtime_settings)
        client=provider_for_stage(settings,"polish")
        cached=getattr(client,"cached_health",lambda:None)()
        from .llm_config import discovered_service_models
        discovered,stamp=discovered_service_models(service_id,self.runtime_settings)
        self._merge_discovered_models(service_id,discovered)
        age=time.monotonic()-cached.checked_monotonic if cached else float('inf')
        ready=cached is not None and str(getattr(cached.state,"value",cached.state))=="READY"
        if ready:
            self._apply_ai_provider_status("SESSION READY",f"{cached.message} · 缓存 {int(age)} 秒前")
            if age<480 and not force and not refresh_models:return
        else:
            self._apply_ai_provider_status("REQUESTING","正在后台检测当前模型…")
        operation=self._ai_operation_registry().begin(kind,generation)
        event=operation.cancel;self._ai_provider_probe_cancel=event
        bind_text(self.ai_test_connection, '取消检测')
        def work():
            models=()
            def progress_signal(message):
                if event.is_set():return
                try:self.ai_provider_progress_signal.emit(generation,str(message))
                except RuntimeError:event.set()  # Page closed during the probe.
            try:
                if refresh_models:
                    progress_signal("正在刷新模型列表；会话状态保持独立")
                    models=client.discover_models(timeout=20,cancel_check=event.is_set,refresh=True)
                    state="SESSION READY" if ready else "AUTH REQUIRED" if cached and str(getattr(cached.state,"value",cached.state))=="AUTH_REQUIRED" else "UNKNOWN"
                    message=(str(cached.message)+" · " if cached else "")+f"已刷新 {len(models)} 个模型；当前选择保持不变"
                else:
                    status=client.validate(timeout=20,use_cache=not force,cancel_check=event.is_set,
                        on_progress=progress_signal)
                    models=status.models
                    state="SESSION READY" if status.authenticated else "AUTH REQUIRED" if status.available else "OFFLINE"
                    message=str(status.message)
                    timings=dict(getattr(client,"last_timings",{}) or {})
                    if not timings.get("cache_hit") and timings.get("readiness_request_seconds") is not None:
                        message+=f" · 模型响应 {timings['readiness_request_seconds']:.2f}s"
                if event.is_set():
                    state,message='CANCELLED','当前请求已取消'
            except Exception as exc:
                from .provider_diagnostics import redact_diagnostics
                state='CANCELLED' if event.is_set() else "SESSION READY" if refresh_models and ready else "ERROR"
                message='当前请求已取消' if event.is_set() else redact_diagnostics(str(exc))
            try:self.ai_provider_probe_signal.emit(generation,state,message,{'request_id':operation.request_id,'models':models})
            except RuntimeError:event.set()
        threading.Thread(target=work,daemon=True,name="studio-ai-provider-probe").start()

    def _ai_provider_progress(self,generation,message):
        operation=self._ai_operation_registry().by_generation.get(generation)
        if operation is not None and not operation.cancel.is_set() and generation==self._ai_provider_probe_generation:
            self.ai_provider_health.setText(str(message))
            self.ai_provider_health.show()

    def _ai_provider_probe_finished(self,generation,state,message,discovered=None):
        registry=self._ai_operation_registry()
        operation=registry.by_generation.get(generation)
        if operation is None or not isinstance(discovered,dict) or discovered.get('request_id')!=operation.request_id:return
        registry.finish(generation)
        discovered=discovered.get('models',())
        if operation.kind=='account' and registry.current.get('account') is operation:
            self._ai_cli_login_running=False
            if hasattr(self,'ai_cli_login'):(bind_text(self.ai_cli_login, '打开官方 Codex 登录') if state not in ('READY', 'SESSION READY') else bind_text(self.ai_cli_login, '重新登录或切换账号'))
        if generation!=self._ai_provider_probe_generation:return
        if operation.kind != 'account':
            self._ai_provider_probe_cancel=None
        self._refresh_ai_design_provider_summary()
        bind_text(self.ai_test_connection, '测试连接')
        self._apply_ai_provider_status(state,message)
        service=str(self.ai_provider.currentData() or "custom")
        self._merge_discovered_models(service,discovered)

    def _copy_ai_provider_diagnostics(self):
        from .provider_diagnostics import redact_diagnostics
        client=provider_for_stage(GLOBAL_PROVIDER_REGISTRY.bind(self.runtime_settings),"polish")
        payload=redact_diagnostics({"provider":str(self.ai_provider.currentData()),
            "model":self.ai_model.currentText(),"trace":client.invocation_trace(),
            "status":getattr(self,"_ai_provider_last_detail",self.ai_provider_health.text()),
            "network":__import__("twobyteasr.network_policy",fromlist=["snapshot"]).snapshot()})
        QApplication.clipboard().setText(json.dumps(payload,ensure_ascii=False,indent=2))

    def _merge_discovered_models(self, service_id: str, discovered: object) -> None:
        """Merge the provider's live /models listing into the model combo."""
        model = getattr(self, "ai_model", None)
        if model is None or not isinstance(discovered, (list, tuple)) or not discovered:
            return
        if str(getattr(self, "ai_provider", None).currentData() or "custom") != service_id:
            return
        current = str(model.currentText() or "")
        existing = [str(model.itemText(index)) for index in range(model.count())]
        merged = list(dict.fromkeys([
            item for item in (*existing, *(str(name) for name in discovered)) if item
        ]))
        if merged == existing:
            return
        model.blockSignals(True)
        model.clear()
        for model_id in merged:
            model.addItem(model_id, model_id)
        if not current:model.setCurrentIndex(-1)
        model.setCurrentText(current)
        model.blockSignals(False)

    def _apply_ai_provider_status(self, state: str, message: str = "") -> None:
        from .design.components import map_provider_ui_state

        mapped = map_provider_ui_state(state, message)
        badge = getattr(self, "ai_provider_status", None)
        if badge is not None and hasattr(badge, "set_state"):
            badge.set_state(mapped)
            bind_text(badge, {'SESSION READY': '● 会话就绪', 'READY': '● 已就绪', 'REQUESTING': '● 检测中', 'TIMEOUT': '● 连接超时', 'SCHEMA ERROR': '● 响应格式有误', 'QUALITY LOW': '● 方案质量待改进', 'FAILURE': '● 连接失败'}.get(mapped, f'● {mapped.title()}'))
        label = getattr(self, "ai_provider_health", None)
        if label is not None:
            import html
            label.setTextFormat(Qt.TextFormat.PlainText)
            from .provider_diagnostics import redact_diagnostics
            detail=redact_diagnostics(html.unescape(str(message or "")))
            self._ai_provider_last_detail=detail
            (bind_text(label, detail) if len(detail) <= 150 else bind_text(label, '{value0}…（见技术详情）', value0=detail[:145]))
            if hasattr(self,'ai_network_detail'):
                from .network_policy import snapshot
                self.ai_network_detail.setPlainText(detail+"\n"+json.dumps(snapshot(),ensure_ascii=False,indent=2))
            label.setVisible(bool(str(message or "").strip()))

    def _commit_ai_design_provider_selection(
        self, *, persist: bool, provider_changed: bool = False
    ) -> None:
        provider = getattr(self, "ai_provider", None)
        model = getattr(self, "ai_model", None)
        if provider is None or model is None:
            return
        # configure_runtime_llms 会把 legacy.RUNTIME_SETTINGS 重绑定为新 dict；
        # 永远采用活引用，防止把旧快照（可能还是 Google 端点）写回磁盘。
        legacy = getattr(self.window(), "legacy", None)
        live = getattr(legacy, "RUNTIME_SETTINGS", None)
        if isinstance(live, dict) and live is not self.runtime_settings:
            self.runtime_settings = live
        GLOBAL_PROVIDER_REGISTRY.bind(self.runtime_settings)
        service_id = str(provider.currentData() or "custom")
        settings = self.runtime_settings
        values = active_service_values(settings, stage="polish")
        if provider_changed and service_id in AI_SERVICE_SPECS and values.get("service") != service_id:
            values = activate_ai_service(settings, service_id, stage="polish")
        model_id = model.currentText().strip() or str(values.get("model") or "")
        update_active_profile(settings, stage="polish", model=model_id)
        if not persist:
            return
        try:
            validated, _path, _warnings = save_runtime_settings(settings)
            self.runtime_settings = validated
            GLOBAL_PROVIDER_REGISTRY.bind(validated)
            if legacy is not None:
                legacy.RUNTIME_SETTINGS = validated
        except (OSError, RuntimeError, ValueError) as exc:
            self._apply_ai_provider_status("ERROR", f"模型配置保存失败：{exc}")

    def _capture_ai_vision_frame(
        self,
        generation: int,
        cancel_event: threading.Event,
    ) -> Path | None:
        """Capture through mpv only after the provider declares vision support."""
        controller = getattr(self.video, "controller", None)
        if controller is None or not getattr(controller, "running", False):
            return None
        destination = (
            studio_data_root() / "ai-context" /
            f"visual-design-{generation}-{uuid.uuid4().hex[:8]}.jpg"
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            controller.screenshot_to_file(destination, mode="video")
        except (OSError, RuntimeError):
            return None
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if cancel_event.is_set() or self._close_requested:
                return None
            try:
                if destination.is_file() and destination.stat().st_size > 0:
                    return destination
            except OSError:
                return None
            time.sleep(0.02)
        return None

    def _ai_stage_changed(self, generation: int, stage: str) -> None:
        if generation != self._ai_request_generation:
            return
        drafts = getattr(self,'_theme_draft_coordinator',None)
        if drafts is not None and drafts.current and drafts.current.generation == generation:
            if drafts.phase != 'PROVIDER' or drafts.cancel_event.is_set(): return
            drafts.detail = stage
        labels = {
            AIDesignStage.PREPARING_CONTEXT.value: "正在准备字幕与字体上下文",
            AIDesignStage.CONNECTING_PROVIDER.value: "正在连接 Provider",
            AIDesignStage.GENERATING.value: "Provider 正在生成视觉方案",
            AIDesignStage.PARSING.value: "正在解析 Provider 返回结果",
            AIDesignStage.VALIDATING.value: "正在校验 A / B / C 三套方案",
            AIDesignStage.BUILDING_LIVE.value: "正在构建实时预览",
            AIDesignStage.RENDERING_FIDELITY.value: "正在渲染高保真预览",
            AIDesignStage.COMPLETE.value: "视觉方案已完成",
            AIDesignStage.FAILED.value: "Provider 请求失败",
        }
        self.ai_confidence.setText(labels.get(stage, stage))
        console = getattr(self, 'ai_stream_console', None)
        if console is not None:
            request_id = str(getattr(getattr(drafts, 'current', None), 'request_id', ''))
            bind_text(console, '{value0}\n请求：{value1}', property='placeholderText', value0=labels.get(stage, stage), value1=request_id)
        self._studio_trace(
            "AI_DESIGN_STAGE",
            generation=generation,
            stage=stage,
        )
        self._update_ai_progress_bar(stage)
        window = getattr(self, "_ai_generation_window", None)
        if window is not None and window.isVisible():
            window.update_stage(labels.get(stage, stage))
            window.update_progress(
                getattr(self, "ai_progress_bar", None).value()
                if getattr(self, "ai_progress_bar", None) is not None else 0
            )

    def _update_ai_progress_bar(self, stage: str) -> None:
        """Map pipeline stages / streaming deltas onto the progress bar.

        Users judge "is it still working" from the bar alone, so even
        unfamiliar internal stage names must move it visibly.
        """
        bar = getattr(self, "ai_progress_bar", None)
        if bar is None:
            return
        text = str(stage or "")
        if text == "CONNECTING_PROVIDER":
            bar.setValue(8)
        elif text == "PREPARING_CONTEXT":
            bar.setValue(4)
        elif text == "REQUESTING":
            bar.setValue(max(bar.value(), 15))
        elif text.startswith("模型思考中"):
            bar.setValue(max(bar.value(), 18))
        elif text.startswith("正在输出主题"):
            # 15% + 60% scaled by emitted characters (~18k chars typical).
            try:
                chars = int(text.split("（")[1].split(" 百字")[0]) * 100
            except (IndexError, ValueError):
                chars = 0
            bar.setValue(min(78, 15 + int(60 * min(1.0, chars / 18000))))
        elif text == "VALIDATING":
            bar.setValue(82)
        elif text == "PARSING":
            bar.setValue(80)
        elif text in {"BUILDING_LIVE", "RENDERING_FIDELITY"}:
            bar.setValue(90)
        elif text == "COMPLETE":
            bar.setValue(100)

    def _open_translation_dialog(self) -> None:
        """Open the AI subtitle translation dialog (bilingual workflow)."""
        from .studio_translation_dialog import SubtitleTranslationDialog

        dialog = SubtitleTranslationDialog(self, self.window() or self)
        dialog.translation_finished.connect(
            lambda ok, _results: self._set_bilingual_mode(True)
            if ok else None
        )
        dialog.exec()

    def _ai_progress_window(self):
        window = getattr(self, "_ai_generation_window", None)
        if window is None:
            from .studio_ai_progress_window import AIGenerationProgressWindow

            window = AIGenerationProgressWindow(self.window() or self)
            self._ai_generation_window = window
        return window

    def _set_ai_input_sections_visible(self, visible: bool) -> None:
        """生成期间隐藏"生成服务/视觉设计要求"，只留设计草稿区；
        取消或完成后恢复，避免长输出流把输入区挤出视野。"""
        for name in ("ai_provider_section", "ai_prompt_section"):
            section = getattr(self, name, None)
            if section is not None:
                section.setVisible(visible)

    def _scroll_ai_panel_into_view(self, target=None) -> None:
        """点击生成后把设计草稿卡滚到可见——不用手动下滑找进度。"""
        drawer = getattr(self, "context_drawer", None)
        if drawer is not None:
            try:
                drawer.setCurrentIndex(0)
            except Exception:
                pass
        target = target or getattr(self, "ai_stream_console", None) or getattr(
            self, "ai_suggestion_card", None
        )
        if target is None:
            return
        from PySide6.QtWidgets import QScrollArea

        parent = target.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(target)
                return
            parent = parent.parentWidget()
        # No scroll area ancestor: at least raise the card so stacked layouts
        # surface it.
        target.raise_()

    def _ai_stream_line(self, generation: int, chunk: str) -> None:
        """Append raw AI output to the in-panel code console (user feature:
        a CMD-style window above the progress bar, like ASR's built-in CMD)."""
        if generation != getattr(self, "_ai_request_generation", -1):
            return
        drafts = getattr(self,'_theme_draft_coordinator',None)
        if drafts is not None and drafts.current and drafts.current.generation == generation:
            if drafts.phase != 'PROVIDER' or drafts.cancel_event.is_set(): return
        window = getattr(self, "_ai_generation_window", None)
        if window is not None:
            window.append_tail(chunk)
        console = getattr(self, "ai_stream_console", None)
        if console is None:
            return
        console.setVisible(True)
        bar = getattr(console, "verticalScrollBar", lambda: None)()
        cursor = console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(str(chunk or ""))
        console.setTextCursor(cursor)
        if bar is not None:
            bar.setValue(bar.maximum())

    def _show_ai_progress_bar(self, visible: bool) -> None:
        bar = getattr(self, "ai_progress_bar", None)
        if bar is None:
            return
        bar.setVisible(visible)
        if visible:
            bar.setValue(0)
        console = getattr(self, "ai_stream_console", None)
        if console is not None and visible:
            console.clear()
            console.setVisible(True)

    def _finish_ai_progress_bar(self) -> None:
        bar = getattr(self, "ai_progress_bar", None)
        if bar is None or not bar.isVisible():
            return
        bar.setValue(100)

        generation = self._ai_request_generation
        def hide_later() -> None:
            if generation == self._ai_request_generation and not self._ai_request_active:
                bar.setVisible(False)

        from PySide6.QtCore import QTimer

        QTimer.singleShot(2500, hide_later)

    def _ai_web_theme_ready(self, generation: int, cue_id: str, suggestion) -> None:
        """Only the current immutable request may enter the render gate."""
        if generation != getattr(self, "_ai_request_generation", -1):
            return
        self._theme_drafts().receive(generation, cue_id, suggestion)
        self._ai_refine_rounds = 0

    # One full-frame LIVE page per immutable draft; the six validated stills
    # stay visible if animation fails. There is no silent batch-render fallback.
    _STORYBOARD_LOOP_SECONDS = 3.0
    _STORYBOARD_BAND_KEEP = 1.0

    def _start_web_theme_storyboard(self, theme: dict) -> None:
        from .theme_draft import canonical_theme
        drafts = self._theme_drafts()
        if not drafts.is_valid() or canonical_theme(theme) != drafts.current.theme_json:
            return
        self._stop_storyboard_animation()
        draft = drafts.current
        token = self._storyboard_playback_token
        self.ai_web_theme_storyboard_wrap.show()
        bind_text(self.ai_web_theme_demo_label, '正在加载六秒动画…')
        self._storyboard_frame_times = []
        self._storyboard_started = time.perf_counter()
        from .live_web_preview import LiveWebPreviewWorker
        bridge = self._ensure_storyboard_live_bridge()
        worker = LiveWebPreviewWorker(loop_seconds=6., width=960, height=540,
                                      name='web-live-storyboard')
        worker.frame_ready.connect(lambda data,cue,stage: bridge.frame_ready.emit(token,data,cue,stage))
        worker.failed.connect(lambda message: bridge.failed.emit(token,message))
        self._storyboard_live_worker = worker
        self._storyboard_draft_id = draft.request_id
        try:
            worker.configure(theme=draft.theme, text=draft.text, speaker=draft.speaker, duration_seconds=6.)
            worker.start()
        except Exception as exc:
            self._on_storyboard_live_failed(token,str(exc))
        def first_frame_deadline():
            if token==getattr(self,'_storyboard_playback_token',None) and not self._storyboard_frame_times:
                self._on_storyboard_live_failed(token,'动画页六秒内未返回首帧')
        QTimer.singleShot(6000,first_frame_deadline)

    def _ensure_storyboard_live_bridge(self):
        bridge = getattr(self,'_storyboard_live_bridge',None)
        if bridge is None:
            from PySide6.QtCore import QObject, Signal
            class Bridge(QObject):
                frame_ready = Signal(int,object,float,float)
                failed = Signal(int,str)
            bridge = Bridge(self)
            bridge.frame_ready.connect(self._on_storyboard_live_frame)
            bridge.failed.connect(self._on_storyboard_live_failed)
            self._storyboard_live_bridge = bridge
        return bridge

    def _on_storyboard_live_failed(self, token, message):
        if token != getattr(self,'_storyboard_playback_token',None): return
        self._stop_storyboard_animation()
        bind_text(self.ai_web_theme_demo_label, '动画预览失败：{value0}\n六帧保留，可重试预览', value0=str(message))
        drafts = self._theme_drafts()
        drafts.animation_error = str(message)
        drafts.detail = '六帧通过；动画预览失败，可重试预览'
        drafts._tick()
        drafts._save_state()

    def _on_storyboard_live_frame(self, token, data, cue_ms, stage_ms):
        if token != getattr(self,'_storyboard_playback_token',None): return
        drafts = self._theme_drafts()
        if not drafts.current or drafts.current.request_id != self._storyboard_draft_id: return
        from PySide6.QtGui import QImage
        image = QImage.fromData(data)
        if image.isNull(): return
        now = time.perf_counter()
        self._storyboard_frame_times.append(now)
        self._storyboard_frame_times = self._storyboard_frame_times[-600:]
        demo = self.ai_web_theme_demo_label
        demo.setPixmap(QPixmap.fromImage(image).scaled(demo.size(),Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
        drafts.animation_error = ''
        count = len(self._storyboard_frame_times)
        if count > 2 and count % 30 == 0:
            spans = sorted((b-a)*1000 for a,b in zip(self._storyboard_frame_times,self._storyboard_frame_times[1:]))
            fps = (count-1)/(now-self._storyboard_frame_times[0])
            drafts.animation_metrics = dict(fps=round(fps,2),p95_ms=spans[int((len(spans)-1)*.95)],
                first_frame_ms=(self._storyboard_frame_times[0]-self._storyboard_started)*1000)
            drafts._tick()

    def _stop_storyboard_animation(self):
        self._storyboard_playback_token = int(getattr(self,'_storyboard_playback_token',0))+1
        timer = getattr(self,'_storyboard_timer',None)
        if timer is not None: timer.stop()
        live = getattr(self,'_storyboard_live_worker',None)
        if live is not None: live.stop()
        self._storyboard_live_worker = None
        self._storyboard_frames = {'demo':[]}
        self._storyboard_cursor = {'demo':0}

    def _pending_web_cue_text(self) -> str:
        pending = getattr(self, "_pending_web_theme", None)
        cue_id = str(getattr(pending, "cue_id", "") or self.selected_cue_id or "")
        try:
            return cue_by_id(self.project, cue_id).text
        except Exception:
            return "这是字幕特效的动画演示"

    def _open_web_theme_workshop(self, cue_id: str | None = None) -> None:
        """AI 字幕工坊：对话式精修当前/指定 cue 的特效字幕主题（十八轮）。

        与样式面板参数式「文字工具」互补：入口=视频画布双击 / 特效字幕调整卡 /
        AI 面板按钮。目标 cue 优先级：显式 cue_id > 播头所在 cue > 选中 cue。
        """
        project = self.project
        if project is None:
            return
        cue = None
        target_id = str(cue_id or "")
        if target_id and getattr(self, "_cue_lookup", None):
            cue = self._cue_lookup.get(target_id)
        if cue is None:
            resolver = getattr(self, "_renderer_cue_at_playhead", None)
            try:
                cue = resolver() if callable(resolver) else None
            except Exception:
                cue = None
        if cue is None and getattr(self, "_cue_lookup", None):
            cue = self._cue_lookup.get(str(self.selected_cue_id or ""))
        if cue is None:
            self._show_studio_hint(tr('没有可编辑的字幕'))
            return
        theme = (project.style_recipes.get(cue.style_id, {}) or {}).get("webTheme")
        if not isinstance(theme, Mapping) or not theme:
            self._show_studio_hint(tr('当前字幕不是 AI 特效字幕——先在 AI 面板生成或从特效字幕库套用'))
            return
        speaker_name = ""
        for speaker in project.speakers or []:
            if getattr(speaker, "id", "") == getattr(cue, "speaker_id", ""):
                speaker_name = str(getattr(speaker, "name", "") or "")
                break
        from .studio_web_theme_workshop import WebThemeWorkshopDialog

        self._web_theme_workshop = WebThemeWorkshopDialog(
            self,
            cue_id=cue.id,
            theme=dict(theme),
            cue_text=cue.text,
            speaker_name=speaker_name,
            parent=self,
        )
        self._web_theme_workshop.show()

    def _current_web_theme_recipe(self) -> dict | None:
        """webTheme recipe dict for the currently selected cue, if any."""
        cue = self._cue_lookup.get(str(self.selected_cue_id or "")) if getattr(self, "_cue_lookup", None) else None
        if cue is None:
            return None
        payload = self.project.style_recipes.get(cue.style_id, {})
        theme = payload.get("webTheme") if isinstance(payload, Mapping) else None
        return dict(theme) if isinstance(theme, Mapping) and theme else None

    def _update_web_adjust_visibility(self) -> None:
        """样式面板「特效字幕调整」卡：仅当前 cue 是 AI 特效字幕时显示。

        二十七轮：特效字幕模式下**反向隐藏全部原生参数分区**（预设/文字/
        外观/动效/应用范围/位置/当前字幕）——这些控件对 web cue 无效
        （外观由主题驱动），旧版同屏堆叠让用户"第一眼不知道怎么操作"。
        恢复为普通字幕后（_clear_advanced_style）随选择刷新自动回来。
        """
        block = getattr(self, "web_adjust_host", None)
        if block is None:
            return
        theme = self._current_web_theme_recipe()
        block.setVisible(theme is not None)
        for host in getattr(self, "style_native_hosts", None) or []:
            try:
                host.setVisible(theme is None)
            except RuntimeError:
                continue  # 已销毁的 widget（测试收尾竞争）
        identity = getattr(self, "web_adjust_identity", None)
        if identity is not None:
            if theme is None:
                bind_text(identity, '当前特效：—')
            else:
                name = str(theme.get("name") or "").strip() or "未命名主题"
                notes = str(theme.get("notes") or "").strip()
                # 作用对象行：agy 复审指出缺"改的是哪条字幕"的安全感。
                target = ""
                selector = getattr(getattr(self, "cue_controller", None), "selected_cue_ids", None)
                ids = list(selector() if callable(selector) else (selector or []))
                lookup = getattr(self, "_cue_lookup", None) or {}
                cue = lookup.get(ids[0]) if len(ids) == 1 else None
                if cue is not None:
                    try:
                        ordinal = list(getattr(self, "project").cues).index(cue) + 1
                    except (ValueError, AttributeError):
                        ordinal = 0
                    if ordinal:
                        start = int(cue.start_ms) / 1000.0
                        target = (
                            f"\n作用对象：第 {ordinal} 句"
                            f"（{int(start // 60):02d}:{start % 60:04.1f} 起）"
                        )
                bind_text(identity, '当前特效：{value0}{value1}{value2}', value0=name, value1=f'\n{notes}' if notes else '', value2=target)
        if theme is None:
            return
        # 从主题的 appearance/镜像同步默认字号与颜色（仅展示初值， guarded）。
        if getattr(self, "_web_adjust_syncing", False):
            return
        self._web_adjust_syncing = True
        try:
            size = getattr(self, "web_adjust_size", None)
            if size is not None:
                from .style_recipe import StyleRecipe

                try:
                    recipe = StyleRecipe.from_dict(
                        self.project.style_recipes.get(
                            self._cue_lookup.get(str(self.selected_cue_id or "")).style_id, {}
                        )
                    )
                    size.setValue(int(float(recipe.typography.get("fontSize", 58) or 58)))
                except Exception:
                    size.setValue(58)
            color_button = getattr(self, "web_adjust_color", None)
            if color_button is not None:
                palette = theme.get("palette") or {}
                self._web_adjust_color_value = str(palette.get("text") or "#FFFFFF")
                bind_text(color_button, '文字颜色 {value0}', value0=self._web_adjust_color_value)
            self._assemble_web_adjust_opinion()
        finally:
            self._web_adjust_syncing = False

    def _assemble_web_adjust_opinion(self) -> str:
        """把字体/字号/颜色选择汇总成一句发给 AI 的修改意见。"""
        parts: list[str] = []
        font = getattr(self, "web_adjust_font", None)
        if font is not None:
            family = str(font.currentText() or "").strip()
            if family:
                parts.append(f"字幕字体改成 {family}")
        size = getattr(self, "web_adjust_size", None)
        if size is not None:
            parts.append(f"字号改成 {int(size.value())}")
        color = str(getattr(self, "_web_adjust_color_value", "") or "")
        if color:
            parts.append(f"文字颜色改成 {color}")
        extra = getattr(self, "web_adjust_extra", None)
        extra_text = str(extra.text() or "").strip() if extra is not None else ""
        if extra_text:
            parts.append(extra_text)
        opinion = "；".join(parts)
        label = getattr(self, "web_adjust_opinion", None)
        if label is not None:
            (bind_text(label, '将请求 AI：{value0}', value0=opinion) if opinion else bind_text(label, '输入修改要求发送，或展开快速调整选择字体/字号/颜色'))
        return opinion

    def _web_adjust_target_cue_ids(self) -> list[str]:
        """Resolve the web-adjust scope to cue ids that carry a web theme."""
        scope_combo = getattr(self, "web_adjust_scope", None)
        scope = str(scope_combo.currentData() or "current") if scope_combo is not None else "current"
        project = self.project
        if project is None:
            return []
        selected_id = str(self.selected_cue_id or "")
        current = self._cue_lookup.get(selected_id) if getattr(self, "_cue_lookup", None) else None
        if scope == "all":
            candidates = list(project.cues)
        elif scope == "speaker" and current is not None:
            candidates = [cue for cue in project.cues if cue.speaker_id == current.speaker_id]
        else:
            candidates = [current] if current is not None else []
        return [
            cue.id for cue in candidates
            if isinstance(
                (project.style_recipes.get(cue.style_id, {}) or {}).get("webTheme"), Mapping
            )
        ]

    def _send_web_adjust_request(self) -> None:
        """把「特效字幕调整」的意见发给 AI 批量修改范围内的特效字幕。"""
        theme = self._current_web_theme_recipe()
        if theme is None:
            self._show_studio_hint(tr('当前字幕不是 AI 特效字幕'))
            return
        if getattr(self, "_ai_refine_active", False):
            return
        opinion = self._assemble_web_adjust_opinion()
        if not opinion:
            self._show_studio_hint(tr('请先选择字体/字号/颜色，或在补充要求里输入修改意见'))
            return
        targets = self._web_adjust_target_cue_ids()
        if not targets:
            self._show_studio_hint(tr('所选范围内没有 AI 特效字幕'))
            return
        request = opinion
        if len(targets) > 1:
            request += (
                f"（该主题同时用于 {len(targets)} 条字幕，请保持整体风格统一）"
            )
        self._theme_drafts().repair(request,theme=theme,cue_id=self.selected_cue_id,targets=targets)

    def _apply_web_theme_to_scope(self) -> None:
        """把当前特效字幕的主题套用到所选范围的全部字幕。"""
        theme = self._current_web_theme_recipe()
        if theme is None:
            self._show_studio_hint(tr('当前字幕不是 AI 特效字幕'))
            return
        scope_combo = getattr(self, "web_adjust_scope", None)
        scope = str(scope_combo.currentData() or "all") if scope_combo is not None else "all"
        project = self.project
        selected_id = str(self.selected_cue_id or "")
        current = self._cue_lookup.get(selected_id) if getattr(self, "_cue_lookup", None) else None
        if scope == "all" or current is None:
            targets = [cue.id for cue in project.cues]
        elif scope == "speaker":
            targets = [cue.id for cue in project.cues if cue.speaker_id == current.speaker_id]
        else:
            targets = [selected_id] if selected_id else []
        apply_web = getattr(self, "_apply_web_theme", None)
        try:
            applied = sum(
                1 for cue_id in targets
                if callable(apply_web) and apply_web(cue_id, copy.deepcopy(dict(theme)))
            )
        except Exception as exc:
            self._show_studio_hint(tr('范围应用未完成；已应用字幕保留，可重试：{value0}', value0=str(exc)))
            return
        # 二十四轮：套用后立即排队条带预热——被套 cue 先后有帧，不再出现
        # "应用到其它字幕后字幕直接消失"（原生被压制而条带/live 还没轮到）。
        if applied:
            warm = getattr(self, "_queue_web_strip_warm", None)
            if callable(warm):
                warm(targets)
        self._show_studio_hint((tr('已把特效主题套用到 {value0} 条字幕', value0=applied) if applied else tr('没有可套用的字幕')))

    def _ai_refine_ready(self, generation, payload):
        if generation != self._ai_request_generation: return
        if isinstance(payload,Exception) or payload.source != 'refined': return
        self._theme_drafts().adopt(payload.theme,self.selected_cue_id,label='校验修改主题')

    def _web_adjust_ready(self, generation, payload, target_ids):
        if generation != self._ai_request_generation: return
        if isinstance(payload,Exception) or payload.source != 'refined': return
        drafts=self._theme_drafts()
        drafts.adopt(payload.theme,self.selected_cue_id,label='校验修改主题')
        drafts.apply_targets=list(target_ids)

    def _export_ai_theme_archive(self) -> None:
        """把当前草稿主题导出为独立档案（HTML 动画演示 + JSON）。"""
        pending = getattr(self, "_pending_web_theme", None)
        if pending is None:
            self._show_studio_hint(tr('请先生成或导入一个网页主题'))
            return
        drafts = self._theme_drafts()
        if not drafts.allow_pending():
            self._show_studio_hint(tr('当前草稿尚未通过渲染校验，不能导出'))
            return
        from PySide6.QtWidgets import QFileDialog

        dest = QFileDialog.getExistingDirectory(
            self, tr('选择档案保存位置'), str(Path.home() / "Desktop"),
        )
        if not dest:
            return
        drafts.export(dest)

    def _import_ai_theme_archive(self) -> None:
        """从 .2byte-theme 档案载入主题到设计草稿。"""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, tr('选择字幕特效档案'),
            str(Path.home() / "Desktop"),
            "字幕特效档案 (theme.html theme.json *.2byte-theme.html *.json);;所有文件 (*)",
        )
        if not path:
            return
        from .web_theme import import_theme_archive

        try:
            theme = import_theme_archive(path)
        except Exception as exc:
            self._show_studio_hint(tr('档案导入失败：{value0}', value0=exc))
            return
        cue_id = str(self.selected_cue_id or "")
        if cue_id: self._theme_drafts().adopt(theme,cue_id,label='校验导入档案')

    def _ai_ready(self, suggestion: AIDesignSuggestion) -> None:
        self._ai_request_active = False
        self._ai_cancel_event = None
        self._finish_ai_progress_bar()
        self.ai_generate.setEnabled(True)
        (bind_text(self.ai_generate, '重新生成') if suggestion.provider_succeeded else bind_text(self.ai_generate, '重试 Provider'))
        fallback_button = getattr(self, "ai_use_local_fallback", None)
        if fallback_button is not None:
            fallback_button.setVisible(not suggestion.provider_succeeded)
        if hasattr(self, "ai_suggestion_card"):
            self.ai_suggestion_card.show()
        while self.ai_variant_row.count():
            item = self.ai_variant_row.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self.ai_variant_cards = []
        self._ai_variant_preview_labels = []
        self._ai_variant_preview_paths = []
        self._ai_variant_preview_done.clear()
        variants = list(suggestion.variants) or []
        if not variants:
            try:
                from .studio_ai import visual_design_variants
                variants = visual_design_variants("", VisualStyleRecipe.from_style_recipe(suggestion.recipe))
            except Exception:
                variants = []
        variants = self._normalize_ai_variants_for_cue(
            variants, suggestion.cue_id
        )
        if variants:
            suggestion = replace(
                suggestion,
                recipe=variants[0].to_style_recipe(),
                variants=tuple(variants),
            )
        self._pending_suggestion = suggestion
        self._ai_history = ([suggestion] + self._ai_history)[:8]
        directions = list(suggestion.art_directions)
        quality_scores = list(suggestion.quality_scores)
        for index, visual in enumerate(variants):
            direction = directions[index] if index < len(directions) else None
            quality = quality_scores[index] if index < len(quality_scores) else None
            recipe_for_motion = visual.to_style_recipe()
            graph_for_motion = recipe_for_motion.visual_graph
            has_motion = bool(
                isinstance(graph_for_motion, Mapping)
                and isinstance(graph_for_motion.get("motionGraph"), Mapping)
                and graph_for_motion["motionGraph"].get("tracks")
            )
            card = AIDesignVariantCard()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 7, 8, 7)
            card_layout.setSpacing(5)
            concept_name = (
                direction.concept_name if direction is not None else visual.name
            )
            title = bind_text(QLabel(), '方案 {value0} · {concept_name}', value0=chr(65 + index), concept_name=concept_name)
            title.setObjectName("cardMeta")
            title.setWordWrap(True)
            card_layout.addWidget(title)
            if direction is not None:
                # One line of intent + feature tags. The big preview carries
                # the design; long prose duplicated what the eye already sees.
                summary = QLabel(self._ai_direction_card_summary(direction, has_motion))
                summary.setObjectName("contextMeta")
                summary.setWordWrap(False)
                (bind_text(summary, '质量校验通过', property='toolTip') if quality is not None and quality.accepted else bind_text(summary, '设计方向', property='toolTip'))
                card_layout.addWidget(summary)
            tags = QLabel(self._ai_variant_tags(visual, direction))
            tags.setObjectName("aiVariantTags")
            tags.setWordWrap(False)
            tags.setCursor(Qt.CursorShape.WhatsThisCursor)
            tags.setStyleSheet(
                "color:#cfe3b8;background:#2c342c;border-radius:8px;"
                "padding:2px 8px;font-size:11px;letter-spacing:1px;"
            )
            card_layout.addWidget(tags)
            rendered = QLabel("正在生成与成片一致的预览…")
            rendered.setObjectName("aiVariantRendererPreview")
            rendered.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rendered.setMinimumHeight(240)
            rendered.setMaximumHeight(320)
            rendered.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            rendered.setWordWrap(True)
            rendered.setStyleSheet("background:#303633;color:#eef3ea;border-radius:6px;")
            card_layout.addWidget(rendered, 1)
            actions = QHBoxLayout()
            play_motion = QPushButton("播放")
            apply = QPushButton("应用")
            refine = QPushButton("微调")
            save = QPushButton("保存")
            restore = QPushButton("恢复上一版")
            play_motion.setObjectName("studioButton")
            apply.setObjectName("studioPrimary")
            refine.setObjectName("studioButton")
            save.setObjectName("studioButton")
            restore.setObjectName("studioButton")
            restore.setVisible(bool(self._ai_variant_revisions.get(index)))
            # Selecting a card is a click on the card itself; there is no
            # separate 选择 action. Apply/Save act on this card's variant.
            card.clicked.connect(
                lambda item=visual: self._select_ai_variant(item, suggestion)
            )
            play_motion.clicked.connect(
                lambda _checked=False, row=index, item=visual: self._play_ai_variant_motion(row, item)
            )
            play_motion.setEnabled(has_motion)
            if not has_motion:
                bind_text(play_motion, '无动效')
            apply.clicked.connect(
                lambda _checked=False, item=visual: self._apply_ai_variant(item, suggestion)
            )
            refine.clicked.connect(
                lambda _checked=False, row=index, item=visual: self._request_ai_revision(
                    row, item, suggestion,
                )
            )
            save.clicked.connect(
                lambda _checked=False, item=visual: self._save_ai_variant(item, suggestion)
            )
            restore.clicked.connect(
                lambda _checked=False, row=index: self._restore_ai_variant_revision(row)
            )
            for button in (play_motion, apply, refine, save, restore):
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                actions.addWidget(button)
            actions.addStretch(1)
            card_layout.addLayout(actions)
            self.ai_variant_row.addWidget(card)
            self.ai_variant_cards.append(card)
            self._ai_variant_preview_labels.append(rendered)
            self._ai_variant_preview_paths.append("")
        self.ai_variant_row.addStretch(1)
        if variants:
            self._select_ai_variant(variants[0], suggestion)
            self._ai_stage_changed(
                self._ai_request_generation,
                AIDesignStage.RENDERING_FIDELITY.value,
            )
            self._start_ai_variant_previews(variants)
        self.ai_empty_state.hide()
        recipe = suggestion.recipe
        route = route_recipe(recipe)
        (bind_text(self.ai_suggestion_title, recipe.name) if suggestion.provider_succeeded else bind_text(self.ai_suggestion_title, '{value0} · 可使用本地备选', value0=self._ai_failure_label(suggestion)))
        if not variants:
            self._ai_stage_changed(
                self._ai_request_generation, AIDesignStage.COMPLETE.value
            )
        direction = directions[0] if directions else None
        if direction is not None:
            bind_text(self.ai_preview, tr('{value0}\n{value1}\n\n{value2} · {value3}\n构图：{value4}\n配色：{value5}\n\n动效：\n{value6} → {value7} → {value8}', value0=direction.concept_name, value1=direction.intent, value2=direction.visual_language, value3=direction.hierarchy, value4=direction.composition, value5=direction.color_strategy, value6=direction.entrance_feel, value7=direction.hold_feel, value8=direction.exit_feel), property='plainText')
        else:
            bind_text(self.ai_preview, tr('{value0}\n{value1}\n\n动效：{value2}', value0=recipe.name, value1=suggestion.design_intent or suggestion.rationale, value2=suggestion.motion_reason or '稳定可读'), property='plainText')

    def _request_ai_revision(
        self, index: int, visual: VisualStyleRecipe, suggestion: AIDesignSuggestion,
    ) -> None:
        """“微调设计”: one-round PATCH dialog on a single approved variant."""
        if not self.project:
            return
        if self._ai_revision_active:
            bind_text(self.ai_confidence, '上一轮微调仍在进行')
            return
        feedback, accepted = _revision_feedback_dialog(self, index)
        feedback = str(feedback or "").strip()
        if not accepted or not feedback:
            return
        directions = list(suggestion.art_directions)
        direction = directions[index] if index < len(directions) else None
        previous_graph = (
            visual.to_style_recipe().visual_graph
            if isinstance(visual.to_style_recipe().visual_graph, Mapping) else None
        )
        if previous_graph is None:
            bind_text(self.ai_confidence, '该方案没有 VisualDesignGraph，无法微调')
            return
        self._ai_revision_active = True
        self._ai_revision_generation += 1
        generation = self._ai_revision_generation
        bind_text(self.ai_confidence, '正在微调方案 {value0} …', value0=chr(65 + index))
        project = self.project
        base_instruction = str(getattr(self, "_ai_last_instruction", "") or "")
        settings = GLOBAL_PROVIDER_REGISTRY.settings()
        cancel_event = threading.Event()
        self._ai_revision_cancel = cancel_event

        def work() -> None:
            try:
                recipe, revised_direction, notes = request_style_revision(
                    project,
                    suggestion.cue_id,
                    base_instruction,
                    feedback,
                    direction,
                    previous_graph,
                    settings,
                    cancel_check=lambda: cancel_event.is_set() or self._close_requested,
                )
                if generation == self._ai_revision_generation and not cancel_event.is_set():
                    self.ai_revision_signal.emit(generation, index, recipe, revised_direction, notes)
            except Exception as exc:  # noqa: BLE001 - surfaced through the signal
                if generation == self._ai_revision_generation:
                    self.ai_revision_failed_signal.emit(generation, str(exc)[:300])
            finally:
                if generation == self._ai_revision_generation:
                    self._ai_revision_active = False

        threading.Thread(target=work, daemon=True, name="studio-ai-revision").start()

    def _ai_revision_ready(
        self,
        generation: int,
        index: int,
        recipe: VisualStyleRecipe,
        direction,
        notes: str,
    ) -> None:
        if generation != self._ai_revision_generation:
            return
        self._ai_revision_active = False
        self._ai_revision_cancel = None
        suggestion = self._pending_suggestion
        if suggestion is None or index >= len(suggestion.variants):
            return
        # Keep the previous version for 恢复上一版; the stack lives per slot.
        self._ai_variant_revisions.setdefault(index, []).append(
            suggestion.variants[index],
        )
        if len(self._ai_variant_revisions[index]) > 6:
            self._ai_variant_revisions[index].pop(0)
        directions = list(suggestion.art_directions)
        if index < len(directions):
            directions[index] = direction
        variants = list(suggestion.variants)
        variants[index] = recipe
        updated = replace(
            suggestion,
            recipe=variants[0].to_style_recipe(),
            variants=tuple(variants),
            art_directions=tuple(directions),
        )
        self._pending_suggestion = updated
        self._ai_history = ([updated] + self._ai_history)[:8]
        self._ai_ready(updated)
        suffix = f"（{notes}）" if notes else ""
        bind_text(self.ai_confidence, '方案 {value0} 已更新为 Version {value1}{suffix}', value0=chr(65 + index), value1=len(self._ai_variant_revisions[index]) + 1, suffix=suffix)

    def _ai_revision_failed(self, generation: int, message: str) -> None:
        if generation != self._ai_revision_generation:
            return
        self._ai_revision_active = False
        self._ai_revision_cancel = None
        bind_text(self.ai_confidence, '微调失败：{message}', message=message)

    def _restore_ai_variant_revision(self, index: int) -> None:
        stack = self._ai_variant_revisions.get(index)
        suggestion = self._pending_suggestion
        if not stack or suggestion is None or index >= len(suggestion.variants):
            return
        previous = stack.pop()
        variants = list(suggestion.variants)
        variants[index] = previous
        updated = replace(
            suggestion,
            recipe=variants[0].to_style_recipe(),
            variants=tuple(variants),
        )
        self._pending_suggestion = updated
        self._ai_ready(updated)
        bind_text(self.ai_confidence, '方案 {value0} 已恢复上一版', value0=chr(65 + index))

    @staticmethod
    def _ai_direction_card_summary(direction, has_motion: bool) -> str:
        def concise(value: object, limit: int = 34) -> str:
            text = str(value or "").strip().split(";", 1)[0].split("。", 1)[0]
            return text if len(text) <= limit else text[: limit - 1] + "…"

        return concise(direction.visual_language, 46) or (
            "动效设计" if has_motion else "静态设计"
        )

    @staticmethod
    def _ai_variant_tags(visual, direction) -> str:
        """Short feature tags: STEAMPUNK / METALLIC / GEARS / MULTI-STROKE…"""
        tags: list[str] = []
        family = str(getattr(direction, "primary_family", "") or "")
        family_tags = {
            "INDUSTRIAL_BRASS_HUD": "STEAMPUNK",
            "VICTORIAN_MECHANICAL": "STEAMPUNK",
            "STEAM_GAUGE_TYPO": "STEAMPUNK",
            "CYBER_HUD": "CYBER",
            "CRT_GLITCH": "CRT",
            "SIGNAL_LOSS": "CRT",
            "AMERICAN_COMIC_BURST": "COMIC",
            "MANGA_IMPACT": "MANGA",
            "HALFTONE_SLAM": "MANGA",
            "CRITICAL_HIT": "GAMING",
            "STREAMER_EMPHASIS": "GAMING",
            "ACHIEVEMENT_POP": "GAMING",
        }
        if family in family_tags:
            tags.append(family_tags[family])
        recipe = visual.to_style_recipe()
        graph_payload = recipe.visual_graph if isinstance(recipe.visual_graph, Mapping) else {}
        text_layer = graph_payload.get("textLayer") or {}
        fill = text_layer.get("fill") or {}
        stops = fill.get("stops") or []
        if len(stops) >= 2:
            tags.append("METALLIC" if any(
                str(stop.get("color") or "").upper() in {
                    "#FFFFE9B8", "#FFD9A441", "#FF8A5A19", "#FFFFE2C0",
                    "#FFB87333", "#FF7A4A1D", "#FFFFF3D6", "#FFE0B25C",
                    "#FFA06B22", "#FFC9971F",
                } for stop in stops
            ) else "GRADIENT")
        if len(text_layer.get("strokes") or []) >= 2:
            tags.append("MULTI-STROKE")
        if (text_layer.get("glow") or {}).get("enabled"):
            tags.append("GLOW")
        for layer in graph_payload.get("decorationLayers") or []:
            name = str(layer.get("primitive") or "")
            if name and name != "NONE" and name not in tags:
                tags.append(name.replace("_", " "))
            if len(tags) >= 6:
                break
        for layer in graph_payload.get("effectLayers") or []:
            name = str(layer.get("primitive") or "")
            if name and name not in tags:
                tags.append(name.replace("_", " "))
            if len(tags) >= 6:
                break
        return " · ".join(tags[:6]) if tags else "CUSTOM"

    @staticmethod
    def _ai_failure_label(suggestion: AIDesignSuggestion) -> str:
        """Keep Provider failures actionable instead of collapsing all stages."""
        stage = str(getattr(suggestion, "failure_stage", "") or "").upper()
        labels = {
            "AUTH": "Provider 认证失败",
            "HTTP": "设计请求超时" if "timeout" in str(getattr(suggestion, "provider_error_category", "")).casefold() else "Provider 传输失败",
            "MODEL": "Provider 已响应 · 当前模型不可用",
            "PARSE": "Provider 已响应 · 设计结构无效",
            "SCHEMA": "Provider 已响应 · 设计结构无效",
            "QUALITY_VALIDATOR": "Provider 已响应 · 方案质量不足",
            "REPAIR": "Provider 已响应 · 修复未通过",
            "FINAL": "Provider 未完成",
        }
        return labels.get(stage, "Provider 未完成")

    def _normalize_ai_variants_for_cue(
        self,
        variants: Iterable[VisualStyleRecipe],
        cue_id: str,
    ) -> list[VisualStyleRecipe]:
        """Validate and bind pending card variants to the selected cue.

        The graph remains renderer-neutral, while its pending UI copy is
        normalized to the real cue span so card/apply/export observe the same
        lifetime. ``CompiledLiveScene`` still revalidates at render time.
        """
        if not self.project:
            return [copy.deepcopy(item) for item in variants]
        cue = cue_by_id(self.project, cue_id)
        cue_duration_ms = max(120, int(cue.end_ms) - int(cue.start_ms))
        normalized: list[VisualStyleRecipe] = []
        for source in variants:
            visual = copy.deepcopy(source)
            if isinstance(visual.visual_graph, Mapping) and visual.visual_graph:
                graph = normalize_motion_graph_to_cue(
                    VisualDesignGraph.from_dict(visual.visual_graph),
                    cue_duration_ms,
                )
                visual.visual_graph = graph.to_dict()
            visual.validate()
            normalized.append(visual)
        return normalized

    def _ai_variant_snapshot(self, visual: VisualStyleRecipe, index: int):
        if not self.project or not self.selected_cue_id:
            return None
        project = copy.deepcopy(self.project)
        cue = cue_by_id(project, self.selected_cue_id)
        source = next((item for item in project.styles if item.id == cue.style_id), None)
        if source is None:
            return None
        style = copy.deepcopy(source)
        recipe = visual.to_style_recipe()
        # Card previews always use the trusted final compositor, including for
        # designs that could also be represented by ASS. The user never sees a
        # painted mock substituted for the rendered pixels.
        recipe.engine = "remotion"
        recipe.validate()
        style.id = f"ai-card-preview-{index}"
        style.name = visual.name
        style.font_family = str(recipe.typography.get("fontFamily") or style.font_family)
        style.font_size = max(88.0, float(recipe.typography.get("fontSize") or style.font_size))
        visible_chars = max(1, len(str(cue.text or "").replace("\n", "")))
        target_size = 640.0 * 0.55 / max(1.0, visible_chars * 0.82)
        style.font_size = max(style.font_size, min(170.0, target_size))
        style.bold = bool(recipe.typography.get("bold", style.bold))
        style.italic = bool(recipe.typography.get("italic", style.italic))
        style.spacing = float(recipe.typography.get("spacing") or style.spacing)
        fill = recipe.colors.get("fill", style.primary_color)
        if isinstance(fill, Mapping):
            stops = fill.get("stops") or []
            if stops and isinstance(stops[0], Mapping):
                style.primary_color = str(stops[0].get("color") or style.primary_color)
        else:
            style.primary_color = str(fill)
        # AI cards are a 16:6 inspection stage, not a miniature final frame.
        # Centre a bilingual/two-line safe sample so typography, gradient and
        # stroke occupy roughly 25-45% of the stage instead of hugging bottom.
        style.position_x = 960.0
        style.position_y = 540.0
        style.alignment = 5
        cue.text = "精彩操作 Aa 123\n第二行测试字幕"
        cue.start_ms = 0
        cue.end_ms = 2400
        project.styles = [item for item in project.styles if item.id != style.id] + [style]
        project.style_recipes[style.id] = recipe.to_dict()
        cue.style_id = style.id
        cue.base_preset_id = style.id
        cue.appearance_override = {}
        cue.transform = {}
        return build_visual_cue_snapshot(project, cue.id, width=640, height=240, fps=30.0)

    def _start_ai_variant_previews(self, variants: list[VisualStyleRecipe]) -> None:
        self._ai_variant_preview_generation += 1
        generation = self._ai_variant_preview_generation
        snapshots = [self._ai_variant_snapshot(visual, index) for index, visual in enumerate(variants)]

        def work() -> None:
            indexed_requests = [
                (
                    index,
                    snapshot,
                    max(0, min(snapshot.end_ms - snapshot.start_ms - 1, 300)),
                    640,
                    240,
                )
                for index, snapshot in enumerate(snapshots)
                if snapshot is not None
            ]
            if generation != self._ai_variant_preview_generation:
                return
            for index, snapshot in enumerate(snapshots):
                if snapshot is None:
                    self.ai_variant_preview_ready_signal.emit(
                        generation, index, "无法为当前方案构建预览快照", False
                    )
            if not indexed_requests:
                return
            try:
                rendered = self._advanced_preview_cache.render_snapshot_batch(
                    [request[1:] for request in indexed_requests],
                    generation=generation,
                    batch_group=f"ai-style-cards:{generation}",
                    render_type="card_preview",
                    job_kind="card_preview",
                )
                for request, (_key, path, hit) in zip(indexed_requests, rendered):
                    if generation != self._ai_variant_preview_generation:
                        return
                    index = request[0]
                    self.ai_variant_preview_ready_signal.emit(generation, index, str(path), bool(hit))
            except Exception as exc:
                for index, *_request in indexed_requests:
                    self.ai_variant_preview_ready_signal.emit(generation, index, str(exc), False)

        threading.Thread(target=work, daemon=True, name="ai-style-card-previews").start()

    def _ai_variant_preview_ready(self, generation: int, index: int, value: str, success_or_hit: bool) -> None:
        if generation != self._ai_variant_preview_generation or not (0 <= index < len(self._ai_variant_preview_labels)):
            return
        label = self._ai_variant_preview_labels[index]
        pixmap = QPixmap(value)
        if pixmap.isNull():
            bind_text(label, '暂时无法生成预览；可重试生成方案')
            label.setToolTip(value)
        else:
            self._ai_variant_preview_paths[index] = value
            display = pixmap.scaled(
                max(1, label.width()), max(180, label.height()),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(display)
            bind_text(label, '使用成片渲染器生成{value0}', property='toolTip', value0=tr(' · 已缓存') if success_or_hit else '')
        self._ai_variant_preview_done.add(index)
        if len(self._ai_variant_preview_done) >= len(self._ai_variant_preview_labels):
            self._ai_stage_changed(
                self._ai_request_generation, AIDesignStage.COMPLETE.value
            )

    def _play_ai_variant_motion(self, index: int, visual: VisualStyleRecipe) -> None:
        if not (0 <= index < len(self._ai_variant_preview_labels)):
            return
        label = self._ai_variant_preview_labels[index]
        snapshot = self._ai_variant_snapshot(visual, index)
        if snapshot is None:
            return
        generation = self._ai_variant_preview_generation
        old = self._ai_variant_motion_timers.pop(index, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        graph_payload = (
            snapshot.style_recipe.get("visualGraph")
            if isinstance(snapshot.style_recipe, Mapping)
            else None
        )
        try:
            from .visual_design_graph import compile_live_scene

            duration = max(240, int(snapshot.end_ms - snapshot.start_ms))
            scene = compile_live_scene(
                graph_payload if isinstance(graph_payload, Mapping)
                else graph_from_style_recipe(snapshot.style_recipe),
                cue_duration_ms=duration,
            )
            layers = render_live_layers(snapshot, width=640, height=240)
            pivot = composition_pivot_for_snapshot(snapshot, 640, 240)
        except Exception as exc:
            bind_text(label, '实时动效暂不可用：{exc}', exc=exc)
            return
        started = time.monotonic()
        timer = QTimer(self)
        timer.setInterval(33)
        self._ai_variant_motion_timers[index] = timer

        def show_next() -> None:
            if generation != self._ai_variant_preview_generation:
                timer.stop()
                return
            relative_ms = min(duration, round((time.monotonic() - started) * 1000.0))
            frame, _sample = composite_live_scene_layers(
                layers, scene, relative_ms, pivot=pivot
            )
            pixmap = QPixmap.fromImage(frame)
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(
                    max(1, label.width()), max(180, label.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            if relative_ms >= duration:
                timer.stop()
                self._ai_variant_motion_timers.pop(index, None)
                cached_path = self._ai_variant_preview_paths[index]
                if cached_path:
                    self._ai_variant_preview_ready(generation, index, cached_path, True)
                else:
                    bind_text(label, 'LIVE 编译场景播放完成', property='toolTip')

        timer.timeout.connect(show_next)
        show_next()
        timer.start()

    def _select_ai_variant(self, visual: VisualStyleRecipe, source: AIDesignSuggestion) -> None:
        visual.validate()
        recipe = visual.to_style_recipe()
        # Selecting a card changes only the recipe. Preserve provider outcome,
        # failure stage, repair telemetry, and semantic directions for the
        # later Apply/Save actions and the audit trail.
        self._pending_suggestion = replace(source, recipe=recipe)
        self._preview_visual_recipe(visual)
        selected_index = next(
            (
                index for index, item in enumerate(source.variants)
                if item.to_dict() == visual.to_dict()
            ),
            0,
        )
        self._mark_ai_variant_selected(selected_index)
        direction = (
            source.art_directions[selected_index]
            if selected_index < len(source.art_directions)
            else None
        )
        self.ai_suggestion_title.setText(
            direction.concept_name if direction is not None else visual.name
        )
        route = route_recipe(recipe)
        (bind_text(self.ai_confidence, '可直接实时预览') if route.engine == 'native' else bind_text(self.ai_confidence, '复杂视觉方案 · 预览与成片使用同一视觉配方'))
        if direction is not None:
            bind_text(self.ai_preview, tr('{value0}\n{value1}\n\n{value2} · {value3}\n构图：{value4}\n配色：{value5}\n\n动效：\n{value6} → {value7} → {value8}', value0=direction.concept_name, value1=direction.intent, value2=direction.visual_language, value3=direction.hierarchy, value4=direction.composition, value5=direction.color_strategy, value6=direction.entrance_feel, value7=direction.hold_feel, value8=direction.exit_feel), property='plainText')
        else:
            bind_text(self.ai_preview, tr('{value0}\n完整视觉方向\n\n动效：已使用可信 MotionGraph 编译', value0=visual.name), property='plainText')

    def _mark_ai_variant_selected(self, index: int) -> None:
        for position, card in enumerate(getattr(self, "ai_variant_cards", [])):
            selected = position == index
            if bool(card.property("selected")) == selected:
                continue
            card.setProperty("selected", selected)
            card.style().unpolish(card)
            card.style().polish(card)

    def _apply_ai_variant(
        self, visual: VisualStyleRecipe, source: AIDesignSuggestion
    ) -> None:
        self._select_ai_variant(visual, source)
        self._apply_ai_preview()

    def _save_ai_variant(
        self, visual: VisualStyleRecipe, source: AIDesignSuggestion
    ) -> None:
        self._select_ai_variant(visual, source)
        self._save_ai_design_presets()

    def _show_ai_raw_response(self) -> None:
        suggestion = getattr(self, "_pending_suggestion", None)
        if not isinstance(suggestion, AIDesignSuggestion):
            self._show_studio_hint(tr('当前没有可查看的 AI 原始响应'))
            return
        dialog = QDialog(self)
        bind_text(dialog, 'AI 原始 JSON · 调试', property='windowTitle')
        dialog.resize(760, 620)
        apply_secondary_surface_theme(dialog)
        layout = QVBoxLayout(dialog)
        note = QLabel("仅调试模式显示。下面是 Provider 原始结构化响应，尚未经过 UI 摘要。")
        note.setWordWrap(True)
        layout.addWidget(note)
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(json.dumps(suggestion.raw_response, ensure_ascii=False, indent=2, sort_keys=True))
        layout.addWidget(viewer, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _preview_visual_recipe(self, visual: VisualStyleRecipe) -> None:
        if not hasattr(self, "style_preview"):
            return
        visual.validate()
        gradient = visual.fill if isinstance(visual.fill, dict) and str(visual.fill.get("type", "")).lower() != "solid" else None
        if gradient and gradient.get("stops"):
            stops = sorted(gradient.get("stops", []), key=lambda item: float(item.get("position", item.get("pos", 0))))
            parts = []
            for stop in stops:
                color = str(stop.get("color", "#FFFFFF"))
                position = round(float(stop.get("position", stop.get("pos", 0))) * 100)
                parts.append(f"stop:{position}% {color}")
            self.ai_gradient_swatch.setStyleSheet(
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0," + ",".join(parts) + "); border-radius:4px;"
            )
            self.ai_gradient_swatch.show()
        else:
            self.ai_gradient_swatch.hide()
        self.style_preview.set_gradient(gradient)
        self.style_preview.set_glow(visual.glow if visual.glow else None)
        self.style_preview.set_strokes(visual.strokes)
        self.style_preview.set_decorations(visual.decorations)
        if hasattr(self, "motion_preview"):
            self.motion_preview.set_gradient(gradient)
            self.motion_preview.set_glow(visual.glow if visual.glow else None)
            self.motion_preview.set_strokes(visual.strokes)
            self.motion_preview.set_decorations(visual.decorations)

    def _ai_failed(self, message: str) -> None:
        self._ai_request_active = False
        self._ai_cancel_event = None
        self._set_ai_input_sections_visible(True)
        self.ai_generate.setEnabled(True)
        self._show_ai_progress_bar(False)
        cancelled = "取消" in str(message)
        bind_text(self.ai_generate, '重新生成')
        self._pending_suggestion = None
        if hasattr(self, "ai_suggestion_card"):
            self.ai_suggestion_card.show()
        (bind_text(self.ai_suggestion_title, '生成已取消') if cancelled else bind_text(self.ai_suggestion_title, 'Provider 未完成'))
        (bind_text(self.ai_confidence, '未生成本地备选') if cancelled else bind_text(self.ai_confidence, '可根据具体错误重试 Provider'))
        self.ai_preview.setPlainText(message)

    def _apply_ai_preview(self) -> None:
        owner = getattr(self, '_theme_draft_coordinator', None)
        if (owner and owner.current and owner.current.theme_json and self.selected_cue_id
                and not owner.allow_pending() and owner.phase not in
                {'PROVIDER','RENDERING','EXPORTING','CONCEPT_PREVIEW','APPLYING'}):
            # Revalidate against the newly selected text/time instead of
            # silently keeping a stale target or bypassing the render gate.
            owner.adopt(owner.current.theme,self.selected_cue_id,label='重新校验并应用已采用方案')
            return
        if getattr(self,'_pending_web_theme',None) is not None:
            drafts = self._theme_drafts()
            if not drafts.allow_pending():
                self._show_studio_hint(tr('当前草稿尚未通过渲染校验，不能应用'))
                return
            frozen_pending = self._pending_web_theme
            try:
                self.style_controller._apply_ai_preview()
            except Exception as exc:
                drafts.error, drafts.category = str(exc), 'apply_error'
                drafts._set_phase('READY', '草稿已验证；应用未完成，可重试或导出：'+str(exc))
                drafts._save_state()
            finally:
                self._pending_web_theme = frozen_pending
                drafts.bind_pending()
            return
        return self.style_controller._apply_ai_preview()

    def _save_ai_design_presets(self) -> None:
        pending_web = getattr(self, "_pending_web_theme", None)
        if pending_web is not None:
            if not self._theme_drafts().allow_pending():
                self._show_studio_hint(tr('当前草稿尚未通过渲染校验，不能保存'))
                return
            # 网页主题路线：recipe 已带 webTheme，入库后特效字幕库可渲染
            # 真实 HTML/CSS 预览卡。
            from types import SimpleNamespace

            self.style_controller._persist_ai_design(
                SimpleNamespace(recipe=pending_web.recipe)
            )
            self._show_studio_hint(tr('网页主题「{value0}」已保存到样式库；可在「特效字幕库」查看真实预览', value0=pending_web.name))
            return
        suggestion = getattr(self, "_pending_suggestion", None)
        if suggestion is None:
            self._show_studio_hint(tr('请先生成视觉方案'))
            return
        self.style_controller._persist_ai_design(suggestion)
        self._show_studio_hint(tr('已保存到 Style Library；Motion 仍可单独在 Motion Library 管理'))

    def _persist_ai_design(self, suggestion) -> None:
        return self.style_controller._persist_ai_design(suggestion)

    def _refresh_saved_ai_styles(self) -> None:
        return self.style_controller._refresh_saved_ai_styles()

    def _apply_saved_ai_style(self, recipe_payload, name: str = "") -> None:
        return self.style_controller._apply_saved_ai_style(recipe_payload, name)

    def _apply_style_recipe(self, cue_id: str, recipe) -> bool:
        return self.style_controller._apply_style_recipe(cue_id, recipe)

    def _apply_web_theme(self, cue_id: str, theme, *, preserve_overrides=None) -> bool:
        # 单行委托（studio_ui 拆分后的 wrapper 纪律）：AI 面板回调与特效字幕库
        # 都通过 page._apply_web_theme 访问 controller。
        return self.style_controller._apply_web_theme(cue_id, theme,preserve_overrides=preserve_overrides)

    def _update_advanced_style_status(self, payload: Mapping[str, object]) -> None:
        if not hasattr(self, "advanced_style_status"):
            return
        web_updater = getattr(self, "_update_web_adjust_visibility", None)
        if callable(web_updater):
            web_updater()
        status = AdvancedRendererBackend().status()
        (bind_text(self.advanced_style_status, '渲染环境就绪') if status.available else bind_text(self.advanced_style_status, '未安装 · {value0}', value0=status.reason))
        if payload:
            try:
                recipe = StyleRecipe.from_dict(payload)
                route = route_recipe(recipe)
                layers = recipe.outline.get("layers", [])
                glow = recipe.effects.get("glow", {}) if isinstance(recipe.effects, Mapping) else {}
                motion = recipe.motion.get("entrance", recipe.motion.get("entry", {})) if isinstance(recipe.motion, Mapping) else {}
                self.advanced_style_chips.setText(
                    f"{len(layers) or 1}× Stroke · Glow {int(float(glow.get('blur', 0) or 0))} · "
                    f"{motion.get('type', route.engine)}"
                )
            except (TypeError, ValueError, KeyError):
                bind_text(self.advanced_style_chips, '多层 Stroke · Glow · Motion')

    def _apply_advanced_gallery_preset(self, prompt: str) -> None:
        if not self.project or not self.selected_cue_id:
            return
        recipe = style_recipe_for_prompt(prompt)
        self._preview_visual_recipe(VisualStyleRecipe.from_style_recipe(recipe))
        if self._apply_style_recipe(self.selected_cue_id, recipe):
            self._queue_advanced_preview(recipe.to_dict())

    def _open_ai_design_from_style(self) -> None:
        if hasattr(self, "context_drawer"):
            self.context_drawer.setCurrentIndex(0)
        if hasattr(self, "ai_prompt"):
            self.ai_prompt.setFocus(Qt.FocusReason.TabFocusReason)

    def _clear_advanced_style(self) -> None:
        return self.style_controller._clear_advanced_style()

    def _replay_advanced_preview(self) -> None:
        if not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = self.project.style_recipes.get(cue.style_id, {}) if cue else {}
        if payload:
            self._queue_advanced_preview(payload, force=True, delay_ms=0)
            try:
                visual = VisualStyleRecipe.from_style_recipe(StyleRecipe.from_dict(payload))
                self.motion_preview.play_motion(visual.motion.to_dict())
            except (TypeError, ValueError):
                pass

    def _advanced_preview_quality_changed(self, _index: int = -1) -> None:
        if not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = self.project.style_recipes.get(cue.style_id, {}) if cue else {}
        if payload:
            self._queue_advanced_preview(payload)

    def _advanced_preview_size(self) -> tuple[int, int]:
        """Preview composition resolution for the current quality tier.

        Draft/Balanced/High map to fixed 640/960/1280 widths; Auto picks the
        smallest tier that still covers the visible preview surface at the
        current device pixel ratio, so a big Studio panel stops upscaling a
        640px frame (the classic "dirty preview" cause).
        """
        quality = "auto"
        if hasattr(self, "advanced_preview_quality"):
            quality = str(self.advanced_preview_quality.currentData() or "auto")
        fixed = {
            # Legacy values kept so old persisted selections stay valid.
            "low": (640, 360),
            "medium": (960, 540),
            "draft": (640, 360),
            "balanced": (960, 540),
            "high": (1280, 720),
        }
        if quality in fixed:
            return fixed[quality]
        tiers = ((640, 360), (960, 540), (1280, 720))
        # Auto: cover whichever surface actually shows the frame — the video
        # overlay is the big one (a top-level window sized in physical px).
        target = 960
        label = getattr(self, "advanced_preview_image", None)
        if label is not None:
            dpr = float(label.devicePixelRatioF() or 1.0)
            target = int(round(max(1, label.width()) * dpr))
        overlay = getattr(self, "advanced_cue_overlay", None)
        if overlay is not None and not overlay._base_rect.isEmpty():
            target = max(target, int(overlay._base_rect.width()))
        for width, height in tiers:
            if width >= target:
                return (width, height)
        return tiers[-1]
