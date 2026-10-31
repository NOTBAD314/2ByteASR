"""A one-time editorial default, after final identity/voiceprint merging."""
import copy
from collections import defaultdict

POLICY = 'low-share-speakers-v1'
MAX_CUES = 3
MAX_SHARE = .005
MAX_SPEECH_MS = 10000


def apply_low_share_policy(project):
    from ..recognition.speaker_recovery import apply_candidate_role, load_candidate_snapshot
    organization = project.generation_metadata.get('speaker_organization') or {}
    if organization.get('low_share_policy') or not project.cues:
        return None
    try:
        snapshot = load_candidate_snapshot(project)
    except (ValueError, KeyError, TypeError):
        return None
    if not snapshot:
        return None
    groups = defaultdict(list)
    for cue in project.cues:
        groups[cue.speaker_id].append(cue)
    decisions = organization.get('decisions') or {}
    manual_groups = project.studio_state.get('speaker_roles', {}).get('manual') or {}
    roles = snapshot.get('roles') or {}
    explicit = snapshot.get('role_decisions') or {}
    eligible = {}
    total = len(project.cues)
    for speaker in project.speakers:
        cues = groups[speaker.id]
        if (not cues or speaker.is_host or speaker.id in decisions or speaker.id in manual_groups
                or speaker.id in explicit or roles.get(speaker.id, 'unconfirmed') != 'unconfirmed'):
            continue
        intervals = sorted((c.start_ms, c.end_ms) for c in cues)
        spoken = 0
        previous = -1
        for start, end in intervals:
            spoken += max(0, end-max(start, previous))
            previous = max(previous, end)
        if len(cues) <= MAX_CUES and len(cues)/total <= MAX_SHARE and spoken <= MAX_SPEECH_MS:
            eligible[speaker.id] = dict(cues=len(cues), share=len(cues)/total, speech_ms=spoken)
    result = project
    for label, stats in eligible.items():
        result = apply_candidate_role(result, snapshot, label, 'ignore', decision_source='low_share')
        snapshot = result.generation_metadata['speaker_recovery']
        snapshot.setdefault('reasons', {})[label] = '低占比自动忽略：{cues}条、{share:.2%}、{seconds:.1f}秒；可恢复。'.format(
            **stats, seconds=stats['speech_ms']/1000)
    if result is project:
        result = copy.copy(project)
        result.generation_metadata = dict(project.generation_metadata)
    organization = copy.deepcopy(result.generation_metadata.get('speaker_organization') or {})
    organization['low_share_policy'] = dict(version=POLICY, total_cues=total, ignored=eligible,
        max_cues=MAX_CUES, max_share=MAX_SHARE, max_speech_ms=MAX_SPEECH_MS)
    result.generation_metadata['speaker_organization'] = organization
    return result
