"""Project Hub presentation and preferences behavior for Subtitle Studio."""

from __future__ import annotations

import json
import os
import re
import threading

_LIBRARY_INDEX_LOCK = threading.RLock()
from .i18n import tr, user_text, current_language, join_text
from .project_display_name import display_project_name

from time import perf_counter
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QFrame,
    QSizePolicy,
)

from .studio_helpers import _library_duration
from .studio_project import (
    _LIBRARY_INDEX_SUMMARY_KEYS,
    library_index_entry_stale,
    library_project_snapshot,
    load_library_index,
    load_project,
    project_library_root,
    repair_project_library_metadata,
    save_library_index,
    save_project,
    studio_settings_path,
)
from .studio_theme import (
    StudioComboBox,
    apply_secondary_surface_theme,
    create_studio_menu,
    studio_message_box,
)
from .theme_manager import apply_theme, available_themes, theme_key
from .themed_icons import install_themed_icon
from .ui_theme import theme_definition, theme_display_label

from .i18n import bind_text

# Card sizing for the recent-projects grid: the column count is derived from
# the live viewport instead of hard breakpoints, so a 16:9 window gains its
# 4th column as soon as real space exists for it.
_GRID_GAP = 24
_GRID_TARGET_CARD_WIDTH = 320
_GRID_MIN_CARD_WIDTH = 280
_GRID_MAX_CARD_WIDTH = 380


# Decoded library covers are cached by bytes, not count: a card view and a
# list view of ~120 projects need two sizes each, which thrashed a 128-entry
# cache on every view switch (2026-10-12).
_COVER_CACHE_BYTES = 64 * 1024 * 1024
_COVER_CACHE_ENTRIES = 600
_HERO_COVER_MAX_WIDTH = 1280
_INTERNAL_PROJECT_DIRS = {
    "autosave", "autosaves", "backup", "backups", "recovery",
    "recoveries", "checkpoint", "checkpoints", "temp", "tmp",
}


def _internal_project_snapshot(path: Path, library_root: Path) -> bool:
    """Autosave/backup/recovery copies inside the library are not projects."""
    try:
        parts = path.relative_to(library_root).parts if path.is_relative_to(library_root) else path.parts
    except ValueError:
        parts = path.parts
    lowered_parts = {part.lower() for part in parts}
    name = path.name.lower()
    return bool(
        lowered_parts & _INTERNAL_PROJECT_DIRS
        or any(marker in name for marker in (".previous", ".autosave", ".backup", ".recovery", ".checkpoint", ".tmp"))
        or re.fullmatch(r"[0-9a-f]{24,64}\.2byteproj", name)
    )


def _dedupe_library_records(merged: list[dict[str, object]]) -> list[dict[str, object]]:
    """Formal project entries win. A project id is canonical; legacy projects
    without a stable id fall back to their normalized source-media path."""
    deduplicated: list[dict[str, object]] = []
    logical_seen: set[str] = set()
    for record in merged:
        project_id = str(record.get("project_id", "")).strip().lower()
        media = str(record.get("source_media", "")).strip()
        media_key = str(Path(media).expanduser()).replace("/", "\\").lower() if media else ""
        key = f"project:{project_id}" if project_id else (f"media:{media_key}" if media_key else f"path:{str(record.get('path', '')).lower()}")
        if key in logical_seen:
            continue
        logical_seen.add(key)
        deduplicated.append(record)
    return deduplicated


def _library_display_signature(records: list[dict[str, object]]) -> tuple:
    """What the cards, rows and hero show of each record, in order.

    Bookkeeping fields (underscore keys: summary/repair flags, presence) and
    the informational ``status`` string are excluded, so the background scan
    of an unchanged library compares equal to the first paint from the index
    and does not rebuild every card a second time.
    """
    return tuple(
        tuple(sorted((str(key), repr(value)) for key, value in record.items()
                     if not str(key).startswith("_") and key != "status"))
        for record in records
    )


class _ProjectCard(QToolButton):
    """Composite card that keeps the legacy QToolButton click contract."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_text = ""
        self.setText("")

    def set_project_text(self, value: str) -> None:
        self._project_text = str(value)

    def text(self) -> str:
        return self._project_text


class StudioHubMixin:
    _LIBRARY_BUILD_BATCH = 8
    # Cards / rows built when the library opens; more are built as the user
    # scrolls towards the end (2026-10-12: building all ~120 cards kept the
    # page janky for seconds after it appeared).
    _LIBRARY_INITIAL_CARD_ROWS = 4
    _LIBRARY_INITIAL_LIST_ROWS = 24

    def _apply_hub_paper_texture(self, widget: QWidget) -> None:
        """Create one deterministic warm paper tile; never repaint it per frame."""
        tile = QPixmap(96, 96)
        tile.fill(QColor("#F7F2E8"))
        painter = QPainter(tile)
        for index in range(92):
            x = (index * 37 + 11) % 96
            y = (index * 53 + 7) % 96
            alpha = 3 + (index % 3) * 2
            painter.setPen(QColor(112, 91, 62, alpha))
            painter.drawPoint(x, y)
        painter.setPen(QColor(255, 255, 255, 6))
        for y in range(8, 96, 18):
            painter.drawLine(0, y, 95, y + 2)
        painter.end()
        palette = widget.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(tile))
        palette.setBrush(QPalette.ColorRole.Base, QBrush(tile))
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)

    @staticmethod
    def _library_grid_metrics(viewport_width: int) -> tuple[int, int, int]:
        gap = _GRID_GAP
        # Reserve a scrollbar gutter so a later vertical bar cannot push the
        # grid past the visible viewport (horizontal scrolling is disabled).
        available = max(_GRID_MIN_CARD_WIDTH, int(viewport_width) - 84 - 18)
        columns = max(1, (available + gap) // (_GRID_TARGET_CARD_WIDTH + gap))
        card_width = (available - gap * (columns - 1)) // columns
        card_width = max(_GRID_MIN_CARD_WIDTH, min(_GRID_MAX_CARD_WIDTH, card_width))
        return columns, card_width, gap

    def _library_layout_width(self) -> int:
        """Width the card grid is laid out for.

        The scroll area's own width, not its viewport's: the viewport narrows
        when the vertical bar appears after the first cards, which changed the
        card width by a few pixels and rebuilt every card a second time. The
        grid metrics already keep a scrollbar gutter.
        """
        scroll = getattr(self, "project_library_scroll", None)
        if scroll is None:
            return self.width()
        # Entering Studio shows the page / hub; their layouts may not have
        # caught up with the window yet. Settle only the chain from the window
        # down to the scroll area (never the hidden editor tree) first.
        chain, widget = [], scroll
        while widget is not None:
            chain.append(widget)
            if widget.isWindow():
                break
            widget = widget.parentWidget()
        for widget in reversed(chain):
            layout = widget.layout()
            if layout is not None:
                layout.activate()
        return max(0, scroll.width() - 2 * scroll.frameWidth())

    def _library_visible_content_width(self) -> int:
        scroll = getattr(self, "project_library_scroll", None)
        if scroll is None:
            return max(360, self.width() - 84)
        return max(360, scroll.viewport().width() - 84)

    def _sync_resume_hero_geometry(self) -> None:
        """Size the hero preview to the cover aspect so it neither crops nor letterboxes."""
        if not hasattr(self, "resume_hero") or not hasattr(self, "resume_preview"):
            return
        visible = self._library_visible_content_width()
        if hasattr(self, "project_library_header"):
            self.project_library_header.setMaximumWidth(visible)
        self.resume_hero.setMaximumWidth(visible)
        info_min = 280
        chrome = 22 + 16 + 18
        aspect = float(getattr(self, "_resume_cover_aspect", 16 / 9) or (16 / 9))
        aspect = max(1.2, min(2.0, aspect))
        has_cover = bool(getattr(self, "_resume_has_cover", False))
        self.resume_preview.setVisible(has_cover)
        if not has_cover:
            # Empty artwork carries no information. Let project titles and
            # the recent grid occupy the first screen instead of a giant CC.
            self.resume_hero.setFixedHeight(224)
            return
        preview_h = min(280, max(192, round(visible * 0.20)))
        preview_w = round(preview_h * aspect)
        if preview_w + info_min + chrome > visible:
            preview_w = max(200, visible - info_min - chrome)
            preview_h = max(1, round(preview_w / aspect))
        self.resume_preview.setFixedSize(preview_w, preview_h)
        self.resume_hero.setFixedHeight(preview_h + 32)

    def _refresh_studio_empty_state(self, *, rescan: bool = True) -> None:
        if getattr(self, '_hub_layout_refreshing', False):
            return
        self._hub_layout_refreshing = True
        try:
            # 2026-09-19：会话首次进入工程库时用持久化索引播种 records
            # （零解析、零媒体探测，首屏即全量列表）。仅一次：之后的
            # records=None 表示"显式丢弃扫描结果"（删除流程/测试语义），
            # 回退 recent 直读。
            if (
                getattr(self, "_hub_library_records", None) is None
                and not getattr(self, "_hub_records_seeded", False)
            ):
                self._hub_records_seeded = True
                self._hub_library_records = self._library_records_from_index()
            self._rebuild_project_library()
            if rescan:
                self._request_library_scan()
        finally:
            self._hub_layout_refreshing = False

    def _request_library_scan(self) -> None:
        """Read project/recovery metadata off the GUI thread; keep cards usable."""
        if self.project is not None:
            return
        if getattr(self, "_hub_scan_pending", False):
            self._hub_scan_again = True
            return
        now = perf_counter()
        if now - getattr(self, "_hub_scan_started", -10.0) < 1.0:
            timer = getattr(self, "_hub_scan_timer", None)
            if timer is None:
                timer = self._hub_scan_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._request_library_scan)
            if not timer.isActive():
                timer.start(max(1, round((1.0 - now + self._hub_scan_started) * 1000)))
            return
        if not getattr(self, "_hub_scan_connected", False):
            self.library_records_ready_signal.connect(self._library_scan_ready)
            self._hub_scan_connected = True
        self._hub_scan_pending = True
        self._hub_scan_started = now
        # 2026-09-19：扫描代次。删除等改写库结构的操作会 bump 代次；晚到的
        # 过期扫描结果（捕获于删除前）被丢弃并重扫，防止旧列表覆盖新状态。
        scan_generation = int(getattr(self, "_hub_scan_generation", 0))

        def scan():
            try:
                records = self._project_library_records()
            except (OSError, ValueError, TypeError) as exc:
                records = {'error': f'工程库读取失败：{exc}。原工程未被修改。'}
            # Project / media presence is checked here, never while building
            # cards: media often lives on external drives that may be asleep.
            self._library_presence_next = self._check_library_presence(records)
            try:
                self.library_records_ready_signal.emit(records, scan_generation)
            except RuntimeError:
                pass  # The window may have been closed while files were read.

        threading.Thread(target=scan, name="studio-library-scan", daemon=True).start()

    @staticmethod
    def _check_library_presence(records) -> dict[str, tuple[bool, bool | None]]:
        """(project file present, source media present or None) per record path."""
        presence: dict[str, tuple[bool, bool | None]] = {}
        if not isinstance(records, list):
            return presence
        for record in records:
            if not isinstance(record, dict):
                continue
            path = str(record.get("path", "") or "")
            if not path:
                continue
            media = str(record.get("source_media") or "").strip()
            try:
                project_present = Path(path).is_file()
            except OSError:
                project_present = False
            try:
                media_present = Path(media).is_file() if media else None
            except OSError:
                media_present = False
            presence[path] = (project_present, media_present)
        return presence

    def _hub_on_screen(self) -> bool:
        empty = getattr(self, "studio_empty", None)
        if empty is None:
            return True  # headless hosts (tests) have no hub widgets
        try:
            return bool(empty.isVisible())
        except RuntimeError:
            return False

    def _library_scan_ready(self, records, scan_generation: int = -1) -> None:
        self._hub_scan_pending = False
        presence = getattr(self, "_library_presence_next", None)
        self._library_presence_next = None
        if scan_generation != int(getattr(self, "_hub_scan_generation", 0)):
            # Stale snapshot captured before a structural change: rescan.
            self._request_library_scan()
            return
        if getattr(self, "_hub_scan_again", False):
            self._hub_scan_again = False
            self._request_library_scan()
        if records is None:
            return
        if isinstance(records, dict) and 'error' in records:
            self.hub_loading_label.setText(records['error'])
            self.hub_loading_label.setWordWrap(True)
            self.hub_loading_label.show()
            self.project_library_empty.hide()
            return
        if presence:
            known = getattr(self, "_library_presence", None)
            if known is None:
                known = self._library_presence = {}
            known.update(presence)
        warnings = getattr(self, '_library_read_warnings', [])
        self.hub_loading_label.setText('\n'.join(warnings))
        self.hub_loading_label.setWordWrap(True)
        self.hub_loading_label.setVisible(bool(warnings))
        self._hub_library_records = records
        if self.project is not None:
            return
        if not self._hub_on_screen():
            # The user left the library while files were read: keep the
            # result and render it when the library is shown again.
            self._hub_rebuild_pending = True
            return
        self._rebuild_project_library()
        self._apply_library_presence()

    def _rebuild_project_library(self) -> None:
        if not hasattr(self, "studio_empty"):
            return
        self.studio_empty.setVisible(self.project is None)
        if self.project is not None:
            return
        records = getattr(self, "_hub_library_records", None)
        records = list(self.recent_project_records() if records is None else records)
        query = self.project_search.text().strip().casefold() if hasattr(self, "project_search") else ""
        if query:
            records = [record for record in records if query in str(display_project_name(record)).casefold()
                       or query in Path(str(record.get("source_media", ""))).name.casefold()]
        sort_mode = str(self.project_sort.currentData() or "recent") if hasattr(self, "project_sort") else "recent"
        if sort_mode == "name":
            records.sort(key=lambda record: str(display_project_name(record)).casefold())
        elif sort_mode == "created":
            records.sort(key=lambda record: str(record.get("created_at", "")), reverse=True)
        else:
            records.sort(key=lambda record: (str(record.get("last_opened", "")), str(record.get("updated_at", ""))), reverse=True)
        columns, card_width, gap = self._library_grid_metrics(self._library_layout_width())
        selection_mode = bool(getattr(self, "_library_selection_mode", False))
        signature = (_library_display_signature(records), query, sort_mode, columns, card_width, theme_key(),
                     selection_mode, current_language())
        self._hub_rebuild_pending = False
        current = getattr(self, "_hub_render_signature", None)
        if signature == current:
            # Same cards: keep them (and their scroll); newer bookkeeping
            # fields of the same projects are adopted without a rebuild.
            self._hub_display_records = records
            self._sync_resume_hero_geometry()
            return
        if (current is not None and getattr(self, "_hub_card_widgets", None)
                and signature[:3] + signature[5:] == current[:3] + current[5:]
                and not getattr(self, "_hub_relayout_due", False)):
            # Only the grid width differs: a transient geometry while the
            # hub is being shown again. Re-check once the layout settled;
            # rebuild only if the width really changed (2026-10-12).
            timer = getattr(self, "_hub_relayout_timer", None)
            if timer is None:
                timer = self._hub_relayout_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(120)

                def relayout():
                    self._hub_relayout_due = True
                    try:
                        if self.project is None and self._hub_on_screen():
                            self._rebuild_project_library()
                    finally:
                        self._hub_relayout_due = False
                timer.timeout.connect(relayout)
            timer.start()
            self._sync_resume_hero_geometry()
            return
        self._hub_render_signature = signature
        self._hub_display_records = records
        self._update_resume_project(records[0] if records and not query else None)
        saved_scroll = None
        if hasattr(self, "project_library_scroll"):
            saved_scroll = self.project_library_scroll.verticalScrollBar().value()
        while self.all_projects_layout.count():
            item = self.all_projects_layout.takeAt(0)
            if item and item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        while self.project_list_layout.count():
            item = self.project_list_layout.takeAt(0)
            if item and item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._hub_card_widgets = []
        self._hub_row_widgets = []
        self._hub_status_widgets = {}
        self._hub_built_views = set()
        self._library_cover_labels = {}
        self._library_build_generation = getattr(self, "_library_build_generation", 0) + 1
        for column in range(8):
            # Each grid cell contains an entire flex row, not one card. Giving
            # unused grid columns a card width doubled the minimum width.
            self.all_projects_layout.setColumnMinimumWidth(column, 0)
            self.all_projects_layout.setColumnStretch(column, 0)
        self.all_projects_heading.setVisible(True)
        self.all_projects_stack.setVisible(bool(records))
        self.project_library_empty.setVisible(not records)
        self.resume_hero.setVisible(bool(records) and not query)
        self._sync_resume_hero_geometry()
        # Only the visible view (cards or list) is built; the other one is
        # built when the user switches to it (2026-10-12).
        mode = "list" if getattr(self, "_project_library_view_mode", "card") == "list" else "card"
        self._hub_grid_metrics = (columns, card_width, gap)
        self._build_library_view(mode, saved_scroll=saved_scroll)
        self._start_library_cover_worker()
        self._set_project_library_view(mode, refresh=False)
        self._hub_viewport_width = self.project_library_scroll.viewport().width()
        self._library_update_manage_bar()

    def _build_library_view(self, view: str, *, saved_scroll=None) -> None:
        """Create one view's widgets for the displayed records in batches.

        2026-09-18 III 工程库懒加载：每批 8 个（QTimer(0) 链），首屏立即可操作，
        后续滚动中补齐；重建/筛选/切管理态通过 generation 失效旧批次。封面解码在
        后台线程出 QImage。
        """
        records = list(getattr(self, "_hub_display_records", ()) or ())
        generation = getattr(self, "_library_build_generation", 0)
        built = getattr(self, "_hub_built_views", None)
        if built is None:
            built = self._hub_built_views = set()
        built.add(view)
        columns, card_width, gap = getattr(self, "_hub_grid_metrics", None) or self._library_grid_metrics(
            self.project_library_scroll.viewport().width())
        preferences = getattr(self, "_studio_preferences", None)
        auto_cover = (preferences() if callable(preferences) else {}).get("auto_cover", True) is not False
        pending_records = list(records)
        pending_cards: list[QToolButton] = []
        timers = getattr(self, "_library_build_timers", None)
        if timers is None:
            timers = self._library_build_timers = {}
        batch_timer = timers.get(view)
        if batch_timer is None:
            batch_timer = timers[view] = QTimer(self)
            batch_timer.setSingleShot(True)
            if view == "card":
                self._library_build_timer = batch_timer
        slots = getattr(self, "_library_build_slots", None)
        if slots is None:
            slots = self._library_build_slots = {}
        previous = slots.pop(view, None)
        if previous is not None:
            try:
                batch_timer.timeout.disconnect(previous)
            except (RuntimeError, TypeError):
                pass
        restored = [saved_scroll is None]
        target = [max(16, columns * self._LIBRARY_INITIAL_CARD_ROWS) if view == "card"
                  else self._LIBRARY_INITIAL_LIST_ROWS]
        waiting = getattr(self, "_library_build_more", None)
        if waiting is None:
            waiting = self._library_build_more = {}
        waiting.pop(view, None)
        if not getattr(self, "_library_scroll_hooked", False) and hasattr(self, "project_library_scroll"):
            bar = self.project_library_scroll.verticalScrollBar()
            bar.valueChanged.connect(self._library_scrolled)
            bar.rangeChanged.connect(lambda _low, _high: self._library_scrolled())
            self._library_scroll_hooked = True

        def restore_scroll_once():
            if restored[0]:
                return
            bar = self.project_library_scroll.verticalScrollBar()
            if saved_scroll > bar.maximum() and pending_records:
                return  # build on until the previous position exists again
            restored[0] = True
            if saved_scroll <= bar.maximum():
                bar.setValue(saved_scroll)

        def built_count() -> int:
            return len(self._hub_card_widgets) if view == "card" else len(self._hub_row_widgets)

        def continue_or_wait() -> None:
            if built_count() < target[0] or not restored[0] or pending_cards:
                batch_timer.start(0)
            else:
                waiting[view] = (generation, target, batch_timer)

        def build_batch() -> None:
            if generation != getattr(self, "_library_build_generation", 0):
                return  # 新一次重建/筛选已接管，本批作废
            batch = pending_records[:self._LIBRARY_BUILD_BATCH]
            del pending_records[:self._LIBRARY_BUILD_BATCH]
            for record in batch:
                if view == "card":
                    card = self._build_project_card(record, card_width)
                    self._hub_card_widgets.append(card)
                    pending_cards.append(card)
                else:
                    self._add_project_list_row(record)
                self._queue_library_maintenance(record, auto_cover)
            if view != "card":
                self.project_list_layout.activate()
                restore_scroll_once()
                if pending_records:
                    continue_or_wait()
                return
            # 按整行落位卡片网格
            while len(pending_cards) >= columns:
                row_cards = pending_cards[:columns]
                del pending_cards[:columns]
                row_host = QWidget(self.all_projects_host)
                row_host.setMinimumWidth(min(
                    columns * card_width + gap * max(0, columns - 1),
                    self._library_visible_content_width(),
                ))
                row_host.setMinimumHeight(row_cards[0].height())
                row_layout = QHBoxLayout(row_host)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(gap)
                for card in row_cards:
                    row_layout.addWidget(card)
                row_layout.addStretch(1)
                self.all_projects_layout.addWidget(
                    row_host, self.all_projects_layout.count(), 0)
            restore_scroll_once()
            if pending_records:
                continue_or_wait()
                return
            # 尾行
            if pending_cards:
                row_host = QWidget(self.all_projects_host)
                row_host.setMinimumWidth(min(
                    len(pending_cards) * card_width + gap * max(0, len(pending_cards) - 1),
                    self._library_visible_content_width(),
                ))
                row_host.setMinimumHeight(pending_cards[0].height())
                row_layout = QHBoxLayout(row_host)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(gap)
                for card in pending_cards:
                    row_layout.addWidget(card)
                row_layout.addStretch(1)
                self.all_projects_layout.addWidget(
                    row_host, self.all_projects_layout.count(), 0)
                pending_cards.clear()
            self.all_projects_layout.activate()
            restore_scroll_once()

        batch_timer.timeout.connect(build_batch)
        slots[view] = build_batch
        build_batch()

    def _library_scrolled(self, _value=None) -> None:
        """Near the end of the built cards: build the next rows."""
        waiting = getattr(self, "_library_build_more", None) or {}
        view = "list" if getattr(self, "_project_library_view_mode", "card") == "list" else "card"
        entry = waiting.get(view)
        if entry is None:
            return
        generation, target, timer = entry
        if generation != getattr(self, "_library_build_generation", 0):
            waiting.pop(view, None)
            return
        scroll = self.project_library_scroll
        bar = scroll.verticalScrollBar()
        if bar.maximum() - bar.value() > scroll.viewport().height():
            return
        waiting.pop(view, None)
        columns = (getattr(self, "_hub_grid_metrics", None) or (1,))[0]
        target[0] += max(16, columns * self._LIBRARY_INITIAL_CARD_ROWS) if view == "card" \
            else self._LIBRARY_INITIAL_LIST_ROWS
        timer.start(0)

    def _queue_library_maintenance(self, record: dict[str, object], auto_cover: bool) -> None:
        """Metadata repair / cover backfill, decided without touching media drives."""
        if bool(record.get("_needs_metadata_repair")):
            self._queue_project_metadata_repair(record)
            return
        if not auto_cover:
            return
        presence = (getattr(self, "_library_presence", None) or {}).get(str(record.get("path", "")))
        if not presence or not presence[0] or not presence[1]:
            return  # unknown until the background scan reports, or offline
        cover = self._library_cover_path(record)
        if not cover.is_file():
            self._queue_project_cover_backfill(record)

    def _project_presence(self, record: dict[str, object]):
        path = str(record.get("path", "") or "")
        known = (getattr(self, "_library_presence", None) or {}).get(path)
        if known is not None:
            return known
        if str(record.get("status") or "") == "工程文件已移动":
            # recent_project_records() already found the project file gone.
            return False, None
        return None

    def _project_status(self, record: dict[str, object]) -> tuple[str, str]:
        presence = self._project_presence(record)
        if presence is None:
            # Not checked yet: the background scan reports moments later.
            return tr("正在检查…"), "checking"
        project_present, media_present = presence
        if not project_present:
            return tr("工程文件已移动"), "missing"
        if media_present is False:
            return tr("素材离线"), "offline"
        return tr("可继续"), "ready"

    def _apply_library_presence(self) -> None:
        """Update status pills in place after a scan (no card rebuild)."""
        records = {str(record.get("path", "")): record
                   for record in (getattr(self, "_hub_display_records", ()) or ())}
        from shiboken6 import isValid
        for path, widgets in list((getattr(self, "_hub_status_widgets", None) or {}).items()):
            record = records.get(path)
            if record is None:
                continue
            status_text, status_key = self._project_status(record)
            for kind, widget, extra in widgets:
                if not isValid(widget):
                    continue
                if widget.property("status") == status_key:
                    continue
                widget.setProperty("status", status_key)
                if kind == "row":
                    widget.setText("●  " + status_text)
                    widget.setAccessibleName(status_text)
                    if extra is not None and isValid(extra):
                        extra.setText(tr("继续编辑") if status_key == "ready" else tr("查看工程"))
                else:
                    widget.setText(status_text)
                    if extra is not None and isValid(extra):
                        name = display_project_name(record)
                        count = int(record.get("cue_count", 0) or 0)
                        duration = max(0, int(record.get("duration_ms", 0) or 0))
                        extra.set_project_text(tr("{name}\n{count} 条字幕 · {duration}\n{status}", name=name,
                                                  count=count, duration=_library_duration(duration),
                                                  status=status_text))
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        display = getattr(self, "_hub_display_records", None) or []
        query = self.project_search.text().strip() if hasattr(self, "project_search") else ""
        if display and not query and getattr(self, "_resume_target", "") == str(display[0].get("path", "")):
            self._update_resume_project(display[0])
        if self._hub_on_screen():
            preferences = getattr(self, "_studio_preferences", None)
            auto_cover = (preferences() if callable(preferences) else {}).get("auto_cover", True) is not False
            for record in display:
                self._queue_library_maintenance(record, auto_cover)

    def _register_status_widget(self, record, kind: str, widget, extra=None) -> None:
        registry = getattr(self, "_hub_status_widgets", None)
        if registry is None:
            registry = self._hub_status_widgets = {}
        registry.setdefault(str(record.get("path", "")), []).append((kind, widget, extra))

    @staticmethod
    def _cover_source_pixmap(record: dict[str, object]) -> QPixmap:
        cover = StudioHubMixin._library_cover_path(record)
        pixmap = QPixmap(str(cover)) if cover.is_file() else QPixmap()
        return pixmap if not pixmap.isNull() else QPixmap()

    def _hero_cover_pixmap(self, record: dict[str, object]) -> QPixmap:
        """The hero's cover, decoded once per file version at a bounded width."""
        if not str(record.get('cover_path') or ''):
            return QPixmap()
        cover = self._library_cover_path(record)
        try:
            stat = cover.stat()
        except OSError:
            return QPixmap()
        key = (str(cover), stat.st_mtime_ns, stat.st_size)
        cached = getattr(self, "_hero_cover_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(cover))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > _HERO_COVER_MAX_WIDTH:
            reader.setScaledSize(QSize(_HERO_COVER_MAX_WIDTH,
                                       max(1, round(size.height() * _HERO_COVER_MAX_WIDTH / size.width()))))
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self._hero_cover_cache = (key, pixmap)
        return pixmap

    # 2026-09-18 III：工程库封面解码/缩放移出 GUI 线程。worker 产出目标
    # 尺寸 QImage（文件 IO+平滑缩放都在后台），GUI 侧只 fromImage 贴 label。
    @staticmethod
    def _library_cover_path(record):
        value = str(record.get('cover_path') or '')
        cover = Path(value)
        if value and not cover.is_absolute() and record.get('path'):
            cover = Path(str(record['path'])).resolve().parent / cover
        return cover

    def _enqueue_library_cover(self, record: dict[str, object], width: int, height: int, label) -> None:
        if not str(record.get('cover_path') or ''):
            return
        cover = self._library_cover_path(record)
        try:
            stat = cover.stat()
        except OSError:
            return
        key = (str(cover), int(width), int(height))
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = getattr(self, '_library_cover_images', {}).get(key)
        if cached is not None and cached[0] == stamp:
            label.setPixmap(QPixmap.fromImage(cached[1]))
            return
        self._library_cover_labels.setdefault(key, []).append(label)
        queue = getattr(self, "_library_cover_queue", None)
        if queue is None:
            import queue as _queue
            queue = self._library_cover_queue = _queue.Queue()
            self._library_cover_queued = set()
        if key not in self._library_cover_queued and queue.qsize() < 400:
            self._library_cover_queued.add(key)
            queue.put(key)

    def _start_library_cover_worker(self) -> None:
        if getattr(self, "_library_cover_thread", None) is not None:
            return
        if not hasattr(self, "library_cover_ready_signal"):
            return
        if getattr(self, "_library_cover_queue", None) is None:
            import queue as _queue
            self._library_cover_queue = _queue.Queue()
            self._library_cover_queued = set()
        self.library_cover_ready_signal.connect(self._on_library_cover_ready)
        queue = self._library_cover_queue

        def worker():
            from PySide6.QtGui import QImage, Qt as _Qt
            while True:
                key = queue.get()
                if key is None:
                    return
                path, width, height = key
                try:
                    stat = Path(path).stat()
                    stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
                    image = QImage(path)
                    if not image.isNull():
                        image = image.scaled(
                            width, height,
                            _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            _Qt.TransformationMode.SmoothTransformation,
                        )
                        image.setText('source_stamp', stamp)
                    self.library_cover_ready_signal.emit(path, width, height, image)
                except OSError:
                    self.library_cover_ready_signal.emit(path, width, height, QImage())
                except RuntimeError:
                    pass  # 页面关闭后信号对象可能已析构

        import threading as _threading
        thread = _threading.Thread(target=worker, name="studio-library-covers", daemon=True)
        self._library_cover_thread = thread
        thread.start()

    def _on_library_cover_ready(self, path: str, width: int, height: int, image) -> None:
        from PySide6.QtGui import QImage, QPixmap
        key = (str(path), int(width), int(height))
        getattr(self, '_library_cover_queued', set()).discard(key)
        if not isinstance(image, QImage) or image.isNull():
            getattr(self, '_library_cover_labels', {}).pop(key, None)
            return
        from collections import OrderedDict
        try:
            stat = Path(path).stat()
        except OSError:
            getattr(self, '_library_cover_labels', {}).pop(key, None)
            return
        stamp = image.text('source_stamp')
        if stamp and stamp != f'{stat.st_mtime_ns}:{stat.st_size}':
            # The custom cover changed while this decode was in flight.
            self._library_cover_queued.add(key)
            self._library_cover_queue.put(key)
            return
        cache = getattr(self, '_library_cover_images', None)
        if cache is None:
            cache = self._library_cover_images = OrderedDict()
        cache[key] = ((stat.st_mtime_ns, stat.st_size), image)
        cache.move_to_end(key)
        self._library_cover_bytes = sum(int(entry[1].sizeInBytes()) for entry in cache.values())
        while cache and (len(cache) > _COVER_CACHE_ENTRIES or self._library_cover_bytes > _COVER_CACHE_BYTES):
            _old_key, (_stamp, old_image) = cache.popitem(last=False)
            self._library_cover_bytes -= int(old_image.sizeInBytes())
        labels = getattr(self, "_library_cover_labels", {}).pop(key, None) or []
        pixmap = QPixmap.fromImage(image)
        from shiboken6 import isValid
        for label in labels:
            if isValid(label):
                label.setPixmap(pixmap)

    @staticmethod
    def _placeholder_cover(width: int, height: int) -> QPixmap:
        active = theme_definition(theme_key())
        pixmap = QPixmap(max(1, width), max(1, height))
        pixmap.fill(QColor(active.panel))
        painter = QPainter(pixmap)
        painter.setPen(QColor(active.accent))
        painter.setFont(QFont("Microsoft YaHei UI", max(15, min(28, width // 12)), QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "CC")
        painter.end()
        return pixmap

    @staticmethod
    def _cover_pixmap(record: dict[str, object], width: int, height: int) -> QPixmap:
        pixmap = StudioHubMixin._cover_source_pixmap(record)
        if pixmap.isNull():
            pixmap = StudioHubMixin._placeholder_cover(width, height)
        return pixmap.scaled(
            QSize(max(1, width), max(1, height)),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _build_project_card(self, record: dict[str, object], card_width: int) -> QToolButton:
        path = Path(str(record.get("path", "")))
        source_path = Path(str(record.get("source_media") or ""))
        name = display_project_name(record)
        count = int(record.get("cue_count", 0) or 0)
        duration = max(0, int(record.get("duration_ms", 0) or 0))
        status_text, status_key = self._project_status(record)
        cover_width = max(220, card_width - 20)
        cover_height = round(cover_width * 9 / 16)
        # Thumbnail keeps 16:9 and lands at ~58% of the fixed card height;
        # the remaining block holds the two-line title, meta and actions.
        card = _ProjectCard()
        card.setObjectName("recentProjectCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(card_width, cover_height + 168)
        card.set_project_text(tr("{name}\n{count} 条字幕 · {duration}\n{status}", name=name, count=count, duration=_library_duration(duration), status=status_text))
        bind_text(card, join_text([name, str(source_path) if source_path.name else tr("无源媒体"), str(path)], "\n"), property="toolTip")
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda _pos, target=str(path): self._recent_project_menu(target))
        card._library_item_path = str(path)
        card.clicked.connect(
            lambda checked=False, target=str(path): self._library_item_clicked(target, checked)
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        media = QFrame()
        media.setObjectName("projectCardMedia")
        media_layout = QGridLayout(media)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(0)
        cover_label = QLabel()
        cover_label.setObjectName("projectCardCover")
        cover_label.setFixedSize(cover_width, cover_height)
        cover_label.setPixmap(self._placeholder_cover(cover_width, cover_height))
        cover_label.setScaledContents(True)
        self._enqueue_library_cover(record, cover_width, cover_height, cover_label)
        media_layout.addWidget(cover_label, 0, 0)
        status = QLabel(status_text)
        status.setObjectName("projectCardStatus")
        status.setProperty("status", status_key)
        status.setFixedHeight(24)
        media_layout.addWidget(status, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._register_status_widget(record, "card", status, card)
        layout.addWidget(media)
        metrics = QFontMetrics(card.font())
        title = user_text(QLabel(metrics.elidedText(name, Qt.TextElideMode.ElideRight, cover_width)))
        title.setObjectName("projectCardTitle")
        title.setWordWrap(True)
        title.setFixedHeight(max(42, metrics.lineSpacing() * 2 + 4))
        layout.addWidget(title)
        media_name = metrics.elidedText(source_path.name or tr("无源媒体"), Qt.TextElideMode.ElideRight, cover_width)
        meta = bind_text(QLabel(), '{count} 条字幕 · {value1} · {media_name}', count=count, value1=_library_duration(duration), media_name=media_name)
        meta.setObjectName("projectCardMeta")
        meta.setFixedHeight(20)
        layout.addWidget(meta)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        open_button = QPushButton("继续编辑")
        open_button.setObjectName("projectCardOpen")
        from .design.presentation import button_role
        button_role(open_button, 'primary', icon='fa5s.play')
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.setMinimumHeight(34)
        open_button.clicked.connect(lambda _checked=False, target=str(path): self._open_recent_project_card(target))
        actions.addWidget(open_button)
        actions.addStretch(1)
        more = QToolButton()
        more.setObjectName("projectCardMore")
        install_themed_icon(more, "fa5s.ellipsis-h", "muted")
        more.clicked.connect(lambda _checked=False, target=str(path): self._recent_project_menu(target))
        actions.addWidget(more)
        layout.addLayout(actions)
        if bool(getattr(self, "_library_selection_mode", False)):
            selected = getattr(self, "_library_selected_paths", None) or set()
            card.setCheckable(True)
            card.setChecked(str(path) in selected)
            open_button.setEnabled(False)
            more.setEnabled(False)
        return card

    @staticmethod
    def _library_edited_time(record: dict[str, object]) -> str:
        """最近编辑时间的短形态（本地时区 MM-DD HH:MM），读不到留空。"""
        from datetime import datetime

        for key in ("last_opened", "modified", "updated_at"):
            raw = str(record.get(key) or "")
            if not raw:
                continue
            try:
                stamp = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone()
            return stamp.strftime("%m-%d %H:%M")
        return ""

    def _add_project_list_row(self, record: dict[str, object]) -> None:
        """整行可打开；信息居左，状态和继续编辑动作在右侧居中对齐。"""
        path = Path(str(record.get("path", "")))
        source_path = Path(str(record.get("source_media") or ""))
        name = display_project_name(record)
        count = int(record.get("cue_count", 0) or 0)
        duration = max(0, int(record.get("duration_ms", 0) or 0))
        status_text, status_key = self._project_status(record)
        row = QToolButton()
        row.setObjectName("projectListRow")
        # QToolButton 默认 Fixed 尺寸策略会把整行压成 sizeHint 宽（~20px 塌陷）；
        # 行必须横向铺满、高度由内容+QSS min-height 决定。
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.setMinimumHeight(76)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(row, '{name}\n{value1}\n{path}\n点击任意位置继续编辑', property='toolTip', name=name, value1=source_path if source_path.name else tr("无源媒体"), path=path)
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda _pos, target=str(path): self._recent_project_menu(target)
        )
        row._library_item_path = str(path)
        row.clicked.connect(
            lambda checked=False, target=str(path): self._library_item_clicked(target, checked)
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        cover = QLabel()
        cover.setObjectName("projectCardCover")
        cover.setFixedSize(104, 58)
        cover.setPixmap(self._placeholder_cover(104, 58))
        cover.setScaledContents(True)
        self._enqueue_library_cover(record, 104, 58, cover)
        layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = user_text(QLabel(name))
        title.setObjectName("projectListTitle")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_row.addWidget(title, 1)
        status = QLabel(status_text)
        status.setObjectName("projectRowStatus")
        status.setProperty("status", status_key)
        status.setText("●  " + status_text)
        status.setAccessibleName(status_text)
        text.addLayout(title_row)
        meta_bits = [
            tr("{count} 条字幕", count=count),
            _library_duration(duration),
            source_path.name or tr("无源媒体"),
        ]
        edited = self._library_edited_time(record)
        if edited:
            meta_bits.append(tr("编辑 {time}", time=edited))
        meta = bind_text(QLabel(), join_text(meta_bits))
        meta.setObjectName("projectListMeta")
        meta.setWordWrap(False)
        text.addWidget(meta)
        layout.addLayout(text, 1)
        layout.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
        open_button = QPushButton("继续编辑" if status_key == "ready" else "查看工程")
        open_button.setObjectName("projectRowOpen")
        self._register_status_widget(record, "row", status, open_button)
        install_themed_icon(open_button, "fa5s.arrow-right", "primary")
        open_button.setAccessibleName(f"{open_button.text()} {name}")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.setMinimumHeight(32)
        bind_text(open_button, '继续编辑该工程', property='toolTip')
        open_button.clicked.connect(
            lambda _checked=False, target=str(path): self._open_recent_project_card(target)
        )
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignVCenter)
        more = QToolButton()
        more.setObjectName("projectCardMore")
        install_themed_icon(more, "fa5s.ellipsis-h", "muted")
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(more, '更多操作', property='toolTip')
        more.clicked.connect(
            lambda _checked=False, target=str(path): self._recent_project_menu(target)
        )
        layout.addWidget(more, 0, Qt.AlignmentFlag.AlignVCenter)
        if bool(getattr(self, "_library_selection_mode", False)):
            selected = getattr(self, "_library_selected_paths", None) or set()
            row.setCheckable(True)
            row.setChecked(str(path) in selected)
            open_button.setEnabled(False)
            more.setEnabled(False)
        row_widgets = getattr(self, "_hub_row_widgets", None)
        if row_widgets is None:
            row_widgets = self._hub_row_widgets = []
        row_widgets.append(row)
        self.project_list_layout.addWidget(row)

    def _update_resume_project(self, record: dict[str, object] | None) -> None:
        if not hasattr(self, "resume_title"):
            return
        if not record:
            self._resume_has_cover = False
            self._resume_target = ""
            bind_text(self.resume_title, '还没有打开过工程')
            bind_text(self.resume_meta, '导入视频或打开 .2byteproj，开始你的第一批字幕。')
            bind_text(self.resume_status, '等待开始')
            if hasattr(self, "resume_status_pill"):
                self.resume_status_pill.hide()
            self.resume_continue_button.setEnabled(False)
            self.resume_details_button.setEnabled(False)
            self._resume_cover_aspect = 16 / 9
            self.resume_preview_image.set_cover(self._placeholder_cover(640, 360))
            self._sync_resume_hero_geometry()
            return
        path = Path(str(record.get("path", "")))
        source_path = Path(str(record.get("source_media") or ""))
        name = display_project_name(record)
        count = int(record.get("cue_count", 0) or 0)
        duration = max(0, int(record.get("duration_ms", 0) or 0))
        status_text, status_key = self._project_status(record)
        progress = record.get("review_progress")
        self._resume_target = str(path)
        user_text(self.resume_title).setText(name)
        if isinstance(progress, (int, float)):
            bind_text(self.resume_meta, '{count} 条字幕 · {value1} · {progress_text}', count=count,
                      value1=_library_duration(duration), progress_text=tr("复核 {percent}%", percent=int(progress)))
        elif hasattr(self, "resume_status_pill"):
            # The state is already the pill below; do not repeat it here.
            edited = self._library_edited_time(record)
            if edited:
                bind_text(self.resume_meta, '{count} 条字幕 · {value1} · 上次编辑 {edited}', count=count,
                          value1=_library_duration(duration), edited=edited)
            else:
                bind_text(self.resume_meta, '{count} 条字幕 · {value1}', count=count, value1=_library_duration(duration))
        else:
            bind_text(self.resume_meta, '{count} 条字幕 · {value1} · {progress_text}', count=count,
                      value1=_library_duration(duration), progress_text=status_text)
        if hasattr(self, "resume_status_pill"):
            self.resume_status_pill.setText(status_text)
            self.resume_status_pill.setProperty("status", status_key)
            self.resume_status_pill.style().unpolish(self.resume_status_pill)
            self.resume_status_pill.style().polish(self.resume_status_pill)
            self.resume_status_pill.show()
            user_text(self.resume_status).setText(source_path.name or tr("无源媒体"))
        else:
            bind_text(self.resume_status, join_text([status_text, source_path.name or tr("无源媒体")]))
        enabled = bool(str(path))
        self.resume_continue_button.setEnabled(enabled)
        self.resume_details_button.setEnabled(enabled)
        source = self._hero_cover_pixmap(record)
        self._resume_has_cover = not source.isNull()
        if source.isNull():
            source = self._placeholder_cover(640, 360)
            self._resume_cover_aspect = 16 / 9
        else:
            self._resume_cover_aspect = max(0.5, source.width() / max(1, source.height()))
        self.resume_preview_image.set_cover(source)
        self._sync_resume_hero_geometry()

    def _set_project_library_view(self, mode: str, *, refresh: bool = True) -> None:
        mode = "list" if str(mode) == "list" else "card"
        self._project_library_view_mode = mode
        if hasattr(self, "all_projects_stack"):
            self.all_projects_stack.setCurrentIndex(1 if mode == "list" else 0)
        if hasattr(self, "project_card_view_button"):
            self.project_card_view_button.setChecked(mode == "card")
        if hasattr(self, "project_list_view_button"):
            self.project_list_view_button.setChecked(mode == "list")
        built = getattr(self, "_hub_built_views", None)
        if (built is not None and mode not in built and getattr(self, "_hub_render_signature", None) is not None
                and hasattr(self, "all_projects_layout") and getattr(self, "project", None) is None):
            self._build_library_view(mode)
        if hasattr(self, "all_projects_layout") and mode == "card":
            self.all_projects_layout.activate()
            self.all_projects_layout.setGeometry(self.all_projects_host.rect())
        if hasattr(self, "project_list_layout") and mode == "list":
            self.project_list_layout.activate()
            self.project_list_layout.setGeometry(self.project_list_host.rect())
        if refresh and hasattr(self, "project") and self.project is None:
            self._refresh_studio_empty_state()

    def _show_recent_project_details(self, target: str) -> None:
        path = Path(str(target)).expanduser()
        records = [item for item in self._project_library_records() if str(item.get("path", "")) == str(path)]
        record = records[0] if records else {"name": path.stem, "path": str(path)}
        count = int(record.get("cue_count", 0) or 0)
        duration = max(0, int(record.get("duration_ms", 0) or 0))
        source = str(record.get("source_media") or "无源媒体")
        width = int(record.get("width", 0) or 0)
        height = int(record.get("height", 0) or 0)
        updated = str(record.get("updated_at") or "未知")
        resolution = f"{width} × {height}" if width and height else "未知"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        bind_text(box, '工程详情', property='windowTitle')
        box.setText(display_project_name(record))
        bind_text(box, '媒体：{value0}\n分辨率：{value1}\n视频时长：{value2}\n字幕条数：{value3}\n最后编辑：{value4}\n工程路径：{value5}', property='informativeText', value0=Path(source).name if source != '无源媒体' else tr(source), value1=resolution, value2=_library_duration(duration), value3=count, value4=updated, value5=path)
        apply_secondary_surface_theme(box)
        box.exec()

    def _project_library_records(self) -> list[dict[str, object]]:
        """Merge recent metadata with every project in the canonical library.

        2026-09-19：持久化摘要索引（library-index.json）驱动。卡片摘要命中
        (mtime_ns+size) 时零解析直接复用，只有真实变化过的工程才走全量
        snapshot；扫描结束把更新写回索引。首屏在 _rebuild_project_library
        里直接读索引，不再等扫描。
        """
        self._library_read_warnings = []
        scan_generation = int(getattr(self, '_hub_scan_generation', 0))
        index = load_library_index(diagnostics=self._library_read_warnings)
        index_dirty = False

        def cached_summary(resolved: str, stat) -> dict[str, object] | None:
            entry = index.get(resolved)
            if library_index_entry_stale(entry, stat):
                return None
            summary = {key: entry[key] for key in _LIBRARY_INDEX_SUMMARY_KEYS if key in entry}
            summary["_needs_metadata_repair"] = bool(entry.get("needs_metadata_repair"))
            summary["_summary_loaded"] = True
            return summary

        recent = self.recent_project_records()
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        library_root = project_library_root().resolve()

        def internal_snapshot(path: Path) -> bool:
            # An explicitly configured library may itself live under a temp
            # parent (portable runs/tests). Filter its internal subfolders,
            # not the caller's choice of ancestor directory.
            resolved = path.resolve()
            if not resolved.is_relative_to(library_root):
                resolved = path
            return _internal_project_snapshot(resolved, library_root)

        def enrich(record: dict[str, object], project_path: Path) -> dict[str, object]:
            nonlocal index_dirty
            resolved = str(project_path.resolve())
            try:
                stat = project_path.stat()
            except OSError:
                stat = None
            cached = cached_summary(resolved, stat)
            if cached is not None:
                record.update(cached)
                return record
            _project, summary, needs_repair = library_project_snapshot(project_path, record)
            record.update(summary)
            record["_needs_metadata_repair"] = bool(needs_repair)
            record["_summary_loaded"] = True
            if stat is not None:
                entry = {
                    "mtime_ns": int(stat.st_mtime_ns),
                    "size": int(stat.st_size),
                    "needs_metadata_repair": bool(needs_repair),
                }
                entry.update({key: summary.get(key) for key in _LIBRARY_INDEX_SUMMARY_KEYS})
                index[resolved] = entry
                index_dirty = True
            return record

        for recent_index, item in enumerate(recent):
            path = str(item.get("path", ""))
            project_path = Path(path).expanduser() if path else None
            if project_path is not None and internal_snapshot(project_path):
                continue
            resolved = str(project_path.resolve()) if project_path and project_path.exists() else path
            if path and resolved not in seen:
                record = dict(item)
                record["path"] = resolved
                if project_path.is_file():
                    try:
                        enrich(record, project_path)
                    except (OSError, ValueError, TypeError):
                        pass
                # Legacy recent records predate the explicit timestamp. Their
                # persisted order is still valid recency metadata.
                record.setdefault("last_opened", str(record.get("modified", "")) or f"9999-recent-{9999 - recent_index:04d}")
                merged.append(record)
                seen.add(resolved)
        def walk_error(error):
            raise error
        try:
            library_root.stat()
            candidates = sorted(
                (Path(folder) / name for folder, _dirs, names in os.walk(library_root, onerror=walk_error)
                 for name in names if name.lower().endswith('.2byteproj')),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except FileNotFoundError as exc:
            # A fresh library has no directory yet. Removing its last recent
            # external/missing project must still produce the empty state.
            # An unavailable drive remains an actionable read error.
            if not Path(library_root.anchor).is_dir():
                raise OSError(f'{library_root}：{exc}') from exc
            candidates = []
        except OSError as exc:
            raise OSError(f'{library_root}：{exc}') from exc
        for path in candidates:
            if internal_snapshot(path):
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            try:
                record = enrich({
                    "path": resolved,
                    "name": path.stem,
                    "last_opened": "",
                }, path)
            except (OSError, ValueError, TypeError) as exc:
                record = {"path": resolved, "name": path.stem, "cue_count": 0, "source_media": ""}
                record['status'] = f'读取失败：{exc}'
                self._library_read_warnings.append(f'工程读取失败：{path.name}（{exc}）')
            merged.append(record)
            seen.add(resolved)

        deduplicated = _dedupe_library_records(merged)
        if index_dirty and not self._library_read_warnings:
            with _LIBRARY_INDEX_LOCK:
                if scan_generation == int(getattr(self, '_hub_scan_generation', 0)):
                    save_library_index(index)
        return deduplicated

    def _library_records_from_index(self) -> list[dict[str, object]] | None:
        """First-paint records straight from the persisted index (no parsing).

        Merges recent entries with cached summaries; projects absent from the
        index fall back to their persisted recent fields (or basic path info),
        and the background scan refreshes them moments later.
        """
        # 2026-10-12: built exactly like the background scan builds an
        # unchanged library (same fields, order, filtering and dedupe), so the
        # scan result compares equal and does not rebuild every card. No file
        # system checks here: those run in the scan thread.
        index = load_library_index()
        if not index:
            return None
        library_root = Path(os.path.abspath(project_library_root()))
        root_key = os.path.normcase(str(library_root)).rstrip("\\/") + os.sep

        def summary(entry: dict[str, object]) -> dict[str, object]:
            values = {key: entry[key] for key in _LIBRARY_INDEX_SUMMARY_KEYS if key in entry}
            values["_needs_metadata_repair"] = bool(entry.get("needs_metadata_repair"))
            values["_summary_loaded"] = True
            return values

        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for recent_index, item in enumerate(self._recent_records_unchecked()):
            path = str(item.get("path", ""))
            if not path:
                continue
            resolved = os.path.abspath(os.path.expanduser(path))
            if _internal_project_snapshot(Path(resolved), library_root) or resolved in seen:
                continue
            record = dict(item)
            record["path"] = resolved
            entry = index.get(resolved)
            if isinstance(entry, dict):
                record.update(summary(entry))
            record.setdefault("last_opened", str(record.get("modified", "")) or f"9999-recent-{9999 - recent_index:04d}")
            merged.append(record)
            seen.add(resolved)
        library_entries = sorted(
            ((key, entry) for key, entry in index.items()
             if key not in seen and isinstance(entry, dict)
             and os.path.normcase(key).startswith(root_key)
             and not _internal_project_snapshot(Path(key), library_root)),
            key=lambda item: int(item[1].get("mtime_ns", 0) or 0),
            reverse=True,
        )
        for resolved, entry in library_entries:
            record = {"path": resolved, "name": Path(resolved).stem, "last_opened": ""}
            record.update(summary(entry))
            merged.append(record)
            seen.add(resolved)
        return _dedupe_library_records(merged) or None

    def _recent_records_unchecked(self) -> list[dict[str, object]]:
        """recent_project_records() without its per-file existence checks."""
        try:
            payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
            recent = payload.get("recent_projects", []) if isinstance(payload, dict) else []
        except (OSError, ValueError, TypeError):
            recent = []
        records: list[dict[str, object]] = []
        for item in recent:
            record = dict(item) if isinstance(item, dict) else {"path": str(item)}
            path = Path(str(record.get("path", "")))
            record.setdefault("name", path.stem)
            record.setdefault("source_media", "")
            record.setdefault("modified", "")
            record.setdefault("cue_count", 0)
            record.setdefault("cover_path", "")
            record.setdefault("pinned", False)
            records.append(record)
        return records

    def _open_recent_project_card(self, target: str) -> None:
        """Card-level entry point; keeps the canonical path and reports progress."""
        project_path = Path(str(target)).expanduser()
        self._studio_trace("RECENT_CLICK", card_id=str(project_path.stem), project_path=str(project_path))
        self._studio_trace("OPEN_REQUEST", project_path=str(project_path))
        self._studio_trace("OPEN_VALIDATE", exists=project_path.is_file(), readable=os.access(project_path, os.R_OK))
        if not project_path.is_file():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            bind_text(box, '工程文件已移动', property='windowTitle')
            bind_text(box, '找不到工程文件：\n{project_path}\n\n可以重新定位工程，或从最近记录移除。', project_path=project_path)
            locate = box.addButton("重新定位工程", QMessageBox.ButtonRole.AcceptRole)
            remove = box.addButton("从最近记录移除", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            apply_secondary_surface_theme(box)
            box.exec()
            if box.clickedButton() is locate:
                self.open_project_dialog()
            elif box.clickedButton() is remove:
                self._remove_recent_project_metadata(str(project_path))
            return
        self._project_opening_path = str(project_path.resolve())
        self._project_view_state = "loading"
        bind_text(self.save_state, '正在打开…')
        bind_text(self.hub_loading_label, '正在打开工程…')
        self.hub_loading_label.show()
        self.studio_empty.setEnabled(False)
        # Paint the existing, stable Hub. Never drain an event loop between
        # changing toolbar visibility and restoring the destination layout.
        self.hub_loading_label.repaint()
        host = self.window()
        if host is not self and hasattr(host, "open_studio_project"):
            host.open_studio_project(str(project_path), mode="edit", source="recent_card")
        else:
            self.open_project(project_path)

    def _remove_recent_project_metadata(self, target: str) -> None:
        self._remove_recent_project_metadata_batch({str(target)})

    def _set_hub_toolbar_mode(self, hub: bool) -> None:
        """Keep project-only actions out of the project-free Hub header."""
        if hub and hasattr(self, "teach_banner"):
            self.teach_banner.hide()
        if hasattr(self, "studio_toolbar"):
            self.studio_toolbar.setProperty("hubMode", bool(hub))
            self.studio_toolbar.style().unpolish(self.studio_toolbar)
            self.studio_toolbar.style().polish(self.studio_toolbar)
        active = theme_definition(theme_key())
        icon_role = "muted" if hub else "primary"
        for button, icon_name in (
            (getattr(self, "studio_back_button", None), "fa5s.arrow-left"),
            (getattr(self, "studio_home_button", None), "fa5s.home"),
            (getattr(self, "studio_library_button", None), "fa5s.th-large"),
            (getattr(self, "studio_open_button", None), "fa5s.folder-open"),
            (getattr(self, "studio_hub_settings_button", None), "fa5s.cog"),
        ):
            if button is not None:
                install_themed_icon(button, icon_name, icon_role)
        hidden = getattr(self, "_hub_toolbar_hidden", ())
        for widget in hidden:
            if widget is not None:
                widget.setVisible(not hub)
        # Application settings are a global preference, reachable from the
        # editor as well as the project library.
        if hasattr(self, "studio_hub_settings_button"):
            self.studio_hub_settings_button.setVisible(True)
        if hasattr(self, "studio_library_button"):
            self.studio_library_button.setVisible(True)
        if hasattr(self, "_sync_navigation_chrome"):
            self._sync_navigation_chrome()
        for widget in getattr(self, '_studio_toolbar_overflow_widgets', ()):
            widget.hide()

    def _show_hub_preferences(self) -> None:
        from .application_settings import open_application_settings

        open_application_settings(
            self,
            on_saved=self._after_application_settings_saved,
            reset_layout=self._reset_studio_layout_preferences,
            refresh_library=self._refresh_visible_library,
        )

    def _after_application_settings_saved(self) -> None:
        if self.project:
            self._schedule_autosave()

    def _refresh_visible_library(self) -> None:
        """Rescan only while the Hub is actually on screen; never navigates."""
        if getattr(self, "_project_view_state", "") == "hub":
            self._refresh_studio_empty_state()

    def _save_hub_preferences(self, root: str, auto_save: bool, interval: int, recent_count: int, cover: bool, restore_layout: bool, recovery_policy: str = "ask") -> None:
        from .application_settings import save_hub_preferences

        save_hub_preferences(root, auto_save, interval, recent_count, cover, restore_layout, recovery_policy)
        if self.project:
            self._schedule_autosave()

    @staticmethod
    def _choose_hub_project_root(editor: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(editor.window(), tr('选择默认工程目录'), editor.text())
        if chosen:
            editor.setText(chosen)

    def _save_hub_preferences(self, root: str, auto_save: bool, interval: int, recent_count: int, cover: bool, restore_layout: bool, recovery_policy: str = "ask") -> None:
        path = studio_settings_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        if root:
            payload["project_root"] = str(Path(root).expanduser())
        else:
            payload.pop("project_root", None)
        payload["studio_preferences"] = {
            "autosave_enabled": bool(auto_save), "autosave_interval_seconds": int(interval),
            "recent_project_count": int(recent_count), "auto_cover": bool(cover),
            "restore_layout": bool(restore_layout),
            "recovery_policy": recovery_policy if recovery_policy in {"ask", "auto", "official"} else "ask",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if self.project:
            self._schedule_autosave()
        self._refresh_studio_empty_state()

    def _clear_recent_project_metadata(self) -> None:
        path = studio_settings_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        payload["recent_projects"] = []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._refresh_studio_empty_state()

    def _set_library_manage_mode(self, enabled: bool) -> None:
        """Batch-selection mode: cards/list rows become checkable, clicks toggle."""
        enabled = bool(enabled)
        if enabled == bool(getattr(self, "_library_selection_mode", False)):
            return
        self._library_selection_mode = enabled
        if not enabled:
            self._library_selected_paths = set()
        button = getattr(self, "project_manage_button", None)
        if button is not None:
            button.blockSignals(True)
            button.setChecked(enabled)
            (bind_text(button, '完成') if enabled else bind_text(button, '管理'))
            button.blockSignals(False)
        bar = getattr(self, "project_manage_bar", None)
        if bar is not None:
            bar.setVisible(enabled)
        if hasattr(self, "studio_empty"):
            self._rebuild_project_library()

    def _library_item_clicked(self, target: str, checked: bool) -> None:
        if getattr(self, "_library_selection_mode", False):
            self._set_library_item_selected(target, checked)
        else:
            self._open_recent_project_card(target)

    def _set_library_item_selected(self, target: str, selected: bool) -> None:
        selected_paths = getattr(self, "_library_selected_paths", None)
        if selected_paths is None:
            selected_paths = self._library_selected_paths = set()
        key = str(Path(str(target)))
        if selected:
            selected_paths.add(key)
        else:
            selected_paths.discard(key)
        self._library_update_manage_bar()

    def _library_update_manage_bar(self) -> None:
        label = getattr(self, "project_manage_count_label", None)
        if label is None:
            return
        count = len(getattr(self, "_library_selected_paths", None) or ())
        bind_text(label, '已选 {count} 项', count=count)
        delete = getattr(self, "project_delete_button", None)
        if delete is not None:
            delete.setEnabled(count > 0)

    def _iter_library_item_widgets(self):
        for widget in list(getattr(self, "_hub_card_widgets", ()) or ()):
            yield widget
        for widget in list(getattr(self, "_hub_row_widgets", ()) or ()):
            yield widget

    @staticmethod
    def _library_record_is_empty(record: dict[str, object]) -> bool:
        """空工程 = 摘要已确认的前提下，无字幕且无可用源媒体。

        2026-09-18 III："尚未加载"不等于"空工程"——解析失败的回退记录没有
        _summary_loaded 标记，禁止被批量删除命中。
        """
        if not record.get("_summary_loaded"):
            return False
        count = int(record.get("cue_count", 0) or 0)
        if count:
            return False
        source_value = str(record.get("source_media") or "").strip()
        return (not source_value) or (not Path(source_value).is_file())

    def _library_select_empty_projects(self) -> None:
        self._library_select_displayed(
            predicate=lambda record: self._library_record_is_empty(record)
        )

    def _library_select_displayed(self, *, predicate=None, select_all: bool = False) -> None:
        records = list(getattr(self, "_hub_display_records", ()) or ())
        if select_all:
            targets = {str(record.get("path", "")) for record in records}
        elif predicate is not None:
            targets = {str(record.get("path", "")) for record in records if predicate(record)}
        else:
            targets = set()
        selected = getattr(self, "_library_selected_paths", None)
        if selected is None:
            selected = self._library_selected_paths = set()
        selected.clear()
        selected.update(targets)
        for widget in self._iter_library_item_widgets():
            path = getattr(widget, "_library_item_path", "")
            if path:
                widget.setChecked(path in selected)
        self._library_update_manage_bar()

    def _remove_recent_project_metadata_batch(self, targets: set[str]) -> None:
        if not targets:
            return
        def _normalized(path: str) -> str:
            return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))

        wanted = {_normalized(target) for target in targets}
        settings = studio_settings_path()
        try:
            payload = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        payload["recent_projects"] = [
            item for item in payload.get("recent_projects", [])
            if not isinstance(item, dict) or _normalized(item.get("path", "")) not in wanted
        ]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # 2026-09-19：显式移除同步清持久化索引与内存 records——删除后的
        # 列表刷新不能再从索引渲染已删工程（离线盘的"保留记录"只适用于
        # 扫描时不可达，不适用于用户明确移除）。路径键统一 resolve+normcase
        # 后比较，避免原始/resolved 写法差异导致清不掉。
        from .studio_project import load_library_index, save_library_index

        with _LIBRARY_INDEX_LOCK:
            # Also prevent a scan captured before deletion from re-persisting
            # the old index after the card has been removed.
            self._hub_scan_generation = int(getattr(self, "_hub_scan_generation", 0)) + 1
            index = load_library_index()
            stale = [key for key in index if _normalized(key) in wanted]
            if stale:
                for key in stale:
                    index.pop(key, None)
                save_library_index(index)
        # 同步重算（索引命中时 <100ms），立即得到删除后的正确列表。
        try:
            self._hub_library_records = self._project_library_records()
        except (OSError, ValueError, TypeError):
            records = getattr(self, "_hub_library_records", None)
            if records:
                self._hub_library_records = [
                    record for record in records
                    if _normalized(str(record.get("path", ""))) not in wanted
                ]

    def _delete_selected_library_projects(self) -> None:
        selected = set(getattr(self, "_library_selected_paths", None) or ())
        if not selected:
            return
        records = {
            str(record.get("path", "")): record
            for record in (getattr(self, "_hub_display_records", ()) or ())
        }
        targets = [path for path in selected if path in records]
        if not targets:
            self._library_update_manage_bar()
            return
        preview = "\n".join(
            f"· {display_project_name(records[path])}" for path in targets[:6]
        )
        if len(targets) > 6:
            preview += '\n' + tr('… 以及另外 {count} 个', count=len(targets)-6)
        answer = studio_message_box(
            self,
            QMessageBox.Icon.Warning,
            tr('删除所选工程'),
            tr('确定删除 {value0} 个工程？\n\n{value1}\n\n仅移除工程文件（.2byteproj）与最近记录，源媒体和识别缓存不受影响。', value0=len(targets), value1=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted: list[str] = []
        failed: list[str] = []
        for path in targets:
            try:
                Path(path).unlink(missing_ok=True)
                deleted.append(path)
            except OSError:
                failed.append(path)
        self._remove_recent_project_metadata_batch(set(deleted))
        self._studio_trace(
            "LibraryBatchDelete",
            requested=len(targets),
            deleted=len(deleted),
            failed=len(failed),
        )
        self._library_selected_paths = set()
        self._refresh_studio_empty_state()
        self._library_update_manage_bar()
        if failed:
            studio_message_box(
                self,
                QMessageBox.Icon.Warning,
                tr('部分工程未能删除'),
                tr('{value0} 个工程文件删除失败（可能正被占用）：\n{value1}', value0=len(failed), value1='\n'.join((Path(path).name for path in failed[:5]))),
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok,
            )

    def _recent_project_menu(self, target: str) -> None:
        menu = create_studio_menu(self)
        details = menu.addAction("工程详情")
        rename = menu.addAction("重命名")
        menu.addSeparator()
        remove = menu.addAction("从最近记录移除")
        reveal = menu.addAction("打开所在目录")
        delete = menu.addAction("删除工程")
        chosen = menu.exec(QCursor.pos())
        path = Path(target)
        if chosen is details:
            self._show_recent_project_details(str(path))
        elif chosen is rename and path.is_file():
            try:
                project = load_project(path)
            except (OSError, ValueError, TypeError):
                return
            value, accepted = QInputDialog.getText(
                self,
                tr('重命名工程'),
                tr('工程名称'),
                text=str((project.studio_state or {}).get("project_name") or path.stem),
            )
            if accepted and value.strip():
                project.studio_state = dict(project.studio_state or {})
                project.studio_state["project_name"] = value.strip()
                project.studio_state.pop("project_name_origin", None)
                project.studio_state.pop("project_name_automatic", None)
                save_project(project, path)
                self._refresh_studio_empty_state()
        elif chosen is remove:
            self._remove_recent_project_metadata(str(path))
            self._refresh_studio_empty_state()
        elif chosen is reveal and path.exists():
            os.startfile(str(path.parent))
        elif chosen is delete:
            answer = studio_message_box(
                self, QMessageBox.Icon.Warning, tr('删除工程'), tr('确定删除 {value0}？', value0=path.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    studio_message_box(self, QMessageBox.Icon.Warning, tr('工程删除失败'), str(exc))
                    return
                self._remove_recent_project_metadata(str(path))
                self._refresh_studio_empty_state()
