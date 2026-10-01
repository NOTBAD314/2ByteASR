"""Project-owned popup combo subsystem for the Main UI."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QParallelAnimationGroup,
    QPropertyAnimation, QRect, QSize, Qt,
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .main_ui_branding import _icon
from .ui_motion import MOTION_STANDARD_MS, motion_duration

from .i18n import bind_text


# Private registry: ensure at most one project popup is open at any time.
_active_combo_popup: "_ComboPopup | None" = None


class _ComboPopup(QFrame):
    """Project-owned popup; never creates Qt's black private combo container.

    Rules (per user spec):
    - Click same trigger → toggle (close if open)
    - Click outside popup → close
    - Click another trigger → close current first (no re-animate of old), then open new
    - Never replay the open animation for the same popup while it is already showing
    - Only one popup of this kind open globally
    """

    def __init__(self, combo):
        super().__init__(
            combo,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.combo = combo
        self.setObjectName("comboPopupWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.listing = QListWidget(self)
        self.listing.setObjectName("comboPopupList")
        self.listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.listing.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.listing.verticalScrollBar().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self.listing)
        self.listing.itemClicked.connect(self._choose_item)
        self.listing.itemActivated.connect(self._choose_item)
        self._animation = None
        self._outside_filter_installed = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        global _active_combo_popup
        if _active_combo_popup is self:
            _active_combo_popup = None
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        # Close when user clicks anywhere outside the popup.
        # IMPORTANT: Do NOT swallow the click. If user clicked another combo trigger,
        # we must let the event propagate so that trigger can open its own popup.
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                gp = event.globalPos()
            popup_rect = self.geometry()
            if not popup_rect.contains(self.mapFromGlobal(gp)):
                # If the press is on our owning combo's rect, set a one-shot suppression
                # so that the same press does not cause an immediate re-open.
                try:
                    cgeo = self.combo.geometry()
                    combo_global = QRect(self.combo.mapToGlobal(cgeo.topLeft()), cgeo.size())
                except Exception:
                    combo_global = QRect()
                if combo_global.contains(gp):
                    try:
                        self.combo._suppress_show_until_click_release = True
                    except Exception:
                        pass
                # Hide without consuming the event → other widgets (e.g., another combo) can react.
                self.hide()
                # return False to let Qt deliver the press to the target widget.
                return False
        return super().eventFilter(obj, event)

    def _apply_mask(self):
        self.clearMask()

    def _choose_item(self, item):
        index = int(item.data(Qt.ItemDataRole.UserRole))
        self.combo.setCurrentIndex(index)
        self.combo.activated.emit(index)
        self.combo.textActivated.emit(self.combo.itemText(index))
        self.hide()

    def rebuild(self):
        self.listing.clear()
        model = self.combo.model()
        for index in range(self.combo.count()):
            item = QListWidgetItem(
                self.combo.itemIcon(index),
                self.combo.itemText(index),
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            model_index = model.index(index, self.combo.modelColumn())
            if not model.flags(model_index) & Qt.ItemFlag.ItemIsEnabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setSizeHint(QSize(0, 40))
            self.listing.addItem(item)
        self.listing.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if self.combo.count() <= self.combo.maxVisibleItems()
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        if self.combo.currentIndex() >= 0:
            self.listing.setCurrentRow(self.combo.currentIndex())

    def _target_geometry(self):
        screen = self.combo.screen().availableGeometry()
        metrics = self.combo.fontMetrics()
        content_width = max(
            (metrics.horizontalAdvance(self.combo.itemText(i)) for i in range(self.combo.count())),
            default=0,
        )
        width = min(max(self.combo.width(), content_width + 64), screen.width() - 20)
        visible = min(max(1, self.combo.maxVisibleItems()), max(1, self.combo.count()))
        height = min(visible * 40 + 10, screen.height() - 20)
        below = self.combo.mapToGlobal(self.combo.rect().bottomLeft()) + QPointF(0, 5).toPoint()
        x = min(max(screen.left() + 5, below.x()), screen.right() - width - 5)
        y = below.y()
        if y + height > screen.bottom() - 5:
            above = self.combo.mapToGlobal(self.combo.rect().topLeft()).y() - height - 5
            y = max(screen.top() + 5, above)
        return QRect(x, y, width, height)

    def _stop_animation(self):
        if self._animation is not None:
            try:
                self._animation.stop()
            except Exception:
                pass
            self._animation = None

    def _immediate_hide(self):
        """Hide without playing any close animation; used when another trigger takes over."""
        self._stop_animation()
        self.hide()

    def hide(self):
        # Ensure animation is stopped and global registry is cleared on any hide path.
        self._stop_animation()
        global _active_combo_popup
        if _active_combo_popup is self:
            _active_combo_popup = None
        app = QApplication.instance()
        if app is not None and self._outside_filter_installed:
            app.removeEventFilter(self)
            self._outside_filter_installed = False
        super().hide()

    def show_animated(self):
        global _active_combo_popup
        # If a different popup is currently active, close it immediately (no re-animate of the old one).
        if _active_combo_popup is not None and _active_combo_popup is not self:
            try:
                if _active_combo_popup.isVisible():
                    _active_combo_popup._immediate_hide()
            except Exception:
                pass
            _active_combo_popup = None

        # Guard: if THIS popup is already visible, do not replay the open animation.
        if self.isVisible():
            # Ensure it is on top and focused, but do not restart geometry/opacity animation.
            try:
                self.raise_()
                self.listing.setFocus(Qt.FocusReason.PopupFocusReason)
            except Exception:
                pass
            _active_combo_popup = self
            return

        self.rebuild()
        if not self.listing.count():
            return
        app = QApplication.instance()
        if app is not None and not self._outside_filter_installed:
            app.installEventFilter(self)
            self._outside_filter_installed = True
        final_rect = self._target_geometry()
        duration = motion_duration(MOTION_STANDARD_MS)
        start_rect = QRect(final_rect).translated(0, 6) if duration else final_rect
        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0 if duration else 1.0)
        self.show()
        self.setVisible(True)
        self.raise_()
        self.listing.setFocus(Qt.FocusReason.PopupFocusReason)
        _active_combo_popup = self
        if duration:
            group = QParallelAnimationGroup(self)
            geometry = QPropertyAnimation(self, b"geometry", group)
            geometry.setStartValue(start_rect)
            geometry.setEndValue(final_rect)
            opacity = QPropertyAnimation(self, b"windowOpacity", group)
            opacity.setStartValue(0.0)
            opacity.setEndValue(1.0)
            for animation in (geometry, opacity):
                animation.setDuration(duration)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.finished.connect(lambda: setattr(self, "_animation", None))
            self._animation = group
            group.start()


class FramelessPopupCombo(QComboBox):
    """Combo box backed by the project-owned rounded popup.

    Toggle/close semantics:
    - Click trigger while closed → open (animated once)
    - Click trigger while open → close (no re-animate)
    - Click outside → close (handled by popup's eventFilter)
    - Click another trigger → previous is closed immediately without animation replay
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup = _ComboPopup(self)
        self._suppress_show_until_click_release = False
        # 2026-09-17：selectedFirst 只在每个 widget 生命周期内生效一次（首次
        # 打开置顶）；此后列表保持稳定，点击/换项不再改变行位置。最近使用
        # 的置顶在下次构建（重开页面/重启）时随选中恢复自然出现。
        self._selected_first_applied = False

    def setEditable(self, editable):
        previous = self.lineEdit()
        if previous is not None:
            previous.removeEventFilter(self)
        super().setEditable(editable)
        editor = self.lineEdit()
        if editable and editor is not None:
            editor.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            watched is self.lineEdit()
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and self.count()
        ):
            self.showPopup()
        return super().eventFilter(watched, event)

    def showPopup(self):
        # If a suppression flag was set by the popup's outside-click filter
        # (user clicked on THIS combo's rect while it was open), eat this show.
        if getattr(self, "_suppress_show_until_click_release", False):
            self._suppress_show_until_click_release = False
            return
        if self._popup.isVisible():
            self._popup.hide()
            return
        # 四十轮：selectedFirst——模型/服务商长列表打开时当前选中项置于第一行，
        # 用户不必滚动寻找（用户实录："点开后就应该是在第一行第一个"）。
        # 2026-09-17 改为一次性：仅首次打开置顶；会话内点击模型后列表不再
        # 跳行（用户反馈"点击以后立即跑到第一行"打断配置）。
        if self.property("selectedFirst") and not self._selected_first_applied:
            self._selected_first_applied = True
            self._move_current_to_front()
            try:
                from .runtime_trace import GLOBAL_STUDIO_TRACE
                GLOBAL_STUDIO_TRACE.emit("ASRModelOrder", {
                    "selected": self.currentText(),
                    "last_used_saved": True,
                    "session_reorder": False,
                    "note": "pinned-once-per-widget",
                })
            except Exception:
                pass
        self._popup.show_animated()

    def _move_current_to_front(self):
        index = self.currentIndex()
        if index <= 0:
            return
        self.blockSignals(True)
        try:
            icon = self.itemIcon(index)
            text = self.itemText(index)
            data = self.itemData(index)
            self.removeItem(index)
            self.insertItem(0, icon, text, data)
            self.setCurrentIndex(0)
        finally:
            self.blockSignals(False)

    def hidePopup(self):
        self._popup.hide()

    def mouseReleaseEvent(self, event):
        # Clear any one-shot suppression on release so next independent click works.
        if getattr(self, "_suppress_show_until_click_release", False):
            self._suppress_show_until_click_release = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # 页面滚动时，鼠标悬停在下拉框上不应误改语言、人数、覆盖策略或模型。
        # 选项只允许通过点击弹层修改；忽略后父级滚动区域仍可接管滚轮。
        event.ignore()


class EditableHistoryCombo(FramelessPopupCombo):
    """Editable combo with an explicit, reliable history dropdown affordance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(9)
        self.setMinimumHeight(42)
        self.lineEdit().setClearButtonEnabled(True)
        self._history_action = self.lineEdit().addAction(
            _icon("fa5s.chevron-down", "#5f625c"),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        bind_text(self._history_action, '展开历史记录与内置游戏', property='toolTip')
        self._history_action.triggered.connect(self.showPopup)
        self.setStyleSheet("QComboBox::drop-down { width: 0px; border: 0; }")

    def setPlaceholderText(self, text: str):
        self.lineEdit().setPlaceholderText(text)
