"""Production persistence/queue checks with isolated, locally generated input."""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from twobyteasr.recognition_result import (
    RecognitionResultMismatch, committed_result_reference, media_identity_for_task,
    recognition_project_path, verify_result_reference,
)
from twobyteasr.runtime import RuntimeContext, activate_runtime_context
from twobyteasr.service import CancellationToken, RunOptions, run_media_queue
from twobyteasr.studio_project import create_studio_outputs, load_project, save_project
from tests.test_service_layer import FakeLegacy, FakePipeline


def media(tmp_path, relative="same.wav", value=0):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(int(value).to_bytes(2, "little", signed=True) * 16000)
    return path


def cues(text="本次字幕"):
    return [SimpleNamespace(cue_id="c1", start=.1, end=.6, text=text, speaker="S01")]


@pytest.fixture
def owned_library(tmp_path, monkeypatch):
    import twobyteasr.studio_project as storage
    root = tmp_path / "Projects"
    monkeypatch.setattr(storage, "project_library_root", lambda *a, **k: root)
    return root


def create(path, job, text="本次字幕", target="", snapshot=None):
    identity = media_identity_for_task(path, RuntimeContext())
    return create_studio_outputs(path, cues(text), txt_path="", target_project_path=target,
        generation_metadata={"job_id": job, "media_identity": identity}, recognition_snapshot=snapshot)


def test_same_basename_and_same_source_new_jobs_keep_independent_projects(tmp_path, owned_library):
    first_media = media(tmp_path, "A/same.wav", 0)
    second_media = media(tmp_path, "B/same.wav", 500)
    a = create(first_media, "a")
    a_path = Path(a["project"])
    old = load_project(a_path)
    old.cues[0].text = "旧工程人工编辑"
    save_project(old, a_path)
    before = a_path.read_bytes()
    b = create(second_media, "b", "另一个同名文件")
    c = create(first_media, "c", "同源新任务")
    projects = [load_project(r["project"]) for r in (a, b, c)]
    assert len({r["project"] for r in (a, b, c)}) == 3
    assert len({p.project_id for p in projects}) == 3
    assert a_path.read_bytes() == before
    assert verify_result_reference(b["result_ref_json"]).cues[0].text == "另一个同名文件"
    assert verify_result_reference(c["result_ref_json"]).cues[0].text == "同源新任务"


def test_same_job_delivery_idempotent_and_conflicting_or_edited_result_protected(tmp_path, owned_library):
    path = media(tmp_path)
    first = create(path, "same-job")
    target = Path(first["project"])
    before = target.read_bytes(), target.stat().st_mtime_ns
    duplicate = create(path, "same-job")
    assert duplicate == first
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    with pytest.raises(ValueError, match="同一识别任务"):
        create(path, "same-job", "不同晚到结果")
    assert target.read_bytes() == before[0]
    edited = load_project(target)
    edited.cues[0].text = "后续人工编辑"
    save_project(edited, target)
    edited_bytes = target.read_bytes()
    with pytest.raises(RecognitionResultMismatch):
        create(path, "same-job")
    assert target.read_bytes() == edited_bytes
    assert len(list(owned_library.glob("*/*.2byteproj"))) == 1


def test_another_job_cannot_overwrite_explicit_target(tmp_path, owned_library):
    path = media(tmp_path)
    first = create(path, "job-a")
    before = Path(first["project"]).read_bytes()
    with pytest.raises(ValueError, match="其它任务"):
        create(path, "job-b", target=first["project"])
    assert Path(first["project"]).read_bytes() == before


def test_same_job_duplicate_or_conflict_cannot_overwrite_committed_artifacts(tmp_path, owned_library):
    source = media(tmp_path)
    txt = tmp_path/"incoming.txt"
    report = tmp_path/"incoming.json"
    txt.write_text("首个已提交文稿", "utf8")
    report.write_text('{"revision":1}', "utf8")
    identity = media_identity_for_task(source, RuntimeContext())
    metadata = {"job_id":"artifact-job", "media_identity":identity}
    def deliver(text="本次字幕"):
        return create_studio_outputs(source, cues(text), txt_path=str(txt), report_path=str(report), generation_metadata=metadata)
    first = deliver()
    parent = Path(first["project"]).parent
    before = {str(p.relative_to(parent)):(p.read_bytes(), p.stat().st_mtime_ns) for p in parent.rglob("*") if p.is_file()}
    txt.write_text("晚到文稿不能覆盖首个交付", "utf8")
    report.write_text('{"revision":2}', "utf8")
    assert deliver() == first
    with pytest.raises(ValueError, match="同一识别任务"):
        deliver("冲突晚到字幕")
    after = {str(p.relative_to(parent)):(p.read_bytes(), p.stat().st_mtime_ns) for p in parent.rglob("*") if p.is_file()}
    assert after == before


def test_source_changed_between_commit_and_studio_open_is_rejected(tmp_path, owned_library):
    source = media(tmp_path)
    result = create(source, "completed-before-replace")
    source.write_bytes(source.read_bytes()+b"replacement")
    with pytest.raises(RecognitionResultMismatch, match="媒体文件已改变"):
        verify_result_reference(result["result_ref_json"])


@pytest.mark.parametrize("change", ["trim", "timeline", "source", "stream", "rate", "geometry", "manual_counter"])
def test_ref_rejects_graph_or_manual_revision_only_changes_but_library_open_remains_valid(tmp_path, owned_library, change):
    result = create(media(tmp_path), "graph-ref-job")
    path = Path(result["project"])
    project = load_project(path)
    cue_before = [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues]
    audio_clip = project.audio_tracks[0].clips[0]
    from twobyteasr.studio_edit_sequence import sequence_of
    sequence = sequence_of(project)
    if change == "trim":
        sequence.segments[0].source_in_ms += 10
        sequence.segments[0].timeline_out_ms -= 10
    elif change == "timeline":
        sequence.segments[0].timeline_in_ms += 10
        sequence.segments[0].timeline_out_ms += 10
    elif change == "source": project.media.path = str(media(tmp_path, "other.wav", 10))
    elif change == "stream": audio_clip.stream_index += 1
    elif change == "rate": sequence.segments[0].timeline_out_ms += 10
    elif change == "geometry": project.media.width += 16
    else: project.edit_history.append({"command": "manual-adjustment", "revision": 1})
    save_project(project, path)
    loaded = load_project(path)
    assert [(c.id, c.start_ms, c.end_ms, c.text) for c in loaded.cues] == cue_before
    with pytest.raises(RecognitionResultMismatch, match="映射已改变|已有人工修订"):
        verify_result_reference(result["result_ref_json"], project=loaded, project_path=path)
    assert load_project(path).project_id == project.project_id


def test_runtime_metadata_refresh_does_not_change_pinned_input_graph(tmp_path, owned_library):
    result = create(media(tmp_path), "graph-runtime-job")
    project = load_project(result["project"])
    project.generation_metadata["preview_status"] = {"time": 999, "ready": True}
    project.studio_state["preview_playhead_ms"] = 333
    assert verify_result_reference(result["result_ref_json"], project=project).project_id == project.project_id


@pytest.mark.parametrize("decoded,video_end,expected", [(67.6533125, 67576.75, 67653), (60.0, 72000.0, 72000), (67.6533125, 0.0, 70187)])
def test_home_initial_graph_uses_decoded_duration_but_preserves_real_video_tail(tmp_path, owned_library, monkeypatch, decoded, video_end, expected):
    from twobyteasr.media_service import GLOBAL_MEDIA_SERVICE, MediaMetadataSnapshot
    source = media(tmp_path)
    stat = source.stat()
    snapshot = MediaMetadataSnapshot(source_path=str(source), source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns, duration_ms=70187, has_video=True, has_audio=True,
        video_stream_end_ms=video_end, width=1920, height=1080, fps=60.0, fingerprint="metadata-only")
    probes = []
    def probe(path, *, refresh=False):
        probes.append(refresh)
        return snapshot
    monkeypatch.setattr(GLOBAL_MEDIA_SERVICE, "metadata", probe)
    identity = media_identity_for_task(source, RuntimeContext())
    result = create_studio_outputs(source, cues(), txt_path="", decoded_audio_seconds=decoded,
        generation_metadata={"job_id":"valid-duration-job", "media_identity":identity})
    project = verify_result_reference(result["result_ref_json"])
    assert probes == [True]
    assert project.media.duration_ms == expected
    assert project.edit_sequence["source_duration_ms"] == expected
    for track in (*project.video_tracks, *project.audio_tracks):
        for clip in track.clips:
            assert clip.source_in_ms == clip.timeline_in_ms == 0
            assert clip.source_out_ms == clip.timeline_out_ms == expected
    assert project.generation_metadata["input_duration_evidence"]["decoded_audio_ms"] == round(decoded*1000)


@pytest.mark.parametrize("change", ["path", "project_id", "job_id", "revision", "media", "text", "time", "count"])
def test_reference_rejects_wrong_loaded_result(tmp_path, owned_library, change):
    result = create(media(tmp_path), "ref-job")
    ref = json.loads(result["result_ref_json"])
    project = load_project(result["project"])
    requested = result["project"]
    if change == "path": requested = str(tmp_path / "other.2byteproj")
    elif change == "project_id": project.project_id = "wrong-id"
    elif change == "job_id": project.generation_metadata["recognition_result"]["job_id"] = "wrong-job"
    elif change == "revision": project.generation_metadata["recognition_result"]["result_revision"] = "wrong-revision"
    elif change == "media": project.generation_metadata["media_identity"]["fingerprint"] = "wrong-input"
    elif change == "text": project.cues[0].text = "过期内容"
    elif change == "time": project.cues[0].end_ms += 10
    else: project.cues = []
    with pytest.raises(RecognitionResultMismatch):
        verify_result_reference(ref, project=project, project_path=requested)


def test_same_path_same_stat_changed_bytes_have_distinct_cache_identity_once_per_job(tmp_path, monkeypatch):
    path = media(tmp_path)
    stat = path.stat()
    opened = []
    original = Path.open
    def observe(self, mode="r", *a, **k):
        if self == path and mode == "rb": opened.append(str(self))
        return original(self, mode, *a, **k)
    monkeypatch.setattr(Path, "open", observe)
    first_context = RuntimeContext()
    first = media_identity_for_task(path, first_context)
    media_identity_for_task(path, first_context)
    different_selection = media_identity_for_task(path, first_context, selection={"audio_stream": 1, "range_ms": [10, 100]})
    assert len(opened) == 1
    assert different_selection["fingerprint"] != first["fingerprint"]
    with original(path, "rb") as stream:
        data = stream.read()
    path.write_bytes(data[:-2] + b"\x01\x00")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = media_identity_for_task(path, RuntimeContext())
    assert second["size"] == first["size"] and second["mtime_ns"] == first["mtime_ns"]
    assert second["sha256"] != first["sha256"] and second["fingerprint"] != first["fingerprint"]
    assert len(opened) == 2


class CommitPipeline(FakePipeline):
    def process_media(self, media_path, file_index, file_total, legacy, runtime_context=None):
        result = create_studio_outputs(media_path, cues(Path(media_path).parent.name), txt_path="",
            target_project_path=runtime_context.studio_project_path,
            generation_metadata={"job_id": runtime_context.job_id, "media_identity": runtime_context.media_identity})
        runtime_context.committed_result_ref = json.loads(result["result_ref_json"])
        return "", "", .01


def test_queue_publishes_only_current_committed_references_for_same_basename(tmp_path, owned_library):
    paths = [media(tmp_path, "A/same.wav"), media(tmp_path, "B/same.wav", 1)]
    events = []
    result = run_media_queue(paths, RunOptions(job_id="queue-id"), events.append,
        _legacy=FakeLegacy(tmp_path), _pipeline=CommitPipeline(), _skip_environment_preflight=True)
    assert result.job_id == "queue-id"
    assert len(result.successes) == 2
    assert len({r.project_path for r in result.results}) == 2
    assert len({r.project_id for r in result.results}) == 2
    for item in result.results:
        assert item.job_id == "queue-id"
        assert verify_result_reference(item.result_ref_json).project_id == item.project_id
    assert all(event.job_id == "queue-id" for event in events)


def test_report_and_existing_canonical_path_are_not_completion_fallback(tmp_path, owned_library):
    path = media(tmp_path)
    old = create(path, "old-job")
    report_path = tmp_path / "same.json"
    report_path.write_text(json.dumps({"status": "success", "result": {"outputs": {"project": old["project"]}}}), encoding="utf-8")
    result = run_media_queue([path], RunOptions(job_id="new-job"),
        _legacy=FakeLegacy(tmp_path), _pipeline=FakePipeline(), _skip_environment_preflight=True)
    assert result.results[0].project_path == ""
    assert result.results[0].result_ref_json == ""
    assert len(list(owned_library.glob("*/*.2byteproj"))) == 1


def test_cancel_after_commit_does_not_publish_success_or_reference(tmp_path, owned_library):
    class LateCommit(CommitPipeline):
        def process_media(self, media_path, file_index, file_total, legacy, runtime_context=None):
            value = super().process_media(media_path, file_index, file_total, legacy, runtime_context=runtime_context)
            self.token.cancel()
            return value
    result = run_media_queue([media(tmp_path)], RunOptions(job_id="cancelled"),
        _legacy=FakeLegacy(tmp_path), _pipeline=LateCommit(), _skip_environment_preflight=True)
    assert result.results[0].status == "cancelled"
    assert result.results[0].project_path == result.results[0].result_ref_json == ""
    assert not result.successes


def test_same_second_job_reports_have_distinct_paths(tmp_path, monkeypatch):
    from twobyteasr import reporting
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path / "reports")
    path = media(tmp_path)
    for job,index in (("first",1), ("first",2), ("second",1)):
        context = RuntimeContext(job_id=job, media_path=str(path),media_index=index, identity_task_active=True)
        with activate_runtime_context(context):
            reporting.begin_media_report(path, {"identity": media_identity_for_task(path, context)}, {"models": {
                "qwen_asr_model": "not-run", "polish_model": "not-run", "group_model": "not-run"}})
            reporting.finish_media_report("success", cue_count=1)
    paths = list((tmp_path / "reports").glob("*_字幕任务报告.json"))
    assert len(paths) == 3
    assert {json.loads(p.read_text(encoding="utf-8"))["job_id"] for p in paths} == {"first", "second"}
    assert {(json.loads(p.read_text('utf8'))['job_id'], json.loads(p.read_text('utf8'))['media_index']) for p in paths} == {('first',1),('first',2),('second',1)}


def test_reopening_a_delivered_result_accepts_the_users_edits(tmp_path, owned_library):
    """2026-10-10 (user): after proofreading on the result page, 打开字幕工作台
    said 工程字幕数量或文本时间摘要与已保存结果不一致. Delivery stays exact; a
    reopen of the same job's project checks its identity, not its content."""
    from twobyteasr.recognition_result import working_reference
    from twobyteasr.studio_commands import BatchReplaceTextCommand
    from twobyteasr.studio_edit_sequence import sequence_of
    result = create(media(tmp_path), "reopen-job", "原来的字幕")
    path = Path(result["project"])
    project = load_project(path)
    cue_id = project.cues[0].id
    BatchReplaceTextCommand(project, {cue_id: "校对后的字幕"}, needle="校对").redo()
    save_project(project, path)
    edited = load_project(path)
    # Only the caption text changed; the recognition stamp is intact.
    assert edited.generation_metadata["recognition_result"] == json.loads(result["result_ref_json"])
    with pytest.raises(RecognitionResultMismatch, match="文本时间摘要"):
        verify_result_reference(result["result_ref_json"], project=edited, project_path=path)
    reopened = working_reference(result["result_ref_json"])
    assert verify_result_reference(reopened, project=edited, project_path=path).cues[0].text == "校对后的字幕"
    assert verify_result_reference(reopened).cues[0].text == "校对后的字幕"  # read from its own path
    # Studio edits after delivery (timing, cuts, manual revisions) are the user's too.
    edited.cues[0].end_ms += 40
    sequence_of(edited).segments[0].timeline_out_ms -= 10
    edited.edit_history.append({"command": "manual-adjustment", "revision": 1})
    save_project(edited, path)
    assert verify_result_reference(reopened, project=load_project(path), project_path=path)
    assert working_reference("") == ""


@pytest.mark.parametrize("change", ["path", "project_id", "job_id", "revision", "stamp_digest", "media",
                                    "media_file", "corrupt", "other_job"])
def test_reopening_still_rejects_another_project_job_or_media(tmp_path, owned_library, change):
    from twobyteasr.recognition_result import working_reference
    source = media(tmp_path)
    result = create(source, "identity-job")
    ref = json.loads(result["result_ref_json"])
    requested = result["project"]
    project = load_project(requested)
    project.cues[0].text = "用户改过的字幕"  # allowed by itself
    if change == "path": requested = str(tmp_path / "other.2byteproj")
    elif change == "project_id": project.project_id = "wrong-id"
    elif change == "job_id": project.generation_metadata["recognition_result"]["job_id"] = "wrong-job"
    elif change == "revision": project.generation_metadata["recognition_result"]["result_revision"] = "wrong-revision"
    elif change == "stamp_digest": project.generation_metadata["recognition_result"]["cue_digest"] = "another-result"
    elif change == "media": project.generation_metadata["media_identity"]["fingerprint"] = "wrong-input"
    elif change == "media_file": source.write_bytes(source.read_bytes() + b"replacement")
    elif change == "corrupt": ref["job_id"] = "forged-job"  # the reference no longer hashes to its revision
    else:
        # Another job's project at a different path, presented under this reference.
        other = create(media(tmp_path, "other/same.wav", 9), "other-job")
        project, requested = load_project(other["project"]), other["project"]
    with pytest.raises(RecognitionResultMismatch):
        verify_result_reference(working_reference(json.dumps(ref)), project=project, project_path=requested)


def test_pending_studio_reload_retry_accepts_later_proofreading(tmp_path, owned_library):
    """A Studio-run recognition whose in-app reload failed is retried on the
    next Studio entry. By then the result page may have proofread the project;
    the retry must check identity like any reopen, not the delivered digest."""
    from twobyteasr.recognition_result import WORKING_SCOPE
    from twobyteasr.studio_commands import BatchReplaceTextCommand
    from twobyteasr.ui import MainWindow
    result = create(media(tmp_path), "pending-job", "原来的字幕")
    path = Path(result["project"])
    project = load_project(path)
    BatchReplaceTextCommand(project, {project.cues[0].id: "校对后的字幕"}, needle="校对").redo()
    save_project(project, path)
    calls = []
    studio = SimpleNamespace(_pending_recognition_reload=str(path),
                             _pending_recognition_result_ref=result["result_ref_json"],
                             _studio_trace=lambda *a, **k: None)
    window = SimpleNamespace(built_page=lambda name: studio,
                             open_studio_project=lambda *a, **k: calls.append((a, k)))
    MainWindow._retry_pending_recognition_reload(window)
    assert studio._pending_recognition_reload == ""
    (args, kwargs), = calls
    assert args == (str(path),) and kwargs["source"] == "studio_recognition"
    retry_ref = kwargs["expected_result_ref"]
    assert json.loads(retry_ref)["scope"] == WORKING_SCOPE
    assert verify_result_reference(retry_ref, project_path=path).cues[0].text == "校对后的字幕"
    # Identity is still enforced: another project at that path is refused.
    other = load_project(path)
    other.project_id = "someone-else"
    save_project(other, path)
    with pytest.raises((RecognitionResultMismatch, ValueError)):
        verify_result_reference(retry_ref, project_path=path)
