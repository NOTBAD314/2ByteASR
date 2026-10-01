"""AI subtitle translation dialog (bilingual workflow).

Triggered from the toolbar bilingual button's menu: choose a target language
and the configured AI service translates every cue into
``generation_metadata["translations"][cue_id]`` in batches, then enables the
bilingual display so the translation shows side-by-side with the original.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .i18n import bind_text

_TARGET_LANGUAGES = (
    ("英语", "English"),
    ("日语", "Japanese"),
    ("韩语", "Korean"),
    ("繁体中文", "Traditional Chinese"),
    ("西班牙语", "Spanish"),
    ("法语", "French"),
)

_BATCH_SIZE = 20


class TranslationWorker(threading.Thread):
    """Batch-translate cues off the UI thread."""

    def __init__(
        self,
        provider: Any,
        cues: list,
        language_label: str,
        language_name: str,
        on_progress: Callable[[int, int, str], None],
        on_done: Callable[[bool, str, dict], None],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True, name="subtitle-translate")
        self._provider = provider
        self._cues = cues
        self._language_label = language_label
        self._language_name = language_name
        self._on_progress = on_progress
        self._on_done = on_done
        self._cancel = cancel_event

    def run(self) -> None:
        results: dict[str, str] = {}
        total = len(self._cues)
        done = 0
        try:
            for start in range(0, total, _BATCH_SIZE):
                if self._cancel.is_set():
                    self._on_done(False, "已取消", results)
                    return
                batch = self._cues[start:start + _BATCH_SIZE]
                lines = "\n".join(
                    f'{index + 1}. {cue.text}' for index, cue in enumerate(batch)
                )
                prompt = (
                    f"把以下游戏视频字幕逐条翻译成{self._language_label}（{self._language_name}）。"
                    "保持口语与游戏语境，简短有力，不添加解释。"
                    "只输出 JSON 对象，键为行号字符串，值为译文。\n\n" + lines
                )
                response = self._provider.complete(
                    [
                        {"role": "system", "content": "你是专业的游戏字幕翻译引擎，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4096,
                    temperature=0.3,
                    timeout=180.0,
                )
                payload = json.loads(self._extract_json(response))
                if not isinstance(payload, Mapping):
                    raise ValueError("翻译结果不是 JSON 对象")
                for index, cue in enumerate(batch):
                    value = payload.get(str(index + 1), payload.get(index + 1))
                    if value is not None and str(value).strip():
                        results[cue.id] = str(value).strip()
                done += len(batch)
                self._on_progress(done, total, f"已翻译 {done}/{total}")
            self._on_done(True, f"完成：{len(results)}/{total} 条", results)
        except Exception as exc:  # noqa: BLE001 - report, keep partial results
            self._on_done(
                bool(results), f"{type(exc).__name__}: {exc}"[:200], results,
            )

    @staticmethod
    def _extract_json(text: str) -> str:
        source = str(text or "").strip()
        if source.startswith("```"):
            lines = source.splitlines()
            if lines and lines[0].strip().casefold() in {"```", "```json"}:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            source = "\n".join(lines).strip()
        start = source.find("{")
        end = source.rfind("}")
        if start >= 0 and end > start:
            return source[start:end + 1]
        return source


class SubtitleTranslationDialog(QDialog):
    """Choose language + AI service, translate all cues, enable bilingual."""

    translation_finished = Signal(bool, dict)

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        bind_text(self, 'AI 字幕翻译（双语对照）', property='windowTitle')
        self.setMinimumWidth(460)
        self.page = page
        self._worker: TranslationWorker | None = None
        self._cancel_event = threading.Event()

        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        form.addWidget(QLabel("目标语言"))
        self.language = QComboBox()
        for label, _name in _TARGET_LANGUAGES:
            self.language.addItem(label, label)
        form.addWidget(self.language, 1)
        layout.addLayout(form)

        from .ai_providers import provider_for_stage
        from .studio_ai import GLOBAL_PROVIDER_REGISTRY

        settings = GLOBAL_PROVIDER_REGISTRY.settings()
        try:
            provider = provider_for_stage(settings, "polish")
            provider_desc = f"{getattr(provider, 'provider_id', '') or ''} · {getattr(provider, 'model', '') or '默认模型'}"
        except Exception:
            provider = None
            provider_desc = "未配置（请先在设置中配置 AI 服务）"
        self._provider = provider
        service_row = QHBoxLayout()
        service_row.addWidget(QLabel("AI 服务"))
        self.service_label = QLabel(provider_desc)
        self.service_label.setObjectName("contextMeta")
        service_row.addWidget(self.service_label, 1)
        layout.addLayout(service_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)
        self.status = QLabel("将翻译当前工程的全部字幕并写入双语对照。")
        self.status.setObjectName("contextMeta")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("开始翻译")
        self.start_button.setObjectName("studioPrimary")
        self.start_button.clicked.connect(self._start)
        buttons.addWidget(self.start_button)
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("studioButton")
        self.close_button.clicked.connect(self._close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.start_button.setEnabled(self._provider is not None)
        # Worker thread results hop back through queued signal connections.
        self.translation_progress.connect(self._apply_progress, Qt.ConnectionType.QueuedConnection)
        self.translation_done.connect(self._apply_done, Qt.ConnectionType.QueuedConnection)

    def _start(self) -> None:
        project = getattr(self.page, "project", None)
        if project is None or not project.cues or self._provider is None:
            return
        language_label = str(self.language.currentData() or "英语")
        language_name = dict(_TARGET_LANGUAGES).get(language_label, language_label)
        cues = [cue for cue in project.cues if cue.text]
        self.start_button.setEnabled(False)
        self.progress.setValue(1)
        self._cancel_event = threading.Event()
        self._worker = TranslationWorker(
            self._provider,
            cues,
            language_label,
            language_name,
            on_progress=self._on_progress,
            on_done=self._on_done,
            cancel_event=self._cancel_event,
        )
        self._worker.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        # Worker thread → marshal via signal-free queued invoke through the
        # dialog's own signal below.
        self.translation_progress.emit(done, total, message)

    translation_progress = Signal(int, int, str)
    translation_done = Signal(bool, str, dict)

    def _on_done(self, ok: bool, message: str, results: dict) -> None:
        self.translation_done.emit(ok, message, results)

    def _apply_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setValue(max(1, int(100 * done / max(1, total))))
        self.status.setText(message)

    def _apply_done(self, ok: bool, message: str, results: dict) -> None:
        self.start_button.setEnabled(True)
        self.progress.setValue(100 if ok else self.progress.value())
        self.status.setText(message)
        self.log.appendPlainText(message)
        if results:
            project = self.page.project
            metadata = dict(project.generation_metadata or {})
            translations = dict(metadata.get("translations", {}) or {})
            translations.update(results)
            metadata["translations"] = translations
            project.generation_metadata = metadata
            try:
                self.page._changed = True
                self.page._update_changed_marker()
            except Exception:
                pass
            # Refresh the bilingual editor for the currently selected cue.
            try:
                selected = str(getattr(self.page.session, "selected_cue_id", "") or "")
                if selected:
                    self.page.cue_controller.select_cue(selected)
            except Exception:
                pass
            self.translation_finished.emit(ok, results)

    def _close(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._cancel_event.set()
        self.reject()
