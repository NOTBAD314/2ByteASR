"""「排查原因」: why a recognition task failed or came out poorly (2026-10-23).

User request: the completion page says *what* went wrong ("字幕保真检查未通过")
but not *why*, so the developer answered each user by hand. This window shows

* 本地检查 — ``recognition.run_diagnosis`` matched against the known-problem
  catalog: the likely causes, how sure, the report lines that show it, what to
  do, and buttons into the existing settings / workshop / retry entries.
  Nothing is sent anywhere for this part.
* AI 分析 — on request only: a redacted digest of the report plus the
  program's own knowledge go to the text AI the user configured (the 字幕校对
  service, the same key AI 断句 / AI 校对 use). The answer streams in and can be
  stopped. Without a key the panel explains why a key helps and offers setup.
* 复制排查报告 / 保存… — a short redacted text for sending to the developer.

Buttons that leave the window close it and set ``chosen_action``; the main
window carries the action out (``open_run_diagnosis``) and, for the AI key
setup, reopens this window afterwards.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QPoint, QRect, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from ..design.main_ui_dialogs import SpringDialog
from ..i18n import bind_text, current_language, tr, translate
from ..i18n_widgets import user_text
from ..recognition.diagnosis_catalog import ACTION_LABELS
from ..recognition.run_diagnosis import CONFIDENCE_LABELS, SEVERITY_LABELS

SEVERITY_TONES = {"blocker": "danger", "problem": "warn", "quality": "info", "tip": "accent"}
# Actions that only make sense on the completion page of this very task.
TASK_ACTIONS = {"retry", "recover", "studio", "glossary_proofread", "mosi_resplit"}
AI_STAGE = "polish"  # the 字幕校对 service: the one key AI 断句 / 校对 / 翻译 share


def _tones(theme):
    return {
        "danger": (theme.danger, theme.danger_soft),
        "warn": (theme.warning, theme.warning_soft),
        "info": (theme.info, theme.info_soft),
        "accent": (theme.accent, theme.accent_soft),
        "ok": (theme.success, theme.success_soft),
        "muted": (theme.text_muted, theme.panel),
    }


def diagnosis_qss(theme) -> str:
    from ..design.typography import MONO_FONT_STACK
    tones = _tones(theme)
    rules = [
        f"QDialog#runDiagnosis {{ background: {theme.surface}; }}",
        f"QLabel#diagTitle {{ color: {theme.text}; font-size: 20px; font-weight: 700; }}",
        f"QLabel#diagSubtitle, QLabel#diagMuted {{ color: {theme.text_muted}; font-size: 13px; }}",
        f"QLabel#diagSection {{ color: {theme.text}; font-size: 15px; font-weight: 700; }}",
        f"QLabel#diagError {{ color: {theme.text_secondary}; font-size: 13px; background: {theme.panel};"
        f" border: 1px solid {theme.border}; border-radius: 8px; padding: 6px 10px; }}",
        f"QFrame#diagCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 12px; }}",
        f"QFrame#diagAiCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 12px; }}",
        f"QLabel#diagCardTitle {{ color: {theme.text}; font-size: 15px; font-weight: 700; }}",
        f"QLabel#diagBody {{ color: {theme.text_secondary}; font-size: 13px; }}",
        f"QLabel#diagAdvice {{ color: {theme.text}; font-size: 13px; }}",
        f"QLabel#diagFixed {{ color: {theme.success}; font-size: 12px; }}",
        f"QLabel#diagEvidence {{ color: {theme.text_secondary}; font-family: {MONO_FONT_STACK}; font-size: 12px;"
        f" background: {theme.panel}; border-radius: 8px; padding: 6px 8px; }}",
        f"QToolButton#diagEvidenceToggle {{ color: {theme.text_muted}; background: transparent; border: 0; font-size: 12px; padding: 0; }}",
        f"QToolButton#diagEvidenceToggle:hover {{ color: {theme.text}; }}",
        f"QTextBrowser#diagAiOutput {{ background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border};"
        f" border-radius: 10px; padding: 8px 10px; font-size: 14px; }}",
        f"QPlainTextEdit#diagSentPreview {{ background: {theme.panel}; color: {theme.text_secondary}; border: 1px solid {theme.border};"
        f" border-radius: 8px; font-family: {MONO_FONT_STACK}; font-size: 12px; }}",
        "QScrollArea#diagScroll { background: transparent; border: 0; }",
        "QWidget#diagScrollBody { background: transparent; }",
    ]
    for tone, (strong, soft) in tones.items():
        rules.append(f'QLabel#diagPill[tone="{tone}"] {{ color: {strong}; background: {soft}; border-radius: 9px;'
                     ' padding: 2px 8px; font-size: 12px; font-weight: 600; }')
        rules.append(f'QFrame#diagCard[tone="{tone}"] {{ border-left: 4px solid {strong}; }}')
    return "\n".join(rules)


class _FlowLayout(QLayout):
    """Buttons wrap to the next row instead of widening the card (English
    labels are about twice as wide as Chinese ones)."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items, self._spacing = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.sizeHint())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def _place(self, rect, *, apply):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


def _label(source="", name="diagBody", *, wrap=True, **arguments) -> QLabel:
    widget = QLabel()
    if source:
        bind_text(widget, source, **arguments)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _pill(source: str, tone: str) -> QLabel:
    pill = QLabel()
    bind_text(pill, source)
    pill.setObjectName("diagPill")
    pill.setProperty("tone", tone)
    pill.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return pill


class FindingCard(QFrame):
    """One local finding: what, why, this task's evidence, what to do, buttons."""

    action_clicked = Signal(str)

    def __init__(self, finding, *, available_actions=None, parent=None):
        super().__init__(parent)
        from ..design.presentation import button_role
        self.finding = finding
        issue = finding.issue
        self.setObjectName("diagCard")
        self.setProperty("tone", SEVERITY_TONES[finding.severity])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(7)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_pill(SEVERITY_LABELS[finding.severity], SEVERITY_TONES[finding.severity]))
        head.addWidget(_pill(CONFIDENCE_LABELS[finding.confidence], "muted"))
        title = _label(issue.title, "diagCardTitle")
        head.addWidget(title, 1)
        layout.addLayout(head)
        self.title_label = title
        self.specific_label = None
        if finding.specific:
            # Catalog values (language and model names) follow the UI language.
            arguments = {key: (tr(str(value)) if key in finding.translate_args else value)
                         for key, value in finding.specific_args.items()}
            self.specific_label = _label(finding.specific, "diagAdvice", **arguments)
            layout.addWidget(self.specific_label)
        self.cause_label = _label(issue.cause, "diagBody")
        layout.addWidget(self.cause_label)
        self.advice_label = _label(tr("怎么做：{advice}", advice=tr(issue.advice)), "diagAdvice")
        layout.addWidget(self.advice_label)
        if issue.fixed:
            layout.addWidget(_label(tr("修正情况：{fixed}", fixed=tr(issue.fixed)), "diagFixed"))
        self.evidence_label = None
        if finding.evidence:
            self.evidence_toggle = QToolButton()
            self.evidence_toggle.setObjectName("diagEvidenceToggle")
            self.evidence_toggle.setCheckable(True)
            self.evidence_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self._evidence_count = len(finding.evidence)
            self._sync_evidence_toggle(False)
            self.evidence_label = user_text(QLabel("\n".join(finding.evidence)))
            self.evidence_label.setObjectName("diagEvidence")
            self.evidence_label.setWordWrap(True)
            self.evidence_label.setTextFormat(Qt.TextFormat.PlainText)
            self.evidence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.evidence_label.hide()
            self.evidence_toggle.toggled.connect(self._toggle_evidence)
            layout.addWidget(self.evidence_toggle, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(self.evidence_label)
        actions = [action for action in issue.actions
                   if available_actions is None or action in available_actions]
        self.action_buttons = {}
        if actions:
            holder = QWidget()
            holder.setObjectName("diagActions")
            row = _FlowLayout(holder, spacing=8)
            for index, action in enumerate(actions):
                button = button_role(QPushButton(), "primary" if index == 0 and finding.severity != "tip" else "secondary",
                                     size="compact")
                bind_text(button, ACTION_LABELS[action])
                button.setObjectName(f"diagAction_{action}")
                button.clicked.connect(lambda _checked=False, value=action: self.action_clicked.emit(value))
                row.addWidget(button)
                self.action_buttons[action] = button
            layout.addWidget(holder)

    def _sync_evidence_toggle(self, shown: bool) -> None:
        if shown:
            bind_text(self.evidence_toggle, "收起依据 ▾")
        else:
            bind_text(self.evidence_toggle, "查看这次的依据（{count} 条）▸", count=self._evidence_count)

    def _toggle_evidence(self, shown: bool) -> None:
        self.evidence_label.setVisible(shown)
        self._sync_evidence_toggle(shown)


class DiagnosisAiWorker(QThread):
    """One AI analysis request; deltas arrive on the GUI thread through signals."""

    delta = Signal(str)
    restarted = Signal()
    finished_ok = Signal(str)
    failed = Signal(str, str)

    def __init__(self, settings: dict, messages: list[dict], parent=None):
        super().__init__(parent)
        self._settings = settings
        self._messages = messages

    def run(self):  # noqa: D401 - QThread override
        from ..providers.ai_providers import AIProviderError, provider_for_stage

        def on_event(kind, detail):
            if kind == "delta" and detail:
                self.delta.emit(str(detail))
            elif kind == "request_identity":
                try:
                    attempt = int(json.loads(str(detail)).get("attempt") or 1)
                except (TypeError, ValueError, AttributeError):
                    attempt = 1
                if attempt > 1:
                    self.restarted.emit()
        try:
            provider = provider_for_stage(self._settings, AI_STAGE)
            text = provider.complete(
                self._messages, max_tokens=2000, temperature=0.2, timeout=(15, 180),
                cancel_check=self.isInterruptionRequested, stage="recognition_diagnosis",
                on_stream_event=on_event, enable_thinking=False, operation_kind="general",
            )
        except AIProviderError as exc:
            self.failed.emit(" ".join(str(exc).split())[:400], str(getattr(exc, "category", "") or ""))
        except Exception as exc:  # any provider surprise ends as a readable failure
            self.failed.emit(" ".join(f"{type(exc).__name__}: {exc}".split())[:400], "error")
        else:
            self.finished_ok.emit(str(text or ""))


# A worker outlives a closed window until its request returns.
_LIVE_WORKERS: set[DiagnosisAiWorker] = set()


class AiAnalysisPanel(QFrame):
    """The AI part: ready → button + streamed answer; no key → why and setup."""

    action_clicked = Signal(str)
    started = Signal()

    def __init__(self, *, settings: dict | None, messages_factory, sent_preview: str, parent=None):
        super().__init__(parent)
        from ..design.presentation import button_role
        self.setObjectName("diagAiCard")
        self._settings = settings
        self._messages_factory = messages_factory
        self._worker: DiagnosisAiWorker | None = None
        self._generation = 0
        self._text = ""
        self.answer = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        layout.addWidget(_label(tr("AI 分析"), "diagSection"))
        ready, service, gate = self._readiness(settings)
        self.ready = ready
        if not ready:
            layout.addWidget(_label(tr(
                "还没有设置文字 AI 的 API Key。设置后可以让 AI 结合软件说明读这次的报告找原因；"
                "AI 断句和 AI 校对也用同一个 Key，字幕断句和错字会好很多。"), "diagBody"))
            row = QHBoxLayout()
            row.setSpacing(8)
            self.setup_button = button_role(QPushButton(), "primary", size="compact")
            bind_text(self.setup_button, "设置 API Key…")
            self.setup_button.setObjectName("diagAiSetup")
            self.setup_button.clicked.connect(lambda: self.action_clicked.emit("ai_settings"))
            row.addWidget(self.setup_button)
            self.help_button = button_role(QPushButton(), "secondary", size="compact")
            bind_text(self.help_button, "API Key 是什么？")
            self.help_button.setObjectName("diagAiHelp")
            self.help_button.clicked.connect(lambda: self.action_clicked.emit("api_key_help"))
            row.addWidget(self.help_button)
            row.addStretch(1)
            layout.addLayout(row)
            self.run_button = self.stop_button = self.output = self.status = None
            return
        self.intro = _label(tr("点下面的按钮，把精简后的任务报告（{size}，已隐藏密钥和个人路径）和软件说明发给 {service}，"
                               "让 AI 找原因。只在你点了之后才发送。",
                               size=_size_text(len(sent_preview)), service=service), "diagBody")
        layout.addWidget(self.intro)
        if gate == "failed":
            layout.addWidget(_label(tr("上次「测试连接」没有通过，这次可能也会失败。"), "diagMuted"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.run_button = button_role(QPushButton(), "primary", size="compact")
        bind_text(self.run_button, "让 AI 分析")
        self.run_button.setObjectName("diagAiRun")
        self.run_button.clicked.connect(self.start)
        row.addWidget(self.run_button)
        self.stop_button = button_role(QPushButton(), "secondary", size="compact")
        bind_text(self.stop_button, "停止")
        self.stop_button.setObjectName("diagAiStop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        row.addWidget(self.stop_button)
        self.preview_toggle = QToolButton()
        self.preview_toggle.setObjectName("diagEvidenceToggle")
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.preview_toggle, "查看要发送的内容 ▸")
        row.addWidget(self.preview_toggle)
        row.addStretch(1)
        layout.addLayout(row)
        self.preview = user_text(QPlainTextEdit())
        self.preview.setObjectName("diagSentPreview")
        self.preview.setReadOnly(True)
        self.preview.setPlainText(sent_preview)
        self.preview.setMinimumHeight(160)
        self.preview.hide()
        self.preview_toggle.toggled.connect(self._toggle_preview)
        layout.addWidget(self.preview)
        self.status = _label("", "diagMuted")
        self.status.hide()
        layout.addWidget(self.status)
        self.output = user_text(QTextBrowser())
        self.output.setObjectName("diagAiOutput")
        self.output.setOpenExternalLinks(False)
        self.output.setMinimumHeight(180)
        self.output.hide()
        layout.addWidget(self.output)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render)

    @staticmethod
    def _readiness(settings):
        """(ready, service label, connection gate) without any request."""
        if settings is None:
            return False, "", "no_key"
        try:
            from ..providers.llm_config import effective_ai_identity, text_ai_key_missing
            if text_ai_key_missing(settings, AI_STAGE):
                return False, "", "no_key"
            identity = effective_ai_identity(settings, AI_STAGE)
            service = " · ".join(str(part) for part in (identity.get("label") or identity.get("service")
                                                          or identity.get("provider"), identity.get("model")) if part)
        except Exception:
            return False, "", "no_key"
        try:
            from ..providers.ai_connection_record import feature_gate
            gate = feature_gate(settings)
        except Exception:
            gate = ""
        return True, service or str(tr("你设置的 AI")), gate

    def _toggle_preview(self, shown: bool) -> None:
        self.preview.setVisible(shown)
        if shown:
            bind_text(self.preview_toggle, "收起要发送的内容 ▾")
        else:
            bind_text(self.preview_toggle, "查看要发送的内容 ▸")

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> None:
        if self._worker is not None or not self.ready:
            return
        self._generation += 1
        generation = self._generation
        self._text = ""
        self.answer = ""
        self.output.clear()
        self.output.show()
        self.status.show()
        bind_text(self.status, "正在分析…（通常 10–60 秒）")
        self.run_button.setEnabled(False)
        self.stop_button.show()
        worker = DiagnosisAiWorker(self._settings, self._messages_factory())
        self._worker = worker
        _LIVE_WORKERS.add(worker)
        worker.delta.connect(lambda text, g=generation: self._on_delta(g, text))
        worker.restarted.connect(lambda g=generation: self._on_restart(g))
        worker.finished_ok.connect(lambda text, g=generation: self._on_done(g, text))
        worker.failed.connect(lambda message, category, g=generation: self._on_failed(g, message, category))
        worker.finished.connect(lambda w=worker: (_LIVE_WORKERS.discard(w), w.deleteLater()))
        worker.start()
        self.started.emit()

    def stop(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.requestInterruption()
        self._generation += 1  # a late answer is dropped
        self._worker = None
        self.run_button.setEnabled(True)
        bind_text(self.run_button, "重新分析")
        self.stop_button.hide()
        bind_text(self.status, "已停止。")
        self.answer = self._text

    def _alive(self, generation: int) -> bool:
        from shiboken6 import isValid
        return isValid(self) and generation == self._generation

    def _on_delta(self, generation: int, text: str) -> None:
        if not self._alive(generation):
            return
        self._text += text
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _on_restart(self, generation: int) -> None:
        if self._alive(generation):
            self._text = ""
            bind_text(self.status, "第一次请求没有成功，正在重试…")

    def _render(self) -> None:
        bar = self.output.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.output.setMarkdown(self._text)
        if at_end:
            bar.setValue(bar.maximum())

    def _finish(self) -> None:
        self._worker = None
        self.run_button.setEnabled(True)
        bind_text(self.run_button, "重新分析")
        self.stop_button.hide()

    def _on_done(self, generation: int, text: str) -> None:
        if not self._alive(generation):
            return
        self._finish()
        # Streaming and non-streaming transports both end here with the full text.
        self._text = text if text.strip() else self._text
        self.answer = self._text
        self._render_timer.stop()
        self._render()
        if self.answer.strip():
            bind_text(self.status, "AI 分析完成。AI 也可能出错，请结合上面的本地检查判断。")
        else:
            bind_text(self.status, "AI 没有返回内容，可以重新分析。")

    def _on_failed(self, generation: int, message: str, category: str) -> None:
        if not self._alive(generation):
            return
        self._finish()
        self.answer = self._text
        if category == "cancelled":
            bind_text(self.status, "已停止。")
            return
        hint = {
            "auth_error": "API Key 不对或已失效，请在 AI 设置里重新填写并测试连接。",
            "auth_config": "API Key 不对或已失效，请在 AI 设置里重新填写并测试连接。",
            "quota_exhausted": "AI 服务的余额或额度不足，请到服务商那里充值。",
            "rate_limited": "AI 服务暂时太忙，请稍后重新分析。",
            "timeout": "AI 服务太久没有回应，请稍后重新分析。",
            "request_too_large": "这次的报告对这个 AI 模型太大了，可以换一个上下文更长的模型。",
        }.get(category, "")
        if hint:
            bind_text(self.status, "AI 分析失败：{hint}", hint=tr(hint))
        else:
            bind_text(self.status, "AI 分析失败：{reason}", reason=message)

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._generation += 1
            self._worker = None


def _size_text(characters: int) -> str:
    kib = max(1, round(characters * 1.5 / 1024))  # Chinese text ~ 3 bytes, JSON mostly 1
    return f"≈{kib} KB"


class RunDiagnosisDialog(SpringDialog):
    """``chosen_action`` after closing: an ACTION_LABELS key, 'api_key_help' or ''."""

    def __init__(self, diagnosis, *, task_name: str = "", item_error: str = "", settings: dict | None = None,
                 app_version: str = "", available_actions=None, parent=None):
        super().__init__(parent)
        from ..design.presentation import button_role, glyph_button
        from ..recognition.diagnosis_prompt import build_request
        self.setObjectName("runDiagnosis")
        self.diagnosis = diagnosis
        self.task_name = task_name
        self.item_error = item_error
        self.app_version = app_version
        self.chosen_action = ""
        bind_text(self, "排查原因", property="windowTitle")
        self.refresh_theme_palette()
        self.setMinimumWidth(640)
        self.resize(780, 720)

        facts = diagnosis.facts
        from ..i18n import LANGUAGE_NATIVE_NAMES
        language_name = LANGUAGE_NATIVE_NAMES.get(current_language(), "简体中文")
        # Built once: what 「查看要发送的内容」 shows is exactly what is sent.
        request, self._digest = build_request(diagnosis, language_name=language_name, app_version=app_version,
                                              item_error=item_error, environment=_environment(app_version))

        def messages():
            return [dict(message) for message in request]
        self._messages = messages

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 18, 18)
        outer.setSpacing(12)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(_label(tr("排查原因"), "diagTitle"))
        subtitle = QLabel(task_name)
        user_text(subtitle)
        subtitle.setObjectName("diagSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        close = glyph_button(button_role(QPushButton("×"), "ghost"))
        bind_text(close, "关闭", property="accessibleName")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("diagScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("diagScrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.scroll = scroll

        outcome = facts.outcome
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        if outcome is not None:
            tone = ("danger" if outcome.core_status == "failed" else
                    "muted" if outcome.core_status == "cancelled" else
                    "warn" if outcome.core_status in {"partial", "unknown"} or outcome.has_review else "ok")
            status_row.addWidget(_pill(outcome.title, tone))
        stats = _label(tr("{cues} 条字幕 · 有效音频 {minutes} 分钟", cues=facts.cue_count,
                          minutes=f"{facts.audio_seconds / 60:.1f}"), "diagMuted", wrap=False)
        status_row.addWidget(stats)
        status_row.addStretch(1)
        layout.addLayout(status_row)
        if facts.errors:
            error = user_text(QLabel(" ".join(facts.errors[0].split())[:600]))
            error.setObjectName("diagError")
            error.setWordWrap(True)
            error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(error)
            self.error_label = error

        layout.addWidget(_label(tr("本地检查"), "diagSection"))
        if diagnosis.findings:
            layout.addWidget(_label(tr("按已知问题清单核对了这次的任务报告，找到 {count} 个可能原因（最可能的在最上面）。这一步不发送任何内容。",
                                       count=len(diagnosis.findings)), "diagMuted"))
        else:
            layout.addWidget(_label(tr("按已知问题清单核对了这次的任务报告，没有发现已知问题。如果字幕仍然不对，可以让 AI 再看一遍，"
                                       "或者用「回报问题」把情况发给开发者。"), "diagMuted"))
        self.cards: list[FindingCard] = []
        for finding in diagnosis.findings:
            card = FindingCard(finding, available_actions=available_actions)
            card.action_clicked.connect(self._choose)
            layout.addWidget(card)
            self.cards.append(card)

        self.ai_panel = AiAnalysisPanel(settings=settings, messages_factory=messages,
                                        sent_preview=self._digest)
        self.ai_panel.action_clicked.connect(self._choose)
        # The answer appears at the bottom: bring it into view once asked for.
        self.ai_panel.started.connect(lambda: QTimer.singleShot(
            60, lambda: _valid(self.scroll) and self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum())))
        layout.addWidget(self.ai_panel)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.copy_button = button_role(QPushButton(), "secondary")
        bind_text(self.copy_button, "复制排查报告")
        bind_text(self.copy_button, "复制本地检查和 AI 分析的结果（已隐藏密钥与个人路径），可以直接发给开发者",
                  property="toolTip")
        self.copy_button.setObjectName("diagCopy")
        self.copy_button.clicked.connect(self._copy)
        footer.addWidget(self.copy_button)
        self.save_button = button_role(QPushButton(), "secondary")
        bind_text(self.save_button, "保存为文件…")
        self.save_button.setObjectName("diagSave")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)
        self.copy_note = _label("", "diagMuted", wrap=False)
        footer.addWidget(self.copy_note)
        footer.addStretch(1)
        self.close_button = button_role(QPushButton(), "primary")
        bind_text(self.close_button, "关闭")
        self.close_button.setObjectName("diagClose")
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        outer.addLayout(footer)

    def refresh_theme_palette(self) -> None:
        """The shared dialog sheet (buttons, scroll bars) plus this window's own rules."""
        super().refresh_theme_palette()
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.setStyleSheet(self.styleSheet() + "\n" + diagnosis_qss(theme_definition(theme_key())))

    def report_text(self) -> str:
        from ..recognition.diagnosis_prompt import plain_report
        return plain_report(self.diagnosis, language=current_language(), task_name=self.task_name,
                            ai_answer=self.ai_panel.answer, app_version=self.app_version)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.report_text())
        bind_text(self.copy_note, "已复制")
        QTimer.singleShot(2500, lambda: self.copy_note.setText("") if _valid(self.copy_note) else None)

    def _save(self) -> None:
        from pathlib import Path
        stem = Path(self.task_name).stem if self.task_name else "2ByteASR"
        path, _filter = QFileDialog.getSaveFileName(self, translate("保存排查报告", current_language()),
                                                    f"{stem}_排查报告.txt", "Text (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.report_text(), encoding="utf-8")
        except OSError as exc:
            bind_text(self.copy_note, "保存失败：{reason}", reason=str(exc)[:120])
        else:
            bind_text(self.copy_note, "已保存")

    def _choose(self, action: str) -> None:
        self.chosen_action = action
        self.accept()

    def done(self, result):  # noqa: D401 - Qt override
        self.ai_panel.shutdown()
        super().done(result)


def _valid(widget) -> bool:
    from shiboken6 import isValid
    return isValid(widget)


def _environment(app_version: str) -> dict:
    """The program and computer *now* (the report may come from an older run)."""
    import platform
    info = {"program_version": app_version, "system": f"{platform.system()} {platform.release()} {platform.machine()}"}
    try:
        from ..recognition.recognition_choices import host_profile
        host = host_profile()
        info["nvidia_tool"] = bool(host.nvidia_tool)
    except Exception:
        pass
    return info


MAX_REPORT_BYTES = 12 * 1024 * 1024


def locate_task_report(media_path: str, job_id: str) -> dict | None:
    """The report of a failed or cancelled task, whose MediaResult carries no
    report path: ``<stem>__<job_id>_<n>_字幕任务报告.json`` for this media."""
    import os
    from pathlib import Path
    from ..recognition.reporting import REPORT_ROOT
    if not media_path or not job_id:
        return None
    stem = Path(media_path).stem
    try:
        candidates = sorted(Path(REPORT_ROOT).glob(f"{_glob_escape(stem)}__{_glob_escape(job_id)}_*_字幕任务报告.json"))
    except OSError:
        return None
    wanted = os.path.normcase(os.path.abspath(media_path))
    for path in candidates:
        try:
            if path.stat().st_size > MAX_REPORT_BYTES:
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        media = payload.get("media") if isinstance(payload, dict) else None
        recorded = str((media or {}).get("path") or "")
        if not recorded or os.path.normcase(os.path.abspath(recorded)) == wanted:
            return payload
    return None


def _glob_escape(text: str) -> str:
    from glob import escape
    return escape(str(text))


def current_app_version() -> str:
    try:
        from ..diagnostics.build_identity import load_build_identity
        return str(load_build_identity().app_version or "")
    except Exception:
        return ""


def open_run_diagnosis(window, report: dict, *, item_error: str = "", task_name: str = "",
                       available_actions=None) -> str:
    """Diagnose ``report`` over ``window`` and carry out the chosen action."""
    import copy
    from ..recognition.run_diagnosis import DiagnosisInput, diagnose_run
    settings = None
    legacy = getattr(window, "legacy", None)
    if legacy is not None and isinstance(getattr(legacy, "RUNTIME_SETTINGS", None), dict):
        settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    ai_ready = None
    if settings is not None:
        ready, _service, _gate = AiAnalysisPanel._readiness(settings)
        ai_ready = ready
    version = current_app_version()
    diagnosis = diagnose_run(DiagnosisInput(report=report, item_error=item_error, ai_ready=ai_ready,
                                            app_version=version))
    dialog = RunDiagnosisDialog(diagnosis, task_name=task_name, item_error=item_error, settings=settings,
                                app_version=version, available_actions=available_actions, parent=window)
    window._run_diagnosis_dialog = dialog
    dialog.exec()
    action = dialog.chosen_action
    window._run_diagnosis_dialog = None
    dialog.deleteLater()
    if action:
        reopen = lambda: open_run_diagnosis(window, report, item_error=item_error, task_name=task_name,
                                            available_actions=available_actions)
        run_diagnosis_action(window, action, reopen=reopen)
    return action


def run_diagnosis_action(window, action: str, *, reopen=None) -> bool:
    """Carry out one finding button through the window's existing entries."""
    def call(name, *args, **kwargs):
        method = getattr(window, name, None)
        if method is None:
            return False
        method(*args, **kwargs)
        return True

    if action == "ai_settings":
        # Back to this window after the AI settings close, now able to ask the AI.
        if hasattr(window, "_open_ai_settings_dialog"):
            window._open_ai_settings_dialog(on_finished=(lambda: QTimer.singleShot(0, reopen)) if reopen else None)
            return True
        return call("_open_ai_provider_config")
    if action == "api_key_help":
        from .api_key_explainer import open_api_key_explainer
        choice = open_api_key_explainer(window)
        if reopen is not None and choice != "setup":
            QTimer.singleShot(0, reopen)
        return True
    pickers = {"pick_primary": "primary", "pick_timeline": "timeline", "pick_review": "review"}
    if action in pickers:
        return call("_open_model_picker", pickers[action])
    if action == "choose_plan":
        return call("_next_step_action", "choose_plan")
    targets = {
        "cloud_asr_setup": "_open_api_setup_guide", "model_workshop": "_open_model_workshop",
        "retry": "_retry_failed_items", "recover": "_recover_recognition_output",
        "mosi_resplit": "_resplit_blocked_cloud_segments",
        "glossary_proofread": "_open_glossary_proofread", "studio": "_open_studio_from_result",
        "update": "_check_updates", "support": "_open_support",
    }
    name = targets.get(action)
    return call(name) if name else False


def diagnosis_strings() -> tuple[str, ...]:
    """Every 排查原因 string that is not a literal tr()/bind_text() argument
    (catalog, labels, task-specific sentences, the plain report, AI hints);
    the localization test checks these like the literal ones."""
    from ..recognition.diagnosis_catalog import catalog_strings
    from ..recognition.diagnosis_checks import SPECIFIC_TEMPLATES, TRANSLATED_NAMES
    from ..recognition.diagnosis_prompt import REPORT_STRINGS
    return tuple(dict.fromkeys(catalog_strings() + SPECIFIC_TEMPLATES + TRANSLATED_NAMES + REPORT_STRINGS
                               + tuple(SEVERITY_LABELS.values()) + tuple(CONFIDENCE_LABELS.values()) + (
        "API Key 不对或已失效，请在 AI 设置里重新填写并测试连接。",
        "AI 服务的余额或额度不足，请到服务商那里充值。",
        "AI 服务暂时太忙，请稍后重新分析。",
        "AI 服务太久没有回应，请稍后重新分析。",
        "这次的报告对这个 AI 模型太大了，可以换一个上下文更长的模型。",
        "你设置的 AI", "保存排查报告",
    )))
