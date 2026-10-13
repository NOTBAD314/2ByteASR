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
                               QProgressBar, QPushButton, QRadioButton, QVBoxLayout)

from .i18n import bind_text, tr

from .recognition_translation import load_cache, save_cache  # noqa: E402

# Derived per-cue states (subtitle_translation.STATUSES), in display order.
STATUS_LABELS = (("untranslated", "未翻译"), ("done", "已翻译"), ("manual", "人工译文"),
                 ("needs_update", "原文已改需更新"), ("failed", "失败"))


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
    finished = Signal(object)


class SubtitleTranslationDialog(QDialog):
    translation_finished = Signal(bool, dict)

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        bind_text(self, '翻译 / 生成双语字幕', property='windowTitle')
        self.setMinimumWidth(520)
        self.page = page
        self.project = page.project
        self._cancel = threading.Event()
        self._thread = None
        self._result = None
        self._signals = _Signals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        from .subtitle_translation import migrate
        migrate(self.project)
        layout = QVBoxLayout(self)
        from .language_rules import project_language
        language = project_language(self.project)
        self.language_note = QLabel()
        self.language_note.setWordWrap(True)
        bind_text(self.language_note, ("原文：日语（识别时判定）。译文与原文分开保存，原文、说话人和时间不变。"
                                       if language == "ja" else
                                       "这个工程没有记录为日语素材；翻译仍按“日文 → 中文”处理，请确认原文是日语。"))
        layout.addWidget(self.language_note)
        self.scope_group = QButtonGroup(self)
        selected = list(getattr(page, "selected_cue_ids", lambda: [])() or [])
        self._selected = selected
        scopes = (("pending", "只处理未翻译、失败和需要更新的字幕"), ("all", "全部字幕（人工译文保留）"),
                  ("selected", f"选中的 {len(selected)} 条字幕"))
        self.scope_buttons = {}
        for key, label in scopes:
            button = QRadioButton(tr(label))
            self.scope_group.addButton(button)
            self.scope_buttons[key] = button
            layout.addWidget(button)
        self.scope_buttons["selected"].setEnabled(bool(selected))
        self.scope_buttons["pending"].setChecked(True)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("中文字形")))
        self.script = QComboBox()
        self.script.addItem("简体中文", "zh-Hans")
        self.script.addItem("繁體中文", "zh-Hant")
        stored = ((self.project.generation_metadata.get("subtitle_output") or {}).get("translation_script")
                  or (self.project.generation_metadata.get("translation_records") or {}).get("target") or "zh-Hans")
        self.script.setCurrentIndex(max(0, self.script.findData(stored)))
        row.addWidget(self.script, 1)
        layout.addLayout(row)
        self.context = QLineEdit(str(self.project.generation_metadata.get("translation_context")
                                     or getattr(page, "_content_name", "") or ""))
        bind_text(self.context, '背景（可选）：作品 / 游戏名、角色关系，帮助译名一致', property='placeholderText')
        layout.addWidget(self.context)
        self.glossary = QPlainTextEdit()
        self.glossary.setMaximumHeight(90)
        bind_text(self.glossary, '术语对照（可选，每行一条）：日文 = 中文，例如 ゆっこ = 由子', property='placeholderText')
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
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
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

    # -- state -------------------------------------------------------------
    def _target(self) -> str:
        return str(self.script.currentData() or "zh-Hans")

    def _refresh_counts(self) -> None:
        from .subtitle_translation import status_counts
        counts = status_counts(self.project, target=self._target())
        bind_text(self.counts, " · ".join(f"{tr(label)} {counts.get(key, 0)}" for key, label in STATUS_LABELS))

    def _describe_service(self) -> bool:
        from .studio_ai import GLOBAL_PROVIDER_REGISTRY
        try:
            settings = GLOBAL_PROVIDER_REGISTRY.settings()
            selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
            ready, _source = GLOBAL_PROVIDER_REGISTRY.credential(selection)
            model = str(getattr(selection, "model", "") or "")
            name = f"{selection.service or selection.provider}{' · ' + model if model else ''}"
        except Exception:  # noqa: BLE001 - shown to the user as "not configured"
            ready, name = False, ""
        if ready:
            bind_text(self.service, "使用已配置的 AI 文字服务：{name}。只发送字幕文字和前后几句上下文（不发送音频），"
                                    "按批请求，可能产生费用；不会改用其他模型。", name=name)
        else:
            bind_text(self.service, "还没有配置 AI 文字服务：请先在设置中配置“字幕校对”使用的服务，再回来翻译。")
        self.start_button.setEnabled(ready)
        return ready

    def _scope_ids(self):
        from .subtitle_translation import ids_with_status
        if self.scope_buttons["selected"].isChecked():
            return list(self._selected)
        if self.scope_buttons["all"].isChecked():
            return None
        return ids_with_status(self.project, {"untranslated", "failed", "needs_update"}, target=self._target())

    # -- run ---------------------------------------------------------------
    def _start(self) -> None:
        from .studio_ai import GLOBAL_PROVIDER_REGISTRY
        from .ai_providers import provider_for_stage
        from .subtitle_translation import translation_source
        ids = self._scope_ids()
        if ids is not None and not ids:
            bind_text(self.status, "没有需要处理的字幕。")
            return
        pairs = parse_glossary(self.glossary.toPlainText())
        self.project.generation_metadata["translation_glossary"] = [list(pair) for pair in pairs]
        self.project.generation_metadata["translation_context"] = self.context.text().strip()
        source = translation_source(self.project)
        provider = provider_for_stage(GLOBAL_PROVIDER_REGISTRY.settings(), "polish")
        options = dict(target=self._target(), game_context=self.context.text().strip(), glossary_pairs=pairs)
        self._cancel.clear()
        self.start_button.setEnabled(False)
        bind_text(self.cancel_button, "停止")
        bind_text(self.status, "正在翻译…")
        cache = load_cache()

        def work():
            from .subtitle_translation import translate
            try:
                result = translate(source, ids, provider, cancel_check=self._cancel.is_set,
                                   progress=lambda done, total, message="": self._signals.progress.emit(
                                       int(done), int(total), str(message or "")),
                                   cache=cache, suggest_for_manual=True, **options)
                try:
                    save_cache(cache)
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001 - reported in the dialog
                result = exc
            self._signals.finished.emit(result)

        self._thread = threading.Thread(target=work, name="subtitle-translation", daemon=True)
        self._thread.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setValue(int(100 * done / max(1, total)))
        bind_text(self.status, "已完成 {done}/{total} 条 {message}", done=done, total=total, message=message)

    def _on_finished(self, result) -> None:
        self._thread = None
        self.start_button.setEnabled(self._provider_ready)
        bind_text(self.cancel_button, "关闭")
        if isinstance(result, Exception):
            bind_text(self.status, "翻译没有完成：{error}。已完成的部分没有写入，可以再试。", error=str(result)[:200])
            self.translation_finished.emit(False, {})
            return
        self._result = result
        from .subtitle_translation import apply_translation_result
        from .studio_bilingual import ApplyTranslationSnapshotCommand, apply_display, current_settings
        before, after = apply_translation_result(self.project, result)
        changed_ids = list(result.translations)
        if before != after:
            self.page.undo_stack.push(ApplyTranslationSnapshotCommand(self.project, before, after, changed_ids,
                                                                      label="AI 翻译字幕"))
        parts = [tr("成功 {count} 条", count=len(result.translations))]
        if result.cache_hits:
            parts.append(tr("其中 {count} 条来自翻译缓存", count=result.cache_hits))
        if result.failed:
            parts.append(tr("失败 {count} 条（可选“只处理未翻译、失败…”再试）", count=len(result.failed)))
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
        from .subtitle_translation import accept_suggestions
        from .studio_bilingual import ApplyTranslationSnapshotCommand
        before, after = accept_suggestions(self.project, self._result)
        if before != after:
            self.page.undo_stack.push(ApplyTranslationSnapshotCommand(
                self.project, before, after, list(self._result.suggestions), label="采用 AI 译文"))
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
