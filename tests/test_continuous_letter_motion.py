"""Continuity is a temporal property, including gaps and excerpt clocks."""
import copy
import pytest

from twobyteasr.caption_style.letter_motion import PRESETS, choreograph, sample


def plan(mode):
    return {'mode': mode, 'text': '连贯的字效', 'duration_ms': 3000,
            'spans': [{'char_start': i, 'char_end': i+1, 'start_ms': a, 'end_ms': b}
                      for i,(a,b) in enumerate([(100,240),(400,570),(680,830),(1500,1670),(1800,2050)])]}


@pytest.mark.parametrize('mode', ['karaoke_wipe','word_sweep'])
def test_ink_moves_through_brief_gaps_and_stops_for_a_phrase_pause(mode):
    source = plan(mode); before = copy.deepcopy(source)
    units = choreograph(source)['units']
    assert source == before
    # Formerly all these frames were the same completed first character.
    inks = [sample(units[0], t)['ink'] for t in (250,280,310,340,370)]
    assert all(0 < a < b < 1 for a,b in zip(inks, inks[1:]))
    for t in (1000,1200,1400):
        assert sample(units[2],t)['ink'] == 1
        assert sample(units[3],t)['ink'] == 0
    # Incoming and outgoing ink velocities agree at the character boundary.
    left = (1-sample(units[0],395)['ink'])/5
    right = sample(units[1],405)['ink']/5
    assert left == pytest.approx(right, rel=.08)


@pytest.mark.parametrize('mode', PRESETS)
def test_neighbouring_letters_are_in_flight_together(mode):
    units = choreograph(plan(mode))['units']
    channel = {'word_sweep':'ink', 'word_echo':'ink','word_pulse':'split',
               'word_float':'sy','word_dust':'scatter','word_mist':'scale'}[mode]
    if mode == 'word_sweep':
        assert sample(units[0],300)['ink'] < sample(units[0],350)['ink'] < 1
    else:
        # At this handover both letters still change, not a finished letter
        # followed by an unrelated next entrance.
        for unit in units[:2]:
            assert sample(unit,270)[channel] != sample(unit,300)[channel]


@pytest.mark.parametrize('mode', ['karaoke_wipe',*PRESETS])
def test_continuous_choreography_preserves_excerpt_clock(mode):
    source = plan(mode); full = choreograph(source)
    cut = copy.deepcopy(source)
    cut.update(clock_offset_ms=315, original_duration_ms=3000, duration_ms=2500)
    for span in cut['spans']:
        span['start_ms'] -= 315; span['end_ms'] -= 315
    short = choreograph(cut)
    for t in (0,37,280,900,2100,2480):
        for a,b in zip(full['units'],short['units']):
            assert sample(a,t+315) == pytest.approx(sample(b,t),abs=.0001)
