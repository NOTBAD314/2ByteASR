"""The tutorial centre: chapters on the left, a preview on the right, and 新手任务 (2026-11-16).

User (2026-11-16) chose draft C of three: a syllabus grouped 基础 / 进阶 / 即将推出 with a
preview and 「开始这一章」, and a second tab of small tasks ticked by themselves
(``newbie_tasks``). It opens from 「说明 → 新手教学」 and after a fresh install's first chapter.

The window only chooses: ``chosen`` holds the chapter id to start (or a task's chapter) once it
has closed; the main window starts the tutorial (``MainWindow._start_home_tour``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..design.main_ui_dialogs import SpringDialog
from ..i18n import bind_text, tr
from . import newbie_tasks, tutorial_chapters


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


def _qss(t) -> str:
    accent = t.accent
    return f"""
    QDialog#tutorialCentre {{ background: {t.surface}; border: 2px solid {accent}; border-radius: 26px; }}
    QLabel#centreTitle {{ color: {t.text}; font-size: 22px; font-weight: 800; }}
    QLabel#centreSub, QLabel#centreFootNote, QLabel#centreMeta, QLabel#taskHint, QLabel#centreGroup
        {{ color: {t.text_secondary}; font-size: 13px; }}
    QLabel#centreGroup {{ font-size: 12px; letter-spacing: 1px; margin: 8px 4px 2px 4px; }}
    QPushButton#centreClose {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 17px;
        color: {t.text}; font-size: 18px; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
    QPushButton#centreTab {{ background: transparent; border: 0; border-radius: 12px; padding: 6px 14px;
        color: {t.text_secondary}; font-size: 14px; }}
    QPushButton#centreTab:checked {{ background: {t.accent_soft}; color: {t.text}; font-weight: 700; }}
    QPushButton#chapterRow {{ background: transparent; border: 1px solid transparent; border-radius: 14px;
        padding: 0; text-align: left; }}
    QPushButton#chapterRow:hover {{ background: {t.surface_elevated}; }}
    QPushButton#chapterRow:checked {{ background: {t.surface_elevated}; border-color: {accent}; }}
    QLabel#rowTitle {{ color: {t.text}; font-size: 15px; }}
    QLabel#rowMinutes {{ color: {t.text_secondary}; font-size: 12px; }}
    QLabel#rowCheck {{ border: 2px solid {t.text_secondary}; border-radius: 12px; min-width: 20px; max-width: 20px;
        min-height: 20px; max-height: 20px; color: {t.text_on_accent}; font-size: 12px; qproperty-alignment: AlignCenter; }}
    QLabel#rowCheck[done="true"] {{ background: {t.success}; border-color: {t.success}; }}
    QLabel#pill {{ border-radius: 9px; padding: 1px 9px; font-size: 12px; font-weight: 700; }}
    QLabel#pill[kind="done"] {{ background: {t.success_soft}; color: {t.success}; }}
    QLabel#pill[kind="new"] {{ background: {t.info_soft}; color: {t.info}; }}
    QLabel#pill[kind="soon"] {{ background: {t.surface_elevated}; color: {t.text_secondary}; }}
    QLabel#pill[kind="todo"] {{ background: {t.accent_soft}; color: {t.text}; }}
    QFrame#centrePreview {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 20px; }}
    QLabel#previewPicture {{ background: {t.app_background}; border-radius: 14px; }}
    QLabel#previewTitle {{ color: {t.text}; font-size: 19px; font-weight: 800; }}
    QLabel#previewLearn {{ color: {t.text}; font-size: 14px; }}
    QPushButton#centreStart {{ background: {accent}; color: {t.text_on_accent}; border: 0; border-radius: 16px;
        padding: 10px 22px; font-size: 16px; font-weight: 700; }}
    QPushButton#centreStart:hover {{ background: {t.accent_hover}; }}
    QPushButton#centreStart:disabled {{ background: {t.surface}; color: {t.text_secondary}; }}
    QPushButton#centreGhost {{ background: {t.surface_elevated}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 14px; padding: 7px 14px; font-size: 13px; }}
    QFrame#taskCard {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 16px; }}
    QLabel#taskTitle {{ color: {t.text}; font-size: 14px; }}
    QLabel#taskTitle[done="true"] {{ color: {t.text_secondary}; text-decoration: line-through; }}
    QLabel#taskCheck {{ border: 2px solid {t.text_secondary}; border-radius: 7px; min-width: 22px; max-width: 22px;
        min-height: 22px; max-height: 22px; color: {t.text_on_accent}; qproperty-alignment: AlignCenter; }}
    QLabel#taskCheck[done="true"] {{ background: {t.success}; border-color: {t.success}; }}
    QScrollArea#centreScroll {{ background: transparent; border: 0; }}
    QWidget#centreList {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QPushButton#taskTeach {{ background: transparent; color: {accent}; border: 1px solid {accent}; border-radius: 11px;
        padding: 3px 10px; font-size: 12px; }}
    """


class _Theme:
    """The theme's tokens, with the few this window needs filled in when a theme lacks them."""

    def __init__(self, theme):
        self._t = theme

    def __getattr__(self, name):
        value = getattr(self._t, name, None)
        if value:
            return value
        fallback = {'success': '#3f9a63', 'success_soft': 'rgba(63,154,99,0.18)', 'info': '#4f7fc4',
                    'info_soft': 'rgba(79,127,196,0.18)', 'border': '#5a4d60'}
        return fallback.get(name, '#888888')


class _ChapterRow(QPushButton):
    """Let translated chapter names determine the row height."""
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(44, self.layout().totalHeightForWidth(width)) if self.layout() else 44

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(self.heightForWidth(self.width()))
        return size


class TutorialCentre(SpringDialog):
    """新手教学: the chapters and the 新手任务, one choice, then it closes."""

    def __init__(self, window, *, tab: str = 'chapters'):
        super().__init__(window)
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.window_ = window
        self.chosen = ''
        theme = theme_definition(theme_key())
        self._light = getattr(theme, 'is_light', False)
        self.setObjectName('tutorialCentre')
        bind_text(self, '新手教学 - 2ByteASR', property='windowTitle')
        self.setStyleSheet(_qss(_Theme(theme)))
        self.setMinimumSize(QSize(860, 560))
        from . import onboarding
        state = onboarding.load_state()
        self.learned = set(state.get('chapters_done') or ())
        self.tasks_done = newbie_tasks.done_keys(window, state)
        self.pick = recommended(self.learned) or tutorial_chapters.CATALOG[0].id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 16)
        outer.setSpacing(10)
        head = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel()
        title.setObjectName('centreTitle')
        bind_text(title, '新手教学')
        words.addWidget(title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName('centreSub')
        words.addWidget(self.subtitle)
        head.addLayout(words, 1)
        close = QPushButton('×')
        close.setObjectName('centreClose')
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(close, '关闭', property='toolTip')
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.tab_group = QButtonGroup(self)
        self.tab_buttons = {}
        for key, label in (('chapters', '章节'), ('tasks', '新手任务')):
            button = QPushButton()
            button.setObjectName('centreTab')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bind_text(button, label)
            button.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            self.tab_group.addButton(button)
            self.tab_buttons[key] = button
            tabs.addWidget(button)
        tabs.addStretch(1)
        outer.addLayout(tabs)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_chapters())
        self.stack.addWidget(self._build_tasks())
        outer.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        keys = QPushButton()
        keys.setObjectName('centreGhost')
        keys.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(keys, '快捷键一览')
        keys.clicked.connect(self._open_shortcuts)
        foot.addWidget(keys)
        foot.addStretch(1)
        note = QLabel()
        note.setObjectName('centreFootNote')
        bind_text(note, '之后随时在「说明 → 新手教学」回来')
        foot.addWidget(note)
        outer.addLayout(foot)
        self._refresh_subtitle()
        self.show_tab(tab)
        self.select(self.pick)

    # ------------------------------------------------------------ chapters
    def _build_chapters(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        scroll = _scroll()
        scroll.setFixedWidth(370)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName('centreList')
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(2)
        self.row_group = QButtonGroup(self)
        self.rows = {}
        group = ''
        for chapter in tutorial_chapters.CATALOG:
            if chapter.group != group:
                group = chapter.group
                label = QLabel()
                label.setObjectName('centreGroup')
                bind_text(label, group)
                column.addWidget(label)
            button = self._chapter_row(chapter)
            self.row_group.addButton(button)
            self.rows[chapter.id] = button
            column.addWidget(button)
        column.addStretch(1)
        scroll.setWidget(holder)
        row.addWidget(scroll)
        row.addWidget(self._build_preview(), 1)
        return page

    def _chapter_row(self, chapter) -> QPushButton:
        status = chapter_status(chapter, self.learned)
        button = _ChapterRow()
        button.setObjectName('chapterRow')
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(44)
        button.setProperty('chapter', chapter.id)
        line = QHBoxLayout(button)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(10)
        check = QLabel('✓' if status == 'done' else '')
        check.setObjectName('rowCheck')
        check.setProperty('done', status == 'done')
        line.addWidget(check)
        title = QLabel()
        title.setObjectName('rowTitle')
        title.setWordWrap(True)
        title.setMinimumWidth(0)
        bind_text(title, chapter.title)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        line.addWidget(title, 1)
        if status == 'new':
            line.addWidget(self._pill('new'))
        minutes = QLabel()
        minutes.setObjectName('rowMinutes')
        bind_text(minutes, '{value0} 分', value0=chapter.minutes)
        line.addWidget(minutes)
        for child in (check, minutes):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if status == 'soon':
            button.setProperty('soon', True)
            for child in (title, minutes):
                child.setEnabled(False)
        button.clicked.connect(lambda _=False, key=chapter.id: self.select(key))
        return button

    def _pill(self, kind: str) -> QLabel:
        pill = QLabel()
        pill.setObjectName('pill')
        pill.setProperty('kind', kind)
        pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bind_text(pill, {'done': '✓ 已完成', 'new': '新', 'soon': '即将推出', 'todo': '未学'}[kind])
        return pill

    def _build_preview(self) -> QFrame:
        card = QFrame()
        card.setObjectName('centrePreview')
        column = QVBoxLayout(card)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(10)
        self.picture = QLabel()
        self.picture.setObjectName('previewPicture')
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setFixedHeight(180)
        self.picture.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        column.addWidget(self.picture)
        top = QHBoxLayout()
        self.preview_title = QLabel()
        self.preview_title.setObjectName('previewTitle')
        self.preview_title.setWordWrap(True)
        self.preview_title.setMinimumWidth(0)
        top.addWidget(self.preview_title, 1)
        self.preview_pill_holder = QHBoxLayout()
        top.addLayout(self.preview_pill_holder)
        column.addLayout(top)
        self.preview_meta = QLabel()
        self.preview_meta.setObjectName('centreMeta')
        column.addWidget(self.preview_meta)
        self.preview_learn = QLabel()
        self.preview_learn.setObjectName('previewLearn')
        self.preview_learn.setTextFormat(Qt.TextFormat.RichText)
        self.preview_learn.setWordWrap(True)
        column.addWidget(self.preview_learn, 1)
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.bunny = QLabel()
        face = _bunny_face()
        if not face.isNull():
            self.bunny.setPixmap(face.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        bottom.addWidget(self.bunny)
        self.start_button = QPushButton()
        self.start_button.setObjectName('centreStart')
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self._start_picked)
        bottom.addWidget(self.start_button)
        bottom.addStretch(1)
        column.addLayout(bottom)
        return card

    def select(self, key: str) -> None:
        chapter = tutorial_chapters.BY_ID.get(key)
        if chapter is None:
            return
        self.pick = key
        button = self.rows.get(key)
        if button is not None:
            button.setChecked(True)
        status = chapter_status(chapter, self.learned)
        bind_text(self.preview_title, chapter.title)
        while self.preview_pill_holder.count():
            item = self.preview_pill_holder.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        pill = self._pill(status)
        self.preview_pill_holder.addWidget(pill)
        pill.show()
        bind_text(self.preview_meta, '约 {value0} 分钟', value0=chapter.minutes)
        lines = ''.join(f'<li>{str(tr(line))}</li>' for line in chapter.learn)
        self.preview_learn.setText(f'<b>{str(tr("会学到"))}</b><ul style="margin-left:-18px">{lines}</ul>')
        from .home_tour import tutorial_anim_path
        path = tutorial_anim_path(chapter.picture, self._light, still=True)
        picture = QPixmap(str(path)) if path is not None else QPixmap()
        if not picture.isNull():
            self.picture.setPixmap(picture.scaled(QSize(400, 176), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        else:
            self.picture.clear()
        self.start_button.setEnabled(status != 'soon')
        bind_text(self.start_button, {'soon': '即将推出', 'done': '再学一遍'}.get(status, '开始这一章 ›'))

    def _start_picked(self) -> None:
        self.start(self.pick)

    def start(self, key: str) -> None:
        chapter = tutorial_chapters.BY_ID.get(key)
        if chapter is None or chapter.soon:
            return
        self.chosen = key
        self.accept()

    # ------------------------------------------------------------ 新手任务
    def _build_tasks(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        scroll = _scroll()
        holder = QWidget()
        holder.setObjectName('centreList')
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.task_cards = {}
        for index, task in enumerate(newbie_tasks.TASKS):
            card = self._task_card(task)
            self.task_cards[task.key] = card
            grid.addWidget(card, index // 2, index % 2)
        grid.setRowStretch(len(newbie_tasks.TASKS) // 2 + 1, 1)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)
        note = QLabel()
        note.setObjectName('centreFootNote')
        note.setWordWrap(True)
        bind_text(note, '在你自己的工程里做过一次就会自动打勾（教学里的练习不算）')
        column.addWidget(note)
        return page

    def _task_card(self, task) -> QFrame:
        done = task.key in self.tasks_done
        card = QFrame()
        card.setObjectName('taskCard')
        card.setProperty('task', task.key)
        line = QHBoxLayout(card)
        line.setContentsMargins(12, 10, 12, 10)
        line.setSpacing(10)
        check = QLabel('✓' if done else '')
        check.setObjectName('taskCheck')
        check.setProperty('done', done)
        line.addWidget(check)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel()
        title.setObjectName('taskTitle')
        title.setProperty('done', done)
        bind_text(title, task.title)
        words.addWidget(title)
        hint = QLabel()
        hint.setObjectName('taskHint')
        hint.setWordWrap(True)
        bind_text(hint, task.hint)
        words.addWidget(hint)
        line.addLayout(words, 1)
        chapter = tutorial_chapters.BY_ID.get(task.chapter)
        if not done and chapter is not None and not chapter.soon:
            teach = QPushButton()
            teach.setObjectName('taskTeach')
            teach.setCursor(Qt.CursorShape.PointingHandCursor)
            bind_text(teach, '教我')
            bind_text(teach, '学「{value0}」这一章', property='toolTip', value0=tr(chapter.title))
            teach.clicked.connect(lambda _=False, key=chapter.id: self.start(key))
            line.addWidget(teach, 0, Qt.AlignmentFlag.AlignVCenter)
        return card

    # ------------------------------------------------------------ the rest
    def show_tab(self, key: str) -> None:
        key = key if key in self.tab_buttons else 'chapters'
        self.tab_buttons[key].setChecked(True)
        self.stack.setCurrentIndex(0 if key == 'chapters' else 1)

    def _refresh_subtitle(self) -> None:
        available = [chapter for chapter in tutorial_chapters.CATALOG if not chapter.soon]
        learned = sum(chapter.id in self.learned for chapter in available)
        bind_text(self.subtitle, '已学 {value0} / {value1} 章 · 新手任务 {value2} / {value3}',
                  value0=learned, value1=len(available), value2=len(self.tasks_done), value3=len(newbie_tasks.TASKS))

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
