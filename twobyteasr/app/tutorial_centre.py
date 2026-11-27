"""新手教学: the chapters as the questions a newcomer asks, one card each (2026-11-27).

History: 2026-11-16 a syllabus with a second tab of 新手任务; 2026-11-19 「学习路线」 (numbered
nodes on a line, the next chapter breathing); 2026-11-20 a landscape preview card.

2026-11-27 (user: the window is ugly and complicated, newcomers feel forced to study; they
picked draft B 「我想…」 of three). What made it feel like homework: fifteen numbered chapters on a
path, 「已学 N / 15 章 · 新手任务 0 / 15」, a 「新」 or 「未学」 on every row, and a tab of fifteen
empty boxes with 「教我」. Now:

* 兔白 at the top says to pick whatever they ran into, no need to learn it all; beside her a
  search field (「例如：剪掉开头」) that matches the question, the title, what it teaches and a few
  everyday words (``KEYWORDS``).
* 「大家最常问」: six big cards, each a question in the newcomer's own words (``QUESTIONS``) with
  how long it takes; 「其他问题」: the other nine as pills. A chapter already seen only gets a small
  「✓ 看过」. No numbers, counters, badges or task list (the ticks are still recorded by
  ``newbie_tasks``, just not listed).
* A card opens its details over the list, pushed in from the right (``PAGE_PUSH``, calm, no
  bounce): the still, the chapter, what it teaches and 「开始（约 N 分钟）」; 「换一个问题」 goes back.

Later on 2026-11-27 (user, on the host: it looked unlike the draft, weights off, too much empty
space): the cards were stretched to the window's height and filled with grey points. Now they
are the draft's (icon, question, minutes) at their own height, every size is the draft's times
one share of the window's width (``_scale_for``), the window is as tall as the questions, titles
use the real Heavy face and 兔白's name 猫啃.

The window only chooses: ``chosen`` holds the chapter id once it has closed; the main window
starts the tutorial (``MainWindow._start_home_tour``).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..design.main_ui_dialogs import SpringDialog
from ..i18n import bind_text, tr
from . import newbie_tasks, tutorial_chapters

# The chapter as the newcomer would ask for it. Source text (zh), translated like any UI string.
QUESTIONS = {
    'first': '我想做出第一份字幕',
    'how': '字幕是怎么做出来的？',
    'timeline': '时间轴上的颜色、轨道看不懂',
    'fix': '字幕有错字、人名写错',
    'studio': '想一条条改字、调时间',
    'select': '想一次改好多条字幕',
    'ai': '想让 AI 帮我补字幕、修字幕',
    'editor': '想改得更快（快捷键）',
    'terms': '游戏名词老是被听错',
    'bunny': '找不到按钮，想问人',
    'render': '想导出带字幕的视频',
    'speakers': '说话人的名字、颜色要改',
    'style': '想让字幕更好看',
    'cut': '想剪掉不要的片段',
    'audio': '声音太小或太吵',
}
POPULAR = ('first', 'fix', 'timeline', 'ai', 'cut', 'render')     # the six big cards, in this order
# Everyday words that should find a chapter (matched as typed, Simplified or Traditional).
KEYWORDS = {
    'first': '开始 生成 第一次 视频 影片 拖进 识别 開始 第一次 視頻 識別',
    'how': '原理 准 模型 準',
    'timeline': '时间轴 红线 红色 灰色 黄色 折叠 展开 往下滑 上下滑 轨道 颜色 时间線 時間軸 紅線 紅色 灰色 黃色 摺疊 折疊 展開 軌道 顏色 播放头 播放頭',
    'fix': '错字 人名 校对 改字 錯字 校對',
    'studio': '改字 时间 审核 剃刀 合并 時間 審核 合併 稽核',
    'select': '多选 全选 范围 套用 应用到 多選 全選 範圍 應用到',
    'ai': 'AI 补 修 重新识别 断句 翻译 优化 補 重新識別 斷句 翻譯 優化',
    'editor': '快捷键 快 快捷鍵',
    'terms': '术语 词库 名词 術語 詞庫 名詞',
    'bunny': '问 兔白 找不到 按钮 問 按鈕',
    'render': '导出 压制 画质 码率 編碼 匯出 導出 壓制 畫質 碼率',
    'speakers': '说话人 名字 颜色 合并 說話人 顏色 合併',
    'style': '样式 字体 颜色 好看 动效 位置 樣式 字體 顏色 動效',
    'cut': '剪 开头 结尾 删掉 切开 转场 剪辑 開頭 結尾 刪掉 切開 轉場 剪輯',
    'audio': '声音 音量 响度 太小 太吵 聲音 響度',
}
# Tints by what the chapter is for: making subtitles / making them better / going further.
TINT = {'first': 'start', 'how': 'start', 'timeline': 'start',
        'fix': 'better', 'studio': 'better', 'select': 'better', 'ai': 'better', 'speakers': 'better', 'terms': 'better',
        'editor': 'more', 'cut': 'more', 'audio': 'more', 'style': 'more', 'render': 'more', 'bunny': 'more'}
ICONS = {'first': 'fa5s.closed-captioning', 'how': 'fa5s.lightbulb', 'timeline': 'fa5s.stream',
         'fix': 'fa5s.spell-check', 'studio': 'fa5s.pen', 'select': 'fa5s.object-group', 'ai': 'fa5s.magic',
         'editor': 'fa5s.keyboard', 'terms': 'fa5s.book', 'bunny': 'fa5s.comment-dots', 'render': 'fa5s.film',
         'speakers': 'fa5s.user-friends', 'style': 'fa5s.palette', 'cut': 'fa5s.cut', 'audio': 'fa5s.volume-up'}


def chapter_status(chapter, done: set) -> str:
    if chapter.soon:
        return 'soon'
    if chapter.id in done:
        return 'done'
    return 'new' if chapter.new else 'todo'


def recommended(done: set) -> str:
    """The first chapter not learned yet (in the catalogue's order)."""
    return next((chapter.id for chapter in tutorial_chapters.CATALOG
                 if not chapter.soon and chapter.id not in done), '')


def question(chapter_id: str) -> str:
    chapter = tutorial_chapters.BY_ID.get(chapter_id)
    return QUESTIONS.get(chapter_id) or (chapter.title if chapter is not None else '')


def matches(chapter_id: str, typed: str) -> bool:
    """Search: the typed words against the question, title, points (as shown) and KEYWORDS."""
    words = [word.casefold() for word in str(typed or '').split() if word]
    if not words:
        return True
    chapter = tutorial_chapters.BY_ID.get(chapter_id)
    if chapter is None:
        return False
    shown = [question(chapter_id), chapter.title, *chapter.learn]
    haystack = ' '.join([*(str(tr(text)) for text in shown), *shown, KEYWORDS.get(chapter_id, '')]).casefold()
    return all(word in haystack for word in words)


def _tints(t) -> dict:
    """(soft fill, icon colour) per tint, from the theme."""
    return {'start': (t.accent_soft, t.accent), 'better': (t.info_soft, t.info), 'more': (t.success_soft, t.success)}


def _scale_for(width: int) -> float:
    """2026-11-27 (user: on the host the window was large but its cards tall and empty, unlike
    the draft): the draft's sizes are for a 980 px window; a wider one grows every size by the
    same share (in steps of 0.05, at most MOST_SCALE), so it keeps the draft's proportions."""
    share = max(1.0, min(MOST_SCALE, width / BASE_WIDTH))
    return round(share * 20) / 20


BASE_WIDTH = 980
MOST_SCALE = 1.35


def _qss(t, scale: float = 1.0) -> str:
    """The draft's sizes (980 px window) times ``scale``. Weights as the app has them: body in
    思源黑体 Medium, emphasis (≥ 600) in the real Heavy face (``TITLE_FONT_STACK``), 兔白's name
    in 猫啃 (``PLAYFUL_FONT_STACK``; a family in the sheet, or the app's sheet wins over setFont)."""
    from ..design.typography import PLAYFUL_FONT_STACK, TITLE_FONT_STACK

    def px(value: float) -> int:
        return max(1, round(value * scale))

    accent, heavy, cute = t.accent, TITLE_FONT_STACK, PLAYFUL_FONT_STACK
    return f"""
    QDialog#tutorialCentre {{ background: {t.surface}; border: 0; }}
    QWidget#centreBody, QWidget#centreList, QWidget#centreDetail {{ background: {t.surface}; }}
    QLabel#centreLabel {{ color: {t.text}; font-family: {heavy}; font-size: {px(15)}px; font-weight: 800;
        margin: 0 {px(4)}px 0 {px(4)}px; }}
    QLabel#centreFootNote, QLabel#detailNote {{ color: {t.text_secondary}; font-size: {px(13)}px; }}
    QLabel#centreEmpty {{ color: {t.text_secondary}; font-size: {px(14)}px; padding: {px(24)}px {px(6)}px; }}
    QPushButton#centreClose {{ background: {t.surface_elevated}; border: 1px solid {t.border};
        border-radius: {px(34) // 2}px; color: {t.text}; font-size: {px(18)}px; padding: 0;
        min-width: {px(34) - 2}px; max-width: {px(34) - 2}px; min-height: {px(34) - 2}px; max-height: {px(34) - 2}px; }}
    QPushButton#centreClose:hover {{ border-color: {t.border_strong}; }}
    QFrame#bunnySays {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: {px(18)}px; }}
    QLabel#bunnyName {{ color: {accent}; font-family: {cute}; font-size: {px(12)}px; background: transparent;
        border: 0; }}
    QLabel#bunnyLine {{ color: {t.text}; font-family: {heavy}; font-size: {px(15)}px; font-weight: 800;
        background: transparent; border: 0; }}
    QLineEdit#centreSearch {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {px(14)}px;
        padding: 0 {px(12)}px 0 {px(6)}px; color: {t.text}; font-size: {px(14)}px;
        min-height: {px(40) - 2}px; max-height: {px(40) - 2}px; }}
    QLineEdit#centreSearch:focus {{ border-color: {accent}; }}
    QPushButton#questionCard {{ background: {t.surface_elevated}; border: 1px solid {t.border};
        border-radius: {px(20)}px; padding: 0; text-align: left; }}
    QPushButton#questionCard:hover {{ border-color: {t.border_strong}; }}
    QLabel#cardQuestion {{ color: {t.text}; font-family: {heavy}; font-size: {px(17)}px; font-weight: 800;
        background: transparent; }}
    QLabel#cardMinutes {{ color: {t.text_secondary}; font-size: {px(12.5)}px; background: transparent; }}
    QLabel#seenTag {{ color: {t.success}; font-family: {heavy}; font-size: {px(12)}px; font-weight: 800; background: transparent; }}
    QPushButton#questionPill {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {px(18)}px;
        padding: 0; text-align: left; }}
    QPushButton#questionPill:hover {{ background: {t.surface_elevated}; border-color: {t.border_strong}; }}
    QLabel#pillText {{ color: {t.text}; font-family: {heavy}; font-size: {px(14)}px; font-weight: 800; background: transparent; }}
    QLabel#detailQuestion {{ color: {t.text_secondary}; font-size: {px(14)}px; }}
    QLabel#detailTitle {{ color: {t.text}; font-family: {heavy}; font-size: {px(24)}px; font-weight: 800; }}
    QLabel#detailPoints {{ color: {t.text}; font-size: {px(15)}px; }}
    QPushButton#centreStart {{ background: {accent}; color: {t.text_on_accent}; border: 0; border-radius: {px(16)}px;
        padding: {px(10)}px {px(22)}px; font-family: {heavy}; font-size: {px(15)}px; font-weight: 800; }}
    QPushButton#centreStart:hover {{ background: {t.accent_hover}; }}
    QPushButton#centreStart:disabled {{ background: {t.surface_elevated}; color: {t.text_secondary}; }}
    QPushButton#centreGhost, QPushButton#detailBack {{ background: transparent; color: {t.text_secondary}; border: 0;
        border-radius: {px(12)}px; padding: {px(7)}px {px(10)}px; font-size: {px(13)}px; }}
    QPushButton#detailBack {{ color: {t.text}; font-family: {heavy}; font-size: {px(14)}px; font-weight: 800; }}
    QPushButton#centreGhost:hover, QPushButton#detailBack:hover {{ background: {t.surface_elevated}; color: {t.text}; }}
    QScrollArea#centreScroll, QScrollArea#centreScroll > QWidget#qt_scrollarea_viewport
        {{ background: transparent; border: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 0; border: 0; }}
    QScrollBar::handle:vertical {{ background: {_faint(t.border)}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.border_strong}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """


def _faint(color: str) -> str:
    """A colour at half strength, so a scroll bar does not read as a divider (2026-11-19)."""
    value = QColor(color)
    return f'rgba({value.red()},{value.green()},{value.blue()},0.45)'


class _Theme:
    """The theme's tokens, with the few this window needs filled in when a theme lacks them."""

    def __init__(self, theme):
        self._t = theme

    def __getattr__(self, name):
        value = getattr(self._t, name, None)
        if value:
            return value
        fallback = {'success': '#3f9a63', 'success_soft': 'rgba(63,154,99,0.18)', 'info': '#4f7fc4',
                    'info_soft': 'rgba(79,127,196,0.18)', 'border': '#5a4d60', 'border_strong': '#574c60',
                    'text_on_accent': '#ffffff', 'app_background': '#19151c', 'accent_soft': 'rgba(179,68,112,0.18)'}
        return fallback.get(name, '#888888')


class _FlowLayout(QLayout):
    """Pills that wrap into lines; hidden ones (search) take no room."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt API
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802 - Qt API
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802 - Qt API
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt API
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width):  # noqa: N802 - Qt API
        return self._place(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802 - Qt API
        super().setGeometry(rect)
        self._place(rect, False)

    def sizeHint(self):  # noqa: N802 - Qt API
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 - Qt API
        size = QSize()
        for item in self._shown():
            size = size.expandedTo(item.minimumSize())
        return size

    def _shown(self):
        return [item for item in self._items if item.widget() is None or not item.widget().isHidden()]

    def _place(self, rect, measure):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._shown():
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return max(0, y + line - rect.y())


class _Bubble(QWidget):
    """A soft tint with the chapter's icon: a rounded square on a card, a circle on a pill."""

    def __init__(self, chapter_id: str, theme, size: int, icon: int, parent=None, *, circle: bool = False):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fill, colour = _tints(theme)[TINT.get(chapter_id, 'start')]
        self._fill = QColor(fill)
        self._radius = size / 2 if circle else round(size * 0.34)
        self._icon = QPixmap()
        try:
            from ..design.themed_icons import colored_icon
            ratio = self.devicePixelRatioF() or 1.0
            self._icon = colored_icon(ICONS.get(chapter_id, 'fa5s.circle'), colour).pixmap(QSize(icon, icon), ratio)
        except Exception:  # noqa: BLE001 - no icon font: the tint alone
            pass
        self._icon_size = icon

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fill)
        painter.drawRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        if not self._icon.isNull():
            offset = (self.width() - self._icon_size) // 2
            painter.drawPixmap(QRect(offset, offset, self._icon_size, self._icon_size), self._icon)
        painter.end()


class _RoundPicture(QWidget):
    """The chapter's still, in a rounded frame at its own proportions."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._picture = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_picture(self, picture: QPixmap) -> None:
        self._picture = picture
        self.update()

    def pixmap(self) -> QPixmap:
        return self._picture

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from PySide6.QtGui import QPainterPath, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(area, 16, 16)
        painter.setClipPath(clip)
        painter.fillRect(area, QColor(self.theme.app_background))
        if not self._picture.isNull():
            size = self._picture.size().toSizeF()
            scale = max(area.width() / size.width(), area.height() / size.height())
            width, height = size.width() * scale, size.height() * scale
            painter.drawPixmap(QRectF((area.width() - width) / 2, (area.height() - height) / 2, width, height),
                               self._picture, QRectF(self._picture.rect()))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(self.theme.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(area, 16, 16)
        painter.end()


class _LaidOutButton(QPushButton):
    """A button whose size is its layout's (a card or a pill). A plain QPushButton reports its
    own text's size (none here) until it is first shown, so the window measured the questions
    far too short and cut the pills off (2026-11-27)."""

    def sizeHint(self):  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.sizeHint() if layout is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.minimumSize() if layout is not None else super().minimumSizeHint()

    def hasHeightForWidth(self):  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.hasHeightForWidth() if layout is not None else super().hasHeightForWidth()

    def heightForWidth(self, width):  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.totalHeightForWidth(width) if layout is not None else super().heightForWidth(width)


class _Body(QWidget):
    """The list, with the details laid over it (pushed in from the right)."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setObjectName('centreBody')
        self._owner = owner

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._owner._lay_out_body()


def _label(name: str, text: str = '', **values) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    if text:
        bind_text(label, text, **values)
    return label


class TutorialCentre(SpringDialog):
    """新手教学: questions to pick from, one choice, then it closes."""

    OPEN_SIZE = QSize(980, 620)        # the smallest it opens at (the draft's size)
    LARGEST = QSize(1400, 1000)
    SHARE = (0.72, 0.82)               # of the main window's width / height
    PICTURE_RATIO = 187 / 440          # the stills' own height / width (TourAnim.SIZE)

    @classmethod
    def open_size(cls, window) -> QSize:
        """2026-11-27 (user: on the host's large screen the window looked small, lots of empty
        space): a share of the main window, between OPEN_SIZE and LARGEST, inside the screen."""
        width = round(window.width() * cls.SHARE[0]) if window is not None else 0
        height = round(window.height() * cls.SHARE[1]) if window is not None else 0
        size = QSize(min(cls.LARGEST.width(), max(cls.OPEN_SIZE.width(), width)),
                     min(cls.LARGEST.height(), max(cls.OPEN_SIZE.height(), height)))
        screen = window.screen() if window is not None else None
        if screen is not None:
            room = screen.availableGeometry().size()
            size = QSize(min(size.width(), max(cls.OPEN_SIZE.width(), room.width() - 40)),
                         min(size.height(), max(cls.OPEN_SIZE.height(), room.height() - 40)))
        return size

    def __init__(self, window, *, tab: str = 'chapters'):   # ``tab`` kept for old callers (no tabs since 2026-11-27)
        super().__init__(window)
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.window_ = window
        self.chosen = ''
        theme = theme_definition(theme_key())
        self._light = getattr(theme, 'is_light', False)
        self.setObjectName('tutorialCentre')
        bind_text(self, '新手教学 - 2ByteASR', property='windowTitle')
        self._theme = _Theme(theme)
        size = self.open_size(window)
        self._scale = _scale_for(size.width())
        self.setStyleSheet(_qss(self._theme, self._scale))
        self.setMinimumSize(QSize(860, 540))
        from . import onboarding
        state = onboarding.load_state()
        self.learned = set(state.get('chapters_done') or ())
        self.tasks_done = newbie_tasks.done_keys(window, state)
        self.pick = ''
        self._slide = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self._px(26), self._px(18), self._px(26), self._px(12))
        outer.setSpacing(self._px(14))
        outer.addLayout(self._build_head())
        self.body = _Body(self)
        outer.addWidget(self.body, 1)
        self.list_page = self._build_list()
        self.list_page.setParent(self.body)
        self.detail_page = self._build_detail()
        self.detail_page.setParent(self.body)
        self.detail_page.hide()

        foot = QHBoxLayout()
        keys = QPushButton()
        keys.setObjectName('centreGhost')
        keys.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(keys, '快捷键一览')
        keys.clicked.connect(self._open_shortcuts)
        foot.addWidget(keys)
        foot.addStretch(1)
        foot.addWidget(_label('centreFootNote', '之后随时在「说明 → 新手教学」回来'))
        outer.addLayout(foot)
        self.resize(size.width(), self._fitted_height(size))

    def _px(self, value: float) -> int:
        return max(1, round(value * self._scale))

    def _fitted_height(self, size: QSize) -> int:
        """As tall as the questions need (no empty strip under them), at most ``size``'s height.
        The cards keep their own height like the draft's; a tall window used to stretch them
        into big empty boxes (2026-11-27)."""
        layout = self.layout()
        for widget in (self, *self.findChildren(QWidget)):
            widget.ensurePolished()             # the sheet's sizes, before measuring
        self._flow.invalidate()
        layout.invalidate()
        layout.activate()
        margins = layout.contentsMargins()
        width = size.width() - margins.left() - margins.right()
        holder = self.scroll.widget()
        content = holder.heightForWidth(width) if holder.hasHeightForWidth() else holder.sizeHint().height()
        head, foot = (item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
                      for item in (layout.itemAt(0), layout.itemAt(layout.count() - 1)))   # 兔白's line wraps
        wanted = margins.top() + head + content + foot + margins.bottom() + 2 * layout.spacing() + self._px(6)
        return max(self.minimumHeight(), min(size.height(), wanted))

    # ------------------------------------------------------------ top: 兔白 and the search
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(self._px(12))
        self.bunny = self._bunny()
        if self.bunny is not None:
            head.addWidget(self.bunny, 0, Qt.AlignmentFlag.AlignVCenter)
        says = QFrame()
        says.setObjectName('bunnySays')
        words = QVBoxLayout(says)
        words.setContentsMargins(self._px(14), self._px(8), self._px(14), self._px(9))
        words.setSpacing(self._px(1))
        words.addWidget(_label('bunnyName', '兔白'))          # 猫啃: set in the sheet
        self.bunny_line = _label('bunnyLine', '遇到什么就点哪张卡，我陪你做一次。不用全部学～')
        self.bunny_line.setWordWrap(True)
        words.addWidget(self.bunny_line)
        head.addWidget(says, 1, Qt.AlignmentFlag.AlignVCenter)
        self.search = QLineEdit()
        self.search.setObjectName('centreSearch')
        self.search.setFixedSize(self._px(250), self._px(40))
        self.search.setClearButtonEnabled(True)
        bind_text(self.search, '例如：剪掉开头', property='placeholderText')
        try:
            from ..design.themed_icons import themed_icon
            self.search.addAction(themed_icon('fa5s.search', 'secondary'), QLineEdit.ActionPosition.LeadingPosition)
        except Exception:  # noqa: BLE001
            pass
        self.search.textChanged.connect(self.filter)
        head.addWidget(self.search, 0, Qt.AlignmentFlag.AlignVCenter)
        close = QPushButton('×')
        close.setObjectName('centreClose')
        close.setFixedSize(self._px(34), self._px(34))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(close, '关闭', property='toolTip')
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    def _bunny(self) -> QWidget | None:
        try:
            from ..design.bunny_mascot import BunnyMascot
            mascot = BunnyMascot(self, height=self._px(64), motion='bob')
            if mascot.available:
                mascot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                return mascot
            mascot.deleteLater()
        except Exception:  # noqa: BLE001 - no pictures: her face, or nothing
            pass
        face = _bunny_face()
        if face.isNull():
            return None
        label = QLabel()
        label.setPixmap(face.scaled(self._px(56), self._px(56), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        return label

    # ------------------------------------------------------------ the questions
    def _build_list(self) -> QWidget:
        scroll = self.scroll = _scroll()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName('centreList')
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, self._px(4), self._px(4))
        column.setSpacing(self._px(8))
        self.popular_label = _label('centreLabel', '大家最常问')
        column.addWidget(self.popular_label)
        grid = self._grid = QGridLayout()
        grid.setHorizontalSpacing(self._px(12))
        grid.setVerticalSpacing(self._px(12))
        self.cards = {}
        for index, key in enumerate(key for key in POPULAR if key in tutorial_chapters.BY_ID):
            card = self._card(key)
            self.cards[key] = card
            grid.addWidget(card, index // 3, index % 3)
        for column_index in range(3):
            grid.setColumnStretch(column_index, 1)
        column.addLayout(grid)
        column.addSpacing(self._px(8))
        self.other_label = _label('centreLabel', '其他问题')
        column.addWidget(self.other_label)
        pills_holder = QWidget()
        pills_holder.setObjectName('centreList')
        flow = _FlowLayout(pills_holder, spacing=self._px(8))
        self.pills = {}
        for chapter in tutorial_chapters.CATALOG:
            if chapter.id in self.cards or chapter.soon:
                continue
            pill = self._pill(chapter.id)
            self.pills[chapter.id] = pill
            flow.addWidget(pill)
        self._flow = flow
        column.addWidget(pills_holder)
        self.empty = _label('centreEmpty', '没找到这个问题。关掉这里，点顶栏的「问问兔白」直接问她。')
        self.empty.setWordWrap(True)
        self.empty.hide()
        column.addWidget(self.empty)
        column.addStretch(1)                # a window made taller: the room goes below, not into the cards
        self._list_column = column
        scroll.setWidget(holder)
        return scroll

    def _seen(self, key: str) -> QLabel | None:
        if key not in self.learned:
            return None
        seen = _label('seenTag', '✓ 看过')
        seen.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return seen

    def _card(self, key: str) -> QPushButton:
        chapter = tutorial_chapters.BY_ID[key]
        card = _LaidOutButton()
        card.setObjectName('questionCard')
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setProperty('chapter', key)
        # The draft's card: icon, the question, how long. Its own height; cards in a row match.
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(card)
        column.setContentsMargins(self._px(16), self._px(16), self._px(16), self._px(14))
        column.setSpacing(self._px(10))
        top = QHBoxLayout()
        top.addWidget(_Bubble(key, self._theme, self._px(44), self._px(21)), 0, Qt.AlignmentFlag.AlignTop)
        top.addStretch(1)
        seen = self._seen(key)
        if seen is not None:
            top.addWidget(seen, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(top)
        words = _label('cardQuestion', question(key))
        words.setWordWrap(True)
        words.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(words)
        column.addStretch(1)
        minutes = _label('cardMinutes', '约 {value0} 分钟', value0=chapter.minutes)
        minutes.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(minutes)
        card.clicked.connect(lambda _=False, k=key: self.open_detail(k))
        return card

    def _pill(self, key: str) -> QPushButton:
        pill = _LaidOutButton()
        pill.setObjectName('questionPill')
        pill.setCursor(Qt.CursorShape.PointingHandCursor)
        pill.setProperty('chapter', key)
        line = QHBoxLayout(pill)
        line.setContentsMargins(self._px(7), self._px(6), self._px(14), self._px(6))
        line.setSpacing(self._px(8))
        line.addWidget(_Bubble(key, self._theme, self._px(24), self._px(13), circle=True), 0,
                       Qt.AlignmentFlag.AlignVCenter)
        words = _label('pillText', question(key))
        words.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        line.addWidget(words, 0, Qt.AlignmentFlag.AlignVCenter)
        seen = self._seen(key)
        if seen is not None:
            line.addWidget(seen, 0, Qt.AlignmentFlag.AlignVCenter)
        line.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        pill.clicked.connect(lambda _=False, k=key: self.open_detail(k))
        return pill

    def filter(self, typed: str) -> None:
        """Show only the questions the typed words find."""
        shown_cards = shown_pills = 0
        for card in self.cards.values():
            self._grid.removeWidget(card)
        for key, card in self.cards.items():            # the cards found fill the grid from the left
            hit = matches(key, typed)
            card.setVisible(hit)
            if hit:
                self._grid.addWidget(card, shown_cards // 3, shown_cards % 3)
            shown_cards += hit
        for key, pill in self.pills.items():
            hit = matches(key, typed)
            pill.setVisible(hit)
            shown_pills += hit
        self.popular_label.setVisible(shown_cards > 0)
        self.other_label.setVisible(shown_pills > 0)
        self.empty.setVisible(shown_cards + shown_pills == 0)
        self._flow.invalidate()
        if self.detail_page.isVisible():
            self.close_detail()

    # ------------------------------------------------------------ details of one chapter
    def _build_detail(self) -> QWidget:
        page = QWidget()
        page.setObjectName('centreDetail')
        page.setAutoFillBackground(True)
        grid = QGridLayout(page)
        grid.setContentsMargins(4, 8, 4, 0)
        grid.setHorizontalSpacing(self._px(26))
        self.picture = _RoundPicture(self._theme)
        self.picture.setObjectName('previewPicture')
        grid.addWidget(self.picture, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        info = QVBoxLayout()
        info.setSpacing(self._px(12))
        info.addStretch(1)
        self.detail_question = _label('detailQuestion')
        self.detail_question.setWordWrap(True)
        info.addWidget(self.detail_question)
        self.preview_title = _label('detailTitle')
        self.preview_title.setWordWrap(True)
        info.addWidget(self.preview_title)
        self.preview_learn = _label('detailPoints')
        self.preview_learn.setTextFormat(Qt.TextFormat.RichText)
        self.preview_learn.setWordWrap(True)
        info.addWidget(self.preview_learn)
        button_row = QHBoxLayout()
        self.start_button = QPushButton()
        self.start_button.setObjectName('centreStart')
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self._start_picked)
        button_row.addWidget(self.start_button)
        button_row.addStretch(1)
        info.addLayout(button_row)
        info.addWidget(_label('detailNote', '用示范工程练习，按 Esc 随时停下'))
        info.addStretch(1)
        grid.addLayout(info, 0, 1)
        grid.setColumnStretch(0, 11)
        grid.setColumnStretch(1, 10)
        back = self.back_button = QPushButton()
        back.setObjectName('detailBack')
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(back, '‹  换一个问题')
        back.clicked.connect(self.close_detail)
        grid.addWidget(back, 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        grid.setRowStretch(0, 1)
        return page

    def select(self, key: str) -> None:
        """Fill the details with a chapter (they show with ``open_detail``)."""
        chapter = tutorial_chapters.BY_ID.get(key)
        if chapter is None:
            return
        self.pick = key
        status = chapter_status(chapter, self.learned)
        bind_text(self.detail_question, '「{value0}」', value0=tr(question(key)))
        bind_text(self.preview_title, chapter.title)
        self._render_learn()
        from .home_tour import tutorial_anim_path
        path = tutorial_anim_path(chapter.picture, self._light, still=True)
        self.picture.set_picture(QPixmap(str(path)) if path is not None else QPixmap())
        self.start_button.setEnabled(status != 'soon')
        if status == 'soon':
            bind_text(self.start_button, '即将推出')
        elif status == 'done':
            bind_text(self.start_button, '再看一遍（约 {value0} 分钟）', value0=chapter.minutes)
        else:
            bind_text(self.start_button, '开始（约 {value0} 分钟）', value0=chapter.minutes)
        self._fit_picture()

    def _render_learn(self) -> None:
        chapter = tutorial_chapters.BY_ID.get(self.pick)
        tick = self._theme.success
        from ..design.typography import TITLE_FONT_STACK
        heavy = TITLE_FONT_STACK.replace('"', "'")
        rows = ''.join(f'<div style="margin-top:6px"><span style="color:{tick}; font-family:{heavy}; font-weight:800">✓</span>&nbsp; '
                       f'{str(tr(line))}</div>' for line in (chapter.learn if chapter is not None else ()))
        self.preview_learn.setText(rows)

    def open_detail(self, key: str) -> None:
        self.select(key)
        page = self.detail_page
        page.setGeometry(self.body.rect())
        self._fit_picture()
        page.show()
        page.raise_()
        self._push(page, self.body.width(), 0)
        self.start_button.setFocus()

    def close_detail(self) -> None:
        self._stop_slide()
        self.detail_page.hide()
        self.detail_page.move(0, 0)
        card = self.cards.get(self.pick) or self.pills.get(self.pick)
        if card is not None and card.isVisible():
            card.setFocus()

    def _push(self, page, start_x: int, end_x: int) -> None:
        """Slide the details over the list (PAGE_PUSH: an even start, a long soft arrival)."""
        self._stop_slide()
        from ..design.transitions import enabled
        if not enabled() or not self.isVisible():
            page.move(end_x, 0)
            return
        from ..design.motion_tokens import PAGE_PUSH, easing_curve
        slide = QPropertyAnimation(page, b'pos', self)
        slide.setDuration(PAGE_PUSH.ms)
        slide.setStartValue(QPoint(start_x, 0))
        slide.setEndValue(QPoint(end_x, 0))
        try:
            slide.setEasingCurve(easing_curve(PAGE_PUSH))
        except Exception:  # noqa: BLE001
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide = slide
        slide.start()

    def _stop_slide(self) -> None:
        if self._slide is not None:
            self._slide.stop()
            self._slide = None

    def _lay_out_body(self) -> None:
        rect = self.body.rect()
        self.list_page.setGeometry(rect)
        if self.detail_page.isVisible() and self._slide is None:
            self.detail_page.setGeometry(rect)
        else:
            self.detail_page.resize(rect.size())
        self._fit_picture()

    def _fit_picture(self) -> None:
        """The still at its own proportions, as wide as its column allows."""
        width = max(1, round((self.body.width() - 8 - self._px(26)) * 11 / 21))
        height = max(80, min(round(width * self.PICTURE_RATIO), self.body.height() - 60))
        self.picture.setFixedHeight(height)

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape and self.detail_page.isVisible():
            self.close_detail()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_picked(self) -> None:
        self.start(self.pick)

    def start(self, key: str) -> None:
        chapter = tutorial_chapters.BY_ID.get(key)
        if chapter is None or chapter.soon:
            return
        self.chosen = key
        self.accept()

    def _open_shortcuts(self) -> None:
        self.chosen = ''
        self.reject()
        opener = getattr(self.window_, '_open_application_settings', None)
        if callable(opener):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: opener(initial_section='快捷键'))


def _scroll() -> QScrollArea:
    scroll = QScrollArea()
    scroll.setObjectName('centreScroll')
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.viewport().setAutoFillBackground(False)
    return scroll


def _bunny_face() -> QPixmap:
    try:
        from ..design.bunny_mascot import mascot_root
        return QPixmap(str(mascot_root() / 'bunny_face.png'))
    except Exception:  # noqa: BLE001
        return QPixmap()


def open_tutorial_centre(window, *, tab: str = 'chapters') -> str:
    """Show the centre; returns the chapter id to start ('' when closed)."""
    dialog = TutorialCentre(window, tab=tab)
    try:
        dialog.exec()
        return dialog.chosen
    finally:
        dialog.deleteLater()
