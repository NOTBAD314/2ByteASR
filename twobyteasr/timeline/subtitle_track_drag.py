"""Subtitle tracks moved by dragging (2026-11-20).

User (2026-11-20): subtitle tracks in the workbench should be freely draggable to another place,
and several selected subtitles should move up or down between tracks together in one drag.

A subtitle track is a speaker; its place is ``studio_state['speaker_track_order']``.

* ``reordered``: the track order after dragging one track's header onto another's row.
* ``shifted_speakers``: the selected lines moved by the same number of rows as the pointer, each
  keeping its distance to the others; nothing moves when one of them would leave the rows or land
  on a locked track.
* ``ReorderSubtitleTracksCommand``: the new order as one undo step.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from PySide6.QtGui import QUndoCommand


def reordered(order: Sequence[str], source: str, target: str) -> list[str]:
    """``order`` with ``source`` put where ``target`` is (``target`` moves one place toward
    where ``source`` was). Unchanged when either is missing or they are the same."""
    items = [str(item) for item in order]
    if source == target or source not in items or target not in items:
        return items
    index = items.index(target)
    items.remove(source)
    items.insert(index, source)
    return items


def shifted_speakers(speakers: Mapping[str, str], rows: Sequence[str], origin: str, target: str,
                     locked: Iterable[str] = ()) -> dict[str, str]:
    """{cue id: new speaker} for the cues whose track changes, when the pointer went from row
    ``origin`` to row ``target`` (``rows`` top to bottom). Empty when nothing can move."""
    rows = [str(row) for row in rows]
    if not speakers or origin not in rows or target not in rows or origin == target:
        return {}
    shift = rows.index(target) - rows.index(origin)
    blocked = {str(item) for item in locked}
    moved: dict[str, str] = {}
    for cue_id, speaker in speakers.items():
        if speaker not in rows:
            return {}                       # on a row that is not its own (a collapsed group)
        index = rows.index(speaker) + shift
        if index < 0 or index >= len(rows) or rows[index] in blocked:
            return {}
        if rows[index] != speaker:
            moved[cue_id] = rows[index]
    return moved


class ReorderSubtitleTracksCommand(QUndoCommand):
    """One subtitle track dragged to another place: the saved order, undoable."""

    def __init__(self, page, order: Sequence[str]):
        super().__init__('调整字幕轨道顺序')
        self.page, self.project = page, page.project
        self.before = list(self.project.studio_state.get('speaker_track_order') or page.timeline.speaker_ids())
        self.after = [str(item) for item in order]

    def _apply(self, order):
        from ..projects.studio_runtime_state import DirtyDomain as D, state_for
        page, project = self.page, self.project
        dirty = D.TIMELINE_INDEX | D.AUTOSAVE | D.TIMELINE_PIXELS
        with state_for(project).transaction(project, action_id=self.text(), dirty=dirty):
            project.studio_state['speaker_track_order'] = list(order)
        if page.project is project:
            page.timeline.reindex_project()
            page.timeline.update()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def reorder_subtitle_track(page, source: str, target: str) -> bool:
    """Push the move of track ``source`` onto ``target``'s place. False when nothing changes."""
    if page.project is None:
        return False
    current = page.timeline.speaker_ids()
    order = reordered(current, source, target)
    if order == current:
        return False
    page.undo_stack.push(ReorderSubtitleTracksCommand(page, order))
    return True


__all__ = ['ReorderSubtitleTracksCommand', 'reorder_subtitle_track', 'reordered', 'shifted_speakers']
