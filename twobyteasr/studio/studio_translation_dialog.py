"""Translate / generate bilingual subtitles for the open project (Japanese -> Chinese).

One dialog for the whole workflow: choose the scope (all, selected, or only
cues that are untranslated / failed / need an update), the Chinese script and
optional context and term pairs, then run the configured AI text service.
Only subtitle text (with a few neighbouring lines as context) is sent; audio,
timing and speakers stay local and unchanged. Results are applied as one
undoable edit; manual translations are never overwritten silently.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QApplication)

from ..i18n import bind_text, tr, user_text

from ..subtitle_rules.recognition_translation import load_cache, save_cache  # noqa: E402

# Derived per-cue states (subtitle_translation.STATUSES), in display order.
STATUS_LABELS = (("untranslated", "未翻译"), ("done", "已翻译"), ("manual", "人工译文"),
                 ("needs_update", "需更新 / 合并后部分缺译"), ("failed", "失败"))


def _european_label(language: str) -> str:
    """西班牙语 / 德语 / 法语 / 葡萄牙语 / 意大利语 / 俄语, or '' (2026-10-19)."""
    from ..subtitle_rules.european_text import LABELS
    return LABELS.get(str(language or ""), "")


def parse_glossary(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in str(text or "").splitlines():
        for separator in ("=", "＝", "→", "->", "\t"):
            if separator in line:
                left, right = line.split(separator, 1)
                if left.strip() and right.strip():
                    pairs.append((left.strip(), right.strip()))
                break
    return pairs


class _Signals(QObject):
    progress = Signal(int, int, str)
    event = Signal(object)
    finished = Signal(object)


class SubtitleTranslationDialog(QDialog):
    translation_finished = Signal(bool, dict)

    def __init__(self, page, parent=None, *, scope=None) -> None:
        super().__init__(parent)
        bind_text(self, '翻译 / 生成双语字幕', property='windowTitle')
        self.setMinimumWidth(520)
        self.page = page
        self.project = page.project
        self._session_generation = getattr(getattr(page, 'session', None), 'generation', None)
        self._cancel = threading.Event()
        self._thread = None
        self._result = None
        self._log = None
        self._signals = _Signals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.event.connect(self._on_event)
        from ..subtitle_rules.subtitle_translation import migrate
        migrate(self.project)
        layout = QVBoxLayout(self)
        from ..subtitle_rules.language_rules import project_language
        language = project_language(self.project)
        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        self._language = language
        bind_text(self.language_note, ("原文：日语（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。"
                                       if language == "ja" else
                                       "原文：英语（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。"
                                       if language == "en" else
                                       "原文：韩语（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。"
                                       if language == "ko" else
                                       tr("原文：{value0}（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。",
                                          value0=tr(_european_label(language)))
                                       if _european_label(language) else
                                       "原文：中文（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。"
                                       if language == "zh" else
                                       "这个工程没有记录识别语言，按日语原文处理；请确认原文是日语。"))
        layout.addWidget(self.language_note)
        self.scope_group = QButtonGroup(self)
        selected = list(getattr(page, "selected_cue_ids", lambda: [])() or [])
        self._selected = selected
        scopes = (("pending", tr("只处理未翻译、失败和需要更新的字幕")), ("all", tr("全部字幕（人工译文保留）")),
                  ("selected", tr("选中的 {count} 条字幕", count=len(selected))))
        self.scope_buttons = {}
        for key, label in scopes:
            button = QRadioButton(label)
            self.scope_group.addButton(button)
            self.scope_buttons[key] = button
            layout.addWidget(button)
        self.scope_buttons["selected"].setEnabled(bool(selected))
        initial_scope = scope if scope in ('all', 'pending') else ('selected' if selected else 'pending')
        self.scope_buttons[initial_scope].setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("译文语言")))
        # Any target in another language than the source (2026-10-14); native names.
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, targets_for
        self.script = user_text(QComboBox())
        for target in targets_for(language):
            self.script.addItem(TARGET_LABELS[target], target)
        stored = ((self.project.generation_metadata.get("translation_records") or {}).get("target")
                  or (self.project.generation_metadata.get("subtitle_output") or {}).get("translation_script")
                  or "zh-Hans")
        self.script.setCurrentIndex(max(0, self.script.findData(stored)))
        row.addWidget(self.script, 1)
        layout.addLayout(row)
        self.context = QLineEdit(str(self.project.generation_metadata.get("translation_context")
                                     or getattr(page, "_content_name", "") or ""))
        bind_text(self.context, '背景（可选）：作品 / 游戏名、角色关系，帮助译名一致', property='placeholderText')
        layout.addWidget(self.context)
        self.glossary = QPlainTextEdit()
        self.glossary.setMaximumHeight(90)
        self._glossary_hint()
        pairs = self.project.generation_metadata.get("translation_glossary") or []
        self.glossary.setPlainText("\n".join(f"{a} = {b}" for a, b in pairs if a and b))
        layout.addWidget(self.glossary)
        self.counts = QLabel()
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        self.service = QLabel()
        self.service.setWordWrap(True)
        self.service.setObjectName("contextMeta")
        layout.addWidget(self.service)
        self.settings_button = QPushButton(tr('前往设置：AI 文字翻译服务 / API Key'))
        self.settings_button.clicked.connect(self._go_to_settings)
        layout.addWidget(self.settings_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log_note = QLabel(tr("请求日志只保留批次、用量与验证摘要；要分享字幕内容，请在「回报问题」中选择。"))
        self.log_note.setWordWrap(True)
        layout.addWidget(self.log_note)
        self.request_log = QPlainTextEdit()
        self.request_log.setReadOnly(True)
        self.request_log.setMaximumBlockCount(1000)
        self.request_log.setFixedHeight(125)
        self.request_log.setPlaceholderText(tr("开始后显示每批请求、耗时、用量、失败原因和重试过程。"))
        layout.addWidget(self.request_log)
        buttons = QHBoxLayout()
        self.copy_log_button = QPushButton(tr("复制请求日志"))
        self.copy_log_button.setEnabled(False)
        self.copy_log_button.clicked.connect(self._copy_log)
        buttons.addWidget(self.copy_log_button)
        self.usage_button = QPushButton(tr('用量与估算费用'))
        self.usage_button.clicked.connect(self._show_usage)
        buttons.addWidget(self.usage_button)
        self._usage_task_id = ''
        self.accept_suggestions_button = QPushButton(tr("用 AI 结果替换这些人工译文"))
        self.accept_suggestions_button.hide()
        self.accept_suggestions_button.clicked.connect(self._accept_suggestions)
        buttons.addWidget(self.accept_suggestions_button)
        buttons.addStretch(1)
        self.start_button = QPushButton(tr("开始翻译"))
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton(tr("取消"))
        self.cancel_button.clicked.connect(self._cancel_or_close)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self._provider_ready = self._describe_service()
        self._refresh_counts()
        self.script.currentIndexChanged.connect(self._target_changed)

    def _go_to_settings(self):
        from .translation_actions import open_translation_settings
        open_translation_settings(self)

    def _show_usage(self):
        from .usage_dialog import open_usage
        open_usage(self, project=self.project, task_id=self._usage_task_id)

    # -- state -------------------------------------------------------------
    def _target(self) -> str:
        return str(self.script.currentData() or "zh-Hans")

    def _target_changed(self, _index: int) -> None:
        self._glossary_hint()
        self._refresh_counts()

    def _glossary_hint(self) -> None:
        chinese_target = self._target() in ("zh-Hans", "zh-Hant")
        if chinese_target and self._language == "en":
            hint = '术语对照（可选，每行一条）：英文 = 中文，例如 Paimon = 派蒙'
        elif chinese_target and self._language == "ko":
            hint = '术语对照（可选，每行一条）：韩文 = 中文，例如 페이몬 = 派蒙'
        elif chinese_target and _european_label(self._language):
            hint = '术语对照（可选，每行一条）：原文 = 中文，例如 Paimon = 派蒙'
        elif chinese_target:
            hint = '术语对照（可选，每行一条）：日文 = 中文，例如 ゆっこ = 由子'
        else:
            hint = '术语对照（可选，每行一条）：原文 = 译文，例如 派蒙 = Paimon'
        bind_text(self.glossary, hint, property='placeholderText')

    def _refresh_counts(self) -> None:
        from ..subtitle_rules.subtitle_translation import status_counts
        counts = status_counts(self.project, target=self._target())
        bind_text(self.counts, " · ".join(f"{tr(label)} {counts.get(key, 0)}" for key, label in STATUS_LABELS))

    def _describe_service(self) -> bool:
        from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
        from ..providers.llm_config import text_ai_key_missing
        missing = False
        try:
            settings = GLOBAL_PROVIDER_REGISTRY.settings()
            selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
            ready, _source = GLOBAL_PROVIDER_REGISTRY.credential(selection)
            model = str(getattr(selection, "model", "") or "")
            name = f"{selection.service or selection.provider}{' · ' + model if model else ''}"
            missing = not ready and text_ai_key_missing(settings, "polish")
        except Exception:  # noqa: BLE001 - shown to the user as "not configured"
            ready, name = False, ""
        if ready:
            bind_text(self.service, "使用已配置的 AI 文字服务：{name}。只发送字幕文字和前后几句上下文（不发送音频），"
                                    "按批请求，可能产生费用；不会改用其他模型。", name=name)
        elif missing:
            # 2026-10-15: only the key is missing — 开始翻译 stays clickable and explains it.
            bind_text(self.service, '文字翻译服务 {name} 尚未填写 API Key。请前往“字幕校对”服务设置；不是语音识别 ASR 的 Key。', name=name)
        else:
            bind_text(self.service, "还没有配置 AI 文字服务：请先在设置中配置“字幕校对”使用的服务，再回来翻译。")
        self.start_button.setEnabled(ready or missing)
        return ready or missing

    def _scope_ids(self):
        from ..subtitle_rules.subtitle_translation import ids_with_status
        if self.scope_buttons["selected"].isChecked():
            return list(self._selected)
        if self.scope_buttons["all"].isChecked():
            return None
        return ids_with_status(self.project, {"untranslated", "failed", "needs_update"}, target=self._target())

    # -- run ---------------------------------------------------------------
    def _owns_project(self) -> bool:
        return (not getattr(self.page, '_close_requested', False)
                and self.page.project is self.project
                and getattr(getattr(self.page, 'session', None), 'generation', None) == self._session_generation)

    def _log_disowned_result(self, result=None) -> None:
        from ..diagnostics.studio_events import background_result
        decision = ("discarded_project_changed" if self.page.project is not self.project else
                    "discarded_page_closed" if getattr(self.page, "_close_requested", False) else
                    "discarded_session_changed")
        background_result(getattr(self, "_diagnostic", {}), self.page.project,
                          decision=decision, cancelled=bool(getattr(result, "cancelled", False)),
                          applied_count=0)

    def _start(self) -> None:
        if self._thread is not None:
            return
        if not self._owns_project():
            bind_text(self.status, '工程已切换或关闭，请在当前工程重新打开翻译。')
            return
        from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
        from ..providers.ai_providers import provider_for_stage
        from ..subtitle_rules.subtitle_translation import translation_source
        ids = self._scope_ids()
        if ids is not None and not ids:
            bind_text(self.status, "没有需要处理的字幕。")
            return
        from ..providers.llm_config import text_ai_key_missing
        if text_ai_key_missing(GLOBAL_PROVIDER_REGISTRY.settings(), 'polish'):
            self._describe_service()
            bind_text(self.status, '翻译没有运行：请点击“前往设置”填写当前文字服务的 API Key；保存后会检查原文并继续。')
            self.settings_button.setFocus()
            return
        self.request_log.clear()
        self.accept_suggestions_button.hide()
        self._result = None
        from ..subtitle_rules.translation_diagnostics import TranslationLog
        self._log = TranslationLog()
        self.copy_log_button.setEnabled(True)
        self.request_log.appendPlainText(tr("日志文件：{path}", path=str(self._log.path)))
        pairs = parse_glossary(self.glossary.toPlainText())
        self.project.generation_metadata["translation_glossary"] = [list(pair) for pair in pairs]
        self.project.generation_metadata["translation_context"] = self.context.text().strip()
        source = translation_source(self.project)
        try:
            provider = provider_for_stage(GLOBAL_PROVIDER_REGISTRY.settings(), "polish")
        except Exception as exc:
            self._log({"event": "error", "error": str(exc)})
            self._on_finished(exc)
            return
        options = dict(target=self._target(), game_context=self.context.text().strip(), glossary_pairs=pairs)
        self._request_target = options['target']
        import uuid
        self._usage_task_id = uuid.uuid4().hex
        self._cancel.clear()
        self.start_button.setEnabled(False)
        self.script.setEnabled(False)
        self.settings_button.setEnabled(False)
        for button in self.scope_buttons.values():
            button.setEnabled(False)
        bind_text(self.cancel_button, "停止")
        bind_text(self.status, "正在翻译…")
        cache = load_cache()

        def record(event):
            self._log(event)
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.event.emit(event)

        def progress(done, total, message=''):
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.progress.emit(int(done), int(total), str(message or ''))

        def work():
            from ..subtitle_rules.subtitle_translation import translate
            try:
                from ..providers.usage_ledger import usage_scope
                with usage_scope(project_id=source.project_id, task_id=self._usage_task_id):
                    result = translate(source, ids, provider, cancel_check=self._cancel.is_set,
                                       progress=progress, cache=cache, suggest_for_manual=True,
                                       event=record, **options)
                try:
                    save_cache(cache)
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001 - reported in the dialog
                from ..providers.provider_diagnostics import redact_diagnostics
                record({"event": "error", "error": str(redact_diagnostics(str(exc)))})
                result = exc
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.finished.emit(result)

        from ..diagnostics.studio_events import background_ticket
        self._diagnostic = background_ticket(self.project,"translation",ids=ids)
        from ..diagnostics.event_log import context
        original_work = work
        def bound_work():
            with context(**self._diagnostic):
                original_work()
        self._thread = threading.Thread(target=bound_work, name="subtitle-translation", daemon=True)
        self._thread.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setValue(int(100 * done / max(1, total)))
        bind_text(self.status, "已完成 {done}/{total} 条 {message}", done=done, total=total, message=message)

    def _on_event(self, event: dict) -> None:
        from ..providers.provider_diagnostics import redact_diagnostics
        event = redact_diagnostics(event)
        kind, batch = event.get("event"), event.get("batch", "")
        prefix = f"[{event.get('at', '')}] "
        if kind == "request":
            text = tr("第 {batch} 批 · {provider} / {model} · {count} 条 · 输出上限 {tokens}",
                      batch=batch, provider=event.get("provider"), model=event.get("model"),
                      count=len(event.get("ids", [])), tokens=event.get("max_tokens"))
        elif kind == "response":
            usage = event.get("usage") or {key: value for key, value in event.get("response_metadata", {}).items()
                                          if key in {"prompt_tokens", "completion_tokens", "total_tokens"}}
            text = tr("第 {batch} 批返回 · {seconds} 秒 · 用量 {usage}", batch=batch,
                      seconds=event.get("elapsed_seconds"), usage=json.dumps(usage, ensure_ascii=False) if usage else tr("未返回用量"))
        elif kind == "validated":
            text = tr("第 {batch} 批校验 · 接受 {count} 条 · 问题 {problems}", batch=batch,
                      count=event.get("accepted"), problems=json.dumps(event.get("problems", {}), ensure_ascii=False))
        elif kind == "error":
            from .translation_actions import failure_hint
            text = tr("第 {batch} 批失败 · {category} · {error}", batch=batch,
                      category=event.get("category", ""), error=event.get("error", ""))
            text += ' ' + failure_hint(event.get('category'))
        elif kind == "retry":
            text = tr("第 {batch} 批重试 · 剩余 {count} 条 · 等待 {seconds} 秒 · 输出至少 {tokens}",
                      batch=batch, count=len(event.get("ids", [])), seconds=event.get("wait_seconds"),
                      tokens=event.get("output_floor"))
        elif kind == "started":
            text = tr("开始翻译：{count} 条 · {provider} / {model}", count=event.get("requested"),
                      provider=event.get("provider"), model=event.get("model"))
        elif kind == "finished":
            summary = event.get("summary", {})
            text = tr("翻译结束：成功 {done} 条，失败 {failed} 条，请求 {requests} 批", done=summary.get("succeeded", 0),
                      failed=summary.get("failed", 0), requests=summary.get("requests", 0))
        elif kind == "cache":
            text = tr("缓存命中 {count} 条", count=event.get("count", 0))
        elif kind == "split":
            text = tr("拆分批次：{count} 条 · {reason}", count=len(event.get("ids", [])), reason=event.get("reason"))
        else:
            # Request/answer bodies stay in the copyable file; the visible log
            # remains readable while a long project is running.
            text = json.dumps({key: value for key, value in event.items()
                               if key not in {"at", "provider", "model", "target", "failed"}}, ensure_ascii=False)
        self.request_log.appendPlainText(prefix + text)
        self.request_log.verticalScrollBar().setValue(self.request_log.verticalScrollBar().maximum())

    def _copy_log(self) -> None:
        from ..providers.provider_diagnostics import redact_diagnostics
        text = self.request_log.toPlainText()
        if self._log is not None:
            try:
                text = self._log.path.read_text(encoding="utf-8")
            except OSError:
                pass
        QApplication.clipboard().setText(str(redact_diagnostics(text)))

    def _on_finished(self, result) -> None:
        self._thread = None
        self.script.setEnabled(True)
        self.settings_button.setEnabled(True)
        for key, button in self.scope_buttons.items():
            button.setEnabled(key != 'selected' or bool(self._selected))
        if not self._owns_project():
            self._log_disowned_result(result)
            self._result = None
            self.start_button.setEnabled(False)
            self.accept_suggestions_button.hide()
            bind_text(self.cancel_button, '关闭')
            bind_text(self.status, '工程已切换或关闭，这次翻译结果未写入。')
            self.translation_finished.emit(False, {})
            return
        self.start_button.setEnabled(self._provider_ready)
        bind_text(self.cancel_button, "关闭")
        if self._log is not None and self._log.error:
            self.request_log.appendPlainText(tr("日志文件写入失败：{error}", error=self._log.error))
        if isinstance(result, Exception):
            from ..diagnostics.studio_events import background_result
            from ..diagnostics.event_log import emit, exception_info
            background_result(getattr(self,"_diagnostic",{}),self.page.project,decision="failed",cancelled=self._cancel.is_set())
            emit("translation.failed",level="ERROR",result="failed",exception=exception_info(result),**getattr(self,"_diagnostic",{}))
            from ..providers.provider_diagnostics import redact_diagnostics
            from .translation_actions import failure_hint
            error = failure_hint(getattr(result, 'category', '')) + str(redact_diagnostics(str(result)))
            self.request_log.appendPlainText(error)
            bind_text(self.status, "翻译没有完成：{error}。已完成的部分没有写入，可以再试。", error=error[:200])
            self.translation_finished.emit(False, {})
            return
        from ..diagnostics.studio_events import background_result
        self._result = result
        if result.target != self._target():
            background_result(getattr(self,"_diagnostic",{}), self.project,
                              decision="discarded_target_changed", cancelled=result.cancelled, applied_count=0)
            bind_text(self.status, '目标语言已变化，迟到的翻译结果没有写入。')
            self.translation_finished.emit(False, {})
            return
        if self.page.project is not self.project:
            self._log_disowned_result(result)
            bind_text(self.status, '工程已切换，迟到的翻译结果没有写入。请求用量仍保留在记录中。')
            self.translation_finished.emit(False, {})
            return
        from ..subtitle_rules.subtitle_translation import apply_translation_result
        from .studio_bilingual import ApplyTranslationSnapshotCommand, apply_display, current_settings
        from ..diagnostics.event_log import context
        with context(**getattr(self, "_diagnostic", {})):
            before, after = apply_translation_result(self.project, result)
            changed_ids = list(result.translations)
            if before != after:
                self.page.undo_stack.push(ApplyTranslationSnapshotCommand(self.project, before, after, changed_ids,
                                                                          label="AI 翻译字幕"))
            decision = ("partially_accepted" if result.discarded and result.translations else
                        "discarded_stale" if result.discarded else
                        "accepted" if result.translations else
                        "waiting" if result.suggestions else
                        "cancelled" if result.cancelled else "failed" if result.failed else "skipped")
            background_result(getattr(self,"_diagnostic",{}), self.project, decision=decision,
                              cancelled=result.cancelled, stale_ids=result.discarded,
                              applied_count=len(changed_ids) if before != after else 0,
                              discard_reasons=result.discarded)
        parts = [tr("成功 {count} 条", count=len(result.translations))]
        if result.discarded:
            parts.append(tr('跳过 {count} 条已修改、撤销或删除的字幕', count=len(result.discarded)))
        if result.cache_hits:
            parts.append(tr("其中 {count} 条来自翻译缓存", count=len(result.cache_hits)))
        if result.failed:
            parts.append(tr("失败 {count} 条（可选“只处理未翻译、失败…”再试）", count=len(result.failed)))
            from ..providers.provider_diagnostics import redact_diagnostics
            reason = str(redact_diagnostics(result.fatal_error or next(iter(result.failed.values()))))
            parts.append(tr("失败原因：{error}（详情见请求日志）", error=reason[:180]))
        if result.suggestions:
            parts.append(tr("人工译文 {count} 条保留不变（AI 结果可选择替换）", count=len(result.suggestions)))
            self.accept_suggestions_button.show()
        if getattr(result, "pending", None):
            parts.append(tr("未处理 {count} 条", count=len(result.pending)))
        if result.cancelled:
            parts.append(tr("已停止；已完成的部分已保存"))
        bind_text(self.status, "；".join(parts) + "。")
        self.progress.setValue(100)
        self._refresh_counts()
        if result.translations and current_settings(self.page).mode == "original":
            apply_display(self.page, mode="bilingual")
        self.translation_finished.emit(bool(result.translations), dict(result.translations))

    def _accept_suggestions(self) -> None:
        if self._result is None:
            return
        if not self._owns_project():
            self._log_disowned_result(self._result)
            return
        from ..subtitle_rules.subtitle_translation import accept_suggestions
        from .studio_bilingual import ApplyTranslationSnapshotCommand
        from ..diagnostics.studio_events import background_result
        from ..diagnostics.event_log import context
        with context(**getattr(self, "_diagnostic", {})):
            before, after = accept_suggestions(self.project, self._result)
            if before != after:
                self.page.undo_stack.push(ApplyTranslationSnapshotCommand(
                    self.project, before, after, list(self._result.suggestions), label="采用 AI 译文"))
            background_result(getattr(self,"_diagnostic",{}), self.project,
                              decision="accepted" if before != after else "skipped",
                              stale_ids=self._result.discarded, discard_reasons=self._result.discarded,
                              applied_count=len(self._result.suggestions) if before != after else 0)
        self.accept_suggestions_button.hide()
        self._refresh_counts()

    def _cancel_or_close(self) -> None:
        if self._thread is not None:
            self._cancel.set()
            bind_text(self.status, "正在停止：等待当前这一批返回…")
            return
        self.reject()

    def reject(self) -> None:
        if self._thread is not None:
            self._cancel.set()
            return
        super().reject()
