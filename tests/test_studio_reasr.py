import subprocess
from pathlib import Path

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_reasr import build_clip_command, clip_bounds, run_local_reasr


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


def _project(media):
    return SubtitleProject(
        media=StudioMedia(str(media), duration_ms=60_000),
        cues=[StudioCue("a", 10_000, 12_000, "当前", original_text="原始", evidence_refs=["e1"])],
        asr_evidence={"e1": {"text": "主结果"}},
        glossary_ids=["game-terms"],
    )


def test_clip_bounds_are_padded_and_capped_to_thirty_seconds(tmp_path):
    project = _project(tmp_path / "video.mp4")
    assert clip_bounds(project, "a") == (8800, 13200)
    assert clip_bounds(project, "a", padding_ms=0) == (10000, 12000)
    project.cues[0].start_ms = 1000
    project.cues[0].end_ms = 50_000
    start, end = clip_bounds(project, "a")
    assert end - start == 30_000


def test_batch_reasr_keeps_manual_text_and_limits_speaker_scope(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.studio.studio_reasr import LocalReASRResult
    from twobyteasr.studio.studio_reasr_batch import BatchReASREvent, receive, targets_for
    from twobyteasr.studio.studio_task_progress import SubtitleTask
    from twobyteasr.subtitle_rules.sentence_refine_ranges import input_version

    model = _project(tmp_path / "video.mp4")
    model.cues.extend([StudioCue("b", 12000, 13000, "已确认"),
                       StudioCue("c", 13000, 14000, "其他人", "other")])
    model.studio_state["review_confirmations"] = {"b": True}
    page = SimpleNamespace(project=model, selected_cue_id="a", timeline=SimpleNamespace(locked_speakers=set()),
                           _revision_store=StudioRevisionStore(model))
    assert [cue.id for cue in targets_for(page, speaker=True)] == ["a"]
    assert [cue.id for cue in targets_for(page, ["c", "a", "b", "c"])] == ["c", "a"]
    task = SubtitleTask("批量重新识别", ("a",))
    task.project = model
    task.results = {}
    task.mapping_revision = page._revision_store.render.mapping_revision
    task.input_versions = {"a": input_version([model.cues[0]], model)}
    page._subtitle_tasks = {task.task_id: task}
    found = LocalReASRResult("a", "当前", "主结果", "建议", (), "建议", "local")
    receive(page, BatchReASREvent(task.task_id, "a", found))
    assert task.rows["a"]["status"] == "suggestion"
    assert model.cues[0].text == "当前"


def test_clip_command_extracts_mono_16khz_pcm(tmp_path):
    command = build_clip_command(FFMPEG, tmp_path / "in.mp4", tmp_path / "out.wav", 1000, 2500)
    assert command[command.index("-ss") + 1] == "1.000"
    assert command[command.index("-t") + 1] == "1.500"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"


def test_local_reasr_uses_bounded_clip_and_returns_evidence(tmp_path, monkeypatch):
    media = tmp_path / "source.mp4"
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=size=64x64:rate=1", "-f", "lavfi", "-i", "sine=440:duration=2", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(media)],
        check=True,
    )
    project = _project(media)
    project.media.duration_ms = 2000
    project.cues[0].start_ms = 500
    project.cues[0].end_ms = 1500
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    def transcriber(path, regions, _audio, *, backend_override):
        assert Path(path).stat().st_size > 44
        assert regions == [{"start": 0.0, "end": 2.0}]
        assert backend_override == "whisper_turbo"
        return [{"text": "复核结果"}]

    result = run_local_reasr(
        project,
        "a",
        {"models": {"primary_asr_backend": "moss", "qwen_asr_backend": "whisper_turbo"}},
        FFMPEG,
        transcriber=transcriber,
    )
    assert result.primary_text == "主结果"
    assert result.review_text == "复核结果"
    assert result.recommendation == "复核结果"
    assert result.glossary_evidence == ("game-terms",)
    assert not list((tmp_path / "local").rglob("*.wav"))
