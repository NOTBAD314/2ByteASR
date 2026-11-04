import subtitle_core


def test_content_entry_type_can_exist_before_terms(tmp_path, monkeypatch):
    learned_path = tmp_path / "learned.json"
    monkeypatch.setattr(subtitle_core, "LEARNED_TERMS_PATH", str(learned_path))

    assert subtitle_core.ensure_learned_content("鹰角嘉年华", "event")
    assert subtitle_core.learned_content_type("鹰角嘉年华") == "event"
    assert subtitle_core.learned_mappings_for_game("鹰角嘉年华") == []
    assert subtitle_core.delete_learned_game("鹰角嘉年华")
