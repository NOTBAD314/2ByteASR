import pytest
import subtitle_core  # initialize the legacy facade
from twobyteasr.subtitle_rules.english_segmentation import break_scores, pieces_from_breaks


@pytest.mark.parametrize('words,cut', [
    (['get', 'our', 'color', 'management', 'set', 'up'], 4),
    (["I'm", 'going', 'to', 'need'], 1),
    (['timeline', 'color', 'space'], 1),
    (['DaVinci', 'Wide', 'Gamut'], 0),
    (['Resolve', 'Color', 'Management'], 1),
    (['talk', 'to', 'you', 'today'], 0),
])
def test_phrase_boundary_is_rejected_for_ai_and_penalized_for_local_rules(words, cut):
    assert break_scores(words)[cut] <= -30
    assert pieces_from_breaks(words, [cut]) is None


def test_real_sentence_punctuation_takes_precedence_over_phrase_match():
    assert break_scores(['The', 'set.', 'Up', 'next'])[1] > 0
