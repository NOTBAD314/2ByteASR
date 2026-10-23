"""Full caption rebuilds in a resident worker process (stall stage 3, 2026-10-22).

The caption preparing thread rebuilds only changed cues (caption_playback_cache).
A full rebuild is still needed when caption-wide state changes (the default
style, bilingual mode, speaker-name layout, the first build): 2-3.5 s of pure
Python for 2090 bilingual cues. In the editor's process that time is taken
from the GUI thread through the GIL. Here it runs in the shared resident
worker (``system/resident_worker.py``); the preparing thread only pickles the
cues and styles (~10 ms) and waits on the pipe without holding the GIL.

Any failure answers ``None`` and the caller rebuilds in process, as before.
"""
from __future__ import annotations

from dataclasses import replace


def wire_revision(revision):
    """The part of a render revision a display rebuild reads.

    Display cues do not read caption receipts; like the ASS compiler's wire
    revision, the caption timeline stays home (it is most of studio_state).
    """
    from ..projects.studio_revisions import FrozenMap
    state = revision.studio_state
    if isinstance(state, FrozenMap):
        state = FrozenMap(tuple(item for item in state.items if item[0] != "caption_timeline"))
    return replace(revision, cues=revision.timeline_cues if revision.timeline_cues is not None else revision.cues,
                   timeline_cues=None, word_animations=None, studio_state=state)


def build_display_cues(revision):
    """``project_display_cues`` for every cue of a (wire) revision."""
    from ..projects.studio_project import StudioCue
    from ..caption_style.bilingual_layout import project_display_cues
    from .caption_playback_cache import _caption_source_project
    source = _caption_source_project(revision)
    return project_display_cues(source, [StudioCue(**cue.to_dict()) for cue in revision.cues])


def build_in_worker(revision):
    """Display cues built by the shared resident worker, or None."""
    from ..system.resident_worker import shared_worker
    worker = shared_worker()
    if worker is None:
        return None
    return worker.call("twobyteasr.rendering.caption_display_actor:build_display_cues", wire_revision(revision))
