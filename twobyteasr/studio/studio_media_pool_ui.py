"""Searchable Media Pool and multi-track controls for Subtitle Studio."""

from __future__ import annotations

from pathlib import Path
import threading
from collections import OrderedDict

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel, QTimer, QSettings
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QSlider,
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

from ..timeline.studio_media_commands import media_graph_command, media_pool_import_command
from ..timeline.studio_media_pool import (
    add_video_clip,
    create_video_track,
    media_usage,
    primary_video_track_id,
    add_media_asset,
    relink_media_asset,
    remove_unused_media,
)
from ..design.themed_icons import themed_icon
from .media_pool_view import MediaPoolModel, MediaPoolView
from .studio_helpers import probe_media_identity

from ..i18n import bind_text

from ..i18n import tr


MEDIA_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.webm *.flv *.avi *.gif *.wav *.mp3 "
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

    metadata_ready = Signal(object)

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        self.page = page
        self.setAcceptDrops(True)
        self.view_settings = QSettings('2ByteASR', '2ByteASR')
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

        self.model = MediaPoolModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterRole(Qt.ItemDataRole.UserRole+3)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        modes = QHBoxLayout()
        self.list_button = self._button('fa5s.list', '列表', lambda: self._presentation(False))
        self.thumbnail_button = self._button('fa5s.th-large', '缩略图', lambda: self._presentation(True))
        for button in (self.list_button, self.thumbnail_button):
            button.setCheckable(True); modes.addWidget(button)
        self.thumbnail_size = QSlider(Qt.Orientation.Horizontal)
        self.thumbnail_size.setRange(132, 240); self.thumbnail_size.setValue(172)
        self.thumbnail_size.setToolTip('缩略图大小；列数随面板宽度变化')
        self.thumbnail_size.valueChanged.connect(lambda *_: self._presentation(self.assets.thumbnail_mode))
        modes.addWidget(self.thumbnail_size, 1)
        layout.addLayout(modes)
        self.assets = MediaPoolView(page, page.source_monitor.wave_cache)
        self.assets.setModel(self.proxy)
        self.assets.selectionModel().currentChanged.connect(lambda *_: self._sync_actions())
        self.assets.doubleClicked.connect(self._open_selected)
        self.assets.visible_assets.connect(self._queue_visible)
        layout.addWidget(self.assets, 1)
        self._bound_project = None
        self._epoch = 0
        self._jobs = OrderedDict()
        self._probed = set()
        self._condition = threading.Condition()
        self._closed = False
        self.metadata_ready.connect(self._metadata_ready)
        self._worker = threading.Thread(target=self._metadata_work, name='pool-metadata', daemon=True)
        self._worker.start()

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
        # Placement controls live next to the source range. Keep these legacy
        # selectors available to existing track commands without two targets
        # competing for the user's attention.
        divider.hide(); self.track_selector.hide(); self.add_track_button.hide()

        self.add_to_track_button = QPushButton("打开源预览 / 选择片段")
        self.add_to_track_button.setObjectName("studioPrimary")
        self.add_to_track_button.setIcon(themed_icon("fa5s.arrow-right", "primary"))
        self.add_to_track_button.clicked.connect(self._open_selected)
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
        if project is not self._bound_project:
            self._bound_project = project
            self._epoch += 1
            self._probed.clear()
            with self._condition:
                self._jobs.clear()
            if self.page.source_monitor.project is not None and self.page.source_monitor.project is not project:
                self.page.source_monitor.reset()
                self.page.source_tabs.setCurrentIndex(0)
            prefs = project.studio_state.get('media_pool_view', {}) if project else {}
            self.thumbnail_size.blockSignals(True)
            try:
                size = int(prefs.get('size', self.view_settings.value('studio/media_pool_thumb_size', 172)))
            except (ValueError, TypeError):
                size = 172
            self.thumbnail_size.setValue(size)
            self.thumbnail_size.blockSignals(False)
            mode = prefs.get('mode', self.view_settings.value('studio/media_pool_view', 'thumbnails'))
            self.assets.set_presentation(mode == 'thumbnails', self.thumbnail_size.value())
        self.model.refresh(project)
        monitor = self.page.source_monitor
        if monitor.project is project and monitor.asset_id and monitor.asset is None:
            monitor.close_source()
        if monitor.asset is not None and monitor.source_path_at_open != monitor.asset.canonical_source:
            if monitor.isVisible():
                monitor.open_asset(monitor.asset_id)
            else:
                monitor.reset()
        if selected_asset_id:
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 0)
                if index.data(Qt.ItemDataRole.UserRole) == selected_asset_id:
                    self.assets.setCurrentIndex(index); break
        self.track_selector.blockSignals(True)
        self.track_selector.clear()
        if project is None:
            bind_text(self.asset_count, '0 个素材')
            self.track_selector.blockSignals(False)
            self._sync_actions()
            return
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
        self.list_button.setChecked(not self.assets.thumbnail_mode)
        self.thumbnail_button.setChecked(self.assets.thumbnail_mode)
        self.thumbnail_size.setEnabled(self.assets.thumbnail_mode)
        self.page.source_monitor.refresh_targets()
        self._sync_actions()

    def selected_asset_id(self) -> str:
        return str(self.assets.currentIndex().data(Qt.ItemDataRole.UserRole) or '')

    def selected_track_id(self) -> str:
        return str(self.track_selector.currentData() or "")

    def select_track(self, track_id: str) -> None:
        index = self.track_selector.findData(str(track_id))
        if index >= 0:
            self.track_selector.setCurrentIndex(index)
        source_index = self.page.source_monitor.video_target.findData(str(track_id))
        if source_index >= 0:
            self.page.source_monitor.video_target.setCurrentIndex(source_index)

    def _apply_filter(self, query: str) -> None:
        selected = self.selected_asset_id()
        if selected:
            self._last_selected = selected
        self.proxy.setFilterFixedString(str(query or '').strip())
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(Qt.ItemDataRole.UserRole) == getattr(self, '_last_selected', ''):
                self.assets.setCurrentIndex(index); break
        self.assets.timer.start()
        self._sync_actions()

    def _sync_actions(self) -> None:
        project = self.page.project
        asset_id = self.selected_asset_id()
        track_id = self.selected_track_id()
        track = next(
            (item for item in project.video_tracks if item.id == track_id),
            None,
        ) if project else None
        self.relink_button.setEnabled(bool(project and asset_id))
        self.add_to_track_button.setEnabled(bool(project and asset_id))
        self.add_to_track_button.setToolTip('双击或点击打开源预览；设置入出点后选择音视频方式加入')
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
        paths, _selected = QFileDialog.getOpenFileNames(self, tr('添加素材'), '', MEDIA_FILTER)
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        if self.page.project is None:
            return
        self.add_asset_button.setEnabled(False)
        self.preview_contract.setText('正在后台读取素材信息…')
        with self._condition:
            key = ('import', self._epoch, tuple(str(p) for p in paths))
            self._jobs[key] = (self._epoch, self.page.project, '', tuple(str(p) for p in paths))
            self._jobs.move_to_end(key, last=False)
            self._condition.notify_all()

    @staticmethod
    def external_media_paths(mime):
        from ..design.studio_theme import STUDIO_MEDIA_SUFFIXES
        return tuple(dict.fromkeys(url.toLocalFile() for url in mime.urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in STUDIO_MEDIA_SUFFIXES))

    def dragEnterEvent(self, event):
        if self.page.project is not None and self.external_media_paths(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self.external_media_paths(event.mimeData())
        if self.page.project is None or not paths:
            event.ignore()
            return
        self.import_paths(paths)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

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

    def _add_selected_to_track(self):
        self._open_selected()

    def _open_selected(self, *_):
        asset_id = self.selected_asset_id()
        if self.page.project is None or not asset_id:
            return
        self.page._set_major_panel_visible('cue_list', True)
        self.page.source_tabs.setCurrentIndex(1)
        self.page.source_monitor.open_asset(asset_id)
        name = next(a.display_name for a in self.page.project.media_pool if a.asset_id == asset_id)
        self.page.source_tabs.setTabText(1, '源：'+(name[:10]+'…' if len(name)>10 else name))
        self.page.source_tabs.setTabToolTip(1, name)
        self.page.source_monitor.setFocus()

    def _presentation(self, thumbnails):
        self.assets.set_presentation(thumbnails, self.thumbnail_size.value())
        self.list_button.setChecked(not thumbnails); self.thumbnail_button.setChecked(thumbnails)
        self.thumbnail_size.setEnabled(thumbnails)
        self.view_settings.setValue('studio/media_pool_view', 'thumbnails' if thumbnails else 'list')
        self.view_settings.setValue('studio/media_pool_thumb_size', self.thumbnail_size.value())
        if self.page.project:
            self.page.project.studio_state['media_pool_view'] = dict(mode='thumbnails' if thumbnails else 'list', size=self.thumbnail_size.value())

    def _queue_visible(self, assets):
        project = self.page.project
        if project is None:
            return
        with self._condition:
            for asset in assets:
                key = (self._epoch, asset.asset_id, asset.canonical_source)
                if key not in self._probed and not asset.offline:
                    self._probed.add(key)
                    self._jobs[key] = (self._epoch, project, asset.asset_id, (asset.canonical_source,))
                    self._jobs.move_to_end(key, last=False)
            probes = [key for key in self._jobs if key[0] != 'import']
            for key in probes[24:]:
                self._jobs.pop(key, None); self._probed.discard(key)
            self._condition.notify_all()

    def _metadata_work(self):
        while True:
            with self._condition:
                while not self._jobs and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                _, (epoch, project, asset_id, paths) = self._jobs.popitem(last=False)
            results = []
            for path in paths:
                if self._closed or epoch != self._epoch:
                    break
                try:
                    results.append((path, probe_media_identity(path), ''))
                except Exception as exc:
                    results.append((path, {}, str(exc)))
            try:
                self.metadata_ready.emit((epoch, project, asset_id, results))
            except RuntimeError:
                return

    @staticmethod
    def _metadata_dicts(identity):
        return (dict(width=identity.get('width', 0), height=identity.get('height', 0),
                     fps=identity.get('fps', 0), has_video=bool(identity.get('has_video'))),
                dict(has_audio=bool(identity.get('has_audio')), streams=list(identity.get('audio_streams', [])),
                     sample_rate=identity.get('sample_rate', 0), channels=identity.get('channels', 0), stream_index=0,
                     source_start_ms=identity.get('source_start_ms', 0),
                     sample_timeline_origin_ms=identity.get('sample_timeline_origin_ms', 0)))

    def _metadata_ready(self, payload):
        epoch, project, asset_id, results = payload
        if self._closed or epoch != self._epoch or self.page.project is not project:
            self.add_asset_button.setEnabled(True)
            return
        if not asset_id:
            self.add_asset_button.setEnabled(True)
            def add(working):
                for path, identity, error in results:
                    if error:
                        continue
                    video, audio = self._metadata_dicts(identity)
                    add_media_asset(working, path, fingerprint=str(identity.get('fingerprint') or ''),
                        duration_ms=int(identity.get('duration_ms') or 0), video_metadata=video,
                        audio_metadata=audio, materialize_audio=False)
            if any(not error for _, _, error in results):
                command=media_pool_import_command(project, add)
                if command is not None:self.page.undo_stack.push(command)
            errors = [str(Path(path).name)+': '+error for path, _, error in results if error]
            self.preview_contract.setText('；'.join(errors) if errors else f'已添加 {len(results)} 个素材；双击预览，拖动选段加入')
        elif results:
            path, identity, error = results[0]
            asset = next((a for a in project.media_pool if a.asset_id == asset_id and a.canonical_source == path), None)
            if asset and not error:
                from ..projects.studio_runtime_state import state_for, DirtyDomain as D
                video, audio = self._metadata_dicts(identity)
                changed = (any(asset.video_metadata.get(k) != v for k, v in video.items()) or
                           any(asset.audio_metadata.get(k) != v for k, v in audio.items()))
                if changed:
                    with state_for(project).transaction(project, action_id='source_metadata', dirty=D.MEDIA_POOL | D.AUTOSAVE):
                        asset.video_metadata.update(video); asset.audio_metadata.update(audio)
                        asset.duration_ms = int(identity.get('duration_ms') or asset.duration_ms)
                if self.page.source_monitor.asset_id == asset_id:
                    # Enrich stream choices without moving either playhead.
                    self.page.source_monitor.refresh_metadata()
            elif asset and error:
                self.preview_contract.setText('素材信息读取失败：'+error+'；可重新定位')
        self.refresh(project)
        self.assets.timer.start()

    def shutdown(self):
        self._closed = True; self._epoch += 1
        with self._condition:
            self._jobs.clear(); self._condition.notify_all()
        self.assets.shutdown()
