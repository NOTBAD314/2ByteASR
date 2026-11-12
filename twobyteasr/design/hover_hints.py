"""Application-wide policy for automatically requested hover explanations.

Keep tooltip strings available to accessibility and existing command metadata.
Consume only the request event, before native widgets, actions and item-view
delegates handle it. No widget walks, polling, or popup-window interception.
"""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication


class HoverHintPolicy(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            event.accept()
            return True
        return False


def install_hover_hint_policy(app=None):
    app = app or QApplication.instance()
    if app is None:
        return None
    policy = getattr(app, '_hover_hint_policy', None)
    if policy is None:
        policy = app._hover_hint_policy = HoverHintPolicy(app)
        app.installEventFilter(policy)
    return policy
