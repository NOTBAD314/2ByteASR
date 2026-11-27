"""比利犬 13/16/17 (2026-11-26): Japanese AI proposals the local rules can only reject.

Of 37/76/62 proposals none was accepted; nearly all were single-source rewrites
rejected by japanese_semantic_needs_listening and shown as "AI 提出 37 · 拒绝 21".
The user chose: such edits are not proposed (prompt) and not counted (local precheck).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from tests.test_stage9_cache_and_budget import context  # noqa: F401
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules.language_rules import language_scope


def test_unacceptable_japanese_edits_are_withheld_not_counted(context, monkeypatch):  # noqa: F811
    from twobyteasr.subtitle_rules import polishing
    text = 'お客さんを連れしたぞ経理科の林君だ'
    row = SpeechSegment(38, 0, 3, text, .8, [], primary_source='moss-dialogue', moss_text=text,
                        firered_text='お客さんを連れしたぞ経理課の林君だ',
                        qwen_asr_text='お客さんを連れしたぞ経理課の林君だ')
    sent = []

    def complete(messages, **kwargs):
        sent.append(messages[0]['content'])
        return json.dumps({'checked_ids': [38], 'cues': [{'id': 38, 'edits': [
            # two independent families heard 経理課: may be accepted
            {'from': '経理科', 'to': '経理課', 'start': 10, 'end': 13, 'type': 'asr_correction', 'evidence': 'F+Q'},
            # nobody heard it: a contextual guess the local rules can only reject
            {'from': '林君', 'to': '早瀬君', 'start': 14, 'end': 16, 'type': 'asr_correction', 'evidence': '语境'},
            # notation only
            {'from': 'お客さん', 'to': 'おきゃくさん', 'start': 0, 'end': 4, 'type': 'asr_correction', 'evidence': '写法'},
        ]}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **kw: SimpleNamespace(complete=complete))
    with language_scope('ja'):
        polishing.call_correction_api([row], [], '', '', '', '', [], [], [])
    receipt = row.caption_arbitration['terminology_polish']
    assert [edit['to'] for edit in receipt['returned_edits']] == ['経理課']
    assert receipt['rejected_edits'] == [] and receipt['rejected_edit_count'] == 0
    assert sorted(edit['to'] for edit in receipt['withheld_japanese_edits']) == ['おきゃくさん', '早瀬君']
    assert receipt['validated_text'] == 'お客さんを連れしたぞ経理課の林君だ'
    assert '至少两个不同家族的独立 ASR 来源' in sent[0]


def test_single_source_japanese_rewrite_gives_zero_proposed_and_rejected(context, monkeypatch):  # noqa: F811
    from twobyteasr.subtitle_rules import polishing
    text = 'ドンニャビリケン'
    row = SpeechSegment(17, 0, 2, text, .8, [], primary_source='moss-dialogue', moss_text=text,
                        qwen_asr_text='どうにゃビリケン')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(
        complete=lambda *a, **kw: json.dumps({'checked_ids': [17], 'cues': [{'id': 17, 'edits': [
            {'from': 'ドンニャビリケン', 'to': 'どうにゃビリケン', 'start': 0, 'end': 8,
             'type': 'asr_correction', 'evidence': 'Q'}]}]}, ensure_ascii=False)))
    before = len(context[1].review_items)
    with language_scope('ja'):
        polishing.call_correction_api([row], [], '', '', '', '', [], [], [])
    receipt = row.caption_arbitration['terminology_polish']
    assert receipt['returned_edits'] == [] and receipt['rejected_edits'] == []
    assert receipt['withheld_japanese_edits'][0]['rule_id'] == 'japanese_semantic_needs_listening'
    assert receipt['validated_text'] == text
    assert len(context[1].review_items) == before        # no listening review item any more
