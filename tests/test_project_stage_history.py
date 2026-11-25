from twobyteasr.storage import project_stage_history as history


def test_recognition_sources_follow_executed_model_routes():
    rows = {
        "planned": dict(role="primary_transcription", backend="api", selected=True),
        "real": dict(role="primary_transcription", backend="qwen_local", completed=True),
        "ultra": dict(role="timeline_alignment", backend="qwen_ultra_aligner", completed=True),
        "earlier": dict(role="timeline_alignment", backend="qwen_aligner", failed=True),
        "old": "historical status",
    }
    assert history.model_execution_receipt(rows, "primary_transcription") == ("completed", "qwen_local")
    assert history.model_execution_receipt(rows, "timeline_alignment") == ("partial", "qwen_ultra_aligner")
    assert history.model_execution_receipt(rows, "review") == ("", "")


def test_project_history_preserves_partial_results_without_content(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_database", lambda: tmp_path / "history.sqlite3")
    first = history.record_stage("source-project", "translation", "partial", applied=7, failed=2,
                                 raw_text="not part of the stage receipt")
    second = history.record_stage("different-project", "proofread", "completed", applied=3)
    first.result(timeout=5)
    second.result(timeout=5)
    assert history.recent_stages("source-project").result(timeout=5) == [
        {"stage": "translation", "outcome": "partial", "counts": {"applied": 7, "failed": 2}}
    ]
    assert history.recent_stages("missing-project").result(timeout=5) == []


def test_retry_records_only_a_real_terminal_attempt(tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
    from twobyteasr.studio.studio_task_progress import SubtitleTask

    monkeypatch.setattr(history, "_database", lambda: tmp_path / "history.sqlite3")
    project = SubtitleProject(media=StudioMedia(""))
    restored = SubtitleTask("AI 断句", ("a",))
    restored.project = project
    restored.finish(record_history=False)
    assert history.recent_stages(project.project_id).result(timeout=5) == []

    attempt = SubtitleTask("批量重新识别", ("a",), is_retry=True)
    attempt.project = project
    attempt.update({"range_id": "a", "cue_ids": ["a"], "status": "suggestion"})
    attempt.finish()
    attempt.finish()
    rows = history.recent_stages(project.project_id).result(timeout=5)
    assert [(row["stage"], row["outcome"], row.get("source")) for row in rows] == [
        ("retry", "suggestion", "re_asr_retry"), ("re_asr", "suggestion", None)]


def test_latest_receipts_keep_each_phase_through_many_later_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_database", lambda: tmp_path / "history.sqlite3")
    history.record_stage("project", "download", "completed", tracks=1)
    history.record_stage("different", "json3", "completed", tracks=2)
    for _ in range(20):
        history.record_stage("project", "re_asr", "failed", failed=1)
    history.record_stage("project", "re_asr", "suggestion", suggested=1)
    assert history.latest_stages("project").result(timeout=5) == [
        {"stage": "re_asr", "outcome": "suggestion", "counts": {"suggested": 1}},
        {"stage": "download", "outcome": "completed", "counts": {"tracks": 1}},
    ]


def test_pages_keep_order_sources_and_project_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_database", lambda: tmp_path / "history.sqlite3")
    for value in range(5):
        history.record_stage("owner", "download", "completed", source="youtube", tracks=value)
    history.record_stage("other", "alignment", "suggestion", source="sylla", tracks=99)
    first, cursor = history.stage_page("owner", limit=3).result(timeout=5)
    assert [item["counts"]["tracks"] for item in first] == [4, 3, 2]
    assert all(item["source"] == "youtube" and item["finished"] > 0 for item in first)
    assert cursor is not None
    second, end = history.stage_page("owner", before=cursor, limit=3).result(timeout=5)
    assert [item["counts"]["tracks"] for item in second] == [1, 0]
    assert end is None
