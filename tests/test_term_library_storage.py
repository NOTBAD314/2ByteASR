import json

import subtitle_core


def test_delete_user_created_game_removes_learned_terms_and_history(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned_game_terms.json"
    history_path = tmp_path / "game_profile_history.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))
    monkeypatch.setattr(subtitle_core, "PROFILE_HISTORY_PATH", str(history_path))

    subtitle_core.persist_learned_mappings(
        "鹰角嘉年华",
        [
            {
                "from": "嘉年化",
                "to": "嘉年华",
                "reason": "人工确认",
                "confirmed": True,
            }
        ],
    )
    subtitle_core.save_runtime_game_history("鹰角嘉年华")
    subtitle_core.save_runtime_game_history("崩坏：星穹铁道")

    assert subtitle_core.delete_learned_game("鹰角嘉年华") is True
    assert subtitle_core.delete_runtime_game_history("鹰角嘉年华") is True
    assert subtitle_core.learned_mappings_for_game("鹰角嘉年华") == []
    assert subtitle_core.load_runtime_game_history() == ["崩坏星穹铁道"]
    payload = json.loads(learned_path.read_text(encoding="utf-8"))
    assert subtitle_core.runtime_game_identity("鹰角嘉年华") not in payload["games"]


def test_delete_missing_game_is_non_destructive(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned_game_terms.json"
    history_path = tmp_path / "game_profile_history.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))
    monkeypatch.setattr(subtitle_core, "PROFILE_HISTORY_PATH", str(history_path))
    history_path.write_text('{"recent_games":["原神"]}\n', encoding="utf-8")

    assert subtitle_core.delete_learned_game("不存在") is False
    assert subtitle_core.delete_runtime_game_history("不存在") is False
    assert subtitle_core.load_runtime_game_history() == ["原神"]


def test_profile_migration_only_imports_explicit_user_verified_terms(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned_game_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))
    monkeypatch.setattr(
        subtitle_core,
        "load_game_profiles",
        lambda: {
            "洛克王国：世界": {
                "identity": "洛克王国世界",
                "terms": [
                    {
                        "canonical": "迪莫",
                        "aliases": ["迪莫莫"],
                        "source": "user_verified_manual_srt_2026-08-03",
                        "category": "角色",
                    },
                    {
                        "canonical": "圣光迪莫",
                        "aliases": [],
                        "source": "official_wiki",
                        "category": "角色",
                    },
                ],
            }
        },
    )

    assert subtitle_core.migrate_user_verified_profile_terms() == 2
    confirmed = subtitle_core.user_confirmed_mappings_for_game("洛克王国：世界")
    assert {(item["from"], item["to"]) for item in confirmed} == {
        ("迪莫", "迪莫"),
        ("迪莫莫", "迪莫"),
    }
    assert subtitle_core.builtin_reference_terms_for_game("洛克王国：世界") == ["圣光迪莫"]
    assert subtitle_core.migrate_user_verified_profile_terms() == 0


def test_only_user_actions_count_as_confirmed(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned_game_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))

    subtitle_core.persist_learned_mappings(
        "原神",
        [{"from": "自动候选", "to": "自动候选", "confirmed": True}],
    )
    assert subtitle_core.user_confirmed_mappings_for_game("原神") == []

    assert subtitle_core.add_learned_mapping(
        "原神", "芙宁那", "芙宁娜", origin="批量导入"
    )
    confirmed = subtitle_core.user_confirmed_mappings_for_game("原神")
    assert [(item["from"], item["to"], item["provenance"]) for item in confirmed] == [
        ("芙宁那", "芙宁娜", subtitle_core.TERM_PROVENANCE_USER_CONFIRMED)
    ]


def test_profile_hide_persists_until_user_recreates_library(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned_game_terms.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))

    assert subtitle_core.hide_runtime_game_profile("鹰角嘉年华") is True
    assert subtitle_core.is_runtime_game_profile_hidden("鹰角嘉年华") is True
    reloaded = json.loads(learned_path.read_text(encoding="utf-8"))
    assert subtitle_core.runtime_game_identity("鹰角嘉年华") in reloaded["hidden_profile_ids"]

    assert subtitle_core.ensure_learned_content("鹰角嘉年华", "event") is True
    assert subtitle_core.is_runtime_game_profile_hidden("鹰角嘉年华") is False
