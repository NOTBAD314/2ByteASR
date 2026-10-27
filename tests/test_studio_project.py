import json
import os
from pathlib import Path

import pytest

from twobyteasr.rendering.ass_compiler import compile_ass, compile_txt
from twobyteasr.recognition.transcript_data import SubtitleCue
from twobyteasr.projects.studio_project import (
    PROJECT_SCHEMA_VERSION,
    ProjectValidationError,
    StudioCue,
    StudioMedia,
    SubtitleProject,
    autosave_path,
    load_project,
    project_archive_path,
    project_backup_path,
    project_from_runtime_cues,
    project_library_root,
    recoverable_autosave,
    save_autosave,
    save_project,
    studio_data_root,
    waveform_cache_root,
    create_studio_outputs,
)


def _project() -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(path="D:/video/game.mp4", duration_ms=12_000),
        cues=[
            StudioCue(
                id="cue-2",
                start_ms=2300,
                end_ms=4100,
                text="第二句",
                speaker_id="S02",
                original_text="第二句原稿",
                evidence_refs=["primary:2", "review:2"],
            ),
            StudioCue(
                id="cue-1",
                start_ms=100,
                end_ms=2200,
                text="第一句",
                speaker_id="S01",
                original_text="第一句原稿",
                evidence_refs=["primary:1"],
            ),
        ],
        asr_evidence={"primary:1": {"model": "moss", "text": "第一句原稿"}},
        glossary_ids=["game-main"],
        report_path="D:/video/game_字幕任务报告.json",
        original_outputs={"srt": "D:/video/game_剪映文稿.srt"},
    )


def test_project_round_trip_preserves_source_of_truth_fields(tmp_path):
    project = _project()
    project.media.width = 1920
    project.media.height = 800
    path = save_project(project, tmp_path / "game")

    assert path.suffix == ".2byteproj"
    loaded = load_project(path)
    assert loaded.schema_version == PROJECT_SCHEMA_VERSION
    assert loaded.cues[0].original_text == "第二句原稿"
    assert loaded.cues[0].evidence_refs == ["primary:2", "review:2"]
    assert loaded.original_outputs["srt"].endswith("_剪映文稿.srt")
    assert loaded.report_path.endswith("_字幕任务报告.json")
    assert (loaded.media.width, loaded.media.height) == (1920, 800)


def test_transient_qc_cache_is_not_serialized_but_old_state_stays_loadable(tmp_path):
    project = _project()
    project.studio_state["review_risks"] = {"cue-1": {"score": 99}}
    project.studio_state["review_confirmations"] = {"cue-1": "2026-08-19T00:00:00+00:00"}
    path = save_project(project, tmp_path / "qc-cache.2byteproj")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "review_risks" not in payload["studio_state"]
    assert payload["studio_state"]["review_confirmations"]["cue-1"]


def test_save_keeps_previous_valid_project_as_backup(tmp_path):
    project = _project()
    path = save_project(project, tmp_path / "game.2byteproj")
    first_payload = json.loads(path.read_text(encoding="utf-8"))
    project.cues[0].text = "人工修改"

    save_project(project, path)

    backup_payload = json.loads(project_backup_path(path).read_text(encoding="utf-8"))
    assert backup_payload == first_payload
    assert load_project(path).cues[0].text == "人工修改"


def test_autosave_and_waveform_paths_are_isolated_from_stable_settings(tmp_path):
    project = _project()
    project_path = save_project(project, tmp_path / "project" / "game.2byteproj")
    autosaved = save_autosave(project, project_path, base=tmp_path / "local")

    expected_root = tmp_path / "local" / "2ByteASR" / "SubtitleStudioPreview"
    assert studio_data_root(tmp_path / "local") == expected_root
    assert autosaved == autosave_path(project, project_path, base=tmp_path / "local")
    assert waveform_cache_root(tmp_path / "local") == expected_root / "waveform-cache"
    assert "2byteasr_settings.json" not in str(autosaved)


def test_newer_autosave_is_reported_for_crash_recovery(tmp_path):
    project = _project()
    project_path = save_project(project, tmp_path / "game.2byteproj")
    autosaved = save_autosave(project, project_path, base=tmp_path / "local")
    newer = project_path.stat().st_mtime_ns + 2_000_000_000
    os.utime(autosaved, ns=(newer, newer))

    assert recoverable_autosave(project_path, base=tmp_path / "local") == autosaved


def test_invalid_cue_timing_and_unknown_schema_fail_closed():
    project = _project()
    project.cues[0].end_ms = project.cues[0].start_ms
    with pytest.raises(ProjectValidationError, match="invalid timing"):
        project.to_dict()

    payload = _project().to_dict()
    payload["schema_version"] = 999
    with pytest.raises(ProjectValidationError, match="unsupported"):
        SubtitleProject.from_dict(payload)


def test_runtime_conversion_preserves_original_asr_text_and_output_paths(tmp_path):
    media = tmp_path / "input.mp4"
    project = project_from_runtime_cues(
        media,
        [SubtitleCue(7, 1.25, 2.75, "原始识别", speaker="S03")],
        original_outputs={"srt": str(tmp_path / "input.srt")},
    )

    assert project.cues[0].id == "7"
    assert (project.cues[0].start_ms, project.cues[0].end_ms) == (1250, 2750)
    assert project.cues[0].original_text == "原始识别"
    assert project.speakers[0].id == "S03"


def test_ass_compiler_is_deterministic_sorted_and_escapes_override_injection():
    project = _project()
    project.cues[0].text = "文本{\\pos(1,1)}\n下一行"

    first = compile_ass(project)
    second = compile_ass(project)

    assert first == second
    assert first.index("第一句") < first.index("文本")
    assert "｛\\\\pos(1,1)｝\\N下一行" in first
    assert "PlayResX: 1920" in first
    style = project.styles[0]
    assert f"Style: Default,{style.font_family},{style.font_size:g}" in first
    assert style.primary_color == "#FFFFFF"
    assert style.outline_color == "#000000"
    assert style.outline_width == 4.0
    assert style.shadow == 2.0
    assert style.bold
    declared={line.split(",",1)[0].removeprefix("Style: ") for line in first.splitlines() if line.startswith("Style: ")}
    assert all(line.split(",",4)[3] in declared for line in first.splitlines() if line.startswith("Dialogue: "))
    assert compile_txt(project) == "第一句\n文本{\\pos(1,1)} 下一行\n"


def test_ass_compiler_emits_real_style_inspector_fields():
    project = _project()
    style = project.styles[0]
    style.font_family = "Arial"
    style.font_size = 64
    style.primary_color = "#80F0E0D0"
    style.outline_color = "#102030"
    style.back_color = "#60403020"
    style.outline_width = 4.5
    style.shadow = 2.5
    style.bold = True
    style.italic = True
    style.underline = True
    style.spacing = 1.5
    style.border_style = 3
    style.alignment = 8
    style.margin_l = 24
    style.margin_r = 26
    style.margin_v = 38

    ass = compile_ass(project)

    assert (
            "Style: Default,Arial,64,&H7FD0E0F0,&H7FD0E0F0,&H00302010,"
            "&H9F203040,-1,-1,-1,0,100,100,1.5,0,3,4.5,2.5,8,24,26,38,1"
    ) in ass


def test_style_position_round_trip_emits_ass_override(tmp_path):
    project = _project()
    project.styles[0].position_x = 731
    project.styles[0].position_y = 882

    loaded = load_project(save_project(project, tmp_path / "positioned.2byteproj"))
    assert (loaded.styles[0].position_x, loaded.styles[0].position_y) == (731, 882)
    from twobyteasr.rendering.ass_font_units import ass_font_style
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    caption=resolve_caption_style(loaded.styles,loaded.speakers,loaded.cues[0],loaded.style_recipes,1920,1080)
    native=ass_font_style(caption.style,1920,1080,layout=caption.layout)
    assert f"\\pos({round(native.position_x,2):g},{round(native.position_y,2):g})" in compile_ass(loaded)


def test_live_preview_payload_contains_editable_style_values():
    project = _project()
    project.cues[0].text = "测试字幕"
    style = project.styles[0]
    style.font_size = 130
    style.primary_color = "#FF0000"
    style.outline_color = "#000000"
    style.outline_width = 3
    style.position_x = 960
    style.position_y = 900
    ass = compile_ass(project)
    assert "Format: Name, Fontname, Fontsize, PrimaryColour" in ass
    assert (
        f"Default,{style.font_family},130,&H000000FF,&H000000FF,&H00000000"
        in ass
    )
    from twobyteasr.rendering.ass_font_units import ass_font_style
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    caption=resolve_caption_style(project.styles,project.speakers,project.cues[0],project.style_recipes,1920,1080)
    native=ass_font_style(caption.style,1920,1080,layout=caption.layout)
    assert f"\\pos({round(native.position_x,2):g},{round(native.position_y,2):g})" in ass
    assert "Dialogue: 0,0:00:00.10" in ass


def test_create_studio_outputs_keeps_original_asr_files_and_links_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"media")
    txt = tmp_path / "game_剪映文稿.txt"
    srt = tmp_path / "game_剪映文稿.srt"
    txt.write_text("original txt", encoding="utf-8")
    srt.write_text("original srt", encoding="utf-8")

    class Segment:
        segment_id = 9
        start = 0.0
        end = 2.0
        text = "primary"
        speaker = "S01"
        primary_source = "moss"
        moss_text = "primary"
        firered_text = "review"
        firered_llm_text = ""
        qwen_asr_text = "qwen"
        alternate_text = ""

    outputs = create_studio_outputs(
        media,
        [SubtitleCue(1, 0.2, 1.8, "成片字幕", speaker="S01")],
        txt_path=str(txt),
        srt_path=str(srt),
        report_path=str(tmp_path / "report.json"),
        segments=[Segment()],
    )

    project = load_project(outputs["project"])
    assert txt.read_text(encoding="utf-8") == "original txt"
    assert srt.read_text(encoding="utf-8") == "original srt"
    project_path = Path(outputs["project"])
    assert project_path.parent.name.startswith("game__")
    assert project_path.parent.parent == project_library_root()
    assert all(
        (project_path.parent / name).is_dir()
        for name in ("subtitles", "reports", "source", "autosave", "cache", "preview", "backup", "renders", "exports")
    )
    assert (project_path.parent / "subtitles" / "transcript.txt").read_text(encoding="utf-8") == "original txt"
    assert (project_path.parent / "subtitles" / "master.srt").read_text(encoding="utf-8") == "original srt"
    assert "ass" not in outputs
    assert not srt.with_suffix(".ass").exists()
    assert project.cues[0].evidence_refs == ["segment:9"]
    assert project.asr_evidence["segment:9"]["qwen_asr_text"] == "qwen"


def test_recognition_projects_from_different_media_drives_share_canonical_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    first_txt = tmp_path / "a.txt"
    second_txt = tmp_path / "b.txt"
    first_txt.write_text("a", encoding="utf-8")
    second_txt.write_text("b", encoding="utf-8")
    first = create_studio_outputs(r"C:\footage\A.mp4", [], txt_path=str(first_txt))
    second = create_studio_outputs(r"H:\footage\B.mp4", [], txt_path=str(second_txt))
    root = project_library_root()
    assert Path(first["project"]).parent.parent == root
    assert Path(second["project"]).parent.parent == root
    assert Path(first["project"]).is_file()
    assert Path(second["project"]).is_file()


def test_archive_project_backup_stays_inside_backup_directory(tmp_path):
    project = _project()
    project_path = project_archive_path(tmp_path / "game.srt", tmp_path / "game.mp4")
    save_project(project, project_path)
    project.cues[0].text = "第二版"
    save_project(project, project_path)

    assert project_backup_path(project_path).parent == project_path.parent / "backup"
    assert load_project(project_backup_path(project_path)).cues[0].text == "第二句"


def _real_media_identity(path: str, duration_ms: int = 175_617) -> dict:
    return {
        "path": path,
        "duration_ms": duration_ms,
        "fingerprint": "fp-real-media",
        "has_video": True,
        "video_codec": "h264",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "video_timebase": "1/15360",
        "rotation": 0,
        "has_audio": True,
        "audio_codec": "aac",
        "sample_rate": 48000,
        "channels": 2,
        "audio_timebase": "1/48000",
        "audio_stream_index": 1,
    }


def test_p74c_recognition_creation_probes_real_media_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    cue = type("Cue", (), {"start": 0.5, "end": 4.0, "text": "你好", "speaker": "S01", "cue_id": 1})()
    project = project_from_runtime_cues(
        str(media), [cue], media_identity=_real_media_identity(str(media))
    )

    asset = project.media_pool[0]
    assert asset.duration_ms == 175_617
    assert asset.fingerprint == "fp-real-media"
    assert asset.video_metadata["width"] == 1920
    assert asset.audio_metadata["has_audio"] is True
    clip = project.video_tracks[0].clips[0]
    assert clip.source_in_ms == 0
    assert clip.source_out_ms == 175_617
    assert clip.timeline_in_ms == 0
    assert clip.timeline_out_ms == 175_617


def test_p74c_open_time_hydrate_repairs_zero_duration_recognition_project(tmp_path):
    """The shipped user project shape: correct legacy media, dead pool asset."""

    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    # Reproduce the pristine on-disk recognition project: media.duration_ms=0,
    # the pool asset migrated from that zero media, and a 0->0 V1 clip.
    project = SubtitleProject(media=StudioMedia(path=str(media)))
    project.validate()
    asset = project.media_pool[0]
    assert asset.duration_ms == 0
    assert project.video_tracks[0].clips[0].timeline_out_ms == 0

    from twobyteasr.projects.studio_project import hydrate_media_contract

    hydrate_media_contract(
        project,
        _real_media_identity(str(media)),
        source_path=str(media),
        asset_id=asset.asset_id,
    )

    assert asset.duration_ms == 175_617
    assert asset.video_metadata["width"] == 1920
    assert project.media.duration_ms == 175_617
    clip = project.video_tracks[0].clips[0]
    assert clip.source_out_ms == 175_617
    assert clip.timeline_out_ms == 175_617
    # The linked A1 lane materializes in lockstep with the repaired V1 clip.
    assert project.audio_tracks and project.audio_tracks[0].id == "A1"
    audio_clip = project.audio_tracks[0].clips[0]
    assert audio_clip.linked_video_clip_id == clip.id
    assert audio_clip.timeline_out_ms == clip.timeline_out_ms
    assert project.av_track_groups[0].video_track_id == "V1"
    assert project.av_track_groups[0].audio_track_id == "A1"


def test_p74c_zero_duration_project_survives_probe_failure_without_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")

    def _fail(_path):
        raise RuntimeError("ffprobe unavailable")

    monkeypatch.setattr(
        "twobyteasr.studio.studio_helpers.probe_media_identity", _fail
    )
    project = project_from_runtime_cues(str(media), [])
    assert "media_contract_probe_error" in project.generation_metadata
    assert project.media_pool[0].duration_ms == 0
    # The project still opens; the Studio salvage layer keeps the preview up.
    project.validate()
    assert project.video_tracks[0].clips[0].timeline_out_ms == 0


def test_p74c_linked_av_edits_move_trim_and_remove_in_lockstep(tmp_path):
    from twobyteasr.projects.studio_project import hydrate_media_contract
    from twobyteasr.timeline.studio_media_pool import (
        add_media_asset,
        add_video_clip,
        create_video_track,
        move_video_clip,
        remove_video_clip,
        trim_video_clip,
    )

    primary = tmp_path / "one.mp4"
    primary.write_bytes(b"a")
    second = tmp_path / "two.mp4"
    second.write_bytes(b"b")
    audio_meta = {"has_audio": True, "codec": "aac", "channels": 2}
    project = SubtitleProject(media=StudioMedia(path=str(primary)))
    project.validate()
    hydrate_media_contract(
        project,
        _real_media_identity(str(primary), 60_000),
        source_path=str(primary),
        asset_id=project.media_pool[0].asset_id,
    )
    v2_asset = add_media_asset(
        project,
        second,
        fingerprint="fp2",
        duration_ms=30_000,
        video_metadata={"has_video": True, "width": 1280, "height": 720},
        audio_metadata=audio_meta,
    )
    create_video_track(project, "V2")
    v2_clip = add_video_clip(project, "V2", v2_asset.asset_id, timeline_in_ms=5_000)

    groups = {group.video_track_id: group for group in project.av_track_groups}
    assert set(groups) == {"V1", "V2"}
    assert groups["V1"].audio_track_id == "A1"
    assert groups["V2"].audio_track_id == "A2"
    a2 = next(track for track in project.audio_tracks if track.id == "A2")
    linked = {clip.linked_video_clip_id: clip for clip in a2.clips}
    assert linked[v2_clip.id].timeline_in_ms == 5_000
    assert linked[v2_clip.id].timeline_out_ms == 35_000

    # Linked move: dragging V2 moves A2 with it.
    move_video_clip(project, "V2", v2_clip.id, 9_000)
    linked = {clip.linked_video_clip_id: clip for clip in a2.clips}
    assert v2_clip.timeline_in_ms == 9_000
    assert linked[v2_clip.id].timeline_in_ms == 9_000
    assert linked[v2_clip.id].timeline_out_ms == 39_000

    # Linked trim: source range edits mirror into the audio lane.
    trim_video_clip(project, "V2", v2_clip.id, source_in_ms=1_000, source_out_ms=10_000)
    linked = {clip.linked_video_clip_id: clip for clip in a2.clips}
    assert linked[v2_clip.id].source_in_ms == 1_000
    assert linked[v2_clip.id].source_out_ms == 10_000
    assert linked[v2_clip.id].timeline_out_ms == v2_clip.timeline_out_ms

    # Removing the video clip drops its linked audio clip, never the whole A2.
    remove_video_clip(project, "V2", v2_clip.id)
    from twobyteasr.projects.studio_project import sync_linked_av_contract

    sync_linked_av_contract(project)
    assert a2.clips == []
    assert any(track.id == "A2" for track in project.audio_tracks)


def test_p74c_pure_audio_asset_gets_standalone_lane_without_fake_video(tmp_path):
    from twobyteasr.timeline.studio_media_pool import add_media_asset
    from twobyteasr.projects.studio_project import sync_linked_av_contract

    primary = tmp_path / "one.mp4"
    primary.write_bytes(b"a")
    audio_only = tmp_path / "voice.mp3"
    audio_only.write_bytes(b"m")
    project = SubtitleProject(media=StudioMedia(path=str(primary)))
    project.validate()
    asset = add_media_asset(
        project,
        audio_only,
        fingerprint="fp-audio",
        duration_ms=45_000,
        video_metadata={"has_video": False, "width": 0, "height": 0},
        audio_metadata={"has_audio": True, "codec": "mp3", "channels": 1},
    )
    sync_linked_av_contract(project)

    video_assets = {
        clip.asset_id for track in project.video_tracks for clip in track.clips
    }
    assert asset.asset_id not in video_assets
    standalone = [
        track for track in project.audio_tracks
        if track.id not in {
            group.audio_track_id for group in project.av_track_groups
        }
    ]
    assert len(standalone) == 1
    assert standalone[0].clips and standalone[0].clips[0].source_out_ms == 45_000
    # The standalone lane is not grouped with any video track.
    assert all(group.video_track_id != "" for group in project.av_track_groups)


def test_p74c_on_disk_recognition_split_brain_repairs_on_load(tmp_path):
    """The shipped user project: StudioMedia duration is real, pool/clip are 0."""

    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    payload = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project_id": "p74cdeadbeef",
        "created_at": "2026-08-26T00:00:00+00:00",
        "updated_at": "2026-08-26T00:00:00+00:00",
        "media": {
            "path": str(media),
            "display_name": "game.mp4",
            "duration_ms": 175617,
            "width": 1920,
            "height": 1080,
            "fingerprint": "fp-legacy",
        },
        "media_pool": [
            {
                "asset_id": "asset-deadbeef01",
                "canonical_source": str(media),
                "display_name": "game.mp4",
                "fingerprint": "",
                "duration_ms": 0,
                "video_metadata": {"width": 0, "height": 0},
                "audio_metadata": {},
                "proxy_identity": "",
                "offline": False,
                "relink_state": "linked",
            }
        ],
        "video_tracks": [
            {
                "id": "V1",
                "name": "V1",
                "enabled": True,
                "muted": False,
                "locked": True,
                "z_index": 0,
                "kind": "video",
                "clips": [
                    {
                        "id": "clip-deadbeef01",
                        "asset_id": "asset-deadbeef01",
                        "source_in_ms": 0,
                        "source_out_ms": 0,
                        "timeline_in_ms": 0,
                        "timeline_out_ms": 0,
                        "enabled": True,
                        "audio_enabled": True,
                        "transform": {},
                    }
                ],
            }
        ],
        "audio_tracks": [],
        "av_track_groups": [],
        "cues": [
            {
                "id": "c1",
                "start_ms": 267,
                "end_ms": 1350,
                "text": "先抽卡",
                "speaker_id": "S01",
            }
        ],
        "speakers": [{"id": "S01", "name": "S01"}],
        "styles": [],
        "edit_sequence": {
            "version": 1,
            "source_path": str(media),
            "source_duration_ms": 175617,
            "empty_timeline": False,
            "in_point_ms": 0,
            "out_point_ms": 0,
            "selected_segment_id": "",
            "video_track_locked": True,
            "danmaku_path": "",
            "markers": [],
            "clip_candidates": [],
            "segments": [
                {
                    "id": "seg-1",
                    "source_path": str(media),
                    "source_in_ms": 0,
                    "source_out_ms": 175617,
                    "timeline_in_ms": 0,
                    "timeline_out_ms": 175617,
                }
            ],
        },
        "studio_state": {},
        "effects": {},
        "style_recipes": {},
        "generation_metadata": {"created_by": "2ByteASR recognition pipeline"},
        "asr_evidence": {},
        "glossary_ids": [],
        "edit_history": [],
        "render_settings": {},
        "report_path": "",
        "original_outputs": {},
    }
    path = tmp_path / "game.2byteproj"
    path.write_text(json.dumps(payload), encoding="utf-8")
    project = load_project(path)
    asset = project.media_pool[0]
    clip = project.video_tracks[0].clips[0]
    assert asset.duration_ms == 175617
    assert clip.source_out_ms == 175617
    assert clip.timeline_out_ms == 175617
    assert project.audio_tracks[0].id == "A1"
    assert project.audio_tracks[0].clips
    assert project.audio_tracks[0].clips[0].linked_video_clip_id == clip.id
    assert project.av_track_groups[0].video_track_id == "V1"
    assert project.av_track_groups[0].audio_track_id == "A1"


def test_p74c_create_studio_outputs_hydrates_without_constructed_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "game.mp4"
    media.write_bytes(b"mp4")
    txt = tmp_path / "game.txt"
    txt.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(
        "twobyteasr.studio.studio_helpers.probe_media_identity",
        lambda path: _real_media_identity(str(path)),
    )
    outputs = create_studio_outputs(
        str(media),
        [SubtitleCue(1, 0.2, 1.8, "成片字幕", speaker="S01")],
        txt_path=str(txt),
    )
    project = load_project(outputs["project"])
    asset = project.media_pool[0]
    assert asset.duration_ms == 175617
    assert asset.audio_metadata["has_audio"] is True
    clip = project.video_tracks[0].clips[0]
    assert clip.timeline_out_ms == 175617
    assert project.av_track_groups[0].audio_track_id == "A1"
