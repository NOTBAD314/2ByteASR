"""The first-run tutorial: do it once with demo data, one step at a time (2026-10-14).

Each step outlines a real control (or shows a centred card), says what you
can do there in one line, and offers the action itself: put in the demo
video, switch the subtitle language, open the AI key form, look at the
result page of a pretend recognition, open AI glossary proofreading, open
the workbench. Steps may switch pages and wait until their target appears.
Esc skips, Enter/→ goes on, ← goes back. Nothing is uploaded or paid for:
the demo media and result come from the bundled example project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .i18n import bind_text, tr


@dataclass
class TourAction:
    label: str
    run: Callable[[], None]
    advance: bool = False   # go to the next step after running


@dataclass
class TourStep:
    text: str | Callable[[], str]          # one line; **marked** words in the accent colour
    target: Callable[[], QWidget | None] | None = None   # None: a centred card
    actions: list = field(default_factory=list)          # TourAction
    enter: Callable[[], None] | None = None              # runs when the step opens (page switch...)
    ready: Callable[[], bool] | None = None              # wait for this (default: target visible)
    next_label: str = '下一步'
    show_next: bool = True                               # False: an action moves on
    optional: bool = False                               # shown only if already there (no waiting)


class GuidedTour(QWidget):
    finished = Signal(bool)  # True when the last step was passed, False when skipped

    WAIT_MS = 20000
    TEXT_WIDTH = 440                                     # bubble text column (logical px)

    def __init__(self, window, steps: list[TourStep]):
        super().__init__(window)
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        self.window_ = window
        self.steps = steps
        self.index = -1
        self.theme = theme_definition(theme_key())
        self.hole = QRectF()
        self._entered = set()
        self._waiting = QTimer(self)
        self._waiting.setInterval(150)
        self._waiting.timeout.connect(self._poll)
        self._wait_left = 0
        self.setObjectName('guidedTour')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(window.rect())
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(280)
        self._motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_hole)
        self._build_bubble()
        window.installEventFilter(self)

    # ------------------------------------------------------------ bubble
    def _build_bubble(self):
        t = self.theme
        accent = QColor(t.accent)
        self.bubble = QFrame(self)
        self.bubble.setObjectName('tourBubble')
        self.bubble.setStyleSheet(
            f"QFrame#tourBubble {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 18px; }}"
            f"QLabel#tourCount {{ color: {t.accent}; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);"
            f" border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 700; }}"
            f"QLabel#tourText {{ color: {t.text}; font-size: 16px; }}"
            f"QPushButton#tourSkip {{ background: transparent; border: 0; color: {t.text_muted}; padding: 4px 6px; }}"
            f"QPushButton#tourSkip:hover {{ color: {t.text}; }}")
        shadow = QGraphicsDropShadowEffect(self.bubble)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.bubble.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self.bubble)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName('tourCount')
        top.addWidget(self.count)
        top.addStretch(1)
        self.skip = QPushButton()
        bind_text(self.skip, '跳过教学')
        self.skip.setObjectName('tourSkip')
        self.skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip.clicked.connect(lambda: self.close_tour(False))
        top.addWidget(self.skip)
        layout.addLayout(top)
        self.text = QLabel()
        self.text.setObjectName('tourText')
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.text.setFixedWidth(self.TEXT_WIDTH)
        layout.addWidget(self.text)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        layout.addLayout(self.buttons)
        self.action_buttons: list[QPushButton] = []
        from .design.presentation import button_role
        self.back = button_role(QPushButton(), 'ghost')
        bind_text(self.back, '上一步')
        self.back.clicked.connect(lambda: self.go(self.index - 1, step=-1))
        self.next = button_role(QPushButton(), 'primary')
        self.next.setObjectName('tourNext')
        self.next.clicked.connect(lambda: self.go(self.index + 1))

    def _fill_buttons(self, step: TourStep):
        from .design.presentation import button_role
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in (self.back, self.next):
                widget.deleteLater()
        self.action_buttons = []
        for index, action in enumerate(step.actions):
            primary = not step.show_next and index == 0
            button = button_role(QPushButton(), 'primary' if primary else 'secondary')
            bind_text(button, action.label)
            button.setObjectName(f'tourAction_{index}')
            button.clicked.connect(lambda _=False, a=action: self._run_action(a))
            self.buttons.addWidget(button)
            self.action_buttons.append(button)
        self.buttons.addStretch(1)
        self.buttons.addWidget(self.back)
        self.buttons.addWidget(self.next)
        self.back.setVisible(self.index > 0 and step.show_next)
        self.next.setVisible(step.show_next)
        bind_text(self.next, step.next_label)

    def _run_action(self, action: TourAction):
        try:
            action.run()
        except Exception:  # noqa: BLE001 - a failing demo action must not trap the user in the tutorial
            import traceback
            traceback.print_exc()
        if action.advance:
            self.go(self.index + 1)
        else:
            self.raise_()

    # ------------------------------------------------------------ steps
    def start(self):
        self.show()
        self.raise_()
        self.setFocus()
        self.go(0)

    def _target(self, index):
        step = self.steps[index] if 0 <= index < len(self.steps) else None
        if step is None or step.target is None:
            return None
        widget = step.target()
        return widget if widget is not None and widget.isVisible() else None

    def _is_ready(self, index) -> bool:
        step = self.steps[index]
        if step.ready is not None and not step.ready():
            return False
        return step.target is None or self._target(index) is not None

    def go(self, index: int, *, step: int = 1):
        self._waiting.stop()
        if index >= len(self.steps):
            self.close_tour(True)
            return
        if index < 0:
            return
        self.index = index
        current = self.steps[index]
        if index not in self._entered and current.enter is not None:
            self._entered.add(index)
            try:
                current.enter()
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
        if self._is_ready(index):
            self._show(index)
            return
        if current.optional:   # e.g. the proofreading page when the user chose not to open it
            self.go(index + step, step=step)
            return
        # Wait (page switch, import, project opening) with the bubble hidden.
        self.bubble.hide()
        self._wait_left = self.WAIT_MS
        self._wait_direction = step
        self._waiting.start()

    def _poll(self):
        self._wait_left -= self._waiting.interval()
        if self._is_ready(self.index):
            self._waiting.stop()
            self._show(self.index)
        elif self._wait_left <= 0:
            self._waiting.stop()
            self.go(self.index + self._wait_direction, step=self._wait_direction)  # this part is not available here

    def _show(self, index):
        from .onboarding import emphasis_html
        step = self.steps[index]
        widget = self._target(index)
        if widget is not None:
            scroll = widget.parent()
            while scroll is not None and not isinstance(scroll, QScrollArea):
                scroll = scroll.parent()
            if scroll is not None:
                scroll.ensureWidgetVisible(widget, 40, 60)
        text = step.text() if callable(step.text) else step.text
        self.text.setText(emphasis_html(str(tr(text)), self.theme.accent))
        # A wrapped label's size hint assumes its own width; pin both so no line is clipped.
        self.text.setFixedHeight(self.text.heightForWidth(self.TEXT_WIDTH))
        self.count.setText(f'{index + 1} / {len(self.steps)}')
        self._fill_buttons(step)
        self.bubble.adjustSize()
        self.raise_()
        self.bubble.show()
        target = self._rect_of(widget) if widget is not None else QRectF()
        from .ui_motion import reduced_motion
        if target.isNull() or self.hole.isNull() or reduced_motion():
            self._motion.stop()
            self._move_hole(target)
        else:
            self._motion.stop()
            self._motion.setStartValue(self.hole)
            self._motion.setEndValue(target)
            self._motion.start()
        (self.next if step.show_next else (self.action_buttons[0] if self.action_buttons else self.next)).setFocus()

    def _rect_of(self, widget) -> QRectF:
        top_left = widget.mapTo(self.window_, QPoint(0, 0))
        rect = QRectF(top_left.x(), top_left.y(), widget.width(), widget.height()).adjusted(-8, -8, 8, 8)
        return rect.intersected(QRectF(self.rect()).adjusted(6, 6, -6, -6))

    def _move_hole(self, rect):
        self.hole = QRectF(rect)
        self._place_bubble()
        self.update()

    def _place_bubble(self):
        size = self.bubble.sizeHint()
        self.bubble.resize(size)
        margin = 16
        if self.hole.isNull():   # a centred card
            self.bubble.move(int((self.width() - size.width()) / 2), int((self.height() - size.height()) / 2))
            return
        below = self.hole.bottom() + 14
        y = below if below + size.height() < self.height() - margin else self.hole.top() - 14 - size.height()
        if y < margin:  # a tall target: sit inside its lower edge instead
            y = min(self.height() - size.height() - margin, self.hole.bottom() - size.height() - 14)
        x = min(max(margin, self.hole.left()), self.width() - size.width() - margin)
        self.bubble.move(int(x), int(y))

    def close_tour(self, completed: bool):
        self._motion.stop()
        self._waiting.stop()
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit(bool(completed))
        self.deleteLater()

    # ------------------------------------------------------------ Qt
    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if watched is self.window_ and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.window_.rect())
            widget = self._target(self.index)
            self._move_hole(self._rect_of(widget) if widget is not None else QRectF())
        return False

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        key = event.key()
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if key == Qt.Key.Key_Escape:
            self.close_tour(False)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right) and step is not None and step.show_next:
            self.go(self.index + 1)
        elif key == Qt.Key.Key_Left and step is not None and step.show_next:
            self.go(self.index - 1, step=-1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        event.accept()  # the page underneath waits until the tutorial is closed

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.setFillRule(Qt.FillRule.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            shade.addRoundedRect(self.hole, 16, 16)
        painter.fillPath(shade, QColor(12, 9, 16, 178))
        if not self.hole.isNull():
            accent = QColor(self.theme.accent)
            for width, alpha in ((10, 40), (6, 70)):
                glow = QColor(accent)
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(self.hole, 16, 16)
            painter.setPen(QPen(accent, 2.5))
            painter.drawRoundedRect(self.hole, 16, 16)
        painter.end()


# Kept for callers of the first version.
HomeTour = GuidedTour


# ---------------------------------------------------------------- the tutorial

def tutorial_steps(window) -> list[TourStep]:
    """The whole first subtitle with demo data: home → pretend result → proofreading → workbench."""
    w = window
    get = lambda name: (lambda: w.__dict__.get(name))  # noqa: E731 - resolved when shown
    card = lambda role: (lambda: getattr(w.__dict__.get('recognition_plan'), 'cards', {}).get(role))  # noqa: E731
    studio = lambda name: (lambda: getattr(w.built_page('studio'), name, None) if w.built_page('studio') else None)  # noqa: E731
    on_home = lambda: w.pages.currentWidget() is w.__dict__.get('settings_scroll')  # noqa: E731
    on_completion = lambda: w.pages.currentWidget() is not None and w.pages.currentWidget().objectName() == 'completionScroll'  # noqa: E731

    def studio_ready():
        page = w.built_page('studio')
        return (page is not None and w.pages.currentWidget() is page and page.project is not None
                and page._readiness.ready and not page._readiness.active)

    def language():
        combo = w.__dict__.get('recognition_language')
        return str(combo.currentData() or '') if combo is not None else ''

    def set_language(code):
        combo = w.__dict__.get('recognition_language')
        if combo is not None and combo.findData(code) >= 0:
            combo.setCurrentIndex(combo.findData(code))

    def timeline_text():
        if language() == 'ja':
            return '**字幕时间轴**（日语用 CTC 对齐模型）：给**每个字**定时间（FireRedASR2 只认中文）'
        return '**字幕时间轴**（推荐 FireRedASR2）：给**每个字**定时间，并独立再识别一遍做对照（中文）'

    def leave_proofread():
        page = w.__dict__.get('glossary_proofread_page')
        if page is not None and w.pages.currentWidget() is page:
            page.back_button.click()

    return [
        TourStep('**两分钟带你做一遍**：用演示视频，不上传、不花钱；随时可以跳过', next_label='开始',
                 enter=w._tutorial_prepare_demo),
        TourStep('**放入影音**：把视频或音频拖进来，一次可以放好几个。先放一段演示视频', get('media_frame'),
                 [TourAction('放入演示视频', w._tutorial_add_demo_media, advance=True)], show_next=False, ready=on_home),
        TourStep('放进来了。放错了点这里的 **×** 就能移除，现在先留着', get('clear_single_media_button'),
                 ready=lambda: bool(getattr(w, 'media_paths', None))),
        TourStep('先选**字幕语言**：中文，或日本语（日语会换成适合日语的时间轴模型）', get('recognition_language'),
                 [TourAction('中文', lambda: set_language('zh')), TourAction('日本語', lambda: set_language('ja'))]),
        TourStep('**主力转写**（推荐 MOSS）：听出**谁在说话**，把多人对话分开，写出第一遍文字。点卡片可以更换', card('primary')),
        TourStep(timeline_text, card('timeline')),
        TourStep('**文字复核**（推荐 Qwen3-ASR）：第三次识别。三份结果互相比对，留下最可靠的文字和**精确到字的时间**',
                 card('review')),
        TourStep('**AI 智能断句**：按语气断句、校对专有名词。需要一把 AI 服务的 API Key，没有也能先跳过',
                 get('home_process_card'), [TourAction('填写 API Key', lambda: w._open_ai_settings_dialog())]),
        TourStep('**术语库**：填上游戏或节目名，勾选术语库，角色名和专有名词就会按它写对', get('content_profile_card')),
        TourStep('正式使用时点 **开始生成字幕**。现在不用等，直接看**识别完成**的样子', get('start_button'),
                 [TourAction('看演示结果', w._tutorial_demo_completion, advance=True)], show_next=False),
        TourStep('**识别完成**：标题告诉你结果，下面可以试听预览；有需要注意的地方会列出来', get('result_title'),
                 ready=on_completion),
        TourStep('**AI 词库校对**：一次找出写错的人名和术语，勾选的才会改', get('repolish_current_glossary_button'),
                 [TourAction('打开看看', lambda: w.repolish_current_glossary_button.click(), advance=True)]),
        TourStep('左边**勾选词库**，再点**按词库匹配**或 **AI 校对**；右边逐条采用，随时能撤销', get('glossary_proofread_page'),
                 optional=True),
        TourStep('**导出字幕**：存成 SRT、ASS、TXT，放到你选的文件夹', get('export_result_button'),
                 enter=leave_proofread, ready=on_completion),
        TourStep('**字幕工作台**：逐条修改、调时间、做字幕样式、压制视频', get('open_studio_result_button'),
                 [TourAction('打开看看', lambda: w.open_studio_result_button.click(), advance=True)], show_next=False),
        TourStep('点一条字幕就能**改文字**；改完自动保存，Ctrl+Z 撤销', studio('cue_table'), ready=studio_ready),
        TourStep('**时间轴**：拖动字幕两端改时间；按 **Q / W** 把起点或终点剪到播放头', studio('timeline')),
        TourStep('**标点**：一键添加或去掉标点，画面和导出一起变，文稿不会被改', studio('punctuation_button')),
        TourStep('**导出字幕**在这里，旁边的**压制成片**把字幕烧进视频', studio('studio_export_button')),
        TourStep('完成！现在可以**放入你自己的影音**开始了', next_label='回到首页', enter=None),
    ]


def start_home_tour(window, on_finished=None) -> GuidedTour | None:
    """Start the tutorial (one at a time)."""
    existing = window.findChild(GuidedTour)
    if existing is not None:
        return existing
    tour = GuidedTour(window, tutorial_steps(window))
    if on_finished is not None:
        tour.finished.connect(on_finished)
    tour.start()
    return tour
