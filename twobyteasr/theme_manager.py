"""Runtime application theme registry and Qt palette/QSS application."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .ui_theme import DEFAULT_THEME_KEY, THEMES, ThemeDefinition, theme_definition


def _trace_mark(label: str, start: float | None = None) -> float:
    """Optional phase timer for theme apply (TWOBYTEASR_THEME_TRACE=1)."""
    now = time.perf_counter()
    if os.environ.get("TWOBYTEASR_THEME_TRACE") == "1":
        elapsed = f"{now - start:.3f}s" if start is not None else "0"
        print(f"[theme-trace] {label}: {elapsed}", flush=True)
    return now


SETTINGS_ORG = "2ByteASR"
SETTINGS_APP = "2ByteASR"
_volatile_theme_keys: dict[str, str] = {}


class _ThemeRootFilter(QObject):
    """Theme new independent windows before their first paint."""

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.ParentChange and isinstance(widget, QWidget):
            if widget.parentWidget() is not None and not widget.isWindow():
                previous = getattr(widget, "_theme_root_sheet", None)
                if previous is not None:
                    # Controls may be polished while temporarily parentless
                    # (notably lazy font selectors). Once adopted, inherit the
                    # owning window instead of retaining a frozen root theme.
                    if widget.styleSheet() == previous:
                        widget.setStyleSheet(getattr(widget, "_theme_root_local_sheet", ""))
                    del widget._theme_root_sheet
                    widget._theme_root_local_sheet = ""
        if event.type() == QEvent.Type.Show and isinstance(widget, QWidget):
            if getattr(widget, "_secondary_theme_surface", False):
                from .studio_theme import refresh_secondary_surface_theme
                refresh_secondary_surface_theme(widget)
            pending = getattr(widget, "_theme_refresh_pending", False)
            if pending:
                widget._theme_refresh_pending = False
                if widget.objectName() == "subtitleStudio":
                    from .studio_theme import build_studio_qss
                    widget.setStyleSheet(build_studio_qss(theme_definition(theme_key())))
                    widget._set_hub_toolbar_mode(getattr(widget, "_project_view_state", "") == "hub")
                refresh = getattr(widget, "refresh_theme_palette", None)
                if callable(refresh):
                    refresh()
        # Many controls are constructed parentless and adopted immediately.
        # Polishing them with the entire application sheet, then stripping it
        # on ParentChange, cost hundreds of redundant native style passes.
        # Show still precedes first paint, when window ownership is settled.
        if event.type() == QEvent.Type.Show and isinstance(widget, QWidget):
            if widget.parentWidget() is None and widget.objectName() != "subtitleStudio":
                self.apply_root(widget)
        return False

    def apply_root(self, widget):
        sheet = getattr(self.parent(), "_theme_window_qss", "")
        if not sheet or getattr(widget, "_theme_root_busy", False):
            return
        previous = getattr(widget, "_theme_root_sheet", None)
        current = widget.styleSheet()
        if current != previous:
            widget._theme_root_local_sheet = current
        combined = sheet + getattr(widget, "_theme_root_local_sheet", "")
        if current != combined:
            widget._theme_root_busy = True
            started = time.perf_counter()
            try:
                widget._theme_root_sheet = combined
                widget.setStyleSheet(combined)
            finally:
                widget._theme_root_busy = False
                if os.environ.get('TWOBYTEASR_THEME_TRACE') == '1':
                    print(f'[theme-root] {widget.metaObject().className()} {widget.objectName()!r} '
                          f'{(time.perf_counter()-started)*1000:.3f}ms', flush=True)


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def theme_key() -> str:
    settings = _settings()
    stored = settings.value("appearance/theme")
    value = str(stored or _volatile_theme_keys.get(settings.fileName(), DEFAULT_THEME_KEY))
    return value if value in THEMES else DEFAULT_THEME_KEY


def save_theme_key(key: str) -> str:
    normalized = str(key or DEFAULT_THEME_KEY)
    if normalized not in THEMES:
        normalized = DEFAULT_THEME_KEY
    settings = _settings()
    settings.setValue("appearance/theme", normalized)
    settings.sync()
    settings_id = settings.fileName()
    if str(settings.value("appearance/theme") or "") == normalized:
        _volatile_theme_keys.pop(settings_id, None)
    else:
        # Sandboxed Windows sessions can read HKCU but reject writes. Keep the
        # active selection usable for this process without confusing another
        # QSettings backend used by tests or portable builds.
        _volatile_theme_keys[settings_id] = normalized
    return normalized


def _palette(theme: ThemeDefinition) -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: theme.app_background,
        QPalette.ColorRole.Base: theme.input_surface,
        QPalette.ColorRole.AlternateBase: theme.panel,
        QPalette.ColorRole.Button: theme.surface,
        QPalette.ColorRole.ToolTipBase: theme.surface_elevated,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.ToolTipText: theme.text,
        QPalette.ColorRole.PlaceholderText: theme.text_muted,
        QPalette.ColorRole.Highlight: theme.accent,
        # 五十二轮：浅色 accent（暖夜炭绿/岩灰橘）上白字对比不足——
        # 选中项文字颜色与 QSS 的 text_on_accent 契约对齐。
        QPalette.ColorRole.HighlightedText: theme.text_on_accent,
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    return palette


def _global_qss(theme: ThemeDefinition) -> str:
    """Override semantic surfaces while retaining existing component geometry."""
    from .design.tokens import WEIGHT_SCALE
    return f"""
QMainWindow, QWidget#appRoot, QWidget#appContent, QStackedWidget,
QStackedWidget > QWidget, QScrollArea, QAbstractScrollArea,
QAbstractScrollArea::viewport, QWidget#qt_scrollarea_viewport {{
    background: {theme.app_background}; color: {theme.text};
}}
QWidget#appRoot {{ border-color: {theme.shell_border}; }}
QFrame#appHeader, QFrame#windowTitleBar {{ background: {theme.shell}; border-color: {theme.shell_border}; }}
QFrame#workflow, QFrame#accordion, QFrame#mediaRow, QFrame#actionBar,
QFrame#modalFooter, QFrame#settingTile, QFrame#smartSourceCard {{
    background: {theme.surface}; border-color: {theme.border}; color: {theme.text};
}}
QFrame#dropOverlay {{ background: {theme.overlay_scrim}; border: 0; }}
QFrame#dropTarget {{
    background: {theme.drop_surface}; border: 3px dashed {theme.accent}; border-radius: 24px;
}}
QLabel#dropOverlayTitle {{ color: {theme.text}; }}
QLabel#dropOverlayHint {{ color: {theme.text_muted}; }}
QFrame#recognitionRoleCard {{ background: {theme.surface_muted}; border-color: {theme.border}; }}
QFrame#recognitionRoleCard[role="primary"] {{
    background: {theme.accent_soft}; border: 2px solid {theme.primary_role};
}}
QFrame#recognitionRoleCard[role="timeline"] {{
    background: {theme.warning_soft}; border: 1px solid {theme.warning};
}}
QFrame#recognitionRoleCard[role="review"] {{
    background: {theme.surface_muted}; border: 1px solid {theme.border};
}}
/* 五十二轮：暗色 accent（夜炭绿/岩灰橘）亮度高，图标/徽章上的固定白字
   对比不足——与 QSS text_on_accent 契约对齐（暖色主题仍为白字，不变）。 */
QLabel#recognitionRoleIcon {{ color: {theme.text_on_accent}; }}
QFrame#recognitionRoleCard[role="timeline"] QLabel#recognitionRoleIcon {{
    background: {theme.warning};
}}
QLabel#recognitionStatusWarn {{ color: {theme.text_on_accent}; }}
QFrame#recognitionRoleCard[role="primary"] QLabel#recognitionModelName {{
    color: {theme.text}; font-weight: {WEIGHT_SCALE['heavy']};
}}
QLabel#contentHeroTitle, QLabel#sectionTitle, QLabel#pageSubtitle,
QLabel#termLibraryTitle, QLabel#termGameTitle, QLabel#smartDialogTitle,
QLabel#headerSubtitle, QLabel#recognitionRoleLabel, QLabel#recognitionModelName,
QLabel#settingTileTitle, QLabel#settingTileSummary {{ color: {theme.text}; }}
QLabel#pageSubtitle, QLabel#settingTileSummary {{ color: {theme.text_muted}; }}
QLabel#headerStatus, QLabel#recognitionStatusGood {{ background: {theme.accent_soft}; color: {theme.success}; }}
QLabel#headerStatus {{ padding: 0; min-width: 0; min-height: 0; background: transparent; }}
QPushButton, QToolButton {{ color: {theme.text}; border-color: {theme.border}; }}
QPushButton#outline, QPushButton#softAction {{
    background: {theme.surface_elevated}; color: {theme.text};
    border: 1px solid {theme.border_strong}; border-radius: 8px;
    padding: 8px 16px; font-weight: 650;
}}
QPushButton#outline:hover, QPushButton#softAction:hover {{
    background: {theme.selected}; border-color: {theme.accent}; color: {theme.text};
}}
QPushButton#studioFooterButton {{
    background: {theme.surface_elevated}; color: {theme.text};
    border: 1px solid {theme.border_strong}; border-radius: 8px;
    padding: 11px 24px; min-width: 190px;
    font-size: 15px; font-weight: 750;
}}
QPushButton#studioFooterButton:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QPushButton#primary {{
    background: {theme.accent}; color: {theme.text_on_accent}; border: 1px solid {theme.accent};
    border-radius: 8px; padding: 11px 28px; font-weight: 750;
}}
QPushButton#primary:hover {{ background: {theme.accent_hover}; color: {theme.text_on_accent}; }}
QPushButton#primary:pressed {{ background: {theme.accent_pressed}; color: {theme.text_on_accent}; }}
QFrame#homeContentProfile, QFrame#homeBatchGlossary {{
    background: {theme.surface_elevated}; border: 1px solid {theme.border_strong}; border-radius: 10px;
}}
QFrame#homeContentProfile QFrame#homeBatchGlossary {{
    background: transparent; border: 0; border-top: 1px solid {theme.border}; border-radius: 0;
}}
QFrame#homeContentProfile QLabel#muted, QFrame#homeBatchGlossary QLabel#muted {{
    color: {theme.text_secondary};
}}
QLabel#homeCardTitle, QLabel#homeGlossaryStatus {{ color: {theme.text}; }}
QFrame#actionBar {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QPushButton:hover, QToolButton:hover {{ background: {theme.selected}; border-color: {theme.accent}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border};
    selection-background-color: {theme.accent}; selection-color: #ffffff;
}}
QComboBox QAbstractItemView, QAbstractItemView {{
    background: {theme.input_surface}; color: {theme.text}; border-color: {theme.border};
    selection-background-color: {theme.selected}; selection-color: {theme.text};
}}
QMenu, QMessageBox, QDialog {{ background: {theme.surface}; color: {theme.text}; border-color: {theme.border}; }}
QMenu::item:selected, QAbstractItemView::item:selected {{ background: {theme.selected}; color: {theme.text}; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background: {theme.panel}; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {theme.border_strong}; }}
/* Window controls: explicit bright tokens instead of remapped warm literals.
   Dark themes need clearly visible normal/hover/disabled states. */
QPushButton#windowControl, QPushButton#windowControlClose {{
    background: transparent; color: {theme.text}; border: 0; border-radius: 6px;
    padding: 0; min-width: 28px; min-height: 26px; max-width: 28px; max-height: 26px;
}}
QPushButton#windowControl:hover {{ background: {theme.selected}; color: {theme.text}; }}
QPushButton#windowControl:pressed {{ background: {theme.border}; color: {theme.text}; }}
QPushButton#windowControl:disabled {{ color: {theme.disabled}; }}
QPushButton#windowControlClose:hover {{ background: {theme.danger}; color: #ffffff; }}
QPushButton#windowControlClose:pressed {{ background: {theme.danger}; color: #ffffff; }}
QLabel#mediaName, QFrame#mediaRow QLabel#mediaName {{ color: {theme.text}; font-weight: 700; }}
QLabel#dropHint, QFrame#mediaRow QLabel#dropHint {{ color: {theme.text_secondary}; }}
QFrame#mediaRow QLabel {{ color: {theme.text}; }}
QFrame#mediaRow[empty="true"] {{ background: {theme.input_surface}; border-color: {theme.border_strong}; }}
QLabel#muted {{ color: {theme.text_muted}; }}
QLabel#pageSubtitle {{ color: {theme.text_secondary}; }}
QFrame#studioEntryCard {{
    background: {theme.warning_soft}; border: 1px solid {theme.warning}; border-radius: 8px;
}}
QLabel#studioEntryTitle {{ color: {theme.text}; font-size: 19px; font-weight: 800; }}
QLabel#studioEntryHint {{ color: {theme.text_secondary}; }}
QPushButton#studioEntryPrimary {{
    background: {theme.warning_soft}; color: {theme.text}; border: 1px solid {theme.warning};
    border-radius: 6px; min-height: 38px; padding: 0 14px; font-weight: 800;
}}
QPushButton#studioEntryPrimary:hover {{ background: {theme.selected}; }}
QDialog, QMessageBox {{ background: {theme.surface}; color: {theme.text}; border-radius: 4px; }}
/* Completion-page hierarchy: a solid elevated secondary CTA and readable
   soft action pills replace transparent outlines that vanish on dark themes. */
QPushButton#secondaryCTA {{
    background: {theme.surface_elevated}; color: {theme.text};
    border: 1px solid {theme.border_strong}; border-radius: 8px;
    padding: 8px 16px; font-weight: 700;
}}
QPushButton#secondaryCTA:hover {{ background: {theme.selected}; border-color: {theme.accent}; color: {theme.text}; }}
QPushButton#secondaryCTA:pressed {{ background: {theme.accent_soft}; border-color: {theme.accent}; }}
QPushButton#softAction {{
    background: {theme.selected}; color: {theme.text};
    border: 1px solid {theme.border}; border-radius: 8px;
    padding: 8px 16px; font-weight: 600;
}}
QPushButton#softAction:hover {{ background: {theme.accent_soft}; border-color: {theme.accent}; color: {theme.text}; }}
QPushButton#softAction:pressed {{ background: {theme.border}; border-color: {theme.accent}; }}
"""


def apply_application_theme(app: QApplication | None = None, key: str | None = None) -> ThemeDefinition:
    """Apply one theme to the application and all currently-created Studio pages."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is required before applying a theme")
    normalized = save_theme_key(key or theme_key())
    theme = theme_definition(normalized)
    if getattr(app, "_applied_theme_key", None) == normalized and app.styleSheet():
        # Same theme already live: stylesheet churn would only re-polish
        # every widget for no visual change.
        return theme
    app._applied_theme_key = normalized
    from .main_ui_theme import APP_QSS
    from .qss_retheme import retheme_qss
    # Dialog/menu/input surfaces are inherited from the owning window.
    # Parentless future windows receive the same sheet before first paint.
    from .studio_theme import build_secondary_surface_qss, build_studio_qss

    from PySide6.QtCore import Qt

    t = _trace_mark(f"apply[{normalized}] start")
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        # QStyleSheetStyle wraps Fusion and has an empty objectName. Testing
        # that proxy's name recreated Fusion (and repolished the entire tree)
        # on every theme change.
        if not getattr(app, "_theme_fusion_installed", False):
            app.setStyle("Fusion")
            app._theme_fusion_installed = True
        app.setPalette(_palette(theme))
        t = _trace_mark("app.setPalette", t)
        sheet = (
            retheme_qss(APP_QSS, theme)
            + _global_qss(theme)
            + build_secondary_surface_qss(theme)
        )
        # QApplication's repolish visits its cached widgets AND recursively
        # their descendants (~300k style events for 3.6k widgets). A window
        # sheet traverses each subtree once; new independent windows receive
        # it from the Polish filter before their first paint.
        app._theme_window_qss = sheet
        if not hasattr(app, "_theme_root_filter"):
            app._theme_root_filter = _ThemeRootFilter(app)
            app.installEventFilter(app._theme_root_filter)
            app.setStyleSheet("/* Window-owned theme sheets; see _ThemeRootFilter. */")
        for root in app.topLevelWidgets():
            if root.parentWidget() is None and root.objectName() != "subtitleStudio":
                app._theme_root_filter.apply_root(root)
        t = _trace_mark("window theme sheets", t)

        # Studio owns a page-level stylesheet for its editor controls. Refresh it
        # after the application sheet so Hub, Editor, and dialogs use one theme.
        for widget in list(app.topLevelWidgets()):
            page = widget if widget.objectName() == "subtitleStudio" else getattr(widget, "studio_page", None)
            if isinstance(page, QWidget):
                if page.parentWidget() is not None and not page.isVisible():
                    page._theme_refresh_pending = True
                    continue
                sheet = build_studio_qss(theme)
                if page.styleSheet() != sheet:
                    page.setStyleSheet(sheet)
                hub_refresh = getattr(page, "_set_hub_toolbar_mode", None)
                if callable(hub_refresh):
                    hub_refresh(getattr(page, "_project_view_state", "") == "hub")
        t = _trace_mark("studio page sheet + hub mode", t)
        for widget in app.allWidgets():
            if getattr(widget, "_secondary_theme_surface", False) and widget.isVisible():
                from .studio_theme import refresh_secondary_surface_theme
                refresh_secondary_surface_theme(widget)
            if hasattr(widget, "refresh_theme_palette"):
                if widget.isVisible():
                    widget.refresh_theme_palette()
                else:
                    widget._theme_refresh_pending = True
            if widget.objectName() in {"projectLibraryScroll", "projectLibraryViewport", "projectLibraryPage"}:
                widget.setProperty("themeKey", normalized)
        t = _trace_mark("allWidgets palette loop", t)
        # Visible dialogs with their own secondary sheet are refreshed too.
        for widget in app.topLevelWidgets():
            if widget.objectName() == "subtitleStudio" or getattr(widget, "studio_page", None) is not None:
                continue
            if widget.isWindow() and widget.isVisible():
                if not callable(getattr(widget, "refresh_theme_palette", None)):
                    widget.setStyleSheet(build_secondary_surface_qss(theme))
        t = _trace_mark("secondary surfaces", t)
        # Re-rasterize only the registered theme-sensitive icons (toolbar,
        # timeline tools, inspector tabs); content data is never refreshed here.
        from .themed_icons import refresh_themed_icons

        refresh_themed_icons(app)
        _trace_mark("refresh_themed_icons", t)
    finally:
        QApplication.restoreOverrideCursor()
    return theme


def apply_theme(key: str, app: QApplication | None = None) -> ThemeDefinition:
    """Public concise alias used by settings and acceptance scripts."""
    return apply_application_theme(app=app, key=key)


def available_themes() -> tuple[ThemeDefinition, ...]:
    return tuple(THEMES.values())
