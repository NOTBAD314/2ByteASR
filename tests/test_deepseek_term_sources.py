"""2026-11-16: term-library sources from DeepSeek Search / Fetch."""
from datetime import date

import pytest

from twobyteasr.glossary import deepseek_term_sources as dts
from twobyteasr.glossary.glossary_skill import SearchedTerm
from twobyteasr.providers import deepseek_tools


def test_queries_cover_topics_and_recent_versions():
    rows = dts.queries('绝区零', 'game', today=date(2026, 11, 16))
    assert all(row.startswith('绝区零 ') and len(row) <= 128 for row in rows)
    assert any('after:2026-05-20' in row for row in rows)
    assert dts.queries('绝区零', 'game', categories=['boss', 'nonsense']) == ['绝区零 Boss']
    assert not any('after:' in row for row in dts.queries('某主播', 'creator'))
    assert dts.queries('', 'game') == []
    assert dts.planned_requests('game') == len(dts.queries('x', 'game')) + dts.MAX_PAGES


def test_gather_keeps_named_results_best_first_and_skips_failed_queries():
    def search(api_key, query, **_kw):
        if '地图' in query:
            raise deepseek_tools.DeepSeekToolError('timeout', status=504, category='http')
        return [dict(title='绝区零 角色', url='https://a.example/1', summary='', rerank_score=1.2, authority=2),
                dict(title='绝区零 wiki', url='https://b.example/2', summary='', rerank_score=2.4, authority=4),
                dict(title='别的', url='https://c.example/3', summary='无关', rerank_score=3, authority=4),
                dict(title='绝区零 http', url='http://d.example/4', summary='')]
    results, made, rejected = dts.gather('k', '绝区零', dts.queries('绝区零', 'game'), search=search)
    assert [row['url'] for row in results] == ['https://b.example/2', 'https://a.example/1']
    assert made == len(dts.queries('绝区零', 'game')) and rejected == ['https://c.example/3']


def test_gather_stops_on_key_or_balance():
    def search(*_a, **_k):
        raise deepseek_tools.DeepSeekToolError('no money', status=402, category='balance')
    with pytest.raises(deepseek_tools.DeepSeekToolError):
        dts.gather('k', '绝区零', ['绝区零 角色'], search=search)


def test_pick_pages_skips_video_and_repeats_a_site():
    rows = [dict(url='https://www.bilibili.com/video/BV1'), dict(url='https://wiki.example/a'),
            dict(url='https://wiki.example/b'), dict(url='https://other.example/c')]
    assert [r['url'] for r in dts.pick_pages(rows, 3)] == ['https://wiki.example/a', 'https://other.example/c']


def test_material_fits_the_budget():
    results = [dict(url=f'https://x.example/{i}', title='绝区零' * 5, summary='角' * 400) for i in range(40)]
    pages = [dict(url='https://x.example/p', title='p', text='艾莲' * 50000)]
    material = dts.model_material(results, pages, budget=20000)
    import json
    assert len(json.dumps(material, ensure_ascii=False).encode('utf8')) <= 20000 + 2000
    assert material['pages'] and material['search_results']


def test_verify_terms_needs_the_spelling_in_a_read_page():
    texts = dts.evidence_texts([dict(url='https://a.example/1', title='绝区零', summary='艾莲 是代理人')],
                               [dict(url='https://b.example/2', title='', text='星见 雅 和 鲨鱼妹')])
    terms = [SearchedTerm(term='艾莲', aliases=('鲨鱼妹', '乱猜'), sources=({'url': 'https://a.example/1'},)),
             SearchedTerm(term='星见雅', sources=({'url': 'https://made.up'},)),
             SearchedTerm(term='朱鸢', sources=({'url': 'https://a.example/1'},))]
    dts.verify_terms(terms, texts)
    assert terms[0].verification == 'page_verified' and terms[0].aliases == ()   # 鲨鱼妹 is on another page
    assert terms[1].verification == 'page_verified' and terms[1].sources[0]['url'] == 'https://b.example/2'
    assert terms[2].verification == 'unverified' and terms[2].sources == ()


def test_clean_markdown_drops_pictures_and_link_targets():
    assert dts.clean_markdown('![x](https://i/1.png) [艾莲](https://w/a)\n\n\n朱鸢') == '艾莲\n朱鸢'
