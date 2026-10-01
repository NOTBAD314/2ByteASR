"""Motion preset cards and the motion browser dialog."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .effect_dsl import builtin_effects
from .motion_library import MotionPreset, MotionPresetStore
from .studio_style_widgets import StylePreview
from .studio_theme import StudioComboBox, apply_secondary_surface_theme

from .i18n import bind_text

from .i18n import tr

class MotionCard(QFrame):
    activated = Signal(str)
    favorite_changed = Signal(str, bool)
    delete_requested = Signal(str)
    rename_requested = Signal(str)

    def __init__(self, preset: MotionPreset, style, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("motionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(148)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 7)
        layout.setSpacing(5)
        self.preview = StylePreview(self)
        self.preview.setFixedHeight(74)
        self.preview.set_style(style)
        self._preview_effect = builtin_effects()[preset.preview_effect_id]
        self._previewing = False
        layout.addWidget(self.preview)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(preset.name)
        name.setObjectName("motionCardName")
        name_row.addWidget(name, 1)
        badge = QLabel("内置" if preset.system else "自定义")
        badge.setObjectName("motionCardBadge")
        badge.setProperty("builtIn", bool(preset.system))
        name_row.addWidget(badge)
        layout.addLayout(name_row)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        kind = QLabel(preset.describe())
        kind.setObjectName("motionCardType")
        meta_row.addWidget(kind, 1)
        self.favorite = QToolButton()
        self.favorite.setObjectName("motionCardFavorite")
        self.favorite.setText("★" if preset.favorite else "☆")
        (bind_text(self.favorite, '取消收藏', property='toolTip') if preset.favorite else bind_text(self.favorite, '收藏', property='toolTip'))
        self.favorite.clicked.connect(self._toggle_favorite)
        meta_row.addWidget(self.favorite)
        if not preset.system:
            rename = QToolButton()
            rename.setObjectName("motionCardTool")
            rename.setText("✎")
            bind_text(rename, '重命名自建 Motion', property='toolTip')
            rename.clicked.connect(lambda: self.rename_requested.emit(self.preset.id))
            meta_row.addWidget(rename)
            remove = QToolButton()
            remove.setObjectName("motionCardTool")
            remove.setText("×")
            bind_text(remove, '删除自建 Motion', property='toolTip')
            remove.clicked.connect(lambda: self.delete_requested.emit(self.preset.id))
            meta_row.addWidget(remove)
        layout.addLayout(meta_row)

    def _library_preview_effect(self) -> dict:
        effect = copy.deepcopy(self._preview_effect)
        entry = effect.setdefault("entry", {})
        raw = int(entry.get("duration", 180) or 180)
        if raw < 900:
            entry["duration"] = min(1600, max(1100, raw * 5))
        exit_part = effect.setdefault("exit", {})
        exit_raw = int(exit_part.get("duration", 140) or 140)
        if exit_raw < 400:
            exit_part["duration"] = min(700, max(420, exit_raw * 3))
        return effect

    def start_preview(self) -> None:
        if self._previewing:
            return
        self._previewing = True
        self.preview.play_motion(self._library_preview_effect(), loop=True, hold_ms=700)

    def stop_preview(self) -> None:
        self._previewing = False
        self.preview._motion_timer.stop()
        self.preview._motion_clock.invalidate()
        self.preview.update()

    def enterEvent(self, event) -> None:
        self.start_preview()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self.property("selected"):
            self.stop_preview()
        super().leaveEvent(event)

    def _toggle_favorite(self) -> None:
        favorite = self.favorite.text() != "★"
        self.favorite.setText("★" if favorite else "☆")
        self.favorite_changed.emit(self.preset.id, favorite)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QToolButton):
                self.activated.emit(self.preset.id)
                event.accept()
                return
        super().mousePressEvent(event)


class MotionBrowserDialog(QDialog):
    motion_selected = Signal(str)

    FILTERS = (("全部", "all"), ("收藏", "favorite"), ("内置", "builtin"), ("自定义", "custom"))

    def __init__(self, style, parent=None, *, current_motion: Mapping[str, object] | None = None,
                 current_preview_effect_id: str = "soft_fade"):
        super().__init__(parent)
        self.setWindowTitle("Motion Library")
        self.setMinimumSize(900, 650)
        self._style = copy.deepcopy(style)
        self._current_motion = copy.deepcopy(dict(current_motion or {}))
        self._current_preview_effect_id = (
            current_preview_effect_id
            if current_preview_effect_id in builtin_effects()
            else "soft_fade"
        )
        self.store = MotionPresetStore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        heading = QHBoxLayout()
        title = QLabel("Motion Library")
        title.setObjectName("motionLibraryTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.save_current = QPushButton("保存当前 Motion")
        self.save_current.setObjectName("studioButton")
        self.save_current.setEnabled(bool(self._current_motion))
        bind_text(self.save_current, '把当前 Inspector 中的动效（时长 / 缓动 / 延迟 / 参数）保存为可复用 Motion', property='toolTip')
        self.save_current.clicked.connect(self._save_current_motion)
        heading.addWidget(self.save_current)
        self.search = QLineEdit()
        bind_text(self.search, '搜索动效', property='placeholderText')
        self.search.setMaximumWidth(260)
        heading.addWidget(self.search)
        layout.addLayout(heading)
        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for index, (label, value) in enumerate(self.FILTERS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("motionFilter")
            button.setChecked(index == 0)
            button.setProperty("filterKind", value)
            self.filter_group.addButton(button, index)
            filters.addWidget(button)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._populate)
        self.filter_group.idClicked.connect(lambda _id: self._populate())
        apply_secondary_surface_theme(self)
        self._populate()

    def _clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _active_filter(self) -> str:
        button = self.filter_group.checkedButton()
        return str(button.property("filterKind") or "all") if button is not None else "all"

    def _populate(self) -> None:
        self._clear()
        needle = self.search.text().strip().casefold()
        presets = list(self.store.all().values())
        presets.sort(key=lambda preset: (not preset.favorite, not preset.system, preset.name.casefold()))
        kind = self._active_filter()
        def _visible(preset: MotionPreset) -> bool:
            if needle and needle not in preset.name.casefold() and needle not in preset.describe().casefold():
                return False
            if kind == "favorite":
                return preset.favorite
            if kind == "builtin":
                return preset.system
            if kind == "custom":
                return not preset.system
            return True
        visible = [preset for preset in presets if _visible(preset)]
        for index, preset in enumerate(visible):
            card = MotionCard(preset, self._style)
            card.activated.connect(self._select)
            card.favorite_changed.connect(self._favorite)
            card.delete_requested.connect(self._delete)
            card.rename_requested.connect(self._rename)
            self.grid.addWidget(card, index // 3, index % 3)
        self.grid.setRowStretch((len(visible) + 2) // 3, 1)

    def _select(self, preset_id: str) -> None:
        self.motion_selected.emit(preset_id)
        self.accept()

    def _favorite(self, preset_id: str, favorite: bool) -> None:
        self.store.set_favorite(preset_id, favorite)
        self._populate()

    def _delete(self, preset_id: str) -> None:
        try:
            self.store.delete(preset_id)
        except ValueError:
            return
        self._populate()

    def _rename(self, preset_id: str) -> None:
        preset = self.store.all().get(preset_id)
        if preset is None or preset.system:
            return
        dialog = QDialog(self)
        bind_text(dialog, '重命名 Motion', property='windowTitle')
        dialog.setMinimumWidth(420)
        apply_secondary_surface_theme(dialog)
        form = QVBoxLayout(dialog)
        form.setContentsMargins(18, 14, 18, 12)
        form.setSpacing(8)
        name_edit = QLineEdit(preset.name)
        description_edit = QLineEdit(preset.description)
        bind_text(description_edit, '可选描述', property='placeholderText')
        form.addWidget(QLabel("名称"))
        form.addWidget(name_edit)
        form.addWidget(QLabel("描述"))
        form.addWidget(description_edit)
        row = QHBoxLayout()
        ok = QPushButton("保存")
        ok.clicked.connect(dialog.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dialog.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addLayout(row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return
        try:
            self.store.rename(preset_id, name, description_edit.text().strip())
        except (ValueError, KeyError):
            return
        self._populate()

    def _save_current_motion(self) -> None:
        """Capture the live motion config (entry/hold/exit with all params)
        into a custom preset that survives restarts."""
        if not self._current_motion:
            return
        values = self._run_motion_save_form()
        if values is None:
            return
        name, description, category, favorite = values
        if not name:
            return
        import datetime as _datetime

        identifier = "user-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
        self.store.upsert(MotionPreset(
            identifier,
            name,
            copy.deepcopy(self._current_motion),
            preview_effect_id=self._current_preview_effect_id,
            system=False,
            favorite=favorite,
            description=description,
            category=category,
            created_at=_datetime.datetime.now().isoformat(timespec="seconds"),
        ))
        self._populate()

    def _run_motion_save_form(self) -> tuple[str, str, str, bool] | None:
        """Modal name/description/category form; None when cancelled.

        Split out so tests can inject values without driving the offscreen
        modal event loop (dialog.exec would block forever there).
        """
        dialog = QDialog(self)
        bind_text(dialog, '保存当前 Motion', property='windowTitle')
        dialog.setMinimumWidth(460)
        apply_secondary_surface_theme(dialog)
        form = QGridLayout(dialog)
        form.setContentsMargins(18, 14, 18, 12)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        name_edit = QLineEdit()
        bind_text(name_edit, 'Motion 名称（必填）', property='placeholderText')
        description_edit = QLineEdit()
        bind_text(description_edit, '可选描述', property='placeholderText')
        category_edit = StudioComboBox()
        category_edit.setEditable(True)
        for item in ("通用", "游戏", "柔和", "强调", "故障"):
            category_edit.addItem(item)
        favorite_box = QCheckBox("收藏")
        entrance = self._current_motion.get("entrance", {})
        entrance_type = str((entrance or {}).get("type", "动效")) if isinstance(entrance, Mapping) else "动效"
        summary = bind_text(QLabel(), '来源：{entrance_type} · 入场 {value1}ms', entrance_type=entrance_type, value1=(entrance or {}).get('duration_ms', (entrance or {}).get('duration', '-')))
        summary.setObjectName("cardMeta")
        form.addWidget(QLabel("名称"), 0, 0)
        form.addWidget(name_edit, 0, 1)
        form.addWidget(QLabel("描述"), 1, 0)
        form.addWidget(description_edit, 1, 1)
        form.addWidget(QLabel("分类"), 2, 0)
        form.addWidget(category_edit, 2, 1)
        form.addWidget(favorite_box, 3, 1, Qt.AlignmentFlag.AlignLeft)
        form.addWidget(summary, 4, 0, 1, 2)
        row = QHBoxLayout()
        save = QPushButton("保存")
        save.clicked.connect(dialog.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dialog.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        form.addLayout(row, 5, 0, 1, 2)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return name_edit.text().strip(), description_edit.text().strip(), category_edit.currentText().strip(), favorite_box.isChecked()
