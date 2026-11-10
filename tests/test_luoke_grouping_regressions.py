"""Fixed real model answers with shard-scoped corrected source evidence."""
import copy
import json
from pathlib import Path

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments
from twobyteasr.subtitle_rules.language_rules import language_scope

FIXTURE_PATH = Path(__file__).parent / "fixtures/grouping_contract/luoke_cfeea.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
BATCHES = [(shard["id"], batch["batch_index"])
           for shard in FIXTURE["shards"] for batch in shard["batches"]]


@pytest.fixture(autouse=True)
def chinese_task():
    with language_scope("zh"), activate_runtime_context(
            RuntimeContext(task_language="zh", enable_domain_terms=False), legacy=core):
        yield


def replay(shard_id, batch_id):
    shard = next(shard for shard in FIXTURE["shards"] if shard["id"] == shard_id)
    batch = next(batch for batch in shard["batches"] if batch["batch_index"] == batch_id)
    sources = [row for row in core.deserialize_segments(shard["segments"])
               if row.segment_id in batch["source_segment_ids"]]
    quality = quality_for_segments(sources, FIXTURE["acoustic_tokens"],
                                   protected=batch["protected_source_offsets"])
    cuts, issues = quality.repair(batch["model_boundaries"])
    return quality, cuts, issues, sources, batch


def assert_term_intact(quality, cuts, term):
    position = quality.index.content.find(term)
    while position >= 0:
        assert not any(position < cut < position+len(term) for cut in cuts), term
        position = quality.index.content.find(term, position+1)


def test_overlength_first_sentence_uses_complete_predicate_and_complement():
    quality, cuts, issues, _, batch = replay("r001", 1)
    assert len(core.content_exact(batch["model_texts"][0])) == 26
    assert_term_intact(quality, cuts, "开出来")
    assert ''.join(quality.index.pieces(cuts)[:3]) == ''.join(batch['model_texts'][:1]) + '就结束了'
    assert all(core.display_length(piece) <= 14 for piece in quality.index.pieces(cuts))
    assert not issues


def test_raw_model_pronouns_return_to_their_own_subject_phrases():
    quality, cuts, _, _, _ = replay("r001", 1)
    pieces = quality.index.pieces(cuts)
    assert "国服第一玩我这个阵容" in pieces
    assert "我也很紧张" in pieces and "我比你都紧张" in pieces
    assert not set(pieces) & {"国服第一玩我", "这个阵容我", "也很紧张我", "比你都紧张"}


def test_source_and_model_consensus_outrank_cross_source_hmm_name():
    quality, cuts, _, _, _ = replay("r002", 3)
    pieces = quality.index.pieces(cuts)
    assert "打冰雹的话他会被控费" in pieces
    assert "对直接下契约了" in pieces
    assert not any(piece == "契约了" for piece in pieces)


def test_repeated_commands_keep_the_directional_noun():
    quality, cuts, _, _, _ = replay("r002", 4)
    assert_term_intact(quality, cuts, "右下柱")
    assert sum(piece.count('打右下柱') for piece in quality.index.pieces(cuts)) == quality.index.text.count('打右下柱')


def test_event_classifier_does_not_split_action_name():
    quality, cuts, _, _, _ = replay("r002", 11)
    assert_term_intact(quality, cuts, "光能聚集")
    assert "对的" in quality.index.pieces(cuts)


def test_completed_temporal_clause_is_not_treated_as_a_stranded_adverb():
    quality, cuts, _, _, _ = replay("r003", 13)
    pieces = quality.index.pieces(cuts)
    assert any('然后你明天一来' in piece for piece in pieces)
    assert "直接就是900块开始" in pieces
    assert "开始" not in pieces


def test_real_cross_speaker_source_boundary_is_preserved():
    quality, cuts, _, _, _ = replay("r003", 2)
    assert 26 in quality.required and 26 in cuts
    pieces = quality.index.pieces(cuts)
    assert "可以" in pieces


@pytest.mark.parametrize("shard_id,batch_id", BATCHES)
def test_every_recorded_batch_keeps_content_and_stops_drifting(shard_id, batch_id):
    quality, cuts, _, sources, batch = replay(shard_id, batch_id)
    original = copy.deepcopy(sources)
    assert "".join(quality.index.pieces(cuts)) == batch["source_text"]
    assert all(end-start <= 14 for start, end in zip([0, *cuts], cuts))
    again = quality_for_segments(sources, FIXTURE["acoustic_tokens"],
                                 protected=batch["protected_source_offsets"])
    assert again.repair(cuts)[0] == cuts
    assert sources == original
