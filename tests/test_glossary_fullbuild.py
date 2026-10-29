"""VII 轮：完整建库引擎纯函数测试（无网络、无真实词库写入）。"""

from __future__ import annotations

import json

import pytest

from twobyteasr.glossary import glossary_build as gb
from twobyteasr.glossary.glossary_skill import (
    SearchedTerm,
    diff_term_updates,
    quote_normalize_term,
)


# ---------------------------------------------------------------- 归一

def test_quote_normalize_variants_collapse():
    assert quote_normalize_term("「11号」") == quote_normalize_term("11号")
    assert quote_normalize_term("《绝区零》") == quote_normalize_term("绝区零")
    assert quote_normalize_term(" 希格莉德 ") == "希格莉德"


def test_diff_treats_quoted_existing_as_duplicate():
    candidate = SearchedTerm(
        term="11号",
        category="角色",
        category_key="character",
        sources=({"url": "https://a.b/c", "title": ""},),
        verification="page_verified",
    )
    diffs = diff_term_updates(
        [candidate],
        existing_terms=["「11号」"],
        confirmed_pairs=[],
        excluded_terms=[],
    )
    assert diffs == []  # 引号变体不算新增（幂等）


def test_diff_flags_cross_game_term_not_default_checked():
    candidate = SearchedTerm(
        term="马娘",
        category="角色",
        category_key="character",
        sources=({"url": "https://a.b/c", "title": ""},),
    )
    diffs = diff_term_updates(
        [candidate],
        existing_terms=[],
        confirmed_pairs=[],
        excluded_terms=[],
        cross_game_terms=["马娘"],
    )
    assert len(diffs) == 1
    assert diffs[0].cross_game is True
    assert diffs[0].checked_by_default is False


# ---------------------------------------------------------------- 目录发现

def test_normalize_catalogs_filters_and_caps():
    payload = {
        "current_version": "1.8",
        "version_note": "新角色居多",
        "catalogs": [
            {"url": "https://wiki.a/agents", "title": "代理人一览", "covers": "characters"},
            {"url": "https://wiki.a/agents", "title": "dup", "covers": "characters"},  # 重复 URL
            {"url": "http://insecure/x", "title": "http", "covers": "misc"},          # 非 https
            {"url": "https://wiki.a/weapons", "title": "音擎图鉴", "covers": "weapons"},
        ],
    }
    result = gb.normalize_catalogs(payload)
    urls = [item["url"] for item in result["catalogs"]]
    assert urls == ["https://wiki.a/agents", "https://wiki.a/weapons"]
    assert result["current_version"] == "1.8"


def test_normalize_catalogs_rejects_empty():
    with pytest.raises(ValueError):
        gb.normalize_catalogs({"catalogs": []})


# ---------------------------------------------------------------- 名称提取

ROSTER_HTML = """
<html><body>
<table><tr><th>代理人</th><th>属性</th></tr>
<tr><td>安比</td><td>电</td></tr>
<tr><td>「11号」</td><td>火</td></tr>
<tr><td>编辑</td><td>噪音</td></tr></table>
<ul><li><a href="/zzz/青衣" title="青衣">青衣</a></li><li>朱鸢</li></ul>
</body></html>
"""


def test_extract_catalog_names_filters_existing_and_noise():
    pages = {"https://wiki.a/agents": ROSTER_HTML}
    catalogs = [{"url": "https://wiki.a/agents", "title": "代理人一览", "covers": "characters"}]
    entries = gb.extract_catalog_names(
        pages, catalogs, existing_terms=["安比", "「11号」"]
    )
    names = [entry.name for entry in entries]
    assert "青衣" in names and "朱鸢" in names
    assert "安比" not in names and "11号" not in names   # 引号归一后视为已有
    assert "编辑" not in names                            # 停用词
    assert all(entry.source_url == "https://wiki.a/agents" for entry in entries)
    assert entries[0].hint_key  # 有类别提示


# ---------------------------------------------------------------- 整理批

def _entry(name: str) -> gb._NameEntry:
    return gb._NameEntry(
        name=name, hint_key="character",
        source_url="https://wiki.a/agents", title="代理人一览", context="",
    )


def test_page_extract_messages_carry_text_and_focus():
    messages = gb.build_page_extract_messages(
        "绝区零", page_title="代理人一览", text_chunk="安比 电属性 强攻", covers_hint="characters",
        today="2026-09-18",
    )
    payload = json.loads(messages[1]["content"])
    assert payload["text"] == "安比 电属性 强攻"
    assert "通行的短名" in messages[0]["content"] and "程序会验证" in messages[0]["content"]
    assert "names" in messages[0]["content"]


def test_normalize_page_names_containment_and_aliases():
    payload = {
        "names": [
            {"name": "青衣", "category": "角色", "aliases": ["青衣姐"],
             "priority": "core", "evidence": "目录页在列"},
            {"name": "朱鸢", "category": "角色", "aliases": ["青衣"],  # 别名指向他词：保留（别名去重交给 diff）
             "priority": "recommended"},
            {"name": "不存在的词", "category": "角色"},               # 不在页面文本 → 丢弃
            {"name": "安比", "category": "角色"},                     # 已有词 → 跳过
        ]
    }
    terms, dropped = gb.normalize_page_names(
        payload,
        plain_text="代理人有 青衣、朱鸢 与其它名词。安比也在。",
        source_url="https://wiki.a/agents",
        source_title="代理人一览",
        existing_terms=["安比"],
        seen_terms=set(),
    )
    assert [t.term for t in terms] == ["青衣", "朱鸢"]
    assert terms[0].verification == "page_verified"
    assert terms[0].sources[0]["url"] == "https://wiki.a/agents"
    assert terms[0].aliases == ("青衣姐",)
    assert dropped == 1  # 不存在的词被包含性验证丢弃


def test_normalize_page_names_requires_names_array():
    with pytest.raises(ValueError):
        gb.normalize_page_names(
            {"results": []}, plain_text="x", source_url="u", source_title="t",
            existing_terms=[], seen_terms=set(),
        )


# ---------------------------------------------------------------- 跨游戏

class _FakeLegacy:
    def load_learned_term_payload(self):
        return {
            "games": {
                "zzz": {"game": "绝区零", "mappings": [
                    {"from": "安比", "to": "安比"},
                ]},
                "uma": {"game": "赛马娘", "mappings": [
                    {"from": "马娘", "to": "马娘"},
                ]},
            }
        }


def test_other_game_canonical_terms_excludes_current_game():
    terms = gb.other_game_canonical_terms(_FakeLegacy(), "绝区零")
    assert "马娘" in terms
    assert "安比" not in terms


# ---------------------------------------------------------------- 检查点

def test_checkpoint_term_roundtrip():
    term = SearchedTerm(
        term="青衣", category="角色", category_key="character",
        aliases=("青衣姐",), priority="core", formality="official",
        sources=({"url": "https://wiki.a/agents", "title": "代理人一览"},),
        evidence="目录页在列", verification="page_verified",
    )
    data = gb.serialize_term(term)
    assert json.loads(json.dumps(data)) == data  # 可 JSON 序列化
    restored = gb._deserialize_term(data)
    assert restored.term == term.term
    assert restored.aliases == term.aliases
    assert restored.verification == "page_verified"
    assert restored.sources == term.sources


def test_checkpoint_payload_v3(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    term = SearchedTerm(
        term="青衣", category="角色", category_key="character",
        aliases=("青衣姐",), priority="core",
        sources=({"url": "https://wiki.a/agents", "title": "代理人一览"},),
        evidence="分类成员", verification="page_verified",
    )
    payload = gb._checkpoint_payload(
        "绝区零", [{"url": "https://wiki.a/agents", "title": "t", "covers": "characters"}],
        [term], {"https://wiki.a/agents"}, True, "3.2", "note", deterministic_count=1,
    )
    gb.save_task_checkpoint("task-v3", payload)
    loaded = gb.load_task_checkpoint("task-v3")
    assert loaded["config_version"] == gb.BUILD_CONFIG_VERSION
    assert loaded["done_urls"] == ["https://wiki.a/agents"]
    assert loaded["community_done"] is True
    restored = gb._deserialize_term(loaded["candidates"][0])
    assert restored.term == "青衣" and restored.verification == "page_verified"


def test_covers_seed_category_accepts_chinese_keywords():
    assert gb._covers_seed_category("代理人") == ("character", "角色")
    assert gb._covers_seed_category("音擎") == ("equipment", "装备")
    assert gb._covers_seed_category("characters") == ("character", "角色")
    assert gb._covers_seed_category("邦布") == ("item", "物品")
    assert gb._covers_seed_category("随便") == ("other", "其他")
