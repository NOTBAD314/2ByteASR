# -*- coding: utf-8 -*-
"""Proofreading never proposes the service's own normalization as "AI 校对" (2026-10-12).

Before: the correction service validates every cue on
``clean_subtitle_text(text)`` (spaces collapsed/stripped, ordinary punctuation
deleted).  Even with zero model edits — and on fallback/timeout — Studio
diffed that against the raw cue and showed "AI 校对 · 删去「 」 · 推荐",
ticked by default.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade before polishing
from twobyteasr.studio_glossary_review import diff_occurrences, format_only_change, transplant_model_edits
from twobyteasr.studio_glossary_service import preview_glossary_correction
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry

TEXTS = ("这里怎么办 ", "好，我们走 ", "没事 开一把就知道了", "魔草巫灵、来了 ")


def library(*terms):
    return GlossarySnapshot((GlossaryLibrary('v', '瓦罗兰特', '1', terms=tuple(terms),
        profile_json=json.dumps({'_content_domain': {'id': 'v', 'name': '瓦罗兰特',
                                                     'source': 'saved_library_game'}})),))


def project(*texts):
    p = SubtitleProject(media=StudioMedia(path='isolated.mp4'), glossary_ids=['v'],
        cues=[StudioCue(str(i), i * 2000, i * 2000 + 1000, text, original_text=text, speaker_id='S01')
              for i, text in enumerate(texts, 1)])
    p.validate()
    return p


def real_provider_snapshot(monkeypatch):
    from tests.test_stage9_provider_snapshot import config
    from twobyteasr import llm_config
    import twobyteasr.asr_provider_snapshot as provider
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("fixture", "test"))
    snap = provider.resolve_provider_snapshot(config())
    monkeypatch.setattr(provider, 'resolve_provider_snapshot', lambda *_a, **_kw: snap)
    return snap


def model_answers(monkeypatch, edits_for=lambda cue_id, text: []):
    """A provider answering through the real call_correction_api."""
    sent = []

    def complete(messages, **_kwargs):
        rows = json.loads(messages[1]['content'])['cues']
        sent.extend(row['primary_text'] for row in rows)
        cues = [{'id': row['id'], 'edits': edits}
                for row in rows for edits in [edits_for(row['id'], row['primary_text'])] if edits]
        return json.dumps({'checked_ids': [row['id'] for row in rows], 'cues': cues})

    monkeypatch.setattr('twobyteasr.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=complete))
    return sent


def test_root_cause_the_safety_adjudicator_returns_normalized_text_without_edits():
    from twobyteasr.correction_safety import apply_correction_edits
    corrected, applied = apply_correction_edits("这里怎么办 ", [], [], independent_sources=[])
    assert (corrected, applied) == ("这里怎么办", [])
    corrected, _ = apply_correction_edits("魔草巫灵、来了 ", [], [], independent_sources=[])
    assert corrected == "魔草巫灵来了"


def test_zero_model_edits_produce_no_suggestion(monkeypatch):
    real_provider_snapshot(monkeypatch)
    sent = model_answers(monkeypatch)
    p = project(*TEXTS)
    result = preview_glossary_correction(p, [c.id for c in p.cues], library(TermEntry('autumn', category='选手ID')), {})
    assert sent  # the real request went out
    assert result.receipt['successful_cues'] == len(TEXTS)
    assert not [hit for hit in result.hits if hit.source == 'ai_accepted']
    assert all(row['final_diff'] == [] for row in result.receipt['segments'])
    assert [row['final_text'] for row in result.receipt['segments']] == list(TEXTS)
    assert result.receipt['empty_state'] != 'changes_ready'


def test_timeout_fallback_produces_no_suggestion(monkeypatch):
    from twobyteasr import polishing
    from twobyteasr.provider_input_budget import RetryBudget
    real_provider_snapshot(monkeypatch)
    sent = model_answers(monkeypatch)
    monkeypatch.setattr(polishing, 'correction_task_budget',
                        lambda *_a, **_kw: RetryBudget(0, total_seconds=0))
    p = project(*TEXTS)
    result = preview_glossary_correction(p, [c.id for c in p.cues], library(TermEntry('autumn', category='选手ID')), {})
    assert not sent and result.receipt['fallback_cues'] == len(TEXTS)
    assert not result.hits
    assert result.receipt['empty_state'] == 'request_failed'


def test_failed_request_produces_no_suggestion(monkeypatch):
    real_provider_snapshot(monkeypatch)

    def broken(messages, **_kwargs):
        from twobyteasr.ai_providers import AIProviderError
        raise AIProviderError('offline', category='configuration_error')

    monkeypatch.setattr('twobyteasr.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=broken))
    p = project(*TEXTS)
    result = preview_glossary_correction(p, [c.id for c in p.cues], library(TermEntry('autumn', category='选手ID')), {})
    assert not result.hits
    assert result.receipt['fallback_cues'] == len(TEXTS) and result.receipt['successful_cues'] == 0


def test_real_model_edit_is_transplanted_onto_the_raw_text(monkeypatch):
    """Only 巫 -> 乌 is proposed; the cue's 、 and trailing space are not touched."""
    import twobyteasr.polishing as polish
    from twobyteasr.text_rules import clean_subtitle_text

    def correction(rows, *_a, **_kw):
        texts = {row.segment_id: clean_subtitle_text(row.text) for row in rows}
        texts[1] = texts[1].replace('巫', '乌')
        return polish.PolishBatchResult(texts, details={1: {'accepted_edits': [{'from': '巫', 'to': '乌'}],
                                                            'returned_edits': [{'from': '巫', 'to': '乌'}]}})

    real_provider_snapshot(monkeypatch)
    monkeypatch.setattr(polish, 'call_correction_api', correction)
    p = project("魔草巫灵、来了 ", "这里怎么办 ")
    result = preview_glossary_correction(p, ['1', '2'], library(TermEntry('autumn', category='选手ID')), {})
    assert [(h.cue_id, h.original, h.replacement, h.source) for h in result.hits] == [
        ('1', '巫', '乌', 'ai_accepted')]
    assert result.hits[0].span == (2, 3)
    row = result.receipt['segments'][0]
    assert row['final_text'] == "魔草乌灵、来了 " and row['ai_edits_transplanted'] is True


@pytest.mark.parametrize('raw, edited, expected', [
    ("这里怎么办 ", "这里怎么办", "这里怎么办 "),                  # no model edit
    ("魔草巫灵、来了 ", "魔草乌灵来了", "魔草乌灵、来了 "),          # edit kept, punctuation/space kept
    ("好，Borlin 也没有接住", "好BerLIN 也没有接住", "好，BerLIN 也没有接住"),
    ("对  对", "对 对", "对  对"),
    ("BorLIN守住", "BerLIN守住", "BerLIN守住"),                     # already normalized text
    ("好，Borlin守住", "好，BerLIN守住", "好，BerLIN守住"),           # raw-space answer is kept as is
])
def test_transplant_model_edits(raw, edited, expected):
    assert transplant_model_edits(raw, edited) == expected


def test_format_only_occurrences_are_never_model_proposals():
    cue = StudioCue('1', 0, 1000, "这里怎么办 ，好")
    hits = diff_occurrences(cue, "这里怎么办好", reason='AI 校对建议', source='ai_accepted', ignore_format_only=True)
    assert hits == []
    hits = diff_occurrences(cue, "这里怎么做好", reason='AI 校对建议', source='ai_accepted', ignore_format_only=True)
    assert [(h.original, h.replacement) for h in hits] == [('办 ，', '做')]
    assert format_only_change(" ", "") and format_only_change("、", "") and not format_only_change("巫", "乌")
    # A local glossary normalization (not a model) may legitimately change spacing.
    local = diff_occurrences(StudioCue('2', 0, 1000, "Team Liquid赢了"), "TeamLiquid赢了",
                             reason='local', source='local_confirmed')
    assert [(h.original, h.replacement) for h in local] == [(' ', '')]
