"""One data-only, committed document version for a subtitle export task."""
from __future__ import annotations

import marshal
from dataclasses import dataclass, fields, is_dataclass


def _record(value):
    # Declared document fields only. Never traverse __dict__, runtime owners,
    # callbacks, or __deepcopy__ supplied by a GUI object.
    result = {}
    for field in fields(value):
        item = getattr(value, field.name)
        if is_dataclass(item):
            item = _record(item)
        elif isinstance(item, list):
            item = [_record(row) if is_dataclass(row) else row for row in item]
        result[field.name] = item
    return result


def _receipt_evidence_refs(value, refs, visited):
    if type(value) not in (dict, list, tuple) or id(value) in visited:
        return
    visited.add(id(value))
    if type(value) is dict:
        for key, item in value.items():
            if key in {'evidence_ref', 'source_ref'} and isinstance(item, str):
                refs.add(item)
            elif key == 'evidence_refs' and isinstance(item, (list, tuple)):
                refs.update(ref for ref in item if isinstance(ref, str))
            else:
                _receipt_evidence_refs(item, refs, visited)
    else:
        for item in value:
            _receipt_evidence_refs(item, refs, visited)


@dataclass(frozen=True)
class SubtitleSnapshot:
    project_id: str
    revision: int
    data: bytes
    cue_count: int = 0

    @classmethod
    def capture(cls, project):
        from ..timeline.studio_edit_sequence import sequence_of
        runtime = getattr(project, '_studio_state_runtime', None)
        if runtime is not None and runtime._active is not None:
            raise RuntimeError('不能在编辑事务提交前创建导出快照')
        payload = {name: getattr(project, name) for name in (
            'project_id', 'schema_version', 'created_at', 'updated_at',
            'effects', 'style_recipes', 'generation_metadata', 'asr_evidence',
            'glossary_ids', 'render_settings', 'studio_state')}
        payload['media'] = _record(project.media)
        for name in ('cues', 'speakers', 'styles', 'media_pool', 'video_tracks', 'audio_tracks', 'av_track_groups'):
            payload[name] = [_record(item) for item in getattr(project, name)]
        # Export uses the current mapping, including an unpersisted edit.
        payload['edit_sequence'] = sequence_of(project).to_dict()
        # These document histories are unrelated to subtitle delivery. The
        # caption archive and active receipts remain in studio_state.
        payload['generation_metadata'] = {key: value for key, value in project.generation_metadata.items()
                                          if key != 'range_recognitions'}
        payload['studio_state'] = {key: value for key, value in project.studio_state.items()
                                   if key not in {'review_risks', 'review_confirmations',
                                                  'cue_statuses', 'glossary_proofread_review'}}
        refs = {'cue-align:' + cue.id for cue in project.cues if isinstance(cue.id, str)}
        refs.update(ref for cue in project.cues if isinstance(cue.evidence_refs, (list, tuple))
                    for ref in cue.evidence_refs if isinstance(ref, str))
        timeline = project.studio_state.get('caption_timeline')
        instances = timeline.get('instances') if isinstance(timeline, dict) else None
        instances = instances if isinstance(instances, dict) else {}
        visited = set()
        for cue in project.cues:
            if isinstance(cue.id, str):
                _receipt_evidence_refs(instances.get(cue.id), refs, visited)
        if isinstance(project.asr_evidence, dict):
            payload['asr_evidence'] = {key: value for key, value in project.asr_evidence.items() if key in refs}
        # marshal accepts data values and rejects Qt objects, locks and custom
        # instances without executing their copy/reduction hooks.
        return cls(project.project_id, int(getattr(runtime, 'revision', 0)), marshal.dumps(payload, 4), len(project.cues))

    def materialize(self):
        from ..projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
            SubtitleStyle, MediaAsset, VideoTrack, VideoClip, VideoTransform, AudioTrack, AudioClip, AVTrackGroup)
        payload = marshal.loads(self.data)
        for name, model in (('cues', StudioCue), ('speakers', StudioSpeaker), ('styles', SubtitleStyle)):
            payload[name] = [model(**row) for row in payload[name]]
        payload['media'] = StudioMedia(**payload['media'])
        payload['media_pool'] = [MediaAsset(**row) for row in payload['media_pool']]
        payload['av_track_groups'] = [AVTrackGroup(**row) for row in payload['av_track_groups']]
        for row in payload['video_tracks']:
            row['clips'] = [VideoClip(**dict(clip, transform=VideoTransform(**clip['transform']))) for clip in row['clips']]
        for row in payload['audio_tracks']:
            row['clips'] = [AudioClip(**clip) for clip in row['clips']]
        payload['video_tracks'] = [VideoTrack(**row) for row in payload['video_tracks']]
        payload['audio_tracks'] = [AudioTrack(**row) for row in payload['audio_tracks']]
        project = SubtitleProject(**payload)
        project._subtitle_export_owned = True
        return project


def owned_export_project(project):
    if not getattr(project, '_subtitle_export_owned', False):
        project = SubtitleSnapshot.capture(project).materialize()
    if not getattr(project, '_subtitle_export_prepared', False):
        from ..projects.subtitle_consistency import validate_export_view, ValidationResult
        from .export_consistency import SubtitleDataError
        from .export_consistency import require_consistent_view
        from ..timeline.studio_edit_sequence import projected_cues
        import copy
        from ..diagnostics.subtitle_export_work import stage
        canonical = project.cues
        visible = project.visible_cues()
        intrinsic = {'cue_id_invalid', 'cue_id_duplicate', 'sentence_time_invalid',
                     'cue_text_invalid', 'speaker_id_invalid', 'speaker_reference_missing'}
        with stage('validate_model'):
            errors = tuple(issue for issue in validate_export_view(project, visible).errors
                           if issue.code in intrinsic)
            if errors:
                raise SubtitleDataError(ValidationResult(errors=errors))
            selected = copy.copy(project)
            selected.cues = visible
            require_consistent_view(project, projected_cues(selected, domain='timeline'))
            # Normalization may initialize legacy media tracks and mutate
            # style/name records. Do it once on the detached document before
            # sharing it between scopes. Hidden invalid captions stay outside
            # the selected export, just as on the existing export boundary.
            project.cues = visible
            try:
                project.validate(owned=True)
            finally:
                project.cues = canonical
        project._subtitle_export_prepared = True
    return project
