"""multi-glossary 数据面测试（UI IMPLEMENTATION 第 0 步）。

- settings glossary 段 + list merge + 旧设置迁移
- RuntimeContext / RunOptions 的 enabled_glossary_ids 贯通
- learned mappings / lexicon 按启用集合 union，单库浏览语义不变
- cache 签名包含 enabled ids
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import subtitle_core  # noqa: E402
from twobyteasr.recognition.run_context import (  # noqa: E402
    RuntimeContext,
    activate_runtime_context,
    runtime_context_from_legacy,
)
from twobyteasr.storage.settings import (  # noqa: E402
    DEFAULT_SETTINGS,
    load_runtime_settings,
    save_runtime_settings,
)
from twobyteasr.recognition.service import RunOptions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- settings

def test_settings_glossary_section_defaults():
    assert DEFAULT_SETTINGS["glossary"]["enabled_glossary_ids"] == []
    assert DEFAULT_SETTINGS["glossary"]["enable_domain_terms"] is False


def test_settings_merge_accepts_glossary_list(tmp_path):
    settings, _path, warnings = load_runtime_settings(tmp_path)
    assert not [w for w in warnings if "glossary" in w], "不允许 glossary 相关警告（无文件警告可忽略）"
    settings["glossary"]["enabled_glossary_ids"] = ["我的世界", "异环", "我的世界"]
    settings["glossary"]["enable_domain_terms"] = True
    saved, _path2, warnings2 = save_runtime_settings(settings, tmp_path)
    assert not warnings2
    reloaded, _path3, reload_warnings = load_runtime_settings(tmp_path)
    assert not [w for w in reload_warnings if "glossary" in w]
    assert reloaded["glossary"]["enabled_glossary_ids"] == ["我的世界", "异环"], "去重保序"


def test_settings_migrates_legacy_selected_glossary(tmp_path):
    payload = {
        "schema_version": 1,
        "glossary": {"selected_glossary": "绝区零", "enable_domain_terms": True},
    }
    path = tmp_path / "2byteasr_settings.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    settings, _p, warnings = load_runtime_settings(tmp_path)
    assert not warnings
    assert settings["glossary"]["enabled_glossary_ids"] == ["绝区零"], "旧单库迁移为单元素列表"


def test_settings_migrates_content_name_when_nothing_selected(tmp_path):
    payload = {
        "schema_version": 1,
        "glossary": {"content_name": "原神"},
    }
    path = tmp_path / "2byteasr_settings.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    settings, _p, _w = load_runtime_settings(tmp_path)
    assert settings["glossary"]["enabled_glossary_ids"] == ["原神"]
    # enable_domain_terms 缺省随启用集合
    assert settings["glossary"]["enable_domain_terms"] is True


def test_settings_rejects_invalid_list_elements(tmp_path):
    settings, _p, _w = load_runtime_settings(tmp_path)
    settings["glossary"]["enabled_glossary_ids"] = ["ok", "", 3, None, "ok"]
    saved, _p2, _w2 = save_runtime_settings(settings, tmp_path)
    assert saved["glossary"]["enabled_glossary_ids"] == ["ok"]


# ---------------------------------------------------------------- runtime

def test_runtime_context_carries_enabled_glossary_ids():
    class Legacy:
        RUNTIME_GAME_NAME = "我的世界"
        RUNTIME_ENABLE_DOMAIN_TERMS = True
        RUNTIME_ENABLED_GLOSSARY_IDS = ["我的世界", "异环"]

    context = runtime_context_from_legacy(Legacy())
    assert context.enabled_glossary_ids == ["我的世界", "异环"]

    context2 = runtime_context_from_legacy(type("L2", (), {"RUNTIME_GAME_NAME": "原神"})())
    assert context2.enabled_glossary_ids == [], "旧属性缺失 → 空列表（由创建处回退）"


def test_run_options_fall_back_to_content_name_when_ids_empty():
    class Legacy:
        RUNTIME_GAME_NAME = "绝区零"
        RUNTIME_ENABLE_DOMAIN_TERMS = True

        @staticmethod
        def runtime_game_identity(name):
            return subtitle_core.runtime_game_identity(name)

    options = RunOptions(
        content_name="绝区零",
        enable_domain_terms=True,
        enabled_glossary_ids=(),
    )
    context = options.create_runtime_context(Legacy())
    assert context.enabled_glossary_ids == ["绝区零"], "空 ids 回退旧单库行为"


def test_run_options_keeps_ids_empty_when_domain_terms_disabled():
    class Legacy:
        @staticmethod
        def runtime_game_identity(name):
            return subtitle_core.runtime_game_identity(name)

    options = RunOptions(
        content_name="绝区零",
        enable_domain_terms=False,
        enabled_glossary_ids=(),
    )
    context = options.create_runtime_context(Legacy())
    assert context.enable_domain_terms is False
    assert context.enabled_glossary_ids == []


def test_run_options_normalizes_multiple_ids():
    class Legacy:
        RUNTIME_GAME_NAME = ""

        @staticmethod
        def runtime_game_identity(name):
            return subtitle_core.runtime_game_identity(name)

    options = RunOptions(
        content_name="我的世界",
        enable_domain_terms=True,
        enabled_glossary_ids=("我的世界", "异环", "我的世界"),
    )
    context = options.create_runtime_context(Legacy())
    assert context.enabled_glossary_ids == ["我的世界", "异环"]


# ---------------------------------------------------------------- union helpers

def test_runtime_enabled_glossary_ids_uses_active_context():
    context = RuntimeContext(
        game_name="我的世界",
        enable_domain_terms=True,
        enabled_glossary_ids=["我的世界", "异环"],
    )
    with activate_runtime_context(context):
        assert subtitle_core.runtime_enabled_glossary_ids() == ["我的世界", "异环"]


def test_learned_mappings_merge_enabled_glossaries(tmp_path, monkeypatch):
    payload = {
        "schema": 1,
        "games": {
            subtitle_core.runtime_game_identity("我的世界"): {
                "game": "我的世界",
                "mappings": [
                    {"from": "苦力怕", "to": "苦力怕", "confirmed": True, "updated": "2026-08-13"}
                ],
            },
            subtitle_core.runtime_game_identity("异环"): {
                "game": "异环",
                "mappings": [
                    {"from": "福宁娜", "to": "芙宁娜", "confirmed": False, "updated": "2026-08-13"}
                ],
            },
        },
    }
    monkeypatch.setattr(
        subtitle_core,
        "load_learned_term_payload",
        lambda: json.loads(json.dumps(payload, ensure_ascii=False)),
    )
    context = RuntimeContext(enabled_glossary_ids=["我的世界", "异环"], enable_domain_terms=True)
    with activate_runtime_context(context):
        merged = subtitle_core.learned_mappings_for_game()
        assert {item["from"] for item in merged} == {"苦力怕", "福宁娜"}
        # 显式传参仍是单库浏览语义
        single = subtitle_core.learned_mappings_for_game("异环")
        assert {item["from"] for item in single} == {"福宁娜"}


def test_learned_mappings_deduplicate_same_pair_across_glossaries(tmp_path, monkeypatch):
    identity = subtitle_core.runtime_game_identity
    payload = {
        "schema": 1,
        "games": {
            identity("我的世界"): {
                "game": "我的世界",
                "mappings": [{"from": "苦力怕", "to": "苦力怕", "confirmed": True, "updated": "x"}],
            },
            identity("异环"): {
                "game": "异环",
                "mappings": [{"from": "苦力怕", "to": "苦力怕", "confirmed": False, "updated": "y"}],
            },
        },
    }
    monkeypatch.setattr(
        subtitle_core,
        "load_learned_term_payload",
        lambda: json.loads(json.dumps(payload, ensure_ascii=False)),
    )
    context = RuntimeContext(enabled_glossary_ids=["我的世界", "异环"], enable_domain_terms=True)
    with activate_runtime_context(context):
        merged = subtitle_core.learned_mappings_for_game()
        assert len(merged) == 1, "同一 (from,to) 跨库只保留第一条（已确认优先由首库保证）"
        assert merged[0]["confirmed"] is True


def test_lexicon_names_merge_enabled_profiles(monkeypatch):
    # 用真实 game_profiles：启用 洛克王国 + 绝区零 → 两类 lexicon 都出现
    context = RuntimeContext(
        game_name="洛克王国：世界",
        enable_domain_terms=True,
        enabled_glossary_ids=[
            subtitle_core.runtime_game_identity("洛克王国：世界"),
            subtitle_core.runtime_game_identity("绝区零"),
        ],
    )
    with activate_runtime_context(context):
        names, loaded = subtitle_core.load_enabled_game_lexicon_names()
        assert names, "启用集合应产出词库词"
        assert len(names) > 500, "洛克王国 skills 553 + spirits + 绝区零 characters 应并集"
        # 单库浏览函数仍只给当前内容
        single_names, _single_loaded = subtitle_core.load_active_game_lexicon_names()
        assert len(single_names) < len(names)


def test_content_profile_signature_includes_enabled_ids():
    context = RuntimeContext(game_name="原神", enable_domain_terms=True, enabled_glossary_ids=["异环", "原神"])
    with activate_runtime_context(context):
        signature = subtitle_core.runtime_content_profile_signature()
        assert signature["enabled_glossary_ids"] == ["原神", "异环"], "sorted ids 进签名防缓存串味"


def test_enabled_glossary_adjudication_evidence_includes_aliases_and_user_mappings(monkeypatch):
    identity = subtitle_core.runtime_game_identity
    monkeypatch.setattr(
        subtitle_core,
        "load_game_profiles",
        lambda: {
            "我的世界": {
                "identity": "我的世界",
                "terms": [{
                    "canonical": "末影龙",
                    "aliases": ["末影隆"],
                    "source": "official",
                }],
            }
        },
    )
    monkeypatch.setattr(
        subtitle_core,
        "load_learned_term_payload",
        lambda: {
            "schema": 1,
            "games": {
                identity("我的世界"): {
                    "game": "我的世界",
                    "mappings": [{
                        "from": "苦力帕",
                        "to": "苦力怕",
                        "category": "角色",
                        "origin": "手动",
                    }],
                }
            },
        },
    )
    context = RuntimeContext(
        game_name="我的世界",
        enable_domain_terms=True,
        enabled_glossary_ids=[identity("我的世界")],
    )

    with activate_runtime_context(context):
        evidence = subtitle_core.enabled_glossary_adjudication_evidence()

    assert evidence["game_or_content_names"] == ["我的世界"]
    assert set(evidence["canonical_terms"]) == {"末影龙", "苦力怕"}
    assert evidence["aliases"] == [{"alias": "末影隆", "canonical": "末影龙"}]
    assert evidence["wrong_to_correct_mappings"] == [{
        "wrong": "苦力帕",
        "correct": "苦力怕",
        "category": "角色",
        "origin": "手动",
    }]
