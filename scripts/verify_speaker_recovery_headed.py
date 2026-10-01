"""Read-only real MOSS fixture; actual Qt candidate selection and bounded mute preview."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out / "local"), APPDATA=str(out / "roaming"),
                      QT_QPA_PLATFORM="windows", DASHSCOPE_API_KEY="sk-local-test-dummy")
    original_connect = socket.socket.connect
    def local_only(sock, address):
        if address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("external network prohibited in recovery verification")
        return original_connect(sock, address)
    socket.socket.connect = local_only
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from twobyteasr.speaker_recovery import load_candidate_snapshot, candidate_statistics
    from twobyteasr.studio_project import load_project, save_project, save_autosave
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_speaker_manager import SpeakerManagerDialog
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in [args.project, *args.cache.glob("*.json")]}
    project = load_project(args.project)
    snapshot = load_candidate_snapshot(project, args.cache)
    project.generation_metadata["speaker_recovery"] = snapshot
    deliverable = save_project(project, out / "candidate-recovery.2byteproj")
    checks = []
    def check(name, condition, detail=None):
        checks.append(dict(name=name, passed=bool(condition), detail=detail))
        if not condition:
            raise AssertionError(name)
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1400, 880)
    page.volume_slider.setValue(0)
    # No waveform reconstruction is needed to verify this bounded UI task.
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.show()
    dialog = None
    try:
        page.open_project(deliverable, skip_dirty_guard=True)
        deadline = time.monotonic() + 25
        while (page.project is None or page.video._startup_state != "READY") and time.monotonic() < deadline:
            QTest.qWait(50)
        check("media ready", page.project is not None and page.video._startup_state == "READY")
        page.video.set_paused(True)
        page.volume_slider.setValue(0)
        dialog = SpeakerManagerDialog(page)
        dialog.show()
        QTest.qWait(120)
        check("all six raw labels visible", dialog.candidate_table.rowCount() == 6)
        check("no automatic audition", page.video._paused)
        check("confirmation visible", "需要确认" in dialog.candidate_note.text())
        dialog.grab().save(str(out / "speaker-candidates.png"))
        # Explicit simulated choices verify both routes; they are not human identity findings.
        for second in ("S03", "S06"):
            before_s02 = [c for c in page.project.to_dict()["cues"] if c["speaker_id"] == "S02"]
            for label, box in dialog._role_boxes.items():
                wanted = "main" if label in {"S02", second} else "game"
                box.setFocus()
                QTest.keyClick(box, Qt.Key.Key_Home)
                for _ in range(box.findData(wanted)):
                    QTest.keyClick(box, Qt.Key.Key_Down)
            QTest.mouseClick(dialog.rebuild_button, Qt.MouseButton.LeftButton)
            QTest.qWait(120)
            check(f"simulated {second} two independent tracks", set(page.timeline.speaker_ids()) == {"S02", second})
            def content(rows):
                return [{key:value for key,value in row.items() if key not in {"end_ms"}} for row in rows]
            check(f"simulated {second} S02 text/style/start reused", content([c for c in page.project.to_dict()["cues"] if c["speaker_id"] == "S02"]) == content(before_s02))
            save_project(page.project, out / f"SIMULATED-{second}-not-identity.2byteproj")
            auto = save_autosave(page.project, project_path=deliverable, base=out / f"autosave-{second}")
            check(f"{second} autosave reopens two tracks", len(load_project(auto).speakers) == 2)
            page.undo_stack.undo()
            check(f"{second} undo returns one track", page.timeline.speaker_ids() == ["S02"])
            page.undo_stack.redo()
            check(f"{second} redo returns two tracks", set(page.timeline.speaker_ids()) == {"S02", second})
            page.undo_stack.undo()
            dialog._load_candidates()
        # One real audition, muted, bounded by the production timer at 2–4 seconds.
        row = next(i for i in range(6) if dialog.candidate_table.item(i, 0).text() == "S03")
        page._set_speed(4.)
        QTest.mouseClick(dialog.candidate_table.cellWidget(row, 5), Qt.MouseButton.LeftButton)
        check("audition timer 2–4 seconds", 2000 <= dialog._preview_timer.interval() <= 4000)
        check("audition uses natural 1x speed", page.speed_box.currentData() == 1.)
        QTest.qWait(dialog._preview_timer.interval() + 150)
        check("audition automatically pauses", page.video._paused)
        check("audition restores manual rate", page.speed_box.currentData() == 4.)
        check("test muted", page.volume_slider.value() == 0)
        page.grab().save(str(out / "studio-candidate-warning.png"))
        dialog.close()
        dialog = None
        page.undo_stack.setClean()
        check("source files unchanged", all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in hashes.items()))
    finally:
        if dialog is not None:
            dialog.close()
        page.undo_stack.setClean()
        page.close_page()
        QTest.qWait(300)
        (out / "result.json").write_text(json.dumps(dict(checks=checks, statistics=candidate_statistics(snapshot["raw_segments"]),
            human_identity_confirmed=False, original_hashes=hashes, output=str(deliverable)), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == "__main__":
    main()
