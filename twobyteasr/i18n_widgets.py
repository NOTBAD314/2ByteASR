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


def apply(root, language):
    from PySide6.QtCore import QSignalBlocker, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel,
        QLineEdit, QPlainTextEdit, QTextEdit, QTabBar, QTableWidget, QListWidget, QPushButton, QWidget)
    from .i18n import _KNOWN_KEYS, _TRANSLATIONS, translate, render_arguments
    reverse = {value: source for table in _TRANSLATIONS.values() for source,value in table.items()}

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
        if isinstance(obj, (QLabel, QAbstractButton, QAction)):
            property_text(obj, "text", obj.text(), obj.setText)
        if isinstance(obj, QPushButton) and obj.text() and obj.minimumWidth() != obj.maximumWidth():
            if not hasattr(obj, '_i18n_base_minimum'):
                obj._i18n_base_minimum = obj.minimumWidth()
            content = obj.fontMetrics().horizontalAdvance(obj.text()) + 28 + (obj.iconSize().width()+6 if not obj.icon().isNull() else 0)
            obj.setMinimumWidth(max(obj._i18n_base_minimum, min(max(content, obj.sizeHint().width() + 4),obj.maximumWidth())))
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
            if not self.busy and isinstance(obj,QWidget) and event.type() == QEvent.Type.Show:
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
                ids={id(r) for r in roots}
                def has_pending_parent(widget):
                    parent=widget.parentWidget()
                    while parent is not None:
                        if id(parent) in ids:return True
                        parent=parent.parentWidget()
                    return False
                roots = [r for r in roots if not has_pending_parent(r)]
                for root in roots:
                    apply(root,current_language())
            finally:
                self.busy = False

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
