"""Retained failure: missing player name is not a Chinese particle vote."""
import subtitle_core  # Initialize the existing legacy facade before its exports.
from twobyteasr.recognition.caption_arbitration import arbitrate
from twobyteasr.subtitle_rules.correction_safety import apply_reference_consensus_corrections
from twobyteasr.recognition.transcript_data import SpeechSegment


def test_sop_missing_in_both_references_never_becomes_so_particle():
    decision = arbitrate('Sop还在往里走', '了还在往里走', '折打了还在往里走')
    assert decision['selected_text'] == 'Sop还在往里走'
    assert not decision['accepted_spans']


def test_latin_identifier_case_and_numeric_identity_not_character_votes():
    for text, reference in [('对JDG放松警惕了', '对jdg放松警惕了'),
                            ('这个S0pp多杀', '这个Sopp多杀')]:
        assert arbitrate(text, reference, reference)['selected_text'] == text


def test_decoding_damage_is_not_valid_transcript_evidence():
    assert arbitrate('跟队友回合', '跟队友汇合\ufffd', '跟队友汇合')['selected_text'] == '跟队友回合'


def test_repeat_consensus_preserves_original_slots_and_other_receipts():
    row = SpeechSegment(8, 12.41, 13.65, 'Sop还在往里走', .78, [],
        moss_text='Sop还在往里走', firered_text='了还在往里走', qwen_asr_text='折打了还在往里走')
    row.caption_arbitration = {'terminology_polish': {'original_text': row.text}}
    apply_reference_consensus_corrections([row])
    original = dict(row.caption_arbitration['independent_input_evidence'])
    apply_reference_consensus_corrections([row])
    assert row.text == 'Sop还在往里走'
    assert row.caption_arbitration['independent_input_evidence'] == original
    assert row.caption_arbitration['terminology_polish']['original_text'] == row.text


def test_neighbour_only_reference_prefix_is_not_inserted():
    assert arbitrate('所以感觉有点失去比赛感觉了', '所所以感觉有点失去比赛感觉了',
                     '所所以感觉有点失去比赛感觉了')['selected_text'] == '所以感觉有点失去比赛感觉了'
