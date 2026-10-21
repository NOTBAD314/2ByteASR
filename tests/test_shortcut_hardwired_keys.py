"""2026-10-17: keys and hints that ignored the shortcut registry now follow it.

The shortcut page inventory found four places where a rebinding was silently
undone or mislabelled: Studio toolbar tooltips naming the default key, the home
start button tooltip ("(Ctrl+Enter)" written back by the readiness bar), the
export page's literal I / O shortcuts and the timeline's own Ctrl+A.

The second round (same day) did the texts left over: the review and
empty-timeline undo hints, the timeline's selected-gap hints, the audio track
menu, the pronoun tip on review card 1 and the interface zoom toast.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.studio import shortcut_registry as reg


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A private shortcut store; listeners from this test stay in this test."""
    monkeypatch.setattr(reg, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(reg, "_listeners", [])
    return tmp_path / "settings.json"


def test_display_names_keys_like_the_key_caps(qapp):
    assert reg.display("Ctrl+Return", "win32") == "Ctrl+Enter"
    assert reg.display("Num+Enter", "win32") == "Enter"
    assert reg.display("Delete", "win32") == "Delete"
    assert reg.display("Meta+K", "win32") == "Win+K"
    assert reg.display("Ctrl++", "win32") == "Ctrl++"
    assert reg.display("Shift+Q", "win32") == "Shift+Q"
    assert reg.display("", "win32") == ""


def test_display_ignores_the_apps_qt_translation(qapp):
    """In the app Qt's Chinese translator turned the default start key into "Ctrl+回车"."""
    from PySide6.QtCore import QTranslator

    class Chinese(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            return {"Return": "回车", "Space": "空格", "Left": "左"}.get(source, "")

        def isEmpty(self):
            return False

    translator = Chinese()
    qapp.installTranslator(translator)
    try:
        assert [reg.display(key, "win32") for key in ("Ctrl+Return", "Space", "Left")] == ["Ctrl+Enter", "Space", "Left"]
    finally:
        qapp.removeTranslator(translator)


# ------------------------------------------------------------ Studio


def _studio(qapp):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page = SubtitleStudioPage()
    qapp.processEvents()
    return page


def _close(qapp, page):
    page.close_page()
    page.deleteLater()
    qapp.processEvents()


def _by_source(page, template):
    from PySide6.QtWidgets import QToolButton
    return next(button for button in page.findChildren(QToolButton) if button.property("commandSource") == template)


def _hints(page):
    return {
        "save": page.save_button, "undo": _by_source(page, "撤销 ({key})"), "redo": _by_source(page, "重做 ({key})"),
        "review": page.review_mode_button, "find": page.studio_find_replace_button,
        "track": page.add_subtitle_track_button, "add": page.add_subtitle_button,
        "selection": page.selection_tool_button, "forward": page.track_forward_tool_button,
        "razor": page.razor_tool_button, "merge_tool": page.merge_tool_button,
        "transition": _by_source(page, "转场 · {video} 视频 / {audio} 音频"),
        "split": _by_source(page, "拆分当前字幕 ({key})"), "merge": _by_source(page, "与下一条合并 ({key})"),
        "merge_previous": _by_source(page, "波纹向前合并 ({key})"),
        "merge_next": _by_source(page, "波纹向后合并 ({key})"), "delete": _by_source(page, "删除当前字幕 ({key})"),
        "frame_left": _by_source(page, "上一帧 ({key})"), "play": page.play_button,
        "frame_right": _by_source(page, "下一帧 ({key})"), "snap": page.snap_toggle, "frame": page.save_frame_button,
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows key names")
def test_studio_hints_read_as_before_with_default_keys(qapp, store):
    page = _studio(qapp)
    try:
        tips = {name: widget.toolTip() for name, widget in _hints(page).items()}
    finally:
        _close(qapp, page)
    assert tips == {
        "save": "保存项目 (Ctrl+S)", "undo": "撤销 (Ctrl+Z)", "redo": "重做 (Ctrl+Y)",
        "review": "R 进入 / 退出审核模式", "find": "查找并替换字幕文字 (Ctrl+F / Ctrl+H)",
        "track": "新建字幕轨 · 按 T 在此轨添加字幕", "add": "添加字幕 (T) · 在播放头创建字幕块",
        "selection": "选择工具 (V)", "forward": "轨道向前选择 (A) · Shift 单轨",
        "razor": "剃刀工具 (C)——移动鼠标预览切点与前后文字，点击切开；Esc 取消",
        "merge_tool": "合并工具 (B)——点选字幕后拖动方向合并", "transition": "转场 · Ctrl+D 视频 / Ctrl+Shift+D 音频",
        "split": "拆分当前字幕 (Ctrl+Shift+S)", "merge": "与下一条合并 (Ctrl+Shift+M)",
        "merge_previous": "波纹向前合并 (Shift+Q)", "merge_next": "波纹向后合并 (Shift+W)",
        "delete": "删除当前字幕 (Delete)", "frame_left": "上一帧 (Left)", "play": "播放或暂停 (Space)",
        "frame_right": "下一帧 (Right)", "snap": "拖动字幕时吸附到播放头、相邻边界和静音点（快捷键 S）",
        "frame": "保存工程画布原分辨率图片（Ctrl+Alt+F）",
    }


def test_studio_hints_and_overflow_menu_follow_a_rebind(qapp, store):
    page = _studio(qapp)
    try:
        hints = _hints(page)
        reg.save_values({"razor_tool": "Shift+C", "video_transition": "Ctrl+Alt+D", "split": "Ctrl+Alt+S",
                         "delete": "Backspace", "toggle_snap": "", "save_current_frame": "F9",
                         "add_subtitle": "Shift+T", "toggle_review": "F8", "find": "F3"})
        tips = {name: widget.toolTip() for name, widget in hints.items()}
        # The single-cue commands still leave the bar for the "更多" menu, which
        # lists them under their current tooltips.
        hidden = page._timeline_overflow_widgets
        menu = page.cue_more_button.menu()
        menu.aboutToShow.emit()
        entries = [action.text() for action in menu.actions()]
        mark_in = str(page._shortcut_key_text("mark_in"))
    finally:
        _close(qapp, page)
    assert tips["razor"].startswith(f"剃刀工具 ({reg.display('Shift+C')})——")
    assert tips["transition"] == f"转场 · {reg.display('Ctrl+Alt+D')} 视频 / {reg.display('Ctrl+Shift+D')} 音频"
    assert tips["split"] == f"拆分当前字幕 ({reg.display('Ctrl+Alt+S')})"
    assert tips["delete"] == f"删除当前字幕 ({reg.display('Backspace')})"
    assert tips["snap"].endswith("（快捷键 未绑定）")
    assert tips["frame"] == "保存工程画布原分辨率图片（F9）"
    assert f"({reg.display('Shift+T')})" in tips["add"] and f"按 {reg.display('Shift+T')} " in tips["track"]
    assert tips["review"].startswith("F8 ") and "(F3 / " in tips["find"]
    assert len(hidden) == 9 and all(widget.property("cueMenuCommand") for widget in hidden)
    assert f"拆分当前字幕 ({reg.display('Ctrl+Alt+S')})" in entries
    assert f"删除当前字幕 ({reg.display('Backspace')})" in entries
    assert mark_in == reg.display("I")


def test_studio_hint_of_an_unbound_key_is_translated(qapp, store, monkeypatch):
    from twobyteasr import i18n
    page = _studio(qapp)
    try:
        reg.save_values({"split": ""})
        monkeypatch.setattr(i18n, "current_language", lambda: "en")
        page._refresh_shortcut_tooltips()
        tip = _by_source(page, "拆分当前字幕 ({key})").toolTip()
    finally:
        _close(qapp, page)
    assert tip == "Split current caption (Unassigned)"


# ------------------------------------------------------------ timeline


def test_timeline_select_all_follows_the_registry(qapp, store):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    page = _studio(qapp)
    try:
        calls = []
        page.timeline.select_all_clips = lambda: calls.append("all")
        assert page.timeline.select_all_key == "Ctrl+A"
        reg.save_values({"select_all": "Ctrl+Shift+A"})
        assert page.timeline.select_all_key == "Ctrl+Shift+A"
        QTest.keyClick(page.timeline, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert calls == []  # the old key no longer selects every clip
        QTest.keyClick(page.timeline, Qt.Key.Key_A,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert calls == ["all"]
        reg.save_values({"select_all": ""})
        QTest.keyClick(page.timeline, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert calls == ["all"]
    finally:
        _close(qapp, page)


# ------------------------------------------------------------ home


def test_start_button_tooltip_keeps_the_rebound_key(qapp, store):
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
    from twobyteasr.app import ui as app_ui
    window = QWidget()
    window.start_button = QPushButton(window)
    window.start_hint = QLabel(window)
    window.readiness_chips_layout = QHBoxLayout()
    window._ui_language = "zh"
    window.media_paths = ["clip.mp4"]
    window._choose_media = lambda: None
    window._home_page_active = lambda: True
    window._refresh_readiness_bar = lambda items: app_ui.MainWindow._refresh_readiness_bar(window, items)
    app_ui._bind_home_shortcuts(window, window)
    window._refresh_readiness_bar([])
    assert window.start_button.toolTip() == f"开始生成字幕 ({reg.display('Ctrl+Return')})"
    reg.save_values({"home.start_run": "F5"})
    assert window.start_button.toolTip() == "开始生成字幕 (F5)"
    window._refresh_readiness_bar([])  # used to write "(Ctrl+Enter)" back
    assert window.start_button.toolTip() == "开始生成字幕 (F5)"
    assert window.start_button.shortcut().toString() == "F5"
    window.media_paths = []
    reg.save_values({"home.start_run": "F6"})
    assert window.start_button.toolTip() == "先选择素材才能开始"
    window.media_paths = ["clip.mp4"]
    reg.save_values({"home.start_run": ""})
    assert window.start_button.toolTip() == "开始生成字幕 (未绑定)"


# ------------------------------------------------------------ export page


def test_export_page_in_out_keys_follow_mark_in_and_mark_out(qapp, store, tmp_path, monkeypatch):
    from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    calls = []
    monkeypatch.setattr(StudioExportWorkspace, "_set_in", lambda self: calls.append("in"))
    ui = StudioExportWorkspace(SubtitleProject(media=StudioMedia(path="clip.mp4", duration_ms=1000)),
                               str(tmp_path / "preview.ass"))
    try:
        assert ui._shortcut_mark_in.key().toString() == "I"
        assert ui._shortcut_mark_out.key().toString() == "O"
        reg.save_values({"mark_in": "F7", "mark_out": ""})
        assert ui._shortcut_mark_in.key().toString() == "F7"
        assert ui._shortcut_mark_out.key().isEmpty()
        ui._shortcut_mark_in.activated.emit()
        assert calls == ["in"]
    finally:
        ui.close()
        ui.deleteLater()
        qapp.processEvents()


# ------------------------------------------------------------ round 2: the texts left over


def _review_page(tmp_path, monkeypatch, cues):
    from tests.test_review_click_fix import _fake_candidates
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.studio import studio_review_ui
    app, page = _page(tmp_path, monkeypatch, cues)
    monkeypatch.setattr(studio_review_ui, "review_candidates", _fake_candidates({}))
    return app, page


def _card_one(page):
    from twobyteasr.studio.studio_cards import ReviewCandidateCard
    layout = page.review_dock_candidate_layout
    return next(widget for widget in (layout.itemAt(index).widget() for index in range(layout.count()))
                if isinstance(widget, ReviewCandidateCard) and widget._suggestions)


def test_review_toasts_and_pronoun_tip_name_the_current_keys(qapp, store, tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue
    app, page = _review_page(tmp_path, monkeypatch, [StudioCue("a", 0, 2000, "他说他们马上到"),
                                                     StudioCue("b", 3000, 5000, "下一句")])
    try:
        page._set_review_mode(True)
        page.select_cue("a")
        page._refresh_review_summary_strip()
        app.processEvents()
        card = _card_one(page)
        default_tip = card._mark_tip(0)
        assert page._flip_review_pronouns()
        flipped = page.save_state.text()
        reg.save_values({"undo": "Ctrl+Alt+Z", "review_flip_pronoun": "Shift+P"})
        rebound_tip = card._mark_tip(0)  # the same card, hovered after the rebind
        assert page._flip_review_pronouns()
        flipped_again = page.save_state.text()
        assert page._apply_review_suggestion(0)
        changed = page.save_state.text()
        reg.save_values({"undo": ""})
        assert page._flip_review_pronouns()
        unbound = page.save_state.text()
    finally:
        page.close_page()
        page.deleteLater()
    assert flipped == "人称已切换 · Ctrl+Z 撤销"
    assert default_tip == "点一下：他 → 她；右键选择 他 / 她 / 它；按 P 切换整条的人称"
    assert rebound_tip == "点一下：他 → 她；右键选择 他 / 她 / 它；按 Shift+P 切换整条的人称"
    assert flipped_again == "人称已切换 · Ctrl+Alt+Z 撤销"
    assert changed.startswith("已改为「") and changed.endswith("」· Ctrl+Alt+Z 撤销")
    assert unbound == "人称已切换 · 未绑定 撤销"


def test_pronoun_tip_of_a_card_on_its_own_reads_the_store(qapp, store):
    from twobyteasr.studio.studio_cards import ReviewCandidateCard
    from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
    from twobyteasr.subtitle_rules.studio_qc import QCCandidate
    text = "他说他们马上到"
    card = ReviewCandidateCard(0, QCCandidate(text, ("Current",)), is_current=True, current_text=text,
                               suggestions=review_suggestions(text, ()))
    try:
        assert "；按 P 切换整条的人称" in card._mark_tip(0)
        reg.save_values({"review_flip_pronoun": "F4"})
        assert "；按 F4 切换整条的人称" in card._mark_tip(0)
    finally:
        card.deleteLater()


def test_empty_timeline_note_names_the_undo_key_and_follows_a_rebind(qapp, store, tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    app, page = _review_page(tmp_path, monkeypatch, [StudioCue("a", 0, 2000, "一句")])
    try:
        sequence = sequence_of(page.project)
        sequence.segments = []
        sequence.empty_timeline = True
        page._sync_video_empty_state()
        before = page.video_empty_note.text()
        reg.save_values({"undo": "Ctrl+Alt+Z"})
        after = page.video_empty_note.text()  # no other refresh: the rebind rewrote it
    finally:
        page.close_page()
        page.deleteLater()
    assert before == "已清除旧画面、字幕和播放状态；按 Ctrl+Z 可恢复"
    assert after == "已清除旧画面、字幕和播放状态；按 Ctrl+Alt+Z 可恢复"


def test_selected_gap_hints_name_the_delete_key(qapp, store, tmp_path, monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.studio import studio_timeline
    app, page = _review_page(tmp_path, monkeypatch, [StudioCue("a", 0, 2000, "一句")])
    painted = []
    real_tr = studio_timeline.tr

    def spy(source, **arguments):
        if source == "空白 · {key} 闭合":
            painted.append(str(arguments["key"]))
        return real_tr(source, **arguments)

    monkeypatch.setattr(studio_timeline, "tr", spy)
    try:
        timeline = page.timeline
        track_id = page.project.video_tracks[0].id if page.project.video_tracks else "V1"
        timeline.selected_gap = (track_id, 4000, 6000)
        timeline.grab()
        assert timeline.delete_key == "Delete"
        reg.save_values({"delete": "Backspace"})
        assert timeline.delete_key == "Backspace"
        timeline.grab()
        reg.save_values({"delete": ""})
        unbound = str(timeline._delete_key_text())
        timeline.selected_gap = None
    finally:
        page.close_page()
        page.deleteLater()
    assert painted[0] == "Delete" and painted[-1] == "Backspace"
    assert unbound == "未绑定"


def test_standalone_timeline_gap_hint_keeps_delete(qapp):
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline = WaveformTimeline()
    try:
        assert str(timeline._delete_key_text()) == "Delete"
    finally:
        timeline.deleteLater()


def test_audio_track_menu_names_the_gain_and_delete_keys(qapp, store, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    from twobyteasr.design import studio_theme
    from twobyteasr.projects.studio_project import AudioTrack, StudioCue
    from twobyteasr.timeline.studio_track_delete import track_menu
    menus = []

    def menu_without_exec(parent=None):
        menu = QMenu(parent)
        menu.exec = lambda *_args: None
        menus.append(menu)
        return menu

    monkeypatch.setattr(studio_theme, "create_studio_menu", menu_without_exec)
    app, page = _review_page(tmp_path, monkeypatch, [StudioCue("a", 0, 2000, "一句")])
    try:
        page.project.audio_tracks.append(AudioTrack("AX", "独立音频", []))
        track_menu(page, "audio", "AX", QPoint())
        default = [action.text() for action in menus[-1].actions() if action.text()]
        reg.save_values({"track_gain": "Shift+G", "delete": "Backspace"})
        track_menu(page, "audio", "AX", QPoint())
        rebound = [action.text() for action in menus[-1].actions() if action.text()]
        reg.save_values({"track_gain": ""})
        track_menu(page, "audio", "AX", QPoint())
        unbound = [action.text() for action in menus[-1].actions() if action.text()]
    finally:
        page.close_page()
        page.deleteLater()
    assert default[0] == "轨道音量…    G" and default[-1].endswith("    Delete")
    assert rebound[0] == "轨道音量…    Shift+G" and rebound[-1].endswith("    Backspace")
    assert unbound[0] == "轨道音量…    未绑定"


def test_zoom_toast_names_the_current_reset_key(qapp, store):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app.ui_zoom import ZoomController
    window = QWidget()
    controller = ZoomController(qapp, window)
    try:
        controller._show_toast(110)
        default = controller._toast.text()
        reg.save_values({"app.zoom_reset": "Ctrl+9"})
        controller._show_toast(120)
        rebound = controller._toast.text()
        reg.save_values({"app.zoom_reset": ""})
        controller._show_toast(130)
        unbound = controller._toast.text()
    finally:
        native = getattr(controller, "_native", None)
        if native is not None:
            qapp.removeNativeEventFilter(native)
        else:
            qapp.removeEventFilter(controller)
        controller.deleteLater()
        window.deleteLater()
        qapp.processEvents()
    assert default == "界面大小 110%  ·  Ctrl+0 恢复默认"
    assert rebound == "界面大小 120%  ·  Ctrl+9 恢复默认"
    assert unbound == "界面大小 130%  ·  未绑定 恢复默认"


def test_new_key_templates_are_translated():
    from twobyteasr.i18n import translate
    templates = ("已改为「{new}」· {key} 撤销", "人称已切换 · {key} 撤销", "已清除旧画面、字幕和播放状态；按 {key} 可恢复",
                 "空白 · {key} 闭合", "已选择 {track_id} 空白：{key} 同步闭合工程时间；其他轨道有素材或受锁定保护时停止",
                 "轨道音量…    {key}", "点一下：{old} → {new}；右键选择 他 / 她 / 它；按 {key} 切换整条的人称",
                 "界面大小 {percent}%  ·  {key} 恢复默认")
    for language in ("en", "ja", "ko"):
        for template in templates:
            value = translate(template, language)
            assert value != template and "{key}" in value, (language, template)
    # Default keys read as before in English.
    old = {"已改为「{new}」· {key} 撤销": "已改为「{new}」· Ctrl+Z 撤销", "人称已切换 · {key} 撤销": "人称已切换 · Ctrl+Z 撤销",
           "已清除旧画面、字幕和播放状态；按 {key} 可恢复": "已清除旧画面、字幕和播放状态；按 Ctrl+Z 可恢复",
           "轨道音量…    {key}": "轨道音量…    G", "界面大小 {percent}%  ·  {key} 恢复默认": "界面大小 {percent}%  ·  Ctrl+0 恢复默认",
           "点一下：{old} → {new}；右键选择 他 / 她 / 它；按 {key} 切换整条的人称":
               "点一下：{old} → {new}；右键选择 他 / 她 / 它；按 P 切换整条的人称"}
    keys = {"轨道音量…    {key}": "G", "点一下：{old} → {new}；右键选择 他 / 她 / 它；按 {key} 切换整条的人称": "P",
            "界面大小 {percent}%  ·  {key} 恢复默认": "Ctrl+0"}
    for template, before in old.items():
        values = {"new": "她", "old": "他", "percent": 110}
        assert translate(template, "en").format(key=keys.get(template, "Ctrl+Z"), **values) == \
            translate(before, "en").format(**values), template
