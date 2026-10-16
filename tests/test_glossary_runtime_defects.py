"""2026-10-17 glossary runtime defects: hotword order, hidden references, 法厄同."""
import json
from types import SimpleNamespace

import subtitle_core as legacy
from twobyteasr.terminology import TermResolver, recognition_hotwords, snapshot_glossaries


def row(source, target, category):
    return {"from": source, "to": target, "category": category, "confirmed": True,
            "provenance": "user_confirmed", "origin": "手动"}


def library(mappings, profile_terms=(), hidden=None, lexicon=None):
    # The app re-sorts mappings by (to, from) on every write.
    entry = {"game": "终末地", "mappings": sorted(mappings, key=lambda x: (x["to"], x["from"]))}
    entry.update(hidden or {})
    profiles = {"终末地": {"identity": "zmd", "terms": list(profile_terms)}}
    return SimpleNamespace(load_game_profiles=lambda: profiles,
        load_learned_term_payload=lambda: {"games": {"zmd": entry}},
        _profile_lexicon_paths_for=lambda profile: [str(lexicon)] if lexicon and profile else [])


ORDINARY = [row(f"丁类机制名称{i:02d}", f"丁类机制名称{i:02d}", "机制") for i in range(60)]
VALUABLE = [row("陈千语", "陈千语", "角色"), row("陈千雨", "陈千语", "角色"),
            row("佩丽卡", "佩丽卡", "角色"), row("莱万汀", "莱万汀", "角色"),
            row("熔岩巨像", "熔岩巨像", "Boss"), row("原石", "源石", "其他")]
OTHER = [row("便携电池", "便携电池", "物品"), row("pvp", "PVP", "玩家用语")]
BUILTIN = [{"canonical": "终末地", "aliases": [], "category": "game_term", "source": "wiki"},
           {"canonical": "塔卫二", "aliases": [], "category": "region", "source": "wiki"}]


def snapshot():
    return snapshot_glossaries(library([*ORDINARY, *VALUABLE, *OTHER], BUILTIN), ["zmd"])


def test_hotwords_put_builtin_then_names_and_misheard_terms_before_unicode_order():
    current = snapshot()
    # Stored order would send PVP and 60 mechanics before any character.
    assert current.canonical_terms[:4] == ("终末地", "塔卫二", "PVP", "丁类机制名称00")
    assert current.hotword_terms[:10] == ("终末地", "塔卫二", "陈千语", "佩丽卡", "源石", "熔岩巨像",
                                          "莱万汀", "便携电池", "PVP", "丁类机制名称00")
    assert sorted(current.hotword_terms) == sorted(current.canonical_terms)
    assert len(current.hotword_terms) == len(current.canonical_terms)
    # A view only: the frozen snapshot and its digest are unchanged.
    assert "hotword" not in json.dumps(current.to_dict())
    assert current.digest == type(current).from_dict(current.to_dict()).digest


def test_case_only_variant_is_not_a_mishearing():
    current = snapshot_glossaries(library([row("pvp", "PVP", "玩家用语"), row("QQ", "QQ", "玩家用语"),
                                           row("Tl", "Tom", "玩家用语")]), ["zmd"])
    assert current.hotword_terms == ("Tom", "PVP", "QQ")


def test_objects_without_ranking_keep_their_canonical_order():
    assert recognition_hotwords(SimpleNamespace(canonical_terms=["B", "A"])) == ("B", "A")
    assert recognition_hotwords(SimpleNamespace()) == ()


NAMES = {"陈千语", "佩丽卡", "莱万汀", "熔岩巨像", "源石"}


def test_every_recognition_hint_receives_the_names_first():
    from twobyteasr.asr_api_process import cloud_request_hints
    from twobyteasr.mosi_asr import MODEL as MOSI_MODEL
    from twobyteasr.qwen31_asr import FILETRANS
    from twobyteasr import asr
    from twobyteasr.runtime import RuntimeContext, activate_runtime_context
    context = RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=["zmd"], glossary_snapshot=snapshot())
    with activate_runtime_context(context):
        qwen = asr.build_qwen_asr_context("clip.mp4")
        mosi = cloud_request_hints({"model": MOSI_MODEL}, {})
        filetrans = cloud_request_hints({"model": FILETRANS}, {})
    listed = qwen.split("用户已确认的专名写法：", 1)[1].split("。", 1)[0].split("、")
    assert NAMES <= set(listed[:7]) and len(listed) < len(snapshot().canonical_terms)
    assert NAMES <= set(mosi["mosi_keyterms"]) and len(mosi["mosi_keyterms"]) == 20
    sent = filetrans["filetrans_context"][0]["content"][0]["text"]
    assert all(name in sent for name in NAMES)
    assert filetrans["hint_counts"]["context_omitted_terms"] > 0


def test_hidden_reference_names_written_by_the_page_leave_the_snapshot(tmp_path, monkeypatch):
    lexicon = tmp_path / "lexicon.json"
    lexicon.write_text(json.dumps({"game": "测试游戏", "entries": [{"name": "图鉴甲"}, {"name": "图鉴乙"}]},
                                  ensure_ascii=False), encoding="utf-8")
    profiles = {"测试游戏": {"identity": "测试游戏", "lexicons": ["lexicon.json"], "terms": [
        {"canonical": "内置甲", "aliases": ["内置误听"], "category": "character", "source": "wiki", "confirmed": True},
        {"canonical": "内置乙", "aliases": [], "category": "character", "source": "wiki", "confirmed": True}]}}
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "terms.json"))
    monkeypatch.setattr(legacy, "load_game_profiles", lambda: profiles)
    monkeypatch.setattr(legacy, "_profile_lexicon_paths_for", lambda profile: [str(lexicon)] if profile else [])
    identity = legacy.runtime_game_identity(legacy.canonicalize_runtime_game_name("测试游戏"))
    before = snapshot_glossaries(legacy, [identity])
    assert before.libraries[0].reference_terms == ("图鉴甲", "图鉴乙")
    assert TermResolver(before).resolve("内置误听").text == "内置甲"
    # The term library page's own writer (hidden_reference_terms).
    assert legacy.set_reference_terms_hidden("测试游戏", ["图鉴甲", "内置甲"], True) == 2
    after = snapshot_glossaries(legacy, [identity])
    assert after.libraries[0].reference_terms == ("图鉴乙",)
    assert "内置甲" not in after.canonical_terms and "内置乙" in after.canonical_terms
    assert TermResolver(after).resolve("内置误听").text == "内置误听"


def test_older_hidden_key_still_works_and_user_verified_builtin_rows_stay(tmp_path):
    lexicon = tmp_path / "lexicon.json"
    lexicon.write_text(json.dumps({"entries": [{"name": "图鉴甲"}, {"name": "图鉴乙"}]}, ensure_ascii=False),
                       encoding="utf-8")
    terms = [{"canonical": "核验丙", "aliases": [], "category": "character", "source": "user_verified"}]
    current = snapshot_glossaries(library([], terms, {"hidden_references": ["图鉴乙"],
        "hidden_reference_terms": ["核验丙"]}, lexicon), ["zmd"])
    assert current.libraries[0].reference_terms == ("图鉴甲",)
    assert current.canonical_terms == ("核验丙",)


def test_builtin_zzz_profile_keeps_phaethon_as_its_own_name(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(tmp_path / "terms.json"))
    profiles = legacy.load_game_profiles()
    assert not [term["canonical"] for profile in profiles.values() for term in profile.get("terms", ())
                if "法厄同" in term.get("aliases", ())]
    current = snapshot_glossaries(legacy, ["绝区零"])
    assert {"绳匠", "法厄同"} <= set(current.canonical_terms)
    text = "焚昼余火·法厄同来了，绳匠快跑"
    assert TermResolver(current).resolve(text).text == text
    monkeypatch.setattr(legacy, "RUNTIME_GAME_NAME", "绝区零")
    assert not [rule for rule in legacy.active_profile_alias_rules() if rule["source"] == "法厄同"]

