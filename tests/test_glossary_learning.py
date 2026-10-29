import json

from twobyteasr.glossary.glossary_learning import (
    GlossaryLearningStore,
    extract_term_replacements,
    new_evidence_token,
)


def test_three_manual_corrections_become_pending_and_accept_to_selected_glossary(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    for index in range(3):
        changed = store.record_manual_edit(
            f"这里是那维来特第{index}段",
            f"这里是那维莱特第{index}段",
            project="原神直播.2byteproj",
            speaker="S01",
            context="这里是那维莱特",
        )
        assert changed

    pending = store.pending()
    assert len(pending) == 1
    assert pending[0]["original_term"] == "那维来特"
    assert pending[0]["corrected_term"] == "那维莱特"
    assert pending[0]["occurrence_count"] == 3
    calls = []

    def add_mapping(glossary, source, target, **metadata):
        calls.append((glossary, source, target, metadata))
        return True

    assert store.accept([pending[0]["id"]], "原神", add_mapping=add_mapping) == 1
    assert calls[0][:3] == ("原神", "那维来特", "那维莱特")
    assert store.pending() == []
    payload = json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))
    assert payload["candidates"][0]["accepted_glossary"] == "原神"


def test_general_sentence_edits_and_ai_edits_are_not_learned(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    assert extract_term_replacements("今天天气真的不错我们出门吧", "这句话已经被彻底改写成另一句") == []
    assert store.record_manual_edit("一整句普通字幕", "另一整句普通字幕") == []
    assert store.record_manual_edit("那维来特", "那维莱特", origin="ai_apply") == []
    assert not (tmp_path / "learning.json").exists()


def test_ignored_candidate_does_not_resurface(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json", threshold=2)
    store.record_manual_edit("那维来特登场", "那维莱特登场")
    store.record_manual_edit("欢迎那维来特", "欢迎那维莱特")
    candidate = store.pending()[0]
    assert store.ignore([candidate["id"]]) == 1
    store.record_manual_edit("又是那维来特", "又是那维莱特")
    assert store.pending() == []


def test_xingjian_correction_is_compact_persistent_and_filters_automatic_origins(tmp_path):
    path = tmp_path / "learning.json"
    store = GlossaryLearningStore(path, threshold=2)
    assert store.record_manual_edit("我觉得星见鸦很强", "我觉得星见雅很强", origin="safe_fix") == []
    assert store.record_manual_edit("我觉得星见鸦很强", "我觉得星见雅很强", origin="llm") == []
    store.record_manual_edit("我觉得星见鸦很强", "我觉得星见雅很强", origin="user_edit", project="绝区零")
    store.record_manual_edit("星见鸦登场", "星见雅登场", origin="search_replace", project="绝区零")

    candidate = GlossaryLearningStore(path, threshold=2).pending()[0]
    assert (candidate["original_term"], candidate["corrected_term"]) == ("星见鸦", "星见雅")
    assert candidate["occurrence_count"] == 2
    assert candidate["confidence"] > 0.5
    assert candidate["accepted"] is False
    assert candidate["ignored"] is False


def test_single_manual_edit_is_immediately_visible(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    changed = store.record_manual_edit("那维来特很强", "那维莱特很强", origin="user_edit")
    assert len(changed) == 1
    pending = store.pending()
    assert len(pending) == 1
    assert pending[0]["occurrence_count"] == 1
    assert pending[0]["origin"] == "user_edit"


def test_same_token_never_counts_twice(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    token = new_evidence_token()
    store.record_manual_edit("那维来特很强", "那维莱特很强", origin="user_edit", token=token)
    store.record_manual_edit("那维来特很强", "那维莱特很强", origin="user_edit", token=token)
    pending = store.pending()
    assert len(pending) == 1
    assert pending[0]["occurrence_count"] == 1  # redo 幂等


def test_revert_evidence_removes_only_stale_tokens(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    # 链 1：A→B 提交（结果文本 B）
    store.record_manual_edit(
        "那维来特很强", "那维莱特很强", origin="user_edit", token="tok-chain1"
    )
    # 链 2：另一处修改再提交（结果文本 星见雅登场）
    store.record_manual_edit(
        "星见鸦登场", "星见雅登场", origin="user_edit", token="tok-chain2"
    )
    assert len(store.pending()) == 2
    # 撤销链 2：恢复文本"星见鸦登场"→ 链 2 证据回退，链 1 保留
    removed = store.revert_evidence(["tok-chain2"], cue_after_text="星见鸦登场")
    assert removed == 1
    pending = store.pending()
    assert [(item["original_term"], item["corrected_term"]) for item in pending] == [
        ("那维来特", "那维莱特")
    ]


def test_revert_keeps_accepted_record_without_evidence(tmp_path):
    store = GlossaryLearningStore(tmp_path / "learning.json")
    store.record_manual_edit("星见鸦登场", "星见雅登场", origin="user_edit", token="tok-1")
    candidate = store.pending()[0]
    calls = []

    def add_mapping(glossary, source, target, **metadata):
        calls.append((glossary, source, target, metadata))
        return True

    store.accept([candidate["id"]], "绝区零", add_mapping=add_mapping)
    assert calls and "手动修改" in calls[0][3]["origin"]
    store.revert_evidence(["tok-1"])
    payload = store.load()
    entry = payload["candidates"][0]
    assert entry["status"] == "accepted"  # 确认记录保留，不因撤销静默删除
    assert entry["occurrence_count"] == 0
    assert store.pending() == []  # 但不再出现在待学习列表


def test_legacy_v2_payload_migrates_without_inflation(tmp_path):
    path = tmp_path / "learning.json"
    legacy = {
        "schema_version": 2,
        "candidates": [
            {
                "id": GlossaryLearningStore._identity("那维来特", "那维莱特"),
                "original_term": "那维来特",
                "corrected_term": "那维莱特",
                "occurrence_count": 5,
                "status": "pending",
                "origin": "user_manual",
                "sources": ["studio_manual_edit"],
            }
        ],
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    store = GlossaryLearningStore(path)
    pending = store.pending()
    assert len(pending) == 1
    assert pending[0]["occurrence_count"] == 5  # 旧计数保留，不膨胀
    store.record_manual_edit("又是那维来特", "又是那维莱特", origin="user_edit", token="tok-new")
    pending = store.pending()
    assert pending[0]["occurrence_count"] == 6
