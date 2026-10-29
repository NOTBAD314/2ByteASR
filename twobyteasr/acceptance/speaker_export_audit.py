"""Speaker manager cards and the subtitle export dialog in the real app (2026-10-18).

Opt-in source/frozen UI check on a private desktop (scenario ``speaker-export``),
launched by scripts/verify_speaker_export_headed.py with an isolated data root,
a synthetic video with a tone and a three-speaker Filetrans-style project.
Drives the real entries: 说话人管理 and 导出字幕 on the Studio toolbar (both
modal), then the home completion export dialog; exported files are read back.
"""
import json
import os
import traceback
from pathlib import Path

ROWS = [
    ("API_S01", 0.5, 4.0, "大家晚上好，今天继续打艾尔登法环的DLC"),
    ("API_S02", 4.5, 7.0, "你左边那个宝箱还没开"),
    ("API_S01", 7.5, 11.0, "这个Boss第二阶段会跳起来砸地板"),
    ("API_S03", 11.5, 13.0, "获得黄金种子"),
    ("API_S01", 14.0, 18.5, "看到他蹲下就往旁边翻，不要贪刀"),
    ("API_S02", 19.0, 21.5, "这把武器的战技可以打断他"),
    ("API_S01", 22.0, 26.0, "好，我们先去把赐福点开了"),
    ("API_S03", 27.0, 28.5, "圣杯瓶的使用次数增加了"),
    ("API_S01", 30.0, 34.0, "弹幕说这里有个隐藏墙，我打一下试试"),
    ("API_S02", 35.0, 37.0, "等一下等一下，我先补个血"),
    ("API_S01", 38.0, 42.0, "真的有，墙后面是一个新区域"),
    ("API_S03", 43.0, 44.5, "发现新地点：幽影之地"),
    ("API_S01", 46.0, 50.0, "今天就打到这里，谢谢大家"),
    ("API_S02", 51.0, 53.0, "拜拜，明天见"),
]


def make_project(media: Path, target: Path) -> Path:
    """The fixture project the launcher saves before the app starts."""
    from ..projects.speaker_organization import apply_new_project_policy
    from ..projects.studio_project import (
        StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, default_style, save_project,
    )
    from ..recognition.speaker_recovery import candidate_snapshot
    rows = [{"speaker": s, "start": a, "end": b, "text": t, "utterance_id": i} for i, (s, a, b, t) in enumerate(ROWS)]
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=60_000, width=1280, height=720),
        speakers=[StudioSpeaker("API_S01", "说话人 1"), StudioSpeaker("API_S02", "说话人 2"),
                  StudioSpeaker("API_S03", "说话人 3")],
        styles=[default_style()],
        cues=[StudioCue(f"c{i:02d}", round(a * 1000), round(b * 1000), t, speaker_id=s)
              for i, (s, a, b, t) in enumerate(ROWS)],
    )
    snapshot = candidate_snapshot(rows, source="filetrans")
    snapshot["allow_raw_recovery"] = False
    snapshot["processing"] = {"status": "native", "mode": "filetrans", "backend": "filetrans"}
    project.generation_metadata["speaker_recovery"] = snapshot
    apply_new_project_policy(project)
    save_project(project, target)
    return target


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolButton
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..exports import completion_export, studio_export_ui
    from ..i18n import tr

    theme = os.environ.get("TWOBYTEASR_SPEAKER_AUDIT_THEME", "grape")
    output = Path(output)
    project_path = Path(os.environ["TWOBYTEASR_SPEAKER_AUDIT_PROJECT"])
    stem = Path(os.environ["TWOBYTEASR_SPEAKER_AUDIT_MEDIA"]).stem
    result = dict(passed=False, checks=[], theme=theme, values={}, identity=load_build_identity().to_dict(),
                  pid=os.getpid())
    state = {}

    def check(name, value, detail=None):
        result["checks"].append(dict(name=name, passed=bool(value), detail=detail))

    def save():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def shot(name, widget, popup=None):
        image = widget.grab()
        if popup is not None and popup.isVisible():
            offset = popup.mapToGlobal(QPoint(0, 0)) - widget.mapToGlobal(QPoint(0, 0))
            painter = QPainter(image)
            painter.drawPixmap(QPoint(int(offset.x()), int(offset.y())), popup.grab())
            painter.end()
        image.save(str(output / name))
        result.setdefault("screenshots", []).append(name)

    def finish():
        result["passed"] = bool(result["checks"]) and all(item["passed"] for item in result["checks"]) \
            and "error" not in result
        save()
        page = state.get("page")
        if page is not None:
            try:
                page.save()
            except Exception:  # noqa: BLE001
                result["save_error"] = traceback.format_exc()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def later(ms, func):
        def run():
            if state.get("finished"):
                return
            try:
                func()
            except Exception:  # noqa: BLE001
                result["error"] = traceback.format_exc()
                state["finished"] = True
                finish()
        QTimer.singleShot(ms, run)

    def begin():
        check("Windows runtime", os.name == "nt")
        apply_theme(theme)
        window.showNormal()
        window.resize(1700, 1000)
        window.open_studio_project(str(project_path))
        state["waited"] = 0
        later(2000, studio_ready)

    def studio_ready():
        page = getattr(window, "studio_page", None)
        ready = bool(page is not None and page.project is not None and page.video.controller)
        if not ready and state["waited"] < 40:
            state["waited"] += 1
            later(500, studio_ready)
            return
        check("studio opened with media", ready)
        state["page"] = page
        page.video.set_paused(True)
        later(800, open_manager)

    def open_manager():
        later(1800, manager_initial)
        state["page"].speaker_manager_button.click()  # modal; the scheduled steps run inside it
        later(300, after_manager)

    def manager_initial():
        from ..studio.studio_speaker_manager import SpeakerManagerDialog
        dlg = QApplication.activeModalWidget()
        check("manager is the modal dialog", isinstance(dlg, SpeakerManagerDialog), type(dlg).__name__)
        state["dlg"] = dlg
        check("three cards", list(dlg.cards) == ["API_S01", "API_S02", "API_S03"], list(dlg.cards))
        check("pending banner visible", dlg.banner.isVisible() and dlg.banner_text.text().count("3") >= 2,
              dlg.banner_text.text())
        check("pending pills", all(card.pill.isVisible() for card in dlg.cards.values()))
        check("more tools collapsed", not dlg.more_tools.isVisible())
        card = dlg.cards["API_S01"]
        check("excerpt not cut", card.excerpt_label.text() == card.excerpt_label.full_text(), card.excerpt_label.text())
        shot("01-manager.png", dlg)
        card.play_button.click()
        later(900, preview_running)

    def preview_running():
        dlg = state["dlg"]
        card = dlg.cards["API_S01"]
        check("preview playing on card", card.play_button.property("playing") is True and dlg._preview_timer.isActive())
        later(4200, preview_stopped)

    def preview_stopped():
        dlg = state["dlg"]
        check("preview stopped by itself", not dlg._preview_timer.isActive()
              and dlg.cards["API_S01"].play_button.property("playing") is False)
        state["undo_before"] = dlg.page.undo_stack.count()
        dlg.cards["API_S03"].roles.buttons["game"].click()
        later(400, roles_game)

    def roles_game():
        dlg = state["dlg"]
        ids = [s.id for s in dlg.page.project.speakers]
        check("game moves S03 to background", "API_S03" not in ids and "GAME_BACKGROUND" in ids, ids)
        check("S03 card folded", dlg.cards["API_S03"].data.get("present") is False
              and dlg.cards["API_S03"].roles.role() == "game")
        dlg.cards["API_S01"].roles.buttons["main"].click()
        dlg.cards["API_S02"].roles.buttons["main"].click()
        for key, name in (("API_S01", "主播 小乔"), ("API_S02", "阿凯")):
            edit = dlg.cards[key].name_edit
            edit.selectAll()
            edit.insert(name)
            QTest.keyClick(edit, Qt.Key.Key_Return)
        later(500, roles_done)

    def roles_done():
        dlg = state["dlg"]
        names = {s.id: s.name for s in dlg.page.project.speakers}
        check("renamed", names.get("API_S01") == "主播 小乔" and names.get("API_S02") == "阿凯", names)
        check("banner gone after all confirmed", not dlg.banner.isVisible())
        check("one undo step per action", dlg.page.undo_stack.count() - state["undo_before"] == 5)
        check("timeline tracks follow", set(dlg.page.timeline.speaker_ids()) == {"API_S01", "API_S02", "GAME_BACKGROUND"},
              dlg.page.timeline.speaker_ids())
        shot("02-roles-and-names.png", dlg)
        later(500, lambda: (later(600, color_menu), dlg.cards["API_S02"].swatch.click()))

    def color_menu():
        dlg = state["dlg"]
        popup = QApplication.activePopupWidget()
        check("color menu open", popup is not None)
        shot("03-color-menu.png", dlg, popup)
        choices = popup.findChildren(QToolButton, "speakerSwatchChoice")
        state["picked"] = choices[2].toolTip()
        choices[2].click()
        later(500, color_done)

    def color_done():
        dlg = state["dlg"]
        speaker = next(s for s in dlg.page.project.speakers if s.id == "API_S02")
        check("color applied at once", speaker.color == state["picked"], speaker.color)
        later(400, lambda: (later(600, more_menu), dlg.cards["API_S01"].more_button.click()))

    def more_menu():
        dlg = state["dlg"]
        popup = QApplication.activePopupWidget()
        check("more menu open", popup is not None)
        shot("04-more-menu.png", dlg, popup)
        popup.close()
        later(300, multi_mode)

    def multi_mode():
        dlg = state["dlg"]
        dlg.multi_button.click()
        dlg.more_toggle.click()
        dlg.cards["API_S02"].select_check.setChecked(True)
        later(500, multi_shot)

    def multi_shot():
        dlg = state["dlg"]
        check("batch bar visible", dlg.batch_bar.isVisible() and dlg.more_tools.isVisible())
        check("selection summary", dlg.selection_summary.text() == tr("已选 {value0} 人 / {count} 条字幕", value0=1, count=4),
              dlg.selection_summary.text())
        shot("05-multi-and-tools.png", dlg)
        dlg.multi_button.click()
        dlg.more_toggle.click()
        later(300, lambda: dlg.done_button.click())

    def after_manager():
        page = state["page"]
        modal = QApplication.activeModalWidget()
        check("manager closed", not isinstance(modal, type(state["dlg"])), type(modal).__name__)
        check("toolbar label settled", page.speaker_manager_button.text() == tr("说话人管理"), page.speaker_manager_button.text())
        later(600, open_export)

    def open_export():
        custom = output / "exports-custom"
        custom.mkdir(exist_ok=True)
        studio_export_ui.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(custom))
        later(1500, export_dialog)
        state["page"].studio_export_button.click()  # modal
        later(300, after_export)

    def export_dialog():
        dlg = QApplication.activeModalWidget()
        check("export dialog is modal", type(dlg).__name__ == "SubtitleExportDialog", type(dlg).__name__)
        state["export"] = dlg
        for name, card in dlg.format_checks.items():
            if card.isChecked() != (name in {"srt", "ass", "txt"}):
                card.click()
        dlg.speaker_modes["both"].click()
        dlg.destination_modes["source"].click()
        later(400, export_shot)

    def export_shot():
        dlg = state["export"]
        check("preview lists 12 files", dlg.file_list.header.text() == tr("会产生 {count} 个文件：", count=12)
              and len(dlg.file_list.names()) == 8 and dlg.file_list.rows[-1].text() == tr("…另外 {count} 个", count=4),
              dlg.file_list.header.text())
        result["values"]["export_button"] = dlg.export_button.text()
        shot("06-export.png", dlg)
        dlg.destination_modes["custom"].click()
        later(400, export_custom)

    def export_custom():
        dlg = state["export"]
        check("custom path shown", dlg.path_row.path_label.path() == str(output / "exports-custom"),
              dlg.path_row.path_label.path())
        dlg.export_button.click()
        later(700, export_done)

    def export_done():
        dlg = state["export"]
        check("done page", dlg.pages.currentWidget() is dlg.done_page)
        files = [a.path for a in dlg.artifacts]
        result["values"]["exported"] = [p.name for p in files]
        check("twelve files written", len(files) == 12 and all(p.is_file() for p in files), len(files))
        combined = output / "exports-custom" / f"{stem}.srt"
        text = combined.read_text(encoding="utf-8-sig") if combined.is_file() else ""
        check("combined srt read back", text.count("-->") == len(ROWS) and "大家晚上好" in text)
        host = output / "exports-custom" / f"{stem}_主播_小乔.srt"
        host_text = host.read_text(encoding="utf-8-sig") if host.is_file() else ""
        check("per-speaker srt read back", host_text.count("-->") == 7 and "阿凯" not in host_text)
        shot("07-export-done.png", dlg)
        dlg.done_button.click()

    def after_export():
        modal = QApplication.activeModalWidget()
        check("export dialog closed", type(modal).__name__ != "SubtitleExportDialog", type(modal).__name__)
        later(500, completion)

    def completion():
        out = output / "exports-completion"
        out.mkdir(exist_ok=True)
        completion_export.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out))
        dlg = completion_export.CompletionExportDialog(state["page"].project, stem, window)
        state["completion"] = dlg
        dlg.show()
        later(800, completion_shot)

    def completion_shot():
        dlg = state["completion"]
        check("completion chips", dlg.speakers.count() == 3, dlg.speakers.count())
        shot("08-completion.png", dlg)
        dlg.speakers.item(2).setCheckState(Qt.CheckState.Unchecked)
        dlg.mode.setCurrentIndex(dlg.mode.findData("per_speaker"))
        dlg.export_button.click()
        files = [a.path for a in dlg.artifacts]
        result["values"]["completion_exported"] = [p.name for p in files]
        check("completion export read back", len(files) == 2 and all(
            p.read_text(encoding="utf-8-sig").count("-->") > 0 for p in files), len(files))
        dlg.deleteLater()
        state["finished"] = True
        later_finish()

    def later_finish():
        QTimer.singleShot(300, finish)

    def shutdown():
        result["gui_shutdown"] = True
        save()

    QApplication.instance().aboutToQuit.connect(shutdown)
    later(2500, begin)
