"""Bilingual manual text survives ASS wrapping without relaxing content checks."""
from pathlib import Path

import pytest

from twobyteasr.exports.studio_subtitle_export import SubtitleExportArtifact, verify_subtitle_artifact
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


@pytest.mark.parametrize("source,rendered,valid", [
    ("DaVinci YRGB color managed", r"DaVinci YRGB \Ncolor managed", True),
    ("但 DaVinci YRGB\n采用色彩管理", r"但 DaVinci \NYRGB\N采用色彩管理", True),
    ("但 DaVinci YRGB\n采用色彩管理", "但 DaVinci YRGB采用色彩管理", False),
    ("DaVinci YRGB color managed", r"DaVinci \Ncolor managed", False),
    ("DaVinci YRGB", r"{DaVinci YRGB}错误内容", False),
    ("DaVinci YRGB", r"{\pos(10,20)}DaVinci \NYRGB", True),
    ("DaVinci YRGB color managed", r"DaVinci YRGB\h\Ncolor managed", True),
    ("A B", r"A\NB", False),
    (r"A\NB", r"A\\NB", True),
    (r"A\NB", r"A\NB", False),
    (r"A\hB", r"A\\hB", True),
    ("A\u2028B", r"A\NB", True),
    ("A\u2029B", "AB", False),
])
def test_ass_readback_only_ignores_added_visual_breaks(tmp_path, source, rendered, valid):
    project = SubtitleProject(StudioMedia("", duration_ms=3000),
                              cues=[StudioCue("manual", 1000, 2000, source, speaker_id="S01")])
    path = tmp_path / "bilingual.ass"
    path.write_text("[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,S01,0,0,0,," + rendered + "\n", encoding="utf-8")
    result = verify_subtitle_artifact(SubtitleExportArtifact(path, "ass", "", 1), project)
    assert result.valid is valid
    if not valid:
        assert result.first_mismatch["cue_id"] == "manual"


@pytest.mark.parametrize("separator", [" ", "\u2028", "\u2029"])
def test_real_compiler_wrapping_hard_spaces_passes_readback(tmp_path, separator):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
    from twobyteasr.projects.studio_project import SubtitleStyle
    from twobyteasr.rendering.ass_compiler import compile_ass
    app = QApplication.instance() or QApplication([])
    source = ("DaVinci YRGB color managed preserves every internal space during automatic wrapping." + separator) * 3
    project = SubtitleProject(
        StudioMedia("", duration_ms=3000, width=1920, height=1080),
        styles=[SubtitleStyle("default", "Readback", font_family="Microsoft YaHei", font_size=92)],
        cues=[StudioCue("manual", 1000, 2000, source, speaker_id="S01")],
        render_settings={"play_res_x":1920, "play_res_y":1080},
    )
    project.validate()
    caption = resolve_caption_style(project.styles, project.speakers, project.cues[0], project.style_recipes, 1920, 1080)
    assert any(line["breakAfter"] == "automatic" for line in caption.layout["lines"])
    content = compile_ass(project)
    assert r"\h\N" in content or r"\N\h" in content
    path = tmp_path / "compiled.ass"
    path.write_text(content, encoding="utf-8")
    result = verify_subtitle_artifact(SubtitleExportArtifact(path, "ass", "", 1), project)
    assert result.valid, result.first_mismatch


def test_separate_dialogue_rows_cannot_supply_missing_source_characters(tmp_path):
    project = SubtitleProject(StudioMedia("", duration_ms=3000),
                              cues=[StudioCue("manual", 1000, 2000, "AB", speaker_id="S01")])
    path = tmp_path / "split.ass"
    row = "Dialogue: 0,0:00:01.00,0:00:02.00,Default,S01,0,0,0,,"
    path.write_text("[Events]\n" + row + "A\n" + row + "B\n", encoding="utf-8")
    result = verify_subtitle_artifact(SubtitleExportArtifact(path, "ass", "", 1), project)
    assert not result.valid and result.first_mismatch["cue_id"] == "manual"
