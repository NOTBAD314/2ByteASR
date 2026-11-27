"""Tests for the slim 3-switch Auto-Pipeline engine, real default adapters, and open-project auto-run."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.projects.auto_pipeline import (
    AutoPipelineConfig,
    default_glossary_matcher,
    default_style_applier,
    load_receipt,
    maybe_run_auto_pipeline,
    run_auto_pipeline,
    run_batch_auto_pipeline,
)
from twobyteasr.projects.series_store import CastMember, SeriesStore, VoiceprintObservation
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)


def _app():
    return QApplication.instance() or QApplication([])


def _vec(angle_deg: float, dim: int = 8) -> list[float]:
    rad = math.radians(angle_deg)
    v = [0.0] * dim
    v[0], v[1] = math.cos(rad), math.sin(rad)
    return v


def _make_project(name: str, texts: list[str]) -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(path=f"{name}.mp4", display_name=name, duration_ms=10_000),
        speakers=[
            StudioSpeaker(id="S00", name="S00", color="#999999"),
            StudioSpeaker(id="S01", name="S01", color="#888888"),
            StudioSpeaker(id="S02", name="老王", color="#555555"),
        ],
        cues=[
            StudioCue(
                id=f"c{i}",
                start_ms=i * 1000,
                end_ms=(i + 1) * 1000,
                speaker_id=("S00" if i % 2 == 0 else "S01"),
                text=t,
            )
            for i, t in enumerate(texts, 1)
        ],
    )


def test_auto_pipeline_config_three_switches_and_legacy_compat():
    # Legacy translation / export keys from older saved JSON are safely ignored
    cfg = AutoPipelineConfig.from_dict({
        "enabled": True,
        "run_glossary": True,
        "run_speakers": True,
        "run_style_preset": True,
        "run_translation": True,
        "auto_export_srt": True,
        "stop_for_review": True,
    })
    assert not hasattr(cfg, "run_translation")
    assert not hasattr(cfg, "auto_export_srt")
    assert cfg.plain_flow_preview() == "识别 → 套常用词库 → 套常用人名 → 套常用样式"

    cfg_partial = AutoPipelineConfig(enabled=True, run_glossary=True, run_speakers=False, run_style_preset=True)
    assert cfg_partial.plain_flow_preview() == "识别 → 套常用词库 → 套常用样式"

    cfg_none = AutoPipelineConfig(enabled=False, run_glossary=False, run_speakers=False, run_style_preset=False)
    assert cfg_none.plain_flow_preview() == "识别"


def test_auto_pipeline_runs_all_three_stages_safely_and_persists_receipt(tmp_path: Path):
    store = SeriesStore(tmp_path / "series")
    series = store.create(
        "韩V新星切片",
        glossary_ids=["valorant", "kvtuber"],
        cast=[
            CastMember(cast_id="cast_k", name="小K", color="#4f8557"),
            CastMember(cast_id="cast_7", name="阿七", color="#e0809f"),
        ],
        visual={"subtitle_style_preset": "game"},
    )
    store.enroll_voiceprint(series.id, "cast_k", VoiceprintObservation("S00", _vec(0), _vec(1), _vec(-1), seconds=10.0), episode_id="ep1")
    store.enroll_voiceprint(series.id, "cast_7", VoiceprintObservation("S01", _vec(90), _vec(89), _vec(91), seconds=10.0), episode_id="ep1")
    for ep in ("ep1", "ep2", "ep3"):
        store.record_rule_outcome(series.id, "alias:元神->原神", "元神 → 原神", episode_id=ep, clean_adopted=True)
    store.set_rule_graduated(series.id, "alias:元神->原神", True)
    store.record_rule_outcome(series.id, "alias:杰风->捷风", "杰风 → 捷风", episode_id="ep1", clean_adopted=True)
    series = store.get(series.id)

    cfg = AutoPipelineConfig(
        enabled=True,
        run_glossary=True,
        auto_apply_graduated=True,
        run_speakers=True,
        run_style_preset=True,
    )
    proj = _make_project("韩V新星_EP05", ["今天玩元神还是杰风", "元神启动啦", "杰风起大招"])
    mid_7 = [0.0, 0.55, math.sqrt(1.0 - 0.55 * 0.55), 0.0, 0.0, 0.0, 0.0, 0.0]

    receipt = run_auto_pipeline(
        proj,
        series,
        config=cfg,
        store=store,
        glossary_matcher=lambda _p, _gids: {"proposals": 2},
        voiceprint_observations=[
            VoiceprintObservation("S00", _vec(2), _vec(1), _vec(3), seconds=9.0),
            VoiceprintObservation("S01", mid_7, mid_7, mid_7, seconds=8.0),
        ],
    )

    assert [s.stage for s in receipt.stages] == ["glossary", "speakers", "style"]
    # Graduated alias auto-applied, ungraduated alias untouched!
    assert proj.cues[0].text == "今天玩原神还是杰风"
    assert proj.cues[1].text == "原神启动啦"
    assert proj.cues[2].text == "杰风起大招"
    # Bound glossaries synced to project
    assert "valorant" in proj.glossary_ids and "kvtuber" in proj.glossary_ids
    # Voiceprint automatic matched S00 -> 小K; S01 stayed anonymous for human confirmation; 老王 untouched!
    assert proj.speakers[0].name == "小K" and proj.speakers[0].color == "#4f8557"
    assert proj.speakers[1].name == "S01"
    assert proj.speakers[2].name == "老王"
    # Real default style applier applied builtin 'game' preset!
    assert proj.cues[0].appearance_override.get("original", {}).get("preset_id") == "game"
    assert resolve_cue_visual(proj, proj.cues[0]).style.font_size == 54.0
    assert proj.studio_state["pipeline_visual_applied"]["subtitle_style_preset"] == "game"

    # Additive receipt persists inside studio_state (schema_version 1 untouched)
    assert proj.schema_version == 1
    restored = load_receipt(proj)
    assert restored is not None
    assert restored.remaining_review_count == 3  # 2 glossary proposals + 1 speaker review
    for banned in ("沉淀", "质心", "双半段自洽", "置信区", "信任分级", "生成器"):
        assert banned not in restored.one_line_summary()


def test_default_style_applier_uses_real_presets_and_preserves_manual_cues(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path))
    pstore = StylePresetStore()
    custom = SubtitleStyle(
        id="user-coral",
        name="珊瑚重点",
        font_size=62.0,
        primary_color="#FF7F6B",
        outline_width=5.0,
        bold=True,
    )
    pstore.upsert(custom)

    proj = _make_project("style_test", ["第一句默认", "第二句默认", "第三句手改"])
    # Mark c3 as manually customized
    proj.cues[2].appearance_override = {"primary_color": "#00FFCC", "font_size": 70.0}

    res = default_style_applier(proj, {"subtitle_style_preset": "user-coral"})
    assert res["found"] is True
    assert res["applied"] == 2
    assert res["skipped_manual"] == 1
    assert res["preset_id"] == "user-coral"

    # Untouched cues received the preset
    assert proj.cues[0].appearance_override.get("original", {}).get("preset_id") == "user-coral"
    assert proj.cues[1].appearance_override.get("original", {}).get("preset_id") == "user-coral"
    assert resolve_cue_visual(proj, proj.cues[0]).style.primary_color.upper() == "#FF7F6B"
    assert resolve_cue_visual(proj, proj.cues[0]).style.font_size == 62.0

    # Manually styled cue MUST remain untouched
    assert proj.cues[2].appearance_override.get("primary_color") == "#00FFCC"
    assert proj.cues[2].appearance_override.get("font_size") == 70.0
    assert "preset_id" not in proj.cues[2].appearance_override.get("original", {})

    # Missing preset degrades safely
    missing = default_style_applier(proj, {"subtitle_style_preset": "nonexistent-preset-id"})
    assert missing["found"] is False and missing["applied"] == 0


def test_default_glossary_matcher_counts_local_snapshot_hits_without_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path))
    learned_path = tmp_path / "2ByteASR" / "learned_game_terms.json"
    learned_path.parent.mkdir(parents=True, exist_ok=True)
    learned_path.write_text(
        json.dumps({
            "schema_version": 2,
            "games": {
                "val_local": {
                    "game": "瓦罗兰特",
                    "revision": "1",
                    "mappings": [
                        {
                            "from": "杰风",
                            "to": "捷风",
                            "category": "角色",
                            "origin": "手动",
                            "provenance": "user_confirmed",
                            "confirmed": True,
                        },
                        {
                            "from": "欧闷",
                            "to": "欧门",
                            "category": "角色",
                            "origin": "手动",
                            "provenance": "user_confirmed",
                            "confirmed": True,
                        },
                    ],
                }
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    proj = _make_project("glossary_test", ["杰风起大招了", "欧闷封烟了", "这句没问题"])
    res = default_glossary_matcher(proj, ["val_local"])
    assert res["proposals"] == 2
    assert res["matched_cues"] == 2
    assert "val_local" in res["libraries"]
    # Purely local precheck: never mutates ungraduated cue text directly
    assert proj.cues[0].text == "杰风起大招了"
    assert proj.cues[1].text == "欧闷封烟了"


def test_maybe_run_auto_pipeline_idempotent_and_respects_enabled_flag(tmp_path: Path):
    store = SeriesStore(tmp_path / "series")
    series = store.create(
        "双排系列",
        cast=[CastMember(cast_id="c1", name="主播A", color="#4f8557")],
        visual={"subtitle_style_preset": "game"},
        pipeline={"enabled": False, "run_glossary": True, "run_speakers": True, "run_style_preset": True},
    )
    proj = _make_project("ep01", ["测试句子"])
    proj.studio_state["series_binding"] = {"series_id": series.id, "series_name": series.name}

    # Disabled pipeline -> does nothing
    assert maybe_run_auto_pipeline(proj, store=store, is_new_delivery=True) is None
    assert proj.speakers[1].name == "S01"

    # Enable pipeline -> runs once
    series.pipeline["enabled"] = True
    store.save(series)
    receipt = maybe_run_auto_pipeline(proj, store=store, is_new_delivery=True)
    assert receipt is not None
    assert proj.speakers[1].name == "主播A"
    assert proj.cues[0].appearance_override.get("original", {}).get("preset_id") == "game"

    # Re-running on same project MUST be a no-op (never overwrites subsequent user edits)
    proj.speakers[1].name = "手动改名"
    assert maybe_run_auto_pipeline(proj, store=store, is_new_delivery=True) is None
    assert proj.speakers[1].name == "手动改名"


def test_auto_pipeline_degrades_gracefully_and_supports_batch_cancel(tmp_path: Path):
    store = SeriesStore(tmp_path / "series")
    series = store.create(
        "双排切片",
        cast=[CastMember(cast_id="c1", name="主播A", color="#4f8557")],
        visual={"subtitle_style_preset": "game"},
    )
    cfg = AutoPipelineConfig(enabled=True, run_glossary=True, run_speakers=True, run_style_preset=True)
    projs = [_make_project(f"clip_{i}", ["测试一句"]) for i in range(1, 4)]

    def _broken_style(_p, _v):
        raise RuntimeError("样式损坏")

    done_count = []
    batch = run_batch_auto_pipeline(
        projs,
        series,
        config=cfg,
        store=store,
        glossary_matcher=lambda _p, _g: {"proposals": 1},
        style_applier=_broken_style,
        cancel_check=lambda: len(done_count) >= 2,
        on_project_done=lambda i, _t, _r: done_count.append(i),
    )
    assert batch.cancelled is True
    assert batch.total_videos == 2
    assert projs[0].speakers[1].name == "主播A"
    assert projs[1].speakers[1].name == "主播A"
    assert projs[2].speakers[1].name == "S01"
    assert "已取消" in batch.headline()


def test_studio_project_controller_auto_runs_pipeline_once_on_new_project_open(tmp_path: Path, monkeypatch):
    app = _app()
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    store = SeriesStore()
    series = store.create(
        "实况自动方案",
        glossary_ids=["val_auto"],
        cast=[CastMember(cast_id="c1", name="小K", color="#4f8557")],
        visual={"subtitle_style_preset": "game"},
        pipeline={"enabled": True, "run_glossary": True, "run_speakers": True, "run_style_preset": True},
    )
    store.set_last_selected(series.id)

    proj = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "missing.mp4"), display_name="新交付工程", duration_ms=4_000),
        speakers=[
            StudioSpeaker(id="S00", name="S00", color="#999999"),
            StudioSpeaker(id="S01", name="老王", color="#666666"),
        ],
        cues=[
            StudioCue("cue-1", 0, 1500, "第一句测试", speaker_id="S00"),
            StudioCue("cue-2", 1600, 3000, "第二句测试", speaker_id="S00"),
        ],
        studio_state={"series_binding": {"series_id": series.id, "series_name": series.name}},
    )
    path = save_project(proj, tmp_path / "auto_open.2byteproj")

    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_kw: None)
    try:
        page.open_project(path)
        app.processEvents()

        opened = page.project
        assert opened is not None
        receipt_first = load_receipt(opened)
        assert receipt_first is not None
        assert opened.speakers[0].name == "小K"
        assert opened.speakers[1].name == "老王"
        assert "val_auto" in opened.glossary_ids
        assert opened.cues[0].appearance_override.get("original", {}).get("preset_id") == "game"

        # Save with receipt & manual rename, then reopen -> must NOT re-run pipeline
        opened.speakers[0].name = "用户改名"
        page.save()
        app.processEvents()

        page.open_project(path, skip_dirty_guard=True)
        app.processEvents()
        reopened = page.project
        assert reopened is not None
        receipt_second = load_receipt(reopened)
        assert receipt_second is not None
        assert receipt_second.ran_at == receipt_first.ran_at
        assert reopened.speakers[0].name == "用户改名"
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()
