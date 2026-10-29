"""Delimiter inference is limited to the explicit local mapping mode."""
import pytest

from twobyteasr.glossary.glossary_input import parse_term_line, validate_term_records


@pytest.mark.parametrize('separator', [' → ', ' -> ', ' => ', ' - ', ' ', '    ', '\t'])
def test_generic_two_column_mapping(separator):
    row = parse_term_line('NoxMist' + separator + 'NoX7', mapping_mode=True)
    assert (row['from'], row['to']) == ('NoxMist', 'NoX7')
    assert not row.get('parse_error')


@pytest.mark.parametrize('name', ['Spider-Man', 'F/A-18', 'CH-47', 'A-1', 'Silent Hill', "O'Neil"])
def test_normal_term_preserves_complete_names(name):
    row = parse_term_line(name)
    assert (row['from'], row['to']) == (name, name)
    assert not row.get('parse_error')


@pytest.mark.parametrize('text', ['NoxMist -> Other -> NoX7', 'one two three', 'x\ty\tz', 'x -> ', ' -> y', 'x\t'])
def test_ambiguous_or_missing_columns_cannot_save(text):
    rows = validate_term_records([parse_term_line(text, mapping_mode=True)])
    assert rows[0]['status'] == 'invalid'


def test_quotes_and_explicit_arrows_allow_names_with_spaces():
    for text in ['"Silent Hill" "Silent Hills"', 'Silent Hill -> Silent Hills', '“Silent Hill” “Silent Hills”']:
        row = parse_term_line(text, mapping_mode=True)
        assert (row['from'], row['to']) == ('Silent Hill', 'Silent Hills')
        assert not row.get('parse_error')


def test_batch_conflicts_reject_both_interpretations_before_store():
    rows = validate_term_records([parse_term_line(text, mapping_mode=True) for text in ['alias Alpha', 'ALIAS Beta']])
    assert [row['status'] for row in rows] == ['conflict', 'conflict']


def test_merge_and_duplicate_preserve_confirmed_canonical_case():
    existing = [{'from': 'NoX7', 'to': 'NoX7'}, {'from': 'mist', 'to': 'NoX7'}]
    rows = validate_term_records([parse_term_line(text, mapping_mode=True)
        for text in ['mist nox7', 'fresh NOX7', 'mist Other']], existing)
    assert [row['status'] for row in rows] == ['conflict', 'ready', 'conflict']
    assert rows[1]['to'] == 'NoX7' and '合并' in rows[1]['reason']


def test_unspaced_hyphen_mapping_is_never_guessed():
    row = validate_term_records([parse_term_line('NoxMist-NoX7', mapping_mode=True)])[0]
    assert row['status'] == 'invalid'
    assert row['from'] == row['to'] == 'NoxMist-NoX7'
