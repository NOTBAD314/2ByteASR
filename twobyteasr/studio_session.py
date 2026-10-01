"""Canonical core state for a Subtitle Studio editing session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QUndoStack

    from .studio_project import StudioCue, SubtitleProject
    from .studio_runtime_state import ProjectStateRuntime


@dataclass(slots=True)
class StudioSession:
    """Core Studio state without QObject ownership or UI responsibilities."""

    project: SubtitleProject | None = None
    project_path: Path | None = None
    selected_cue_id: str = ""
    # Transient presentation state, never serialized or used as an edit scope.
    active_cue_id: str = ""
    active_cue_ids: frozenset[str] = field(default_factory=frozenset)
    # E's clock target is independent of manual selection and the editor lock.
    playhead_target_id: str = ""
    observed_playhead_target_id: str | None = None
    preferred_subtitle_speaker: str = ""
    _cue_lookup: dict[str, StudioCue] = field(default_factory=dict)
    undo_stack: QUndoStack | None = None
    runtime: ProjectStateRuntime | None = None
    generation: int = 0
    close_reason: str = ""

    def close(self, reason: str = "") -> int:
        """Invalidate every project-owned reference without closing page services."""
        self.generation += 1
        self.close_reason = str(reason or "")
        self.project = None
        self.project_path = None
        self.selected_cue_id = ""
        self.active_cue_id = ""
        self.active_cue_ids = frozenset()
        self.playhead_target_id = ""
        self.observed_playhead_target_id = None
        self.preferred_subtitle_speaker = ""
        self._cue_lookup.clear()
        self.runtime = None
        if self.undo_stack is not None:
            self.undo_stack.clear()
        return self.generation
