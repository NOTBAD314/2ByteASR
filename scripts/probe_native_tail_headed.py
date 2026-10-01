"""High-cadence probe: when exactly does mpv clear the native subtitle
relative to cue end?

For several native cues, plays through the last 900ms and samples
sub-text/sub-start/video-frame pts every 25ms. Reports the playhead time the
text cleared vs cue.end_ms.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！"
    r"\2026-08-28 19-23-22 一起看绝区零前瞻！.2byteproj"
)
WORK = ROOT / "tmp" / "native_tail_probe"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage
import os

# native default-style cues with exact project spans
TARGETS = [
    ("5", 13817, 14717),
    ("6", 15883, 17033),
    ("9", 24417, 25417),
    ("10", 28217, 29517),
    ("11", 29517, 33833),
    ("12", 33833, 34733),
]


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for entry in WORK.iterdir():
        entry.unlink() if entry.is_file() else shutil.rmtree(entry)
    project_copy = WORK / "probe.2byteproj"
    shutil.copy2(SOURCE_PROJECT, project_copy)

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    page.open_project(project_copy)

    results: list[dict] = []
    index_box = [0]

    def probe_cue():
        if index_box[0] >= len(TARGETS):
            finish()
            return
        cue_id, start_ms, end_ms = TARGETS[index_box[0]]
        records: list[dict] = []

        def sample_once():
            controller = page.video.controller
            entry = {"t_ms": int(page.timeline.playhead_ms), "text": ""}
            if controller is not None and controller.running:
                try:
                    entry["text"] = str(controller.get_property("sub-text", "") or "")[:24]
                except RuntimeError:
                    entry["text"] = "ERR"
            records.append(entry)

        def begin():
            page._seek((end_ms - 1000) / 1000.0)
            page._toggle_playback()
            deadline = time.monotonic() + 6.0

            def tick():
                sample_once()
                if page.timeline.playhead_ms > end_ms + 150 or time.monotonic() > deadline:
                    page._toggle_playback()
                    evaluate(records, cue_id, end_ms)
                    index_box[0] += 1
                    QTimer.singleShot(500, probe_cue)
                    return
                QTimer.singleShot(25, tick)

            tick()

        QTimer.singleShot(300, begin)

    def evaluate(records, cue_id, end_ms):
        last_text = None
        clear_t = None
        for entry in records:
            if entry["text"].strip():
                last_text = entry["t_ms"]
            elif clear_t is None and last_text is not None:
                clear_t = entry["t_ms"]
        after = [e for e in records if e["t_ms"] > end_ms]
        early = clear_t is not None and clear_t < end_ms - 40
        print(f"[TAIL] cue {cue_id} end={end_ms} last_text_t={last_text} clear_t={clear_t} "
              f"clear_vs_end={None if clear_t is None else clear_t - end_ms}ms "
              f"early={early} samples={len(records)}", flush=True)
        results.append({"cue": cue_id, "end": end_ms, "clear_t": clear_t, "early": early})

    def finish():
        early_count = sum(1 for r in results if r["early"])
        print(f"[TAIL] summary early_clear={early_count}/{len(results)}", flush=True)
        page.close_page()
        app.quit()

    QTimer.singleShot(900, probe_cue)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
