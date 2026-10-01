"""Single save/discard/cancel gate for every project replacement path."""

from __future__ import annotations

from enum import Enum
from typing import Callable

from PySide6.QtWidgets import QMessageBox

from .studio_theme import studio_message_box

from .i18n import tr


class DirtyGuardChoice(str, Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


ChoiceProvider = Callable[[str], DirtyGuardChoice]


class ProjectDirtyGuard:
    def __init__(self, page) -> None:
        self.page = page

    def is_dirty(self) -> bool:
        if getattr(self.page, "project", None) is None:
            return False
        stack = getattr(self.page, "undo_stack", None)
        return bool(
            stack is None
            or not stack.isClean()
            or getattr(self.page, "_recovered_autosave_pending", False)
        )

    def _prompt(self, action: str) -> DirtyGuardChoice:
        answer = studio_message_box(
            self.page,
            QMessageBox.Icon.Question,
            tr('保存工程修改'),
            tr('{value0}前是否保存当前工程修改？', value0=tr(action)),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return DirtyGuardChoice.SAVE
        if answer == QMessageBox.StandardButton.Discard:
            return DirtyGuardChoice.DISCARD
        return DirtyGuardChoice.CANCEL

    def confirm(
        self,
        action: str,
        *,
        choice_provider: ChoiceProvider | None = None,
    ) -> bool:
        if not self.is_dirty():
            return True
        choice = (choice_provider or self._prompt)(str(action))
        if choice == DirtyGuardChoice.CANCEL:
            return False
        if choice == DirtyGuardChoice.DISCARD:
            return True
        save = getattr(self.page, "save", None)
        if not callable(save):
            return False
        save()
        return not self.is_dirty()
