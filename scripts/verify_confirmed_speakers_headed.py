"""Real mouse application of the user-confirmed S02/S03 pair, with isolated IO."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import socket
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    assert out.is_relative_to(ROOT / "tmp")
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out / "local"), APPDATA=str(out / "roaming"),
                      QT_QPA_PLATFORM="windows", DASHSCOPE_API_KEY="sk-local-test-dummy")
    connect = socket.socket.connect
    def local_only(sock, address):
        if address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("external network prohibited")
        return connect(sock, address)
    socket.socket.connect = local_only
    from PySide6.QtCore import Qt, QTimer, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from twobyteasr.speaker_recovery import load_candidate_snapshot
    from twobyteasr.studio_project import load_project, save_project
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_speaker_manager import SpeakerManagerDialog
    from twobyteasr.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in [args.project, *args.cache.glob("*.json")]}
    project = load_project(args.project)
    snapshot = load_candidate_snapshot(project, args.cache)
    project.generation_metadata["speaker_recovery"] = snapshot
    path = save_project(project, out / "confirmed-current-project.2byteproj")
    empty = copy.deepcopy(project)
    empty.cues = []
    empty.speakers = []
    empty.project_id += "-reopen-switch"
    other_path = save_project(empty, out / "reopen-switch.2byteproj")
    result = dict(passed=False, checks=[], original_hashes=hashes, human_confirmed_raw_labels=["S02", "S03"],
                  before=dict(tracks=len(project.speakers), cues=len(project.cues)), current_project=str(path), model_requests=0)
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1480, 930)
    page._generate_waveform = lambda *_a, **_k: None
    page.volume_slider.setValue(0)
    page.show()
    def check(name, condition, detail=None):
        result["checks"].append(dict(name=name, passed=bool(condition), detail=detail))
        if not condition:
            raise AssertionError(name)
    def wait_for(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        return bool(predicate())
    def shot(name, widget=page):
        widget.raise_()
        QTest.qWait(70)
        pos = widget.mapToGlobal(QPoint(0, 0))
        pix = widget.screen().grabWindow(0, pos.x(), pos.y(), widget.width(), widget.height())
        check(name + " real screen captured", not pix.isNull())
        pix.save(str(out / (name + ".png")))
    errors = []
    def click(widget, pos=None):
        pos = widget.rect().center() if pos is None else pos
        window = widget.window()
        point = widget.mapTo(window, pos)
        QTest.mouseMove(window.windowHandle(), point)
        QTest.qWait(25)
        QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
    try:
        page.open_project(path, skip_dirty_guard=True)
        check("media ready", wait_for(lambda: page.project is not None and page.video._startup_state == "READY", 25))
        page.video.set_paused(True)
        page.volume_slider.setValue(0)
        current_identity = id(page.project)
        before_text = {c.id:c.text for c in page.project.cues}
        shot("before-studio")
        def choose_and_apply():
            dialog = QApplication.activeModalWidget()
            try:
                check("real manager button opened existing dialog", isinstance(dialog, SpeakerManagerDialog))
                shot("before-manager", dialog)
                for raw in ("S02", "S03"):
                    box = dialog._role_boxes[raw]
                    click(box)
                    QTest.qWait(60)
                    view = box.view()
                    idx = box.model().index(box.findData("main"), 0)
                    view.scrollTo(idx)
                    check(f"{raw} popup visible", view.isVisible())
                    click(view.viewport(), view.visualRect(idx).center())
                    QTest.qWait(50)
                    check(f"{raw} dropdown selected main by mouse", box.currentData() == "main")
                check("S06 untouched and unconfirmed", dialog._role_boxes["S06"].currentData() == "unconfirmed")
                check("unapplied visible separately", "有未应用修改" in dialog.apply_summary.text() and "待应用" in page.speaker_manager_button.text())
                check("preview predicts 2 tracks 49 cues", "2 条轨道 / 49 cue" in dialog.apply_summary.text())
                shot("pending-manager", dialog)
                QTest.mouseClick(dialog.rebuild_button, Qt.MouseButton.LeftButton)
                check("progress visible", "正在应用" in dialog.rebuild_button.text())
                check("apply completes", wait_for(lambda: not dialog._applying))
                check("current project identity unchanged", id(page.project) == current_identity and page.project_path == path)
                check("success result visible", "应用成功" in dialog.candidate_note.text(), dialog.candidate_note.text())
                check("current timeline has real S02 S03 tracks", set(page.timeline.speaker_ids()) == {"S02", "S03"})
                check("current list contains both speakers", {page.cue_model.cue_at(i).speaker_id for i in range(page.cue_model.rowCount())} == {"S02", "S03"})
                check("status cleared", "待" not in page.speaker_manager_button.text())
                check("old text preserved", all(next(c for c in page.project.cues if c.id == key).text == text for key,text in before_text.items()))
                check("separate raw display mapping", page.project.generation_metadata["speaker_recovery"]["display_labels"] == {"S02":"S01", "S03":"S02"})
                check("raw MOSS immutable", page.project.generation_metadata["speaker_recovery"]["raw_segments"] == snapshot["raw_segments"])
                shot("applied-manager", dialog)
            except Exception:
                errors.append(traceback.format_exc())
            finally:
                if dialog:
                    dialog.accept()
        QTimer.singleShot(200, choose_and_apply)
        QTest.mouseClick(page.speaker_manager_button, Qt.MouseButton.LeftButton)
        if errors:
            raise AssertionError(errors[0])
        page.timeline.set_visible_window(0, page.project.media.duration_ms)
        page.select_cue(next(c.id for c in page.project.cues if c.speaker_id == "S03"))
        page._seek(10.8)
        QTest.qWait(300)
        shot("dual-tracks-current-studio")
        result["after"] = dict(tracks=len(page.project.speakers), cues=len(page.project.cues),
                               raw_cue_counts={raw:sum(c.speaker_id == raw for c in page.project.cues) for raw in ("S02", "S03")},
                               display_labels=page.project.generation_metadata["speaker_recovery"]["display_labels"])
        page.undo_stack.undo()
        check("undo restores original single track", page.timeline.speaker_ids() == ["S02"])
        page.undo_stack.redo()
        check("redo restores same map and two tracks", {s.id:s.name for s in page.project.speakers} == {"S02":"S01", "S03":"S02"})
        QTest.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
        check("actual save button writes dual project", len(load_project(path).speakers) == 2)
        original_instance = page.project
        page.open_project(other_path, skip_dirty_guard=True)
        check("switch to another project completes", wait_for(lambda: page.project_path == other_path and page.project is not original_instance))
        page.open_project(path, skip_dirty_guard=True)
        check("disk reopen replaces object", wait_for(lambda: page.project_path == path and page.project is not original_instance))
        check("reopened two tracks and stable map", set(page.timeline.speaker_ids()) == {"S02", "S03"} and
              {s.id:s.name for s in page.project.speakers} == {"S02":"S01", "S03":"S02"})
        artifacts = export_subtitle_artifacts(page.project, out / "subtitles", "双主播", SubtitleExportOptions(speaker_mode="per_speaker"))
        check("split SRT uses display labels", {a.speaker_id:a.path.name for a in artifacts} == {"S02":"双主播_S01.srt", "S03":"双主播_S02.srt"})
        check("source project and caches unchanged", all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p,h in hashes.items()))
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        page.grab().save(str(out / "failure.png"))
    finally:
        page.video.set_paused(True)
        page.undo_stack.setClean()
        page.close_page()
        QTest.qWait(200)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
