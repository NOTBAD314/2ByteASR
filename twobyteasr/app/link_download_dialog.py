"""Link download window in the YDL GUI layout (user's design A, 2026-10-26).

首页 holds one link field, the download kind and, once parsed, the result
card; 队列 lists the task cards; 工具 and 设置 hold the downloader check and
the save location / network options; a status bar shows what is running.

Widget names stay the ones the controller, the acceptance audit and the
tests drive (``url``, ``parse_button``, ``mode``, ``video_format``,
``audio_format``, ``tracks``, ``primary``, ``translation``, ``destination``,
``clip``, ``auto_import``, ``add_button``, ``directory``, ``advanced``,
``proxy``, ``cookie``, ``message``).
"""
from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..i18n import tr, bind_text
from ..i18n_widgets import user_text
from ..design.studio_theme import apply_secondary_surface_theme, refresh_secondary_surface_theme, StudioComboBox
from ..design.soft_widgets import SegmentedControl, WrapLayout
from ..media.link_catalog import SOURCES, language_matches, preferred_track
from ..media import link_choices as choices
from .link_download_controller import link_preferences, save_link_preferences, default_directory
from .link_download_widgets import (STAGES, FILTERS, CoverView, TaskCard, apply_link_sheet, button, divider,
    icon_button, icon_label, named_label, pill, task_filter, ACTIVE, progress_parts)

__all__ = ["LinkDownloadDialog", "STAGES"]
HISTORY_LIMIT = 12
PAGES = ("home", "queue", "tools", "settings")


class NoticeLabel(QLabel):
    """Messages for every page; hidden while empty."""

    def __init__(self):
        super().__init__()
        self.setObjectName("linkNotice")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hide()

    def setText(self, text):  # noqa: N802 - Qt override
        super().setText(str(text or ""))
        self.setVisible(bool(str(text or "").strip()))


class LinkDownloadDialog(QDialog):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.catalog = None
        self.thumbnail = b""
        self._populating = False
        self._cards: dict[str, TaskCard] = {}
        self._tasks: list[dict] = []
        self._details: dict = {}
        self._filter = "all"
        self._chips: dict[str, QPushButton] = {}
        self.preferences = link_preferences()
        self.setWindowTitle(tr("链接下载 · 视频与字幕"))
        self.setModal(False)
        available = parent.screen().availableGeometry()
        # 2026-10-26 (user: too much empty space): smaller, and the height
        # follows the page's content until the user resizes the window.
        self.resize(min(900, available.width()-48), min(600, available.height()-70))
        self.setMinimumSize(720, 440)
        self._user_sized = False
        self._fitting = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.root = QWidget()
        self.root.setObjectName("linkRoot")
        outer.addWidget(self.root)
        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        notice = QHBoxLayout()
        notice.setContentsMargins(20, 6, 20, 0)
        self.message = NoticeLabel()
        notice.addWidget(self.message)
        layout.addLayout(notice)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_home())
        self.pages.addWidget(self._build_queue())
        self.pages.addWidget(self._build_tools())
        self.pages.addWidget(self._build_settings())
        layout.addWidget(self._build_status_bar())
        apply_secondary_surface_theme(self)
        apply_link_sheet(self.root)
        from .rounded_window import RoundedWindow
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.header], buttons=self.window_buttons)
        self.refresh_targets()
        self._mode_changed()
        self.show_page("home")

    # ------------------------------------------------------------------ frame
    def _build_header(self):
        header = QFrame()
        header.setObjectName("linkHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 7, 6, 7)
        row.setSpacing(10)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        mark = icon_label("fa5s.download", 15, "on_accent", "linkBrandMark")
        from .ui_zoom import set_size
        set_size(mark, fixed_w=32, fixed_h=32)
        brand.addWidget(mark)
        words = QVBoxLayout()
        words.setSpacing(0)
        words.addWidget(named_label(tr("链接下载"), "linkBrandTitle"))
        words.addWidget(named_label(tr("视频 · 音频 · 字幕"), "linkBrandNote"))
        brand.addLayout(words)
        brand_box = QWidget()
        brand_box.setLayout(brand)
        row.addWidget(brand_box, 1, Qt.AlignmentFlag.AlignLeft)
        self.nav_buttons = {}
        nav = QHBoxLayout()
        nav.setSpacing(6)
        for key, label, icon in (("home", "首页", "fa5s.home"), ("queue", "队列", "fa5s.list-ul"),
                                 ("tools", "工具", "fa5s.toolbox")):
            widget = button(tr(label), "linkNav", icon, "secondary")
            widget.setCheckable(True)
            widget.setProperty("flexibleWidth", True)
            widget.setIconSize(QSize(16, 16))
            widget.setToolTip(tr(label))
            widget.setAccessibleName(tr(label))
            widget.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_buttons[key] = widget
            nav.addWidget(widget)
        row.addLayout(nav, 0)
        right = QHBoxLayout()
        right.setSpacing(2)
        right.addStretch(1)
        folder = icon_button("fa5s.folder-open", tr("打开下载位置"))
        folder.clicked.connect(lambda: self._open_folder(""))
        right.addWidget(folder)
        self.settings_button = icon_button("fa5s.cog", tr("设置"))
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(lambda: self.show_page("settings"))
        right.addWidget(self.settings_button)
        right.addSpacing(6)
        # 2026-10-26 (user): the window has its own title bar (rounded_window);
        # this header is it, with the window buttons at its end.
        from .rounded_window import WindowButtons
        self.window_buttons = WindowButtons(self)
        right.addWidget(self.window_buttons)
        right_box = QWidget()
        right_box.setLayout(right)
        row.addWidget(right_box, 1)
        self.header = header
        return header

    def _build_status_bar(self):
        bar = QFrame()
        bar.setObjectName("linkStatusBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 5, 14, 5)
        row.setSpacing(12)
        self.status_active = named_label("", "linkStatusStrong")
        self.status_speed = named_label("", "linkStatusText")
        self.status_tools = named_label("", "linkStatusText")
        self.status_tools_dot = QLabel()
        self.status_tools_dot.setObjectName("linkDot")
        for widget in (self.status_active, self.status_speed):
            row.addWidget(widget)
            separator = QFrame()
            separator.setObjectName("linkStatusDivider")
            row.addWidget(separator)
        row.addWidget(self.status_tools_dot)
        row.addWidget(self.status_tools)
        row.addStretch(1)
        hint = named_label(tr("关闭窗口可继续下载；退出程序会取消任务。"), "linkStatusText")
        row.addWidget(hint)
        self._refresh_status()
        return bar

    # --------------------------------------------------------------- height
    def fit_height_later(self, *_):
        QTimer.singleShot(0, self, self._fit_height)

    def _fit_height(self):
        """Height of the current page's content (plus header and status bar),
        within the screen, until the user resizes the window themself."""
        if (self._user_sized or not self.isVisible() or self.isMaximized() or self.isFullScreen()
                or getattr(getattr(self, "chrome", None), "maximized", False)):
            return
        page = self.pages.currentWidget()
        content = page.widget() if isinstance(page, QScrollArea) else page
        width = page.viewport().width() if isinstance(page, QScrollArea) else page.width()
        need = content.heightForWidth(width) if content.hasHeightForWidth() else -1
        need = max(need, content.minimumSizeHint().height()) if need > 0 else content.sizeHint().height()
        if PAGES[self.pages.currentIndex()] == "queue":
            need = min(need, 620)   # a long queue scrolls
        chrome = self.height() - self.pages.height()
        screen = self.screen().availableGeometry()
        target = max(self.minimumHeight(), min(need + chrome, screen.height() - 70))
        self._resize_height(target, screen)
        if isinstance(page, QScrollArea) and PAGES[self.pages.currentIndex()] != "queue":
            QTimer.singleShot(0, self, self._fit_overflow)

    def _fit_overflow(self):
        """Wrapped words can make the estimate a few pixels short: grow by
        whatever the page still scrolls."""
        page = self.pages.currentWidget()
        if self._user_sized or not isinstance(page, QScrollArea) or not self.isVisible():
            return
        extra = page.verticalScrollBar().maximum()
        if extra > 0:
            screen = self.screen().availableGeometry()
            self._resize_height(min(self.height() + extra, screen.height() - 70), screen)

    def _resize_height(self, target, screen):
        if abs(target - self.height()) <= 1:
            return
        self._fitting = True
        try:
            self.resize(self.width(), target)
            top = max(screen.top(), min(self.y(), screen.bottom() + 1 - self.frameGeometry().height()))
            if top != self.y():
                self.move(self.x(), top)
        finally:
            self._fitting = False

    def resizeEvent(self, event):
        if event.spontaneous() and not self._fitting and self.isVisible() \
                and event.oldSize().isValid() and event.oldSize() != event.size():
            self._user_sized = True   # the user dragged an edge: leave the height to them
        super().resizeEvent(event)

    def show_page(self, key):
        self.pages.setCurrentIndex(PAGES.index(key))
        self.fit_height_later()
        for name, widget in self.nav_buttons.items():
            widget.setChecked(name == key)
            widget.setText(tr({"home": "首页", "queue": "队列", "tools": "工具"}[name]) if name == key else "")
        self.settings_button.setChecked(key == "settings")
        self._refresh_queue_badge()
        if key == "tools":
            self._refresh_tools()

    # ------------------------------------------------------------------- home
    def _build_home(self):
        scroll = QScrollArea()
        scroll.setObjectName("linkScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("linkRoot")
        scroll.setWidget(body)
        outer = QHBoxLayout(body)
        outer.setContentsMargins(24, 12, 24, 16)
        outer.addStretch(1)
        center = QWidget()
        center.setMaximumWidth(880)
        center.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(center, 100)
        outer.addStretch(1)
        column = QVBoxLayout(center)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        self.hero_space = QWidget()
        column.addWidget(self.hero_space)
        self.hero_head = QWidget()
        head = QVBoxLayout(self.hero_head)
        head.setContentsMargins(0, 0, 0, 4)
        head.setSpacing(4)
        title = named_label(tr("下载视频与字幕"), "linkHeroTitle")
        note = named_label(tr("支持 Bilibili、YouTube 等视频链接；尝试获取字幕并导入工作台"), "linkHeroNote")
        for label in (title, note):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(label)
        column.addWidget(self.hero_head)
        self.url_field = QFrame()
        self.url_field.setObjectName("linkUrlField")
        field = QHBoxLayout(self.url_field)
        field.setContentsMargins(18, 0, 18, 0)
        field.setSpacing(10)
        field.addWidget(icon_label("fa5s.link", 15, "muted"))
        self.url = QLineEdit()
        self.url.setPlaceholderText(tr("粘贴 Bilibili、YouTube 或其他网站的单个视频链接"))
        self.url.returnPressed.connect(self.parse)
        self.url.textChanged.connect(self._url_changed)
        field.addWidget(self.url, 1)
        column.addWidget(self.url_field)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.mode = StudioComboBox()
        for value, label in choices.MODES:
            self.mode.addItem(tr(label), value)
            self.mode.setItemData(self.mode.count()-1, tr(choices.MODE_NOTES[value]), Qt.ItemDataRole.ToolTipRole)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.mode_segment = SegmentedControl(self.mode, emit_activated=False)
        self.mode_segment.setObjectName("linkSegmented")
        self.mode_segment.setAccessibleName(tr("下载内容"))
        self.mode_segment.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.mode_segment, 0)
        controls.addStretch(1)
        self.cancel_parse = button(tr("取消解析"), "linkGhost")
        self.cancel_parse.clicked.connect(self._cancel_parse)
        self.cancel_parse.setEnabled(False)
        self.cancel_parse.hide()
        controls.addWidget(self.cancel_parse)
        self.parse_button = button(tr("解析视频"), "linkPrimary", "fa5s.search", "on_accent")
        self.parse_button.clicked.connect(self.parse)
        self.parse_button.setEnabled(False)
        controls.addWidget(self.parse_button)
        column.addLayout(controls)
        self.hero_tools = QWidget()
        tools = QHBoxLayout(self.hero_tools)
        tools.setContentsMargins(0, 2, 0, 0)
        tools.setSpacing(10)
        tools.addStretch(1)
        paste = button(tr("粘贴"), "linkGhost", "fa5s.paste", "secondary")
        paste.clicked.connect(self.paste_from_clipboard)
        tools.addWidget(paste)
        self.history_button = button(tr("解析历史"), "linkGhost", "fa5s.history", "secondary")
        self.history_button.clicked.connect(self._show_history)
        tools.addWidget(self.history_button)
        tools.addStretch(1)
        column.addWidget(self.hero_tools)
        self.hero_hints = QWidget()
        hints = QVBoxLayout(self.hero_hints)
        hints.setContentsMargins(0, 6, 0, 0)
        hints.setSpacing(2)
        for text in ("在字幕工作台按 Ctrl+V，可以直接用小卡片下载，不用打开这个窗口。",
                     "遇到下载问题？在「设置」选择 Cookie 文件，或到「工具」页修复下载工具。"):
            label = named_label(tr(text), "linkHint", wrap=True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hints.addWidget(label)
        column.addWidget(self.hero_hints)
        self.result_card = self._build_result_card()
        self.result_card.hide()
        column.addWidget(self.result_card)
        column.addStretch(1)
        self._set_hero(True)
        return scroll

    def _set_hero(self, hero: bool):
        from .ui_zoom import set_size
        set_size(self.hero_space, fixed_h=20 if hero else 0)
        for widget in (self.hero_head, self.hero_tools, self.hero_hints):
            widget.setVisible(hero)
        self.result_card.setVisible(not hero)
        self.url_field.setProperty("compact", not hero)
        self.url_field.style().unpolish(self.url_field)
        self.url_field.style().polish(self.url_field)
        self.fit_height_later()

    def _field(self, text):
        label = named_label(tr(text), "linkFieldLabel")
        label.setMinimumWidth(64)
        return label

    def _build_result_card(self):
        card = QFrame()
        card.setObjectName("linkCard")
        column = QVBoxLayout(card)
        column.setContentsMargins(18, 14, 18, 14)
        column.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.cover = CoverView(176, 99, 10)
        top.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(5)
        self.title = user_text(QLabel(tr("解析后选择画质、音轨和字幕；有字幕即可直接编辑，无须识别模型。")))
        self.title.setObjectName("linkTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.meta_label = user_text(named_label("", "linkMeta", wrap=True))
        info.addWidget(self.meta_label)
        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(8)
        self.summary_pills = [pill(), pill(), pill()]
        for item in self.summary_pills:
            self.summary_row.addWidget(item)
        self.summary_row.addStretch(1)
        info.addLayout(self.summary_row)
        info.addStretch(1)
        top.addLayout(info, 1)
        column.addLayout(top)
        column.addWidget(divider())
        # One form grid: 画质 / 字幕 / 工程原文 labels in one column, 音轨 and
        # 双语译文 in another (2026-10-26; the subtitle pair sat indented in
        # smaller grey words under the chips).
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.video_format = StudioComboBox()
        self.audio_format = StudioComboBox()
        self.audio_format.currentIndexChanged.connect(self._audio_warning)
        self.video_format.currentIndexChanged.connect(self._video_changed)
        grid.addWidget(self._field("画质"), 0, 0)
        grid.addWidget(self.video_format, 0, 1)
        grid.addWidget(self._field("音轨"), 0, 2)
        grid.addWidget(self.audio_format, 0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(3, 2)
        self.audio_note = named_label("", "linkHint", wrap=True)
        grid.addWidget(self.audio_note, 1, 1, 1, 3)
        label = self._field("字幕")
        label.setContentsMargins(0, 7, 0, 0)
        grid.addWidget(label, 2, 0, Qt.AlignmentFlag.AlignTop)
        stack = QVBoxLayout()
        stack.setSpacing(6)
        self.chip_host = QWidget()
        self.chip_layout = WrapLayout(self.chip_host, spacing=8, fill=False)
        stack.addWidget(self.chip_host)
        self.subtitle_status = named_label(tr("尚未解析字幕"), "linkHint", wrap=True)
        stack.addWidget(self.subtitle_status)
        self.all_tracks = QWidget()
        all_tracks = QVBoxLayout(self.all_tracks)
        all_tracks.setContentsMargins(0, 0, 0, 0)
        all_tracks.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("筛选字幕语言或来源"))
        self.filter.textChanged.connect(self._filter_tracks)
        all_tracks.addWidget(self.filter)
        self.tracks = QTreeWidget()
        self.tracks.setHeaderLabels([tr("下载"), tr("语言"), tr("字幕来源"), tr("可用格式"), tr("轨道名称")])
        self.tracks.setRootIsDecorated(False)
        self.tracks.setUniformRowHeights(True)
        self.tracks.setMinimumHeight(150)
        self.tracks.setMaximumHeight(240)
        self.tracks.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tracks.header().setStretchLastSection(True)
        self.tracks.itemChanged.connect(self._selection_changed)
        all_tracks.addWidget(self.tracks)
        self.all_tracks.hide()
        stack.addWidget(self.all_tracks)
        grid.addLayout(stack, 2, 1, 1, 3)
        self.primary = StudioComboBox()
        self.translation = StudioComboBox()
        self.primary.currentIndexChanged.connect(self._audio_warning)
        grid.addWidget(self._field("工程原文"), 3, 0)
        grid.addWidget(self.primary, 3, 1)
        grid.addWidget(self._field("双语译文（可选）"), 3, 2)
        grid.addWidget(self.translation, 3, 3)
        self.subtitle_hint = named_label(tr("只下载勾选语言。额外语言保留文件；译文按时间关联，无法可靠匹配的部分保留待处理。"),
                                         "linkHint", wrap=True)
        self.subtitle_hint.hide()
        grid.addWidget(self.subtitle_hint, 4, 1, 1, 3)
        column.addLayout(grid)
        column.addWidget(divider())
        self.details_toggle = button(tr("导入细节：素材片段与已有字幕"), "linkLink", "fa5s.chevron-down", "accent")
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(self._toggle_details)
        column.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.import_details = QWidget()
        details = QGridLayout(self.import_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(8)
        self.clip = StudioComboBox()
        self.confirm_media = QCheckBox(tr("我确认所选字幕属于此素材"))
        self.policy = StudioComboBox()
        self.policy.addItem(tr("追加，保留已有编辑"), False)
        self.policy.addItem(tr("仅替换所选素材的同一字幕来源（可撤销）"), True)
        details.addWidget(named_label(tr("字幕对应的素材片段"), "linkHint"), 0, 0)
        details.addWidget(self.clip, 0, 1)
        details.addWidget(self.confirm_media, 1, 1)
        details.addWidget(named_label(tr("已有字幕"), "linkHint"), 2, 0)
        details.addWidget(self.policy, 2, 1)
        details.setColumnStretch(1, 1)
        self.import_details.hide()
        column.addWidget(self.import_details)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.auto_import = QCheckBox(tr("下载完成后导入"))
        self.auto_import.setChecked(True)
        self.auto_import.toggled.connect(self._update_add_text)
        footer.addWidget(self.auto_import)
        self.destination = StudioComboBox()
        self.destination.currentIndexChanged.connect(self._mode_changed)
        self.destination.setMinimumWidth(220)
        footer.addWidget(self.destination, 1)
        self.directory_link = button("", "linkLink")
        self.directory_link.setProperty("flexibleWidth", True)
        self.directory_link.clicked.connect(lambda: self.show_page("settings"))
        footer.addWidget(self.directory_link)
        self.add_button = button(tr("下载并导入"), "linkPrimary", "fa5s.download", "on_accent")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.enqueue)
        footer.addWidget(self.add_button)
        column.addLayout(footer)
        return card

    def _toggle_details(self, shown):
        self.import_details.setVisible(shown)
        self.fit_height_later()
        from ..design.themed_icons import install_themed_icon
        install_themed_icon(self.details_toggle, "fa5s.chevron-up" if shown else "fa5s.chevron-down", "accent")

    def _update_add_text(self, *_):
        bind_text(self.add_button, "下载并导入" if self.auto_import.isChecked() else "开始下载")

    def _url_changed(self, text):
        self.parse_button.setEnabled(bool(text.strip()) and not self.cancel_parse.isEnabled())

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text().strip()
        link = choices.find_video_link(text)
        self.url.setText(link or text)
        if link:
            self.parse()

    def _show_history(self):
        from ..design.studio_theme import create_studio_menu
        menu = create_studio_menu(self)
        history = self.preferences.get("history", [])
        if not history:
            menu.addAction(tr("还没有解析记录")).setEnabled(False)
        for entry in history:
            action = menu.addAction(entry.get("title") or entry.get("url", ""))
            action.setToolTip(entry.get("url", ""))
            action.triggered.connect(lambda _=False, url=entry.get("url", ""): (self.url.setText(url), self.parse()))
        menu.exec(self.history_button.mapToGlobal(self.history_button.rect().bottomLeft()))

    # ----------------------------------------------------------------- parsing
    def _network(self):
        return dict(proxy=self.proxy.text().strip() if self.advanced.isChecked() else "",
                    cookie_file=self.cookie.text() if self.advanced.isChecked() else "")

    def parse(self):
        if not self.parse_button.isEnabled() or self.cancel_parse.isEnabled():
            return
        self.catalog = None
        self.add_button.setEnabled(False)
        self.parse_button.setEnabled(False)
        self.cancel_parse.setEnabled(True)
        self.cancel_parse.show()
        self.show_page("home")
        self.message.setText(tr("正在解析；带播放列表参数的链接只处理当前视频。"))
        self.controller.analyze(self.url.text(), owner="dialog", **self._network())

    def _cancel_parse(self):
        self.controller.cancel_analysis()
        self.parsing_finished()
        self.message.setText(tr("已取消"))

    def parsing_finished(self):
        self.cancel_parse.setEnabled(False)
        self.cancel_parse.hide()
        self.parse_button.setEnabled(bool(self.url.text().strip()))

    def set_thumbnail(self, data: bytes):
        """The cover, when it arrives after the choices (2026-10-26)."""
        self.thumbnail = bytes(data or b"")
        self.cover.set_image(self.thumbnail)

    def set_catalog(self, catalog, thumbnail=b""):
        self.catalog = catalog
        self.thumbnail = bytes(thumbnail or b"")
        self.parsing_finished()
        self._populating = True
        self._set_hero(False)
        self.title.setText(catalog["title"])
        meta = [catalog.get("uploader", ""), choices.upload_date_text(catalog.get("upload_date", "")),
                choices.duration_text(catalog.get("duration", 0)),
                {"youtube": "YouTube", "bilibili": "Bilibili"}.get(str(catalog.get("platform", "")).lower(), catalog.get("platform", ""))]
        self.meta_label.setText(" · ".join(part for part in meta if part))
        self.cover.set_image(self.thumbnail)
        self.cover.set_badge(choices.duration_text(catalog.get("duration", 0)))
        self._set_summary()
        self.video_format.clear()
        self.audio_format.clear()
        videos = choices.video_formats(catalog)
        unknown = tr("大小未知")
        for f in videos:
            self.video_format.addItem(choices.video_label(f, unknown), f["format_id"])
        self.video_format.setCurrentIndex(choices.preferred_video_index(videos))
        self.audio_format.addItem(tr("使用视频自带音轨（如有）"), "")
        audios = choices.audio_formats(catalog)
        for f in audios:
            self.audio_format.addItem(choices.audio_label(f, tr("语言未知"), unknown), f["format_id"])
        self.audio_format.setCurrentIndex(max(0, self.audio_format.findData(
            choices.preferred_audio(audios, videos[choices.preferred_video_index(videos)] if videos else None).get("format_id", ""))))
        self.tracks.clear()
        preferred_id = preferred_track(catalog, self.preferences.get("languages", []))
        for track in catalog["tracks"]:
            name = tr(choices.language_name(track["language"], track["language"]))
            language = name if name == track["language"] else f"{name} ({track['language']})"
            item = QTreeWidgetItem(["", language, tr(SOURCES[track["source"]]),
                                   " / ".join(track["formats"]), track["label"]])
            item.setData(0, Qt.ItemDataRole.UserRole, track["track_id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if track["track_id"] == preferred_id else Qt.CheckState.Unchecked)
            item.setToolTip(4, track["track_id"])
            self.tracks.addTopLevelItem(item)
        messages = dict(none="未发现可下载字幕；画面内嵌字幕不能直接提取。仍可下载视频后选择识别。",
            incomplete="字幕查询未完成或需要登录；可在设置选择 Cookie 文件后重试，仍可独立下载视频。",
            available="已区分人工、原语自动、自动翻译与来源待确认的字幕。")
        self.subtitle_status.setText(tr(messages[catalog["subtitle_status"]]))
        self.subtitle_status.setVisible(catalog["subtitle_status"] != "available")
        self._build_chips()
        self._populating = False
        self._selection_changed()
        self._mode_changed()
        self._video_changed()
        self.message.clear()
        self.add_button.setEnabled(True)
        self._remember(catalog)

    def apply_selection(self, selection: dict):
        """Take over choices made in the quick card (更多选项…)."""
        mode = self.mode.findData(selection.get("mode", "both"))
        if mode >= 0:
            self.mode.setCurrentIndex(mode)
        for combo, key in ((self.video_format, "video_format"), (self.audio_format, "audio_format")):
            index = combo.findData(selection.get(key, ""))
            if index >= 0 and selection.get(key):
                combo.setCurrentIndex(index)
        wanted = set(selection.get("track_ids", []))
        if wanted:
            for i in range(self.tracks.topLevelItemCount()):
                item = self.tracks.topLevelItem(i)
                item.setCheckState(0, Qt.CheckState.Checked if item.data(0, Qt.ItemDataRole.UserRole) in wanted
                                   else Qt.CheckState.Unchecked)
            index = self.primary.findData(selection.get("primary_track_id", ""))
            if index >= 0:
                self.primary.setCurrentIndex(index)
        if "auto_import" in selection:
            self.auto_import.setChecked(bool(selection["auto_import"]))

    def _remember(self, catalog):
        history = [entry for entry in self.preferences.get("history", []) if entry.get("url") != catalog["url"]]
        history.insert(0, dict(url=catalog["url"], title=catalog["title"]))
        self.preferences["history"] = history[:HISTORY_LIMIT]
        save_link_preferences(self.preferences)

    def _set_summary(self):
        catalog = self.catalog
        tracks = catalog["tracks"]
        if catalog["subtitle_status"] == "incomplete":
            first = (tr("字幕列表不完整"), "warn")
        elif any(t["source"] == "manual" for t in tracks):
            first = (tr("有人工字幕"), "ok")
        elif tracks:
            first = (tr("只有自动字幕"), "accent")
        else:
            first = (tr("暂无字幕"), "off")
        quality = choices.quality_summary(catalog)
        values = [first, (tr("最高 {quality}", quality=quality), "off") if quality else ("", "off"),
                  (tr("{count} 条字幕可选", count=len(tracks)), "off") if tracks else ("", "off")]
        from .link_download_widgets import set_tone
        for widget, (text, tone) in zip(self.summary_pills, values):
            widget.setText(text)
            set_tone(widget, tone)
            widget.setVisible(bool(text))

    def _build_chips(self):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._chips = {}
        if not self.catalog or not self.catalog["tracks"]:
            self.all_tracks_toggle = None
            return
        for track in choices.chip_tracks(self.catalog, self.preferences.get("languages", [])):
            name = tr(choices.language_name(track["language"], track.get("label", "")))
            chip = button(f"{name} · {tr(choices.SOURCE_SHORT.get(track['source'], '来源待确认'))}", "linkChip")
            user_text(chip)
            chip.setCheckable(True)
            chip.setProperty("flexibleWidth", True)
            chip.setToolTip(tr(SOURCES[track["source"]]) + " · " + track["label"])
            chip.toggled.connect(lambda on, tid=track["track_id"]: self._chip_toggled(tid, on))
            self._chips[track["track_id"]] = chip
            self.chip_layout.addWidget(chip)
        self.all_tracks_toggle = button(tr("全部 {count} 条…", count=len(self.catalog["tracks"])), "linkLink")
        self.all_tracks_toggle.setProperty("flexibleWidth", True)
        self.all_tracks_toggle.setCheckable(True)
        self.all_tracks_toggle.toggled.connect(self.all_tracks.setVisible)
        self.all_tracks_toggle.toggled.connect(self.subtitle_hint.setVisible)
        self.all_tracks_toggle.setChecked(self.all_tracks.isVisible())
        self.chip_layout.addWidget(self.all_tracks_toggle)

    def _chip_toggled(self, track_id, on):
        if self._populating:
            return
        for i in range(self.tracks.topLevelItemCount()):
            item = self.tracks.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == track_id:
                item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def checked_tracks(self):
        return [self.tracks.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.tracks.topLevelItemCount())
                if self.tracks.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def _selection_changed(self, *_):
        if self._populating or self.catalog is None:
            return
        chosen = self.checked_tracks()
        for track_id, chip in self._chips.items():
            chip.blockSignals(True)
            chip.setChecked(track_id in chosen)
            chip.blockSignals(False)
        old_primary, old_translation = self.primary.currentData(), self.translation.currentData()
        self.primary.clear()
        self.translation.clear()
        self.primary.addItem(tr("不导入字幕"), "")
        self.translation.addItem(tr("不关联译文"), "")
        for track in self.catalog["tracks"]:
            if track["track_id"] in chosen:
                label = f"{tr(choices.language_name(track['language'], track['language']))} · {tr(SOURCES[track['source']])}"
                self.primary.addItem(label, track["track_id"])
                self.translation.addItem(label, track["track_id"])
        self.primary.setCurrentIndex(max(1 if chosen else 0, self.primary.findData(old_primary)))
        self.translation.setCurrentIndex(max(0, self.translation.findData(old_translation)))
        self._audio_warning()

    def _filter_tracks(self, text):
        text = text.casefold()
        for index in range(self.tracks.topLevelItemCount()):
            item = self.tracks.topLevelItem(index)
            item.setHidden(bool(text) and not any(text in item.text(c).casefold() for c in range(1, 5)))

    def _video_changed(self):
        if self._populating or self.catalog is None:
            return
        mode = self.mode.currentData()
        selected = next((f for f in self.catalog["formats"] if f["format_id"] == self.video_format.currentData()), {})
        has_audio = choices.has_audio(selected)
        audios = choices.audio_formats(self.catalog)
        if mode == "audio":
            if self.audio_format.currentIndex() == 0 and self.audio_format.count() > 1:
                self.audio_format.setCurrentIndex(max(1, self.audio_format.findData(
                    choices.preferred_audio(audios).get("format_id", ""))))
            self.audio_format.setEnabled(self.audio_format.count() > 1)
            return
        if has_audio:
            self.audio_format.setCurrentIndex(0)
        elif self.audio_format.currentIndex() == 0 and self.audio_format.count() > 1:
            self.audio_format.setCurrentIndex(max(1, self.audio_format.findData(
                choices.preferred_audio(audios, selected).get("format_id", ""))))
        self.audio_format.setEnabled(not has_audio and mode != "subtitles")

    def _audio_warning(self, *_):
        if not self.catalog:
            return
        audio = next((f for f in self.catalog["formats"] if f["format_id"] == (
            self.audio_format.currentData() or self.video_format.currentData())), {})
        track = next((t for t in self.catalog["tracks"] if t["track_id"] == self.primary.currentData()), {})
        language = audio.get("language") or self.catalog.get("language")
        mismatch = language and track and not language_matches(language, track["language"])
        if self.mode.currentData() == "audio":
            text = tr("只下载这条音轨；导入后可以在工作台里识别字幕。")
        elif mismatch and self.mode.currentData() == "both":
            text = tr("字幕语言与所选音轨不同，请确认是否为配音音轨。")
        else:
            text = ""
        self.audio_note.setText(text)
        self.audio_note.setVisible(bool(text))

    def refresh_targets(self):
        previous = self.destination.currentData()
        self.destination.blockSignals(True)
        self.destination.clear()
        page = self.controller.page()
        project = getattr(page, "project", None)
        if project:
            self.destination.addItem(tr("导入当前工程") + " · " + project.media.display_name, "current")
        self.destination.addItem(tr("新建工程"), "new")
        self.destination.setCurrentIndex(max(0, self.destination.findData(previous)))
        self.destination.blockSignals(False)
        self.clip.clear()
        self.clip.addItem(tr("只按同一视频身份自动匹配"), "")
        if project:
            assets = {a.asset_id: a for a in project.media_pool}
            for lane in project.video_tracks:
                for clip in lane.clips:
                    self.clip.addItem(f"{lane.id} · {assets[clip.asset_id].display_name} · {clip.timeline_in_ms/1000:.2f}s · {clip.id}", clip.id)
        self._mode_changed()

    def _mode_changed(self, *_):
        if not hasattr(self, "clip"):
            return
        mode = self.mode.currentData()
        video = mode in ("both", "video")
        subs = mode in ("both", "subtitles")
        self.video_format.setEnabled(video)
        self.audio_format.setEnabled(mode != "subtitles")
        self.tracks.setEnabled(subs)
        self.primary.setEnabled(subs)
        self.translation.setEnabled(subs)
        for chip in self._chips.values():
            chip.setEnabled(subs)
        self.clip.setEnabled(self.destination.currentData() == "current")
        self.confirm_media.setEnabled(self.clip.isEnabled())
        self._refresh_directory_link()
        if self.catalog:
            self._video_changed()
            self._audio_warning()

    def _refresh_directory_link(self):
        if hasattr(self, "directory"):
            path = Path(self.directory.text())
            folder = f"{path.parent.name}{os.sep}{path.name}" if path.parent.name else str(path)
            bind_text(self.directory_link, "保存到 {folder}", folder=folder)
            self.directory_link.setToolTip(str(path))

    def import_target(self):
        target = dict(self.controller.context(), kind=self.destination.currentData(),
                      clip_id=self.clip.currentData() if self.clip.isEnabled() else "",
                      confirmed_media=self.confirm_media.isChecked() and self.confirm_media.isEnabled(),
                      replace_source=bool(self.policy.currentData()))
        page = self.controller.page()
        target["position_ms"] = int(getattr(getattr(page, "timeline", None), "playhead_ms", 0))
        return target

    def enqueue(self):
        if not self.catalog:
            return
        try:
            mode = self.mode.currentData()
            chosen = self.checked_tracks() if mode in ("both", "subtitles") else []
            if mode == "both" and self.catalog["tracks"] and not chosen:
                raise ValueError(tr("请选择要下载的字幕，或切换为仅视频。"))
            primary = self.primary.currentData() if chosen else ""
            secondary = self.translation.currentData() if chosen else ""
            if primary and secondary == primary:
                raise ValueError(tr("原文与译文必须选择不同轨道。"))
            target = self.import_target()
            if mode == "subtitles" and self.auto_import.isChecked() and target["kind"] == "new":
                raise ValueError(tr("仅字幕模式请选当前工程的对应素材，或关闭自动导入。"))
            options = dict(mode=mode, video_format=self.video_format.currentData() or "",
                audio_format=self.audio_format.currentData() or "", track_ids=chosen,
                primary_track_id=primary or "", translation_track_id=secondary or "",
                destination=target["kind"], clip_id=target["clip_id"], confirmed_media=target["confirmed_media"],
                replace_source=target["replace_source"], auto_import=self.auto_import.isChecked())
            task = self.controller.enqueue(self.catalog, self.directory.text(), options,
                                           thumbnail=self.thumbnail, **self._network())
            self.preferences.update(directory=self.directory.text(),
                languages=[t["language"] for t in self.catalog["tracks"] if t["track_id"] in chosen]
                          or self.preferences.get("languages", []))
            save_link_preferences(self.preferences)
            self.message.setText(tr("已加入队列；不会自动调用付费 AI。") + " " + task["video_id"])
            self.update_tasks(self.controller.queue.snapshots(), {})
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc))

    # ------------------------------------------------------------------ queue
    def _build_queue(self):
        page = QWidget()
        page.setObjectName("linkRoot")
        column = QVBoxLayout(page)
        column.setContentsMargins(24, 14, 24, 12)
        column.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(named_label(tr("下载队列"), "linkTitle"))
        head.addSpacing(10)
        self.filter_buttons = {}
        for key, label in FILTERS:
            widget = button(tr(label), "linkChip")
            widget.setCheckable(True)
            widget.setProperty("flexibleWidth", True)
            widget.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.filter_buttons[key] = widget
            head.addWidget(widget)
        head.addStretch(1)
        clear = button(tr("清除已完成"), "linkLink")
        clear.clicked.connect(self._clear_finished)
        head.addWidget(clear)
        column.addLayout(head)
        scroll = QScrollArea()
        scroll.setObjectName("linkScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("linkRoot")
        stack = QVBoxLayout(holder)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(10)
        cards = QWidget()
        self.card_column = QVBoxLayout(cards)
        self.card_column.setContentsMargins(0, 0, 0, 0)
        self.card_column.setSpacing(10)
        stack.addWidget(cards)
        self.queue_empty = named_label(tr("还没有下载任务。回到首页粘贴链接，或在字幕工作台按 Ctrl+V。"), "linkHint", wrap=True)
        self.queue_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stack.addWidget(self.queue_empty)
        stack.addStretch(1)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)
        self._set_filter("all")
        return page

    def _set_filter(self, key):
        self._filter = key
        for name, widget in self.filter_buttons.items():
            widget.setChecked(name == key)
        self._apply_filter()

    def _apply_filter(self):
        shown = 0
        for task in self._tasks:
            card = self._cards.get(task["task_id"])
            if card is None:
                continue
            visible = self._filter == "all" or task_filter(task) == self._filter
            card.setVisible(visible)
            shown += visible
        self.queue_empty.setVisible(shown == 0)
        counts = {key: sum(1 for t in self._tasks if key == "all" or task_filter(t) == key) for key, _ in FILTERS}
        for key, label in FILTERS:
            self.filter_buttons[key].setText(f"{tr(label)} {counts[key]}")

    def _clear_finished(self):
        self.controller.queue.clear_finished()
        self.update_tasks(self.controller.queue.snapshots(), self._details)

    def update_tasks(self, tasks, details):
        self._tasks = list(reversed(tasks))
        self._details = dict(details or {})
        alive = {task["task_id"] for task in self._tasks}
        for key in [k for k in self._cards if k not in alive]:
            card = self._cards.pop(key)
            self.card_column.removeWidget(card)
            card.hide()
            card.deleteLater()
        for position, task in enumerate(self._tasks):
            key = task["task_id"]
            card = self._cards.get(key)
            if card is None:
                card = TaskCard(key)
                card.action.connect(self.controller.task_action)
                self._cards[key] = card
                self.card_column.insertWidget(position, card)
            elif self.card_column.indexOf(card) != position:
                self.card_column.removeWidget(card)
                self.card_column.insertWidget(position, card)
            card.update_task(task, self._details.get(key, {}), self.controller.thumbnail_for(task))
        self._apply_filter()
        self._refresh_queue_badge()
        self._refresh_status()

    def _refresh_queue_badge(self):
        if not hasattr(self, "nav_buttons"):
            return
        active = sum(1 for t in self._tasks if t.get("state") in ACTIVE)
        widget = self.nav_buttons["queue"]
        if widget.isChecked():
            widget.setText(tr("队列") + (f" · {active}" if active else ""))
        widget.setToolTip(tr("队列") + (f" · {tr('{count} 个进行中', count=active)}" if active else ""))

    def _refresh_status(self):
        if not hasattr(self, "status_active"):
            return
        running = [t for t in self._tasks if t.get("state") in ACTIVE]
        speed = 0.0
        for task in running:
            progress = (self._details.get(task["task_id"], {}) or {}).get("progress") or {}
            if isinstance(progress.get("speed"), (int, float)) and task.get("state") == "running":
                speed += progress["speed"]
        self.status_active.setText(tr("下载中 {count}", count=len(running)))
        self.status_speed.setText(f"{speed/1024/1024:.1f} MB/s" if speed else "0 B/s")
        state, text = self.controller.tools_status()
        from .link_download_widgets import set_tone
        set_tone(self.status_tools_dot, state)
        self.status_tools.setText(text)

    # --------------------------------------------------------- tools/settings
    def _build_tools(self):
        page = QWidget()
        page.setObjectName("linkRoot")
        column = QVBoxLayout(page)
        column.setContentsMargins(24, 14, 24, 16)
        column.setSpacing(12)
        column.addWidget(named_label(tr("下载工具"), "linkTitle"))
        card = QFrame()
        card.setObjectName("linkCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.tool_rows = {}
        for row, (key, name, note) in enumerate((("yt_dlp", "yt-dlp", "下载视频与字幕"), ("ejs", "EJS", "解析 YouTube 播放器脚本"),
                                                ("node", "Node", "程序自带"), ("ffmpeg", "FFmpeg", "无损合并，程序自带"))):
            grid.addWidget(named_label(name, "linkFieldLabel"), row, 0)
            value = user_text(named_label("", "linkMeta"))
            grid.addWidget(value, row, 1)
            grid.addWidget(named_label(tr(note), "linkHint"), row, 2)
            self.tool_rows[key] = value
        grid.setColumnStretch(1, 1)
        column.addWidget(card)
        actions = QHBoxLayout()
        self.tools_button = button(tr("检查 / 修复下载工具"), "linkPrimary", "fa5s.tools", "on_accent")
        self.tools_button.clicked.connect(self.controller.install_tools)
        actions.addWidget(self.tools_button)
        actions.addStretch(1)
        column.addLayout(actions)
        column.addWidget(named_label(tr("下载工具版本随应用锁定；缺失时从官方地址下载，核对大小与 SHA-256 后才使用。"
                                        "不会修改系统里的 Python、Node 或 yt-dlp。"), "linkHint", wrap=True))
        column.addStretch(1)
        return page

    def _refresh_tools(self):
        versions = self.controller.tool_versions()
        for key, label in self.tool_rows.items():
            full = versions.get(key) or ""
            # FFmpeg reports "ffmpeg version X Copyright (c) …": the version is
            # enough here, the whole line stays in the tooltip (2026-10-26).
            short = full.removeprefix("ffmpeg version ").split(" Copyright")[0].strip() if key == "ffmpeg" else full
            label.setText(short or tr("未检查"))
            label.setToolTip(full)
        self._refresh_status()

    def _build_settings(self):
        page = QWidget()
        page.setObjectName("linkRoot")
        column = QVBoxLayout(page)
        column.setContentsMargins(24, 14, 24, 16)
        column.setSpacing(12)
        column.addWidget(named_label(tr("设置"), "linkTitle"))
        place = QFrame()
        place.setObjectName("linkCard")
        rows = QVBoxLayout(place)
        rows.setContentsMargins(18, 14, 18, 14)
        rows.setSpacing(10)
        rows.addWidget(named_label(tr("保存到"), "linkFieldLabel"))
        location = QHBoxLayout()
        self.directory = QLineEdit(self.preferences.get("directory") or str(default_directory()))
        self.directory.textChanged.connect(self._refresh_directory_link)
        choose = button(tr("选择…"), "linkGhost")
        choose.clicked.connect(self._choose_directory)
        opener = button(tr("打开下载位置"), "linkGhost")
        opener.clicked.connect(lambda: self._open_folder(""))
        location.addWidget(self.directory, 1)
        location.addWidget(choose)
        location.addWidget(opener)
        rows.addLayout(location)
        rows.addWidget(named_label(tr("每个任务单独一个文件夹（视频 ID＋任务 ID），里面有视频、原始字幕和下载清单。"), "linkHint", wrap=True))
        column.addWidget(place)
        network = QFrame()
        network.setObjectName("linkCard")
        network_rows = QVBoxLayout(network)
        network_rows.setContentsMargins(18, 14, 18, 14)
        network_rows.setSpacing(10)
        advanced = QCheckBox(tr("本次使用代理或 Cookie（可选）"))
        advanced.setObjectName("linkSectionCheck")
        advanced.setChecked(False)
        network_rows.addWidget(advanced)
        advanced_body = QWidget()
        network_rows.addWidget(advanced_body)
        form = QGridLayout(advanced_body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        advanced.toggled.connect(advanced_body.setVisible)
        advanced.toggled.connect(self.fit_height_later)
        advanced_body.hide()
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText(tr("留空沿用现有网络；例如 http://127.0.0.1:7890"))
        form.addWidget(named_label(tr("本次代理"), "linkHint"), 0, 0)
        form.addWidget(self.proxy, 0, 1, 1, 3)
        self.cookie = QLineEdit()
        self.cookie.setReadOnly(True)
        self.cookie.setPlaceholderText(tr("不使用 Cookie"))
        cookie_button = button(tr("选择 Cookie 文件…"), "linkGhost")
        cookie_button.clicked.connect(self._choose_cookie)
        clear_cookie = button(tr("清除"), "linkGhost")
        clear_cookie.clicked.connect(self.cookie.clear)
        form.addWidget(named_label(tr("登录验证"), "linkHint"), 1, 0)
        form.addWidget(self.cookie, 1, 1)
        form.addWidget(cookie_button, 1, 2)
        form.addWidget(clear_cookie, 1, 3)
        form.addWidget(named_label(tr("Cookie 仅在你主动选择时使用，不写入工程或清单。不会修改系统代理或 TUN。"), "linkHint", wrap=True), 2, 1, 1, 3)
        form.setColumnStretch(1, 1)
        self.advanced = advanced
        column.addWidget(network)
        column.addStretch(1)
        self._refresh_directory_link()
        return page

    def _choose_directory(self):
        value = QFileDialog.getExistingDirectory(self, tr("选择下载位置"), self.directory.text())
        if value:
            self.directory.setText(value)
            self.preferences["directory"] = value
            save_link_preferences(self.preferences)

    def _choose_cookie(self):
        value, _ = QFileDialog.getOpenFileName(self, tr("选择 Netscape Cookie 文件"), "", "Cookie (*.txt);;All files (*)")
        if value:
            self.cookie.setText(value)

    def _open_folder(self, task_id=""):
        if task_id:
            self.controller.task_action("folder", task_id)
            return
        path = Path(self.directory.text())
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.message.setText(str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------- lifecycle
    def refresh_theme_palette(self):
        refresh_secondary_surface_theme(self)
        apply_link_sheet(self.root)
        for card in self._cards.values():
            card._rendered = None
        self.update_tasks(self.controller.queue.snapshots(), self._details)
        self._theme_refresh_pending = False

    def showEvent(self, event):
        if getattr(self, "_theme_refresh_pending", False):
            self.refresh_theme_palette()
        super().showEvent(event)
        self.fit_height_later()

    def closeEvent(self, event):
        self.controller.cancel_analysis()
        self.parsing_finished()
        super().closeEvent(event)
