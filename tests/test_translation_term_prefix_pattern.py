"""Preserve flat-regex semantics while reducing large-library compile work."""
import random
import re

import pytest

from twobyteasr.glossary.translation_terms import _literal_pattern, effective_policy, freeze


def flat_pattern(surfaces, boundary):
    patterns = []
    for surface in sorted(surfaces, key=lambda value:(-len(value), value)):
        escaped = re.escape(surface)
        if surface[0].isascii() and surface[0].isalnum():
            escaped = '(?<!' + boundary + ')' + escaped
        if surface[-1].isascii() and surface[-1].isalnum():
            escaped += '(?!' + boundary + ')'
        patterns.append(escaped)
    return re.compile('|'.join(patterns), re.IGNORECASE)


@pytest.mark.parametrize('boundary', [r'[\w]', r'[A-Za-z0-9_]'])
def test_shared_prefixes_preserve_all_spans_and_boundaries(boundary):
    surfaces = ['爱', '爱弥斯', '爱弥斯小姐', 'a', 'ann', 'anna', 'ann中', '中ann',
                'a+b', 'a.b', 'a(b)', 'é', 'éa', 'i', 'ii', 'si', 'k',
                *[f'用語{index:05}' for index in range(1000)]]
    old, new = flat_pattern(surfaces,boundary), _literal_pattern(surfaces,boundary)
    rng = random.Random(20261109)
    alphabet = ['愛', '爱弥斯小姐', 'anna', 'Ann中', 'ann', 'a+b', 'a.b', 'a(b)',
                '用語00001', '用語00999', '用語01000', 'i', 'ı', 'İ', 'ſ', 'K',
                '_', '1', '中', 'é', 'éa', ' ', '!', '(', ')']
    for _ in range(3000):
        text = ''.join(rng.choices(alphabet,k=rng.randint(1,15)))
        expected = [(match.span(),match.group()) for match in old.finditer(text)]
        assert [(match.span(),match.group()) for match in new.finditer(text)] == expected


@pytest.mark.parametrize('surfaces', [['ı', 'iix', 'ıx', 'ii'], ['a'*2000, 'a'*1999]])
def test_unicode_and_long_literal_fallback_preserves_original_expression(surfaces):
    old = flat_pattern(surfaces,r'[\w]')
    new = _literal_pattern(surfaces,r'[\w]')
    assert new.pattern == old.pattern


def test_no_inline_pairs_retains_the_exact_directional_policy():
    frozen = freeze(dict(enabled=True,selected_ids=['ja'],libraries=[dict(id='ja',
        source_language='ja',target_language='zh-Hans',terms=[dict(source='橋',target='桥')])]))
    assert effective_policy(frozen, iter(()), 'ja', 'zh-Hans') is frozen


def test_ten_thousand_shared_names_compile_to_a_bounded_expression():
    pattern = _literal_pattern([f'用語{index:05}' for index in range(10000)], r'[A-Za-z0-9_]')
    assert len(pattern.pattern) < 200
    assert [hit.group() for hit in pattern.finditer('用語00000 用語09999 用語10000')] == ['用語00000','用語09999']
