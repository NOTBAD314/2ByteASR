"""Add a media-pool source at the playhead in one step (2026-11-18).

The user asked for adding GIFs, pictures and clips to be as direct as in
Premiere / 剪映. The "+" on a pool card, its right-click menu, Enter and the
panel's main button all come here: the source (its marked in/out range when
one is set, else all of it) goes to the playhead on the lowest free track
above the main video, or on a new track. One undo step.
"""
from __future__ import annotations

from ..i18n import tr
from ..timeline.source_selection import SourceSelection

MODE_LABELS = {'auto': '加到时间线', 'video': '只加画面', 'audio': '只加声音'}


def add_source_at_playhead(page, asset_id: str, mode: str = 'auto') -> tuple[bool, str]:
    """(added, what to tell the user)."""
    from .source_timeline_drop import insert_placement, placement_label, push_insert
    project = page.project
    if project is None or not asset_id:
        return False, tr('没有打开的工程')
    try:
        selection = SourceSelection.capture(project, asset_id, mode)
        placement = insert_placement(page, selection, int(page.timeline.playhead_ms))
        label = placement_label(placement)
        push_insert(page, selection, placement)
    except KeyError:
        return False, tr('素材已不在媒体池')
    except ValueError as exc:
        return False, str(exc)
    return True, tr('已加入 {value0}；Ctrl+Z 撤销', value0=label)
