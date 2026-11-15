"""Which windows audits may answer as a message box (2026-11-15).

「保存工程修改」 is now the candy ``SaveChangesDialog`` instead of a ``QMessageBox``. It keeps the
message box's ``button(StandardButton)``, ``standardButtons()``, ``buttons()``, ``text()`` and
``informativeText()``, so an audit only needs to recognise it: ``isinstance(w, question_boxes())``.
"""
from __future__ import annotations


def question_boxes() -> tuple:
    from PySide6.QtWidgets import QMessageBox
    from ..projects.save_changes_dialog import SaveChangesDialog
    return QMessageBox, SaveChangesDialog


__all__ = ['question_boxes']
