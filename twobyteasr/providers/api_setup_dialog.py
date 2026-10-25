"""「申请与设置 API」: one calm step at a time, then paste, check, save (2026-10-13, redesigned 2026-10-18).

User (2026-10-18): the old page read like a manual. A long provider list sat
on the left (do I have to click or read all of these?), five boxed step cards
looked uncertain, and people might give up on what is a five-minute job. Now:

* on top, the service being set up, about how long it takes, what it costs
  first and that the key stays on this computer; other services sit behind
  “换一家” (a menu, not a list that is always there);
* a progress bar, then one step per page: the official page's screenshot with
  the button to press ringed, two short lines broken by hand, one button that
  opens the page and “做好了，下一步”;
* “把 Key 贴到这里” with the free check; model, addresses, the trial
  recognition and 进阶设置 are in a collapsed “更多设置”; a passing check
  leads to “检查通过，可以保存了”;
* links, account/upload/cost notes and the full tutorial behind “看完整教程”.

The dialog never stores anything itself. ``SetupHost`` (implemented by the
main window) reads the current values and saves through the existing settings
and credential paths, so the old advanced dialog and this guide always agree.
Tests run on worker threads; the paid recognition test runs only after an
explicit confirmation that names the provider, the data and the cost basis.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRectF, QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget,
)

from . import api_setup_catalog as catalog
from . import cloud_api_test as tests
from ..i18n import bind_text, tr, ui_literal
from ..design.main_ui_dialogs import SpringDialog

STATUS_MARKS = {tests.PASS: '✓', tests.FAIL: '✗', tests.UNKNOWN: '?', tests.SKIP: '—'}
STATUS_NAMES = {'ok': tests.PASS, 'fail': tests.FAIL}

OSS_REGIONS = (('cn-hangzhou', '华东1（杭州）'), ('cn-shanghai', '华东2（上海）'), ('cn-beijing', '华北2（北京）'),
               ('cn-shenzhen', '华南1（深圳）'), ('cn-hongkong', '中国香港'), ('ap-southeast-1', '新加坡'))

KIND_LABELS = {'asr': '生成字幕', 'text': '断句、校对、翻译'}
GROUPS = (('语音识别（生成字幕）', 'asr'), ('文字 AI（断句、校对、翻译）', 'text'))


@dataclass
class SetupHost:
    """Callbacks into the main window (kept small so the dialog is testable)."""
    settings: Callable[[], dict]
    saved_key: Callable[[str, str], str]
    saved_oss_credentials: Callable[[], tuple]
    save: Callable[[str, dict, bool], tuple]          # (provider, values, use_as_primary) -> (ok, message)
    open_advanced: Callable[[str], None] | None = None
    open_text_settings: Callable[[str], None] | None = None


def _shrinkable(combo: QComboBox) -> None:
    """Long item labels must not widen the whole page."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(18)


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _colors(theme) -> dict:
    """The few derived colours of this dialog (everything else is a theme token)."""
    from ..design.ui_theme import blend_hex
    success_ink = blend_hex(theme.success, theme.text, 0.3) if theme.is_light else theme.success
    return dict(
        current=blend_hex(theme.surface, theme.accent, 0.5),
        track=blend_hex(theme.surface, theme.border_strong, 0.45),
        success_soft=blend_hex(theme.surface, theme.success, 0.16 if theme.is_light else 0.14),
        success_ink=success_ink,
        accent_soft=blend_hex(theme.surface, theme.accent, 0.16 if theme.is_light else 0.13),
    )


def _lines_html(lines) -> str:
    """Hand-broken lines (2026-10-18: no automatic breaks in the middle of a phrase)."""
    body = '<br>'.join(html.escape(str(tr(line))) for line in lines)
    return f'<div style="line-height:165%">{body}</div>'


class _Runner(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, job):
        super().__init__()
        self.job = job

    def run(self):
        try:
            self.finished.emit(self.job())
        except Exception as exc:  # shown to the user, never swallowed
            from .provider_diagnostics import redact_diagnostics
            self.failed.emit(redact_diagnostics(str(exc))[:600])


class ShotView(QWidget):
    """The official page's screenshot with the button to press ringed (2026-10-18).

    Pictures are light web pages; the ring is drawn here in the theme's
    accent, so one picture serves every theme. A step without a screenshot
    shows its icon on a soft card of the same 16:10 shape instead.
    """
    CAPTION = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('apiSetupShot')
        self.setMinimumSize(280, 175 + self.CAPTION)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pixmap: QPixmap | None = None
        self.ring = None
        self.caption = ''
        self.icon = 'ph.check-circle'

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(440, 275 + self.CAPTION)

    def set_shot(self, shot) -> bool:
        pixmap = QPixmap(str(shot.path())) if shot is not None else QPixmap()
        if pixmap.isNull():
            self.pixmap, self.ring = None, None
            return False
        self.pixmap, self.ring = pixmap, tuple(shot.ring)
        self.caption = str(tr('官网截图 · {value0}', value0=shot.captured))
        self.setToolTip(shot.source)
        self.update()
        return True

    def set_icon(self, name: str) -> None:
        self.pixmap, self.ring, self.icon, self.caption = None, None, name, ''
        self.update()

    def picture_rect(self) -> QRectF:
        room = QRectF(self.rect()).adjusted(1, 1, -1, -1 - self.CAPTION)
        width = min(room.width(), room.height() * 1.6)
        height = width / 1.6
        return QRectF(room.left() + (room.width() - width) / 2, room.top() + (room.height() - height) / 2,
                      width, height)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        colors = _colors(theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = self.picture_rect()
        path = QPainterPath()
        path.addRoundedRect(box, 12, 12)
        if self.pixmap is not None:
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(box, self.pixmap, QRectF(self.pixmap.rect()))
            if not theme.is_light:
                painter.fillRect(box, QColor(0, 0, 0, 22))   # a white page is glaring in a dark dialog
            painter.restore()
            painter.setPen(QPen(QColor(theme.border_strong), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            if self.ring:
                x, y, w, h = self.ring
                ring = QRectF(box.left() + x * box.width(), box.top() + y * box.height(),
                              w * box.width(), h * box.height()).adjusted(-3, -3, 3, 3)
                glow = QColor(theme.accent)
                glow.setAlpha(80)
                painter.setPen(QPen(glow, 7))
                painter.drawRoundedRect(ring, 9, 9)
                painter.setPen(QPen(QColor(theme.accent), 2.5))
                painter.drawRoundedRect(ring, 9, 9)
            if self.caption:
                font = QFont(self.font())
                font.setPixelSize(12)
                painter.setFont(font)
                painter.setPen(QColor(theme.text_muted))
                painter.drawText(QRectF(box.left(), box.bottom() + 4, box.width(), self.CAPTION - 4),
                                 int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.caption)
        else:
            painter.setPen(QPen(QColor(theme.hairline), 1))
            painter.setBrush(QColor(colors['accent_soft']))
            painter.drawPath(path)
            from ..design.themed_icons import cached_icon_pixmap
            side = int(min(box.width(), box.height()) * 0.36)
            icon = cached_icon_pixmap(self.icon, theme.accent_text, QSize(side, side),
                                      device_pixel_ratio=self.devicePixelRatioF())
            painter.drawPixmap(int(box.center().x() - side / 2), int(box.center().y() - side / 2), icon)
        painter.end()


class StepProgress(QWidget):
    """Segments with a word under each; done, current and still to do (2026-10-18)."""
    step_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('apiSetupProgress')
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.bars, self.labels = [], []

    def set_steps(self, labels) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)   # gone now, not at the next event loop turn
                widget.deleteLater()
        self.bars, self.labels = [], []
        for index, text in enumerate(labels):
            column = QWidget()
            body = QVBoxLayout(column)
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(6)
            bar = QFrame()
            bar.setObjectName('apiSetupBar')
            bar.setFixedHeight(6)
            body.addWidget(bar)
            label = QPushButton(tr(text))
            label.setObjectName('apiSetupBarLabel')
            label.setFlat(True)
            label.setAutoDefault(False)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            label.clicked.connect(lambda _=False, i=index: self.step_clicked.emit(i))
            body.addWidget(label)
            self.row.addWidget(column, 1)
            self.bars.append(bar)
            self.labels.append(label)

    def set_state(self, current: int, done) -> None:
        for index, (bar, label) in enumerate(zip(self.bars, self.labels)):
            state = 'done' if done[index] else ('current' if index == current else 'todo')
            for widget in (bar, label):
                widget.setProperty('state', state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)


def dialog_qss(theme) -> str:
    c = _colors(theme)
    t = theme
    return f"""
QLabel#apiSetupTitle {{ color: {t.text}; font-size: 18px; font-weight: 700; background: transparent; }}
QLabel#apiSetupAvatar {{ background: {c['accent_soft']}; border-radius: 14px; }}
QLabel#apiSetupName {{ color: {t.text}; font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#apiSetupSite {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
QLabel#apiSetupFactText {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QPushButton#apiSetupSwitch {{ background: transparent; color: {t.text_secondary}; border: 1px solid {t.border_strong};
    border-radius: 16px; min-height: 30px; max-height: 30px; padding: 0 12px 0 14px; font-size: 13px; }}
QPushButton#apiSetupSwitch:hover {{ background: {t.selected}; color: {t.text}; }}
QPushButton#apiSetupSwitch::menu-indicator {{ image: none; width: 0; }}
QFrame#apiSetupBar {{ background: {c['track']}; border: 0; border-radius: 3px; }}
QFrame#apiSetupBar[state="done"] {{ background: {t.accent}; }}
QFrame#apiSetupBar[state="current"] {{ background: {c['current']}; }}
QPushButton#apiSetupBarLabel {{ background: transparent; border: 0; padding: 0; min-height: 20px; max-height: 20px;
    text-align: left; color: {t.text_muted}; font-size: 13px; font-weight: 500; }}
QPushButton#apiSetupBarLabel[state="done"] {{ color: {t.text}; }}
QPushButton#apiSetupBarLabel[state="current"] {{ color: {t.text}; font-weight: 700; }}
QPushButton#apiSetupBarLabel:hover {{ color: {t.accent_text}; }}
QLabel#apiSetupStepOf {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QLabel#apiSetupStepTitle, QLabel#apiSetupDoneTitle {{ color: {t.text}; font-size: 23px; font-weight: 700;
    background: transparent; }}
QLabel#apiSetupStepLines {{ color: {t.text_secondary}; font-size: 15px; background: transparent; }}
QFrame#apiSetupNote {{ background: {t.panel}; border: 0; border-radius: 14px; }}
QFrame#apiSetupNote[noteKind="free"] {{ background: {c['success_soft']}; }}
QFrame#apiSetupNote[noteKind="warn"] {{ background: {t.warning_soft}; }}
QLabel#apiSetupNoteText {{ color: {t.text_secondary}; font-size: 13px; font-weight: 500; background: transparent; }}
QFrame#apiSetupNote[noteKind="free"] QLabel#apiSetupNoteText {{ color: {c['success_ink']}; }}
QFrame#apiSetupNote[noteKind="warn"] QLabel#apiSetupNoteText {{ color: {t.warning}; }}
QPushButton#apiSetupNext, QPushButton#apiSetupSkip, QPushButton#apiSetupTrialLink {{ background: transparent;
    border: 1px solid transparent; color: {t.accent_text}; font-size: 14px; font-weight: 500; padding: 0 8px;
    min-height: 36px; border-radius: 10px; }}
QPushButton#apiSetupNext:hover, QPushButton#apiSetupSkip:hover, QPushButton#apiSetupTrialLink:hover {{
    background: {t.selected}; color: {t.text}; }}
QPushButton#apiSetupNext:focus, QPushButton#apiSetupSkip:focus, QPushButton#apiSetupTrialLink:focus {{
    border-color: {t.focus}; }}
QPushButton#apiSetupMoreToggle, QPushButton#apiSetupDetailsToggle {{ background: transparent; border: 0;
    color: {t.text_secondary}; font-size: 13px; padding: 0 4px; min-height: 32px; text-align: left; }}
QPushButton#apiSetupMoreToggle:hover {{ color: {t.text}; }}
QLabel#apiSetupFreeNote, QLabel#apiSetupAfterNote {{ color: {t.text_muted}; font-size: 13px; background: transparent; }}
QFrame#apiSetupMoreBox {{ background: {t.panel}; border: 1px solid {t.hairline}; border-radius: 14px; }}
QFrame#apiSetupMoreBox QLabel {{ background: transparent; }}
QLabel#apiSetupDoneIcon {{ background: {c['success_soft']}; border-radius: 48px; }}
QFrame#apiSetupFooter {{ background: transparent; border: 0; border-top: 1px solid {t.hairline}; }}
QLineEdit#apiSetupField_api_key {{ font-size: 15px; }}
"""


class ApiSetupDialog(SpringDialog):
    ENTRY_ANIMATED = False

    def __init__(self, parent, host: SetupHost, *, kind: str = 'asr', initial: str = '', show_advanced: bool = False):
        self._built = False
        super().__init__(parent)
        self.host = host
        self.kind = kind
        self.show_advanced = bool(show_advanced)
        self._threads = []
        self._fields = {}
        self._field_rows = {}
        self._form_of = {}
        self._locked_widgets = []
        self._lockable_widgets = []
        self._result_labels = {}
        self._icon_buttons = []
        self._guide = None
        self._last_price = {}
        self.oss_button = None
        self.address_view = None
        self._walk = []
        self._done = []
        self._index = 0
        self._pages = []
        self._page_kind = ''
        self._return_to = None
        self.setObjectName('apiSetupDialog')
        bind_text(self, '申请与设置 API', property='windowTitle')
        self.setMinimumWidth(680)
        self.resize(840, 580)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        from ..design.presentation import button_role, glyph_button

        header = QHBoxLayout()
        header.setContentsMargins(28, 14, 14, 0)
        header.setSpacing(6)
        title = QLabel(tr('申请与设置 API'))
        title.setObjectName('apiSetupTitle')
        header.addWidget(title, 1)
        # 2026-10-15: the picture explainer (what a key is, top up, paste it in).
        key_help = button_role(QPushButton(tr('API Key 是什么？')), 'ghost', size='compact')
        key_help.setObjectName('apiSetupExplainer')
        key_help.clicked.connect(self._explain_api_key)
        self._icon(key_help, 'ph.question', 'text_secondary')
        header.addWidget(key_help)
        close = glyph_button(button_role(QPushButton('×'), 'ghost'))
        bind_text(close, '关闭', property='accessibleName')
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        outer.addLayout(header)

        provider = QHBoxLayout()
        provider.setContentsMargins(28, 12, 28, 0)
        provider.setSpacing(14)
        self.avatar = QLabel()
        self.avatar.setObjectName('apiSetupAvatar')
        self.avatar.setFixedSize(46, 46)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        provider.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        about = QVBoxLayout()
        about.setSpacing(3)
        names = QHBoxLayout()
        names.setSpacing(10)
        self.name_label = QLabel()
        self.name_label.setObjectName('apiSetupName')
        names.addWidget(self.name_label)
        self.site_label = QLabel()
        self.site_label.setObjectName('apiSetupSite')
        names.addWidget(self.site_label)
        # 2026-10-25: 千问AI平台 (中国站) / Qwen Cloud (国际站) are one entry.
        self._qwen_site = None
        self.qwen_site_box = QComboBox()
        self.qwen_site_box.setObjectName('apiSetupQwenSite')
        for site, label in catalog.QWEN_SITES:
            self.qwen_site_box.addItem(tr(label), site)
        self.qwen_site_box.setVisible(False)
        self.qwen_site_box.currentIndexChanged.connect(self._choose_qwen_site)
        names.addWidget(self.qwen_site_box)
        names.addStretch(1)
        about.addLayout(names)
        self.facts = QHBoxLayout()
        self.facts.setSpacing(16)
        about.addLayout(self.facts)
        provider.addLayout(about, 1)
        self.switch_button = QPushButton(tr('换一家'))
        self.switch_button.setObjectName('apiSetupSwitch')
        self.switch_button.setAutoDefault(False)
        self.switch_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._icon(self.switch_button, 'ph.caret-down', 'text_secondary')
        self.provider_menu = QMenu(self.switch_button)
        self.provider_menu.setObjectName('apiSetupProviderMenu')
        # The button runs right-to-left only to put its caret on the right; the menu must not inherit it.
        self.provider_menu.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.provider_menu.aboutToShow.connect(self._fill_provider_menu)
        self.switch_button.setMenu(self.provider_menu)
        provider.addWidget(self.switch_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(provider)

        self.progress = StepProgress()
        self.progress.step_clicked.connect(self._go)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(28, 18, 28, 0)
        progress_row.addWidget(self.progress)
        outer.addLayout(progress_row)

        self.stack = QStackedWidget()
        self.stack.setObjectName('apiSetupStack')
        stack_row = QHBoxLayout()
        stack_row.setContentsMargins(28, 16, 28, 14)
        stack_row.addWidget(self.stack)
        outer.addLayout(stack_row, 1)

        footer_frame = QFrame()
        footer_frame.setObjectName('apiSetupFooter')
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(16, 10, 18, 10)
        footer.setSpacing(6)
        self.prev_button = button_role(QPushButton(tr('上一步')), 'ghost')
        self.prev_button.setObjectName('apiSetupPrev')
        self._icon(self.prev_button, 'ph.arrow-left', 'text_secondary')
        self.prev_button.clicked.connect(self._back)
        footer.addWidget(self.prev_button)
        self.tutorial_button = button_role(QPushButton(tr('看完整教程')), 'ghost')
        self.tutorial_button.setObjectName('apiSetupTutorial')
        self._icon(self.tutorial_button, 'ph.book-open', 'text_secondary')
        self.tutorial_button.clicked.connect(self._show_tutorial)
        footer.addWidget(self.tutorial_button)
        self.status = QLabel('')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.skip_button = QPushButton(tr('已经有 Key？直接贴上'))
        self.skip_button.setObjectName('apiSetupSkip')
        self.skip_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._icon(self.skip_button, 'ph.arrow-right', 'accent_text')
        self.skip_button.clicked.connect(lambda: self._go(len(self._walk) - 1))
        footer.addWidget(self.skip_button)
        self.save_button = button_role(QPushButton(tr('保存')), 'secondary')
        self.save_button.clicked.connect(lambda: self._save(False))
        footer.addWidget(self.save_button)
        self.save_primary_button = button_role(QPushButton(tr('保存并用于识别')), 'primary')
        self.save_primary_button.clicked.connect(lambda: self._save(True))
        footer.addWidget(self.save_primary_button)
        for button in (self.prev_button, self.tutorial_button, self.skip_button, self.save_button,
                       self.save_primary_button, key_help):
            button.setAutoDefault(False)
        outer.addWidget(footer_frame)
        # 进阶设置… lives in “更多设置” of each paste page; one button, re-parented there.
        self.advanced_button = button_role(QPushButton(tr('进阶设置…')), 'ghost', size='compact')
        self.advanced_button.setObjectName('apiSetupAdvanced')
        self.advanced_button.setAutoDefault(False)
        self.advanced_button.clicked.connect(self._open_advanced)
        self.more_toggle = None
        self._chrome_icons = len(self._icon_buttons)   # header/footer icons; page icons follow
        self._built = True
        self._apply_theme()
        self._select_initial(initial)

    # ------------------------------------------------------------- theme
    def refresh_theme_palette(self) -> None:
        super().refresh_theme_palette()
        # SpringDialog carries the app sheet itself; this dialog's rules go after it.
        self._base_sheet = self.styleSheet()
        if getattr(self, '_built', False):
            self._apply_theme()

    def _icon(self, button, name: str, color: str) -> None:
        self._icon_buttons.append((button, name, color))
        if getattr(self, '_built', False):
            self._paint_icon(button, name, color)

    def _paint_icon(self, button, name, color) -> None:
        import qtawesome as qta
        theme = _theme()
        value = {'text_secondary': theme.text_secondary, 'accent_text': theme.accent_text,
                 'on_accent': theme.text_on_accent, 'text': theme.text}.get(color, color)
        try:
            button.setIcon(qta.icon(name, color=value, color_active=value, color_disabled=theme.disabled))
        except Exception:  # an icon font that failed to load must not break the dialog
            return
        button.setIconSize(QSize(16, 16))

    def _apply_theme(self) -> None:
        theme = _theme()
        self.setStyleSheet(getattr(self, '_base_sheet', '') + dialog_qss(theme))
        for button, name, color in list(self._icon_buttons):
            self._paint_icon(button, name, color)
        if self.more_toggle is not None:
            self._paint_icon(self.more_toggle, 'ph.caret-down' if self.more_toggle.isChecked() else 'ph.caret-right',
                             'text_secondary')
        if self._guide is not None:
            self._show_header(self._guide)
        for shot in self.findChildren(ShotView):
            shot.update()

    def _pixmap(self, name: str, color: str, size: int) -> QPixmap:
        from ..design.themed_icons import cached_icon_pixmap
        return cached_icon_pixmap(name, color, QSize(size, size), device_pixel_ratio=self.devicePixelRatioF())

    def _explain_api_key(self):
        from ..app.api_key_explainer import open_api_key_explainer
        open_api_key_explainer(self, offer_setup=False)

    # ------------------------------------------------------- the provider
    def _guides(self, kind: str):
        source = catalog.ASR_GUIDES if kind == 'asr' else catalog.TEXT_GUIDES
        return [catalog.QWEN_SITE_GUIDES[self._current_qwen_site()] if guide.site_variant else guide
                for guide in source if self.show_advanced or not guide.advanced_only]

    def _current_qwen_site(self) -> str:
        """The Qwen site shown: chosen here, else the saved address, else the interface language."""
        if self._qwen_site is None:
            settings = self.host.settings() or {}
            models = settings.get('models', {}) if isinstance(settings, dict) else {}
            saved = models.get('qwen_asr_api_provider') == 'qwen_cloud_filetrans'
            self._qwen_site = catalog.qwen_site_for(str(models.get('qwen_asr_api_url') or '') if saved else '')
        return self._qwen_site

    def _choose_qwen_site(self, index: int) -> None:
        site = self.qwen_site_box.itemData(index)
        if not site or site == self._qwen_site or self._guide is None or not self._guide.site_variant:
            return
        self._qwen_site = site
        self._show(catalog.QWEN_SITE_GUIDES[site])

    def _fill_provider_menu(self) -> None:
        """“换一家” (2026-10-18): the provider list only when asked for, with a few honest words each."""
        menu = self.provider_menu
        menu.clear()
        for index, (label, kind) in enumerate(GROUPS):
            if index:
                menu.addSeparator()
            head = menu.addAction(tr(label))
            head.setEnabled(False)
            font = QFont(head.font())
            font.setBold(True)
            head.setFont(font)
            for guide in self._guides(kind):
                text = str(tr(guide.name))
                if guide.tag:
                    text += '\t' + str(tr(guide.tag))
                action = menu.addAction(text)
                action.setCheckable(True)
                action.setChecked(self._guide is guide)
                action.setData((guide.kind, guide.key))
                action.triggered.connect(lambda _=False, g=guide: self.choose(g.kind, g.key))
        if not self.show_advanced:
            menu.addSeparator()
            more = menu.addAction(tr('更多：自架接口、待验证服务'))
            more.triggered.connect(self._reveal_advanced)

    def _reveal_advanced(self) -> None:
        self.show_advanced = True
        QTimer.singleShot(0, self.switch_button.showMenu)

    def provider_choices(self) -> list:
        """(kind, key) of every service the menu offers, in order (tests, audits)."""
        return [(guide.kind, guide.key) for _label, kind in GROUPS for guide in self._guides(kind)]

    def _select_initial(self, initial: str):
        guide = catalog.guide_for(initial, self.kind) if initial else None
        if guide is None:
            guide = next(iter(self._guides(self.kind)), None)
        elif guide.advanced_only:
            self.show_advanced = True   # an advanced service the user already uses is shown, not swapped
        if guide is not None:
            self.choose(guide.kind, guide.key)

    def choose(self, kind: str, key: str) -> None:
        guide = catalog.guide_for(key, kind)
        if guide is None:
            return
        if guide.site_variant:
            guide = catalog.QWEN_SITE_GUIDES[self._current_qwen_site()]
        if guide.advanced_only:
            self.show_advanced = True
        self._show(guide)

    def _show_header(self, guide) -> None:
        theme = _theme()
        self.avatar.setPixmap(self._pixmap('mdi6.waveform' if guide.kind == 'asr' else 'ph.chat-circle-text',
                                           theme.accent_text, 24))
        self.name_label.setText(tr(guide.name))
        self.name_label.setToolTip(ui_literal(guide.title + '\n' + guide.role))
        self.site_label.setText(' · '.join(str(tr(part)) for part in (guide.site, KIND_LABELS[guide.kind]) if part))
        self.qwen_site_box.setVisible(bool(guide.site_variant))
        if guide.site_variant:
            self.qwen_site_box.blockSignals(True)
            self.qwen_site_box.setCurrentIndex(max(0, self.qwen_site_box.findData(guide.site_variant)))
            self.qwen_site_box.blockSignals(False)
        while self.facts.count():
            item = self.facts.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        facts = []
        if guide.minutes:
            facts.append(('ph.clock', tr('约 {value0} 分钟', value0=guide.minutes)))
        if guide.money:
            facts.append(('ph.gift' if guide.free_trial or '免费' in guide.money else 'ph.coin', tr(guide.money)))
        if guide.key != 'cli_accounts':
            facts.append(('ph.lock-simple', tr('Key 只存在本机')))
        for icon, text in facts:
            fact = QWidget()
            row = QHBoxLayout(fact)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(5)
            mark = QLabel()
            mark.setPixmap(self._pixmap(icon, theme.text_secondary, 15))
            row.addWidget(mark)
            label = QLabel(text)
            label.setObjectName('apiSetupFactText')
            row.addWidget(label)
            self.facts.addWidget(fact)
        self.facts.addStretch(1)

    # ------------------------------------------------------------- content
    def _show(self, guide):
        self._guide = guide
        self._fields = {}
        self._field_rows = {}
        self._form_of = {}
        self._locked_widgets = []      # hint/address rows of a locked prefilled field
        self._lockable_widgets = []
        self._result_labels = {}
        self._last_price = {}
        self.oss_button = None
        self.address_view = None
        self._return_to = None
        self._icon_buttons = self._icon_buttons[:self._chrome_icons]
        self.more_toggle = None
        self.advanced_button.setParent(None)
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.setParent(None)
            page.deleteLater()
        self._show_header(guide)
        go_fill = None
        if guide.kind == 'text' and self.host.open_text_settings is not None:
            def go_fill():
                self.accept()
                self.host.open_text_settings(guide.key)
        self._go_fill = go_fill
        self._walk = catalog.walkthrough(guide, can_fill=go_fill is not None)
        self._pages = []
        total = len(self._walk)
        for index, step in enumerate(self._walk):
            if step.role == 'paste':
                page = self._paste_page(guide, step, index, total)
            elif step.role == 'fill':
                page = self._fill_page(guide, step, index, total)
            else:
                page = self._step_page(step, index, total)
            self._pages.append(page)
            self.stack.addWidget(page)
        if not self._walk:
            # 自定义 / 账号登录类: no official steps; the form or the notes directly.
            page = self._paste_page(guide, None, 0, 0) if guide.kind == 'asr' else self._notes_page(guide)
            self._pages.append(page)
            self.stack.addWidget(page)
        self._done_page_widget = self._done_page(guide) if guide.kind == 'asr' else None
        if self._done_page_widget is not None:
            self.stack.addWidget(self._done_page_widget)
        self._tutorial_page_widget = self._tutorial_page(guide)
        self.stack.addWidget(self._tutorial_page_widget)
        self.progress.set_steps([step.label for step in self._walk])
        self.progress.setVisible(bool(self._walk))
        self._done = [False] * len(self._walk)
        self.skip_button.setText(tr('已经有 Key？直接贴上') if guide.kind == 'asr' else tr('已经有 Key？直接去填写'))
        key_field = self._fields.get('api_key')
        if isinstance(key_field, QLineEdit):
            key_field.textChanged.connect(lambda _t: self._update_steps())
            key_field.returnPressed.connect(self._run_free)
        start = 0
        if self._walk and self._key_present():
            start = len(self._walk) - 1    # a saved key: straight to “贴上检查”
        # Pages built after the sheet was set keep their first polish (fonts
        # stayed 14 px offscreen and in the window); set it again so they follow it.
        self.setStyleSheet(self.styleSheet())
        self.status.setText('')
        self._update_steps()
        self._go(start)

    def _step_page(self, step, index, total):
        """One web step: the official page's screenshot beside two lines and one button."""
        page = QWidget()
        page.setObjectName('apiSetupStepPage')
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)
        shot = ShotView()
        from ..app.guide_steps import STEP_ICONS
        if not shot.set_shot(step.shot):
            shot.set_icon(STEP_ICONS.get(step.role, 'ph.check-circle'))
        row.addWidget(shot, 11)
        column = QVBoxLayout()
        column.setSpacing(10)
        column.addStretch(1)
        self._step_texts(column, step, index, total)
        buttons = QVBoxLayout()
        buttons.setSpacing(2)
        buttons.setContentsMargins(0, 8, 0, 0)
        from ..design.presentation import button_role
        if step.action and step.url:
            action = button_role(QPushButton(tr(step.action)), 'primary', size='large')
            action.setObjectName(f'apiSetupOpen_{index}')
            action.setAutoDefault(False)
            action.setToolTip(step.url)
            action.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self._icon(action, 'ph.arrow-square-out', 'on_accent')
            action.clicked.connect(lambda _=False, url=step.url: QDesktopServices.openUrl(QUrl(url)))
            buttons.addLayout(self._left(action))
        nxt = QPushButton(tr('做好了，下一步'))
        nxt.setObjectName(f'apiSetupNext')
        nxt.setProperty('step', index)
        nxt.setAutoDefault(False)
        nxt.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._icon(nxt, 'ph.arrow-right', 'accent_text')
        nxt.clicked.connect(lambda _=False, i=index: self._finish_step(i))
        buttons.addLayout(self._left(nxt))
        column.addLayout(buttons)
        column.addStretch(1)
        row.addLayout(column, 9)
        return page

    @staticmethod
    def _left(widget):
        """A row holding ``widget`` at its natural width on the left.

        Its icon sits right of the text (right-to-left direction), and an
        alignment flag would then mirror too and push it to the right edge.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget)
        row.addStretch(1)
        return row

    def _step_texts(self, column, step, index, total):
        if total:
            step_of = QLabel(tr('第 {value0} 步，共 {value1} 步', value0=index + 1, value1=total))
            step_of.setObjectName('apiSetupStepOf')
            column.addWidget(step_of)
        title = QLabel(tr(step.title))
        title.setObjectName('apiSetupStepTitle')
        title.setWordWrap(True)
        column.addWidget(title)
        if step.lines:
            lines = QLabel(_lines_html(step.lines))
            lines.setObjectName('apiSetupStepLines')
            lines.setTextFormat(Qt.TextFormat.RichText)
            lines.setWordWrap(True)
            column.addWidget(lines)
        if step.note:
            column.addWidget(self._note(step.note, step.note_kind))

    def _note(self, text, kind):
        note = QFrame()
        note.setObjectName('apiSetupNote')
        note.setProperty('noteKind', kind or '')
        row = QHBoxLayout(note)
        row.setContentsMargins(11, 5, 13, 5)
        row.setSpacing(6)
        theme, colors = _theme(), _colors(_theme())
        color = {'free': colors['success_ink'], 'warn': theme.warning}.get(kind, theme.text_secondary)
        mark = QLabel()
        mark.setPixmap(self._pixmap({'free': 'ph.gift', 'warn': 'ph.warning-circle'}.get(kind, 'ph.info'), color, 15))
        row.addWidget(mark)
        label = QLabel(tr(text))
        label.setObjectName('apiSetupNoteText')
        label.setWordWrap(True)
        row.addWidget(label, 1)
        return note

    def _fill_page(self, guide, step, index, total):
        """Text AI: the key is entered and tested in “AI 智能断句设置” (2026-10-14)."""
        page = QWidget()
        page.setObjectName('apiSetupFillPage')
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)
        shot = ShotView()
        shot.set_icon('ph.chat-circle-text')
        row.addWidget(shot, 11)
        column = QVBoxLayout()
        column.setSpacing(10)
        column.addStretch(1)
        self._step_texts(column, step, index, total)
        if step.action and self._go_fill is not None:
            from ..design.presentation import button_role
            go = button_role(QPushButton(tr(step.action)), 'primary', size='large')
            go.setObjectName('apiSetupFill')
            go.setAutoDefault(False)
            go.clicked.connect(self._go_fill)
            column.addSpacing(8)
            column.addWidget(go, 0, Qt.AlignmentFlag.AlignLeft)
        column.addStretch(1)
        row.addLayout(column, 9)
        return page

    def _notes_page(self, guide):
        step = catalog.WalkStep('fill', '', guide.name, (), catalog.FILL_NOTE)
        page = self._fill_page(guide, step, 0, 0)
        role = QLabel(tr(guide.role))
        role.setObjectName('apiSetupStepLines')
        role.setWordWrap(True)
        column = page.layout().itemAt(1).layout()
        column.insertWidget(2, role)
        return page

    def _paste_page(self, guide, step, index, total):
        """“把 Key 贴到这里”: the fields, the free check, results, and “更多设置” folded."""
        self.scroll = QScrollArea()
        self.scroll.setObjectName('apiSetupPasteScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName('apiSetupPage')
        center = QHBoxLayout(inner)
        center.setContentsMargins(0, 0, 8, 0)
        center.addStretch(1)
        body_widget = QWidget()
        body_widget.setMaximumWidth(600)
        body_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        center.addWidget(body_widget, 20)
        center.addStretch(1)
        if total:
            step_of = QLabel(tr('第 {value0} 步，共 {value1} 步', value0=index + 1, value1=total))
            step_of.setObjectName('apiSetupStepOf')
            body.addWidget(step_of)
        title = QLabel(tr(step.title if step is not None else catalog.paste_title(guide)))
        title.setObjectName('apiSetupStepTitle')
        title.setWordWrap(True)
        body.addWidget(title)
        main = QFormLayout()
        main.setHorizontalSpacing(14)
        main.setVerticalSpacing(6)
        main.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        body.addLayout(main)
        self._more_box = QFrame()
        self._more_box.setObjectName('apiSetupMoreBox')
        more_layout = QVBoxLayout(self._more_box)
        more_layout.setContentsMargins(16, 12, 16, 12)
        more_layout.setSpacing(8)
        more = QFormLayout()
        more.setHorizontalSpacing(14)
        more.setVerticalSpacing(6)
        more.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        more_layout.addLayout(more)
        self._main_form, self._more_form = main, more
        self._form(guide)
        body.addLayout(self._check_row(guide))
        body.addWidget(self._results_widget(guide))
        toggle = QPushButton()
        toggle.setObjectName('apiSetupMoreToggle')
        toggle.setCheckable(True)
        toggle.setAutoDefault(False)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_toggle = toggle
        has_more = more.rowCount() > 0

        def show_more(shown):
            self._more_box.setVisible(shown)
            self._paint_icon(toggle, 'ph.caret-down' if shown else 'ph.caret-right', 'text_secondary')
        toggle.setText(tr('更多设置（模型、服务地址）') if has_more else tr('更多设置'))
        toggle.toggled.connect(show_more)
        body.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        extras = QHBoxLayout()
        extras.setSpacing(4)
        from ..design.presentation import button_role
        paid = button_role(QPushButton(tr('试识别一小段…')), 'ghost', size='compact')
        paid.setObjectName('apiSetupTest_paid')
        paid.setAutoDefault(False)
        paid.setToolTip(tr('免费检查不上传音频；“试识别一小段”成功，才说明真的能用（会按用量计费）。'))
        paid.clicked.connect(self._run_recognition)
        extras.addWidget(paid)
        if self.host.open_advanced is not None:
            extras.addWidget(self.advanced_button)
        extras.addStretch(1)
        more_layout.addLayout(extras)
        body.addWidget(self._more_box)
        show_more(False)
        body.addStretch(1)
        self.scroll.setWidget(inner)
        self._apply_field_visibility()
        return self.scroll

    def _check_row(self, guide):
        from ..design.presentation import button_role
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(10)
        free = button_role(QPushButton(tr('免费检查')), 'primary', size='large')
        free.setObjectName('apiSetupTest_free')
        free.setAutoDefault(False)
        free.setToolTip(tr('免费检查（不上传音频）'))
        self._icon(free, 'ph.check-bold', 'on_accent')
        free.clicked.connect(self._run_free)
        row.addWidget(free)
        if guide.needs_storage:
            oss = button_role(QPushButton(tr('检查 OSS')), 'secondary', size='large')
            oss.setObjectName('apiSetupTest_oss')
            oss.setAutoDefault(False)
            oss.setToolTip(tr('检查 OSS（上传很小的测试文件后删除）'))
            oss.clicked.connect(self._run_oss)
            row.addWidget(oss)
            self.oss_button = oss
        note = QLabel(tr('不上传音频，也不收费'))
        note.setObjectName('apiSetupFreeNote')
        note.setWordWrap(True)
        row.addWidget(note, 1)
        return row

    def _done_page(self, guide):
        page = QWidget()
        page.setObjectName('apiSetupDonePage')
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)
        row.addStretch(1)
        theme, colors = _theme(), _colors(_theme())
        icon = QLabel()
        icon.setObjectName('apiSetupDoneIcon')
        icon.setFixedSize(96, 96)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(self._pixmap('ph.check-bold', colors['success_ink'], 44))
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(10)
        column.addStretch(1)
        title = QLabel(tr('检查通过，可以保存了'))
        title.setObjectName('apiSetupDoneTitle')
        title.setWordWrap(True)
        column.addWidget(title)
        lines = QLabel('<div style="line-height:165%">' + html.escape(str(tr('Key 有效，模型也能用。'))) + '<br>'
                       + html.escape(str(tr('保存后，生成字幕就会用 {value0}。', value0=tr(guide.name)))) + '</div>')
        lines.setObjectName('apiSetupStepLines')
        lines.setTextFormat(Qt.TextFormat.RichText)
        lines.setWordWrap(True)
        column.addWidget(lines)
        if guide.after_note:
            after = QLabel(tr(guide.after_note))
            after.setObjectName('apiSetupAfterNote')
            after.setWordWrap(True)
            column.addWidget(after)
        trial = QPushButton(tr('想百分之百确定？试识别一小段…'))
        trial.setObjectName('apiSetupTrialLink')
        trial.setAutoDefault(False)
        trial.clicked.connect(self._run_recognition)
        column.addWidget(trial, 0, Qt.AlignmentFlag.AlignLeft)
        column.addStretch(1)
        holder = QWidget()
        holder.setMaximumWidth(460)
        holder.setLayout(column)
        row.addWidget(holder, 3)
        row.addStretch(1)
        return page

    def _tutorial_page(self, guide):
        """Notes, links and the full tutorial, one click away (“看完整教程”)."""
        scroll = QScrollArea()
        scroll.setObjectName('apiSetupDetails')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 8, 0)
        details_layout.setSpacing(12)
        name = QLabel(tr(guide.title))
        name.setObjectName('apiSetupStepTitle')
        name.setWordWrap(True)
        details_layout.addWidget(name)
        role = QLabel(tr(guide.role))
        role.setWordWrap(True)
        details_layout.addWidget(role)
        facts = []
        if guide.account_note:
            facts.append(tr('需要的账号：') + tr(guide.account_note))
        if guide.uploads:
            facts.append(tr('会传送的数据：') + tr(guide.uploads))
        if guide.cost:
            facts.append(tr('费用：') + tr(guide.cost))
        if guide.status_note:
            facts.append(tr('兔白验证状态：') + tr(guide.status_note))
        if facts:
            info = QLabel('\n'.join(facts))
            info.setObjectName('muted')
            info.setWordWrap(True)
            info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details_layout.addWidget(info)
        if guide.links:
            details_layout.addWidget(self._links(guide))
        guide_box = QTextBrowser()
        guide_box.setObjectName('apiSetupGuide')
        guide_box.setOpenExternalLinks(True)
        text = guide.guide_text()
        if text.startswith('<!--'):
            # The generated 繁體 tutorials start with a "generated from" comment.
            text = text.partition(chr(10))[2]
        if text.startswith('# '):
            # The page already shows the provider name; keep the guide body only.
            text = text.partition(chr(10))[2]
        guide_box.setMarkdown(text)
        guide_box.setMinimumHeight(300)
        guide_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        details_layout.addWidget(guide_box, 1)
        scroll.setWidget(details)
        return scroll

    # ---------------------------------------------------------- navigation
    def _go(self, index: int) -> None:
        if not self._pages:
            return
        index = max(0, min(int(index), len(self._pages) - 1))
        self._index = index
        self._return_to = None
        page = self._pages[index]
        self.stack.setCurrentWidget(page)
        if self._walk:
            role = self._walk[index].role
            self._page_kind = 'step' if role not in {'paste', 'fill'} else role
        else:
            self._page_kind = 'paste' if self._guide.kind == 'asr' else 'notes'
        self._refresh_chrome()
        target = None
        if self._page_kind == 'paste':
            target = next((w for w in self._fields.values() if isinstance(w, QLineEdit) and w.isEnabled()
                           and w.isVisibleTo(self) and not w.text().strip()), self._fields.get('api_key'))
        else:
            target = page.findChild(QPushButton, f'apiSetupOpen_{index}') or page.findChild(QPushButton, 'apiSetupFill') \
                or page.findChild(QPushButton, 'apiSetupNext')
        if target is not None:
            target.setFocus()

    def _finish_step(self, index: int) -> None:
        if 0 <= index < len(self._done):
            self._done[index] = True
        self._go(index + 1)

    def _back(self) -> None:
        if self._page_kind in {'done', 'tutorial'}:
            back = self._return_to
            if back is not None:
                self._return_to = None
                if back == 'done':
                    self._show_done()
                else:
                    self._go(back)
                return
            self._go(len(self._pages) - 1 if self._page_kind == 'done' else self._index)
            return
        self._go(self._index - 1)

    def _show_tutorial(self) -> None:
        back = 'done' if self._page_kind == 'done' else self._index
        self.stack.setCurrentWidget(self._tutorial_page_widget)
        self._page_kind = 'tutorial'
        self._return_to = back
        self._refresh_chrome()

    def _show_done(self) -> None:
        if self._done_page_widget is None:
            return
        if self._done:
            self._done = [True] * len(self._done)
        self.stack.setCurrentWidget(self._done_page_widget)
        self._page_kind = 'done'
        self._refresh_chrome()
        self.save_primary_button.setFocus()

    def _refresh_chrome(self) -> None:
        kind = self._page_kind
        walk = bool(self._walk)
        current = self._index if kind in {'step', 'paste', 'fill'} else len(self._walk)
        self.progress.set_state(current, self._done if kind != 'done' else [True] * len(self._done))
        self.prev_button.setText(tr('返回修改') if kind == 'done' else (tr('返回') if kind == 'tutorial' else tr('上一步')))
        self.prev_button.setVisible(kind in {'done', 'tutorial'} or (walk and self._index > 0))
        self.tutorial_button.setVisible(kind != 'tutorial')
        self.skip_button.setVisible(kind == 'step' and walk)
        is_asr = self._guide is not None and self._guide.kind == 'asr'
        for button in (self.save_button, self.save_primary_button):
            button.setVisible(is_asr and kind in {'paste', 'done'})
        # “保存并用于识别” is the main action once the check passed; before
        # that the free check is (2026-10-18: one emphasized button per page).
        role = 'primary' if kind == 'done' else 'secondary'
        if self.save_primary_button.property('buttonRole') != role:
            self.save_primary_button.setProperty('buttonRole', role)
            self.save_primary_button.style().unpolish(self.save_primary_button)
            self.save_primary_button.style().polish(self.save_primary_button)
        self.save_button.setText(tr('只保存') if kind == 'done' else tr('保存'))

    def _key_present(self) -> bool:
        key = self._fields.get('api_key')
        if not isinstance(key, QLineEdit):
            return False
        spec = next((f for f in self._guide.fields if f.key == 'api_key'), catalog.Field('api_key', '', ''))
        return bool(key.text().strip() or self._saved_secret(self._guide, spec, ''))

    def _update_steps(self, *, checked: bool | None = None):
        """A pasted (or saved) key means the web steps are behind the user."""
        if not self._walk:
            return
        last = len(self._walk) - 1
        if self._walk[last].role == 'paste' and self._key_present():
            for index in range(last):
                self._done[index] = True
        if checked is not None:
            self._done[last] = bool(checked)
        if self._page_kind in {'step', 'paste', 'fill'}:
            self.progress.set_state(self._index, self._done)

    def _links(self, guide):
        box = QWidget()
        # The page must never be wider than the pane; buttons elide instead.
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box.setMinimumWidth(1)
        row = QGridLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(4)
        for index, link in enumerate(guide.links):
            button = QPushButton(tr(link.label) + (tr('（需登录）') if link.needs_login else ''))
            button.setObjectName('helpLink')
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f'{link.url}\n{tr("最后核对")} {link.checked}')
            button.clicked.connect(lambda _=False, url=link.url: QDesktopServices.openUrl(QUrl(url)))
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(80)  # explicit minimum: long labels must not widen the page
            row.addWidget(button, index // 3, index % 3)
        return box

    # ---------------------------------------------------------------- form
    def _add_row(self, form, label, widget):
        form.addRow(label, widget)
        self._form_of[id(widget)] = form

    def _in_more(self, spec) -> bool:
        """Prefilled addresses and optional settings fold into “更多设置” (2026-10-18)."""
        return bool(spec.advanced or (not spec.required and not spec.secret and not spec.choices))

    def _form(self, guide):
        settings = self.host.settings() or {}
        models = settings.get('models', {}) if isinstance(settings, dict) else {}
        same_provider = models.get('qwen_asr_api_provider') == guide.key
        current_url = str(models.get('qwen_asr_api_url') or '') if same_provider else ''
        if guide.site_variant and current_url and catalog.qwen_site_for(current_url, language='') != guide.site_variant:
            current_url = ''
        main, more = self._main_form, self._more_form
        if guide.models:
            combo = QComboBox()
            combo.setObjectName('apiSetupModel')
            _shrinkable(combo)
            for choice in guide.models:
                combo.addItem(choice.label, choice.model)
            wanted = str(models.get('qwen_asr_api_model') or '') if same_provider else ''
            combo.setCurrentIndex(max(0, combo.findData(wanted)))
            summary = QLabel()
            summary.setObjectName('fieldHint')
            summary.setWordWrap(True)

            def describe():
                choice = catalog.model_choice(guide, combo.currentData())
                if choice is None:
                    return
                speakers = tr('有说话人') if choice.speakers else tr('不分说话人')
                timing = tr('字/词级时间') if choice.timestamps == 'word' else tr('只有句段时间')
                # Two facts in one short line; the full description is the tooltip.
                summary.setText(f'{speakers}  ·  {timing}')
                summary.setToolTip(ui_literal(choice.summary))
                combo.setToolTip(ui_literal(choice.summary))

            combo.currentIndexChanged.connect(lambda _i: describe())
            describe()
            self._add_row(more, tr('模型'), combo)
            self._add_row(more, '', summary)
            self._fields['model'] = combo
        for spec in guide.fields:
            form = more if self._in_more(spec) else main
            editor = QLineEdit()
            editor.setObjectName('apiSetupField_' + spec.key)
            if spec.secret:
                editor.setEchoMode(QLineEdit.EchoMode.Password)
            value = self._initial_value(guide, spec, models, current_url)
            if spec.secret:
                saved = self._saved_secret(guide, spec, current_url)
                editor.setPlaceholderText(tr('已保存（···{value0}）；留空表示不修改', value0=saved[-4:]) if saved
                                          else (spec.example or tr('尚未保存')))
            else:
                editor.setText(value)
                editor.setPlaceholderText(spec.example)
            # One short line under the field; the full explanation is on hover
            # and in “看完整教程” (2026-10-14: less text on the page).
            hint = QLabel(tr(spec.short_help))
            hint.setObjectName('fieldHint')
            hint.setWordWrap(True)
            if spec.help and spec.help != spec.short_help:
                hint.setToolTip(ui_literal(spec.help))
            label = tr(spec.label) + ('' if spec.required else tr('（可选）'))
            if spec.choices:
                editor = QComboBox()
                editor.setObjectName('apiSetupField_' + spec.key)
                _shrinkable(editor)
                for choice_value, choice_label in spec.choices:
                    editor.addItem(tr(choice_label), choice_value)
                editor.setCurrentIndex(max(0, editor.findData(value or spec.prefilled)))
                editor.currentIndexChanged.connect(lambda _i: self._apply_field_visibility())
            elif spec.key == 'oss_region':
                editor = QComboBox()
                editor.setObjectName('apiSetupField_oss_region')
                _shrinkable(editor)
                for code, region_label in OSS_REGIONS:
                    editor.addItem(f'{tr(region_label)} · {code}', code)
                index = editor.findData(value or 'cn-hangzhou')
                if index < 0:
                    editor.addItem(value, value)
                    index = editor.count() - 1
                editor.setCurrentIndex(index)
            if spec.help:
                editor.setToolTip(ui_literal(spec.help))
            self._add_row(form, label, editor)
            self._add_row(form, '', hint)
            self._fields[spec.key] = editor
            rows = [editor, hint]
            address = None
            if spec.key == 'api_host' or (spec.key == 'url' and guide.key in {'mosi_moss_pro', 'qwen_cloud_filetrans'}):
                address = self.address_view = QLabel()
                self.address_view.setObjectName('fieldHint')
                self.address_view.setWordWrap(True)
                self.address_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self._add_row(form, tr('将使用'), self.address_view)
                rows.append(address)
            if spec.advanced:
                # A prefilled address stays one line until the user chooses to
                # change it; then its hint and the address breakdown appear.
                editor.setEnabled(False)
                unlock = QToolButton()
                unlock.setText(tr('修改'))
                locked = [hint] + ([address] if address is not None else [])
                self._locked_widgets.extend(locked)

                def unlock_field(_=False, widget=editor, button=unlock, widgets=tuple(locked)):
                    widget.setEnabled(True)
                    button.setEnabled(False)
                    for item in widgets:
                        if item in self._locked_widgets:
                            self._locked_widgets.remove(item)
                    self._apply_field_visibility()

                unlock.clicked.connect(unlock_field)
                self._add_row(form, '', unlock)
                rows.append(unlock)
                self._lockable_widgets.extend(locked)
            if spec.key == 'filetrans_upload':
                # Shown only while the trial upload is selected (ADR 0112).
                trial = QLabel(tr(catalog.TRIAL_UPLOAD_NOTE))
                trial.setObjectName('statusWarn')
                trial.setWordWrap(True)
                self._add_row(form, '', trial)
                self._field_rows['filetrans_upload_trial'] = (
                    catalog.Field('filetrans_upload_trial', '', '', show_when=('filetrans_upload', catalog.UPLOAD_PROVIDER)),
                    [trial])
            if spec.show_when:
                self._field_rows[spec.key] = (spec, rows)
        source = 'api_host' if 'api_host' in self._fields else (
            'url' if guide.key in {'mosi_moss_pro', 'qwen_cloud_filetrans'} else '')
        if source:
            self._fields[source].textChanged.connect(lambda _t: self._describe_address())
            self._describe_address()
        if guide.needs_storage:
            auto_delete = QCheckBox(tr('识别成功后自动删除 OSS 临时音频（建议开启）'))
            auto_delete.setChecked(bool(models.get('oss_auto_delete', True)))
            self._add_row(main, '', auto_delete)
            self._fields['oss_auto_delete'] = auto_delete
            self._field_rows['oss_auto_delete'] = (catalog.Field('oss_auto_delete', '', '', show_when=('filetrans_upload',
                                                   catalog.UPLOAD_OWN_OSS)), [auto_delete])

    def _apply_field_visibility(self):
        """Fields that only apply to one choice (e.g. own OSS) are hidden otherwise."""
        if not self._fields:
            return
        values = {key: self._value(key) for key in self._fields}
        shown = {}
        for widget in self._lockable_widgets:
            shown[id(widget)] = (widget, True)
        for spec, widgets in self._field_rows.values():
            visible = catalog.visible_field(spec, values)
            for widget in widgets:
                shown[id(widget)] = (widget, visible)
        for widget, visible in shown.values():
            visible = visible and widget not in self._locked_widgets
            form = self._form_of.get(id(widget))
            try:
                form.setRowVisible(widget, visible)
            except (AttributeError, TypeError):
                widget.setVisible(visible)
        if self.oss_button is not None:
            self.oss_button.setVisible(catalog.uses_own_storage(self._guide, values))

    def _initial_value(self, guide, spec, models, current_url):
        if spec.key == 'api_host':
            if not current_url:
                return ''
            from .api_endpoints import EndpointInputError, parse_dashscope_address
            try:
                return parse_dashscope_address(current_url).host
            except EndpointInputError:
                return current_url
        if spec.key == 'url':
            return current_url or spec.prefilled
        if spec.key.startswith('oss_'):
            return str(models.get(spec.key) or spec.prefilled or '')
        if spec.key == 'filetrans_upload':
            try:
                saved = tuple(self.host.saved_oss_credentials() or ())
            except Exception:
                saved = ()
            mode = catalog.resolve_upload_mode(models, guide.key, has_oss_credentials=len(saved) >= 2 and all(saved[:2]))
            # Nothing set up yet: start on the regular route (own OSS), never on the trial upload.
            return catalog.UPLOAD_OWN_OSS if mode == catalog.UPLOAD_MISSING else mode
        if spec.key == 'model':
            # A saved model of this provider, else the prefilled one (2026-10-25: OpenRouter's
            # MAI-Transcribe 2 showed an empty box when nothing, or an emptied model, was saved).
            saved = str(models.get('qwen_asr_api_model') or '') if models.get('qwen_asr_api_provider') == guide.key else ''
            return saved or spec.prefilled
        if guide.key == 'spark_asr_v2' and spec.key == 'app_id':
            # AppID is not secret: show the saved one so a check works without re-pasting.
            return self._spark_saved(current_url).get('app_id', '')
        return spec.prefilled

    @staticmethod
    def _prefilled_url(guide) -> str:
        return next((spec.prefilled for spec in guide.fields if spec.key == 'url'), '')

    def _spark_saved(self, current_url='') -> dict:
        try:
            from .llm_config import read_spark_credentials
            from ..app.ui import ASR_API_PRESETS
            return read_spark_credentials(current_url or ASR_API_PRESETS['spark_asr_v2']['url'])
        except Exception:
            return {}

    def _saved_secret(self, guide, spec, current_url):
        try:
            if guide.key == 'spark_asr_v2' and spec.key in {'api_key', 'api_secret'}:
                # Spark keeps its three values under its own scope (2026-10-14 fix:
                # reopening showed them as not saved and checks failed).
                return str(self._spark_saved(current_url).get(spec.key) or '')
            if spec.key == 'api_key':
                url = current_url or next((f.prefilled for f in guide.fields if f.key == 'url'), '')
                return str(self.host.saved_key(guide.key, url) or '')
            if spec.key in {'oss_access_key_id', 'oss_access_key_secret'}:
                ident, secret = (tuple(self.host.saved_oss_credentials() or ()) + ('', ''))[:2]
                return str(ident if spec.key == 'oss_access_key_id' else secret)
        except Exception:
            return ''
        return ''

    def _describe_address(self):
        from .api_endpoints import EndpointInputError, describe_dashscope, describe_mosi
        try:
            if self._guide.key == 'mosi_moss_pro':
                info = describe_mosi(self._value('url'))
            elif self._guide.key == 'qwen_cloud_filetrans':
                info = describe_dashscope(self._value('url') or self._prefilled_url(self._guide))
            else:
                info = describe_dashscope(self._value('api_host'))
        except EndpointInputError as exc:
            self.address_view.setText(ui_literal(str(exc)))
            self.address_view.setToolTip('')
            return
        lines = [f"{tr('官方网站')}：{info['website']}", f"API Host：{info['api_host']}",
                 f"Base URL：{info['base_url']}", f"{tr('完整请求 Endpoint')}：{info['endpoint']}"]
        if info.get('region_label'):
            lines.append(f"{tr('地域')}：{ui_literal(info['region_label'])}")
        notes = [tr(note) for note in info.get('notes') or ()]
        # One line on the page (where requests go); the four addresses kept
        # apart on hover, so nobody has to guess about /v1.
        compact = ' · '.join(part for part in (ui_literal(info.get('region_label') or ''), info['base_url']) if part)
        legacy = [note for note in notes if '旧' in note]
        self.address_view.setText('\n'.join([compact] + legacy))
        self.address_view.setToolTip('\n'.join(lines + notes))

    def _value(self, key):
        widget = self._fields.get(key)
        if widget is None:
            return ''
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or widget.currentText() or '')
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return widget.text().strip()

    # -------------------------------------------------------------- values
    def collected(self) -> dict:
        values = {key: self._value(key) for key in self._fields}
        guide = self._guide
        # A field hidden by the current choice is not part of the setup.
        for spec in guide.fields:
            if spec.show_when and not catalog.visible_field(spec, values):
                values.pop(spec.key, None)
        if guide.key == 'qwen31_filetrans':
            from .api_endpoints import filetrans_endpoint
            values['url'] = filetrans_endpoint(values.get('api_host', ''))
            if 'oss_region' in values:
                values['oss_endpoint'] = catalog.oss_endpoint_for_region(values.get('oss_region', ''))
        elif guide.key == 'qwen_cloud_filetrans':
            from .api_endpoints import EndpointInputError, parse_dashscope_address
            address = parse_dashscope_address(values.get('url') or self._prefilled_url(guide))
            if not (address.qwen_cloud or address.host == 'dashscope-intl.aliyuncs.com'):
                raise EndpointInputError('这里只接受千问AI平台或 Qwen Cloud 的地址（maas.qianwenaiapi.com、'
                                         'maas.qwencloudapi.com 或 dashscope-intl.aliyuncs.com）。'
                                         '阿里云百炼的地址请到“阿里云百炼 · 录音文件识别”填写。')
            values['url'] = address.filetrans_url
        elif guide.key == 'mosi_moss_pro':
            from .mosi_asr import normalize_api_base
            values['url'] = normalize_api_base(values.get('url', ''))
        return values

    def _endpoint(self, values) -> dict:
        from .llm_config import read_asr_api_key
        from ..app.ui import ASR_API_PRESETS
        preset = ASR_API_PRESETS.get(self._guide.key, {})
        endpoint = {'provider': self._guide.key, 'protocol': preset.get('protocol', ''),
                    'model': values.get('model') or preset.get('model', ''),
                    'url': values.get('url') or preset.get('url', ''), 'speaker_source': 'native'}
        if self._guide.key == 'spark_asr_v2':
            saved = self._spark_saved(endpoint['url'])
            for name in ('app_id', 'api_key', 'api_secret'):
                endpoint[name] = values.get(name) or saved.get(name, '')
            return endpoint
        key = values.get('api_key') or read_asr_api_key(self._guide.key, endpoint['url'])[0]
        endpoint['api_key'] = key
        for name in ('app_id', 'api_secret'):
            if values.get(name):
                endpoint[name] = values[name]
        return endpoint

    def _settings_snapshot(self, values) -> dict:
        import copy
        settings = copy.deepcopy(self.host.settings() or {})
        models = settings.setdefault('models', {})
        for key in ('oss_region', 'oss_endpoint', 'oss_bucket', 'oss_prefix', 'oss_auto_delete', 'filetrans_upload'):
            if key in values and values[key] not in ('', None):
                models[key] = values[key]
        models['qwen_asr_api_provider'] = self._guide.key
        return settings

    def _oss_credentials(self, values) -> tuple:
        saved = (tuple(self.host.saved_oss_credentials() or ()) + ('', ''))[:2]
        return (values.get('oss_access_key_id') or saved[0], values.get('oss_access_key_secret') or saved[1])

    # ---------------------------------------------------------------- tests
    def _results_widget(self, guide):
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        levels = [level for level in tests.LEVELS if guide.key in catalog.FILETRANS_GUIDES or level != 'storage']
        for row, level in enumerate(levels):
            mark = QLabel(STATUS_MARKS[tests.SKIP])
            mark.setFixedWidth(22)
            name = QLabel(tr(tests.LEVEL_LABELS[level]))
            detail = QLabel(tr('尚未检查'))
            detail.setObjectName('muted')
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(mark, row, 0)
            grid.addWidget(name, row, 1)
            grid.addWidget(detail, row, 2)
            self._result_labels[level] = (mark, detail)
        grid.setColumnStretch(2, 1)
        # The result rows appear once a check has run.
        self._results_box = QWidget()
        self._results_box.setObjectName('apiSetupResults')
        self._results_box.setLayout(grid)
        self._results_box.hide()
        return self._results_box

    def _show_report(self, report):
        box = getattr(self, '_results_box', None)
        if box is not None:
            box.show()
        if getattr(report, 'price', None):
            self._last_price = dict(report.price)
        for check in report.checks:
            labels = self._result_labels.get(check.level)
            if labels is None:
                continue
            labels[0].setText(STATUS_MARKS.get(check.status, '?'))
            labels[1].setText(ui_literal(check.detail) if check.detail else {
                tests.PASS: tr('通过'), tests.FAIL: tr('未通过'), tests.UNKNOWN: tr('无法判断'),
                tests.SKIP: tr('未执行')}[check.status])
        failed = [c for c in report.checks if c.status == tests.FAIL]
        self.status.setText(tr('有项目未通过，看看检查结果里的说明。') if failed else tr('检查完成。'))
        if any(c.level in {'key', 'recognition'} for c in report.checks):
            passed = not failed and report.status('key') != tests.UNKNOWN
            self._update_steps(checked=passed)
            if passed and self._page_kind == 'paste':
                self._show_done()

    def _start(self, job, message):
        self.status.setText(tr(message))
        thread = QThread(self)
        runner = _Runner(job)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.finished.connect(self._show_report)
        runner.failed.connect(lambda text: self.status.setText(tr('检查失败：') + ui_literal(text)))
        for signal in (runner.finished, runner.failed):
            signal.connect(thread.quit)
        thread.finished.connect(runner.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(item) if item in self._threads else None)
        item = (thread, runner)
        self._threads.append(item)
        thread.start()

    def _format_failure(self, message):
        """Address/field errors land in the result grid, not only the status line."""
        report = tests.Report().add('format', tests.FAIL, str(message))
        self._show_report(report)

    def _run_free(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        endpoint = self._endpoint(values)
        checked_values = dict(values)
        if catalog.uses_own_storage(self._guide, values):
            ident, secret = self._oss_credentials(values)
            checked_values.update(oss_access_key_id=ident, oss_access_key_secret=secret)
        temporary = (self._guide.key in catalog.FILETRANS_GUIDES
                     and str(values.get('filetrans_upload') or '') == catalog.UPLOAD_PROVIDER)
        precheck = tests.format_check(endpoint, checked_values)
        if precheck.status('format') == tests.FAIL:
            # Local mistakes are shown at once; nothing is sent anywhere.
            self._show_report(precheck)
            return

        def job():
            report = tests.free_checks(endpoint, values=checked_values)
            if temporary and report.status('format') != tests.FAIL and report.status('key') != tests.FAIL \
                    and report.status('connection') != tests.FAIL:
                for check in tests.temporary_upload_check(endpoint).checks:
                    report.add(check.level, check.status, check.detail)
            return report

        self._start(job, '正在检查格式、连线与密钥（不上传音频）…')

    def _run_oss(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        settings = self._settings_snapshot(values)
        credentials = self._oss_credentials(values)
        self._start(lambda: tests.oss_check(settings, credentials), '正在检查 OSS…')

    def _run_recognition(self):
        try:
            values = self.collected()
        except Exception as exc:
            self._format_failure(exc)
            return
        endpoint = self._endpoint(values)
        precheck = tests.format_check(endpoint, values)
        if precheck.status('format') == tests.FAIL:
            self._show_report(precheck)
            return
        from urllib.parse import urlsplit
        host = urlsplit(str(endpoint.get('url') or '')).hostname or endpoint.get('url')
        cost = tests.estimate_test_cost(endpoint, self._last_price)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr('实际短音频识别测试'))
        box.setText(tr('这一步会把测试音频上传到 {value0}，并可能产生费用。', value0=host))
        extra = tr('默认上传兔白自带的约 6 秒英文合成语音（不含你的任何素材）。也可以改选你自己的短音频（60 秒以内）。')
        if catalog.uses_own_storage(self._guide, values):
            extra += '\n' + tr('音频会先放到你的 OSS 私有存储，结果取回后删除。')
        elif self._guide.key in catalog.FILETRANS_GUIDES:
            extra += '\n' + tr('音频会先上传到服务商临时空间（你选的“仅供试用”方式，48 小时后由服务商删除），再提交识别。')
        box.setInformativeText(f'{extra}\n{tr("可能费用")}：{tr(cost)}')
        use_sample = box.addButton(tr('上传自带测试音频'), QMessageBox.ButtonRole.AcceptRole)
        choose = box.addButton(tr('选择我的音频…'), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        audio_path = None
        if clicked is choose:
            audio_path, _ = QFileDialog.getOpenFileName(self, tr('选择测试音频'), '',
                                                        tr('音频 (*.wav *.mp3 *.m4a *.flac *.aac *.ogg)'))
            if not audio_path:
                return
        elif clicked is not use_sample:
            return
        settings = self._settings_snapshot(values)
        credentials = self._oss_credentials(values) if catalog.uses_own_storage(self._guide, values) else ()
        self._start(lambda: tests.short_recognition(endpoint, settings, audio_path=audio_path,
                                                    storage_credentials=credentials),
                    '正在上传并等待云端识别…（通常几十秒）')

    # ----------------------------------------------------------------- save
    def _save(self, use_as_primary: bool):
        try:
            values = self.collected()
        except Exception as exc:
            self.status.setText(ui_literal(str(exc)))
            return
        ok, message = self.host.save(self._guide.key, values, use_as_primary)
        self.status.setText(tr(message))
        if ok and use_as_primary:
            self.accept()

    def _open_advanced(self):
        if self.host.open_advanced is not None and self._guide is not None:
            key = self._guide.key
            self.accept()
            self.host.open_advanced(key)

    def done(self, result):
        for thread, _runner in list(self._threads):
            thread.quit()
            thread.wait(30000)
        super().done(result)
