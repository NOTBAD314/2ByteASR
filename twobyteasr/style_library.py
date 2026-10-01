"""User-facing library for complete subtitle style recipes."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .style_presets import BUILTIN_PRESETS, StylePresetStore
from .style_recipe import StyleRecipe
from .studio_theme import apply_secondary_surface_theme

from .i18n import bind_text

from .i18n import tr


class StyleLibraryDialog(QDialog):
    styleSelected = Signal(str)

    def __init__(self, parent=None, *, store: StylePresetStore | None = None) -> None:
        super().__init__(parent)
        self.store = store or StylePresetStore()
        self.setObjectName("toolDialog")
        self.setWindowTitle("Style Library")
        self.setMinimumSize(620, 520)
        self.resize(720, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        title = QLabel("Style Library")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("styleLibraryTabs")
        outer.addWidget(self.tabs, 1)
        self.lists: dict[str, QListWidget] = {}
        for key, label in (
            ("builtin", "内置"), ("favorite", "收藏"),
            ("custom", "自定义"), ("ai", "AI 生成"),
        ):
            listing = QListWidget()
            listing.setObjectName("styleLibraryList")
            listing.setSpacing(6)
            listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.tabs.addTab(listing, label)
            self.lists[key] = listing
        manage = QHBoxLayout()
        self.keep_favorites = QCheckBox("删除全部 AI 时保留收藏")
        self.keep_favorites.setChecked(True)
        manage.addWidget(self.keep_favorites)
        manage.addStretch(1)
        delete_selected = QPushButton("删除选中")
        delete_selected.setObjectName("studioButton")
        delete_selected.clicked.connect(self._delete_selected)
        delete_all_ai = QPushButton("删除全部 AI")
        delete_all_ai.setObjectName("studioButton")
        delete_all_ai.clicked.connect(self._delete_all_ai)
        manage.addWidget(delete_selected)
        manage.addWidget(delete_all_ai)
        restore_builtins = QPushButton("恢复内置")
        restore_builtins.setObjectName("studioButton")
        restore_builtins.clicked.connect(self._restore_builtins)
        manage.addWidget(restore_builtins)
        outer.addLayout(manage)
        self.reload()
        apply_secondary_surface_theme(self)

    def reload(self) -> None:
        for listing in self.lists.values():
            listing.clear()
        styles = self.store.all()
        recipes = self.store.load_recipes()
        metadata = self.store.load_metadata()
        builtin_ids = [style_id for style_id in BUILTIN_PRESETS if style_id in styles]
        user_ids = [style_id for style_id in styles if style_id not in BUILTIN_PRESETS]
        ai_ids = sorted(
            (style_id for style_id in user_ids if str(metadata.get(style_id, {}).get("source") or "") == "ai"),
            key=lambda style_id: str(metadata.get(style_id, {}).get("created_at") or ""),
            reverse=True,
        )
        custom_ids = sorted(
            (style_id for style_id in user_ids if style_id not in ai_ids),
            key=lambda style_id: styles[style_id].name.casefold(),
        )
        for style_id in [*builtin_ids, *custom_ids, *ai_ids]:
            style = styles[style_id]
            if style_id in BUILTIN_PRESETS:
                categories = ("builtin",)
            else:
                meta = metadata.get(style_id, {})
                source = str(meta.get("source") or ("ai" if style_id.startswith("ai-") else "custom"))
                categories = ("ai" if source == "ai" else "custom",)
                if bool(meta.get("favorite", False)):
                    categories += ("favorite",)
            for category in categories:
                self._add_card(self.lists[category], style_id, style, recipes.get(style_id), metadata.get(style_id, {}))
        for category, listing in self.lists.items():
            if listing.count() == 0:
                item = QListWidgetItem("此分类暂时为空")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                listing.addItem(item)

    def _add_card(self, listing, style_id, style, recipe_payload, metadata) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, style_id)
        card = QWidget()
        card.setObjectName("styleLibraryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        name = QLabel(style.name)
        name.setObjectName("styleLibraryName")
        head.addWidget(name, 1)
        recipe = None
        if isinstance(recipe_payload, dict):
            try:
                recipe = StyleRecipe.from_dict(recipe_payload)
            except (TypeError, ValueError):
                recipe = None
        if recipe is not None and recipe.motion:
            head.addWidget(self._badge("Motion"))
        if recipe is not None and recipe.ass.enabled:
            head.addWidget(self._badge("ASS"))
        layout.addLayout(head)
        preview = QLabel("示例字幕 Aa 123")
        preview.setObjectName("styleLibraryPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(54)
        preview.setStyleSheet(
            f"background:#343a38;color:{style.primary_color};border:1px solid #5e6963;"
            f"border-radius:5px;font-family:'{style.font_family}';font-size:18px;font-weight:{700 if style.bold else 500};"
        )
        layout.addWidget(preview)
        actions = QHBoxLayout()
        apply = QPushButton("应用")
        apply.setObjectName("studioPrimary")
        apply.clicked.connect(lambda _checked=False, value=style_id: self.styleSelected.emit(value))
        actions.addWidget(apply)
        if style_id not in BUILTIN_PRESETS:
            favorite = QPushButton("取消收藏" if metadata.get("favorite") else "收藏")
            favorite.setObjectName("studioButton")
            favorite.clicked.connect(lambda _checked=False, value=style_id, state=not bool(metadata.get("favorite")): self._favorite(value, state))
            rename = QPushButton("重命名")
            rename.setObjectName("studioButton")
            rename.clicked.connect(lambda _checked=False, value=style_id, old=style.name: self._rename(value, old))
            delete = QPushButton("删除")
            delete.setObjectName("studioButton")
            delete.clicked.connect(lambda _checked=False, value=style_id: self._delete(value))
            for button in (favorite, rename, delete):
                actions.addWidget(button)
        else:
            delete = QPushButton("删除")
            delete.setObjectName("studioButton")
            bind_text(delete, '从预设库隐藏，不会删除安装包资源', property='toolTip')
            delete.clicked.connect(lambda _checked=False, value=style_id: self._delete(value))
            actions.addWidget(delete)
        actions.addStretch(1)
        for button in card.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addLayout(actions)
        item.setSizeHint(QSize(0, card.sizeHint().height()))
        listing.addItem(item)
        listing.setItemWidget(item, card)

    @staticmethod
    def _badge(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("motionCardBadge")
        return label

    def _favorite(self, style_id: str, favorite: bool) -> None:
        self.store.set_favorite(style_id, favorite)
        self.reload()

    def _rename(self, style_id: str, old_name: str) -> None:
        name, accepted = QInputDialog.getText(self, tr('重命名样式'), tr('名称'), text=old_name)
        if not accepted or not name.strip():
            return
        style = self.store.load_user().get(style_id)
        if style is None:
            return
        style.name = name.strip()
        metadata = self.store.load_metadata().get(style_id, {})
        self.store.upsert(style, self.store.load_recipes().get(style_id), source=str(metadata.get("source") or "custom"))
        self.reload()

    def _delete(self, style_id: str) -> None:
        builtin = style_id in BUILTIN_PRESETS
        answer = QMessageBox.question(
            self,
            tr('删除样式'),
            (tr('确定隐藏这个内置样式？之后可用“恢复内置”找回。') if builtin else tr('确定删除这个自定义样式？')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete(style_id)
            self.reload()

    def _restore_builtins(self) -> None:
        restored = self.store.restore_builtins()
        self.reload()
        if not restored:
            QMessageBox.information(self, tr('恢复内置'), tr('当前没有被隐藏的内置预设。'))

    def _selected_ids(self) -> list[str]:
        selected: list[str] = []
        for listing in self.lists.values():
            for item in listing.selectedItems():
                style_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
                if style_id and style_id not in selected:
                    selected.append(style_id)
        return selected

    def _delete_selected(self) -> None:
        selected = self._selected_ids()
        if not selected:
            QMessageBox.information(self, tr('删除样式'), tr('请先选择一个或多个样式。'))
            return
        answer = QMessageBox.question(
            self,
            tr('删除选中样式'),
            tr('确定删除选中的 {value0} 个样式？内置样式不会受影响。', value0=len(selected)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_many(selected)
            self.reload()

    def _delete_all_ai(self) -> None:
        keep = self.keep_favorites.isChecked()
        answer = QMessageBox.question(
            self,
            tr('删除全部 AI 样式'),
            (tr('确定删除全部未收藏的 AI 样式？') if keep else tr('确定删除全部 AI 样式（包括收藏）？')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_all_ai(keep_favorites=keep)
            self.reload()


__all__ = ["StyleLibraryDialog"]
