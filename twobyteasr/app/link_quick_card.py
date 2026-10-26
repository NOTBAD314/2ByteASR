"""Studio side of link downloads (user's design B, 2026-10-26).

* ``LinkQuickCard``: Ctrl+V with a video link on the clipboard opens it at
  the top right of the workbench; it parses at once, preselects the defaults
  and downloads on Enter.
* ``ProgressCapsule``: next to the toolbar's download button while work runs.
* ``TaskPopover``: the capsule's task list.
* ``ImportToast``: a short notice once a download landed in the project.

The card, popover and notice are frameless tool windows like the onboarding
bubble: the video is a native child window that would paint over ordinary
child widgets.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..design.elided_label import ElidedLabel
from ..design.soft_widgets import SegmentedControl, WrapLayout
from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme, refresh_secondary_surface_theme
from ..i18n import tr, bind_text
from ..i18n_widgets import user_text
from ..media import link_choices as choices
from ..media.link_catalog import SOURCES
from .link_download_controller import link_preferences, save_link_preferences
from .link_download_widgets import (ACTIVE, CoverView, TaskCard, active_theme, apply_link_sheet, button, capsule_qss,
                                    icon_button, icon_label, named_label, pill, ring_icon, set_tone)

SHADOW = 18
CARD_WIDTH = 452
POPOVER_WIDTH = 460
TOAST_WIDTH = 470
TOAST_MS = 9000


def _clock(ms: int) -> str:
    seconds = max(0, int(ms) // 1000)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest//60:02d}:{rest%60:02d}" if hours else f"{rest//60}:{rest%60:02d}"


class _Floating(QWidget):
    """A frameless tool window with a soft shadow that follows its Studio page."""

    def __init__(self, controller, page, name: str, width: int, *, focus=True, popup=False):
        host = page.window()
        flags = (Qt.WindowType.Popup if popup else Qt.WindowType.Tool) | Qt.WindowType.FramelessWindowHint \
            | Qt.WindowType.NoDropShadowWindowHint
        if not focus:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(host, flags)
        self.controller = controller
        self.page = page
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if not focus:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW - 8, SHADOW, SHADOW + 8)
        self.frame = QFrame()
        self.frame.setObjectName(name)
        from .ui_zoom import set_size
        set_size(self.frame, fixed_w=width)
        shadow = QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.frame.setGraphicsEffect(shadow)
        outer.addWidget(self.frame)
        apply_secondary_surface_theme(self)
        apply_link_sheet(self.frame)
        host.installEventFilter(self)

    def refresh_theme_palette(self):
        refresh_secondary_surface_theme(self)
        apply_link_sheet(self.frame)
        for label in self.findChildren(QLabel):
            spec = label.property("_linkIcon")
            if spec:
                from ..design.themed_icons import themed_icon
                label.setPixmap(themed_icon(spec[0], spec[2]).pixmap(QSize(spec[1], spec[1])))
        self._theme_refresh_pending = False

    def showEvent(self, event):
        if getattr(self, "_theme_refresh_pending", False):
            self.refresh_theme_palette()
        super().showEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.page.window() and self.isVisible():
            kind = event.type()
            if kind in (QEvent.Type.Move, QEvent.Type.Resize):
                self.place()
            elif kind == QEvent.Type.Hide or (kind == QEvent.Type.WindowStateChange and watched.isMinimized()):
                self.hide()
        return False

    def fit(self):
        """Size the window from the card's height for its fixed width.

        ``adjustSize`` reads the one-line size hint, which squeezed a wrapped
        title and a second row of subtitle chips."""
        width = self.frame.minimumWidth()
        self.frame.layout().invalidate()   # a row shown / hidden since the last fit
        self.frame.layout().activate()
        height = self.frame.heightForWidth(width) if self.frame.hasHeightForWidth() else -1
        height = max(height, self.frame.sizeHint().height() if height <= 0 else 0,
                     self.frame.minimumSizeHint().height())
        margins = self.layout().contentsMargins()
        self.layout().invalidate()   # the window's own minimum still held the old height
        self.layout().activate()
        self.resize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def refit_later(self):
        """Fit again once Qt has laid out a shown / hidden row or a zoom step."""
        QTimer.singleShot(0, self, self._refit)

    def _refit(self):
        if self.isVisible():
            self.fit()
            self.place()

    def apply_ui_zoom(self, factor):
        self.refit_later()

    def _right_edge(self) -> int:
        # The page's last pixel, not the one past it: in a maximized window
        # that one lies on the next monitor and comes back in its scale
        # (2026-10-26: the card opened at x=3301 beside a 2194 px window).
        return self.page.mapToGlobal(QPoint(max(0, self.page.width() - 1), 0)).x() + 1

    def _move_on_screen(self, x: int, y: int):
        """Move, keeping the visible card (not its shadow margin) on the page's screen."""
        screen = (self.page.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(screen.left() - SHADOW, min(x, screen.right() + 1 + SHADOW - self.width()))
        y = max(screen.top() - SHADOW, min(y, screen.bottom() + 1 + SHADOW - self.height()))
        self.move(x, y)

    def place(self):
        raise NotImplementedError


class LinkQuickCard(_Floating):
    def __init__(self, controller, page):
        super().__init__(controller, page, "linkQuickCard", CARD_WIDTH)
        self.state = "idle"
        self.url = ""
        self.catalog = None
        self.thumbnail = b""
        self._chips = {}
        self.setWindowTitle(tr("链接下载"))
        column = QVBoxLayout(self.frame)
        column.setContentsMargins(18, 16, 18, 18)
        column.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(10)
        mark = icon_label("fa5s.link", 16, "accent", "linkCardIcon")
        from .ui_zoom import set_size
        set_size(mark, fixed_w=32, fixed_h=32)
        head.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(1)
        words.addWidget(named_label(tr("已从剪贴板读取链接"), "linkTaskTitle"))
        self.url_label = user_text(ElidedLabel("", mode=Qt.TextElideMode.ElideMiddle, minimum=120))
        self.url_label.setObjectName("linkHint")
        words.addWidget(self.url_label)
        head.addLayout(words, 1)
        close = icon_button("fa5s.times", tr("关闭"))
        close.clicked.connect(self.close)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(head)
        self.status = named_label("", "linkMeta", wrap=True)
        column.addWidget(self.status)
        self.busy = QProgressBar()
        self.busy.setObjectName("linkProgress")
        self.busy.setTextVisible(False)
        self.busy.setRange(0, 0)
        column.addWidget(self.busy)
        self.retry_row = QHBoxLayout()
        self.retry_button = button(tr("重试"), "linkGhost")
        self.retry_button.clicked.connect(lambda: self.controller.quick_paste(self.page, self.url))
        self.window_button = button(tr("打开完整窗口"), "linkLink")
        self.window_button.clicked.connect(self._more)
        self.retry_row.addWidget(self.retry_button)
        self.retry_row.addWidget(self.window_button)
        self.retry_row.addStretch(1)
        column.addLayout(self.retry_row)
        self.media_box = QWidget()
        media = QHBoxLayout(self.media_box)
        media.setContentsMargins(0, 0, 0, 0)
        media.setSpacing(14)
        self.cover = CoverView(150, 84, 10)
        media.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(6)
        self.title = user_text(named_label("", "linkTaskTitle", wrap=True))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        info.addWidget(self.title)
        self.meta = user_text(named_label("", "linkHint", wrap=True))
        info.addWidget(self.meta)
        self.summary = pill()
        info.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)
        media.addLayout(info, 1)
        # Shown with the quick preview while parsing, and with the result.
        column.insertWidget(1, self.media_box)
        self._previewed = False
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        self.mode = StudioComboBox()
        for value, label in choices.MODES:
            self.mode.addItem(tr(label), value)
            self.mode.setItemData(self.mode.count()-1, tr(choices.MODE_NOTES[value]), Qt.ItemDataRole.ToolTipRole)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.mode_segment = SegmentedControl(self.mode, emit_activated=False)
        self.mode_segment.setObjectName("linkSegmented")
        self.mode_segment.setAccessibleName(tr("下载内容"))
        body.addWidget(self.mode_segment)
        self.subtitle_box = QWidget()
        subtitle = QVBoxLayout(self.subtitle_box)
        subtitle.setContentsMargins(0, 0, 0, 0)
        subtitle.setSpacing(8)
        subtitle.addWidget(named_label(tr("字幕"), "linkFieldLabel"))
        self.chip_host = QWidget()
        self.chip_layout = WrapLayout(self.chip_host, spacing=6, fill=False)
        subtitle.addWidget(self.chip_host)
        body.addWidget(self.subtitle_box)
        box = QFrame()
        box.setObjectName("linkSummaryBox")
        rows = QVBoxLayout(box)
        rows.setContentsMargins(12, 8, 12, 8)
        rows.setSpacing(6)
        quality = QHBoxLayout()
        quality.setSpacing(10)
        self.quality_label = named_label(tr("画质"), "linkHint")
        quality.addWidget(self.quality_label)
        self.video_format = StudioComboBox()
        self.video_format.currentIndexChanged.connect(self._mode_changed)
        quality.addWidget(self.video_format, 1)
        rows.addLayout(quality)
        place = QHBoxLayout()
        place.setSpacing(10)
        place.addWidget(named_label(tr("保存到"), "linkHint"))
        self.directory_label = user_text(ElidedLabel("", mode=Qt.TextElideMode.ElideMiddle, minimum=100))
        self.directory_label.setObjectName("linkMeta")
        place.addWidget(self.directory_label, 1)
        change = button(tr("更改"), "linkLink")
        change.clicked.connect(lambda: self._more("settings"))
        place.addWidget(change)
        rows.addLayout(place)
        body.addWidget(box)
        self.auto_import = QCheckBox()
        self.auto_import.setChecked(True)
        self.auto_import.toggled.connect(lambda on: bind_text(self.download_button, "下载并导入" if on else "开始下载"))
        body.addWidget(self.auto_import)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        more = button(tr("更多选项…"), "linkGhost")
        more.clicked.connect(lambda: self._more())
        footer.addWidget(more)
        footer.addStretch(1)
        self.download_button = button(tr("下载并导入"), "linkPrimary", "fa5s.download", "on_accent")
        self.download_button.clicked.connect(self.download)
        footer.addWidget(self.download_button)
        body.addLayout(footer)
        column.addWidget(self.body)

    # ------------------------------------------------------------ lifecycle
    def start(self, url: str):
        self.url = url
        self.catalog = None
        self.thumbnail = b""
        self._previewed = False
        self.title.setText("")
        self.meta.setText("")
        self.cover.set_image(b"")
        self.cover.set_badge("")
        self.url_label.setText(url.replace("https://www.", "").replace("https://", ""))
        self._set_state("parsing", tr("正在解析视频…"))
        self.place()
        self.show()
        self.raise_()
        self.activateWindow()

    def _set_state(self, state: str, text: str = ""):
        self.state = state
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.busy.setVisible(state == "parsing")
        for widget in (self.retry_button, self.window_button):
            widget.setVisible(state == "error")
        self.media_box.setVisible(state == "ready" or (state == "parsing" and self._previewed))
        self.summary.setVisible(state == "ready")
        self.body.setVisible(state == "ready")
        self.fit()
        self.place()
        self.refit_later()

    def set_progress(self, text: str):
        if self.state == "parsing":
            self.status.setText(text)

    def set_preview(self, preview: dict):
        """Title, channel and cover from the quick preview, while yt-dlp reads
        the formats and subtitles (2026-10-26: the card used to stay empty
        for 4-5 seconds)."""
        if self.state != "parsing" or not (preview.get("title") or preview.get("thumbnail")):
            return
        self._previewed = True
        self.title.setText(preview.get("title") or "")
        self.meta.setText(preview.get("uploader") or "")
        self.thumbnail = bytes(preview.get("thumbnail") or b"")
        self.cover.set_image(self.thumbnail)
        self._set_state("parsing", tr("正在读取画质和字幕…"))

    def set_thumbnail(self, data: bytes):
        """The cover, when it arrives after the choices."""
        self.thumbnail = bytes(data or b"")
        self.cover.set_image(self.thumbnail)

    def show_error(self, text: str):
        self._set_state("error", text)

    def set_catalog(self, catalog, thumbnail=b""):
        self.catalog = catalog
        self.thumbnail = bytes(thumbnail or b"")
        preferences = link_preferences()
        languages = preferences.get("languages", [])
        self.title.setText(catalog["title"])
        meta = [catalog.get("uploader", ""), choices.duration_text(catalog.get("duration", 0))]
        quality = choices.quality_summary(catalog)
        if quality:
            meta.append(tr("最高 {quality}", quality=quality))
        self.meta.setText(" · ".join(part for part in meta if part))
        self.cover.set_image(self.thumbnail)
        self.cover.set_badge(choices.duration_text(catalog.get("duration", 0)))
        tracks = catalog["tracks"]
        if any(t["source"] == "manual" for t in tracks):
            self.summary.setText(tr("有人工字幕"))
            set_tone(self.summary, "ok")
        elif tracks:
            self.summary.setText(tr("只有自动字幕"))
            set_tone(self.summary, "accent")
        else:
            self.summary.setText(tr("暂无字幕，可下载后自己识别"))
            set_tone(self.summary, "off")
        self.video_format.blockSignals(True)
        self.video_format.clear()
        videos = choices.video_formats(catalog)
        for f in videos:
            self.video_format.addItem(choices.video_label(f, tr("大小未知")), f["format_id"])
        self.video_format.setCurrentIndex(choices.preferred_video_index(videos))
        self.video_format.blockSignals(False)
        default = choices.default_selection(catalog, languages)
        self._build_chips(languages, set(default["track_ids"]))
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData("both" if videos else "audio"))
        self.mode.blockSignals(False)
        self.mode_segment.sync()
        self.directory_label.setText(self.controller.directory())
        prompt = ""
        if tracks and not default["track_ids"]:
            # No language evidence and several uploaded tracks: the user picks one.
            prompt = tr("这个视频有几种语言的字幕，点选要导入的一条。")
        self._set_state("ready", prompt)
        self._mode_changed()
        self.download_button.setFocus()

    def _build_chips(self, languages, checked):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._chips = {}
        if not self.catalog["tracks"]:
            self.chip_layout.addWidget(named_label(tr("此视频暂无可用字幕"), "linkHint"))
            return
        for track in choices.chip_tracks(self.catalog, languages, limit=3):
            name = tr(choices.language_name(track["language"], track.get("label", "")))
            chip = user_text(button(f"{name} · {tr(choices.SOURCE_SHORT.get(track['source'], '来源待确认'))}", "linkChip"))
            chip.setCheckable(True)
            chip.setChecked(track["track_id"] in checked)
            chip.setProperty("flexibleWidth", True)
            chip.setToolTip(tr(SOURCES[track["source"]]) + " · " + track["label"])
            chip.toggled.connect(self._chip_toggled)
            self._chips[track["track_id"]] = chip
            self.chip_layout.addWidget(chip)
        if len(self.catalog["tracks"]) > len(self._chips):
            more = button(tr("全部 {count} 条…", count=len(self.catalog["tracks"])), "linkLink")
            more.setProperty("flexibleWidth", True)
            more.clicked.connect(lambda: self._more())
            self.chip_layout.addWidget(more)

    def _chip_toggled(self, on):
        if on and self.status.isVisible() and self.state == "ready":
            self.status.hide()
            self.refit_later()

    def _mode_changed(self, *_):
        if not self.catalog:
            return
        mode = self.mode.currentData()
        self.subtitle_box.setVisible(mode in ("both", "subtitles"))
        self.video_format.setEnabled(mode in ("both", "video"))
        self.quality_label.setEnabled(mode in ("both", "video"))
        page = self.page
        project = getattr(page, "project", None)
        if project is not None:
            where = tr("完成后导入当前工程，放在播放头 {time}", time=_clock(getattr(page.timeline, "playhead_ms", 0)))
        else:
            where = tr("完成后新建工程并导入")
        self.auto_import.setText(where)
        bind_text(self.download_button, "下载并导入" if self.auto_import.isChecked() else "开始下载")
        self.fit()
        self.place()

    def selection(self) -> dict:
        mode = self.mode.currentData()
        catalog = self.catalog
        tracks = [tid for tid, chip in self._chips.items() if chip.isChecked()] if mode in ("both", "subtitles") else []
        videos = {f["format_id"]: f for f in choices.video_formats(catalog)}
        audios = choices.audio_formats(catalog)
        video_format = (self.video_format.currentData() or "") if mode in ("both", "video") else ""
        if mode == "audio" or (video_format and not choices.has_audio(videos.get(video_format, {}))):
            audio_format = choices.preferred_audio(audios, videos.get(video_format)).get("format_id", "")
        else:
            audio_format = ""
        preferred = choices.default_selection(catalog, link_preferences().get("languages", []))["primary_track_id"]
        primary = preferred if preferred in tracks else (tracks[0] if tracks else "")
        return dict(mode=mode, video_format=video_format, audio_format=audio_format, track_ids=tracks,
                    primary_track_id=primary, translation_track_id="", auto_import=self.auto_import.isChecked())

    def download(self):
        if self.state != "ready" or not self.catalog:
            return
        selection = self.selection()
        project = getattr(self.page, "project", None)
        if selection["mode"] == "subtitles" and project is None:
            self.status.setText(tr("仅字幕需要先在工作台打开对应视频的工程；或改用「视频＋字幕」。"))
            self.status.show()
            return
        if selection["mode"] == "both" and self.catalog["tracks"] and not selection["track_ids"]:
            self.status.setText(tr("请选择要下载的字幕，或切换为仅视频。"))
            self.status.show()
            return
        options = dict(selection, destination="current" if project is not None else "new", clip_id="",
                       confirmed_media=False, replace_source=False)
        try:
            self.controller.enqueue(self.catalog, self.controller.directory(), options,
                                    thumbnail=self.thumbnail, **self.controller.network())
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            self.status.show()
            return
        preferences = link_preferences()
        chosen = [t["language"] for t in self.catalog["tracks"] if t["track_id"] in selection["track_ids"]]
        if chosen:
            preferences["languages"] = chosen
            save_link_preferences(preferences)
        self.hide()

    def _more(self, page_key=""):
        selection = self.selection() if self.catalog else {}
        self.hide()
        self.controller.more_options(self.url, self.catalog, self.thumbnail, selection)
        if page_key and self.controller.dialog is not None:
            self.controller.dialog.show_page(page_key)

    def update_tasks(self, tasks, details):
        pass  # the card closes once its task is queued; the capsule shows progress

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state == "ready":
            self.download()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.state == "parsing" and self.controller._analysis_owner == "card":
            self.controller.cancel_analysis()
        super().closeEvent(event)

    def place(self):
        anchor = getattr(self.page, "studio_link_download_button", None)
        top = anchor.mapToGlobal(QPoint(0, anchor.height())).y() + 6 if anchor is not None and anchor.isVisible() \
            else self.page.mapToGlobal(QPoint(0, 0)).y() + 64
        self.fit()
        self._move_on_screen(self._right_edge() - self.width() + SHADOW - 20, top - (SHADOW - 8))


class TaskPopover(_Floating):
    def __init__(self, controller, anchor):
        page = anchor
        while page is not None and page.objectName() != "subtitleStudio":
            page = page.parentWidget()
        super().__init__(controller, page or anchor.window(), "linkPopover", POPOVER_WIDTH, popup=True)
        self.anchor = anchor
        self._cards = {}
        column = QVBoxLayout(self.frame)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(14, 12, 10, 8)
        head.setSpacing(8)
        head.addWidget(named_label(tr("下载任务"), "linkTaskTitle"))
        self.count = named_label("", "linkHint")
        head.addWidget(self.count)
        head.addStretch(1)
        full = button(tr("打开完整窗口"), "linkLink")
        full.clicked.connect(lambda: (self.hide(), self.controller.show("queue")))
        head.addWidget(full)
        column.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(0)
        column.addLayout(self.list)
        self.empty = named_label(tr("没有进行中的下载。"), "linkHint")
        self.empty.setContentsMargins(14, 10, 14, 12)
        column.addWidget(self.empty)
        footer = QFrame()
        footer.setObjectName("linkPopoverFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(14, 9, 14, 9)
        row.addWidget(named_label(tr("在工作台再按 Ctrl+V 可以继续添加链接"), "linkHint"))
        column.addWidget(footer)

    def update_tasks(self, tasks, details):
        recent = list(reversed(tasks))[:5]
        alive = {t["task_id"] for t in recent}
        for key in [k for k in self._cards if k not in alive]:
            card = self._cards.pop(key)
            self.list.removeWidget(card)
            card.hide()
            card.deleteLater()
        for position, task in enumerate(recent):
            card = self._cards.get(task["task_id"])
            if card is None:
                card = TaskCard(task["task_id"], compact=True)
                card.action.connect(self.controller.task_action)
                self._cards[task["task_id"]] = card
                self.list.insertWidget(position, card)
            elif self.list.indexOf(card) != position:
                self.list.removeWidget(card)
                self.list.insertWidget(position, card)
            card.update_task(task, details.get(task["task_id"], {}), self.controller.thumbnail_for(task))
        running = sum(1 for t in tasks if t["state"] in ACTIVE)
        self.count.setText(tr("{count} 个进行中", count=running) if running else "")
        self.empty.setVisible(not recent)
        if self.isVisible():
            self.fit()

    def popup(self):
        self.fit()
        self.place()
        self.show()

    def place(self):
        point = self.anchor.mapToGlobal(QPoint(0, self.anchor.height() + 6))
        self._move_on_screen(point.x() - SHADOW, point.y() - (SHADOW - 8))


class ImportToast(_Floating):
    def __init__(self, controller, page):
        super().__init__(controller, page, "linkToast", TOAST_WIDTH, focus=False)
        self.task_id = ""
        row = QHBoxLayout(self.frame)
        row.setContentsMargins(14, 12, 12, 12)
        row.setSpacing(12)
        mark = icon_label("fa5s.check", 14, "accent", "linkOkIcon")
        from .ui_zoom import set_size
        set_size(mark, fixed_w=30, fixed_h=30)
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(8)
        self.headline = user_text(named_label("", "linkTaskTitle", wrap=True))
        self.detail = user_text(named_label("", "linkHint", wrap=True))
        column.addWidget(self.headline)
        column.addWidget(self.detail)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.locate_button = button(tr("定位到片段"), "linkGhost", "fa5s.crosshairs", "secondary")
        self.locate_button.clicked.connect(lambda: self.controller.task_action("locate", self.task_id))
        self.ai_button = button(tr("AI 精修…"), "linkGhost", "fa5s.magic", "secondary")
        self.ai_button.clicked.connect(lambda: (self.hide(), self.controller.task_action("ai", self.task_id)))
        actions.addWidget(self.locate_button)
        actions.addWidget(self.ai_button)
        actions.addStretch(1)
        column.addLayout(actions)
        row.addLayout(column, 1)
        close = icon_button("fa5s.times", tr("关闭提示"))
        close.clicked.connect(self.hide)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_task(self, task: dict):
        self.task_id = task["task_id"]
        result = task.get("import_result", {})
        self.headline.setText(tr("已导入「{title}」", title=task.get("title") or task["video_id"]))
        clip = None
        project = getattr(self.page, "project", None)
        if project is not None:
            clip = next((c for t in project.video_tracks for c in t.clips if c.id == result.get("clip_id")), None)
        count = result.get("cue_count", 0)
        where = _clock(clip.timeline_in_ms) if clip is not None else ""
        if count and where:
            text = tr("视频和 {count} 条字幕已放在 {time}", count=count, time=where)
        elif count:
            text = tr("已导入 {count} 条字幕", count=count)
        else:
            text = tr("媒体已放在 {time}", time=where) if where else tr("媒体已导入工程")
        if result.get("warnings"):
            text += " · " + " ".join(result["warnings"])
        self.detail.setText(text)
        self.locate_button.setVisible(clip is not None)
        self.ai_button.setVisible(bool(count))
        self.fit()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(TOAST_MS)

    def enterEvent(self, event):
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.timer.start(TOAST_MS // 2)
        super().leaveEvent(event)

    def place(self):
        timeline = getattr(self.page, "timeline", None)
        bottom = (timeline.mapToGlobal(QPoint(0, 0)).y() if timeline is not None and timeline.isVisible()
                  else self.page.mapToGlobal(QPoint(0, max(0, self.page.height() - 1))).y() + 1)
        self.fit()
        self._move_on_screen(self._right_edge() - self.width() + SHADOW - 20, bottom - self.height() + SHADOW - 4)


class ProgressCapsule(QPushButton):
    """Running link downloads next to the Studio toolbar's download button.

    A push button: the toolbar caps its tool buttons at an icon's width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("linkCapsule")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
        # A tight toolbar would squeeze it to the ring alone; the toolbar hides
        # its less important commands instead.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setProperty("flexibleWidth", True)   # its words change while it runs
        self._state = None
        self._fitted_width = 0
        self.setStyleSheet(capsule_qss())
        self.hide()

    def set_state(self, running: int, fraction, attention: bool):
        if getattr(self, "_theme_refresh_pending", False):
            self.refresh_theme_palette()
        key = (running, None if fraction is None else round(float(fraction), 2), attention)
        if key == self._state:
            return
        self._state = key
        t = active_theme()
        warn = attention and not running
        tone = "warn" if warn else ""
        if self.property("tone") != tone:
            self.setProperty("tone", tone)
            self.style().unpolish(self)
            self.style().polish(self)
        if running:
            text = f"{fraction:.0%}" if fraction is not None else tr("下载中")
            tip = tr("下载中 {count} 项，点开查看", count=running)
        else:
            text = tr("待处理")
            tip = tr("有下载需要处理，点开查看")
        self.setText(text)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        color = t.warning if warn else t.accent_text
        self.setIcon(ring_icon(fraction if running else 1.0, color, t.border_strong))
        hidden = self.isHidden()
        self.setVisible(bool(running or attention))
        width = self.sizeHint().width()
        if hidden != self.isHidden() or (not self.isHidden() and width != self._fitted_width):
            # The bar gives the room back or takes it from its least used commands.
            self._fitted_width = width
            page = self.parentWidget()
            while page is not None and page.objectName() != "subtitleStudio":
                page = page.parentWidget()
            sync = getattr(page, "_sync_navigation_chrome", None)
            if callable(sync):
                QTimer.singleShot(0, sync)

    def refresh_theme_palette(self):
        self.setStyleSheet(capsule_qss())
        self._state = None
        self._theme_refresh_pending = False
