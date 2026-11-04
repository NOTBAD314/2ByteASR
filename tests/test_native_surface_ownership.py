import os,sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget,QFrame
from twobyteasr.design.native_surfaces import isolate_native_children,cover_native_video

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Windows native child ownership')


def test_native_video_does_not_promote_layout_ancestors_or_siblings():
    app=QApplication.instance() or QApplication([])
    isolate_native_children()
    root=QWidget();layout_host=QWidget(root);sibling=QWidget(root)
    canvas=QFrame(layout_host)
    canvas.setAttribute(Qt.WA_DontCreateNativeAncestors,True)
    canvas.setAttribute(Qt.WA_NativeWindow,True)
    assert canvas.winId()
    assert not layout_host.testAttribute(Qt.WA_NativeWindow)
    assert not sibling.testAttribute(Qt.WA_NativeWindow)
    root.close();root.deleteLater()


def test_cover_is_native_child_without_promoting_other_panels():
    app=QApplication.instance() or QApplication([])
    isolate_native_children()
    root=QWidget();sibling=QWidget(root);cover=QFrame(root)
    cover_native_video(cover)
    assert cover.winId() and not cover.isWindow() and cover.parentWidget() is root
    assert not sibling.testAttribute(Qt.WA_NativeWindow)
    root.close();root.deleteLater()
