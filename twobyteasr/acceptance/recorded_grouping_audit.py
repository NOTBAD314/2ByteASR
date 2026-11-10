"""Replay recorded shard answers through the source and frozen production path."""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main(output_directory, fixture):
    output = Path(output_directory).resolve()
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output / "profile")
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    import subtitle_core as core
    from twobyteasr.recognition.pipeline_runtime import finalize_cues, normalize_delivered_cue_text
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.shard_identity import namespace_result, STRIDE
    from twobyteasr.recognition.streaming_recognition import ShardResult
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_quality import QUALITY_VERSION
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.subtitle_rules.text_rules import content_exact
    from twobyteasr.subtitle_rules.timing import refresh_final_cue_reviews
    from twobyteasr.subtitle_rules.display_timing import protect_runtime_display_tails
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.projects.studio_project import create_studio_outputs, load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    from twobyteasr.diagnostics.build_identity import load_build_identity

    events = []
    requests = []
    results = []
    checks = {}
    active_shard = ""
    workers = int(fixture.get("workers", 1))
    snapshot = resolve_provider_snapshot({"models": {
        "ai_service": "custom", "provider_profiles": {"custom": {
            "base_url": "http://127.0.0.1:1/v1", "model": "recorded-offline-answers"}}}})

    def record(event, **payload):
        payload.setdefault("shard_id", active_shard)
        events.append(dict(event=event, **payload))

    try:
        with language_scope("zh"), patch.object(core, "record_run_event", side_effect=record), patch.object(
                grouping, "record_run_event", side_effect=record), patch.object(
                grouping, "GROUP_API_BATCH_MAX_CUES", 32), patch.object(
                grouping, "_clear_short_utterance", return_value=False), patch.object(
                grouping, "CLOUD_BATCH_WORKERS", workers), patch.object(grouping, "PARALLEL_CLOUD_BATCHES", True):
            for index, shard in enumerate(fixture["shards"]):
                active_shard = shard["id"]
                traces = {tuple(batch["source_segment_ids"]): batch for batch in shard["batches"]}

                def complete(messages, **options):
                    body = json.loads(messages[1]["content"])
                    requests.append(dict(shard=shard["id"], batch=options.get("batch_index"),
                                         source_text=body["source_text"], retry="failed_constraints" in body))
                    if "failed_constraints" in body:
                        return json.dumps(dict(boundaries=body["current_boundaries"]))
                    ids = tuple(row["id"] for row in body["segments"])
                    trace = traces[ids]
                    if body["source_text"] != trace["source_text"]:
                        raise ValueError("Recorded source identity changed during replay.")
                    if fixture.get("reverse_completion"):
                        import time
                        time.sleep((len(traces)-trace["batch_index"])*.001)
                    return json.dumps(dict(boundaries=trace["model_boundaries"]))

                context = RuntimeContext(task_language="zh", requested_language="zh",
                    enable_domain_terms=False, provider_snapshot=snapshot, shard_id=shard["id"])
                context.review_items.extend(copy.deepcopy(shard.get("upstream_reviews", [])))
                sources = core.deserialize_segments(shard["segments"])
                original = copy.deepcopy(sources)
                with activate_runtime_context(context, legacy=core), patch.object(
                        grouping, "provider_for_stage", return_value=SimpleNamespace(complete=complete)):
                    cues = grouping.group_subtitles(sources, fixture["acoustic_tokens"],
                        fixture.get("speech_regions", []), use_ai=True,
                        provider_snapshot=snapshot, max_workers=workers)
                    cues = finalize_cues(cues, sources, fixture["acoustic_tokens"],
                        fixture.get("speech_regions", []), shard["bounds"][1], fixture["fps"], core)
                    for number, cue in enumerate(cues, 1):
                        cue.cue_id = (index+1)*STRIDE+number
                    normalize_delivered_cue_text(cues, core)
                    checks[shard["id"]+"_immutable_sources"] = sources == original
                    result = ShardResult(index, "recorded", [], sources, cues, {}, list(context.review_items))
                    namespace_result(result)
                    results.append(result)

            active_shard = ""
            sources = sorted([source for result in results for source in result.segments],
                             key=lambda source: (source.start, source.end, source.segment_id))
            cues = sorted([cue for result in results for cue in result.cues],
                          key=lambda cue: (cue.start, cue.end, cue.cue_id))
            context = RuntimeContext(task_language="zh", requested_language="zh", enable_domain_terms=False)
            context.review_items.extend(item for result in results for item in result.reviews)
            context.review_items.extend(copy.deepcopy(fixture.get("delivery_reviews", [])))
            with activate_runtime_context(context, legacy=core):
                protect_runtime_display_tails(cues, sources)
                core.relock_display_timing(cues, fixture["audio_seconds"], fixture["fps"], stage="ready_shards_collection")
                cues = core.validate_final_cues(cues, sources, fixture["audio_seconds"], validate_text=False)
                # Reuse the labels already adopted in the recorded delivery.
                # This step performs no new speaker inference or embedding.
                aliases = fixture.get("speaker_aliases", {})
                for source in sources:
                    native = source.speaker
                    source.speaker = aliases.get(native, native)
                    source.caption_arbitration["recorded_native_speaker"] = native
                for cue in cues:
                    cue.speaker = aliases.get(cue.speaker, cue.speaker)
                refresh_final_cue_reviews(cues, sources, legacy=core, audio_seconds=fixture["audio_seconds"])
                texts = [cue.text for cue in cues]
                joined = "".join(content_exact(cue.text) for cue in cues)
                for term in ("开出来", "我这个阵容", "光能聚集", "右下柱"):
                    occurrences = [i for i in range(len(joined)) if joined.startswith(term, i)]
                    edges = set()
                    cursor = 0
                    for cue in cues:
                        cursor += len(content_exact(cue.text))
                        edges.add(cursor)
                    checks["intact_"+term] = bool(occurrences) and all(
                        not start < edge < start+len(term) for start in occurrences for edge in edges)
                checks["predicate_object_repaired"] = "对直接下契约了" in texts
                checks["condition_source_retained"] = any('然后你明天一来' in text for text in texts)
                checks["next_predicate_retained"] = "直接就是900块开始" in texts
                checks["pronoun_not_left_behind"] = not set(texts) & {"国服第一玩我", "这个阵容我", "也很紧张我", "比你都紧张"}
                checks["hard_character_limit"] = all(core.display_length(cue.text) <= 14 for cue in cues)
                checks["unique_source_ids"] = len({source.segment_id for source in sources}) == len(sources)
                checks["unique_cue_ids"] = len({cue.cue_id for cue in cues}) == len(cues)
                speakers = {source.speaker for source in sources}
                checks["per_speaker_content_conserved"] = all(
                    "".join(content_exact(cue.text) for cue in cues if cue.speaker == speaker)
                    == "".join(content_exact(source.text) for source in sources if source.speaker == speaker)
                    for speaker in speakers)
                report = dict(report_kind="recorded_grouping_replay", review_items=context.review_items, events=events)
                (output/"regroup-report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                paths = create_studio_outputs(fixture.get("media_path", str(output/"fixture.mp4")), cues,
                    txt_path="", srt_path="", report_path=str(output/"regroup-report.json"), segments=sources,
                    generation_metadata={"language": {"code": "zh"}, "created_by": "recorded grouping replay"},
                    target_project_path=str(output/"replay.2byteproj"), decoded_audio_seconds=fixture["audio_seconds"])
                if paths.get("project_error"):
                    raise ValueError(paths["project_error"])
                project = load_project(output/"replay.2byteproj")
                checks["saved_reopened_identical"] = [(cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues] == [
                    (cue.text, round(cue.start*1000), round(cue.end*1000), cue.speaker) for cue in cues]
                exported = export_language_layers(project, output/"export", "replay", layers=("original",))
                original_srt = next(artifact.path for artifact in exported.artifacts if artifact.layer == "original")
                parsed = parse_srt(original_srt.read_text(encoding="utf-8"))[0]
                checks["srt_matches_project"] = [(cue.text, cue.start_ms, cue.end_ms) for cue in parsed] == [
                    (cue.text, cue.start_ms, cue.end_ms) for cue in project.cues]
                checks["evidence_retained"] = len(project.asr_evidence) == len(sources) and all(cue.evidence_refs for cue in project.cues)
                checks["upstream_notices_retained"] = all(
                    item in context.review_items for item in fixture.get("delivery_reviews", []))
                serialized = core.serialize_cues(cues)
                result = dict(passed=all(checks.values()), checks=checks, events=events, requests=requests,
                    real_provider_requests=0, quality_retry_candidates="deterministic offline baseline echo",
                    quality_version=QUALITY_VERSION, identity=load_build_identity().to_dict(),
                    source_segments=len(sources), final_cues=serialized, project=str(output/"replay.2byteproj"),
                    review_items=context.review_items, review_counts=dict(Counter(item["category"] for item in context.review_items)),
                    request_statuses=dict(Counter(event.get("result_status") for event in events if event["event"] == "asr_provider_request")),
                    timeline_sha256=hashlib.sha256(json.dumps(serialized, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
    except Exception as error:
        import traceback
        result = dict(passed=False, error=str(error), traceback=traceback.format_exc(), checks=checks,
                      events=events, requests=requests, real_provider_requests=0)
    (output/"comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1
