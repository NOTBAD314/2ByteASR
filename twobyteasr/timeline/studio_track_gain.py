"""Track gain in dB, stored in the existing extensible Studio state."""
from __future__ import annotations

import math

from ..i18n import bind_text

MIN_GAIN_DB, MAX_GAIN_DB = -60., 24.


def audio_track_id(project, track_id):
    """Vn and its linked An address the same gain control."""
    return next((g.audio_track_id for g in project.av_track_groups
                 if g.linked and g.video_track_id == track_id), track_id)


def track_gain_db(project, track_id):
    values = project.studio_state.get("audio_track_gain_db", {})
    try:
        value = float(values.get(audio_track_id(project, track_id), 0.))
        return max(MIN_GAIN_DB, min(MAX_GAIN_DB, value)) if math.isfinite(value) else 0.
    except (TypeError, ValueError, AttributeError):
        return 0.


def audio_track_locked(project, track_id):
    key = audio_track_id(project, track_id)
    if any(t.locked for t in project.audio_tracks if t.id == key):
        return True
    from .studio_clip_edit import video_track_locked
    owners = {g.video_track_id for g in project.av_track_groups if g.linked and g.audio_track_id == key}
    return any(video_track_locked(project, t) for t in project.video_tracks if t.id in owners)


def gain_amplitude(db):
    value = float(db)
    # Each control is bounded; their sum is an audio chain, not another control.
    return 10. ** (max(-240., min(120., value)) / 20.) if math.isfinite(value) else 1.


def gain_command(project, track_id, value):
    return gains_command(project, {track_id: value})


def gains_command(project, values):
    """One undo step for any number of tracks (the mixer applies them together)."""
    if any(audio_track_locked(project, key) for key in values):
        raise ValueError('音轨或关联视频轨已锁定，请先解锁')
    from PySide6.QtGui import QUndoCommand
    from ..projects.studio_runtime_state import DirtyDomain, state_for

    class TrackGainCommand(QUndoCommand):
        def __init__(self):
            super().__init__("调整轨道音量")
            self.before = dict(project.studio_state.get("audio_track_gain_db", {}))
            self.after = dict(self.before)
            for key, value in values.items():
                self.after[audio_track_id(project, key)] = max(MIN_GAIN_DB, min(MAX_GAIN_DB, float(value)))

        def apply(self, values):
            with state_for(project).transaction(project, action_id=self.text(),
                    dirty=DirtyDomain.AUDIO_GAIN | DirtyDomain.AUTOSAVE | DirtyDomain.TIMELINE_PIXELS,
                    snapshot_cues=False):
                project.studio_state["audio_track_gain_db"] = dict(values)

        def redo(self): self.apply(self.after)
        def undo(self): self.apply(self.before)

    return TrackGainCommand()


# A dot per track so the strips are easy to tell apart (fixed hues, both themes).
TRACK_HUES = ("#c4532c", "#4a78a8", "#6b9a4a", "#8d6bc4", "#c99a1b", "#3f9a92", "#b5487a", "#7a7f8c")


def show_track_gain(page, track_id=""):
    """轨道音量 as a small mixer (2026-11-14, user picked draft C).

    Every audio track gets a vertical fader with its live level beside it, so
    tracks can be balanced against each other. The track that was asked for is
    marked 「当前」. Changes preview at once; 应用 saves all changed tracks as
    one undo step, 取消 (or closing) restores the sound.
    """
    project = page.project
    if project is None or not project.audio_tracks:
        return
    existing = getattr(page, "_track_gain_dialog", None)
    if existing is not None and existing.isVisible():
        existing.raise_(); existing.activateWindow()
        return
    selected = track_id or getattr(page.timeline, "selected_audio_track_id", "")
    if not selected:
        selected = getattr(page.timeline, "selected_video_track_id", "")
    selected = audio_track_id(project, selected)
    if selected not in {track.id for track in project.audio_tracks}:
        bind_text(page.save_state, '请先选择要调整音量的 A 波形行；该视频没有关联音频轨')
        return
    if audio_track_locked(project, selected):
        bind_text(page.save_state, '音轨或关联视频轨已锁定，请先解锁')
        return
    from .track_gain_mixer import TrackGainMixer
    dialog = TrackGainMixer(page, project, selected)
    page._track_gain_dialog = dialog
    dialog.finished.connect(dialog.deleteLater)
    dialog.finished.connect(lambda: setattr(page, "_track_gain_dialog", None))
    dialog.open()
    dialog.focus_current()
