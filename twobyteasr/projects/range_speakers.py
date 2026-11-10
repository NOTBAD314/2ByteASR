"""Conservative retirement of unreferenced, unchanged range-task identities."""
import copy
import re
from dataclasses import asdict

KEY = 'range_auto_speakers'
STATE_KEYS = ('speaker_track_order', 'speaker_roles', 'locked_speakers',
              'caption_ripple_disabled_speakers', 'collapsed_speakers')
METADATA_KEYS = (KEY, 'speaker_names')


def capture_roster(project):
    return (copy.deepcopy(project.speakers),
            {key: copy.deepcopy(project.studio_state[key]) for key in STATE_KEYS if key in project.studio_state},
            {key: copy.deepcopy(project.generation_metadata[key]) for key in METADATA_KEYS if key in project.generation_metadata})


def restore_roster(project, snapshot):
    speakers, state, metadata = copy.deepcopy(snapshot)
    project.speakers = speakers
    for target, keys, values in ((project.studio_state, STATE_KEYS, state),
                                 (project.generation_metadata, METADATA_KEYS, metadata)):
        for key in keys:
            target.pop(key, None)
        target.update(values)


def register_range_speakers(project, speakers):
    if speakers:
        records = project.generation_metadata.setdefault(KEY, {})
        for speaker in speakers:
            records.setdefault(speaker.id, asdict(speaker))


def orphan_range_speakers(project):
    # Canonical captions include hidden and disabled tracks. A UI filter is
    # never evidence that an identity has no references.
    referenced = {cue.speaker_id for cue in project.cues}
    protected = set(project.studio_state.get('locked_speakers') or ())
    protected.update((project.studio_state.get('speaker_roles') or {}).get('manual') or {})
    protected.update((project.generation_metadata.get('speaker_organization') or {}).get('manual') or {})
    organization = project.generation_metadata.get('speaker_organization') or {}
    protected.update(sid for sid, decision in (organization.get('decisions') or {}).items()
                     if decision == 'main')
    recovery = project.generation_metadata.get('speaker_recovery') or {}
    review = recovery.get('voiceprint_review') or {}
    if review.get('reviewed_by') == 'user':
        protected.update(review.get('members') or {})
    protected.update((project.generation_metadata.get('subtitle_imports') or {}).get('tracks') or {})
    records = project.generation_metadata.get(KEY) or {}
    legacy = {sid for row in project.generation_metadata.get('range_recognitions') or ()
              if isinstance(row, dict) for sid in (row.get('speaker_map') or {}).values()}
    result = []
    for speaker in project.speakers:
        if speaker.id in referenced or speaker.id in protected or speaker.hidden or speaker.is_host:
            continue
        original = records.get(speaker.id)
        unchanged = original == asdict(speaker) if original is not None else (
            speaker.id in legacy and speaker.id.startswith('range-')
            and re.fullmatch(r'局部识别 · S\d+（待确认）', speaker.name or '')
            and speaker.style_id == 'default' and not speaker.color)
        if unchanged:
            result.append(speaker.id)
    return result


def clean_range_speakers(project):
    removed = set(orphan_range_speakers(project))
    if not removed:
        return ()
    project.speakers = [speaker for speaker in project.speakers if speaker.id not in removed]
    for key in ('speaker_track_order', 'caption_ripple_disabled_speakers', 'collapsed_speakers'):
        if key in project.studio_state:
            project.studio_state[key] = [sid for sid in project.studio_state[key] if sid not in removed]
    roles = project.studio_state.get('speaker_roles') or {}
    if isinstance(roles.get('auto'), dict):
        roles['auto'] = {sid: role for sid, role in roles['auto'].items() if sid not in removed}
    for mapping in (project.generation_metadata.get(KEY),
                    (project.generation_metadata.get('speaker_names') or {}).get('entries')):
        if isinstance(mapping, dict):
            for sid in removed:
                mapping.pop(sid, None)
    return tuple(sorted(removed))
