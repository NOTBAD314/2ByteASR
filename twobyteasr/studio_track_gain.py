"""Track gain in dB, stored in the existing extensible Studio state."""
from __future__ import annotations

import math

from .i18n import bind_text

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
    return 10. ** (max(MIN_GAIN_DB, min(MAX_GAIN_DB, value)) / 20.) if math.isfinite(value) else 1.


def gain_command(project, track_id, value):
    if audio_track_locked(project, track_id):
        raise ValueError('音轨或关联视频轨已锁定，请先解锁')
    from PySide6.QtGui import QUndoCommand
    from .studio_runtime_state import DirtyDomain, state_for

    class TrackGainCommand(QUndoCommand):
        def __init__(self):
            super().__init__("调整轨道音量")
            self.key = audio_track_id(project, track_id)
            self.before = dict(project.studio_state.get("audio_track_gain_db", {}))
            self.after = dict(self.before)
            self.after[self.key] = max(MIN_GAIN_DB, min(MAX_GAIN_DB, float(value)))

        def apply(self, values):
            with state_for(project).transaction(project, action_id=self.text(),
                    dirty=DirtyDomain.AUDIO_GAIN | DirtyDomain.AUTOSAVE | DirtyDomain.TIMELINE_PIXELS,
                    snapshot_cues=False):
                project.studio_state["audio_track_gain_db"] = dict(values)

        def redo(self): self.apply(self.after)
        def undo(self): self.apply(self.before)

    return TrackGainCommand()


def show_track_gain(page, track_id=""):
    from PySide6.QtWidgets import QDoubleSpinBox, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout
    from .main_ui_dialogs import SpringDialog, DialogSurface
    from .studio_theme import StudioComboBox, apply_secondary_surface_theme
    from .studio_widgets import ScrubDoubleSpinBox
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
    class GainDialog(SpringDialog):
        def done(self, result):
            # Cancel restores the sound immediately, before the exit fade.
            restore(result)
            super().done(result)
    dialog = GainDialog(page, backdrop=False)
    bind_text(dialog, '轨道音量', property='windowTitle')
    dialog.setObjectName("trackGainDialog")
    dialog.resize(450, 290)
    apply_secondary_surface_theme(dialog)
    layout = QVBoxLayout(dialog); layout.setContentsMargins(0, 0, 0, 0)
    surface = DialogSurface(dialog, title="轨道音量", close_callback=dialog.reject)
    layout.addWidget(surface)
    form = QFormLayout(); surface.body_layout.addLayout(form)
    tracks = StudioComboBox(); tracks.setObjectName("gainTrack")
    for track in project.audio_tracks:
        if audio_track_locked(project, track.id):
            continue
        label = f"{track.id} · {track.name}" if track.name and track.name != track.id else f"{track.id} 音轨"
        tracks.addItem(label, track.id)
    tracks.setCurrentIndex(max(0, tracks.findData(selected)))
    gain = ScrubDoubleSpinBox(); gain.setObjectName("trackGainDb")
    gain.setRange(MIN_GAIN_DB, MAX_GAIN_DB); gain.setDecimals(1); gain.setSingleStep(1.)
    gain.setSuffix(" dB"); gain.setMinimumWidth(160)
    def choose():
        page._gain_preview_values = {}
        key = str(tracks.currentData())
        gain.blockSignals(True)
        gain.setValue(track_gain_db(project, key))
        gain.blockSignals(False)
        page._refresh_audio_mix_only()
    tracks.currentIndexChanged.connect(choose); choose()
    form.addRow("轨道", tracks); form.addRow("增益", gain)
    hint = QLabel("左右拖动数值实时试听；Shift 精细，Ctrl 粗调。\n点击可输入；应用后保存，取消恢复原音量。")
    hint.setObjectName("settingsDescription"); surface.body_layout.addWidget(hint)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                               | QDialogButtonBox.StandardButton.Reset)
    bind_text(buttons.button(QDialogButtonBox.StandardButton.Ok), '应用')
    bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
    bind_text(buttons.button(QDialogButtonBox.StandardButton.Reset), '重置为 0 dB')
    buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(lambda: gain.setValue(0.))
    def preview(value):
        if page.project is project:
            page._gain_preview_values = {str(tracks.currentData()):float(value)}
            page._refresh_audio_mix_only()
    gain.valueChanged.connect(preview)
    def commit():
        key = str(tracks.currentData())
        page._gain_preview_values = {}
        if page.project is project and gain.value() != track_gain_db(project, key):
            try:
                page.undo_stack.push(gain_command(project, key, gain.value()))
            except ValueError as exc:
                page.save_state.setText(str(exc))
                dialog.reject()
                return
        dialog.accept()
    def restore(_result):
        gain._cancel_scrub()
        page._gain_preview_values = {}
        if page.project is project:
            page._refresh_audio_mix_only()
    buttons.accepted.connect(commit); buttons.rejected.connect(dialog.reject)
    surface.footer_layout.addWidget(buttons)
    page._track_gain_dialog = dialog
    dialog.finished.connect(dialog.deleteLater)
    dialog.finished.connect(lambda: setattr(page, "_track_gain_dialog", None))
    dialog.open(); gain.setFocus(); gain.selectAll()
