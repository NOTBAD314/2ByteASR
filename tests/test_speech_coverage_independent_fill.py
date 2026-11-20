"""2026-11-19: an online primary that stops before the end of the media.

Reported job: MOSS Pro returned text up to 642.65 s of 667.44 s, FireRedVAD
heard speech until 667.14 s and FireRedASR2-AED (run beside it) transcribed
that tail, yet the tail ended as four "疑似语音" items among 39 and no
subtitles. These tests replay that shape offline.
"""
from types import SimpleNamespace

from twobyteasr.recognition import speech_coverage as coverage


def row(start, end, text='原文', speaker='API_S01'):
    return dict(start=start, end=end, text=text, speaker=speaker)


def chars(start, text, step=.2):
    return [dict(text=c, start=round(start+i*step, 3), end=round(start+(i+1)*step-.02, 3), confidence=.9)
            for i, c in enumerate(text)]


# The primary's last line ends at 20.0 s; VAD speech runs to 40.6 s of 41 s.
SPEECH = [dict(start=0, end=20.5, detector='firered_vad', confidence=.9),
          dict(start=22, end=30, detector='firered_vad', confidence=.9),
          dict(start=34, end=40.6, detector='firered_vad', confidence=.86)]
PRIMARY = [row(0, 10, '我们先打这个'), row(10.2, 20, '反正不打了')]
# FireRed heard the tail, plus one edge character of the last primary line.
TOKENS = chars(19.8, '了') + chars(22.2, '走了走了百分之五十的概率') + chars(34.2, '那就是六百元奖金乘上三倍')


def context(job='tail'):
    from twobyteasr.recognition.run_context import RuntimeContext
    return RuntimeContext(job_id=job)


class Legacy:
    def __init__(self):
        self.events, self.reviews = [], []

    def record_run_event(self, name, **kw):
        self.events.append((name, kw))

    def add_review_item(self, timestamp, category, detail, text='', priority=1, severity=None, **kw):
        self.reviews.append(dict(timestamp=timestamp, category=category, detail=detail, priority=priority))


def test_independent_words_promote_only_real_gaps():
    state = coverage.make_state(SPEECH, PRIMARY, duration=41)
    assert [g['classification'] for g in state['gaps']] == ['uncertain_speech', 'uncertain_speech']
    noise = chars(22.4, '我')  # one edge character, as every non-tail gap in the job
    assert coverage.corroborate(state, noise) == []
    promoted = coverage.corroborate(state, TOKENS)
    assert len(promoted) == 2
    assert all(g['status'] == 'pending' and g['evidence']['speech_corroborated'] for g in state['gaps'])
    assert state['gaps'][0]['evidence']['independent_text']['characters'] >= 3


def test_primary_retry_runs_first_and_fill_covers_the_rest():
    legacy, ctx = Legacy(), context()
    calls = []

    def runner(a, b):
        calls.append((a, b))
        # The API recovers the first piece only.
        return [row(22.1, 29.9, '走了走了百分之五十的概率', 'RECOVERY_X_API')] if a < 30 else []

    payload = dict(segments=list(PRIMARY), execution={})
    state = coverage.audit_primary(payload, SPEECH, ctx, duration=41, legacy=legacy, runner=runner,
                                   source='api', independent=TOKENS, fill_independent=True)
    assert len(calls) == 2
    first, second = state['gaps']
    assert first['status'] == 'recovered' and first['recovery_source'] == 'api'
    assert second['status'] == 'recovered' and second['recovery_source'] == coverage.FILL_SOURCE
    filled = [r for r in payload['segments'] if r.get('source') == coverage.FILL_ROW_SOURCE]
    assert ''.join(r['text'] for r in filled) == '那就是六百元奖金乘上三倍'
    assert all(r['speaker'].startswith('RECOVERY_') and coverage.recovery_speaker(r['speaker']) for r in filled)
    # The API's text is not duplicated by FireRed's copy of it.
    assert sum('百分之五十' in r['text'] for r in payload['segments']) == 1
    coverage.finalize(ctx, payload['segments'], legacy)
    categories = [r['category'] for r in legacy.reviews]
    assert categories == ['FireRed 补字待试听']
    assert coverage.counts(state) == dict(speech_gap_count=0, speech_failure_count=0, speech_confirmation_count=0)


def test_empty_primary_retry_fills_whole_tail_including_short_speech_between_gaps():
    legacy, ctx = Legacy(), context()
    tokens = TOKENS + chars(31.0, '五十六')  # speech between the gaps, below MIN_GAP
    payload = dict(segments=list(PRIMARY), execution={})
    state = coverage.audit_primary(payload, SPEECH, ctx, duration=41, legacy=legacy,
                                   runner=lambda a, b: [], source='api', independent=tokens,
                                   fill_independent=True)
    assert not coverage.pending(state)
    text = ''.join(r['text'] for r in payload['segments'] if r.get('source') == coverage.FILL_ROW_SOURCE)
    assert text == '走了走了百分之五十的概率五十六那就是六百元奖金乘上三倍'
    # The edge character of the last primary line is not copied again.
    assert not text.startswith('了')
    assert {g['independent_fill']['review'] for g in state['gaps']} == {'listen_and_confirm'}
    assert all(r in payload['references'] for r in payload['segments'] if r.get('source') == coverage.FILL_ROW_SOURCE)


def test_without_evidence_the_tail_is_one_prominent_review_item():
    legacy, ctx = Legacy(), context()
    payload = dict(segments=list(PRIMARY), execution={})
    state = coverage.audit_primary(payload, SPEECH + [dict(start=3, end=5, detector='firered_vad', confidence=.9)],
                                   ctx, duration=41, legacy=legacy, runner=lambda a, b: [], source='api')
    assert len(coverage.pending(state)) == 2
    coverage.finalize(ctx, payload['segments'], legacy)
    tail, = [r for r in legacy.reviews if r['category'] == '片尾语音没有字幕']
    assert tail['priority'] == 1 and tail['timestamp'] == 22.0 and '40.600' in tail['detail']
    assert not [r for r in legacy.reviews if r['category'] == '疑似语音待试听确认']


def test_mid_media_gap_keeps_the_normal_label():
    legacy, ctx = Legacy(), context()
    speech = [dict(start=0, end=30, detector='firered_vad', confidence=.9)]
    payload = dict(segments=[row(0, 10), row(20, 30)], execution={})
    coverage.audit_primary(payload, speech, ctx, duration=30, legacy=legacy, source='api')
    coverage.finalize(ctx, payload['segments'], legacy)
    assert [r['category'] for r in legacy.reviews] == ['疑似语音待试听确认']


def test_language_discard_restores_the_gaps():
    legacy, ctx = Legacy(), context()
    payload = dict(segments=list(PRIMARY), execution={})
    state = coverage.audit_primary(payload, SPEECH, ctx, duration=41, legacy=legacy, runner=lambda a, b: [],
                                   source='api', independent=TOKENS, fill_independent=True)
    assert not coverage.pending(state)
    coverage.discard_independent_fill(state, payload)
    assert payload['segments'] == PRIMARY
    assert not any(r.get('source') == coverage.FILL_ROW_SOURCE for r in payload.get('references', []))
    gaps = coverage.pending(state)
    assert len(gaps) == 2 and all(g['status'] == 'needs_confirmation' for g in gaps)
    assert all(g['remaining_ranges'] == [[g['start'], g['end']]] for g in gaps)
    assert not any(g['evidence']['speech_corroborated'] for g in gaps)


def test_no_independent_evidence_keeps_previous_behaviour():
    calls = []
    state = coverage.make_state(SPEECH, PRIMARY, duration=41)
    coverage.recover(state, PRIMARY, lambda *a: calls.append(a), source='api')
    assert not calls and all(g['status'] == 'needs_confirmation' for g in state['gaps'])
