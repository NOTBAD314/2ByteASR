from twobyteasr.caption_style.text_marks import *


def test_markdown_has_plain_unicode_indices_and_no_timing():
    text, marks, _ = parse_markdown('今天終於打過了**最後一關**。')
    assert text == '今天終於打過了最後一關。'
    assert marks == [{'start': 7, 'end': 11, 'bold': True}]
    assert parse_markdown('a *斜體*\n==亮色==')[0] == 'a 斜體\n亮色'


def test_incomplete_escaped_and_literal_input_roundtrip():
    for value in ('**未完', '# literal_a * stars', 'a\\b', '`x` == *'):
        assert parse_markdown(markdown_text(value, []))[0] == value
    assert parse_markdown('**未完')[0] == '**未完'
    assert parse_markdown('`**原樣**`')[0] == '**原樣**'


def test_graphemes_and_single_occurrence_edits():
    text = '甲👨‍👩‍👧‍👦e\u0301甲'
    edge = boundaries(text)
    assert edge == (0, 1, 8, 10, 11)
    assert normalize_marks(text, [{'start': 2, 'end': 9, 'color': '#FF0000'}]) == [
        {'start': 1, 'end': 10, 'color': '#FF0000'}]
    marks = [{'start': 2, 'end': 4, 'bold': True}]
    assert remap_marks('火球火球', '大火球火球', marks) == [{'start': 3, 'end': 5, 'bold': True}]
    assert remap_marks('火球', '冰箭', [{'start': 0, 'end': 2, 'bold': True}]) == []
