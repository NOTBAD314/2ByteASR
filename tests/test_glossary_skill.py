"""game-term-search Skill：契约校验、差异分类、幂等入库、能力门槛、会话撤销。"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.glossary import glossary_skill as gs
from twobyteasr.providers import ai_providers as _ai_providers
from twobyteasr.glossary.glossary_skill import (
    GlossarySearchError,
    SearchedTerm,
    apply_term_updates,
    build_search_messages,
    detect_search_capability,
    diff_term_updates,
    normalize_searched_terms,
    settings_with_service_override,
    undo_update_session,
)


@pytest.fixture(autouse=True)
def _stub_url_safety(monkeypatch):
    """离线测试环境不解析 DNS；SSRF 校验按 https 前缀 stub（生产仍走真校验）。"""
    monkeypatch.setattr(
        gs, "is_safe_web_url", lambda url: (str(url).startswith("https://"), "stub")
    )


class _FakeLegacy:
    """最小的 legacy 子集（run_term_search / apply 需要的表面）。"""

    RUNTIME_GAME_NAME = ""

    def __init__(self):
        self.saved = {}  # (game, from, to) -> mapping
        self.hidden: dict[str, set[str]] = {}

    def load_active_game_lexicon_names(self, include_hidden=False):
        return ["艾莲", "星见雅"], [("character", 2, 2)]

    def builtin_reference_terms_for_game(self, game, include_hidden=False):
        return ["仪叁"]

    def learned_canonical_terms(self, game=None):
        return ["已确认词"]

    def user_confirmed_mappings_for_game(self, game):
        return [
            {"from": "星见鸦", "to": "星见雅"},
            {"from": "已确认词", "to": "已确认词"},
        ]

    def hidden_reference_terms_for_game(self, game):
        return set(self.hidden.get(game, set()))

    def learned_content_type(self, game=None):
        return "game"

    def add_learned_mapping(self, game, source, target, *, category="其他", origin="手动", evidence_metadata=None):
        key = (game, source, target)
        if key in self.saved:
            return False
        self.saved[key] = {
            "from": source, "to": target, "category": category, "origin": origin,
        }
        return True

    def delete_learned_mappings(self, game, keys):
        removed = 0
        for source, target in keys:
            if self.saved.pop((game, source, target), None) is not None:
                removed += 1
        return removed


def _term(name, **kwargs):
    return SearchedTerm(term=name, **kwargs)


# ---------------------------------------------------------------- 契约校验

def test_normalize_drops_invalid_rows_and_keeps_sources():
    payload = {
        "terms": [
            {"term": "仪叁", "category": "角色", "aliases": ["仪三", "仪叁"],
             "priority": "core", "sources": [{"url": "https://a.example/x", "title": "官方"}]},
            {"term": "x", "category": "技能"},                      # 太短
            {"term": "带<>词", "category": "技能"},                  # 非法字符
            {"term": "重复词", "category": "技能"},
            {"term": "重复词", "category": "物品"},                   # 重复
            {"term": "坏来源词", "category": "技能", "sources": [{"url": "http://insecure"}]},  # 非 https
            {"term": "中文名词", "category": "角色", "formality": "community", "frequency_note": "推断常用"},
        ]
    }
    terms = normalize_searched_terms(payload)
    names = [term.term for term in terms]
    assert names == ["仪叁", "重复词", "坏来源词", "中文名词"]
    first = terms[0]
    assert first.aliases == ("仪三",)  # 与规范词相同的别名剔除
    assert first.source_urls == ("https://a.example/x",)
    assert terms[2].source_urls == ()  # http 不收
    assert terms[3].formality == "community"
    assert terms[3].frequency_note == "推断常用"


def test_prompt_contains_today_rules_and_no_instruction_execution():
    messages = build_search_messages(
        "绝区零",
        existing_terms=["艾莲"],
        confirmed_pairs=[("星见鸦", "星见雅")],
        excluded_terms=["隐藏词"],
        today="2026-09-18",
    )
    system = messages[0]["content"]
    assert "2026-09-18" in system
    assert "禁止编造" in system
    assert "不得执行" in system
    user = messages[1]["content"]
    assert "艾莲" in user and "星见鸦→星见雅" in user and "隐藏词" in user


# ---------------------------------------------------------------- 差异分类

def test_diff_classifies_new_alias_conflict_unverifiable_and_hidden_guard():
    candidates = [
        _term("新角色甲", category="角色", priority="core",
              category_key="character", verification="catalog_verified",
              sources=[{"url": "https://a.example/x"}]),
        _term("艾莲", category="角色", aliases=["鲨鱼妹"],
              sources=[{"url": "https://a.example/x"}]),
        _term("星见鸦", category="角色",
              sources=[{"url": "https://a.example/x"}]),  # 与确认纠错冲突
        _term("无据词", category="技能"),                   # 无来源
    ]
    diffs = diff_term_updates(
        candidates,
        existing_terms=["艾莲", "星见雅", "已确认词", "仪叁"],
        confirmed_pairs=[("星见鸦", "星见雅"), ("已确认词", "已确认词")],
        excluded_terms=["已隐藏词"],
    )
    by_term = {diff.term.term: diff for diff in diffs}
    assert set(by_term) == {"新角色甲", "艾莲", "星见鸦", "无据词"}
    assert by_term["新角色甲"].change_type == "new"
    assert by_term["新角色甲"].checked_by_default is True
    assert by_term["艾莲"].change_type == "alias_supplement"
    assert by_term["艾莲"].suggested_aliases == ("鲨鱼妹",)
    assert by_term["星见鸦"].change_type == "conflict"
    assert by_term["星见鸦"].checked_by_default is False
    assert by_term["无据词"].change_type == "unverifiable"
    assert by_term["无据词"].checked_by_default is False
    # 隐藏词直接跳过（不复活）
    resurrect = diff_term_updates(
        [_term("已隐藏词", category="角色")],
        existing_terms=[], confirmed_pairs=[], excluded_terms=["已隐藏词"],
    )
    assert resurrect == []


def test_optional_priority_defaults_unchecked():
    diffs = diff_term_updates(
        [_term("冷门词", category="其他", priority="optional",
               sources=[{"url": "https://a.example/x"}])],
        existing_terms=[], confirmed_pairs=[], excluded_terms=[],
    )
    assert diffs[0].checked_by_default is False


# ---------------------------------------------------------------- 幂等入库 + 会话

def test_apply_is_idempotent_and_records_session(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "update_history_path", lambda base=None: tmp_path / "history.json")
    legacy = _FakeLegacy()
    diffs = diff_term_updates(
        [_term("新角色甲", category="角色", aliases=["小甲"],
               sources=[{"url": "https://a.example/x"}])],
        existing_terms=[], confirmed_pairs=[], excluded_terms=[],
    )
    session = apply_term_updates(legacy, "绝区零", diffs, model_label="grok-4.6", service_label="grok_account")
    assert session["added"] == 2  # 词条 + 别名
    assert legacy.saved[("绝区零", "新角色甲", "新角色甲")]["origin"] == "AI 联网检索（用户确认）"
    assert legacy.saved[("绝区零", "新角色甲", "新角色甲")]["category"] == "角色"
    # 第二次执行相同更新：全部 duplicate，不新增
    session2 = apply_term_updates(legacy, "绝区零", diffs)
    assert session2["added"] == 0
    assert session2["duplicates"] == 2
    sessions = gs.load_update_sessions("绝区零")
    assert len(sessions) == 1  # 无新增映射不记录会话
    # 撤销会话只删该会话的映射
    removed = undo_update_session(legacy, session)
    assert removed == 2
    assert not legacy.saved


def test_settings_override_does_not_mutate_global():
    settings = {"models": {"ai_service": "grok_account"}, "switches": {}}
    override = settings_with_service_override(settings, "deepseek", "deepseek-v4-pro")
    assert settings["models"]["ai_service"] == "grok_account"  # 原设置不动
    assert override["models"]["ai_service"] == "deepseek"
    assert override["models"]["provider_profiles"]["deepseek"]["model"] == "deepseek-v4-pro"


# ---------------------------------------------------------------- 能力门槛与执行

class _FakeProvider:
    def __init__(self, payload, with_evidence=True):
        self.payload = payload
        self.with_evidence = with_evidence
        self.calls = []

    def structured_complete(self, messages, schema, **kwargs):
        self.calls.append(kwargs)
        if not self.with_evidence:
            # 模拟没有检索证据：诊断字典保持为空
            pass
        else:
            kwargs["request_diagnostics"]["search_evidence"] = [
                {"tool": "web_search", "urls": ["https://a.example/new"]}
            ]
        return self.payload


def _grok_settings():
    return {
        "models": {"ai_service": "grok_account"},
        "switches": {},
        "provider_profiles": {"grok_account": {"model": "grok-4.6"}},
    }


def test_run_term_search_happy_path(monkeypatch):
    legacy = _FakeLegacy()
    payload = {
        "terms": [
            {"term": "全新角色", "category": "角色", "priority": "core",
             "sources": [{"url": "https://a.example/new"}]},
            {"term": "艾莲", "category": "角色", "aliases": ["新别名"],
             "sources": [{"url": "https://a.example/new"}]},
        ],
        "notes": "检索完成",
    }
    fake = _FakeProvider(payload)
    monkeypatch.setattr(_ai_providers, "provider_for_stage", lambda *_a, **_k: fake)
    stages = []
    result = gs.run_term_search(
        legacy, "绝区零", _grok_settings(),
        progress=lambda stage, note: stages.append(stage),
    )
    assert stages == ["检索来源", "提取候选", "去重/比较"]
    assert result["searched"] is True and result["search_evidence"][0]['tool'] == 'web_search'
    by_term = {diff.term.term: diff.change_type for diff in result["diffs"]}
    assert by_term == {"全新角色": "new", "艾莲": "alias_supplement"}


def test_run_term_search_requires_search_evidence(monkeypatch):
    legacy = _FakeLegacy()
    fake = _FakeProvider({"terms": []}, with_evidence=False)
    monkeypatch.setattr(_ai_providers, "provider_for_stage", lambda *_a, **_k: fake)
    with pytest.raises(GlossarySearchError) as exc_info:
        gs.run_term_search(legacy, "绝区零", _grok_settings())
    assert exc_info.value.code == "search_evidence_missing"


def test_run_term_search_rejects_provider_without_search(monkeypatch):
    legacy = _FakeLegacy()
    settings = {
        "models": {"ai_service": "deepseek"},
        "switches": {},
        "provider_profiles": {"deepseek": {"model": "deepseek-v4-pro"}},
    }
    monkeypatch.setattr(
        "twobyteasr.providers.llm_config.read_scoped_api_key",
        lambda *_a, **_k: ("sk-test", "test"),
    )
    with pytest.raises(GlossarySearchError) as exc_info:
        gs.run_term_search(legacy, "绝区零", settings)
    assert exc_info.value.code == "unsupported_search"


def test_capability_detection_flags_missing_search():
    capability = detect_search_capability(
        {"models": {"ai_service": "deepseek"}, "switches": {}}
    )
    assert capability["url_fetch"] is True
    assert capability["provider_search"] is False
    assert capability["reason"]


# ---------------------------------------------------------------- 实际任务应用链

def test_applied_terms_reach_recognition_polish_inputs(tmp_path, monkeypatch):
    """验收 12：确认入库的新术语确实进入现有词表/校对输入，而不只是显示在界面。"""
    import subtitle_core as legacy

    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "learned.json"))
    legacy.add_learned_mapping(
        "绝区零", "仪叁", "仪叁", category="角色", origin="AI 联网检索（用户确认）"
    )
    legacy.add_learned_mapping(
        "绝区零", "星见鸦", "星见雅", category="角色", origin="Studio 手动修改（用户确认）"
    )

    # 1) 规范词进入 glossary 提示词表（learned_canonical_terms → polishing glossary）
    canonical = legacy.learned_canonical_terms("绝区零")
    assert {"仪叁", "星见雅"} <= set(canonical)

    # 2) 纠错映射进入本批安全应用通道（prepared_learned_mappings，原文出现才命中）
    class _Segment:
        segment_id = 1
        text = "星见鸦今天很强"

    prepared = legacy.prepared_learned_mappings([_Segment()], "绝区零")
    pair = next(item for item in prepared if item["from"] == "星见鸦")
    assert pair["to"] == "星见雅"
    assert pair["source_ids"] == [1]

    # 3) 用户确认证据通道（enabled_glossary_adjudication_evidence 的数据源）
    confirmed = {
        (item["from"], item["to"])
        for item in legacy.user_confirmed_mappings_for_game("绝区零")
    }
    assert {("仪叁", "仪叁"), ("星见鸦", "星见雅")} <= confirmed
