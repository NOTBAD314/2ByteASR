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


_MANAGED_NAMES = frozenset({'subtitleStudio', 'applicationSettings'})
_TYPE_HAS_BUILT_PAGE: dict = {}


def managed_window(root):
    # Called for every ancestor of every shown widget (a page switch shows
    # hundreds). A missing attribute on a Qt instance costs ~4 us, so look at
    # the class once per type and at the instance dict, never hasattr first.
    if root.objectName() in _MANAGED_NAMES:
        return True
    kind = type(root)
    has_page = _TYPE_HAS_BUILT_PAGE.get(kind)
    if has_page is None:
        has_page = _TYPE_HAS_BUILT_PAGE[kind] = hasattr(kind, 'built_page')
    if not has_page and 'built_page' not in getattr(root, '__dict__', ()):
        return False
    return hasattr(root, 'built_page') and hasattr(root, 'pages')


def prepare(root):
    """The complete sheet belongs to the window/page, never its descendants."""
    root._theme_scope_owner = True
    root._theme_component_scope = True
    root.setAutoFillBackground(True)
    return [root]


def apply_scope(widget):
    from shiboken6 import isValid
    if not isValid(widget) or widget.__dict__.get('_theme_scope_busy', False):
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
    widget._theme_scope_busy = True
    try:
        if widget.objectName() == 'subtitleStudio':
            # Studio already owns a complete unscaled sheet. Do not apply it
            # and then prepend the same window rules for a second native
            # polish when Home is zoomed. One owner, one native style pass.
            sheet = getattr(app, '_theme_window_qss', '') + build_studio_qss(theme_definition(theme_key()))
            if widget.styleSheet() != sheet:
                widget.setStyleSheet(sheet)
            widget.setProperty('_uiZoomStudioBase', sheet)
            widget.setProperty('_uiZoomStudioLast', sheet)
        else:
            ui_zoom.set_sheet(widget, getattr(app, '_theme_window_qss', ''))
        widget._theme_component_sheet = widget.styleSheet()
        widget._theme_component_key = key
    finally:
        widget._theme_scope_busy = False


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
    if budget.due():
        yield GUI_YIELD
        budget.resume()
    # 2026-11-18: polish leaf-first, in slices. ensurePolished() recurses into
    # every unpolished child, so one call on the root polished all of Studio
    # in a single 0.6-0.8 s step while its loading card was up.
    children = root.findChildren(QWidget)
    for widget in reversed(children):
        if not isValid(widget):
            continue
        widget.ensurePolished()
        if budget.due():
            yield GUI_YIELD
            budget.resume()
    root.ensurePolished()
    if budget.due():
        yield GUI_YIELD
        budget.resume()
    for widget in reversed(children):
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
