"""Single save/discard/cancel gate for every project replacement path."""

from __future__ import annotations

from enum import Enum
from typing import Callable

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
        draft = getattr(self.page, "_draft_recovery", None)
        if draft is not None and draft.snapshot() is not None:
            return True
        stack = getattr(self.page, "undo_stack", None)
        return bool(
            stack is None
            or not stack.isClean()
            or getattr(self.page, "_recovered_autosave_pending", False)
        )

    def _project_name(self) -> str:
        project = getattr(self.page, "project", None)
        name = str(getattr(getattr(project, "media", None), "display_name", "") or "")
        if not name:
            path = getattr(self.page, "project_path", None)
            name = getattr(path, "stem", "") or ""
        return str(name)

    def _discard_autosaves(self) -> None:
        """「不保存」: this project's recovery point goes too (2026-11-15).

        Opening a project now restores a newer autosave without asking, so an autosave left
        behind would bring back exactly the changes the user just threw away.
        """
        project = getattr(self.page, "project", None)
        if project is None:
            return
        trace = getattr(self.page, "_studio_trace", lambda *args, **kwargs: None)
        try:
            from .studio_project import autosave_path, discard_autosave, PROJECT_SUFFIX
            path = getattr(self.page, "project_path", None) or None
            canonical = autosave_path(project, path)
            for candidate in {canonical, *canonical.parent.glob(f"{canonical.stem}.*{PROJECT_SUFFIX}")}:
                if candidate.is_file():
                    discard_autosave(candidate)
                    trace("AUTOSAVE_DISCARDED_WITH_CHANGES", autosave_path=str(candidate))
        except Exception as exc:  # noqa: BLE001 - leaving must never fail over a recovery point
            trace("AUTOSAVE_DISCARD_FAILED", error=f"{type(exc).__name__}: {exc}"[:200])

    def _prompt(self, action: str) -> DirtyGuardChoice:
        # 2026-11-15 (user): three candies instead of the Windows message box (draft B).
        from .save_changes_dialog import ask_save_changes
        answer = ask_save_changes(self.page, action, self._project_name())
        if answer == "save":
            return DirtyGuardChoice.SAVE
        if answer == "discard":
            return DirtyGuardChoice.DISCARD
        return DirtyGuardChoice.CANCEL

    def confirm(
        self,
        action: str,
        *,
        choice_provider: ChoiceProvider | None = None,
        on_saved: Callable | None = None,
    ) -> bool:
        queue = getattr(self.page, '_persistence_queue', None)
        if queue is not None and queue.busy:
            if on_saved is not None:
                from .studio_save import queue_navigation_after_save
                queue_navigation_after_save(self.page, on_saved)
            return False
        if not self.is_dirty():
            return True
        choice = (choice_provider or self._prompt)(str(action))
        if choice == DirtyGuardChoice.CANCEL:
            return False
        if choice == DirtyGuardChoice.DISCARD:
            if getattr(self.page, "_canvas_editor", None) is not None:
                self.page._cancel_canvas_inline_edit()
            self._discard_autosaves()
            return True
        save = getattr(self.page, "save", None)
        if not callable(save):
            return False
        if on_saved is not None:
            from .studio_save import queue_navigation_after_save
            queue_navigation_after_save(self.page, on_saved)
        save()
        queue = getattr(self.page, '_persistence_queue', None)
        if queue is not None and queue.busy:
            return False
        from .studio_save import cancel_navigation_after_save
        cancel_navigation_after_save(self.page)
        return not self.is_dirty()
