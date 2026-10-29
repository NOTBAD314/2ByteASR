"""Pieces shared by the link download window, the Studio quick card and the
toolbar capsule (2026-10-26, user's design A+B after YDL GUI).

Colors come from the active theme; sizes in the style sheet are logical px
(``ui_zoom.set_sheet`` scales them). A pill's radius is half its height minus
one, so it stays round when the interface zoom rounds sizes and radii apart.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from ..design.elided_label import ElidedLabel
from ..design.soft_qss import soft_tokens
from ..i18n import tr
from ..i18n_widgets import user_text
from ..media.link_choices import size_text

STAGES = dict(queued="排队中", running="正在下载", parsing="解析视频", tools="准备下载工具",
    downloading="下载音视频", merging="无损合并", subtitles="下载选定字幕", organizing="整理字幕",
    verifying="校验文件", completed="下载完成", pending_import="下载完成，待导入",
    imported="已导入工程", partial="部分成功", failed="失败，可重试", cancelled="已取消",
    cancelling="正在取消", paused="已暂停", pausing="正在暂停")

ACTIVE = {"queued", "running", "pausing", "cancelling"}
FILTERS = (("all", "全部"), ("active", "进行中"), ("done", "已完成"), ("attention", "需处理"))


def task_filter(task: dict) -> str:
    state = task.get("state", "")
    if state in ACTIVE or state == "paused":
        return "active"
    if state == "imported":
        return "done"
    if state in {"pending_import", "partial", "failed"}:
        return "attention"
    return ""


def active_theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def link_qss(t=None) -> str:
    """Component rules for every link download surface (scoped by object name)."""
    t = t or active_theme()
    k = soft_tokens(t)
    return f"""
QWidget#linkRoot {{ background: {t.app_background}; color: {t.text}; }}
QFrame#linkHeader {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QLabel#linkBrandMark {{ background: {t.accent}; border-radius: 9px; }}
QLabel#linkBrandTitle {{ color: {t.text}; font-size: 15px; font-weight: 700; }}
QLabel#linkBrandNote, QLabel#linkMeta, QLabel#linkHint, QLabel#linkStatusText {{ color: {t.text_muted}; }}
QLabel#linkBrandNote {{ font-size: 11px; }}
QPushButton#linkNav {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 17px;
    min-height: 36px; max-height: 36px; padding: 0 13px; font-size: 13px; font-weight: 600;
}}
QPushButton#linkNav:hover {{ background: {k.fill}; color: {t.text}; }}
QPushButton#linkNav:checked {{ background: {k.chip}; color: {t.accent_text}; font-weight: 700; }}
QToolButton#linkIconButton {{
    background: transparent; border: 0; border-radius: 17px; min-width: 36px; max-width: 36px;
    min-height: 36px; max-height: 36px;
}}
QToolButton#linkIconButton:hover {{ background: {k.fill}; }}
QToolButton#linkIconButton:checked {{ background: {k.chip}; }}
QLabel#linkHeroTitle {{ color: {t.text}; font-size: 24px; font-weight: 700; }}
QLabel#linkHeroNote {{ color: {t.text_secondary}; font-size: 14px; }}
QFrame#linkUrlField {{
    background: {t.surface_elevated}; border: 1px solid {t.border_strong}; border-radius: 23px;
    min-height: 48px; max-height: 48px;
}}
QFrame#linkUrlField[compact="true"] {{ border-radius: 19px; min-height: 40px; max-height: 40px; }}
QFrame#linkUrlField QLineEdit {{
    background: transparent; border: 0; padding: 0; font-size: 14px; color: {t.text};
    min-height: 30px;
}}
QFrame#linkUrlField QLabel {{ background: transparent; }}
QPushButton#linkPrimary {{
    background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 19px;
    min-height: 40px; max-height: 40px; padding: 0 20px; font-size: 14px; font-weight: 700;
}}
QPushButton#linkPrimary:hover {{ background: {t.accent_hover}; }}
QPushButton#linkPrimary:pressed {{ background: {t.accent_pressed}; }}
QPushButton#linkPrimary:disabled {{ background: {k.fill}; color: {t.text_muted}; }}
QPushButton#linkGhost {{
    background: {k.fill}; color: {t.text}; border: 0; border-radius: 17px;
    min-height: 36px; max-height: 36px; padding: 0 15px; font-size: 13px; font-weight: 600;
}}
QPushButton#linkGhost:hover {{ background: {k.fill_hover}; }}
QPushButton#linkGhost:disabled {{ color: {t.disabled}; }}
QPushButton#linkLink {{
    background: transparent; color: {t.accent_text}; border: 0; padding: 0 4px;
    min-height: 28px; font-size: 13px; font-weight: 700;
}}
QPushButton#linkLink:hover {{ color: {t.text}; }}
QPushButton#linkLink:disabled {{ color: {t.disabled}; }}
QFrame#linkSegmented {{ background: {k.fill}; border: 0; border-radius: 18px; }}
QFrame#linkSegmented[collapsed="true"] {{ background: transparent; }}
QFrame#linkSegmented QPushButton {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 15px;
    min-height: 32px; max-height: 32px; padding: 0 14px; font-size: 13px; font-weight: 600;
}}
QFrame#linkSegmented QPushButton:hover {{ background: {k.fill_hover}; color: {t.text}; }}
QFrame#linkSegmented QPushButton:checked {{ background: {k.raised}; color: {t.text}; font-weight: 700; }}
QFrame#linkSegmented QPushButton:disabled {{ background: transparent; color: {t.disabled}; }}
QPushButton#linkChip {{
    background: {k.fill}; color: {t.text_secondary}; border: 1px solid transparent; border-radius: 15px;
    min-height: 32px; max-height: 32px; padding: 0 13px; font-size: 13px; font-weight: 600;
}}
QPushButton#linkChip:hover {{ background: {k.fill_hover}; color: {t.text}; }}
QPushButton#linkChip:checked {{ background: {k.chip}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#linkChip:disabled {{ color: {t.disabled}; }}
QFrame#linkCard, QFrame#linkTaskCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 16px; }}
QFrame#linkTaskCard {{ border-radius: 14px; }}
QFrame#linkTaskCard[compact="true"] {{ background: transparent; border: 0; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#linkDivider {{ background: {t.border}; border: 0; min-height: 1px; max-height: 1px; }}
QLabel#linkFieldLabel {{ color: {t.text_secondary}; font-size: 13px; font-weight: 700; }}
QLabel#linkTitle {{ color: {t.text}; font-size: 16px; font-weight: 700; }}
QLabel#linkTaskTitle {{ color: {t.text}; font-size: 14px; font-weight: 700; }}
QLabel#linkMeta {{ font-size: 13px; }}
QLabel#linkHint {{ font-size: 12px; }}
QLabel#linkStepper {{ font-size: 12px; color: {t.text_muted}; }}
QLabel#linkStateText {{ font-size: 12px; font-weight: 700; color: {t.text_muted}; }}
QLabel#linkStateText[tone="ok"] {{ color: {k.ok}; }}
QLabel#linkStateText[tone="warn"] {{ color: {k.warn}; }}
QLabel#linkStateText[tone="accent"] {{ color: {t.accent_text}; }}
QLabel#linkStateText[tone="danger"] {{ color: {t.danger}; }}
QPushButton#linkPrimary[small="true"], QPushButton#linkGhost[small="true"] {{
    min-height: 32px; max-height: 32px; border-radius: 15px; padding: 0 14px; font-size: 13px;
}}
QToolButton#linkIconButton[small="true"] {{
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; border-radius: 15px;
}}
QCheckBox#linkSectionCheck {{ font-size: 13px; font-weight: 700; color: {t.text}; }}
QLabel#linkPill {{
    border-radius: 12px; min-height: 26px; max-height: 26px; padding: 0 10px; font-size: 12px; font-weight: 700;
    background: {k.fill}; color: {t.text_muted};
}}
QLabel#linkPill[tone="ok"] {{ background: {k.ok_tint}; color: {k.ok}; }}
QLabel#linkPill[tone="warn"] {{ background: {k.warn_tint}; color: {k.warn}; }}
QLabel#linkPill[tone="accent"] {{ background: {k.chip}; color: {t.accent_text}; }}
QLabel#linkPill[tone="danger"] {{ background: {t.danger_soft}; color: {t.danger}; }}
QProgressBar#linkProgress {{
    background: {k.fill}; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px;
}}
QProgressBar#linkProgress::chunk {{ background: {t.accent}; border-radius: 3px; }}
QFrame#linkStatusBar {{ background: {t.panel}; border: 0; border-top: 1px solid {t.border}; }}
QLabel#linkStatusText {{ font-size: 12px; }}
QLabel#linkStatusStrong {{ color: {t.text_secondary}; font-size: 12px; font-weight: 700; }}
QFrame#linkStatusDivider {{ background: {t.border_strong}; min-width: 1px; max-width: 1px; min-height: 14px; max-height: 14px; }}
QLabel#linkNotice {{
    background: {k.chip}; color: {t.text}; border-radius: 10px; padding: 8px 14px; font-size: 13px;
}}
QLabel#linkDot {{ border-radius: 3px; min-width: 7px; max-width: 7px; min-height: 7px; max-height: 7px; background: {t.text_muted}; }}
QLabel#linkDot[tone="ok"] {{ background: {k.ok}; }}
QLabel#linkDot[tone="warn"] {{ background: {k.warn}; }}
QFrame#linkQuickCard, QFrame#linkPopover, QFrame#linkToast {{
    background: {t.surface_elevated}; border: 1px solid {t.border_strong}; border-radius: 18px;
}}
QFrame#linkPopover {{ border-radius: 16px; }}
QFrame#linkToast {{ border-radius: 14px; }}
QLabel#linkCardIcon {{ background: {k.chip}; border-radius: 9px; }}
QLabel#linkOkIcon {{ background: {k.ok_tint}; border-radius: 14px; }}
QFrame#linkSummaryBox {{ border: 1px solid {t.border}; border-radius: 12px; background: transparent; }}
QFrame#linkPopoverFooter {{ background: {t.panel}; border: 0; border-top: 1px solid {t.border};
    border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }}
QPushButton#linkCapsule {{
    background: {k.chip}; color: {t.accent_text}; border: 1px solid {t.accent}; border-radius: 15px;
    min-height: 32px; max-height: 32px; padding: 0 10px 0 6px; font-size: 13px; font-weight: 700;
}}
QPushButton#linkCapsule[tone="warn"] {{ background: {k.warn_tint}; color: {k.warn}; border-color: {k.warn}; }}
QPushButton#linkCapsule:hover {{ background: {k.chip_hover}; }}
"""


def capsule_qss(t=None) -> str:
    """The Studio toolbar capsule's own sheet; the workbench is not zoomed."""
    t = t or active_theme()
    k = soft_tokens(t)
    tone = (k.warn_tint, k.warn, k.warn)
    return f"""
QPushButton#linkCapsule {{
    background: {k.chip}; color: {t.accent_text}; border: 1px solid {t.accent}; border-radius: 15px;
    min-height: 32px; max-height: 32px; padding: 0 10px 0 6px; font-size: 13px; font-weight: 700;
}}
QPushButton#linkCapsule:hover {{ background: {k.chip_hover}; }}
QPushButton#linkCapsule[tone="warn"] {{ background: {tone[0]}; color: {tone[1]}; border-color: {tone[2]}; }}
"""


def apply_link_sheet(widget: QWidget, t=None) -> None:
    from .ui_zoom import set_sheet
    set_sheet(widget, link_qss(t))


def pill(text: str = "", tone: str = "off") -> QLabel:
    label = QLabel(text)
    label.setObjectName("linkPill")
    label.setProperty("tone", tone)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


def set_tone(widget: QWidget, tone: str) -> None:
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def named_label(text: str, name: str, *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def button(text: str, name: str = "linkGhost", icon: str = "", role: str = "primary") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        from ..design.themed_icons import install_themed_icon
        install_themed_icon(widget, icon, role)
        widget.setIconSize(QSize(16, 16))
    return widget


def icon_button(icon: str, tooltip: str, role: str = "secondary") -> QToolButton:
    from ..design.themed_icons import install_themed_icon
    widget = QToolButton()
    widget.setObjectName("linkIconButton")
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    install_themed_icon(widget, icon, role)
    widget.setIconSize(QSize(18, 18))
    widget.setToolTip(tooltip)
    widget.setAccessibleName(tooltip)
    return widget


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("linkDivider")
    return line


def icon_label(icon: str, size: int = 18, role: str = "secondary", name: str = "") -> QLabel:
    """A painted icon inside a label (brand mark, field icons)."""
    from ..design.themed_icons import themed_icon
    label = QLabel()
    if name:
        label.setObjectName(name)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setPixmap(themed_icon(icon, role).pixmap(QSize(size, size)))
    label.setProperty("_linkIcon", (icon, size, role))
    return label


def ring_icon(fraction: float | None, color: str, track: str, size: int = 22) -> QIcon:
    """A progress ring; ``None`` draws a quarter arc (unknown size)."""
    from PySide6.QtWidgets import QApplication
    ratio = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(3, 3, size - 6, size - 6)
    pen = QPen(QColor(track), 3)
    painter.setPen(pen)
    painter.drawEllipse(rect)
    pen.setColor(QColor(color))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    span = 90 if fraction is None else max(0.02, min(1.0, float(fraction))) * 360
    painter.drawArc(rect, 90 * 16, -int(span * 16))
    painter.end()
    return QIcon(pixmap)


class CoverView(QWidget):
    """Video cover with rounded corners and an optional duration badge."""

    def __init__(self, width: int, height: int, radius: int = 10, parent=None):
        super().__init__(parent)
        from .ui_zoom import set_size
        set_size(self, fixed_w=width, fixed_h=height)
        self._base_width = width
        self._radius = radius
        self._pixmap = QPixmap()
        self._badge = ""
        self._data = b""

    def set_image(self, data: bytes | None) -> None:
        data = bytes(data or b"")
        if data == self._data:
            return
        self._data = data
        self._pixmap = QPixmap()
        if data:
            self._pixmap.loadFromData(data)
        self.update()

    def set_badge(self, text: str) -> None:
        self._badge = str(text or "")
        self.update()

    def paintEvent(self, event):
        t = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = self.width() / max(1, self._base_width)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius * scale, self._radius * scale)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(t.media))
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size() * self.devicePixelRatioF(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            x = (self.width() - scaled.width() / self.devicePixelRatioF()) / 2
            y = (self.height() - scaled.height() / self.devicePixelRatioF()) / 2
            painter.drawPixmap(int(x), int(y), scaled)
        else:
            from ..design.themed_icons import paint_cached_icon
            side = int(min(self.width(), self.height()) * 0.3)
            rect = self.rect().adjusted((self.width() - side) // 2, (self.height() - side) // 2, 0, 0)
            rect.setSize(QSize(side, side))
            paint_cached_icon(painter, "fa5s.film", t.text_muted, rect)
        if self._badge:
            font = QFont(self.font())
            font.setPixelSize(max(10, int(11 * scale)))
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(self._badge) + 10 * scale
            height = metrics.height() + 2 * scale
            box = QRectF(self.width() - width - 6 * scale, self.height() - height - 6 * scale, width, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 185))
            painter.drawRoundedRect(box, 5 * scale, 5 * scale)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._badge)
        painter.end()


def _eta_text(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    if seconds < 60:
        return tr("剩余约 {count} 秒", count=seconds)
    return tr("剩余约 {count} 分钟", count=max(1, round(seconds / 60)))


def progress_parts(detail: dict) -> tuple[float | None, str]:
    """(fraction or None, "263.4 / 412.6 MiB · 2.4 MB/s · 剩余约 1 分钟")."""
    progress = (detail or {}).get("progress") or {}
    done = progress.get("downloaded_bytes")
    total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
    fraction = None
    parts = []
    if isinstance(done, (int, float)):
        if isinstance(total, (int, float)) and total:
            fraction = max(0.0, min(1.0, done / total))
            parts.append(f"{done/1024/1024:.1f} / {total/1024/1024:.1f} MiB")
        else:
            parts.append(size_text(done))
    speed = progress.get("speed")
    if isinstance(speed, (int, float)) and speed > 0:
        parts.append(f"{speed/1024/1024:.1f} MB/s")
    eta = _eta_text(progress.get("eta"))
    if eta:
        parts.append(eta)
    return fraction, " · ".join(parts)


def stage_of(task: dict, detail: dict) -> str:
    return (detail or {}).get("stage", "") if task.get("state") == "running" else task.get("state", "")


def state_tone(task: dict) -> str:
    return {"imported": "ok", "pending_import": "accent", "partial": "warn", "failed": "danger",
            "running": "accent", "pausing": "off", "cancelling": "off"}.get(task.get("state", ""), "off")


STEP_GROUPS = (("解析", {"queued", "parsing", "tools"}),
               ("音视频", {"downloading", "merging", "verifying"}),
               ("字幕", {"subtitles", "organizing"}),
               ("导入工程", {"completed", "partial", "pending_import", "imported"}))


def stepper_html(task: dict, detail: dict, t=None) -> str:
    t = t or active_theme()
    mode = task.get("mode", "both")
    steps = [step for step in STEP_GROUPS
             if not (step[0] == "字幕" and mode in ("video", "audio"))
             and not (step[0] == "音视频" and mode == "subtitles")]
    stage = stage_of(task, detail)
    current = next((i for i, (_, names) in enumerate(steps) if stage in names), -1)
    if task.get("state") == "imported":
        current = len(steps)
    fraction, _ = progress_parts(detail)
    pieces = []
    for index, (name, _) in enumerate(steps):
        label = tr("音频") if name == "音视频" and mode == "audio" else tr(name)
        if index < current:
            pieces.append(f'<span style="color:{t.success};font-weight:700">{label}</span>')
        elif index == current and task.get("state") in ACTIVE:
            extra = f" {fraction:.0%}" if fraction is not None and name == "音视频" else ""
            pieces.append(f'<span style="color:{t.accent_text};font-weight:700">{label}{extra}</span>')
        else:
            pieces.append(f'<span style="color:{t.text_muted}">{label}</span>')
    return f'<span style="color:{t.border_strong}">  —  </span>'.join(pieces)


class TaskCard(QFrame):
    """One download task: cover, title, state, steps, progress and its actions.

    ``action`` carries (name, task_id); the controller owns what they do.
    The compact form (Studio popover) puts the state in the text line and
    shows icon buttons next to at most one short text button.
    """

    action = Signal(str, str)
    ICONS = {"pause": "fa5s.pause", "cancel": "fa5s.times", "folder": "fa5s.folder-open", "resume": "fa5s.play",
             "retry": "fa5s.redo", "retry_subtitles": "fa5s.redo", "import": "fa5s.file-import",
             "edit": "fa5s.pen", "ai": "fa5s.magic"}

    def __init__(self, task_id: str, *, compact: bool = False, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.compact = compact
        self.setObjectName("linkTaskCard")
        self.setProperty("compact", compact)
        self._actions_key = None
        self._rendered = None
        row = QHBoxLayout(self)
        row.setContentsMargins(*((14, 10, 10, 10) if compact else (14, 12, 14, 12)))
        row.setSpacing(12 if compact else 16)
        self.cover = CoverView(64, 36, 6) if compact else CoverView(144, 81, 10)
        row.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(4 if compact else 6)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = user_text(ElidedLabel("", mode=Qt.TextElideMode.ElideRight, minimum=80))
        self.title.setObjectName("linkTaskTitle")
        head.addWidget(self.title, 1)
        self.state = pill()
        self.state.setVisible(not compact)
        head.addWidget(self.state, 0)
        body.addLayout(head)
        self.stepper = QLabel()
        self.stepper.setObjectName("linkStepper")
        self.stepper.setTextFormat(Qt.TextFormat.RichText)
        self.stepper.setVisible(not compact)
        body.addWidget(self.stepper)
        self.progress = QProgressBar()
        self.progress.setObjectName("linkProgress")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        body.addWidget(self.progress)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.state_text = QLabel()
        self.state_text.setObjectName("linkStateText")
        self.state_text.setVisible(compact)
        line.addWidget(self.state_text, 0)
        self.meta = user_text(ElidedLabel("", mode=Qt.TextElideMode.ElideRight, minimum=60))
        self.meta.setObjectName("linkHint")
        line.addWidget(self.meta, 1)
        body.addLayout(line)
        row.addLayout(body, 1)
        self.action_row = QHBoxLayout()
        self.action_row.setSpacing(2 if compact else 6)
        row.addLayout(self.action_row, 0)

    def update_task(self, task: dict, detail: dict, cover: bytes = b"") -> None:
        fraction, progress_text = progress_parts(detail)
        stage = stage_of(task, detail)
        info = task.get("error") or task.get("import_note") or ""
        if task.get("state") == "running" and progress_text:
            info = progress_text
        elif task.get("state") == "running":
            info = "" if self.compact else tr(STAGES.get(stage, "正在下载"))
        if task.get("state") == "imported":
            result = task.get("import_result", {})
            if result.get("cue_count"):
                info = tr("{count} 条字幕", count=result["cue_count"])
                if result.get("timing_note") and not self.compact:
                    info += " · " + tr(result["timing_note"])
            else:
                info = tr("媒体已导入工程")
            if result.get("warnings"):
                info += " · " + " ".join(result["warnings"])
        if task.get("state") == "partial" and not info:
            info = tr("已保留成功文件，可仅重试字幕或手动导入。")
        if task.get("state") == "paused" and not info:
            info = tr("已暂停；继续时从已下载的部分接着下载。")
        values = (task.get("title") or task["task_id"], tr(STAGES.get(stage, stage)), state_tone(task),
                  info, fraction, stepper_html(task, detail), task.get("state"))
        self.cover.set_image(cover)
        if values != self._rendered:
            self._rendered = values
            self.title.setText(values[0])
            self.state.setText(values[1])
            set_tone(self.state, values[2])
            self.state_text.setText(values[1])
            set_tone(self.state_text, values[2])
            self.meta.setText(info)
            self.meta.setVisible(bool(info))
            running = task.get("state") in ACTIVE
            self.progress.setVisible(running)
            if fraction is None:
                self.progress.setRange(0, 0 if task.get("state") == "running" else 1000)
            else:
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(fraction * 1000))
            self.stepper.setText(values[5])
        self._set_actions(self.available_actions(task))

    @staticmethod
    def available_actions(task: dict) -> list[tuple[str, str, bool]]:
        """(name, label, primary) in display order."""
        state = task.get("state", "")
        subtitles_failed = task.get("mode") in ("both", "subtitles")
        if state == "running":
            return [("pause", "暂停", False), ("cancel", "取消任务", False)]
        if state == "queued":
            return [("cancel", "取消任务", False)]
        if state == "paused":
            return [("resume", "继续", True), ("cancel", "取消任务", False)]
        if state == "pending_import":
            return [("import", "导入工程", True), ("folder", "打开所在文件夹", False)]
        if state == "imported":
            result = task.get("import_result", {})
            actions = [("edit", "进入编辑", True)]
            if result.get("cue_count"):
                actions.append(("ai", "AI 精修…", False))
            return actions + [("folder", "打开所在文件夹", False)]
        if state == "partial":
            actions = [("retry_subtitles", "仅重试字幕", True)] if subtitles_failed else []
            return actions + [("import", "导入已下载部分", not subtitles_failed), ("folder", "打开所在文件夹", False)]
        if state in ("failed", "cancelled"):
            return [("retry", "重试", state == "failed"), ("folder", "打开所在文件夹", False)]
        return []

    def _set_actions(self, actions) -> None:
        key = tuple(actions)
        if key == self._actions_key:
            return
        self._actions_key = key
        while self.action_row.count():
            item = self.action_row.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        texts = 0
        for name, label, primary in actions:
            icon = self.ICONS.get(name)
            if self.compact:
                as_text = primary and texts == 0
            else:
                as_text = primary or name not in ("pause", "cancel", "folder")
            if as_text or not icon:
                widget = button(tr(label), "linkPrimary" if primary and not self.compact else "linkGhost")
                widget.setProperty("small", True)
                texts += 1
            else:
                widget = icon_button(icon, tr(label))
                if self.compact:
                    widget.setProperty("small", True)
            widget.clicked.connect(lambda _=False, n=name: self.action.emit(n, self.task_id))
            self.action_row.addWidget(widget)
