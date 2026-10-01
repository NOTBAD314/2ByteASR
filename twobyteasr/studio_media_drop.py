"""Atomic, ordered media drops with asynchronous probing outside the GUI thread."""
import copy
from pathlib import Path

from PySide6.QtGui import QUndoCommand

from .studio_edit_sequence import VideoSegment, sequence_of, replace_runtime_sequence
from .studio_media_pool import add_media_asset, add_video_clip, create_video_track, primary_video_track_id
from .studio_runtime_state import DirtyDomain, state_for


class MediaDropCommand(QUndoCommand):
    def __init__(self, project, results, position_ms, track_id=""):
        super().__init__("拖入媒体")
        self.project = project
        self.before = self._snapshot(project)
        working = copy.deepcopy(project)
        total = sum(r.duration_ms for r in results)
        position = max(0, int(position_ms))
        selected = track_id or str(working.studio_state.get("selected_video_track_id") or "")
        tracks = sorted(working.video_tracks, key=lambda t: t.id != selected)
        track = next((t for t in tracks if not t.locked and (not track_id or t.id == track_id)
                      and not any(c.timeline_in_ms < position+total and c.timeline_out_ms > position
                                  for c in t.clips)), None)
        track = track or create_video_track(working, locked=False)
        primary = primary_video_track_id(working)
        sequence = sequence_of(working)
        if not working.media.path:
            sequence.segments = []
            first = results[0]
            working.media.path = first.source_path
            working.media.display_name = Path(first.source_path).name
            working.media.duration_ms = first.duration_ms
            working.media.width, working.media.height = first.width, first.height
            working.media.fingerprint = first.fingerprint
            sequence.source_path = first.source_path
            sequence.source_duration_ms = first.duration_ms
            sequence.video_track_locked = False
        for result in results:
            if result.error or result.duration_ms <= 0:
                raise ValueError(result.error or f"媒体时长无效：{result.source_path}")
            asset = add_media_asset(working, result.source_path, fingerprint=result.fingerprint,
                duration_ms=result.duration_ms,
                video_metadata={"width":result.width,"height":result.height,"fps":result.fps,
                    "has_video":result.has_video,"source_start_ms":result.source_start_ms},
                audio_metadata={"has_audio":result.has_audio,"sample_rate":result.sample_rate,
                    "channels":result.channels,"stream_index":0,
                    "source_start_ms":result.source_start_ms,
                    "sample_timeline_origin_ms":result.sample_timeline_origin_ms})
            clip = add_video_clip(working, track.id, asset.asset_id, timeline_in_ms=position)
            if track.id == primary:
                sequence.segments.append(VideoSegment(id=clip.id, source_path=result.source_path,
                    source_in_ms=0, source_out_ms=result.duration_ms,
                    timeline_in_ms=position, timeline_out_ms=position+result.duration_ms))
            position += result.duration_ms
        sequence.segments.sort(key=lambda s: (s.timeline_in_ms, s.id))
        working.studio_state["selected_video_track_id"] = track.id
        working.validate()
        self.after = self._snapshot(working)

    @staticmethod
    def _snapshot(project):
        return {"media":copy.deepcopy(project.media), "media_pool":copy.deepcopy(project.media_pool),
            "video_tracks":copy.deepcopy(project.video_tracks), "audio_tracks":copy.deepcopy(project.audio_tracks),
            "av_track_groups":copy.deepcopy(project.av_track_groups),
            "sequence":copy.deepcopy(sequence_of(project)),
            "selected_video_track_id":project.studio_state.get("selected_video_track_id", "")}

    def _apply(self, data):
        dirty = (DirtyDomain.MEDIA_POOL | DirtyDomain.VIDEO_TRACKS | DirtyDomain.AUDIO_TRACKS
                 | DirtyDomain.SEQUENCE_STRUCTURE | DirtyDomain.TIMELINE_INDEX | DirtyDomain.TIMELINE_PIXELS
                 | DirtyDomain.MEDIA_TIMING | DirtyDomain.VIDEO_COMPOSITION | DirtyDomain.AUTOSAVE
                 | DirtyDomain.PROJECT_METADATA)
        with state_for(self.project).transaction(self.project, action_id="media_drop", dirty=dirty):
            for key in ("media","media_pool","video_tracks","audio_tracks","av_track_groups"):
                setattr(self.project, key, copy.deepcopy(data[key]))
            replace_runtime_sequence(self.project, copy.deepcopy(data["sequence"]))
            self.project.studio_state["selected_video_track_id"] = data["selected_video_track_id"]

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
