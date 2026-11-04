from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.providers.ai_providers import AntigravityCLIProvider
from twobyteasr.system.processes import canonical_subprocess_command
from twobyteasr.caption_design.studio_ai import request_style_design, style_recipe_for_prompt, visual_design_variants
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    library_project_snapshot,
    load_project,
    project_backup_path,
    repair_project_library_metadata,
    save_autosave,
    save_project,
)
from twobyteasr.studio.studio_ui import StylePropertyRow, SubtitleStudioPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_windows_batch_commands_use_explicit_hidden_shell_contract():
    command = canonical_subprocess_command(
        [r"C:\renderer\node_modules\.bin\remotion.cmd", "still", "src/index.ts"],
        environ={"COMSPEC": r"C:\Windows\System32\cmd.exe"},
    )
    if os.name == "nt":
        assert command[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
        assert str(command[4]).endswith("remotion.cmd")
    else:
        assert str(command[0]).endswith("remotion.cmd")


def test_cli_status_cache_skips_repeated_version_and_models(monkeypatch):
    AntigravityCLIProvider._status_cache.clear()
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        # 现行契约：--version 探测、--models 列表、以及须回 2ByteASR_OK 的
        # installed-print 就绪探针（P9A Antigravity 真实请求门）。
        if "--version" in command:
            output = "agy 1.0"
        elif "-p" in command:
            output = "2ByteASR_OK"
        else:
            output = "gemini-3.7-flash-high\tGemini"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(provider, "_run_cli_command", fake_run)
    first = provider.validate(use_cache=False)
    assert first.authenticated and len(calls) == 2  # version + actual session probe; models are lazy

    cached = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    monkeypatch.setattr(cached, "_run_cli_command", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("cache miss")))
    second = cached.validate()
    assert second.authenticated
    assert cached.last_timings["cache_hit"] is True


def test_cli_complex_structured_output_is_locally_parsed_and_validated(monkeypatch):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    monkeypatch.setattr(
        provider,
        "complete",
        lambda *_a, **kwargs: "```json\n{\"design_intent\":\"retro\",\"variants\":[]}\n```",
    )
    payload = provider.structured_complete([], {"type": "object"})
    assert payload["design_intent"] == "retro"
    assert payload["variants"] == []


def test_library_recovers_flv_duration_manual_ass_and_writes_backup(tmp_path):
    project_dir = tmp_path / "未命名工程 4"
    for child in ("autosave", "backup", "preview"):
        (project_dir / child).mkdir(parents=True, exist_ok=True)
    media = project_dir / "录播.flv"
    media.write_bytes(b"real-flv-fixture")
    target = project_dir / "未命名工程 4.2byteproj"
    official = SubtitleProject(media=StudioMedia(path=""))
    save_project(official, target)
    autosave = copy.deepcopy(official)
    autosave.media = StudioMedia(path=str(media), duration_ms=7_298_261, width=2560, height=1440)
    autosave.edit_sequence = {
        "source_path": str(media),
        "source_duration_ms": 7_298_261,
        "segments": [],
    }
    save_autosave(autosave, target)
    (project_dir / "preview" / "manual.ass").write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.20,default,S00,0,0,0,,手动字幕\n",
        encoding="utf-8",
    )

    snapshot, summary, needs_repair = library_project_snapshot(
        target, {"cue_count": 1, "source_media": str(media)}
    )
    assert needs_repair
    assert summary["source_media"] == str(media)
    assert summary["duration_ms"] == 7_298_261
    assert summary["cue_count"] == 1
    assert snapshot.cues[0].text == "手动字幕"

    repaired, _summary, changed = repair_project_library_metadata(
        target, {"cue_count": 1, "source_media": str(media)}
    )
    assert changed and project_backup_path(target).is_file()
    persisted = load_project(target)
    assert persisted.media.path == str(media)
    assert persisted.media.width == 2560 and persisted.media.height == 1440
    assert len(repaired.cues) == len(persisted.cues) == 1


def test_structural_model_refresh_never_requests_advanced_preview(monkeypatch, tmp_path):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.cues.append(StudioCue("manual", 0, 1000, "字幕"))
    page.selected_cue_id = "manual"
    calls: list[object] = []
    monkeypatch.setattr(page, "_sync_selected_cue_advanced", lambda payload: calls.append(payload))
    page.cue_controller.model_changed()
    _app().processEvents()
    assert calls == []
    page.close_page()


def test_candidate_bin_has_remove_clear_and_order_buttons():
    app = _app()
    panel = HighlightAssistantPanel()
    candidates = [
        HighlightCandidate("a", "第一段", 1_000, 31_000, 0.9, status="accepted"),
        HighlightCandidate("b", "第二段", 40_000, 70_000, 0.8, status="accepted"),
        HighlightCandidate("c", "第三段", 80_000, 110_000, 0.7, status="accepted"),
    ]
    panel.reload_candidates(candidates)
    panel.show()
    app.processEvents()
    assert panel.bin.count() == 3 and panel.clear_bin_button.isVisible()
    middle = panel.bin.itemWidget(panel.bin.item(1))
    buttons = {button.text(): button for button in middle.findChildren(QPushButton)}
    assert {"↑", "↓", "×"} <= set(buttons)
    assert all(button.objectName() == "studioButton" for button in buttons.values())
    assert all(button.cursor().shape() == Qt.CursorShape.PointingHandCursor for button in buttons.values())
    panel.close()


def test_style_property_uses_square_swatch_and_row_tint():
    _app()
    row = StylePropertyRow("填充")
    row.set_chip_colors(["#FF6B5F", "#FFD26A"])
    assert row.chip.width() == row.chip.height() == 36
    assert row._tint_colors == ["#FF6B5F", "#FFD26A"]


def test_real_provider_payload_keeps_three_distinct_animated_variants(monkeypatch):
    # Use the archived, contract-valid response; old local recipe variants
    # now correctly fail CHEAP_MOTION and cannot stand in for valid output.
    trace=json.loads((Path(__file__).parent/'data/p9a_r2_deepseek_raw_responses.json').read_text('utf8'))
    prompt=trace['instruction'];payload=copy.deepcopy(trace['raw_provider_responses'][0])

    class FakeProvider:
        provider_id = "google_antigravity"

        def structured_complete(self, *_args, **_kwargs):
            return copy.deepcopy(payload)

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: FakeProvider())
    monkeypatch.setattr(
        "twobyteasr.caption_design.studio_ai.available_font_shortlist",
        lambda **_kwargs: {
            "chinese_display": ["KaiTi"],
            "chinese_sans": ["Source Han Sans CN"],
            "serif": ["SimSun"],
            "handwriting": ["KaiTi"],
            "pixel_game": ["Microsoft YaHei UI"],
            "cartoon": ["KaiTi"],
        },
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.flv", duration_ms=10_000),
        cues=[StudioCue("cue", 0, 1000, "测试字幕")],
    )
    suggestion = request_style_design(project, "cue", prompt, {"models": {"polish_transport": "antigravity_cli"}})
    assert suggestion.raw_response["design_intent"] == payload["design_intent"]
    assert len(suggestion.variants) == 3
    signatures = {
        (
            item.typography.get("fontFamily"),
            str(item.fill),
            str(item.strokes),
            str(item.motion.to_dict()),
        )
        for item in suggestion.variants
    }
    assert len(signatures) == 3
    assert all(item.visual_graph.get('motionGraph',{}).get('tracks') for item in suggestion.variants)
    allowed_fonts = {"KaiTi", "Microsoft YaHei UI", "SimSun", "Source Han Sans CN"}
    assert all(item.typography.get("fontFamily") in allowed_fonts for item in suggestion.variants)
