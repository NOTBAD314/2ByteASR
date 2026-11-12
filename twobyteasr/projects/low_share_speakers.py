"""A one-time editorial default, after final identity/voiceprint merging."""
import copy
from collections import defaultdict

POLICY = 'low-share-speakers-v2-retain'
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
    # Text amount is presentation evidence, never permission to discard speech.
    result = project
    if result is project:
        result = copy.copy(project)
        result.generation_metadata = dict(project.generation_metadata)
    organization = copy.deepcopy(result.generation_metadata.get('speaker_organization') or {})
    organization['low_share_policy'] = dict(version=POLICY, total_cues=total, ignored={}, retained=eligible,
        max_cues=MAX_CUES, max_share=MAX_SHARE, max_speech_ms=MAX_SPEECH_MS)
    result.generation_metadata['speaker_organization'] = organization
    return result


def restore_automatic_low_share(project):
    """Restore only v1 system ignores from their exact saved cues; no raw ASR replay."""
    from ..recognition.speaker_recovery import apply_candidate_role
    organization = project.generation_metadata.get('speaker_organization') or {}
    if not isinstance(organization,dict):return project
    policy = organization.get('low_share_policy') or {}
    if not isinstance(policy,dict) or not isinstance(policy.get('ignored',{}),dict):return project
    if policy.get('version') != 'low-share-speakers-v1':
        return project
    result = copy.deepcopy(project)
    restored = []
    for label in policy.get('ignored', {}):
        state = result.generation_metadata.get('speaker_recovery') or {}
        if not isinstance(state,dict):continue
        if (state.get('role_decisions', {}).get(label) != 'low_share'
                or state.get('roles', {}).get(label) != 'ignore'
                or not state.get('cue_cache', {}).get(label)):
            continue
        state = copy.deepcopy(state)
        state['allow_raw_recovery'] = False
        replacement = apply_candidate_role(result, state, label, 'unconfirmed', decision_source='low_share_restore')
        if replacement is not None:
            restored_state=replacement.generation_metadata['speaker_recovery']
            restored_state['confirmed_by']='system_low_share_restore'
            restored_state.setdefault('reasons',{})[label]='旧版低占比规则已撤回；字幕恢复，身份仍待确认。'
            before = {c.id for c in result.cues}
            restored.extend(c.id for c in replacement.cues if c.id not in before)
            result = replacement
    if result is project:
        result = copy.copy(project)
        result.generation_metadata = copy.deepcopy(project.generation_metadata)
    record = result.generation_metadata['speaker_organization']['low_share_policy']
    record.update(version=POLICY, restored_ids=restored, previous_ignored=copy.deepcopy(policy.get('ignored', {})), ignored={})
    if restored:
        from ..timeline.studio_caption_timeline import ensure_independent_captions
        ensure_independent_captions(result)
    if restored:
        result.validate()
    return result
