"""Shared bounded display handoffs and local slot ownership.

All values use the caller's time unit. Speech observations are read-only.
"""
from __future__ import annotations

VERSION = 'display-continuity-v1'
MICRO_GAP_MS = 200
MAX_GAP_MS = 500
MAX_DISPLAY_MS = 5000


def chain_key(cue):
    speaker = getattr(cue, 'speaker_id', getattr(cue, 'speaker', ''))
    transform = getattr(cue, 'transform', {}) or {}
    track = getattr(cue, 'continuity_track', '') or transform.get('track_id', speaker)
    role = getattr(cue, 'caption_role', '') or transform.get('subtitle_role', 'original')
    return str(track), str(speaker), str(role)


def boundary_blocked(cue, receipt=None):
    transform = getattr(cue, 'transform', {}) or {}
    receipt = receipt or {}
    return bool(getattr(cue, 'timing_locked', False) or transform.get('timing_locked')
        or transform.get('display_break') or transform.get('no_display_extension')
        or transform.get('protected_end') or receipt.get('protected_end')
        or receipt.get('manual_timing') or receipt.get('display_break'))


def handoff_ends(rows, threshold=MAX_GAP_MS, *, micro=None, full_track=True,
                 same_speaker=True, max_duration=None, keys=None, blocked=(), continuous=(), audit=None):
    """Plan end-only changes, requiring evidence for larger-than-micro gaps."""
    micro = threshold * MICRO_GAP_MS / MAX_GAP_MS if micro is None else micro
    ordered = sorted(rows, key=lambda row:(row[2],row[3],str(row[0])))
    ends = {key:end for key,_,_,end in ordered}
    original = dict(ends)
    blocked, continuous = set(blocked), set(continuous)

    def permitted(left, right, end):
        key, _, start, _ = left
        gap = right[2]-end
        if not 0 < gap <= threshold:
            return False
        reason='bounded_display_continuation'
        if key in blocked or right[0] in blocked:
            reason='manual_or_source_boundary'
        elif max_duration is not None and right[2]-start > max_duration:
            reason='maximum_display_duration'
        elif gap > micro and (key,right[0]) not in continuous:
            reason='pause_without_continuation_evidence'
        accepted=reason=='bounded_display_continuation'
        if audit is not None:
            audit.append(dict(cue_id=key,successor_id=right[0],before=end,
                after=right[2] if accepted else end,reason=reason,accepted=accepted,
                stage='display_handoff_planning'))
        return accepted

    if same_speaker:
        lanes = {}
        for row in ordered:
            lanes.setdefault((keys or {}).get(row[0],row[1]),[]).append(row)
        for lane in lanes.values():
            for left,right in zip(lane,lane[1:]):
                if permitted(left,right,ends[left[0]]):
                    ends[left[0]] = right[2]
    if full_track and ordered:
        owner = ordered[0]
        cover = ends[owner[0]]
        for row in ordered[1:]:
            if permitted(owner,row,cover):
                ends[owner[0]] = cover = row[2]
            if ends[row[0]] > cover:
                owner, cover = row, ends[row[0]]
    return {key:end for key,end in ends.items() if end != original[key]}


def visible_display_cues(project, cues=None, *, mode=None):
    from ..caption_style.subtitle_visibility import any_layer_visible
    result=[]
    for cue in project.cues if cues is None else cues:
        transform=getattr(cue,'transform',{}) or {}
        if any_layer_visible(project,cue,mode=mode) and not transform.get('hidden') and transform.get('visible',True):
            result.append(cue)
    return result


def source_cut(left,right,left_receipt,right_receipt):
    left_clip=left.transform.get('source_clip_id') or left_receipt.get('source_clip_id')
    right_clip=right.transform.get('source_clip_id') or right_receipt.get('source_clip_id')
    if left_clip and right_clip and left_clip!=right_clip:
        return True
    left_path,right_path=left_receipt.get('source_path'),right_receipt.get('source_path')
    from os.path import normcase
    if left_path and right_path and normcase(str(left_path))!=normcase(str(right_path)):
        return True
    source_end,source_start=left_receipt.get('source_end_ms'),right_receipt.get('source_start_ms')
    if isinstance(source_end,(int,float)) and isinstance(source_start,(int,float)):
        return abs((source_start-source_end)-(right.start_ms-left.end_ms))>MAX_GAP_MS
    return False


def layout_cues(project,cues):
    """Read-only proxies carry persisted manual/cut boundaries into layouts."""
    from copy import copy
    receipts=project.studio_state.get('caption_timeline',{}).get('instances',{})
    rows=[]
    previous={}
    for cue in sorted(cues,key=lambda c:(c.start_ms,c.end_ms,c.id)):
        receipt=receipts.get(cue.id,{})
        row=copy(cue)
        row.continuity_break=bool(receipt.get('protected_start') or receipt.get('protected_end')
                                  or receipt.get('manual_timing') or receipt.get('display_break'))
        key=chain_key(cue)
        prior=previous.get(key)
        if prior is not None and source_cut(prior,row,receipts.get(prior.id,{}),receipt):
            row.continuity_break=True
            prior.continuity_break=True
        previous[key]=row
        rows.append(row)
    return rows


def project_handoff_plan(project, selected=(), *, progress=None, audit=None):
    from .segmentation_profiles import profile_for, project_language_tag
    rows, keys, blocked = [], {}, set()
    receipts = project.studio_state.get('caption_timeline',{}).get('instances',{})
    source_parts = project.generation_metadata.get('segmentation_source_spans',{}).get('cues',{})
    selected = set(selected)
    locked=set(project.studio_state.get('locked_speakers',[]))
    ordered = sorted(visible_display_cues(project),key=lambda c:(c.start_ms,c.end_ms,c.id))
    continuous, previous = set(), {}
    for number,cue in enumerate(ordered):
        if progress and number % 256 == 0 and not progress(number,len(ordered)):
            return None
        rows.append((cue.id,cue.speaker_id,cue.start_ms,cue.end_ms))
        keys[cue.id] = key = chain_key(cue)
        receipt = receipts.get(cue.id,{})
        tail = cue.transform.get('display_handoff',{})
        stale = tail and [cue.start_ms,cue.end_ms] != tail.get('display_interval_ms')
        if (boundary_blocked(cue,receipt) or cue.speaker_id in locked or stale or (selected and cue.id not in selected)
                or cue.transform.get('protected_start') or receipt.get('protected_start')):
            blocked.add(cue.id)
        prior = previous.get(key)
        if prior:
            prior_receipt=receipts.get(prior.id,{})
            if source_cut(prior,cue,prior_receipt,receipt):
                blocked.add(prior.id)
            left_parts = source_parts.get(prior.id,{}).get('parts',[])
            right_parts = source_parts.get(cue.id,{}).get('parts',[])
            if left_parts and right_parts:
                left,right=left_parts[-1],right_parts[0]
                if left.get('source_id') == right.get('source_id') and left.get('char_end') == right.get('char_start'):
                    continuous.add((prior.id,cue.id))
        previous[key] = cue
    maximum = profile_for(project_language_tag(project)).max_seconds*1000
    changes = handoff_ends(rows,keys=keys,blocked=blocked,continuous=continuous,max_duration=maximum,audit=audit)
    # Equal millisecond endpoints enter the same frame/format mapping later.
    if progress and not progress(len(rows),len(rows)):
        return None
    return changes


def continuity_successors(cues, *, positions=True):
    """Explicit immediate successors reserve a slot for at most one micro gap."""
    lanes, result = {}, {}
    for cue in sorted(cues,key=lambda c:(c.start_ms,c.end_ms,str(getattr(c,'id',getattr(c,'cue_id',''))))):
        lanes.setdefault(chain_key(cue),[]).append(cue)
    for lane in lanes.values():
        for left,right in zip(lane,lane[1:]):
            a = str(getattr(left,'id',getattr(left,'cue_id','')))
            b = str(getattr(right,'id',getattr(right,'cue_id','')))
            left_clip=(getattr(left,'transform',{}) or {}).get('source_clip_id')
            right_clip=(getattr(right,'transform',{}) or {}).get('source_clip_id')
            if (0 <= right.start_ms-left.end_ms <= MICRO_GAP_MS and not boundary_blocked(left)
                    and not boundary_blocked(right) and not getattr(left,'continuity_break',False)
                    and not getattr(right,'continuity_break',False)
                    and not (positions and (getattr(left,'position_locked',False) or getattr(right,'position_locked',False)
                        or (getattr(left,'transform',{}) or {}).get('position_locked')
                        or (getattr(right,'transform',{}) or {}).get('position_locked')))
                    and not (left_clip and right_clip and left_clip!=right_clip)):
                result[a] = b
    return result
