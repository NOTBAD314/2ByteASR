"""2026-09-20II 四修回归：首媒体位置/黑屏换绑门/识别方案记忆/HEX 输入。

覆盖用户验收 Test 1-14：
 1 空工程导入 → playhead==0
 2 首加载 position≈0 + 首帧有效（真实 mpv，headed 冒烟另有脚本）
 3 已存工程 playhead=35s 重开恢复
 4 已有工程 20s 拖第二素材不回 0
 5 加载期源切换被门延迟、READY 后补切（不黑屏）
 6/7 选择方案 B → 返回主页/重启仍 B
 8 刷新方案列表 selection 不变
 9 方案删除 → 明确 fallback 无无效 ID
 10-14 HEX 键入序列不被重写/Enter 提交/中间态/非法恢复/无递归
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="session", autouse=True)
def _session_settings_isolation(tmp_path_factory):
    import twobyteasr.storage.settings as settings_module

    redirected_root = tmp_path_factory.mktemp("fourfix-settings-root")
    settings_module.stable_settings_root = lambda: redirected_root
    yield


# ---------------------------------------------------------------------------
# Test 1/3/4：时间轴跨工程播放头隔离与恢复
# ---------------------------------------------------------------------------

def _timeline():
    from twobyteasr.studio.studio_timeline import WaveformTimeline

    return WaveformTimeline()


def _project(tmp_path, name="p", duration_ms=60_000, playhead_ms=None):
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project

    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "m.mp4"), duration_ms=duration_ms),
    )
    if playhead_ms is not None:
        project.studio_state["playhead_ms"] = int(playhead_ms)
    return project


def test_set_project_resets_stale_playhead_across_projects(tmp_path):
    timeline = _timeline()
    a = _project(tmp_path, "a")
    timeline.set_project(a)
    timeline.set_playhead(8_589)
    assert timeline.playhead_ms == 8_589

    # 关闭到 hub（set_project(None)）→ 残留位置必须清零
    timeline.set_project(None)
    assert timeline.playhead_ms == 0

    # 新工程：仍然 0（Test 1 的核心不变量）
    b = _project(tmp_path, "b")
    timeline.set_project(b)
    assert timeline.playhead_ms == 0

    # 同一工程重复 set_project（refresh 场景）不清当前播放头
    timeline.set_playhead(20_000)
    timeline.set_project(b)
    assert timeline.playhead_ms == 20_000


def test_saved_playhead_restore_not_clobbered_by_reset(tmp_path):
    """Test 3：已存工程 35s 恢复顺序——set_project 重置在前、hydration 恢复在后。"""
    timeline = _timeline()
    timeline.set_playhead(8_589)  # 上一工程残留
    saved = _project(tmp_path, "saved", playhead_ms=35_000)
    timeline.set_project(saved)   # open_project 会先做这一步（重置为 0）
    assert timeline.playhead_ms == 0
    # hydration 阶段随后恢复保存位置（studio_project_controller 同序列）
    timeline.set_playhead(min(60_000, max(0, int(saved.studio_state["playhead_ms"]))))
    assert timeline.playhead_ms == 35_000


def test_second_media_drop_keeps_current_playhead(tmp_path):
    """Test 4：已有素材后 dropEvent 不再走首媒体归零分支。"""
    page = _studio_page(tmp_path)
    try:
        project = _project(tmp_path, "second")
        from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip

        media_file = tmp_path / "a.mp4"
        media_file.write_bytes(b"\0" * 16)
        add_media_asset(project, str(media_file), duration_ms=60_000)
        track = create_video_track(project)
        add_video_clip(project, track.id, project.media_pool[0].asset_id, timeline_in_ms=0)
        page.project = project
        page.timeline.set_project(project)
        page.timeline.set_playhead(20_000)

        # 非空工程：首媒体判定必须为 False → 不会强制 0
        assert page._timeline_is_blank_for_first_media() is False
        assert page.timeline.playhead_ms == 20_000

        # 空工程（重开一个）：判定为 True
        blank = _project(tmp_path, "blank")
        page.project = blank
        page.timeline.set_project(blank)
        assert page._timeline_is_blank_for_first_media() is True
    finally:
        page.close()
        page.deleteLater()


# ---------------------------------------------------------------------------
# Test 5：换绑风暴门
# ---------------------------------------------------------------------------

def _studio_page(tmp_path):
    import twobyteasr.studio.studio_ui as studio_ui

    page = studio_ui.SubtitleStudioPage()
    return page


def test_rebind_storm_gate_defers_until_ready(tmp_path):
    """Test 5：mpv 加载期要求换绑新源 → 门拦下并登记，READY 后补切。"""
    from unittest.mock import MagicMock

    page = _studio_page(tmp_path)
    try:
        project = _project(tmp_path, "gate")
        from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip

        media_file = tmp_path / "raw.flv"
        media_file.write_bytes(b"\0" * 16)
        add_media_asset(project, str(media_file), duration_ms=60_000)
        track = create_video_track(project)
        add_video_clip(project, track.id, project.media_pool[0].asset_id, timeline_in_ms=0)
        page.project = project
        page.timeline.set_project(project)

        video = MagicMock()
        video._startup_state = "MEDIA_OPENING"
        video._startup_play_requested = True
        video._media_path = str(media_file)
        video._media_attached = True
        video._playback_clock = None
        video.playback_position_snapshot.return_value = MagicMock(playback_generation=0)
        video.switch_media_at_async.return_value = True
        page.video = video
        page._active_video_preview_key = "primary"
        page._active_video_preview_source_path = str(media_file)

        # 把目标源解析结果强制指向"另一个源"（模拟 optimized 代理身份）
        original_target = page._multitrack_preview_target

        def _target_with_proxy(timeline_ms):
            base = original_target(timeline_ms)
            if base is None:
                return None
            base = dict(base)
            base["source_path"] = str(tmp_path / "optimized.mp4")
            return base

        page._multitrack_preview_target = _target_with_proxy

        result = page._activate_multitrack_preview(0)
        # 门必须生效：不切换、不 seek，只登记
        video.switch_media_at_async.assert_not_called()
        assert getattr(page, "_deferred_source_rebind", False) is True
        assert result is not None and result[1] is False

        # READY 后补切：清掉 startup 态再跑一次 → 正常换绑
        video._startup_state = "READY"
        page._deferred_source_rebind = False
        result2 = page._activate_multitrack_preview(0)
        video.switch_media_at_async.assert_called()
        assert result2 is not None and result2[1] is True
    finally:
        page.close()
        page.deleteLater()


def test_canvas_ready_transition_fires_retry(tmp_path):
    """画布 READY 转换触发 _retry_deferred_source_rebind（登记后补切）。"""
    from twobyteasr.studio.studio_video_canvas import MpvCanvas

    called = []
    stub_page = type("P", (), {
        "_studio_trace": staticmethod(lambda *a, **k: None),
        "_deferred_source_rebind": True,
        "_retry_deferred_source_rebind": staticmethod(lambda: called.append(True)),
    })()
    canvas = MpvCanvas()
    canvas._studio_page = lambda: stub_page
    canvas._startup_state = "MEDIA_OPENING"
    canvas._startup_started_at = 0.0
    canvas._set_startup_state("READY")
    APP.processEvents()
    assert called, "READY 转换必须调度补切"
    canvas.deleteLater()


# ---------------------------------------------------------------------------
# Test 6-9：识别方案记忆
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_main_window(monkeypatch, tmp_path):
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_module

    original_settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    window = ui_module.MainWindow([], legacy, object(), None)
    try:
        yield window, legacy, ui_module
    finally:
        legacy.RUNTIME_SETTINGS = original_settings
        window.close()
        window.deleteLater()


def _combo_shows(window) -> str:
    return str(window.project_profile_combo.currentData() or "")


def test_profile_selection_persists_across_recreate(isolated_main_window):
    """Test 6+7：选择 B → 重建窗口（≈重启）仍 B。"""
    window, legacy, ui_module = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    b = store.create("B 方案", llm_enabled=True, llm_config_ref="")
    window._refresh_project_profile_combo()
    index = window.project_profile_combo.findData(b.id)
    assert index >= 0
    window.project_profile_combo.setCurrentIndex(index)
    APP.processEvents()
    assert window.current_project_profile.id == b.id
    assert store.last_selected_id() == b.id, "显式切换必须固化 last_selected"

    # 模拟"重启"：重建窗口走 _restore_last_project_profile（singleShot(0)）
    window2 = ui_module.MainWindow([], legacy, object(), None)
    try:
        from PySide6.QtCore import QEventLoop, QTimer as _QTimer

        loop = QEventLoop()
        _QTimer.singleShot(150, loop.quit)
        loop.exec()
        APP.processEvents()
        assert window2.current_project_profile is not None
        assert window2.current_project_profile.id == b.id
        assert _combo_shows(window2) == b.id
    finally:
        window2.close()
        window2.deleteLater()


def test_return_home_restores_global_plan_over_project_plan(isolated_main_window):
    """进 Studio 应用工程方案后返回主页：恢复全局 last_selected。"""
    window, legacy, ui_module = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    global_plan = store.create("全局方案", llm_enabled=True, llm_config_ref="")
    project_plan = store.create("工程方案", llm_enabled=True, llm_config_ref="")
    store.set_last_selected(global_plan.id)

    # 模拟进 Studio 打开工程：应用工程方案（combo 被占据）
    window._apply_project_profile(store.get(project_plan.id), mark_used=False)
    assert _combo_shows(window) == project_plan.id

    window._return_to_settings()
    APP.processEvents()
    assert _combo_shows(window) == global_plan.id, "返回主页必须恢复全局上次使用方案"
    assert store.last_selected_id() == global_plan.id


def test_profile_refresh_keeps_selection(isolated_main_window):
    """Test 8：刷新方案列表（combo 重建）selection 不变。"""
    window, legacy, ui_module = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    b = store.create("B 方案", llm_enabled=True, llm_config_ref="")
    window._apply_project_profile(store.get(b.id), mark_used=False)
    store.set_last_selected(b.id)

    window._refresh_project_profile_combo()
    APP.processEvents()
    assert _combo_shows(window) == b.id


def test_deleted_profile_falls_back_cleanly(isolated_main_window):
    """Test 9：B 被删除 → combo 回自定义方案，无无效 ID。"""
    window, legacy, ui_module = isolated_main_window
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore

    store = ProjectProfileStore(Path(window.profile_store.path))
    b = store.create("将被删除", llm_enabled=True, llm_config_ref="")
    window._apply_project_profile(store.get(b.id), mark_used=False)
    store.set_last_selected(b.id)
    store.delete(b.id)

    window._refresh_project_profile_combo()
    APP.processEvents()
    current = _combo_shows(window)
    assert current == "", "被删方案不得残留在 combo selection"
    assert store.get(current) is None or current == ""


# ---------------------------------------------------------------------------
# Test 10-14：HEX 输入
# ---------------------------------------------------------------------------

def _picker():
    from twobyteasr.design.color_picker import ColorPickerWidget

    widget = ColorPickerWidget(show_alpha=True)
    widget.set_color(QColor("#3366CC"))
    return widget


def test_hex_typing_sequence_never_reset_to_black():
    """Test 10：逐字符输入 #FF7100 全程不被重写。"""
    from PySide6.QtTest import QTest

    widget = _picker()
    widget.hex_edit.setFocus()
    widget.hex_edit.clear()
    typed = ""
    for character in "#FF7100":
        typed += character
        QTest.keyClicks(widget.hex_edit, character)
        APP.processEvents()
        assert widget.hex_edit.text() == typed, f"输入 {typed!r} 被改写为 {widget.hex_edit.text()!r}"
        assert widget._color.name() != "#000000"
    assert widget.hex_edit.text() == "#FF7100"
    widget.deleteLater()


def test_hex_complete_input_live_previews_then_enter_commits():
    """完整合法键入即时预览；Enter 后 committed color == #FF7100（Test 11+即时预览）。"""
    from PySide6.QtTest import QTest

    widget = _picker()
    widget.hex_edit.setFocus()
    widget.hex_edit.clear()
    QTest.keyClicks(widget.hex_edit, "#FF7100")
    APP.processEvents()
    assert widget._color.name() == "#ff7100", "完整合法 HEX 键入应即时预览"
    QTest.keyClick(widget.hex_edit, Qt.Key.Key_Return)
    APP.processEvents()
    assert widget._color.name() == "#ff7100"
    widget.deleteLater()


def test_hex_partial_input_keeps_last_valid_color():
    """Test 12：#123 中间态 → last valid color 不变。"""
    from PySide6.QtTest import QTest

    widget = _picker()
    widget.hex_edit.setFocus()
    widget.hex_edit.clear()
    QTest.keyClicks(widget.hex_edit, "#123")
    APP.processEvents()
    assert widget._color.name() == "#3366cc", "中间态不得改变已提交颜色"
    widget.deleteLater()


def test_hex_invalid_commit_restores_last_valid_with_validation():
    """Test 13：非法值失焦 → 恢复上一合法 + 轻量红框提示，绝不回退成黑。"""
    from PySide6.QtTest import QTest

    widget = _picker()
    widget.hex_edit.setFocus()
    widget.hex_edit.clear()
    QTest.keyClicks(widget.hex_edit, "#GG123")
    APP.processEvents()
    QTest.keyClick(widget.hex_edit, Qt.Key.Key_Return)
    APP.processEvents()
    assert widget._color.name() == "#3366cc", "非法提交不得把颜色改成黑"
    assert widget.hex_edit.text().upper() == "#3366CC"
    assert "border" in widget.hex_edit.styleSheet(), "应有轻量 validation 提示"
    widget.deleteLater()


def test_programmatic_color_update_no_recursion():
    """Test 14：程序化 set_color 更新 HEX 不递归、不破坏输入。"""
    widget = _picker()
    emissions = []
    widget.colorChanged.connect(lambda color: emissions.append(color.name()))
    widget.set_color(QColor("#AB12CD"))
    APP.processEvents()
    assert widget.hex_edit.text() == "#AB12CD"
    assert emissions.count("#ab12cd") == 1, "一次 set_color 恰好一次 colorChanged"
    widget.deleteLater()


def test_alpha_change_keeps_hex_rgb_text():
    """透明度不破坏 RGB HEX 文本（十：双向同步）。"""
    from PySide6.QtTest import QTest

    widget = _picker()
    widget.set_color(QColor("#3366CC"))
    before = widget.hex_edit.text()
    QTest.keyClicks(widget.alpha_spin, "w")  # 聚焦并改值路径走 _alpha_spin_changed
    widget.alpha_spin.setValue(40)
    APP.processEvents()
    assert widget.hex_edit.text() == before, "透明度不得改写 RGB HEX"
    assert widget._color.alpha() == 102
    widget.deleteLater()
