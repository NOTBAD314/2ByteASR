"""Searchable Media Pool and multi-track controls for Subtitle Studio."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .studio_media_commands import media_graph_command
from .studio_media_pool import (
    add_video_clip,
    create_video_track,
    media_usage,
    primary_video_track_id,
    relink_media_asset,
    remove_unused_media,
)
from .themed_icons import themed_icon

from .i18n import bind_text

from .i18n import tr


MEDIA_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.webm *.flv *.avi *.wav *.mp3 "
    "*.m4a *.flac *.aac);;所有文件 (*)"
)


def _format_duration(milliseconds: int) -> str:
    total = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


class StudioMediaPoolPanel(QWidget):
    """A project-bound panel. Mutations always enter the page undo stack."""

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        self.page = page
        self.setObjectName("studioMediaPoolPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("媒体池")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.asset_count = QLabel("0 个素材")
        self.asset_count.setObjectName("mediaPoolMeta")
        header.addWidget(self.asset_count)
        layout.addLayout(header)

        self.preview_contract = QLabel("预览：最上方启用片段 · 不合成重叠视频")
        self.preview_contract.setObjectName("mediaPoolPreviewContract")
        self.preview_contract.setWordWrap(True)
        layout.addWidget(self.preview_contract)

        self.search = QLineEdit()
        self.search.setObjectName("mediaPoolSearch")
        bind_text(self.search, '搜索素材', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.assets = QTreeWidget()
        self.assets.setObjectName("mediaPoolAssets")
        self.assets.setColumnCount(3)
        self.assets.setHeaderLabels(["素材", "状态", "时长"])
        self.assets.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.assets.setRootIsDecorated(False)
        self.assets.setUniformRowHeights(True)
        # Keep at least several selectable rows when the timeline is tall.
        self.assets.setMinimumHeight(140)
        self.assets.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.assets.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.assets.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.assets.itemSelectionChanged.connect(self._sync_actions)
        self.assets.itemDoubleClicked.connect(lambda *_args: self._add_selected_to_track())
        layout.addWidget(self.assets, 1)

        asset_actions = QHBoxLayout()
        self.add_asset_button = self._button(
            "fa5s.plus", "添加素材", self._add_asset
        )
        self.relink_button = self._button(
            "fa5s.link", "重新定位", self._relink_selected
        )
        self.remove_unused_button = self._button(
            "fa5s.trash-alt", "移除未使用", self._remove_unused
        )
        for button in (
            self.add_asset_button,
            self.relink_button,
            self.remove_unused_button,
        ):
            asset_actions.addWidget(button)
        asset_actions.addStretch(1)
        layout.addLayout(asset_actions)

        divider = QFrame()
        divider.setObjectName("mediaPoolDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        track_row = QHBoxLayout()
        self.track_selector = QComboBox()
        self.track_selector.setObjectName("mediaPoolTrackSelector")
        self.track_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.track_selector.currentIndexChanged.connect(self._track_selected)
        track_row.addWidget(self.track_selector, 1)
        self.add_track_button = self._icon_button(
            "fa5s.plus", "新建视频轨", self._add_track
        )
        track_row.addWidget(self.add_track_button)
        layout.addLayout(track_row)

        self.add_to_track_button = QPushButton("加入所选轨道")
        self.add_to_track_button.setObjectName("studioPrimary")
        self.add_to_track_button.setIcon(themed_icon("fa5s.arrow-right", "primary"))
        self.add_to_track_button.clicked.connect(self._add_selected_to_track)
        layout.addWidget(self.add_to_track_button)
        self._sync_actions()

    def _button(self, icon_name: str, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("studioButton")
        button.setIcon(themed_icon(icon_name, "primary"))
        button.clicked.connect(callback)
        return button

    def _icon_button(self, icon_name: str, tooltip: str, callback) -> QToolButton:
        button = QToolButton()
        button.setObjectName("studioTool")
        button.setIcon(themed_icon(icon_name, "primary"))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def refresh(self, project=None) -> None:
        project = self.page.project if project is None else project
        selected_asset_id = self.selected_asset_id()
        selected_track_id = self.selected_track_id()
        self.assets.clear()
        self.track_selector.blockSignals(True)
        self.track_selector.clear()
        if project is None:
            bind_text(self.asset_count, '0 个素材')
            self.track_selector.blockSignals(False)
            self._sync_actions()
            return
        usage = media_usage(project)
        for asset in project.media_pool:
            state = "离线" if asset.offline else "已使用" if usage.get(asset.asset_id) else "未使用"
            health = getattr(project, '_media_availability', {}).get(asset.canonical_source, {})
            if asset.offline:
                state = health.get('reason', state)
            item = QTreeWidgetItem(
                [asset.display_name, state, _format_duration(asset.duration_ms)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, asset.asset_id)
            item.setToolTip(0, asset.canonical_source)
            if asset.offline:
                item.setIcon(0, themed_icon("fa5s.exclamation-triangle", "warning"))
            else:
                item.setIcon(0, themed_icon("fa5s.film", "secondary"))
            self.assets.addTopLevelItem(item)
            if asset.asset_id == selected_asset_id:
                item.setSelected(True)
        for track in project.video_tracks:
            suffix = " · 已锁定" if track.locked else ""
            self.track_selector.addItem(f"{track.id}  {track.name}{suffix}", track.id)
        target_track = selected_track_id or str(
            project.studio_state.get("selected_video_track_id") or ""
        )
        index = self.track_selector.findData(target_track)
        if index < 0 and self.track_selector.count():
            index = next(
                (
                    row
                    for row, track in enumerate(project.video_tracks)
                    if not track.locked
                ),
                0,
            )
        self.track_selector.setCurrentIndex(index)
        self.track_selector.blockSignals(False)
        bind_text(self.asset_count, '{value0} 个素材', value0=len(project.media_pool))
        self._apply_filter(self.search.text())
        self._sync_actions()

    def selected_asset_id(self) -> str:
        item = self.assets.currentItem()
        return str(item.data(0, Qt.ItemDataRole.UserRole) or "") if item else ""

    def selected_track_id(self) -> str:
        return str(self.track_selector.currentData() or "")

    def select_track(self, track_id: str) -> None:
        index = self.track_selector.findData(str(track_id))
        if index >= 0:
            self.track_selector.setCurrentIndex(index)

    def _apply_filter(self, query: str) -> None:
        query = str(query or "").strip().casefold()
        for row in range(self.assets.topLevelItemCount()):
            item = self.assets.topLevelItem(row)
            haystack = " ".join(
                (item.text(0), item.text(1), item.toolTip(0))
            ).casefold()
            item.setHidden(bool(query and query not in haystack))

    def _sync_actions(self) -> None:
        project = self.page.project
        asset_id = self.selected_asset_id()
        track_id = self.selected_track_id()
        track = next(
            (item for item in project.video_tracks if item.id == track_id),
            None,
        ) if project else None
        primary_id = primary_video_track_id(project) if project else ""
        accepts_free_clip = track is not None and track.id != primary_id
        self.relink_button.setEnabled(bool(project and asset_id))
        self.add_to_track_button.setEnabled(
            bool(project and asset_id and accepts_free_clip and not track.locked)
        )
        (bind_text(self.add_to_track_button, 'V1 由主素材剪辑维护；新素材请选择 V2 或新建视频轨。', property='toolTip') if track is not None and track.id == primary_id else bind_text(self.add_to_track_button, '将所选素材放到当前播放头', property='toolTip'))
        unused = (
            sum(1 for used in media_usage(project).values() if not used)
            if project else 0
        )
        self.remove_unused_button.setEnabled(unused > 0)

    def _track_selected(self, _index: int) -> None:
        project = self.page.project
        track_id = self.selected_track_id()
        if project is not None and track_id:
            project.studio_state["selected_video_track_id"] = track_id
            if hasattr(self.page, "timeline"):
                self.page.timeline.selected_video_track_id = track_id
                self.page.timeline.update()
        self._sync_actions()

    def _add_asset(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, tr('添加素材'), "", MEDIA_FILTER
        )
        if path:
            self.page.project_controller._attach_media_to_current(
                Path(path), add_to_timeline=False
            )

    def _relink_selected(self) -> None:
        if self.relink_button.text() == '取消检查':
            self.page.media_availability.cancel_relink()
            return
        project = self.page.project
        asset_id = self.selected_asset_id()
        if project is None or not asset_id:
            return
        self.page.media_availability.choose_relink(asset_id)

    def _remove_unused(self) -> None:
        project = self.page.project
        if project is None:
            return
        unused = [asset for asset in project.media_pool if not media_usage(project).get(asset.asset_id)]
        if not unused:
            return
        answer = QMessageBox.question(
            self,
            tr('移除未使用素材'),
            tr('从当前工程移除 {value0} 个未使用素材？\n源文件不会被删除。', value0=len(unused)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.page.undo_stack.push(
            media_graph_command(project, "移除未使用素材", remove_unused_media)
        )

    def _add_track(self) -> None:
        if self.page.project is None:
            return
        self.page._add_video_track()

    def _add_selected_to_track(self) -> None:
        project = self.page.project
        asset_id = self.selected_asset_id()
        track_id = self.selected_track_id()
        if project is None or not asset_id or not track_id:
            return
        if track_id == primary_video_track_id(project):
            return
        try:
            command = media_graph_command(
                project,
                "添加媒体片段",
                lambda working: add_video_clip(
                    working,
                    track_id,
                    asset_id,
                    timeline_in_ms=int(getattr(self.page.timeline, "playhead_ms", 0)),
                ),
            )
        except (KeyError, ValueError) as exc:
            QMessageBox.information(self, tr('无法添加片段'), str(exc))
            return
        self.page.undo_stack.push(command)
