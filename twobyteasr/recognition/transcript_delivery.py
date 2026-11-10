"""Candidate acquisition and subtitle delivery are independent facts."""
from __future__ import annotations

RECOVERY_MESSAGE = '取得了转写结果，但全部范围存在语言冲突，尚未生成可用字幕。'


class NoSpeechDetected(RuntimeError):
    """A VAD completed and found no speech; distinct from ASR failure."""


def acceptance_counts(raw, accepted, state):
    from .transcript_acceptance import pending_ranges, _inside
    pending = pending_ranges(state)
    rejected = [r for r in raw if any(_inside(r, p['start_sample'], p['end_sample']) for p in pending)]
    spans = []
    for row in sorted(accepted, key=lambda r: (r['start'],r['end'])):
        if spans and row['start'] <= spans[-1]['end']+.001:
            spans[-1]['end'] = max(spans[-1]['end'],row['end'])
        else:
            spans.append(dict(start=row['start'],end=row['end']))
    return dict(candidate_segment_count=len(raw), accepted_segment_count=len(accepted),
                pending_segment_count=len(rejected), pending_range_count=len(pending),
                pending_ranges=[{k: p[k] for k in ('id', 'start', 'end', 'reason')} for p in pending],
                accepted_ranges=spans)


def report_counts(report):
    result = report.get('result') or {}
    if isinstance(result.get('transcript_counts'), dict):
        return result['transcript_counts']
    # Older reports (including the user attachment) have no saved counters.
    events = report.get('events') or []
    gate = next((e for e in reversed(events) if e.get('event') == 'transcript_acceptance'), {})
    candidate = max((int(e.get('segment_count') or 0) for e in events
                     if e.get('event') == 'MODEL_RESULT_AVAILABLE' and
                     e.get('role') not in {'timeline_alignment', 'review'}), default=0)
    return dict(candidate_segment_count=candidate, pending_range_count=len(gate.get('pending_ranges') or []),
                pending_ranges=gate.get('pending_ranges') or [], final_cue_count=int(result.get('cue_count') or 0))


def terminal_status(counts, final_cues, *, degraded=False):
    if counts.get('pending_range_count') or counts.get('speech_gap_count') or counts.get('speech_failure_count'):
        return 'needs_recovery' if not final_cues else 'partial_recovery'
    if not final_cues:
        return 'empty_result'
    return 'degraded_success' if degraded else 'success'
