"""In-app update: the offer dialog and the check/download threads.

The logic (manifest, verification, staging) lives in ``app/updater.py``;
``MainWindow`` drives the flow.  Split out of ``app/ui.py`` on 2026-10-15;
``ui`` still exports these names.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget

from ..design.main_ui_dialogs import SpringDialog
from ..i18n import current_language, tr
from .updater import (
    STARTUP_RECHECK_SECONDS, automatic_check_due, check_for_update, format_bytes, prepare_update, UpdateCancelled,
)
from ..design.typography import emphasis_qss

# How often a waiting reminder looks again whether the user is free, and for
# how long it keeps looking (2026-10-24).
REMINDER_RETRY_MS = 15_000
REMINDER_MAX_TRIES = 240


def reminder_action(check, *, enabled: bool, reminded_version: str, busy: bool, tries: int = 0) -> str:
    """What the start-up reminder does with ``check``: 'show', 'later' (the
    user is in the middle of something) or '' (nothing to remind of)."""
    if not enabled or not getattr(check, 'newer', False) or reminded_version == check.latest_version:
        return ''
    if busy:
        return 'later' if tries < REMINDER_MAX_TRIES else ''
    return 'show'


class UpdateCheckWorker(QThread):
    """Fetch and verify the signed update manifest off the GUI thread.

    ``reminder`` (2026-10-24): the start-up check with the reminder on runs on
    every start, reusing an answer from the last few minutes; without it the
    automatic check stays at most once a day.
    """

    result_ready = Signal(object)
    failed = Signal(str)
    skipped = Signal()

    def __init__(self, parent=None, *, automatic: bool = False, reminder: bool = False):
        super().__init__(parent)
        self.automatic = automatic
        self.reminder = automatic and reminder

    def run(self):
        try:
            if self.reminder:
                self.result_ready.emit(check_for_update(use_cache=True, cache_seconds=STARTUP_RECHECK_SECONDS))
                return
            if self.automatic and not automatic_check_due():
                self.skipped.emit()
                return
            self.result_ready.emit(check_for_update(use_cache=not self.automatic))
        except Exception as exc:  # noqa: BLE001 - UI must report network failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateDownloadWorker(QThread):
    """Download, verify and stage only the components this update changes."""

    progress_changed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, check, parent=None):
        super().__init__(parent)
        self.check = check
        self.cancel_event = threading.Event()

    def run(self):
        try:
            prepared = prepare_update(
                self.check,
                progress=lambda _name, done, total: self.progress_changed.emit(int(done), int(total)),
                cancel=self.cancel_event,
            )
            self.completed.emit(prepared)
        except UpdateCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - UI must report mirror/checksum failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


# 2026-11-11 offer layout: the release notes are one plain text per language.
# Each line becomes a highlight card when the first lines are short enough;
# otherwise every line stays in a plain rounded list.
HIGHLIGHT_CARDS = 4
HIGHLIGHT_LINE_LIMIT = 60
HIGHLIGHT_TITLE_LIMIT = 18
_BULLETS = '·•-*—–●○▪■□◆◇　 \t'
_TITLE_BREAKS = '，,：:；;'
HIGHLIGHT_ICONS = ('fa5s.star', 'fa5s.magic', 'fa5s.bolt', 'fa5s.check-double')


def note_items(notes: str) -> list[str]:
    """The release notes as one entry per non-empty line, bullets removed."""
    items = []
    for line in str(notes or '').splitlines():
        text = line.strip().lstrip(_BULLETS).strip()
        if text:
            items.append(text)
    return items


def split_highlight(text: str) -> tuple[str, str]:
    """(title, description): the line up to its first comma or colon is the
    title when that part is short; otherwise the whole line is the title."""
    for index, char in enumerate(text):
        if char in _TITLE_BREAKS:
            title, rest = text[:index].strip(), text[index + 1:].strip()
            if 2 <= len(title) <= HIGHLIGHT_TITLE_LIMIT and rest:
                return title, rest
            break
    return text.rstrip('。.'), ''


def highlight_plan(items: list[str]) -> tuple[list[tuple[str, str]], list[str], bool]:
    """(cards, remaining lines, as_cards). Cards are used when each of the
    first ``HIGHLIGHT_CARDS`` lines fits a card; otherwise all lines are a list."""
    lead = items[:HIGHLIGHT_CARDS]
    if not lead or any(len(item) > HIGHLIGHT_LINE_LIMIT for item in lead):
        return [], list(items), False
    return [split_highlight(item) for item in lead], list(items[HIGHLIGHT_CARDS:]), True


def card_cells(count: int) -> list[tuple[int, int, int]]:
    """(row, column, column span) for 1..4 cards in a two-column grid: one
    card or the first of three spans the row."""
    if count == 1:
        return [(0, 0, 2)]
    if count == 3:
        return [(0, 0, 2), (1, 0, 1), (1, 1, 1)]
    return [(index // 2, index % 2, 1) for index in range(count)]


def card_hues(theme):
    return (theme.accent, theme.warning, theme.success, theme.zone_colors.get('ai', theme.focus))


def card_ink(theme, index):
    """A card's icon colour: its own hue, deepened until it reads on the tint."""
    from ..design.ui_theme import blend_hex, contrast_ratio
    hue = card_hues(theme)[index % 4]
    tint = blend_hex(theme.surface, hue, 0.2)
    ink = hue
    for amount in (0.0, 0.2, 0.35, 0.5, 0.65):
        ink = blend_hex(hue, theme.text, amount)
        if contrast_ratio(ink, tint) >= 3.0:  # 2026-11-12 (user): vivid titles, still readable
            break
    return ink


def offer_qss(theme) -> str:
    from ..design.ui_theme import blend_hex, contrast_ratio
    tints = [blend_hex(theme.surface, hue, 0.2) for hue in card_hues(theme)]
    on_accent = theme.text_on_accent
    track = blend_hex(theme.surface, theme.text, 0.12)
    size_ink = theme.accent if contrast_ratio(theme.accent, theme.surface) >= 4.5 else theme.text
    rules = [
        f"QDialog#updateOffer {{ background: transparent; }}",  # painted as a rounded card
        f"QLabel#updateOfferPill {{ background: {theme.accent}; color: {on_accent}; border-radius: 10px;"
        f" padding: 2px 9px; font-size: 11.5px; font-weight: 700; }}",
        f"QLabel#updateOfferMeta {{ color: {theme.text_muted}; font-size: 12.5px; }}",
        f"QLabel#updateOfferVersion {{ color: {theme.accent}; font-size: 60px; }}",
        f"QLabel#updateOfferCardTitle {{ color: {theme.text}; font-size: 16px; font-weight: 800; background: transparent; }}",
        f"QLabel#updateOfferCardText {{ color: {theme.text_secondary}; font-size: 12px; background: transparent; }}",
        f"QFrame#updateOfferList {{ background: {theme.surface_elevated}; border: 1px solid {theme.border};"
        f" border-radius: 16px; }}",
        f"QLabel#updateOfferListItem {{ color: {theme.text}; font-size: 13px; background: transparent; }}",
        f"QFrame#updateOfferTrack {{ background: {track}; border: 0; border-radius: 6px; }}",
        f"QFrame#updateOfferTrackFill {{ background: {theme.accent}; border: 0; border-radius: 6px; }}",
        f"QLabel#updateOfferSize {{ color: {size_ink}; font-size: 13px; font-weight: 700; }}",
        f"QLabel#updateOfferDetail {{ color: {theme.text_secondary}; font-size: 12px; }}",
        f"QPushButton#updateOfferPrimary {{ background: {theme.accent}; color: {on_accent}; border: 0;"
        f" border-radius: 16px; min-height: 52px; max-height: 52px; font-size: 16px; font-weight: 700; }}",
        f"QLabel#updateOfferAlso {{ color: {theme.text_muted}; font-size: 11.5px; background: transparent; }}",
        f"QPushButton#updateOfferPrimary:hover {{ background: {theme.accent_hover}; }}",
        f"QPushButton#updateOfferPrimary:pressed {{ background: {theme.accent_pressed}; }}",
        f"QPushButton#updateOfferLater {{ background: {theme.surface}; color: {theme.text};"
        f" border: 1px solid {theme.border_strong}; border-radius: 14px; min-height: 40px; padding: 0 20px; font-size: 14px; }}",
        f"QPushButton#updateOfferLater:hover {{ background: {theme.selected}; }}",
        f"QPushButton#updateOfferPage {{ background: transparent; color: {theme.text_secondary}; border: 0;"
        f" min-height: 40px; padding: 0 12px; font-size: 13px; text-decoration: underline; }}",
        f"QPushButton#updateOfferPage:hover {{ color: {theme.text}; }}",
        f"QPushButton#updateOfferClose {{ background: transparent; color: {theme.text_secondary};"
        f" border: 1px solid {theme.border}; border-radius: 12px; font-size: 18px; padding: 0; }}",
        f"QPushButton#updateOfferClose:hover {{ background: {theme.selected}; color: {theme.text}; }}",
    ]
    for index, tint in enumerate(tints):
        rules.append(f"QFrame#updateOfferCard[tint=\"{index}\"] {{ background: {tint}; border: 0; border-radius: 18px; }}")
        # 2026-11-12 (user): card titles in the card's own vivid colour, not black.
        rules.append(f"QFrame#updateOfferCard[tint=\"{index}\"] QLabel#updateOfferCardTitle {{ color: {card_ink(theme, index)}; }}")
    return '\n'.join(rules)


class UpdateOfferDialog(SpringDialog):
    """Current/new version, release highlights and the real download size."""

    WIDTH = 540
    RADIUS = 24  # 2026-11-12 (user, design B): rounder than the system's 8px corner

    def __init__(self, check, parent=None, *, reminder: bool = False):
        super().__init__(parent)
        # The window paints its own rounded card; the corners stay clear.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.choice = None
        self.keep_reminding = True
        self.setObjectName('updateOffer')
        self.setWindowTitle(tr('发现新版本'))
        self.setFixedWidth(self.WIDTH)
        self._apply_offer_style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        manifest, plan = check.manifest, check.plan

        top = QHBoxLayout()
        top.setSpacing(10)
        pill = QLabel(tr('发现新版本'))
        pill.setObjectName('updateOfferPill')
        meta = QLabel(tr('兔白字幕 {value0}（当前 {value1}）', value0=check.latest_version,
                         value1=check.current_version))
        meta.setObjectName('updateOfferMeta')
        close = QPushButton('×')
        close.setObjectName('updateOfferClose')
        close.setFixedSize(32, 32)
        close.setAccessibleName(tr('关闭'))
        close.setToolTip(tr('关闭'))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        top.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(meta, 1, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        version = QLabel(str(check.latest_version))
        version.setObjectName('updateOfferVersion')
        # 2026-11-12 (user): the version number in 猫啃什锦黑 (bundled with the app).
        from ..design.loading_font import loading_font
        version_font = loading_font()
        version_font.setPixelSize(60)
        version.setFont(version_font)
        # The app sheet's font-family wins over setFont; name the family here too.
        version.setStyleSheet(f"font-family: '{version_font.family()}'; font-size: 60px;")
        layout.addWidget(version)

        notes = manifest.note_for(current_language()) if manifest else ''
        self.highlight_cards: list[QFrame] = []
        self.more_line = None
        cards, rest, as_cards = highlight_plan(note_items(notes))
        if as_cards:
            layout.addLayout(self._card_grid(cards))
            if rest:
                # 2026-11-12 (user, design B): the rest is one quiet line that
                # ends with 查看完整说明 (the release page), not a fold-out list.
                self.more_line = self._also_line(rest)
                layout.addWidget(self.more_line)
        elif rest:
            layout.addWidget(self._note_list(rest))

        layout.addWidget(self._download_block(plan))

        self.remind_box = None
        if plan is not None and plan.mode == 'components':
            primary = QPushButton(tr('下载并准备更新 · {value0}', value0=format_bytes(plan.download_bytes)))
            primary.clicked.connect(lambda: self._finish('download'))
        else:
            primary = QPushButton(tr('下载安装包'))
            primary.clicked.connect(lambda: self._finish('setup'))
        primary.setObjectName('updateOfferPrimary')
        primary.setCursor(Qt.CursorShape.PointingHandCursor)
        from ..design.themed_icons import colored_icon
        primary.setIcon(colored_icon('fa5s.download', self._offer_theme.text_on_accent))
        from PySide6.QtCore import QSize
        primary.setIconSize(QSize(16, 16))
        primary.setDefault(True)
        self.primary_button = primary
        layout.addWidget(primary)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if reminder:
            # Shown when the dialog opened by itself at start-up (2026-10-24).
            self.remind_box = QCheckBox(tr('打开软件时自动检查并提醒'))
            self.remind_box.setObjectName('updateReminderBox')
            self.remind_box.setChecked(True)
            self.remind_box.toggled.connect(lambda checked: setattr(self, 'keep_reminding', bool(checked)))
            buttons.addWidget(self.remind_box)
        buttons.addStretch(1)
        page = QPushButton(tr('打开发布页'))
        page.setObjectName('updateOfferPage')
        page.setCursor(Qt.CursorShape.PointingHandCursor)
        page.clicked.connect(lambda: self._finish('page'))
        later = QPushButton(tr('稍后'))
        later.setObjectName('updateOfferLater')
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.clicked.connect(self.reject)
        buttons.addWidget(page)
        buttons.addWidget(later)
        layout.addLayout(buttons)
        if self.remind_box is not None:
            # 2026-11-12 (user): the line under the buttons is gone; the box
            # explains itself on hover.
            self.remind_box.setToolTip(tr('取消勾选后不再自动弹出；可以在「应用设置 → 关于」里重新打开，顶栏「检查更新」随时可用。'))
        self._fit_height()

    # -- pieces ---------------------------------------------------------
    def _fit_height(self):
        """Word-wrapped cards need the height for this fixed width; the
        default size hint is for an unwrapped line and squeezes them."""
        layout = self.layout()
        # The layout's own minimum measures wrapped labels at a narrow width
        # and came out taller than needed; the spare height then stretched
        # the cards with empty space below the text (2026-11-12).
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.activate()
        height = layout.totalHeightForWidth(self.WIDTH) if layout.hasHeightForWidth() else layout.sizeHint().height()
        self.setMinimumHeight(0)
        self.setFixedHeight(height)

    def _apply_offer_style(self):
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self._offer_theme = theme_definition(theme_key())
        self.setStyleSheet(emphasis_qss(self.styleSheet() + '\n' + offer_qss(self._offer_theme)))

    def refresh_theme_palette(self) -> None:
        super().refresh_theme_palette()
        if self.objectName() == 'updateOffer':
            self._apply_offer_style()

    def _card_grid(self, cards):
        from ..design.themed_icons import colored_icon
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        theme = self._offer_theme
        for index, ((title, text), (row, column, span)) in enumerate(zip(cards, card_cells(len(cards)))):
            card = QFrame()
            card.setObjectName('updateOfferCard')
            card.setProperty('tint', str(index))
            wide = span == 2
            body = QHBoxLayout(card) if wide else QVBoxLayout(card)
            body.setContentsMargins(16, 14, 16, 14)
            body.setSpacing(12 if wide else 6)
            icon = QLabel()
            icon.setPixmap(colored_icon(HIGHLIGHT_ICONS[index], card_ink(theme, index)).pixmap(26, 26))
            icon.setFixedSize(28, 28)
            icon.setStyleSheet('background: transparent;')
            words = QVBoxLayout()
            words.setSpacing(3)
            head = QLabel(title)
            head.setObjectName('updateOfferCardTitle')
            head.setWordWrap(True)
            words.addWidget(head)
            if text:
                line = QLabel(text)
                line.setObjectName('updateOfferCardText')
                line.setWordWrap(True)
                words.addWidget(line)
            if wide:
                body.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
                body.addLayout(words, 1)
            else:
                body.addWidget(icon)
                body.addLayout(words)
                body.addStretch(1)
            grid.addWidget(card, row, column, 1, span)
            self.highlight_cards.append(card)
        return grid

    def _note_list(self, items):
        box = QFrame()
        box.setObjectName('updateOfferList')
        body = QVBoxLayout(box)
        body.setContentsMargins(16, 10, 16, 10)
        body.setSpacing(8)
        for item in items:
            line = QLabel('·  ' + item)
            line.setObjectName('updateOfferListItem')
            line.setWordWrap(True)
            line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(line)
        return box

    def _also_line(self, items):
        import html
        theme = self._offer_theme
        # A note that itself starts with 合入 would read 「还合入：合入…」.
        joined = '；'.join(item.rstrip('。.；; ').removeprefix('合入').removeprefix('还合入') for item in items)
        line = QLabel(html.escape(tr('还合入：{items}。', items=joined))
                      + f' <a href="page" style="color:{theme.accent_text}; text-decoration:none;">'
                      + html.escape(tr('查看完整说明')) + ' ›</a>')
        line.setObjectName('updateOfferAlso')
        line.setTextFormat(Qt.TextFormat.RichText)
        line.setWordWrap(True)
        line.linkActivated.connect(lambda _link: self._finish('page'))
        return line

    def _download_block(self, plan):
        block = QWidget()
        body = QVBoxLayout(block)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        headline, lines, share = '', [], 1.0
        if plan is not None and plan.mode == 'components':
            headline = tr('本次需要下载：{value0}', value0=format_bytes(plan.download_bytes))
            if plan.setup_bytes:
                share = max(0.02, min(1.0, plan.download_bytes / plan.setup_bytes))
            # 2026-11-12 (user): what is downloaded and what is kept was a
            # block of small print; the size and the bar say enough.
        elif plan is not None:
            headline = tr('需要用完整安装包更新（{value0}）。', value0=format_bytes(plan.setup_bytes))
            if plan.fallback_reason:
                lines.append(tr('原因：{value0}', value0=plan.fallback_reason))
            lines.append(tr('安装包会保留设置、词库、工程、模型和运行环境，覆盖安装即可，不要先卸载。'))
        if plan is not None:
            # Only a change is news; "kept, nothing to download" is not shown.
            if plan.environment_changes:
                lines.append(tr('运行环境：{value0} 的需求有变化，用到时程序会提示补齐。',
                                value0='、'.join(plan.environment_changes)))
            if plan.model_changes:
                lines.append(tr('模型：{value0} 有新版本，只有用到该模型时才需要下载。',
                                value0='、'.join(plan.model_changes)))
        self.size_share = share
        if headline and not (plan is not None and plan.mode == 'components'):
            track = QFrame()
            track.setObjectName('updateOfferTrack')
            track.setFixedHeight(12)
            row = QHBoxLayout(track)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            fill = QFrame()
            fill.setObjectName('updateOfferTrackFill')
            steps = max(1, round(share * 100))
            row.addWidget(fill, steps)
            if steps < 100:
                row.addStretch(100 - steps)
            body.addWidget(track)
            size = QLabel(headline)
            size.setObjectName('updateOfferSize')
            size.setWordWrap(True)
            body.addWidget(size)
        if lines:
            detail = QLabel('\n'.join(lines))
            detail.setObjectName('updateOfferDetail')
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(detail)
        return block

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPen
        theme = self._offer_theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.surface))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.RADIUS, self.RADIUS)
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def _finish(self, choice):
        self.choice = choice
        self.accept()
