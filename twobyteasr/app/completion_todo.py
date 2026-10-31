"""The follow-up bar on the completion page (2026-10-30, user chose design B).

One compact bar under the result: AI glossary proofreading (the release's
highlight, always first), current review categories, retry of unfinished
stages and 更多操作. Each row measures its actual child controls after zoom.
The page owns what each button does; these widgets only show facts.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QToolButton, QWidget

from ..design.studio_theme import create_studio_menu
from ..design.theme_manager import theme_key
from ..design.themed_icons import install_themed_icon
from ..design.typography import application_font
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import bind_text, tr
from .completion_widgets import COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_SMALL
from .ui_zoom import logical

# Plain words for the categories a current review item can carry. An unknown
# category keeps its own name.
CATEGORY_LABELS = {
    '说话人重叠': '多人同时说话',
    '多模型争议': '几个模型听到的不一样',
    '多模型文本冲突': '几个模型听到的不一样',
    '边界待看': '句子开头或结尾可能没切准',
    '孤立实义单字': '单独的一个字',
    '阅读较快': '字幕太快，来不及读',
    '显示过短': '字幕显示时间太短',
    '疑似重复': '可能重复',
    '说话人需要确认': '说话人需要确认',
    '术语候选': '术语写法待确认',
    '术语候选待确认': '术语写法待确认',
    '主力转写提前结束': '结尾可能漏了一段',
    'MOSS提前结束': '结尾可能漏了一段',
}
CHIP_LIMIT = 3
BAR_HEIGHT = 36  # buttons and chips inside the bar


def review_groups(items):
    """[(label, count, first_row)] largest first; same-label categories merge."""
    counts, first = Counter(), {}
    for row in items:
        label = CATEGORY_LABELS.get(str(row.get('category') or ''), str(row.get('category') or '其他'))
        counts[label] += 1
        first.setdefault(label, row)
    return [(label, count, first[label]) for label, count in counts.most_common()]


def _icon(name, role, tone):
    icon = QToolButton()
    icon.setObjectName('completionTodoIcon')
    icon.setProperty('tone', tone)
    icon.setFixedSize(26, 26)
    icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    install_themed_icon(icon, name, role)
    return icon


def _label(object_name, tone=''):
    label = QLabel()
    label.setFont(application_font())
    label.setObjectName(object_name)
    if tone:
        label.setProperty('tone', tone)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label


class _BarButton(QPushButton):
    """Compact controls keep their own 36px contract, separate from 44px actions."""

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 30, BAR_HEIGHT)

    def minimumSizeHint(self):
        return self.sizeHint()


def _button(tone):
    button = _BarButton()
    button.setFont(application_font())
    button.setObjectName('completionTodoAction')
    button.setProperty('tone', tone)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedHeight(BAR_HEIGHT)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return button


class _FittingChips(QWidget):
    """Only whole labels fit; this optional area never sets the bar's minimum width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_texts(self, texts):
        for label in self.labels:
            label.hide()
            label.deleteLater()
        self.labels = []
        for text in texts:
            label = _label('completionTodoChip', 'review')
            label.setParent(self)
            label.setText(str(text))
            label.setProperty('i18nUserText', True)
            self.labels.append(label)
        self.fit_labels()

    def fit_labels(self):
        x = 0
        for label in self.labels:
            label.ensurePolished()
            hint = label.sizeHint()
            fits = x + hint.width() <= self.width()
            if fits:
                label.setGeometry(x, (self.height() - hint.height()) // 2, hint.width(), hint.height())
                x += hint.width() + 5
            label.setVisible(fits)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_labels()

    def sizeHint(self):
        return QSize(0, 24)

    def minimumSizeHint(self):
        return QSize(0, 24)


class TodoGroup(QFrame):
    """One follow-up in the bar: icon, title, count badge, short note, action."""

    def __init__(self, tone, icon, title, parent=None, *, action=True):
        super().__init__(parent)
        self.tone = tone
        self.setProperty('uiZoomOwnSize', True)
        self._pressed = False
        if tone == 'ai':
            self.setFocusPolicy(Qt.StrongFocus)
            self.setCursor(Qt.PointingHandCursor)
            self.setAttribute(Qt.WA_Hover)
        self.setObjectName('completionTodoGroup')
        self.setProperty('tone', tone)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        row = QHBoxLayout(self)
        if tone == 'ai':
            row.setContentsMargins(8, 4, 4, 4)
        else:
            row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.icon = _icon(icon, 'on_accent' if tone == 'ai' else 'warning' if tone == 'review' else 'danger', tone)
        row.addWidget(self.icon)
        self.title = bind_text(_label('completionTodoTitle'), title)
        row.addWidget(self.title)
        self.badge = _label('completionTodoBadge', tone)
        self.badge.hide()
        row.addWidget(self.badge)
        self.note = _label('completionTodoNote')
        self.note.hide()
        row.addWidget(self.note)
        self.chips = _FittingChips(self)
        self.chips.setObjectName('completionTodoChips')
        self.chips.hide()
        row.addWidget(self.chips, 1)
        # The action stays at the right in the stacked layout, too.
        self.action_spacer_index = row.count()
        row.addStretch(1)
        self.action = _button(tone) if action else None
        if self.action is not None:
            row.addWidget(self.action)
        for child in (self.title, self.badge, self.note):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mousePressEvent(self, event):
        if self.tone == 'ai' and event.button() == Qt.LeftButton:
            self._pressed = True
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._pressed = self._pressed, False
        if self.tone == 'ai' and event.button() == Qt.LeftButton:
            if pressed and self.rect().contains(event.position().toPoint()):
                self.action.click()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.tone == 'ai' and event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            if not event.isAutoRepeat():
                self.action.click()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_chips(self, texts):
        self.chips.set_texts(texts)

    def chip_texts(self):
        return [label.text() for label in self.chips.labels]

    def protected_width(self):
        widgets = [self.icon, self.title, self.badge, self.note, self.action]
        widgets = [widget for widget in widgets if widget is not None and not widget.isHidden()]
        margins = self.layout().contentsMargins()
        return (sum(max(widget.minimumWidth(), widget.sizeHint().width()) for widget in widgets)
                + self.layout().spacing() * max(0, len(widgets) - 1)
                + margins.left() + margins.right() + (2 if self.tone == 'ai' else 8 if self.tone == 'review' else 0))


class CompletionTodoSection(QFrame):
    """The bar; on a narrow page each follow-up takes its own line."""

    review_jump = Signal(object)  # one current review row; the page opens Studio there
    review_list = Signal()        # the full current review list
    content_changed = Signal()    # height changed; the page re-measures its fixed height

    def __init__(self, more_button, parent=None):
        super().__init__(parent)
        self.setObjectName('completionTodo')
        self.setProperty('uiZoomOwnSize', True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.more_button = more_button
        more_button.set_compact(True)
        more_button.setFixedHeight(BAR_HEIGHT)
        more_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ai_card = TodoGroup('ai', 'fa5s.magic', 'AI 词库校对', self)
        bind_text(self.ai_card.badge, '新')
        self.ai_card.badge.show()
        bind_text(self.ai_card.action, '开始校对 ›')
        bind_text(self.ai_card, '把写错的人名和术语一次找出来，原文和建议并排对照，勾选的才会改；改完能在字幕工作台撤销。',
                  property='toolTip')
        self.review_card = TodoGroup('review', 'fa5s.flag', '待检查', self, action=False)
        self.retry_card = TodoGroup('retry', 'fa5s.redo', '重试', self)
        self.cards = (self.ai_card, self.review_card, self.retry_card)
        # Which groups apply; visibility follows once they are placed.
        self._shown = {self.ai_card: True, self.review_card: False, self.retry_card: False}
        self._groups = []
        self._jump_enabled = True
        self.dividers = [QFrame(self) for _ in range(2)]
        for divider in self.dividers:
            divider.setObjectName('completionTodoDivider')
            divider.setFixedSize(1, 24)
        # One row on wide pages; a narrow page turns the same layout into lines.
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.box.setContentsMargins(8, 3, 10, 3)
        for widget in (self.ai_card, self.dividers[0], self.review_card, self.dividers[1], self.retry_card):
            self.box.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.box.addStretch(1)
        self.box.addWidget(more_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.columns = 0
        self._layout_signature = None
        self._arrange_pending = False
        self.set_ai(enabled=False)
        self.set_retry(visible=False)
        self.refresh_theme_palette()

    # --- facts -----------------------------------------------------------
    def set_ai(self, *, enabled, unfinished=0):
        self.ai_card.action.setEnabled(enabled)
        if unfinished:
            bind_text(self.ai_card.note, '{count} 段没校完，可补做', count=unfinished)
        else:
            bind_text(self.ai_card.note, '')
        self.ai_card.note.setVisible(bool(unfinished))
        self._arrange()

    def set_review(self, items, *, enabled=True):
        groups = review_groups(items)
        self._groups = groups
        self._jump_enabled = enabled
        self._shown[self.review_card] = bool(groups)
        self.review_card.badge.setProperty('i18nUserText', True)
        self.review_card.badge.setText(str(len(items)))
        self.review_card.badge.setVisible(bool(items))
        self.review_card.set_chips([f'{tr(label)} {count}' for label, count, _row in groups[:CHIP_LIMIT]]
                                   + ([tr('+{count} 类', count=len(groups) - CHIP_LIMIT)] if len(groups) > CHIP_LIMIT else []))
        if getattr(self, '_group_menu', None) is not None:
            self._group_menu.close()
        self._arrange()

    def set_retry(self, *, visible, enabled=True, title='重试', label='重试', badge=0, body='',
                  body_arguments=None, note=''):
        """``body`` becomes the tooltip; the bar keeps one short line."""
        self._shown[self.retry_card] = bool(visible)
        self.retry_card.action.setEnabled(enabled)
        bind_text(self.retry_card.title, title)
        bind_text(self.retry_card.action, label)
        self.retry_card.badge.setProperty('i18nUserText', True)
        self.retry_card.badge.setText(str(badge))
        self.retry_card.badge.setVisible(bool(badge))
        bind_text(self.retry_card, body or '原任务有一部分没有跑完。只重试那一部分，原字幕可以继续用。',
                  property='toolTip', **(body_arguments or {}))
        bind_text(self.retry_card.note, note)
        self.retry_card.note.setVisible(bool(note))
        self._arrange()

    def group_menu_rows(self):
        """[(text, row)] the 逐类查看 menu offers, in order."""
        return [(f'{tr(label)}  ·  {count}', row) for label, count, row in self._groups]

    # --- layout ----------------------------------------------------------
    def _columns_for_width(self):
        # Long translated copy can need lines before the nominal breakpoint.
        shown = [card for card in self.cards if self._shown[card]]
        protected = sum(card.protected_width() for card in shown) + self.more_button.sizeHint().width()
        protected += 18 + 10 * (len(shown) * 2 - 1) + max(0, len(shown) - 1)
        return 1 if logical(self.width()) < 900 or protected > self.width() else 3

    def _arrange(self):
        self._arrange_pending = False
        self.ensurePolished()
        columns = self._columns_for_width()
        signature = (columns, tuple(self._shown.values()),
                     tuple((card.protected_width(),card.layout().minimumSize().height()) for card in self.cards),
                     self.more_button.sizeHint().width(),self.more_button.height())
        if signature == self._layout_signature:
            return
        self._layout_signature = signature
        box = self.box
        box.setDirection(QBoxLayout.Direction.LeftToRight if columns > 1 else QBoxLayout.Direction.TopToBottom)
        box.setSpacing(10 if columns > 1 else 6)
        shown = self._shown
        wide = columns > 1
        self.dividers[0].setVisible(wide and shown[self.ai_card] and (shown[self.review_card] or shown[self.retry_card]))
        self.dividers[1].setVisible(wide and shown[self.review_card] and shown[self.retry_card])
        for card in self.cards:
            card.setVisible(shown[card])
            card.setFixedHeight(max(BAR_HEIGHT, card.layout().minimumSize().height()))
            box.setAlignment(card, Qt.AlignmentFlag.AlignVCenter)
            card.setSizePolicy(QSizePolicy.Policy.Expanding if not wide or card is self.review_card
                               else QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            box.setStretch(box.indexOf(card), 1 if wide and card is self.review_card else 0)
        self.review_card.chips.setVisible(wide and bool(self._groups))
        # In a wide review group all spare room goes to whole category chips;
        # its narrow row uses the spacer to keep the action at the right.
        self.review_card.layout().setStretch(self.review_card.action_spacer_index, 0 if wide else 1)
        box.setStretch(5, 1 if wide and not shown[self.review_card] else 0)
        box.setAlignment(self.more_button, Qt.AlignmentFlag.AlignVCenter if wide else Qt.AlignmentFlag.AlignRight)
        # AI's 36px action + 8px padding + border sit inside the 52px bar.
        margins = box.contentsMargins()
        heights = [card.height() for card in self.cards if shown[card]] + [self.more_button.height()]
        height = margins.top() + margins.bottom() + (max(heights) if wide else sum(heights) + box.spacing()*(len(heights)-1))
        self.setFixedHeight(height)
        self.columns = columns
        self.updateGeometry()
        self.content_changed.emit()

    def apply_ui_zoom(self, _factor):
        self._layout_signature = None
        if not self._arrange_pending:
            self._arrange_pending = True
            QTimer.singleShot(0,self,self._arrange)

    def event(self, event):
        result = super().event(event)
        if (event.type() in (QEvent.Type.Show, QEvent.Type.FontChange, QEvent.Type.LayoutRequest)
                and hasattr(self, '_arrange_pending') and not self._arrange_pending):
            self._arrange_pending = True
            QTimer.singleShot(0, self, self._arrange)
        return result

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._columns_for_width() != self.columns:
            self._arrange()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def refresh_theme_palette(self):
        t = theme_definition(theme_key())
        ai = t.zone_colors.get('ai', t.accent)
        tones = {'ai': ai, 'review': t.warning, 'retry': t.danger}
        rules = [
            f"QFrame#completionTodo {{ background:{t.surface}; border:1px solid {t.border}; border-radius:{COMPLETION_RADIUS_MAIN}px; }}",
            f"QFrame#completionTodoDivider {{ background:{t.border}; border:0; }}",
            f"QFrame#completionTodoGroup {{ background:transparent; border:0; }}",
            f"QFrame#completionTodoGroup[tone=\"ai\"] {{ background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {blend_hex(t.surface, ai, 0.26)},"
            f" stop:1 {blend_hex(t.surface, ai, 0.08)}); border:1px solid {blend_hex(t.surface, ai, 0.45)}; border-radius:10px; }}",
            f"QFrame#completionTodoGroup[tone=\"ai\"]:hover, QFrame#completionTodoGroup[tone=\"ai\"]:focus {{ border:1px solid {t.focus}; }}",
            f"QLabel#completionTodoTitle {{ color:{t.text}; font-size:14px; font-weight:700; background:transparent; }}",
            f"QLabel#completionTodoNote {{ color:{t.text_muted}; font-size:12px; background:transparent; }}",
        ]
        for tone, color in tones.items():
            rules += [
                f"QToolButton#completionTodoIcon[tone=\"{tone}\"] {{ background:{color if tone == 'ai' else blend_hex(t.surface, color, 0.18)};"
                f" border:0; padding:0; min-height:0; border-radius:7px; }}",
                f"QLabel#completionTodoBadge[tone=\"{tone}\"] {{ background:{color if tone == 'ai' else blend_hex(t.surface, color, 0.18)};"
                f" color:{t.on_vivid if tone == 'ai' else color}; border-radius:9px; padding:1px 8px; font-size:12px; font-weight:700; }}",
                f"QLabel#completionTodoChip[tone=\"{tone}\"] {{ background:transparent; color:{t.text_secondary};"
                f" border:1px solid {blend_hex(t.surface, color, 0.32)}; border-radius:10px; padding:1px 8px; font-size:12px; }}",
            ]
        rules += [
            f"QPushButton#completionTodoAction {{ background:{t.surface_elevated}; color:{t.text}; border:1px solid {t.border_strong};"
            f" border-radius:{COMPLETION_RADIUS_SMALL}px; font-size:13px; font-weight:600; padding:4px 14px; min-height:0; }}",
            f"QPushButton#completionTodoAction:hover {{ background:{t.selected}; border-color:{t.text_muted}; }}",
            f"QPushButton#completionTodoAction:focus {{ border:2px solid {t.focus}; }}",
            f"QPushButton#completionTodoAction:disabled {{ color:{t.disabled}; border-color:{t.border}; background:{t.panel}; }}",
            f"QPushButton#completionTodoAction[tone=\"ai\"] {{ background:{ai}; color:{t.on_vivid}; border-color:{ai}; }}",
            f"QPushButton#completionTodoAction[tone=\"ai\"]:hover {{ background:{blend_hex(ai, t.text, 0.12)}; border-color:{blend_hex(ai, t.text, 0.12)}; }}",
            f"QPushButton#completionTodoAction[tone=\"ai\"]:focus {{ border:2px solid {t.focus}; }}",
            f"QPushButton#completionTodoAction[tone=\"ai\"]:disabled {{ background:{t.panel}; color:{t.disabled}; border-color:{t.border}; }}",
            f"QPushButton#completionTodoAction[tone=\"review\"] {{ background:{t.warning_soft}; color:{t.warning}; border-color:{blend_hex(t.surface, t.warning, 0.45)}; }}",
            f"QPushButton#completionTodoAction[tone=\"review\"]:hover {{ background:{blend_hex(t.surface, t.warning, 0.24)}; border-color:{t.warning}; }}",
        ]
        self.setStyleSheet('\n'.join(rules))
