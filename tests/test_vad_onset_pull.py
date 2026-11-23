"""2026-11-22 (user): subtitles of a 4 h stream appeared after the voice.

Qwen Audio 3.1 sentence starts sat a median 230 ms after the FireRedVAD
onset (its regions open 80 ms before the detected voice); 540 of the job's
628 "边界待看" items were these. A line that opens a speech region late now
starts at the region; lines inside continuous speech keep their times.
"""
import pytest
import subtitle_core as core
from twobyteasr.recognition.transcript_data import SubtitleCue
from twobyteasr.subtitle_rules import timing

FPS = core.TIMELINE_FPS


@pytest.fixture(autouse=True)
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(timing, 'record_run_event', lambda name, **kw: seen.append((name, kw)), raising=False)
    monkeypatch.setattr(timing, 'add_review_item', lambda *a, **kw: None, raising=False)
    return seen


def region(start, end, detector='firered_vad'):
    return dict(start=start, end=end, detector=detector)


def snap(cues, regions):
    return timing.snap_cue_starts_to_vad_onsets(cues, regions, FPS)


def frame(value):
    return round(value * FPS) / FPS


def test_job_lines_that_open_speech_late_start_at_the_onset(events):
    # The job's first lines: 先去吃点东西吧 (VAD 93.84), 改了我这边看改了 (163.58).
    cues = [SubtitleCue(1, 94.017, 95.517, '先去吃点东西吧'), SubtitleCue(9, 163.817, 165.633, '改了我这边看改了')]
    snap(cues, [region(93.84, 95.39), region(163.58, 165.32)])
    assert cues[0].start == pytest.approx(frame(93.84)) and cues[0].end == 95.517
    assert cues[1].start == pytest.approx(frame(163.58))
    name, receipt = events[-1]
    assert name == 'vad_onset_pull' and receipt['changed'] == 2


def test_the_second_line_of_one_speech_region_keeps_its_word_time():
    cues = [SubtitleCue(1, 136.317, 137.75, '欢迎来到北城直播间啊大家'), SubtitleCue(2, 137.75, 138.433, '晚上好')]
    snap(cues, [region(136.17, 138.5)])
    assert cues[0].start == pytest.approx(frame(136.17))
    assert cues[1].start == 137.75


@pytest.mark.parametrize('start', [10.05, 10.6])
def test_small_and_large_leads_are_left_alone(start):
    # Under 100 ms is within the onset; over 450 ms more likely words the
    # primary dropped or noise at the region start.
    cue = SubtitleCue(1, start, 12.0, '这次播多久')
    snap([cue], [region(10.0, 12.5)])
    assert cue.start == start


def test_a_line_in_silence_still_only_moves_later():
    # The startup self-test case: never earlier from silence.
    cue = SubtitleCue(1, 1.0, 2.0, '句首校准', speaker='S01')
    snap([cue], [region(1.3, 2.0)])
    assert cue.start == pytest.approx(1.3, abs=1 / FPS)


def test_the_previous_line_still_showing_ends_at_the_onset():
    previous = SubtitleCue(1, 20.0, 22.4, '能有5个小时吗？')
    late = SubtitleCue(2, 22.33, 24.0, '嗯其实看到杯果上')
    snap([previous, late], [region(19.9, 21.9), region(22.1, 24.0)])
    assert late.start == pytest.approx(frame(22.1))
    assert previous.end == late.start


def test_another_line_starting_in_the_gap_keeps_the_onset():
    other = SubtitleCue(1, 30.05, 30.5, '嗯', speaker='S01')
    late = SubtitleCue(2, 30.25, 32.0, '我们今天晚上来看一下', speaker='S00')
    snap([other, late], [region(30.0, 32.0)])
    assert late.start == 30.25


def test_energy_vad_and_locked_lines_do_not_move():
    cue = SubtitleCue(1, 40.25, 42.0, '你刷新一下就行了')
    snap([cue], [region(40.0, 42.0, detector='energy_vad')])
    assert cue.start == 40.25
    locked = SubtitleCue(1, 40.25, 42.0, '你刷新一下就行了', timing_locked=True)
    snap([locked], [region(40.0, 42.0)])
    assert locked.start == 40.25


def test_unverified_bounds_do_not_pull_a_cue_earlier():
    cue = SubtitleCue(1, 40.25, 42.0, '你刷新一下就行了')
    snap([cue], [dict(region(40.0, 42.0), confidence_bounds_verified=False)])
    assert cue.start == 40.25


def test_simultaneous_lines_keep_their_shared_start():
    cues = [
        SubtitleCue(1, 40.25, 41.5, '先等一下', speaker='S01'),
        SubtitleCue(2, 40.25, 42.0, '你刷新一下就行了', speaker='S00'),
    ]
    snap(cues, [region(40.0, 42.0)])
    assert [cue.start for cue in cues] == [40.25, 40.25]


def test_a_pull_never_makes_a_line_longer_than_the_limit():
    limit = timing._max_cue_seconds()
    cue = SubtitleCue(1, 50.3, 50.3 + limit - .05, '我就看这个剧情什么时候播完呗')
    snap([cue], [region(50.0, 56.0)])
    assert cue.end - cue.start <= limit + 1e-9
