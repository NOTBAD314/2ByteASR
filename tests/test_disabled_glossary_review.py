"""An absent glossary cannot create missing-glossary review obligations."""
from types import SimpleNamespace

from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry
from twobyteasr.glossary.terminology_support import recall_gaps


def test_disabled_glossary_does_not_flag_ordinary_english_or_names():
    rows = [SimpleNamespace(segment_id=i, text="Let's move over there. Leo and Vincent.")
            for i in range(511)]
    before = [row.text for row in rows]
    assert recall_gaps(rows, [], GlossarySnapshot()) == []
    assert [row.text for row in rows] == before


def test_disabled_glossary_does_not_scan_cues():
    class Unreadable:
        def __iter__(self):
            raise AssertionError('No glossary means no recall-gap scan')
    assert recall_gaps(Unreadable(), [], GlossarySnapshot()) == []


def test_enabled_glossary_still_reports_an_unrecalled_identifier():
    snapshot = GlossarySnapshot((GlossaryLibrary('game', 'Game', '1',
        terms=(TermEntry('PlayerA', ('PlayerA',)),)),))
    rows = [SimpleNamespace(segment_id=7, text='PlayerB')]
    gaps = recall_gaps(rows, [], snapshot)
    assert len(gaps) == 1
    assert gaps[0]['surface'] == 'PlayerB'
    assert not gaps[0]['canonical_inferred']
    assert rows[0].text == 'PlayerB'
