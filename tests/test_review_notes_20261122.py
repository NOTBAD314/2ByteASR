"""2026-11-22 (user, 1 h stream): 303 completion-page problems, about 250 not actionable."""
import subtitle_core  # noqa: F401 - initializes the legacy facade
from twobyteasr.recognition.recognition_outcome import review_severity
from twobyteasr.recognition.overlap_fill import _sounds_like
from twobyteasr.recognition.speech_coverage import without_foreign_runs


def test_voice_activity_without_words_and_other_hearings_are_notes():
    assert review_severity(dict(category='疑似语音待试听确认', severity='warning', priority=3)) == 'info'
    assert review_severity(dict(category='叠话待试听', severity='warning', priority=2)) == 'info'
    assert review_severity(dict(category='词级时间待对齐', severity='review', priority=1)) == 'info'
    assert review_severity(dict(category='边界待看', detail='字幕句首与人声起音候选相差 423ms',
                                severity='review')) == 'info'
    # Still problems: a large start offset, filled text, a real disagreement.
    assert review_severity(dict(category='边界待看', detail='字幕句首与人声起音候选相差 5520ms',
                                severity='review')) == 'review'
    assert review_severity(dict(category='FireRed 补字待试听', severity='warning')) == 'warning'
    assert review_severity(dict(category='语音缺口待恢复', severity='warning')) == 'warning'
    assert review_severity(dict(category='多模型争议', severity='review')) == 'review'


def test_spoken_numbers_match_digits():
    # FireRed 一百五十 under the primary's 150 is the same words, not a second voice.
    assert _sounds_like('一百五十', '可惜了啊其实就该150走的真的') >= .6


def tokens(text, start=0.):
    return [dict(text=c, start=start+i*.2, end=start+i*.2+.18) for i, c in enumerate(text)]


def test_long_english_runs_are_dropped_from_chinese_evidence():
    lyrics = [dict(text=w, start=281.3+i*.5, end=281.7+i*.5)
              for i, w in enumerate('feel it in my body feel it in my feet'.split())]
    kept = without_foreign_runs([*tokens('我们走', 270.), *lyrics, *tokens('好看一下', 309.)])
    assert ''.join(t['text'] for t in kept) == '我们走好看一下'
    short = [dict(text='OK', start=1., end=1.3), dict(text='OK', start=1.4, end=1.7)]
    assert without_foreign_runs([*tokens('嗯好的'), *short]) == [*tokens('嗯好的'), *short]
