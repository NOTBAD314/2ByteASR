"""Profile the secondary QtMultimedia decoder without the Studio shell."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.secondary_video import SecondaryVideoSource  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument(
        "--mode", choices=(
            "paused", "single-playing", "clock-playing",
            "audio-single-playing", "audio-clock-playing", "audio-only-playing",
        ), required=True,
    )
    parser.add_argument("--seconds", type=float, default=12.0)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    source = SecondaryVideoSource()
    process = psutil.Process(os.getpid())
    started = time.perf_counter()
    samples = []
    initial_request_sent = False

    source.prepare(str(args.media.resolve()))

    def request() -> None:
        nonlocal initial_request_sent
        elapsed = time.perf_counter() - started
        audio_enabled = args.mode.startswith("audio-")
        if args.mode == "paused":
            source.request_frame(1_000, paused=True, seek=True)
        elif args.mode in {"single-playing", "audio-single-playing", "audio-only-playing"}:
            if not initial_request_sent:
                source.request_frame(
                    1_000, paused=False, seek=False,
                    volume=1.0 if audio_enabled else 0.0,
                    audio_output_enabled=audio_enabled,
                    video_output_enabled=args.mode != "audio-only-playing",
                )
                initial_request_sent = True
        else:
            source.request_frame(
                1_000 + round(elapsed * 1000), paused=False, seek=False,
                volume=1.0 if audio_enabled else 0.0,
                audio_output_enabled=audio_enabled,
            )

    def sample() -> None:
        memory = process.memory_info()
        samples.append({
            "elapsed_s": round(time.perf_counter() - started, 3),
            "rss_bytes": int(memory.rss),
            "private_bytes": int(getattr(memory, "private", 0)),
            "threads": process.num_threads(),
            "generation": source.generation,
            "delivered_frames": len(source.samples),
            "pts_ms": source.pts_ms,
            "state": source.state,
            "playback_state": source.playback_state,
        })

    request_timer = QTimer()
    request_timer.setInterval(16)
    request_timer.timeout.connect(request)
    request_timer.start()
    sample_timer = QTimer()
    sample_timer.setInterval(1_000)
    sample_timer.timeout.connect(sample)
    sample_timer.start()

    def finish() -> None:
        request_timer.stop()
        sample_timer.stop()
        sample()
        source.release()
        payload = {
            "mode": args.mode,
            "media": str(args.media.resolve()),
            "samples": samples,
            "peak_rss_bytes": max(item["rss_bytes"] for item in samples),
            "peak_private_bytes": max(item["private_bytes"] for item in samples),
            "shutdown_acknowledged": source.shutdown_acknowledged,
            "thread_stopped": source.thread_stopped,
            "thread_forced_termination": source.thread_forced_termination,
            "shutdown_player_polls": source._worker._shutdown_polls,
            "shutdown_player_status": source._worker._shutdown_final_status,
            "shutdown_on_worker_thread": source._worker._shutdown_on_worker_thread,
        }
        source.deleteLater()
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        QTimer.singleShot(500, app.quit)

    QTimer.singleShot(max(1, round(args.seconds * 1000)), finish)
    exit_code = app.exec()
    print("PROFILE_APP_EXEC_RETURNED", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
