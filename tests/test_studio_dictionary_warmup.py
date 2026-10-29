"""Delayed Chinese warmup must belong to a live source-text project."""
from types import SimpleNamespace
import pytest
from twobyteasr.studio.studio_readiness import StudioReadiness


@pytest.mark.parametrize('text,expected', [("Let's move over there.", False), ('先往這邊走', True)])
def test_only_source_chinese_needs_dictionary(text, expected, monkeypatch):
    calls = []
    monkeypatch.setattr('twobyteasr.subtitle_rules.stutter_cleanup.warm_text_analysis', lambda: calls.append(1))
    project = SimpleNamespace(cues=[SimpleNamespace(text=text)],
                              generation_metadata={'translations': {'c0': '中文譯文'}})
    state = SimpleNamespace(generation=2, ready=True, page=SimpleNamespace(project=project))
    StudioReadiness._warm_text_analysis(state, 2)
    assert bool(calls) == expected


@pytest.mark.parametrize('epoch,ready,closing', [(1, True, False), (2, False, False), (2, True, True)])
def test_stale_or_closed_opening_cannot_start_dictionary(epoch, ready, closing, monkeypatch):
    monkeypatch.setattr('twobyteasr.subtitle_rules.stutter_cleanup.warm_text_analysis',
                        lambda: pytest.fail('stale callback started work'))
    state = SimpleNamespace(generation=2, ready=ready, page=SimpleNamespace(
        project=SimpleNamespace(cues=[SimpleNamespace(text='中文')]), _close_requested=closing))
    StudioReadiness._warm_text_analysis(state, epoch)
