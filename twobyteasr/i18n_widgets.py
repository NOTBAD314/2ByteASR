"""Qt bindings for the application's existing Chinese-source i18n catalog.

Only presentation properties are changed. Editors and item data are never
translated. Each property remembers both its source and its last output, so a
new application state replaces the old binding rather than resurrecting it.
"""
from __future__ import annotations

import weakref


def bind_text(widget, source, *, property="text", **arguments):
    from .i18n import current_language, translate, TranslatedText, render_arguments
    if isinstance(source, TranslatedText):
        arguments = source.arguments
        source = source.source
    bindings = getattr(widget, "_i18n_bindings", None)
    if bindings is None:
        bindings = widget._i18n_bindings = {}
    bindings[property] = (str(source), arguments)
    value = translate(str(source), current_language())
    if arguments:
        value = value.format(**render_arguments(arguments))
    setter = getattr(widget, "set" + property[0].upper() + property[1:])
    setter(value)
    outputs = getattr(widget, '_i18n_binding_outputs', {})
    outputs[property] = value
    widget._i18n_binding_outputs = outputs
    return widget


def user_text(widget):
    """Mark a data-bearing label; its tooltip may still be application copy."""
    widget.setProperty("i18nUserText", True)
    return widget


_REVERSE_TRANSLATIONS = None


def _reverse_translations():
    """Translated text -> Chinese source, rebuilt only if a table changes.

    apply() runs for every shown window; rebuilding this map each time cost
    ~0.4 ms per call and hundreds of calls at startup.
    """
    global _REVERSE_TRANSLATIONS
    from .i18n import _KNOWN_KEYS, _TRANSLATIONS
    key = (id(_KNOWN_KEYS), tuple((language, id(table), len(table)) for language, table in _TRANSLATIONS.items()))
    if _REVERSE_TRANSLATIONS is None or _REVERSE_TRANSLATIONS[0] != key:
        _REVERSE_TRANSLATIONS = (key, {value: source for table in _TRANSLATIONS.values() for source,value in table.items()})
    return _REVERSE_TRANSLATIONS[1]


def _zoom_state():
    """(percent, factor, active) of the interface zoom; never fails."""
    try:
        from . import ui_zoom
        percent = ui_zoom.zoom_percent()
        return percent, percent / 100.0, percent != ui_zoom.DEFAULT_PERCENT or bool(ui_zoom._state.get("touched"))
    except Exception:
        return 100, 1.0, False


def _pass_signature(obj, language, zoom, text_widget, line_edit):
    """Everything the language pass reads from a plain widget, plus language
    and zoom. Equal to the stamp left by the previous pass means the pass
    would change nothing (2026-10-12: page switches re-walked whole pages)."""
    return (
        language, zoom,
        obj.text() if text_widget else None,
        obj.toolTip(), obj.accessibleName(), obj.statusTip(), obj.whatsThis(),
        obj.windowTitle() if obj.isWindow() else None,
        obj.placeholderText() if line_edit else None,
    )


def apply(root, language):
    from PySide6.QtCore import QSignalBlocker, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel,
        QLineEdit, QPlainTextEdit, QTextEdit, QTabBar, QTableWidget, QListWidget, QPushButton, QWidget)
    from .i18n import _KNOWN_KEYS, translate, render_arguments
    reverse = _reverse_translations()
    zoom, zoom_factor, zoom_active = _zoom_state()
    # Containers whose items / documents the pass also rewrites are always
    # visited; plain widgets are skipped when nothing they show changed.
    always = (QComboBox, QTabBar, QTableWidget, QListWidget, QGroupBox, QTextEdit, QPlainTextEdit)

    def property_text(obj, prop, text, setter):
        if prop == "text" and obj.property("i18nUserText"):
            return
        bindings = getattr(obj, "_i18n_bindings", {})
        binding = bindings.get(prop)
        outputs = getattr(obj, '_i18n_binding_outputs', {})
        if binding and prop in outputs and text != outputs[prop]:
            # A producer replaced the status without a binding. Do not restore
            # the preceding task's sentence on the next language switch.
            bindings.pop(prop, None)
            binding = None
        # Legacy bindings describe the main text only, never its tooltip.
        if binding is None and prop == "text":
            template = obj.property("i18nTemplate") or obj.property("i18nText")
            if template:
                binding = (str(template), obj.property("i18nArguments") or {})
        if binding:
            source, args = binding
            value = translate(source, language)
            if args:
                value = value.format(**render_arguments(args, language))
            outputs[prop] = value
            obj._i18n_binding_outputs = outputs
        else:
            state = getattr(obj, "_i18n_sources", None)
            if state is None:
                state = obj._i18n_sources = {}
            prior = state.get(prop)
            if prior and text == prior[1]:
                source = prior[0]
            else:
                source = reverse.get(text,text)
            body = source.strip()
            prefix = source[:len(source)-len(source.lstrip())]
            suffix = source[len(source.rstrip()):]
            if body.startswith("●"):
                decor = body[:len(body)-len(body.lstrip("● "))]
                prefix += decor
                body = body[len(decor):]
            if body not in _KNOWN_KEYS:
                state.pop(prop, None)
                return
            value = prefix + translate(body, language) + suffix
            state[prop] = (source, value)
        if text != value:
            setter(value)

    nodes = [root, *root.findChildren(QWidget), *root.findChildren(QAction)]
    seen = set()
    for obj in nodes:
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        stamped = None
        if isinstance(obj, QWidget) and not isinstance(obj, always) and not hasattr(obj, "informativeText"):
            stamped = _pass_signature(obj, language, zoom, isinstance(obj, (QLabel, QAbstractButton)),
                                      isinstance(obj, QLineEdit))
            if getattr(obj, "_i18n_pass", None) == stamped:
                continue
        if isinstance(obj, (QLabel, QAbstractButton, QAction)):
            property_text(obj, "text", obj.text(), obj.setText)
        # flexibleWidth: the owner reflows the button itself (it must not pin a
        # parent's minimum width); every other button keeps its full text.
        if (isinstance(obj, QPushButton) and obj.text() and obj.minimumWidth() != obj.maximumWidth()
                and not obj.property('flexibleWidth')):
            if not hasattr(obj, '_i18n_base_minimum'):
                # Logical px: the button's own minimum before any text fit.
                obj._i18n_base_minimum = obj.minimumWidth() / zoom_factor
            content = obj.fontMetrics().horizontalAdvance(obj.text()) + 28 + (obj.iconSize().width()+6 if not obj.icon().isNull() else 0)
            minimum = max(round(obj._i18n_base_minimum * zoom_factor),
                          min(max(content, obj.sizeHint().width() + 4), obj.maximumWidth()))
            obj.setMinimumWidth(minimum)
            if zoom_active:
                # Measured from the zoomed font already: tell the interface
                # zoom so its next pass keeps it instead of scaling it again.
                obj.setProperty("_uiZoom_min_w", [round(minimum / zoom_factor), minimum])
        if isinstance(obj, QGroupBox):
            property_text(obj, "title", obj.title(), obj.setTitle)
        for prop in ('informativeText', 'detailedText'):
            getter = getattr(obj, prop, None)
            if callable(getter):
                property_text(obj, prop, getter(), getattr(obj, 'set'+prop[0].upper()+prop[1:]))
        if isinstance(obj, QWidget):
            for prop in ("toolTip", "statusTip", "whatsThis", "accessibleName", "accessibleDescription", "windowTitle"):
                value = getattr(obj, prop)()
                if value:
                    property_text(obj, prop, value, getattr(obj, "set" + prop[0].upper()+prop[1:]))
        if isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
            property_text(obj, "placeholderText", obj.placeholderText(), obj.setPlaceholderText)
        if isinstance(obj, (QTextEdit, QPlainTextEdit)) and 'plainText' in getattr(obj, '_i18n_bindings', {}):
            property_text(obj, 'plainText', obj.toPlainText(), obj.setPlainText)
        if isinstance(obj, QAction):
            property_text(obj, "toolTip", obj.toolTip(), obj.setToolTip)
        if isinstance(obj, QTabBar):
            for i in range(obj.count()):
                property_text(obj, f"tab:{i}", obj.tabText(i), lambda s,i=i:obj.setTabText(i,s))
                property_text(obj, f"tabTip:{i}", obj.tabToolTip(i), lambda s,i=i:obj.setTabToolTip(i,s))
        if isinstance(obj, QComboBox) and not obj.isEditable() and not obj.property("i18nUserText"):
            # Changing display text emits currentTextChanged unless blocked.
            # Keep stable user data, selection, and all business callbacks intact.
            blocker = QSignalBlocker(obj)
            for i in range(obj.count()):
                if obj.itemData(i, Qt.ItemDataRole.UserRole + 175):
                    continue
                role = Qt.ItemDataRole.UserRole + 173
                prior = obj.itemData(i, role)
                current = obj.itemText(i)
                source = prior[0] if prior and prior[1] == current else reverse.get(current,current)
                if source in _KNOWN_KEYS:
                    arguments = prior[2] if prior and len(prior) > 2 and prior[1] == current else {}
                    value = translate(source, language).format(**render_arguments(arguments, language)) if arguments else translate(source, language)
                    obj.setItemData(i, (source,value,arguments), role)
                    if current != value:
                        obj.setItemText(i,value)
            del blocker
        if isinstance(obj, QListWidget) and obj.property("i18nItems"):
            blocker = QSignalBlocker(obj)
            for row in range(obj.count()):
                _item(obj.item(row), language, capture=True)
            del blocker
        if isinstance(obj, QTableWidget):
            # Table bodies contain filenames, speaker names, terms and captions.
            # Application-owned cells opt in via bind_item; headers are UI copy.
            blocker = QSignalBlocker(obj)
            for i in range(obj.columnCount()):
                item = obj.horizontalHeaderItem(i)
                if item:
                    _item(item, language, capture=True)
            for row in range(obj.rowCount()):
                for col in range(obj.columnCount()):
                    item = obj.item(row,col)
                    if item:
                        _item(item, language, capture=False)
            del blocker
        if stamped is not None:
            # What this widget shows after the pass (setters may have changed it).
            obj._i18n_pass = _pass_signature(obj, language, zoom, isinstance(obj, (QLabel, QAbstractButton)),
                                             isinstance(obj, QLineEdit))


def _item(item, language, *, capture):
    from PySide6.QtCore import Qt
    from .i18n import _KNOWN_KEYS, translate, render_arguments
    role = Qt.ItemDataRole.UserRole + 174
    binding = item.data(role)
    if not binding and capture and item.text() in _KNOWN_KEYS:
        binding = (item.text(), {})
        item.setData(role, binding)
    if binding:
        item.setText(translate(binding[0],language).format(**render_arguments(binding[1], language)))


def bind_item(item, source, **arguments):
    from PySide6.QtCore import Qt
    from .i18n import tr, TranslatedText
    if isinstance(source, TranslatedText):
        arguments, source = source.arguments, source.source
    item.setData(Qt.ItemDataRole.UserRole + 174, (str(source), arguments))
    item.setText(tr(str(source), **arguments))
    return item


def add_combo_item(combo, source, data):
    """Add an application-owned display label without changing business data."""
    from PySide6.QtCore import Qt
    from .i18n import TranslatedText, tr
    message = source if isinstance(source, TranslatedText) else tr(source)
    combo.addItem(str(message), data)
    combo.setItemData(combo.count()-1, (message.source, str(message), message.arguments), Qt.ItemDataRole.UserRole+173)


def install_language_events():
    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance()
    if app is None or hasattr(app,"_i18n_events"):
        return

    class LanguageEvents(QObject):
        def __init__(self):
            super().__init__(app)
            self.pending = {}
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.flush)
            self.busy = False

        def eventFilter(self,obj,event):
            # Installed on the application: read the type once and leave fast.
            if event.type() != _SHOW or self.busy or not isinstance(obj, QWidget):
                return False
            self.pending[id(obj)] = weakref.ref(obj)
            if not self.timer.isActive():
                self.timer.start(0)
            return False

        def flush(self):
            from shiboken6 import isValid
            from .i18n import current_language
            pending, self.pending = self.pending, {}
            self.busy = True
            try:
                roots = [r() for r in pending.values() if r() is not None and isValid(r())]
                from shiboken6 import getCppPointer

                def key_of(widget):
                    # The C++ address: Python wrappers of parents are created
                    # on demand, so their id() may be reused within this loop.
                    return getCppPointer(widget)[0]
                ids = {key_of(r) for r in roots}
                covered = {}

                def has_pending_parent(widget):
                    # Memoized per ancestor: a shown page queues every child.
                    chain = []
                    parent = widget.parentWidget()
                    result = False
                    while parent is not None:
                        key = key_of(parent)
                        if key in covered:
                            result = covered[key]
                            break
                        if key in ids:
                            result = True
                            break
                        chain.append(key)
                        parent = parent.parentWidget()
                    for key in chain:
                        covered[key] = result
                    return result
                roots = [r for r in roots if not has_pending_parent(r)]
                for root in roots:
                    apply(root,current_language())
            finally:
                self.busy = False

    _SHOW = QEvent.Type.Show
    app._i18n_events = LanguageEvents()
    app.installEventFilter(app._i18n_events)


def refresh_application(language):
    from PySide6.QtCore import QEvent, QCoreApplication
    from PySide6.QtWidgets import QApplication, QWidget
    app=QApplication.instance()
    if app is None:
        return
    install_language_events()
    _qt_language(app, language)
    for window in app.topLevelWidgets():
        callback = getattr(window, 'retranslate_ui', None)
        if callback is not None:
            callback()
        apply(window,language)
        # Standard Qt notification also reaches custom-drawn surfaces.
        QCoreApplication.sendEvent(window,QEvent(QEvent.Type.LanguageChange))
        for widget in window.findChildren(__import__('PySide6.QtWidgets',fromlist=['QWidget']).QWidget):
            callback=getattr(widget,'retranslate_ui',None)
            if callback is not None:
                callback()
            QWidget.update(widget)
        apply(window,language)
        QWidget.update(window)


def _qt_language(app, language):
    """Use the bundled Qt catalogs for native dialogs and standard buttons."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    if getattr(app, '_i18n_qt_language', None) == language:
        return
    previous = getattr(app, '_i18n_qt_translator', None)
    if previous is not None:
        app.removeTranslator(previous)
    translator = QTranslator(app)
    locale = {'zh':'zh_CN','ja':'ja','en':'en'}[language]
    if translator.load('qtbase_' + locale, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    app._i18n_qt_translator = translator
    app._i18n_qt_language = language
