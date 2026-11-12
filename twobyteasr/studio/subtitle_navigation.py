"""Subtitle navigation owns an explicit target; PlaybackClock still owns time.

The target is a project/session + stable cue ID + text layer, never the cue
currently visible in the video. All movement goes through Studio's _seek.
"""
from __future__ import annotations

import json
import math

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence

from ..i18n import tr

COMMAND = 'jump_cue_boundary'
PREFERENCE = 'selection_centered'


def save_center_preference(enabled):
    from ..projects.studio_project import studio_settings_path
    from ..storage.atomic_files import write_text_atomic
    path = studio_settings_path()
    try:
        payload = json.loads(path.read_text('utf8')) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    preferences = payload.get('studio_preferences')
    preferences = dict(preferences) if isinstance(preferences, dict) else {}
    preferences[PREFERENCE] = bool(enabled)
    payload['studio_preferences'] = preferences
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


class StudioSubtitleNavigationMixin:
    def _selection_centered(self):
        toggle = getattr(self, 'selection_center_toggle', None)
        return bool(toggle is not None and toggle.isChecked())

    def _sync_navigation_playback_intent(self, paused):
        # Buffer holds and duplicate player-state receipts are observations,
        # not a fresh request to resume following the user's browsed viewport.
        intended = bool(getattr(self.video, 'playback_intended', not paused))
        previous = getattr(self, '_navigation_playback_intended', False)
        self._navigation_playback_intended = intended
        if not intended:
            self._navigation_resume_follow_pending = False
        elif not previous:
            self._navigation_resume_follow_pending = True
        if not paused and getattr(self, '_navigation_resume_follow_pending', False):
            self._navigation_resume_follow_pending = False
            self.timeline._manual_view_hold = False
            if self._selection_centered():
                self.timeline._follow_suspended_until = 0

    def _selection_center_changed(self, enabled):
        # Compatibility for callers of the former switch. Locating is now an
        # explicit action; ordinary selection and playback never reset zoom.
        if enabled:
            self._locate_selected_subtitle()

    def _locate_selected_subtitle(self):
        # This button owns the explicit selection, independently of an older
        # pinned E draft. The boundary shortcut retains its editor ownership.
        cue_id = self.selection_model.scope.active_id
        cue = self.timeline._timeline_cue_by_id.get(cue_id) if self.project else None
        if cue is None or cue.end_ms <= cue.start_ms:
            self._show_studio_hint(tr('请先选中一条字幕'))
            return
        layer = self.timeline.active_subtitle_layer
        self._remember_subtitle_navigation(cue.id, layer)
        self.timeline.locate_subtitle_start(cue.start_ms)
        self._seek_subtitle_navigation(cue.start_ms, fixed_window=True)

    def _select_cue_observation(self, cue_id, *, hydrate=True):
        # Restoring a project and hydrating a clock highlight are observations,
        # not a new user choice. Preserve the normal E-follow/default-layer path.
        previous = getattr(self, '_navigation_observation_selection', False)
        self._navigation_observation_selection = True
        try:
            return self.select_cue(cue_id, hydrate=hydrate)
        finally:
            self._navigation_observation_selection = previous

    def _remember_subtitle_navigation(self, cue_id, layer=None):
        if self.project is None or not cue_id:
            self._subtitle_navigation_target = None
            self._subtitle_endpoint_hold = False
            self._subtitle_navigation_requested_ms = None
            return
        layer = layer or self.timeline.active_subtitle_layer
        target = (id(self.project), self.session.generation, str(cue_id), layer)
        if target != getattr(self, '_subtitle_navigation_target', None):
            self._subtitle_endpoint_hold = False
            self._subtitle_navigation_requested_ms = None
        self._subtitle_navigation_target = target

    def _held_subtitle_navigation(self):
        target = getattr(self, '_subtitle_navigation_target', None)
        return bool(target is not None and self.project is not None
                    and target[:2] == (id(self.project), self.session.generation)
                    and target[2] == self.selected_cue_id
                    and target[3] == self.timeline.active_subtitle_layer
                    and target[2] in self._cue_lookup)

    def _subtitle_navigation_holds_editor(self):
        draft = getattr(self, '_caption_draft', None)
        target = getattr(self, '_subtitle_navigation_target', None)
        return bool(self._held_subtitle_navigation() and draft is not None
                    and self._caption_owns_draft(draft)
                    and (draft.target.cue_id, draft.target.layer) == target[2:])

    def _subtitle_navigation_cue(self):
        # The editor's bound identity wins while its nonmodal window is open.
        draft = getattr(self, '_caption_draft', None)
        if (getattr(self, '_caption_following', False) and draft is not None
                and self._caption_owns_draft(draft)):
            cue_id, layer = draft.target.cue_id, draft.target.layer
        else:
            cue_id = self.selection_model.scope.active_id
            layer = self.timeline.active_subtitle_layer
        cue = self.timeline._timeline_cue_by_id.get(cue_id) if self.project else None
        if cue is None or cue.end_ms <= cue.start_ms:
            return None
        return cue, layer

    def _navigate_selected_subtitle(self, cue_id):
        """Only a completed click or an explicit keyboard selection calls this."""
        if not self._selection_centered() or cue_id != self.selected_cue_id:
            return
        cue = self.timeline._timeline_cue_by_id.get(cue_id)
        if cue is not None:
            self._remember_subtitle_navigation(cue_id)
            self._seek_subtitle_navigation(cue.start_ms)

    def _seek_subtitle_navigation(self, milliseconds, *, fixed_window=False):
        target = self.timeline._bounded_time_ms(milliseconds)
        self._subtitle_locate_window_target_ms = target if fixed_window else None
        self._subtitle_navigation_requested_ms = target
        # Caption preparation already coalesces requests and rejects old epochs.
        self._seek(target / 1000.0, preserve_subtitle_target=True)

    def _subtitle_navigation_position(self):
        pending = getattr(getattr(self, '_caption_seek_preparation', None), 'pending', None)
        clock = getattr(self.video, '_playback_clock', None)
        requested = getattr(self, '_subtitle_navigation_requested_ms', None)
        if requested is not None and (pending is not None or getattr(clock, 'exact_seek_pending', False)):
            return requested
        return self.timeline.playhead_ms

    def _jump_current_subtitle_boundary(self, edge=None):
        """``edge`` 'start'/'end' goes there; None toggles between them (Alt+J)."""
        edge = edge if edge in ('start','end') else None
        if edge is None:
            resolved = self._subtitle_navigation_cue()
        else:
            cue_id = self.selection_model.scope.active_id
            cue = self.timeline._timeline_cue_by_id.get(cue_id) if self.project else None
            resolved = (cue,self.timeline.active_subtitle_layer) if cue is not None and cue.end_ms>cue.start_ms else None
        if resolved is None:
            self._show_studio_hint(tr('请先选中一条字幕'))
            return
        cue, layer = resolved
        # Resolve the latest projection on every invocation, including after trim.
        self._remember_subtitle_navigation(cue.id, layer)
        self._subtitle_endpoint_hold = True
        if (self.selected_cue_id != cue.id or self.timeline.active_subtitle_layer != layer):
            self.timeline.set_subtitle_layer(layer)
            self.select_cue(cue.id)
            self._remember_subtitle_navigation(cue.id, layer)
            self._subtitle_endpoint_hold = True
        if edge is not None:
            self._seek_subtitle_navigation(cue.end_ms if edge == 'end' else cue.start_ms)
            return
        from ..timeline.caption_frame_time import project_frame_rate
        rate = project_frame_rate(self.project)
        tolerance = max(1, min(math.ceil(1000 / rate) if rate else 1,
                               max(1, (cue.end_ms - cue.start_ms) // 3)))
        position = self._subtitle_navigation_position()
        at_start = (abs(position - cue.start_ms) <= tolerance
                    and abs(position - cue.start_ms) <= abs(position - cue.end_ms))
        self._seek_subtitle_navigation(cue.end_ms if at_start else cue.start_ms)

    def _jump_current_subtitle_start(self):
        self._jump_current_subtitle_boundary('start')

    def _jump_current_subtitle_end(self):
        self._jump_current_subtitle_boundary('end')

    def _sync_cue_capsule(self):
        """The 当前字幕 pill names the selected subtitle's list number and is
        usable only while one is selected. Cheap enough for playback follow."""
        badge = getattr(self, 'cue_capsule_badge', None)
        timeline = getattr(self, 'timeline', None)
        if badge is None:
            return
        cue_id = str(self.selected_cue_id or '') if self.project is not None and timeline is not None else ''
        present = bool(cue_id) and cue_id in timeline._timeline_cue_by_id
        index = None
        if present:
            lookup = getattr(self, '_cue_jump_index', None) or {}
            index = lookup.get(cue_id)
            if index is None:
                from ..timeline.studio_edit_sequence import source_cue_id_of
                index = lookup.get(source_cue_id_of(cue_id))
            if index is None:
                index = timeline._timeline_row_by_id.get(cue_id)
        state = ('#—' if not present else '#' + (str(index + 1) if index is not None else '·'), present)
        if getattr(self, '_cue_capsule_state', None) == state:
            return
        self._cue_capsule_state = state
        badge.setText(state[0])
        badge.setProperty('empty', not present)
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        for button in getattr(self, '_cue_capsule_buttons', ()):
            button.setEnabled(present)

    def _text_navigation_combination(self, sequence):
        cached = getattr(self, '_navigation_text_key_cache', None)
        if cached is not None and cached[0] == sequence:
            return cached[1]
        from .shortcut_registry import normalize
        parts = set(sequence.split('+')[:-1])
        safe = (bool(parts & {'Ctrl', 'Alt', 'Meta'}) and not {'Ctrl', 'Alt'} <= parts
                and sequence.split('+')[-1] not in {'Return', 'Enter', 'Esc', 'Escape', 'Tab', 'Backtab'})
        if safe:
            standard = {normalize(binding.toString(QKeySequence.PortableText))
                        for key in QKeySequence.StandardKey for binding in QKeySequence.keyBindings(key)}
            safe = sequence not in standard
        self._navigation_text_key_cache = (sequence, safe)
        return safe

    def _subtitle_navigation_text_shortcut(self, sequence):
        from .shortcut_registry import normalize
        sequence = normalize(sequence)
        if self._shortcut_lookup.get(sequence) != COMMAND:
            return False
        if getattr(self, '_studio_ime_composing', False):
            return False
        editor = getattr(self, 'subtitle_edit_input', None)
        if (editor is None or not getattr(self, '_caption_following', False)
                or not self._caption_window_owns(editor.focusWidget())
                or getattr(editor, '_preediting', False)
                or getattr(editor, '_ime_commit_key_pending', False)):
            return False
        # Standard text/application editing keys and AltGr retain ownership,
        # even when a user assigns one of them to this navigation action.
        return self._text_navigation_combination(sequence)

    def _subtitle_navigation_key_event(self, watched, event):
        if event.type() not in (QEvent.KeyPress, QEvent.ShortcutOverride):
            return False
        from .shortcut_registry import normalize
        sequence = normalize(QKeySequence(event.keyCombination()).toString(QKeySequence.PortableText))
        if self._shortcut_lookup.get(sequence) != COMMAND:
            return False
        owns_float = self._caption_window_owns(watched) if getattr(self, '_caption_following', False) else False
        if not self.isVisible() and not owns_float:
            return False
        if self._native_keys_blocked():
            return False
        if self._editing_has_focus() and not self._text_navigation_combination(sequence):
            return False
        editor = getattr(self, 'subtitle_edit_input', None)
        composing = (getattr(self, '_studio_ime_composing', False)
                     or getattr(editor, '_preediting', False)
                     or getattr(editor, '_ime_commit_key_pending', False))
        if composing:
            parts = set(sequence.split('+')[:-1])
            if owns_float and parts & {'Ctrl', 'Alt', 'Meta'} and not {'Ctrl', 'Alt'} <= parts:
                # The registered combination is suspended during composition.
                # Do not let its letter leak into the draft as ordinary text.
                event.accept()
                return True
            return False
        if self._editing_has_focus() and not self._subtitle_navigation_text_shortcut(sequence):
            return False
        if event.type() == QEvent.KeyPress:
            self._dispatch_shortcut_key(sequence, auto_repeat=event.isAutoRepeat(), timestamp=event.timestamp())
        event.accept()
        return True
