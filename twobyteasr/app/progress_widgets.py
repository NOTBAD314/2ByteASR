"""Recognition progress page widgets (2026-10-07 visual system).

Only presentation lives here: state comes from the MainWindow's existing
pipeline-event handling. Every state shown must be backed by a real event;
nothing here animates fake progress or invents remaining time.

The run-log helpers at the end (``append_log_html_keep_left`` and friends)
moved here from ``app/ui.py`` on 2026-10-15; ``ui`` still exports them.
"""
from __future__ import annotations

import html
import time

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QTextCursor
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QProgressBar, QSizePolicy, QVBoxLayout, QWidget)

from .ui_zoom import px as _zpx  # painted text follows the interface zoom
from ..i18n import bind_text, translate
from ..design.typography import MONO_FONT_STACK, TITLE_FONT_STACK, UI_FONT_STACK


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition

    return theme_definition(theme_key())


# --------------------------------------------------------------------------
# Phase cards
# --------------------------------------------------------------------------

PHASE_STATE_LABELS = {
    "pending": "等待",
    "active": "进行中",
    "done": "已完成",
    "degraded": "完成 · 有回退",
    "failed": "需处理",
    # 2026-10-08 (M12): an ended run closes every card, and a phase the run
    # does not include says so instead of waiting forever.
    "off": "本次未启用",
    "notrun": "未执行",
    "cancelled": "已取消",
    "stopped": "未完成",
}


def phase_state_colors(theme, state: str) -> dict[str, str]:
    """Explicit per-state roles; never only a near-identical background."""
    if state == "active":
        return dict(fill=theme.accent_tint, border=theme.accent, badge=theme.accent,
                    glyph=theme.text_on_accent, label=theme.accent_text)
    if state == "done":
        return dict(fill="transparent", border=theme.border, badge=theme.success,
                    glyph=theme.app_background, label=theme.success)
    if state == "degraded":
        return dict(fill=theme.warning_soft, border=theme.warning, badge=theme.warning,
                    glyph=theme.app_background, label=theme.warning)
    if state == "failed":
        return dict(fill=theme.danger_soft, border=theme.danger, badge=theme.danger,
                    glyph=theme.app_background, label=theme.danger)
    if state in {"cancelled", "stopped"}:
        return dict(fill="transparent", border=theme.warning, badge=theme.warning,
                    glyph=theme.app_background, label=theme.warning)
    return dict(fill="transparent", border=theme.border, badge="transparent",
                glyph=theme.text_muted, label=theme.text_muted)


class ProgressPhaseCard(QFrame):
    """One of the four recognition phases with an explicit state marker.

    States: pending / active / done / degraded (finished, but an AI step fell
    back to its local source) / failed. Each state differs by glyph, label
    text and colour role, not only by fill.
    """

    def __init__(self, icon_name: str, title: str, subtitle: str, accent: str, *, number: int = 0):
        super().__init__()
        self.setObjectName("phaseCard")
        self.icon_name = icon_name
        self.accent = accent
        self.number = number
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(52, 10, 14, 10)
        layout.setSpacing(0)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("phaseTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("phaseSubtitle")
        self.subtitle_label.hide()
        self.state_label = QLabel("等待")
        self.state_label.setObjectName("phaseState")
        # Long translated qualifiers must not widen the four-column stepper.
        self.state_label.setMinimumWidth(0)
        self.state_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail = ""
        self.steps = (0, 0)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.state_label)
        layout.addLayout(text_layout, 1)
        # Back-compat handle: callers/tests treat the badge as an icon label.
        self.icon_label = self
        self._state = ""
        self._pulse_light = False
        self._pulse = QTimer(self)
        self._pulse.setInterval(900)
        self._pulse.setTimerType(Qt.TimerType.CoarseTimer)
        self._pulse.timeout.connect(self._toggle_active_pulse)
        self.set_state("pending")

    def _state_palette(self, state: str):
        theme = _theme()
        colors = phase_state_colors(theme, state)
        return colors["fill"], colors["border"], colors["label"], PHASE_STATE_LABELS.get(state, "等待")

    def _repaint_state(self) -> None:
        theme = _theme()
        colors = phase_state_colors(theme, self._state)
        self.title_label.setStyleSheet(
            f"color: {theme.text if self._state != 'pending' else theme.text_secondary};"
            f" font-family: {UI_FONT_STACK}; font-size: 16px; font-weight: 600; background: transparent;")
        self.state_label.setStyleSheet(
            f"color: {colors['label']}; font-family: {UI_FONT_STACK}; font-size: 13px; font-weight: 500;"
            " background: transparent;")
        self.update()

    def refresh_theme_palette(self) -> None:
        self._repaint_state()

    def _toggle_active_pulse(self):
        if self._state != "active":
            return
        self._pulse_light = not self._pulse_light
        self.update()

    def set_detail(self, text: str) -> None:
        """Short factual qualifier shown after the state (e.g. fallback count)."""
        self.detail = str(text or "")
        self._apply_label()

    def set_steps(self, done: int, total: int) -> None:
        """Real step counts inside this phase, so the four cards add up to
        the hero's "N of M steps"."""
        steps = (max(0, int(done)), max(0, int(total)))
        if steps != self.steps:
            self.steps = steps
            self._apply_label()

    def _apply_label(self):
        label = PHASE_STATE_LABELS.get(self._state, "等待")
        done, total = self.steps
        if self.detail and self._state in {"degraded", "failed"}:
            bind_text(self.state_label, "{state} · {detail}", state=translate(label), detail=self.detail)
        elif total and self._state in {"active", "cancelled", "stopped"}:
            bind_text(self.state_label, "{state} · {done}/{total} 步", state=translate(label), done=done, total=total)
        elif total and self._state in {"pending", "done"}:
            bind_text(self.state_label, "{state} · {total} 步", state=translate(label), total=total)
        else:
            bind_text(self.state_label, label)
        self._state_full = self.state_label.text()
        self.setToolTip(self._state_full)
        self._elide_state()

    def _elide_state(self):
        full = getattr(self, "_state_full", self.state_label.text())
        width = self.state_label.width()
        if width > 20:
            self.state_label.setText(self.state_label.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_state()

    def set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        self._apply_label()
        self._repaint_state()
        if state == "active":
            self._pulse_light = False
            self._pulse.start()
        else:
            self._pulse.stop()

    def paintEvent(self, event):
        theme = _theme()
        colors = phase_state_colors(theme, self._state)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if colors["fill"] != "transparent":
            painter.setBrush(QColor(colors["fill"]))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(colors["border"]), 1)
        if self._state in {"pending", "off", "notrun"}:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 10, 10)
        # State badge: 26px circle with glyph.
        badge = QRectF(14, (self.height() - 26) / 2, 26, 26)
        if self._state in {"pending", "off", "notrun"}:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.border_strong), 1.5))
            painter.drawEllipse(badge)
            font = QFont(self.font())
            font.setPixelSize(_zpx(12))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.number or ""))
        elif self._state == "active":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.accent_text), 2))
            painter.drawEllipse(badge.adjusted(1, 1, -1, -1))
            dot = QColor(theme.accent_text)
            dot.setAlphaF(1.0 if not self._pulse_light else 0.55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(badge.center(), 5, 5)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["badge"]))
            painter.drawEllipse(badge)
            glyph = {"done": "fa5s.check", "cancelled": "fa5s.stop", "stopped": "fa5s.minus"}.get(
                self._state, "fa5s.exclamation")
            qta.icon(glyph, color=colors["glyph"]).paint(painter, badge.adjusted(7, 7, -7, -7).toRect())
        painter.end()


class RunningIndicator(QLabel):
    """Small status pill; readable without relying on motion.

    2026-10-08 (M12): no animated dots. A timer-driven animation looked busy
    even when a model had gone quiet; the pill only states what the events
    say (running / cancelling / done / cancelled / not finished).
    """

    TONES = ("accent", "muted", "warning", "success", "danger")

    def __init__(self, parent=None):
        super().__init__("运行中", parent)
        self._step = 0
        self._running = False
        self._tone = "muted"
        self._apply_theme()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(320)
        self._timer.timeout.connect(self._tick)

    def _apply_theme(self) -> None:
        theme = _theme()
        from ..design.ui_theme import blend_hex
        tone = self._tone if self._tone in self.TONES else "muted"
        if tone == "accent":
            color, background, border = theme.accent_text, theme.accent_tint, theme.accent
        elif tone == "muted":
            color, background, border = theme.text_secondary, theme.surface_elevated, theme.border_strong
        else:
            base = {"warning": theme.warning, "success": theme.success, "danger": theme.danger}[tone]
            color, background, border = base, blend_hex(theme.surface, base, 0.12), blend_hex(theme.surface, base, 0.55)
        self.setStyleSheet(
            f"background:{background}; color:{color}; border:1px solid {border}; border-radius:12px;"
            f" padding:3px 12px; font-family:{UI_FONT_STACK}; font-size:13px; font-weight:600;")

    def refresh_theme_palette(self) -> None:
        self._apply_theme()

    def _tick(self):
        self._timer.stop()

    def set_status(self, text: str, tone: str = "muted", **arguments) -> None:
        self._running = tone == "accent"
        self._timer.stop()
        bind_text(self, text, **arguments)
        if tone != self._tone:
            self._tone = tone
            self._apply_theme()

    def set_running(self, running: bool):
        self.set_status("运行中" if running else "等待下一步", "accent" if running else "muted")


# --------------------------------------------------------------------------
# Task feed rows
# --------------------------------------------------------------------------

FEED_ICONS = {
    "准备": "fa5s.hourglass-start",
    "开始": "fa5s.play",
    "运行中": "fa5s.play",
    "完成": "fa5s.check",
    "已回退": "fa5s.exclamation-triangle",
    "失败": "fa5s.exclamation",
    "缓存": "fa5s.database",
    "并行": "fa5s.project-diagram",
    "批次": "fa5s.layer-group",
    "素材": "fa5s.file-video",
    "取消": "fa5s.stop",
    "自愈": "fa5s.shield-alt",
    "跳过": "fa5s.forward",
    "交付": "fa5s.save",
    "任务配置": "fa5s.sliders-h",
    "说话人区分": "fa5s.user-friends",
    "最终字幕": "fa5s.closed-captioning",
    "临时转写（待校对）": "fa5s.closed-captioning",
    "已取消": "fa5s.stop-circle",
    "未完成": "fa5s.minus-circle",
    "已停止": "fa5s.power-off",
    "已结束": "fa5s.flag-checkered",
}

FEED_TONES = {
    "完成": "success", "素材": "success", "自愈": "success",
    "开始": "accent", "运行中": "accent",
    "失败": "danger", "取消": "danger",
    "已回退": "warning",
    "缓存": "info", "并行": "info", "批次": "info", "交付": "info", "任务配置": "info",
    "说话人区分": "info", "最终字幕": "info", "临时转写（待校对）": "info", "跳过": "muted",
    "已取消": "warning", "未完成": "danger", "已停止": "muted", "已结束": "muted",
}


def tone_color(theme, tone: str) -> str:
    return {
        "success": theme.success, "warning": theme.warning, "danger": theme.danger,
        "info": theme.info, "accent": theme.accent_text, "muted": theme.text_muted,
    }.get(tone, theme.text_secondary)


class TaskEventCard(QFrame):
    """Compact feed row. Stage rows update in place (start → finished) so the
    feed reads as one line per stage instead of repeated start/finish cards.
    Supplementary events render as quieter indented rows."""

    ICONS = FEED_ICONS

    def __init__(self, badge: str, message: str, color: str = "", parent=None, *, nested: bool = False,
                 meta: str = ""):
        super().__init__(parent)
        self.setObjectName("taskEventRow")
        self._badge = str(badge)
        self._message = str(message)
        self._accent = str(color)
        self._nested = nested
        self._tone = FEED_TONES.get(self._badge, "muted")
        row = QHBoxLayout(self)
        row.setContentsMargins(26 if nested else 8, 4, 8, 4)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setObjectName("eventIcon")
        self.icon.setFixedSize(QSize(20, 20))
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        self.message_label = bind_text(QLabel(), message)
        self.message_label.setObjectName("eventMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.message_label, 1)
        # Duration / live elapsed in its own column so rows read as a record.
        self.meta_label = QLabel()
        self.meta_label.setObjectName("eventMeta")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.set_meta(meta)
        row.addWidget(self.meta_label, 0, Qt.AlignmentFlag.AlignTop)
        self.badge_label = bind_text(QLabel(), badge)
        self.badge_label.setObjectName("eventBadge")
        row.addWidget(self.badge_label, 0, Qt.AlignmentFlag.AlignTop)
        self._apply_theme(_theme())

    def set_meta(self, text) -> None:
        from ..i18n import TranslatedText
        if isinstance(text, TranslatedText):
            bind_text(self.meta_label, text)
        elif self.meta_label.text() != str(text or ""):
            self.meta_label.setText(str(text or ""))
        self.meta_label.setVisible(bool(str(text or "")))

    def set_event(self, badge: str, message: str | None = None, *, template=None, **arguments):
        self._badge = str(badge)
        self._tone = FEED_TONES.get(self._badge, "muted")
        bind_text(self.badge_label, badge)
        if template is not None:
            bind_text(self.message_label, template, **arguments)
        elif message is not None:
            bind_text(self.message_label, message)
        self._apply_theme(_theme())

    def _apply_theme(self, theme) -> None:
        color = tone_color(theme, self._tone)
        # 2026-10-07: feed copy is primary reading text on this page (user: too small).
        # 2026-10-08 (M12): one size up again; the record is read, not scanned.
        size = 15 if self._nested else 16
        self.icon.setPixmap(qta.icon(self.ICONS.get(self._badge, "fa5s.circle"), color=color).pixmap(QSize(15, 15)))
        self.setStyleSheet(
            "QFrame#taskEventRow { background: transparent; border: 0; }"
            f"QLabel#eventBadge {{ color: {color}; font-family: {UI_FONT_STACK}; font-size: 14px; font-weight: 600; }}"
            f"QLabel#eventMeta {{ color: {theme.text_muted}; font-family: {MONO_FONT_STACK}; font-size: 14px;"
            " font-weight: 500; padding-right: 6px; }"
            f"QLabel#eventMessage {{ color: {theme.text if not self._nested else theme.text_secondary};"
            f" font-family: {UI_FONT_STACK}; font-size: {size}px; font-weight: 500; }}")

    def refresh_theme_palette(self) -> None:
        self._apply_theme(_theme())


class ResizeWatcher(QObject):
    """Calls ``callback`` after the watched widget's own resize settles."""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self._callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self._callback()
        return False


class FeedList(QListWidget):
    """Task feed whose word-wrapped rows are re-measured at the real width."""

    def sizeHint(self):
        # Fill leftover space only: a large preferred height made the
        # page's height-for-width exceed the window and Qt grew the window.
        return QSize(320, 96)

    def add_row(self, card, limit: int = 80):
        item = QListWidgetItem()
        self.addItem(item)
        self.setItemWidget(item, card)
        self._fit(item, card)
        while self.count() > limit:
            removed = self.takeItem(0)
            del removed
        self.scrollToBottom()
        return item

    def _fit(self, item, card):
        width = max(160, self.viewport().width() - 4)
        layout = card.layout()
        height = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else card.sizeHint().height()
        item.setSizeHint(QSize(0, max(30, height)))

    def refit(self, card):
        for index in range(self.count()):
            item = self.item(index)
            if self.itemWidget(item) is card:
                self._fit(item, card)
                return

    def resizeEvent(self, event):
        bar = self.verticalScrollBar()
        # A list that was following the newest row keeps following it when
        # the preview below grows and the list gets shorter (M12).
        following = bar.value() >= bar.maximum() - 2
        super().resizeEvent(event)
        for index in range(self.count()):
            item = self.item(index)
            card = self.itemWidget(item)
            if card is not None:
                self._fit(item, card)
        if following:
            self.scrollToBottom()


class ElidedRowsLabel(QWidget):
    """Live model evidence rows: each line elided to width, full text on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveEvidence")
        self._rows: list[str] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows):
        rows = [str(row) for row in rows if str(row).strip()]
        if rows == self._rows:
            return
        self._rows = rows
        self.setToolTip("\n".join(rows))
        self.setAccessibleDescription("\n".join(rows))
        self.updateGeometry()
        self.update()

    def rows(self):
        return list(self._rows)

    def setText(self, text):  # bind_text / legacy QLabel callers
        self.set_rows(str(text or "").splitlines())

    def text(self):
        return "\n".join(self._rows)

    def _font(self):
        font = QFont(self.font())
        font.setPixelSize(_zpx(13))
        return font

    def sizeHint(self):
        metrics = QFontMetrics(self._font())
        return QSize(300, max(0, len(self._rows)) * (metrics.height() + 4))

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())

    def paintEvent(self, event):
        theme = _theme()
        painter = QPainter(self)
        font = self._font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        y = 0
        for row in self._rows:
            label, _, rest = row.partition(" · ")
            x = 0
            painter.setPen(QColor(theme.text_secondary))
            if rest:
                head = label + "  "
                painter.drawText(x, y + metrics.ascent() + 2, head)
                x += metrics.horizontalAdvance(head)
                painter.setPen(QColor(theme.text_muted))
                painter.drawText(x, y + metrics.ascent() + 2,
                                 metrics.elidedText(rest, Qt.TextElideMode.ElideRight, max(0, self.width() - x)))
            else:
                painter.drawText(0, y + metrics.ascent() + 2,
                                 metrics.elidedText(row, Qt.TextElideMode.ElideRight, self.width()))
            y += metrics.height() + 4
        painter.end()


# --------------------------------------------------------------------------
# 2026-10-08 (M12): determinate run bar, live metrics and text preview
# --------------------------------------------------------------------------

class StageProgressBar(QProgressBar):
    """Determinate run progress drawn over the pipeline's real steps.

    The fill is the real fraction (finished steps plus real batch counters in
    the running step). The running step's segment is tinted so its end is
    visible; the tint brightens only when a real output event arrives and
    then fades, so a quiet model never looks busy. Never indeterminate.
    """

    FADE_SECONDS = 1.4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)
        self._segments = 0
        self._spans: tuple = ()
        self._activity_at = 0.0
        self._fade = QTimer(self)
        self._fade.setInterval(40)
        self._fade.timeout.connect(self._fade_step)

    def setRange(self, minimum, maximum):  # noqa: N802 - Qt API
        # Old callers asked for (0, 0) "busy" mode; this bar stays real.
        super().setRange(0, 1000)

    def set_segments(self, count: int, spans=()) -> None:
        count, spans = max(0, int(count)), tuple(spans or ())
        if (count, spans) != (self._segments, self._spans):
            self._segments, self._spans = count, spans
            self.update()

    def note_activity(self) -> None:
        self._activity_at = time.monotonic()
        self._fade.start()
        self.update()

    def _glow(self) -> float:
        age = time.monotonic() - self._activity_at
        return max(0.0, 1.0 - age / self.FADE_SECONDS) if self._activity_at else 0.0

    def _fade_step(self):
        if self._glow() <= 0:
            self._fade.stop()
        self.update()

    def paintEvent(self, event):
        theme = _theme()
        from ..design.ui_theme import blend_hex
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(theme.panel))
        glow = self._glow()
        band = QColor(blend_hex(theme.panel, theme.accent, 0.3 + 0.35 * glow))
        for start, end in self._spans:
            painter.fillRect(QRectF(rect.left() + start * rect.width(), rect.top(),
                                    max(2.0, (end - start) * rect.width()), rect.height()), band)
        span = max(1, self.maximum() - self.minimum())
        fill = (self.value() - self.minimum()) / span * rect.width()
        if fill > 0:
            painter.fillRect(QRectF(rect.left(), rect.top(), fill, rect.height()), QColor(theme.accent))
        if self._segments > 1:
            gap = QColor(theme.surface)
            for index in range(1, self._segments):
                x = rect.left() + index / self._segments * rect.width()
                painter.fillRect(QRectF(x - 1, rect.top(), 2, rect.height()), gap)
        painter.end()


class _ElidedValue(QLabel):
    """One-line value that elides with "…" instead of being clipped."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""

    def setText(self, text):  # noqa: N802 - Qt API
        self._full = str(text or "")
        super().setText(self._full)
        self.update()

    def text(self):
        return self._full

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        rect = self.contentsRect()
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, rect.width()))
        painter.end()


class StageMetricGrid(QWidget):
    """Live facts for the running step as a label / value column.

    2026-10-09 (M14, user): the current-step card puts the action on the
    left and these facts in a right-hand column, so the card's width is used
    and the numbers line up. Values elide; the full text is on the tooltip.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stageMetrics")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(22)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self._rows: list[tuple[QLabel, QLabel]] = []
        self._count = 0
        self._compact = False

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self._grid.setVerticalSpacing(3 if compact else 6)
        for _key, value in self._rows:
            value.setProperty("compact", compact)
            value.style().unpolish(value)
            value.style().polish(value)

    def _row(self, index):
        while len(self._rows) <= index:
            key = QLabel()
            key.setObjectName("stageMetricKey")
            value = _ElidedValue()
            value.setObjectName("stageMetricValue")
            value.setProperty("compact", self._compact)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            row = len(self._rows)
            self._grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignVCenter)
            self._rows.append((key, value))
        return self._rows[index]

    def set_metrics(self, metrics, limit=4) -> None:
        """metrics: [(key, value)] already in the UI language.

        Four facts per step; online API steps may show six (batches in
        flight, retries and token usage, 2026-10-15).
        """
        metrics = list(metrics or ())[:limit]
        for index, (key_text, value_text) in enumerate(metrics):
            key, value = self._row(index)
            if key.text() != key_text:
                key.setText(key_text)
            if value.text() != value_text:
                value.setText(value_text)
            value.setToolTip(f"{key_text}：{value_text}")
        for index, (key, value) in enumerate(self._rows):
            key.setVisible(index < len(metrics))
            value.setVisible(index < len(metrics))
        self._count = len(metrics)
        self.setVisible(bool(metrics))

    def metrics(self):
        return [(key.text(), value.text()) for key, value in self._rows[:self._count]]


class RecognitionPreview(QWidget):
    """Newest readable recognition text, newest row last.

    Rows come only from events that carry real text (FireRed evidence, ASR
    API deltas, AI proofreading results, saved cues). Each row says whether
    it has been proofread. Painted, so the language overlay never touches
    the user's subtitle text.
    """

    ROW = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("recognitionPreview")
        self.setProperty("uiZoomOwnSize", True)  # painted rows of a fixed height
        self._rows: list[tuple[str, str, str, str]] = []
        self._empty = ""
        self._max_rows = 4
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fit_rows()

    def set_max_rows(self, rows: int) -> None:
        rows = max(1, int(rows))
        if rows != self._max_rows:
            self._max_rows = rows
            self._fit_rows()

    def _fit_rows(self):
        # Empty: one explanatory line, the record above gets the room.
        # With text: at most six rows, newest last.
        if self._rows:
            height = self.ROW * min(self._max_rows, max(1, len(self._rows)))
        else:
            height = 44
        self.setFixedHeight(height)

    def set_rows(self, rows) -> None:
        """rows: [(time label, text, tag, tone)], oldest first."""
        rows = [tuple(str(part) for part in row) for row in rows]
        if rows == self._rows:
            return
        count_changed = min(len(rows), self._max_rows) != min(len(self._rows), self._max_rows)
        self._rows = rows
        if count_changed:
            self._fit_rows()
        self.setToolTip("\n".join(f"{time_text}  {text}  ({tag})" for time_text, text, tag, _tone in rows[-8:]))
        self.update()

    def rows(self):
        return list(self._rows)

    def set_empty_text(self, text: str) -> None:
        if text != self._empty:
            self._empty = str(text or "")
            self.update()

    def empty_text(self):
        return self._empty

    def sizeHint(self):
        return QSize(320, self.height() or 44)

    def paintEvent(self, event):
        theme = _theme()
        from ..design.ui_theme import blend_hex
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        if not self._rows:
            font = QFont(self.font())
            font.setPixelSize(_zpx(15))
            painter.setFont(font)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRectF(4, 6, width - 8, self.height() - 12),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                             self._empty)
            painter.end()
            return
        time_font = QFont(self.font())
        time_font.setFamilies([part.strip().strip("'\"") for part in MONO_FONT_STACK.split(",")])
        time_font.setPixelSize(_zpx(13))
        text_font = QFont(self.font())
        text_font.setPixelSize(_zpx(16))
        tag_font = QFont(self.font())
        tag_font.setPixelSize(_zpx(13))
        tag_font.setWeight(QFont.Weight.DemiBold)
        visible = max(1, self.height() // self.ROW)
        rows = self._rows[-visible:]
        y = 0
        rule = QColor(theme.border)
        for index, (time_text, text, tag, tone) in enumerate(rows):
            row_rect = QRectF(0, y, width, self.ROW)
            painter.setFont(time_font)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRectF(4, y, 54, self.ROW), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             time_text)
            painter.setFont(tag_font)
            tag_metrics = QFontMetrics(tag_font)
            tag_width = tag_metrics.horizontalAdvance(tag) + 18
            tag_rect = QRectF(width - tag_width - 2, y + (self.ROW - 24) / 2, tag_width, 24)
            color = QColor(tone_color(theme, tone))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(blend_hex(theme.surface, color.name(), 0.14)))
            painter.drawRoundedRect(tag_rect, 12, 12)
            painter.setPen(color)
            painter.drawText(tag_rect, int(Qt.AlignmentFlag.AlignCenter), tag)
            painter.setFont(text_font)
            text_metrics = QFontMetrics(text_font)
            available = max(0, int(tag_rect.left() - 64 - 12))
            painter.setPen(QColor(theme.text if index == len(rows) - 1 else theme.text_secondary))
            painter.drawText(QRectF(64, y, available, self.ROW), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             text_metrics.elidedText(text, Qt.TextElideMode.ElideRight, available))
            if index < len(rows) - 1:
                painter.fillRect(QRectF(row_rect.left() + 4, row_rect.bottom() - 1, width - 8, 1), rule)
            y += self.ROW
        painter.end()


def resource_fields(resource: str) -> list[tuple[str, str]]:
    """Split a stage resource string into labelled facts for display only.

    ``grok_oauth/grok-4.7 · grok_cli+说话人插话保护`` → 服务 / 模型 / 运行方式.
    Unknown shapes are shown verbatim as one row; nothing is inferred.
    """
    text = str(resource or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.replace("·", " · ").split(" · ") if part.strip()]
    fields: list[tuple[str, str]] = []
    first = parts[0]
    if "/" in first and " " not in first and not first.startswith(("http", "C:", "D:")):
        provider, _, model = first.partition("/")
        fields.append(("服务", provider))
        fields.append(("模型", model))
        parts = parts[1:]
    for part in parts:
        device = part.upper().replace("（", "(").split("(")[0].strip()
        fields.append(("运行设备" if device in {"GPU", "CPU", "CPU/GPU"} else "运行方式", part))
    return fields


# --------------------------------------------------------------------------
# Run log styling (shared by the live log and the completion log)
# --------------------------------------------------------------------------

FATAL_MARKERS = ("traceback", "[文件失败]", "[阶段失败]", "已停止写入", "fatal error", "致命")
RECOVERABLE_MARKERS = ("[警告]", "warning", "最终回退", "连续失败", "403", "forbidden", "回退")


def log_line_tone(line: str, level: str = "stdout") -> str:
    compact = str(line or "")
    lowered = compact.lower()
    stripped = compact.lstrip()
    if any(marker in lowered for marker in FATAL_MARKERS):
        return "error"
    if any(marker in lowered for marker in RECOVERABLE_MARKERS):
        return "warning"
    if level == "stderr":
        return "stderr"
    if stripped.startswith("[阶段完成]"):
        return "success"
    if stripped.startswith("[阶段") or stripped.startswith("===="):
        return "stage"
    if "缓存命中" in compact or "缓存写入" in compact or "缓存跳过" in compact:
        return "cache"
    if "完成" in compact or "成功" in compact:
        return "success"
    return "plain"


def log_line_html(line: str, level: str = "stdout", theme=None) -> str:
    """Theme-derived log row. Background washes only for warnings/errors and
    stage headers; ordinary output stays plain for readability."""
    theme = theme or _theme()
    tone = log_line_tone(line, level)
    from ..design.ui_theme import blend_hex

    base = theme.log_background
    # Every row names its background explicitly: QTextEdit blocks inherit the
    # previous block's background when a row says "transparent".
    color, background, weight = {
        "error": (theme.danger, blend_hex(base, theme.danger, 0.16), 500),
        "warning": (theme.warning, blend_hex(base, theme.warning, 0.13), 500),
        "stderr": (theme.text_muted, base, 500),
        "success": (theme.success, base, 500),
        "stage": (theme.log_text, blend_hex(base, theme.accent, 0.16), 500),
        "cache": (theme.info, base, 500),
    }.get(tone, (blend_hex(theme.log_text, theme.text_muted, 0.35), base, 500))
    safe = html.escape(str(line).rstrip()).replace(" ", "&nbsp;")
    # Highlights are character-level spans: a block-level background would be
    # inherited by every later QTextEdit.append() block.
    if background != base:
        safe = f'<span style="background-color:{background};">{safe}&nbsp;</span>'
    return (f'<div style="color:{color}; margin:0; font-weight:{weight}; white-space:pre;">{safe}</div>')


def log_surface_qss(theme) -> str:
    return (f"QTextEdit#consoleLog, QTextEdit#resultConsole {{ background: {theme.log_background}; "
            f"color: {theme.log_text}; border: 1px solid {theme.border}; border-radius: 8px; padding: 8px 4px; "
            f"font-family: {MONO_FONT_STACK}; font-size: 13px; "
            f"selection-background-color: {theme.selected}; selection-color: {theme.text}; }}")


def progress_page_qss(theme) -> str:
    """Page-scoped surfaces for the progress page (token-derived)."""
    from ..design.ui_theme import blend_hex
    return f"""
QWidget#progressHeader {{ background: transparent; }}
QFrame#currentStageCard, QFrame#eventFeedCard, QFrame#consoleCard {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 12px; }}
/* The step that is running now is the page's focal point (brand wash). */
QFrame#currentStageCard {{ background: {blend_hex(theme.surface, theme.accent_text, 0.08)};
    border-color: {blend_hex(theme.surface, theme.accent_text, 0.45)}; }}
QLabel#progressTitle {{ color: {theme.text}; font-family: {TITLE_FONT_STACK}; font-size: 24px; font-weight: 800; background: transparent; }}
QLabel#progressContext {{ color: {theme.text_secondary}; font-size: 15px; font-weight: 500; background: transparent; }}
QLabel#progressPercent {{ color: {theme.accent_text}; font-family: {TITLE_FONT_STACK}; font-size: 32px; font-weight: 800;
    background: transparent; border: 0; padding: 0; }}
QLabel#progressElapsedCaption {{ color: {theme.text_muted}; font-size: 13px; font-weight: 500; background: transparent; }}
QLabel#progressElapsed {{ color: {theme.text}; font-family: {MONO_FONT_STACK}; font-size: 20px; font-weight: 700;
    background: transparent; border: 0; padding: 0; }}
QLabel#progressStat {{ color: {theme.text}; font-family: {UI_FONT_STACK}; font-size: 20px; font-weight: 700;
    background: transparent; border: 0; padding: 0; }}
QLabel#stageDevice {{ color: {theme.text_secondary}; font-size: 13px; font-weight: 600; background: transparent;
    border: 1px solid {theme.border_strong}; border-radius: 12px; padding: 3px 10px; }}
QLabel#stageEyebrow {{ color: {theme.accent_text}; font-size: 14px; font-weight: 700; background: transparent; }}
QLabel#stageStep {{ color: {theme.text_secondary}; font-size: 14px; font-weight: 500; background: transparent; }}
QLabel#stageLarge {{ color: {theme.text}; font-family: {UI_FONT_STACK}; font-size: 28px; font-weight: 800; background: transparent; }}
QLabel#stageSecondary {{ color: {theme.text_secondary}; font-size: 14px; font-weight: 500; background: transparent; }}
QLabel#stageSubtitle {{ color: {theme.text_secondary}; font-size: 15px; font-weight: 500; background: transparent; }}
QFrame#stageNoteRow {{ background: {theme.panel}; border: 0; border-radius: 8px; }}
QLabel#stageNote {{ color: {theme.text_secondary}; font-size: 14px; font-weight: 500; background: transparent; }}
QLabel#stageNoteDetail {{ color: {theme.text_muted}; font-size: 13px; font-weight: 500; background: transparent; }}
QToolButton#stageNoteMore {{ color: {theme.accent_text}; background: transparent; border: 0; font-size: 13px;
    font-weight: 600; padding: 2px 6px; }}
QToolButton#stageNoteMore:hover {{ text-decoration: underline; }}
QLabel#stageMetricKey {{ color: {theme.text_muted}; font-size: 14px; font-weight: 500; background: transparent; border: 0; }}
QLabel#stageMetricValue {{ color: {theme.text}; font-family: {UI_FONT_STACK}; font-size: 19px; font-weight: 700;
    background: transparent; border: 0; }}
QLabel#stageMetricValue[compact="true"] {{ font-size: 16px; }}
QScrollArea#progressLeftScroll, QWidget#progressLeftContent {{ background: transparent; border: 0; }}
QScrollArea#progressLeftScroll > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QLabel#sectionCaption {{ color: {theme.text}; font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#sectionNote {{ color: {theme.text_muted}; font-size: 13px; font-weight: 500; background: transparent; }}
QFrame#feedRule {{ background: {theme.border}; border: 0; min-height: 1px; max-height: 1px; }}
QListWidget#eventFeed {{ background: transparent; border: 0; padding: 0; outline: 0; }}
QListWidget#eventFeed::item {{ border: 0; margin: 0; padding: 0; background: transparent; }}
QListWidget#eventFeed::item:hover, QListWidget#eventFeed::item:selected {{ background: transparent; }}
QFrame#progressFooterRule {{ background: {theme.border}; border: 0; min-height: 1px; max-height: 1px; }}
QSplitter#progressSplitter::handle {{ background: transparent; }}
QSplitter#progressSplitter::handle:hover {{ background: {theme.border}; }}
""" + log_surface_qss(theme)


def keep_log_view_at_left(edit) -> None:
    """Pin a runtime log view's horizontal scrollbar to the left edge.

    Manual horizontal scrolling stays possible: this is only called right
    after a programmatic content change, never on user input.
    """
    bar = edit.horizontalScrollBar()
    if bar is not None:
        bar.setValue(bar.minimum())


def append_log_html_keep_left(edit, fragment: str) -> None:
    """Follow a live tail, but preserve a user's place in earlier log entries."""
    vertical = edit.verticalScrollBar()
    previous = vertical.value() if vertical is not None else 0
    follow_tail = vertical is None or previous >= vertical.maximum() - 2
    old_cursor = edit.textCursor()
    edit.append(fragment)
    if follow_tail:
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.MoveAnchor)
        edit.setTextCursor(cursor)
    else:
        edit.setTextCursor(old_cursor)
    if vertical is not None:
        vertical.setValue(vertical.maximum() if follow_tail else previous)
    keep_log_view_at_left(edit)


def set_log_html_keep_left(edit, html_text: str) -> None:
    """Replace the whole log (task reload/completion fill) from the left."""
    edit.setHtml(html_text)
    keep_log_view_at_left(edit)
