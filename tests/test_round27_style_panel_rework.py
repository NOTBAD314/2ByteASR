"""二十七轮：工具面板特效字幕模式重排。

用户反馈：①特效字幕模式下应**只保留 AI 字幕调整**——下方 文字/外观 等
原生参数分区对 web cue 无效却占屏（拥挤无重点）；②AI 调整卡内部布局要
有层级：主题身份头 → 主按钮（工坊）→ 快速修改一行 → 折叠参数 → 范围/
套用/恢复普通字幕。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page(tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import (
        StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
    )

    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    page = SubtitleStudioPage()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    project = SubtitleProject(
        media=StudioMedia(path=str(video), duration_ms=60_000, width=1920, height=1080),
    )
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    for index in range(2):
        project.cues.append(StudioCue(
            f"c{index}", index * 1000, index * 1000 + 900, f"第{index}句",
            speaker_id="S01",
        ))
    project.validate()
    page.project = project
    page.project_path = tmp_path / "round27.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.undo_stack.clear()
    page.undo_stack.setClean()
    return page


def _theme() -> dict:
    from twobyteasr.caption_design.web_theme import builtin_web_themes

    return builtin_web_themes()["strand-timefall"].to_dict()


def test_web_cue_hides_native_sections(tmp_path):
    _app()
    page = _page(tmp_path)
    assert getattr(page, "style_native_hosts", None), "native hosts must be registered"
    page.select_cue("c0")
    assert page.web_adjust_host.isHidden(), "normal cue: AI card hidden"
    assert all(not host.isHidden() for host in page.style_native_hosts)
    assert page._apply_web_theme("c0", _theme())
    page.select_cue("c0")  # select_cue 刷新可见性
    assert not page.web_adjust_host.isHidden(), "web cue: AI card visible"
    hidden = [host for host in page.style_native_hosts if host.isHidden()]
    assert len(hidden) == len(page.style_native_hosts), (
        f"all native sections must hide for a web cue (hidden {len(hidden)}/"
        f"{len(page.style_native_hosts)})"
    )
    # 恢复普通字幕后原生分区回来。
    page._clear_advanced_style()
    page.select_cue("c0")
    assert page.web_adjust_host.isHidden()
    assert all(not host.isHidden() for host in page.style_native_hosts)


def test_identity_header_and_restore_button(tmp_path):
    _app()
    page = _page(tmp_path)
    assert page._apply_web_theme("c0", _theme())
    page.select_cue("c0")
    identity = page.web_adjust_identity.text()
    assert "Strand Timefall" in identity, identity
    assert page.web_adjust_restore.text() == "恢复普通字幕样式"
    # 主按钮仍在且是工坊入口。
    assert "工坊" in page.web_adjust_workshop.text()


def test_quick_adjust_collapsed_by_default(tmp_path):
    _app()
    page = _page(tmp_path)
    assert page.web_adjust_quick_host.isHidden(), "quick adjust starts collapsed"
    page.web_adjust_quick_toggle.setChecked(True)
    assert not page.web_adjust_quick_host.isVisible() or not page.web_adjust_quick_host.isHidden()
    assert "▾" in page.web_adjust_quick_toggle.text()
    page.web_adjust_quick_toggle.setChecked(False)
    assert page.web_adjust_quick_host.isHidden()
    assert "▸" in page.web_adjust_quick_toggle.text()


def test_opinion_assembles_from_quick_controls(tmp_path):
    _app()
    page = _page(tmp_path)
    page.web_adjust_font.setCurrentText("KaiTi")
    page.web_adjust_size.setValue(66)
    page._web_adjust_color_value = "#FFD700"
    opinion = page._assemble_web_adjust_opinion()
    # 字体下拉是懒加载组合框：文本可能被规范化，断言三段意见都在。
    assert "字体改成" in opinion and "66" in opinion and "#FFD700" in opinion
    page.web_adjust_extra.setText("背景更透明")
    opinion = page._assemble_web_adjust_opinion()
    assert opinion.endswith("背景更透明")
    label_text = page.web_adjust_opinion.text()
    assert label_text.startswith("将请求 AI：")
