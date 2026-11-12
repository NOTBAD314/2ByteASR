"""Complete window-owned Qt sheets, with native cascade and local overrides.

Never split or rewrite QSS selectors. Comments, parent surfaces, pseudo
states, local declarations and late children retain Qt's native semantics.
The small shell is only the construction placeholder used by existing pages.
"""
from PySide6.QtWidgets import QApplication, QWidget

SHELL_QSS = '''QWidget { color: palette(window-text); }
QFrame#contextPanel, QFrame#cueListPanel, QFrame#studioToolbar,
QFrame#studioFooter, QFrame#appHeader {background: palette(button);}
QStackedWidget, QSplitter {background: transparent;}
'''


def managed_window(root):
    return root.objectName() in {'subtitleStudio', 'applicationSettings'} or (
        hasattr(root, 'built_page') and hasattr(root, 'pages'))


def prepare(root):
    """The complete sheet belongs to the window/page, never its descendants."""
    root._theme_scope_owner = True
    root._theme_component_scope = True
    root.setAutoFillBackground(True)
    return [root]


def apply_scope(widget):
    from shiboken6 import isValid
    if not isValid(widget):
        return
    if _covered_by_studio(widget):
        widget._theme_full_sheet_pending = True
        return
    from .theme_manager import theme_definition, theme_key
    from .studio_theme import build_studio_qss
    from ..app import ui_zoom
    app = QApplication.instance()
    key = (getattr(app, '_applied_theme_key', None), ui_zoom.zoom_percent())
    if (widget.__dict__.get('_theme_component_key') == key
            and widget.styleSheet() == widget.__dict__.get('_theme_component_sheet')):
        return
    if widget.objectName() == 'subtitleStudio':
        sheet = getattr(app, '_theme_window_qss', '') + build_studio_qss(theme_definition(theme_key()))
        if widget.styleSheet() != sheet:
            widget.setStyleSheet(sheet)
        widget.setProperty('_uiZoomStudioBase', sheet)
        widget.setProperty('_uiZoomStudioLast', sheet)
        ui_zoom.protect_studio(widget)
    else:
        # Preserve the unscaled base when interface zoom changes. Descendant
        # inline sheets are never captured or concatenated into this sheet.
        ui_zoom.set_sheet(widget, getattr(app, '_theme_window_qss', ''))
    widget._theme_component_sheet = widget.styleSheet()
    widget._theme_component_key = key


def _covered_by_studio(root):
    # Studio owns a complete sheet itself. While it fills the main stack,
    # updating the hidden Home owner's sheet would style Studio twice. Keep
    # Home's update pending until its subtree is shown again.
    if hasattr(root, 'built_page') and hasattr(root, 'pages'):
        studio = root.built_page('studio')
        if studio is not None and root.pages.currentWidget() is studio and studio.isVisible():
            return True
    return False


def refresh(root):
    from .theme_updates import dispatch
    if _covered_by_studio(root):
        root._theme_full_sheet_pending = True
        return
    root._theme_full_sheet_pending = False
    prepare(root)
    dispatch(lambda: apply_scope(root))


def prepare_steps(root, *, branch=None, all_branches=False):
    """Style once; retain cooperative preparation of layout measurements."""
    from .gui_slices import GuiSlice, GUI_YIELD
    from shiboken6 import isValid
    budget = GuiSlice()
    prepare(root)
    apply_scope(root)
    root.ensurePolished()
    if budget.due():
        yield GUI_YIELD
        budget.resume()
    for widget in reversed(root.findChildren(QWidget)):
        if not isValid(widget) or widget.layout() is None:
            continue
        if branch is not None and widget is not branch and not branch.isAncestorOf(widget):
            continue
        widget.sizeHint()
        widget.minimumSizeHint()
        if budget.due():
            yield GUI_YIELD
            budget.resume()


def shown(widget):
    if managed_window(widget):
        refresh(widget)
        return
    node = widget.parentWidget()
    while node is not None:
        if managed_window(node):
            if node.__dict__.get('_theme_full_sheet_pending', False):
                refresh(node)
            return
        node = node.parentWidget()
    # Qt styles inserted and newly shown children without replacing local QSS.
