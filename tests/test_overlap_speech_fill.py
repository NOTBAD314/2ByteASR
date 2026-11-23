"""2026-11-20: a streamer talking over a trailer narrator.

Reported job (110 s clip of five trailer cuts): MOSS Pro returned one 40 s
narrator line and dropped the streamer under it; 11 of the 16 proofread
streamer lines had to be typed by hand. FireRedASR2-AED, run beside it,
wrote the streamer's words into its mixed transcript. Speech coverage only
checks time, and that time had text. These tests replay the shape offline.
"""
from twobyteasr.recognition import overlap_fill
from twobyteasr.recognition import speech_coverage as coverage


def row(start, end, text, speaker='API_S01', **extra):
    return dict(start=start, end=end, text=text, speaker=speaker, **extra)


def chars(start, text, step=.2):
    return [dict(text=c, start=round(start+i*step, 3), end=round(start+(i+1)*step-.02, 3), confidence=.9)
            for i, c in enumerate(text)]


NARRATOR = '恒常观测共包含十名五星角色至多九十次必定会获得其中随机一名角色在恒常观测中至多八十次观测可以获得一张五星灵子'
STREAMER = '因为不歪所以导致很多常驻角色很难获取'
# FireRed hears the narrator, then the louder streamer over the narrator's
# 可以获得一张五星灵子, as in the job (它 0.35 phonetic score vs. the line).
HEARD = NARRATOR[:44] + STREAMER
PRIMARY = [row(0.0, 14.0, NARRATOR)]


def test_second_voice_under_one_primary_line_becomes_a_candidate_row():
    rows, rejected = overlap_fill.find_overlap_rows(PRIMARY, chars(0.0, HEARD))
    assert [r['text'] for r in rows] == [STREAMER]
    found, = rows
    assert found['speaker'] == overlap_fill.SPEAKER and coverage.recovery_speaker(found['speaker'])
    assert found['source'] == coverage.FILL_ROW_SOURCE and found['fill_kind'] == 'overlap'
    assert found['start'] == round(44*.2, 3) and found['end'] > found['start']
    assert found['overlap_evidence']['primary_speaker'] == 'API_S01'
    assert found['overlap_evidence']['sounds_like_primary'] < overlap_fill.SOUND_ALIKE


def test_a_misheard_copy_of_the_primary_line_is_not_a_second_voice():
    primary = [row(0.0, 8.0, '我们已经恭候多时了接下来介绍新角色')]
    heard = chars(0.0, '我们已经恭候多时了借下来介少心脚色')
    rows, rejected = overlap_fill.find_overlap_rows(primary, heard)
    assert rows == [] and rejected == {'misheard_primary': 1}


def test_where_the_primary_already_has_both_voices_nothing_is_added():
    # MOSS separated this overlap itself (two speakers at that moment): the
    # extra FireRed words were garbles of the mix in the zero-loss job.
    primary = [*PRIMARY, row(8.0, 12.0, '哇这个大招还是很还原的', 'API_S03')]
    rows, rejected = overlap_fill.find_overlap_rows(primary, chars(0.0, HEARD))
    assert rows == [] and rejected == {'primary_has_both_voices': 1}


def test_gap_fill_rows_are_not_a_second_primary_speaker():
    primary = [*PRIMARY, row(9.0, 10.0, '原来', 'RECOVERY_1_FIRERED', source=coverage.FILL_ROW_SOURCE)]
    rows, _ = overlap_fill.find_overlap_rows(primary, chars(0.0, HEARD))
    assert [r['text'] for r in rows] == [STREAMER]


def test_words_outside_primary_text_belong_to_the_gap_fill():
    rows, rejected = overlap_fill.find_overlap_rows(PRIMARY, chars(0.0, NARRATOR) + chars(20.0, STREAMER))
    assert rows == [] and rejected == {'not_under_primary': 1}


def test_text_said_nearby_by_another_row_is_not_added_again():
    # A reordered overlap: the primary has the streamer's line as its own row.
    primary = [row(0.0, 8.8, NARRATOR[:44]), row(9.0, 13.0, STREAMER, 'API_S03')]
    rows, _ = overlap_fill.find_overlap_rows(primary, chars(0.0, HEARD))
    assert rows == []


class Legacy:
    def __init__(self):
        self.events, self.reviews = [], []

    def record_run_event(self, name, **kw):
        self.events.append((name, kw))

    def add_review_item(self, timestamp, category, detail, text='', priority=1, severity=None, **kw):
        self.reviews.append(dict(timestamp=timestamp, category=category, detail=detail, priority=priority,
                                 severity=severity))


def test_rows_join_the_primary_payload_with_one_review_item_each_and_go_with_a_language_discard():
    from twobyteasr.recognition.run_context import RuntimeContext
    legacy, ctx = Legacy(), RuntimeContext(job_id='overlap')
    speech = [dict(start=0, end=14, detector='firered_vad', confidence=.9)]
    payload = dict(segments=list(PRIMARY), execution={})
    tokens = chars(0.0, HEARD)
    state = coverage.audit_primary(payload, speech, ctx, duration=14, legacy=legacy, source='api',
                                   independent=tokens, fill_independent=True)
    added = overlap_fill.add_overlap_rows(state, payload, tokens, legacy)
    assert [r['text'] for r in added] == [STREAMER]
    assert added[0] in payload['segments'] and added[0] in payload['references']
    assert [r['start'] for r in payload['segments']] == sorted(r['start'] for r in payload['segments'])
    assert state['overlap_fill']['rows'][0]['characters'] == len(STREAMER)
    assert ('overlap_speech_fill', dict(rows=1, rejected={}, inserted=True, characters=len(STREAMER))) in legacy.events
    coverage.finalize(ctx, payload['segments'], legacy)
    item, = [r for r in legacy.reviews if r['category'] == '叠话补字待试听']
    assert item['timestamp'] == added[0]['start'] and item['severity'] == 'warning'
    assert 'API_S01' in item['detail'] and f'{len(STREAMER)} 字' in item['detail']
    coverage.discard_independent_fill(state, payload)
    assert payload['segments'] == PRIMARY
    assert state['overlap_fill']['rows'] == [] and state['overlap_fill']['discarded'] == 'task_language'


# 2026-11-22 (user): Qwen Audio 3.1 with speakers turned off still gave eight
# lanes in a 4 h stream: S00 for all primary text, RECOVERY_OVERLAP_FIRERED
# for 72 FireRed lines under S00, one RECOVERY_<sample> lane per recovered gap.

def qwen_settings(diarize):
    return {'models': dict(primary_asr_backend='api', qwen_asr_api_provider='qwen_cloud_filetrans',
                           qwen_asr_api_model='qwen-audio-3.1-asr-flash-filetrans', qwen_audio_diarize=diarize)}


def test_speakers_turned_off_only_for_the_qwen_audio_choice_left_off():
    from twobyteasr.recognition.speaker_strategy import speakers_turned_off
    assert speakers_turned_off(qwen_settings(False))
    assert not speakers_turned_off(qwen_settings(True))
    assert not speakers_turned_off({'models': dict(qwen_settings(False)['models'], primary_asr_backend='moss')})
    other = dict(qwen_settings(False)['models'], qwen_asr_api_provider='qwen31_filetrans')
    assert not speakers_turned_off({'models': other})   # Bailian keeps asking for speakers


def test_with_speakers_off_a_second_voice_is_reviewed_not_added_as_a_lane():
    from twobyteasr.recognition.run_context import RuntimeContext
    legacy, ctx = Legacy(), RuntimeContext(job_id='overlap-off')
    speech = [dict(start=0, end=14, detector='firered_vad', confidence=.9)]
    primary = [row(0.0, 14.0, NARRATOR, 'S00')]
    payload = dict(segments=list(primary), execution={})
    tokens = chars(0.0, HEARD)
    state = coverage.audit_primary(payload, speech, ctx, duration=14, legacy=legacy, source='api',
                                   independent=tokens, fill_independent=True)
    found = overlap_fill.add_overlap_rows(state, payload, tokens, legacy, insert=False)
    assert [r['text'] for r in found] == [STREAMER]
    assert payload['segments'] == primary and not payload.get('references')
    recorded, = state['overlap_fill']['rows']
    assert recorded['inserted'] is False and recorded['text'] == STREAMER
    coverage.finalize(ctx, payload['segments'], legacy)
    assert not [r for r in legacy.reviews if r['category'] == '叠话补字待试听']
    item, = [r for r in legacy.reviews if r['category'] == '叠话待试听']
    assert STREAMER in item['detail'] and '未另开轨道' in item['detail']


def test_with_speakers_off_recovered_rows_join_the_one_lane():
    payload = dict(segments=[row(0.0, 2.0, '先去吃点东西吧', 'S00'),
                             row(3.0, 4.0, '好的', 'RECOVERY_48000_UNKNOWN'),
                             row(5.0, 6.0, '原来', 'RECOVERY_80000_FIRERED', source=coverage.FILL_ROW_SOURCE)])
    payload['references'] = [dict(r) for r in payload['segments']]
    assert coverage.fold_recovery_lanes(payload) == 2
    assert {r['speaker'] for r in payload['segments']} == {'S00'}
    assert {r['speaker'] for r in payload['references']} == {'S00'}
    assert payload['segments'][1]['recovered_speaker'] == 'RECOVERY_48000_UNKNOWN'


def test_lane_fold_leaves_real_speakers_alone():
    payload = dict(segments=[row(0.0, 2.0, '你好', 'S00'), row(2.0, 3.0, '嗯', 'S01'),
                             row(3.0, 4.0, '好的', 'RECOVERY_48000_UNKNOWN')])
    assert coverage.fold_recovery_lanes(payload) == 0
    assert payload['segments'][2]['speaker'] == 'RECOVERY_48000_UNKNOWN'
