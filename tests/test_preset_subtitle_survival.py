"""2026-09-18 P0 回归：字幕样式预设应用绝不能让其它字幕消失。

数据层（cue/model/timeline 计数）+ 渲染层（advanced 路由 cue 常驻 live ASS
轨道作 LIVE 近似兜底；web 帧未就绪时所有权回退 native）。覆盖用户规约
Test A–F（100 cue × 多次预设 × undo/redo × 保存重开）。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project,
    save_project,
)

CUE_COUNT = 100


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _project(tmp_path):
    project = SubtitleProject(
        media=StudioMedia(str(tmp_path / "m.flv"), duration_ms=600_000),
        speakers=[StudioSpeaker("S00")],
        cues=[
            StudioCue(f"c{i}", 1000 + i * 5000, 4000 + i * 5000, f"字幕{i}", "S00")
            for i in range(CUE_COUNT)
        ],
    )
    project.validate()
    return project


def _page(tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    app = _app()
    page = SubtitleStudioPage()
    page._create_blank_studio()
    project = _project(tmp_path)
    page.project = project
    page.project_path = tmp_path / "p.2byteproj"
    page.timeline.set_project(project)
    page.cue_model.set_project(project)
    return page


def _close(page):
    page.close_page()
    page.deleteLater()
    _app().processEvents()


def _presets():
    from twobyteasr.caption_style.style_presets import StylePresetStore

    return [key for key in StylePresetStore().all() if key != "default"] or ["default"]


# --------------------------------------------------------------- data layer

def test_apply_preset_keeps_all_cues_and_items(tmp_path):
    page = _page(tmp_path)
    try:
        page.select_cue("c50")
        pid = _presets()[0]
        page.style_preset.setCurrentIndex(max(0, page.style_preset.findData(pid)))
        page._apply_style(replace_preset=True)
        _app().processEvents()
        assert len(page.project.cues) == CUE_COUNT
        assert page.cue_model.rowCount() == CUE_COUNT
        assert len(page.timeline._cues_by_start) == CUE_COUNT
    finally:
        _close(page)


def test_ten_preset_applications_never_lose_cues(tmp_path):
    page = _page(tmp_path)
    try:
        presets = _presets()
        for round_index in range(10):
            page.select_cue(f"c{round_index * 7 % CUE_COUNT}")
            pid = presets[round_index % len(presets)]
            page.style_preset.setCurrentIndex(max(0, page.style_preset.findData(pid)))
            page._apply_style(replace_preset=(round_index % 2 == 0))
            _app().processEvents()
            assert len(page.project.cues) == CUE_COUNT, f"round {round_index}"
            assert page.cue_model.rowCount() == CUE_COUNT, f"round {round_index}"
            assert len(page.timeline._cues_by_start) == CUE_COUNT, f"round {round_index}"
    finally:
        _close(page)


def test_playhead_sweep_finds_every_cue_after_apply(tmp_path):
    page = _page(tmp_path)
    try:
        page.select_cue("c50")
        pid = _presets()[0]
        page.style_preset.setCurrentIndex(max(0, page.style_preset.findData(pid)))
        page._apply_style(replace_preset=True)
        _app().processEvents()
        page.timeline.set_visible_window(0, 600_000)
        visible_ids = {cue.id for cue in page.timeline.visible_cues()}
        for index in (1, 20, 50, 80, 100):
            cue = next(c for c in page.project.cues if c.id == f"c{index - 1}")
            assert cue.id in visible_ids, f"cue {index} missing from timeline window"
            # 播头进入该 cue 时，数据面必须能解析出当前 cue。
            page.timeline.set_playhead(cue.start_ms + 500)
            inside = [c for c in page.timeline._cues_intersecting(
                cue.start_ms, cue.start_ms + 1000) if c.id == cue.id]
            assert inside, f"cue {index} not intersecting its own window"
    finally:
        _close(page)


def test_undo_redo_after_preset_keeps_cue_set(tmp_path):
    page = _page(tmp_path)
    try:
        page.select_cue("c50")
        pid = _presets()[0]
        page.style_preset.setCurrentIndex(max(0, page.style_preset.findData(pid)))
        page._apply_style(replace_preset=True)
        _app().processEvents()
        stack = page.undo_stack
        for _ in range(min(3, stack.count())):
            stack.undo()
            _app().processEvents()
            assert len(page.project.cues) == CUE_COUNT
            assert len(page.timeline._cues_by_start) == CUE_COUNT
        for _ in range(min(3, stack.count())):
            stack.redo()
            _app().processEvents()
            assert len(page.project.cues) == CUE_COUNT
            assert page.cue_model.rowCount() == CUE_COUNT
    finally:
        _close(page)


def test_save_and_reload_preserves_cues_and_style(tmp_path):
    page = _page(tmp_path)
    target = tmp_path / "saved.2byteproj"
    try:
        page.select_cue("c50")
        pid = _presets()[0]
        page.style_preset.setCurrentIndex(max(0, page.style_preset.findData(pid)))
        page._apply_style(replace_preset=True)
        _app().processEvents()
        save_project(page.project, target)
        reloaded = load_project(target)
        assert len(reloaded.cues) == CUE_COUNT
        assert reloaded.cues[49].style_id != ""
    finally:
        _close(page)


# ---------------------------------------------------------- renderer layer

def _remotion_recipe_payload():
    # 非纯色填充（gradient）按 route_recipe 强制 advanced 渲染引擎。
    return {
        "name": "测试advanced",
        "colors": {"fill": {"type": "linear", "stops": [
            {"position": 0.0, "color": "#FFFFFF"},
            {"position": 1.0, "color": "#33CC66"},
        ]}},
        "typography": {"fontSize": 64, "fontFamily": "Source Han Sans SC"},
    }


def test_advanced_cues_stay_in_live_ass_revision(tmp_path):
    """核心不变量：advanced 路由的 cue 不再被剔出 live ASS 编译。

    这是"应用 web 主题预设后其它字幕消失"的渲染层根因——native 轨被清空，
    逐 cue 等 web 发布，迟到/失败即不可见。
    """
    page = _page(tmp_path)
    try:
        from twobyteasr.caption_style.style_recipe import (
            StyleRecipe, recipe_payload_for_style, route_recipe,
        )

        payload = _remotion_recipe_payload()
        style_id = page.project.cues[0].style_id or "default"
        page.project.style_recipes[style_id] = StyleRecipe.from_dict(payload).to_dict()
        routed = route_recipe(
            recipe_payload_for_style(page.project.style_recipes, style_id)
        )
        assert routed.engine == "remotion", routed

        revision = page._ass_preview_revision()
        assert revision is not None
        revision_ids = {cue.id for cue in revision.cues}
        assert len(revision_ids) == CUE_COUNT, (
            "advanced 路由不得从 live ASS 轨剔除 cue（LIVE 近似兜底）"
        )
    finally:
        _close(page)


def test_advanced_cue_without_frame_falls_back_to_native_owner(tmp_path):
    """web 帧未就绪时，播头所在 advanced cue 的所有权应回退 native。"""
    page = _page(tmp_path)
    try:
        from twobyteasr.diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE
        from twobyteasr.caption_style.style_recipe import StyleRecipe

        payload = _remotion_recipe_payload()
        style_id = page.project.cues[0].style_id or "default"
        page.project.style_recipes[style_id] = StyleRecipe.from_dict(payload).to_dict()
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        from PySide6.QtTest import QTest

        page.show()
        QTest.qWaitForWindowExposed(page)
        page.timeline.set_playhead(cue.start_ms + 500)
        before = len(GLOBAL_STUDIO_TRACE.recent())
        page.ensure_active_subtitle_renderer(reason="test_fallback")
        _app().processEvents()
        recent = GLOBAL_STUDIO_TRACE.recent()[before:]
        visibility = next(
            (item for item in reversed(recent) if item.get("event") == "SUBTITLE_VISIBILITY"),
            None,
        )
        assert visibility is not None
        assert visibility.get("cue_id") == cue.id
        assert visibility.get("canonical_renderer_route") == "advanced"
        # 帧未就绪 → 兜底 native，而不是 NONE（不可见）。
        assert visibility.get("foreground_owner") in {"native", "advanced_live"}, visibility
    finally:
        _close(page)
