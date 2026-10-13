"""Undoable removal of timeline references, with explicit header focus."""
from __future__ import annotations
import copy

from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QApplication

from .studio_runtime_state import DirtyDomain as D, state_for
from .studio_edit_sequence import sequence_of, replace_runtime_sequence


class AddSubtitleTrackCommand(QUndoCommand):
    def __init__(self, page):
        super().__init__('新建字幕轨道')
        import uuid
        from .studio_project import StudioSpeaker
        self.page, self.project = page, page.project
        self.speaker = StudioSpeaker('S'+uuid.uuid4().hex[:10], name=f'字幕轨 {len(page.project.speakers)+1}')
        self.before_order = list(page.project.studio_state.get('speaker_track_order', []))
        self.before_header = page.timeline.selected_track_header

    def _apply(self, forward):
        page, project = self.page, self.project
        dirty = D.CUE_MODEL | D.CUE_TIMING | D.TIMELINE_INDEX | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.AUTOSAVE | D.TIMELINE_PIXELS
        with state_for(project).transaction(project, action_id=self.text(), dirty=dirty):
            if forward:
                project.speakers.append(copy.deepcopy(self.speaker))
                project.studio_state['speaker_track_order'] = self.before_order+[self.speaker.id]
            else:
                project.speakers = [s for s in project.speakers if s.id != self.speaker.id]
                project.studio_state['speaker_track_order'] = list(self.before_order)
        if page.project is project:
            page._populate_speakers()
            page.timeline.reindex_project()
            page.timeline.selected_track_header = ('subtitle',self.speaker.id) if forward else self.before_header
            page.timeline.setFocus()
            page.timeline.update()
            page.ensure_active_subtitle_renderer(reason='add_subtitle_track')

    def redo(self):self._apply(True)
    def undo(self):self._apply(False)


def add_subtitle_track(page):
    if page.project is not None:page.undo_stack.push(AddSubtitleTrackCommand(page))


class DeleteTrackCommand(QUndoCommand):
    def __init__(self, project, kind, track_id, page=None, *, clip_ids=None):
        super().__init__('删除视频片段及关联音频' if clip_ids is not None else delete_label(project, kind, track_id))
        self.project, self.page = project, page
        self.kind, self.track_id = kind, track_id
        self.fields = ('cues', 'speakers', 'render_settings') if kind == 'subtitle' else ('video_tracks', 'audio_tracks', 'av_track_groups', 'cues', 'render_settings')
        self.before = {key: copy.deepcopy(getattr(project, key)) for key in self.fields}
        self.after = copy.deepcopy(self.before)
        self.before_state = copy.deepcopy(project.studio_state)
        self.after_state = copy.deepcopy(project.studio_state)
        working_captions = copy.copy(project)
        working_captions.cues = copy.deepcopy(project.cues)
        working_captions.render_settings = copy.deepcopy(project.render_settings)
        working_captions.studio_state = self.after_state
        from .studio_caption_timeline import ensure_independent_captions
        ensure_independent_captions(working_captions)
        self.after['cues'] = copy.deepcopy(working_captions.cues)
        self.after['render_settings'] = copy.deepcopy(working_captions.render_settings)
        self.before_sequence = copy.deepcopy(sequence_of(project))
        self.after_sequence = copy.deepcopy(self.before_sequence)
        self.sequence_changed = False
        self.playhead_before = int(page.timeline.playhead_ms) if page else None
        self.selected_before = state_for(project).selected_cue_id
        self.selected_after = self.selected_before
        self.ui_before = {}
        if page is not None:
            for key in ('selection_scope','selected_track_header','selected_id','selected_ids','selected_video_track_id',
                        'selected_video_clip_id','selected_audio_track_id','selected_segment_id','selected_segment_ids',
                        'hidden_speakers','locked_speakers'):
                if hasattr(page.timeline,key):self.ui_before[key] = copy.deepcopy(getattr(page.timeline,key))
        if kind == 'subtitle':
            if page and track_id in page.timeline.locked_speakers:
                raise ValueError('轨道已锁定，请先解锁')
            if not any(s.id == track_id for s in project.speakers):raise KeyError(track_id)
            self.after['cues'] = [c for c in self.after['cues'] if c.speaker_id != track_id]
            self.after['speakers'] = [s for s in self.after['speakers'] if s.id != track_id]
            if self.selected_after not in {c.id for c in self.after['cues']}:
                self.selected_after = next((c.id for c in self.after['cues']), '')
            self.after_state['speaker_track_order'] = [key for key in self.after_state.get('speaker_track_order', []) if key != track_id]
            self.dirty = D.CUE_MODEL | D.CUE_TIMING | D.TIMELINE_INDEX | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.CUE_SELECTION
        else:
            videos = {track_id} if kind == 'video' else set()
            audios = {track_id} if kind == 'audio' else set()
            for group in project.av_track_groups:
                if group.linked and (group.video_track_id in videos or group.audio_track_id in audios):
                    videos.add(group.video_track_id);audios.add(group.audio_track_id)
            tracks = [t for t in (*project.video_tracks,*project.audio_tracks) if t.id in videos | audios]
            if not tracks:raise KeyError(track_id)
            if any(t.locked for t in tracks):raise ValueError('关联轨道已锁定，请先解锁')
            from .studio_media_pool import primary_video_track_id
            if primary_video_track_id(project) in videos and self.before_sequence.video_track_locked:
                raise ValueError('视频轨道已锁定，请先解锁')
            if kind == 'video' and clip_ids is None:
                # Removing a video lane owns only its actual linked clips.
                # An audio lane containing independent material must survive.
                removed_ids = {c.id for t in project.video_tracks if t.id in videos for c in t.clips}
                for sound in self.after['audio_tracks']:
                    if sound.id in audios:
                        independent = [c for c in sound.clips if c.linked_video_clip_id not in removed_ids]
                        if independent:
                            sound.clips = independent
                            audios.remove(sound.id)
            if clip_ids is not None:
                ids = set(clip_ids)
                target = next(t for t in self.after['video_tracks'] if t.id == track_id)
                if not ids or not ids <= {c.id for c in target.clips}:raise KeyError('所选片段已不存在')
                target.clips = [c for c in target.clips if c.id not in ids]
                for sound in self.after['audio_tracks']:
                    if sound.id in audios:
                        sound.clips = [c for c in sound.clips if c.linked_video_clip_id not in ids]
                if track_id == primary_video_track_id(project):
                    self.after_sequence.segments = [s for s in self.after_sequence.segments if s.id not in ids]
                    self.after_sequence.empty_timeline = not self.after_sequence.segments
                    self.sequence_changed = True
                # Only this edit's now-empty group is eligible for removal.
                if target.clips or any(t.clips for t in self.after['audio_tracks'] if t.id in audios):
                    videos.clear();audios.clear()
            self.after['video_tracks'] = [t for t in self.after['video_tracks'] if t.id not in videos]
            self.after['audio_tracks'] = [t for t in self.after['audio_tracks'] if t.id not in audios]
            for sound in self.after['audio_tracks']:
                if sound.linked_video_track_id in videos:
                    sound.linked_video_track_id = ''
                    for clip in sound.clips:
                        clip.linked_video_clip_id = '';clip.link_group_id = ''
            self.after['av_track_groups'] = [g for g in self.after['av_track_groups'] if g.video_track_id not in videos and g.audio_track_id not in audios]
            self.after_state['audio_solo_track_ids'] = [key for key in self.after_state.get('audio_solo_track_ids', []) if key not in videos | audios]
            gains = self.after_state.get('audio_track_gain_db')
            if isinstance(gains, dict):
                for key in videos | audios:gains.pop(key,None)
            if primary_video_track_id(project) in videos:
                from .studio_edit_sequence import VideoSegment
                new_primary = next(iter(self.after['video_tracks']), None)
                self.after_state['primary_video_track_id'] = new_primary.id if new_primary else ''
                assets = {a.asset_id:a for a in project.media_pool}
                self.after_sequence.segments = [VideoSegment(c.id, assets[c.asset_id].canonical_source,
                    c.source_in_ms,c.source_out_ms,c.timeline_in_ms,c.timeline_out_ms) for c in new_primary.clips] if new_primary else []
                self.after_sequence.empty_timeline = not self.after_sequence.segments
                self.after_sequence.video_track_locked = bool(new_primary and new_primary.locked)
                self.sequence_changed = True
            # Removal of an explicitly chosen old owner ends that exclusive
            # choice; undo restores it. A remaining offline Solo stays Solo.
            if self.after_state.get('audio_master_track_id') in videos | audios:
                self.after_state['audio_master_track_id'] = ''
                self.after_state['audio_master_mode'] = 'mix_all'
            if not self.after['video_tracks'] and not self.after['audio_tracks']:
                self.after_sequence.segments=[];self.after_sequence.empty_timeline=True;self.sequence_changed=True
            self.dirty = D.VIDEO_TRACKS | D.AUDIO_TRACKS | D.MEDIA_TIMING | D.VIDEO_COMPOSITION | D.TIMELINE_INDEX
            # Preflight projected captions and range markers on a detached
            # graph. Ordinary Delete leaves all remaining timeline gaps intact.
            from .studio_clip_edit import _locked_caption_ranges
            from .studio_edit_sequence import EditSequenceRuntime, timeline_duration_ms
            working = copy.copy(project)
            for key, value in self.after.items():setattr(working, key, copy.deepcopy(value))
            working.studio_state = self.after_state
            working._edit_sequence_runtime = EditSequenceRuntime(self.after_sequence)
            locked = set(page.timeline.locked_speakers) if page else set()
            if locked and _locked_caption_ranges(project, locked) != _locked_caption_ranges(working, locked):
                raise ValueError('关联字幕轨道已锁定，请先解锁；此次删除未提交')
            try:
                from .studio_transitions import reconcile_transitions
            except ImportError:
                pass
            else:
                reconcile_transitions(working)
            duration = timeline_duration_ms(working)
            for name in ('in_point_ms', 'out_point_ms'):
                value = getattr(self.after_sequence, name)
                if value is not None:setattr(self.after_sequence, name, min(max(0, value), duration))
            if (self.after_sequence.in_point_ms is not None and self.after_sequence.out_point_ms is not None
                    and self.after_sequence.out_point_ms <= self.after_sequence.in_point_ms):
                self.after_sequence.in_point_ms = self.after_sequence.out_point_ms = None
            self.sequence_changed |= self.before_sequence != self.after_sequence
            self.dirty |= D.SEQUENCE_STRUCTURE | D.CUE_TIMING | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW
        self.dirty |= D.AUTOSAVE | D.TIMELINE_PIXELS | D.PROJECT_METADATA | D.CUE_MODEL | D.CUE_TIMING
        self.state_keys = {key for key in self.before_state.keys() | self.after_state.keys()
                           if self.before_state.get(key) != self.after_state.get(key)}

    def _apply(self, undo):
        project = self.project
        fields = self.before if undo else self.after
        state = self.before_state if undo else self.after_state
        selected = self.selected_before if undo else self.selected_after
        if self.page and self.kind != 'subtitle':self.page._defer_clip_edit_seek = True
        try:
            with state_for(project).transaction(project, action_id=self.text(), dirty=self.dirty,
                                                selection_after=selected):
                for key,value in fields.items():setattr(project,key,copy.deepcopy(value))
                for key in self.state_keys:
                    if key in state:project.studio_state[key]=copy.deepcopy(state[key])
                    else:project.studio_state.pop(key,None)
                if self.sequence_changed:
                    replace_runtime_sequence(project,copy.deepcopy(self.before_sequence if undo else self.after_sequence))
        finally:
            if self.page and self.kind != 'subtitle':self.page._defer_clip_edit_seek = False
        page = self.page
        if page is not None and page.project is project:
            if not undo:
                page.timeline.selected_track_header = None
                page.timeline.selected_video_clip_id = ''
                page.timeline.selected_segment_id = '';page.timeline.selected_segment_ids.clear()
                if self.kind == 'subtitle':
                    page.timeline.hidden_speakers.discard(self.track_id)
                    page.timeline.locked_speakers.discard(self.track_id)
            page.timeline.reindex_project()
            if selected:page.select_cue(selected)
            if undo:
                for key,value in self.ui_before.items():setattr(page.timeline,key,copy.deepcopy(value))
                page.timeline.update()
            page.ensure_active_subtitle_renderer(reason='delete_track_undo' if undo else 'delete_track')
            if self.kind != 'subtitle':
                from .studio_edit_sequence import timeline_duration_ms
                target = min(self.playhead_before, timeline_duration_ms(project))
                page.timeline.set_playhead(target)
                page._seek(target / 1000.0)

    def redo(self):self._apply(False)
    def undo(self):self._apply(True)


def delete_track(page, kind, track_id):
    if page.project is None:return
    try:command = DeleteTrackCommand(page.project,kind,track_id,page)
    except (ValueError,KeyError) as exc:
        page.save_state.setText(str(exc));return
    page.undo_stack.push(command)


def delete_label(project, kind, track_id):
    if kind == 'subtitle':return '删除字幕轨道'
    paired = any(g.linked and track_id == (g.video_track_id if kind == 'video' else g.audio_track_id)
                 for g in project.av_track_groups)
    return '删除视频及关联音频轨' if paired else '删除视频轨道' if kind == 'video' else '删除音频轨道'


def delete_clips(page, track_id, clip_ids):
    if page.project is None:return
    try:command = DeleteTrackCommand(page.project, 'video', track_id, page, clip_ids=clip_ids)
    except (ValueError, KeyError) as exc:
        page.save_state.setText(str(exc));return
    page.undo_stack.push(command)


def delete_current(page):
    if page._editing_has_focus():return
    timeline = page.timeline
    if timeline.hasFocus() and getattr(timeline, 'selected_gap', None):
        page._delete_timeline_gap()
        return
    header = getattr(timeline,'selected_track_header',None)
    if timeline.hasFocus() and header:
        delete_track(page,*header)
        return
    if timeline.hasFocus() and timeline.selected_segment_ids:
        track = next((t for t in page.project.video_tracks if timeline.selected_segment_ids <= {c.id for c in t.clips}), None)
        if track:
            delete_clips(page, track.id, timeline.selected_segment_ids)
        return
    clip_id = str(getattr(timeline,'selected_video_clip_id','') or '')
    if timeline.hasFocus() and clip_id and not timeline.selected_segment_ids:
        track = next((t for t in page.project.video_tracks if any(c.id==clip_id for c in t.clips)),None)
        if track:
            delete_clips(page,track.id,[clip_id])
            return
    return page.cue_controller.delete_current()


def track_menu(page, kind, track_id, pos):
    from .studio_theme import create_studio_menu
    menu = create_studio_menu(page)
    if kind == 'subtitle':
        from .studio_speaker_roles import GROUP_KEY, group_actions, role_menu
        if track_id == GROUP_KEY:
            # The shared secondary row: group-wide actions only.
            group_actions(page, menu)
            menu.exec(pos)
            return
        from .studio_caption_timeline import DISABLED_KEY,set_caption_ripple_command
        from .i18n import tr
        enabled=track_id not in page.project.studio_state.get(DISABLED_KEY,[])
        action=menu.addAction(tr('跟随波纹编辑'))
        action.setCheckable(True);action.setChecked(enabled)
        action.triggered.connect(lambda checked:page.undo_stack.push(set_caption_ripple_command(page.project,track_id,checked)))
        role_menu(page, menu, track_id)
        menu.addSeparator()
    if kind == 'audio':
        track = next((t for t in page.project.audio_tracks if t.id == track_id), None)
        if track is None:return
        menu.addAction('轨道音量…    G',lambda:page._show_track_gain(track_id))
        menu.addAction('恢复声音' if track.muted else '静音轨道',lambda:page._audio_track_action(track_id,'muted'))
        menu.addAction('取消 Solo' if track.soloed else 'Solo / 独听此轨',lambda:page._audio_track_action(track_id,'solo'))
        missing = {a.asset_id for a in page.project.media_pool if a.offline}
        clip = next((c for c in track.clips if c.asset_id in missing and c.timeline_in_ms <= page.timeline.playhead_ms < c.timeline_out_ms),None)
        if clip:menu.addAction('重新链接素材…',lambda:page.media_availability.choose_relink(clip.asset_id))
    menu.addAction(delete_label(page.project,kind,track_id)+'    Delete',lambda:delete_track(page,kind,track_id))
    menu.exec(pos)
