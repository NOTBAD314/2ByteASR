"""The diagnosis card of the recognition-history details view (2026-11-11).

Shape (details design A): AI 诊断 header → 结论 block with 把握度 → 为什么这么
判断 | 关键日志 → 按这个顺序解决 (each step with its button) → 还是不行？.
It opens filled from the local check; 「让 AI 分析」 sends the 排查原因 request
(redacted digest + program knowledge) to the user's own text AI and refills
the same card from its JSON answer. A non-JSON answer is shown as text.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..i18n import bind_text, current_language, tr, translate
from ..i18n_widgets import user_text
from .diagnosis_catalog import ACTION_LABELS
from .history_diagnosis import (ANALYSE_ACTION, RESUME_ACTION, DiagnosisView, ai_view, local_view,
                                structured_messages, view_text)
from ..design.typography import weighted_font

AI_STAGE = "polish"


def _label(text: str = "", name: str = "historyDiagBody", *, wrap: bool = True, translated: bool = False) -> QLabel:
    label = QLabel()
    if translated:
        user_text(label)
        label.setText(str(text))
    elif text:
        bind_text(label, text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    if wrap:
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


_ERROR_LINE = None
_PATH = None


def key_log_lines(lines, limit: int = 4) -> list[tuple[str, bool]]:
    """The failing part of each log line (2026-11-12, user): folder paths
    dropped, a line cut into clauses, advice left out; only clauses that
    name the failure are marked, with at most one clause of context."""
    import re
    global _ERROR_LINE, _PATH
    if _ERROR_LINE is None:
        _ERROR_LINE = re.compile(r"(?i)not installed|missing|denied|unauthori|forbidden|timed? ?out|\bfail(ed|ure)?\b|"
                                 r"\berror:|exception|traceback|\b(40[13]|429|5\d\d)\b|未安装|缺少|拒绝|超时|失败|无法")
        _PATH = re.compile(r"\(?[A-Za-z]:[\\/][^\s()（）;；,，]*\)?|\(?/(?:Users|home|private)/[^\s()（）;；,，]*\)?")
    advice = re.compile(r"^(请|可以|建议|please\b|try\b)", re.I)
    out: list[tuple[str, bool]] = []
    for line in lines:
        value = _PATH.sub("", " ".join(str(line).split()))
        value = re.sub(r"\s+([)）,，:：])", r"\1", " ".join(value.split())).strip()
        clauses = [part.strip(" ;；。：") for part in re.split(r"[;；。：]", value) if part.strip(" ;；。：")]
        clauses = [part for part in clauses if not advice.match(part)] or clauses
        failing = [part for part in clauses if _ERROR_LINE.search(part)]
        if not failing:
            out.append((value, False))
        else:
            first = clauses[0]
            if first not in failing:
                out.append((first, False))
            out.extend((part, True) for part in failing)
        if len(out) >= limit:
            break
    return out[:limit]


def log_html(lines) -> str:
    """Log lines as a table; lines that name the failure on a red band."""
    import html
    import re
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import blend_hex, theme_definition
    t = theme_definition(theme_key())
    base = getattr(t, "log_background", "") or t.media
    band = blend_hex(base, t.danger, 0.42)
    hot = blend_hex("#ffffff", t.danger, 0.12)
    rows = []
    for text, failing in key_log_lines(lines):
        text = html.escape(breakable(text))
        if failing:
            rows.append(f'<tr><td bgcolor="{band}" style="color:{hot}; padding:3px 6px;">{text}</td></tr>')
        else:
            rows.append(f'<tr><td style="padding:3px 6px;">{text}</td></tr>')
    return '<table width="100%" cellspacing="0" cellpadding="0">' + "".join(rows) + "</table>"


def breakable(text: str) -> str:
    """Let long paths wrap: a zero-width space after each separator."""
    return str(text).replace("\\", "\\\u200b").replace("/", "/\u200b")


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())
            item.layout().deleteLater()


def action_label(action: str) -> str:
    if action == RESUME_ACTION:
        return str(tr("重试未完成部分"))
    if action == ANALYSE_ACTION:
        return str(tr("让 AI 分析"))
    if action == "support":
        return str(tr("回报问题"))
    return str(translate(ACTION_LABELS.get(action, action), current_language())).rstrip("…")


class HistoryDiagnosisPanel(QFrame):
    """``action_requested(action)``: a step button (ACTION_LABELS key or 'resume')."""

    action_requested = Signal(str)

    def __init__(self, report: dict, *, item_error: str = "", task_name: str = "", settings: dict | None = None,
                 parent=None):
        super().__init__(parent)
        from ..app.run_diagnosis_dialog import AiAnalysisPanel, _environment, current_app_version
        from ..i18n import LANGUAGE_NATIVE_NAMES
        from .diagnosis_prompt import build_request
        from .run_diagnosis import DiagnosisInput, diagnose_run

        self.setObjectName("historyDiagnosis")
        self._settings = settings
        self._worker = None
        self._generation = 0
        self.answer = ""
        ready, service, _gate = AiAnalysisPanel._readiness(settings)
        self.ai_ready = ready
        from .recognition_history import short_service_name
        self.service = short_service_name(service) or service
        version = current_app_version()
        self.diagnosis = diagnose_run(DiagnosisInput(report=report, item_error=item_error, ai_ready=ready if settings else None,
                                                     app_version=version))
        language_name = LANGUAGE_NATIVE_NAMES.get(current_language(), "简体中文")
        self._request, self.digest = build_request(self.diagnosis, language_name=language_name, app_version=version,
                                                   item_error=item_error, environment=_environment(version))
        self.view = local_view(self.diagnosis, language=current_language())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label("AI 诊断", "historyDiagTitle", wrap=False))
        self.source_chip = _label("", "historyDiagSource", wrap=False)
        head.addWidget(self.source_chip)
        head.addStretch(1)
        self.service_label = _label("", "historyMuted", wrap=False)
        head.addWidget(self.service_label)
        self.copy_button = QPushButton()
        bind_text(self.copy_button, "复制分析")
        self.copy_button.setObjectName("historyRowButton")
        self.copy_button.clicked.connect(self._copy)
        head.addWidget(self.copy_button)
        layout.addLayout(head)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        layout.addWidget(self.content)

        self.cta = QFrame()
        self.cta.setObjectName("historyDiagCta")
        cta = QHBoxLayout(self.cta)
        cta.setContentsMargins(14, 12, 14, 12)
        cta.setSpacing(10)
        self.cta_text = _label("", "historyDiagBody")
        cta.addWidget(self.cta_text, 1)
        self.run_button = QPushButton()
        self.run_button.setObjectName("historyAiButton")
        self.run_button.clicked.connect(self.start)
        cta.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.stop_button = QPushButton()
        bind_text(self.stop_button, "停止")
        self.stop_button.setObjectName("historySecondary")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        cta.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.cta)
        self._render(self.view)
        self._update_cta()

    # ------------------------------------------------------------------ render
    def _render(self, view: DiagnosisView, raw_text: str = "") -> None:
        self.view = view
        _clear(self.content_layout)
        if view.source == "ai":
            bind_text(self.source_chip, "AI 分析")
            self.service_label.setText(self.service)
        else:
            bind_text(self.source_chip, "本地检查")
            bind_text(self.service_label, "按已知问题清单核对，没有发送任何内容")
        self.source_chip.setProperty("source", view.source)
        self.source_chip.style().unpolish(self.source_chip)
        self.source_chip.style().polish(self.source_chip)

        conclusion = QFrame()
        conclusion.setObjectName("historyDiagConclusion")
        box = QVBoxLayout(conclusion)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)
        box.addWidget(_label("结论", "historyDiagConclusionCaption", wrap=False))
        box.addWidget(_label(view.conclusion, "historyDiagConclusionText", translated=True))
        meter = QHBoxLayout()
        meter.setSpacing(10)
        meter.addWidget(_label(str(tr("把握度 {level}", level=str(tr(view.confidence_label)))), "historyDiagConfidence",
                               wrap=False, translated=True))
        track = QFrame()
        track.setObjectName("historyDiagMeterTrack")
        track.setFixedSize(160, 6)
        fill = QFrame(track)
        fill.setObjectName("historyDiagMeterFill")
        fill.setGeometry(0, 0, int(160 * view.confidence_percent / 100), 6)
        meter.addWidget(track, 0, Qt.AlignmentFlag.AlignVCenter)
        meter.addStretch(1)
        box.addLayout(meter)
        self.content_layout.addWidget(conclusion)

        if raw_text:
            text = _label(raw_text, "historyDiagBody", translated=True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.content_layout.addWidget(text)

        if view.reasons or view.log_lines:
            row = QHBoxLayout()
            row.setSpacing(12)
            if view.reasons:
                card = QFrame()
                card.setObjectName("historyDiagCard")
                card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                reasons = QVBoxLayout(card)
                reasons.setContentsMargins(14, 12, 14, 12)
                reasons.setSpacing(7)
                reasons.addWidget(_label("为什么这么判断", "historyCaption", wrap=False))
                for reason in view.reasons:
                    reasons.addWidget(_label("·  " + reason, "historyDiagBody", translated=True))
                reasons.addStretch(1)
                row.addWidget(card, 1)
            if view.log_lines:
                logs = QFrame()
                logs.setObjectName("historyDiagLogCard")
                logs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                log_box = QVBoxLayout(logs)
                log_box.setContentsMargins(0, 0, 0, 0)
                log_box.setSpacing(6)
                log_box.addWidget(_label("关键日志", "historyCaption", wrap=False))
                code = _label("", "historyDiagLog", translated=True)
                code.setTextFormat(Qt.TextFormat.RichText)
                code.setText(log_html(view.log_lines))
                code.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                log_box.addWidget(code, 1)
                row.addWidget(logs, 1)
            self.content_layout.addLayout(row)

        if view.steps:
            self.content_layout.addWidget(_label("按这个顺序解决", "historyCaption", wrap=False))
            for index, step in enumerate(view.steps, 1):
                self.content_layout.addWidget(self._step(index, step))

        if view.fallback:
            fallback = QFrame()
            fallback.setObjectName("historyDiagFallback")
            line = QHBoxLayout(fallback)
            line.setContentsMargins(14, 10, 12, 10)
            line.setSpacing(10)
            line.addWidget(_label("还是不行？", "historyDiagStrong", wrap=False))
            line.addWidget(_label(view.fallback, "historyMuted", translated=True), 1)
            support = QPushButton()
            bind_text(support, "回报问题")
            support.setObjectName("historyRowButton")
            support.clicked.connect(lambda: self.action_requested.emit("support"))
            line.addWidget(support, 0, Qt.AlignmentFlag.AlignVCenter)
            self.content_layout.addWidget(fallback)

    def _step(self, index: int, step) -> QFrame:
        frame = QFrame()
        frame.setObjectName("historyDiagStep")
        frame.setProperty("first", index == 1)
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 9, 10, 9)
        row.setSpacing(12)
        from .recognition_history import _ElideLabel, _RoundBadge
        number = _RoundBadge(28)
        number.setText(str(index))
        number.setObjectName("historyDiagStepNumber")
        number.setProperty("tone", "ai_first" if index == 1 else "ai")
        row.addWidget(number, 0, Qt.AlignmentFlag.AlignVCenter)
        # 2026-11-12 (user): each step on one line; long text ends in "…"
        # and is complete in the tooltip.
        title = _ElideLabel(step.title, "historyDiagStepTitle")
        title.setToolTip(step.title + (f"\n{step.detail}" if step.detail else ""))
        # Measured with the Heavy face the sheet applies later.
        from PySide6.QtGui import QFont, QFontMetrics
        from ..design.typography import SOURCE_HAN_FAMILY_ALIASES
        heavy = QFont(SOURCE_HAN_FAMILY_ALIASES[0])
        heavy.setPixelSize(15)
        weighted_font(heavy, QFont.Weight.ExtraBold)
        title_width = QFontMetrics(heavy).horizontalAdvance(step.title) + 16
        title.setMinimumWidth(min(title_width, 260 if step.detail else 440))
        title.setMaximumWidth(title_width)
        row.addWidget(title, 3 if step.detail else 1)
        if step.detail:
            detail = _ElideLabel(step.detail, "historyDiagStepDetail")
            detail.setToolTip(step.detail)
            row.addWidget(detail, 2)
        else:
            row.addStretch(1)
        if step.action:
            button = QPushButton(action_label(step.action))
            button.setObjectName("historyAiButton" if index == 1 else "historyRowButton")
            button.clicked.connect(lambda _checked=False, action=step.action: self._step_action(action))
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return frame

    def _step_action(self, action: str) -> None:
        if action == ANALYSE_ACTION:
            self.start()
        else:
            self.action_requested.emit(action)

    def _update_cta(self, status: str = "") -> None:
        running = self._worker is not None
        self.stop_button.setVisible(running)
        if not self.ai_ready:
            bind_text(self.cta_text, "还没有设置文字 AI 的 API Key。设置后可以让 AI 读这次的日志找原因（AI 断句和校对也用同一个 Key）。")
            bind_text(self.run_button, "设置 API Key")
            self.run_button.setEnabled(True)
            return
        if status:
            self.cta_text.setText(status)
        elif self.view.source == "ai":
            bind_text(self.cta_text, "AI 也可能出错，请结合本地检查和日志判断。")
        elif self.view.matched:
            bind_text(self.cta_text, "本地检查只按已知问题清单核对。可以让 {service} 读完整日志再判断一次（API Key 和个人路径会先隐藏）。",
                      service=self.service)
        else:
            bind_text(self.cta_text, "让 {service} 读这次的日志、配置和环境找原因（API Key 和个人路径会先隐藏）。",
                      service=self.service)
        bind_text(self.run_button, "重新分析" if self.view.source == "ai" else "让 AI 分析")
        self.run_button.setEnabled(not running)

    # ------------------------------------------------------------------ AI
    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> None:
        if not self.ai_ready:
            self.action_requested.emit("ai_settings")
            return
        if self._worker is not None:
            return
        from ..app.run_diagnosis_dialog import _LIVE_WORKERS, DiagnosisAiWorker
        self._generation += 1
        generation = self._generation
        self.answer = ""
        worker = DiagnosisAiWorker(self._settings, structured_messages(self._request))
        self._worker = worker
        _LIVE_WORKERS.add(worker)
        worker.restarted.connect(lambda g=generation: self._alive(g) and self._update_cta(str(tr("第一次请求没有成功，正在重试…"))))
        worker.finished_ok.connect(lambda text, g=generation: self._on_done(g, text))
        worker.failed.connect(lambda message, category, g=generation: self._on_failed(g, message, category))
        worker.finished.connect(lambda w=worker: (_LIVE_WORKERS.discard(w), w.deleteLater()))
        worker.start()
        self._update_cta(str(tr("正在分析…（通常 10–60 秒）")))

    def stop(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.requestInterruption()
        self._generation += 1
        self._worker = None
        self._update_cta(str(tr("已停止。")))

    def _alive(self, generation: int) -> bool:
        from shiboken6 import isValid
        return isValid(self) and generation == self._generation

    def _on_done(self, generation: int, text: str) -> None:
        if not self._alive(generation):
            return
        self._worker = None
        self.answer = str(text or "")
        view = ai_view(self.answer)
        if view is not None:
            self._render(view)
            self._update_cta()
        elif self.answer.strip():
            # Not JSON: keep the local card and show the answer as text under it.
            self._render(self.view, raw_text=self.answer.strip())
            self._update_cta(str(tr("AI 分析完成。AI 也可能出错，请结合本地检查判断。")))
        else:
            self._update_cta(str(tr("AI 没有返回内容，可以重新分析。")))

    def _on_failed(self, generation: int, message: str, category: str) -> None:
        if not self._alive(generation):
            return
        self._worker = None
        if category == "cancelled":
            self._update_cta(str(tr("已停止。")))
            return
        hint = {
            "auth_error": "API Key 不对或已失效，请在 AI 设置里重新填写并测试连接。",
            "auth_config": "API Key 不对或已失效，请在 AI 设置里重新填写并测试连接。",
            "quota_exhausted": "AI 服务的余额或额度不足，请到服务商那里充值。",
            "rate_limited": "AI 服务暂时太忙，请稍后重新分析。",
            "timeout": "AI 服务太久没有回应，请稍后重新分析。",
            "request_too_large": "这次的报告对这个 AI 模型太大了，可以换一个上下文更长的模型。",
        }.get(category, "")
        reason = str(tr(hint)) if hint else message
        self._update_cta(str(tr("AI 分析失败：{reason}", reason=reason)))

    def _copy(self) -> None:
        QApplication.clipboard().setText(view_text(self.view) + (f"\n\n{self.answer}" if self.answer and self.view.source != "ai" else ""))
        bind_text(self.copy_button, "已复制")
        QTimer.singleShot(2000, lambda: self._alive(self._generation) and bind_text(self.copy_button, "复制分析"))

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._generation += 1
            self._worker = None
