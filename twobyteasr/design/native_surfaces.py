"""Windows native surfaces are explicit; ordinary panels stay in Qt's backing store."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def isolate_native_children():
    if sys.platform == 'win32':
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)


def cover_native_video(widget):
    """A true in-window cover needs its own HWND above the external player.

    Apply only when Studio enabled isolated native children. Do not promote
    the widget's ancestors/siblings and do not create another top-level window.
    """
    if sys.platform == 'win32' and QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings):
        widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
