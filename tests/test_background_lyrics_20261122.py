"""2026-11-22: background-music lyrics go to a hidden speaker, never deleted."""
import json
from types import SimpleNamespace

import subtitle_core  # noqa: F401 - initializes the legacy facade
from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
from twobyteasr.recognition import background_lyrics as bl

SNAPSHOT = SimpleNamespace(timeout_policy=TimeoutPolicy(), thinking_protocol='auto')
LYRICS = {'最美的相遇 最美的相遇', '最遥不可及', '两颗星星同时在相互吸引'}


def provider(lyrics, flaky=()):
    calls = []

    def complete(messages, **kwargs):
        rows = json.loads(messages[1]['content'])['lines']
        calls.append([r['id'] for r in rows])
        first = len(calls) == 1
        chosen = [r['id'] for r in rows if r['text'] in lyrics and not (r['text'] in flaky and not first)]
        return json.dumps(dict(lyrics=chosen))
    return SimpleNamespace(complete=complete), calls


def lines():
    rows = [(10., '好 我们切火羽'), (12., '他应该会点截拳'), (2993.9, '最美的相遇 最美的相遇'),
            (2996.6, '最遥不可及'), (3000.2, '两颗星星同时在相互吸引'), (3004., '这里怎么办呢？')]
    return rows


def test_lines_both_readings_choose_are_lyrics_and_speech_stays():
    prov, calls = provider(LYRICS)
    assert bl.classify(lines(), SNAPSHOT, provider=prov) == {2, 3, 4}
    assert len(calls) == 2  # one batch, read twice


def test_a_single_reading_counts_only_next_to_a_confirmed_lyric():
    prov, _ = provider(LYRICS | {'这里怎么办呢？'}, flaky={'这里怎么办呢？', '最遥不可及'})
    # 最遥不可及 (one reading) sits between two confirmed lines; 这里怎么办呢？ is
    # next to a confirmed line only through a one-reading neighbour, 3.8 s away.
    chosen = bl.classify(lines(), SNAPSHOT, provider=prov)
    assert {2, 4} <= chosen and 3 in chosen and 0 not in chosen and 1 not in chosen


def test_the_new_project_hides_lyrics_on_their_own_speaker():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    cues = [StudioCue('a', 0, 1000, '好 我们切火羽', speaker_id='S00'),
            StudioCue('b', 2993900, 2996000, '最美的相遇 最美的相遇', speaker_id='S00')]
    project = SubtitleProject(media=StudioMedia(path='x.mp4'), cues=cues, speakers=[StudioSpeaker('S00')])
    project.generation_metadata['background_lyrics'] = dict(lines=[dict(start_ms=2993900, end_ms=2996000,
                                                                         text='最美的相遇 最美的相遇')])
    assert bl.apply_to_project(project) == 1
    assert [c.speaker_id for c in project.cues] == ['S00', bl.SPEAKER_ID]
    lyric = next(s for s in project.speakers if s.id == bl.SPEAKER_ID)
    assert lyric.hidden and lyric.name == '背景歌词'
    assert project.hidden_speaker_ids() == {bl.SPEAKER_ID}
    assert [c.id for c in project.cues] == ['a', 'b']  # nothing deleted
    project.validate()


def test_no_ai_grouping_or_another_language_sends_nothing():
    prov, calls = provider(LYRICS)
    context = SimpleNamespace(provider_snapshot=SNAPSHOT, task_language='ja', recognition_purpose='final',
                              asr_settings_snapshot={'switches': {'use_ai_grouping': True}})
    legacy = SimpleNamespace(record_run_event=lambda *a, **k: None, add_review_item=lambda *a, **k: None)
    cues = [SimpleNamespace(start=0., end=1., text='好')]
    assert bl.mark_background_lyrics(cues, context, legacy) is None
    context.task_language, context.asr_settings_snapshot = 'zh', {'switches': {'use_ai_grouping': False}}
    assert bl.mark_background_lyrics(cues, context, legacy) is None and not calls
