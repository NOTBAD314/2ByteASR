from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.audio_engine import StudioAudioEngine


def _wait(app: QApplication, predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    app.processEvents()
    return bool(predicate())


def run(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    fixture = output / "440hz-4s.wav"
    generated = subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
            "-c:a", "pcm_s16le", str(fixture),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if generated.returncode != 0:
        raise RuntimeError(generated.stderr[-500:] or "failed to create sine fixture")

    app = QApplication.instance() or QApplication([])
    engine = StudioAudioEngine(ffmpeg_path=ffmpeg)
    layer = {
        "track_id": "A2",
        "source_path": str(fixture),
        "source_ms": 0,
        "playback_rate": 1.0,
    }
    engine.synchronize(
        layer,
        audible=True,
        paused=False,
        transport_rate=1.0,
        volume=0.25,
    )
    started = _wait(
        app,
        lambda: (
            int(engine.telemetry_snapshot().get("sink_consumed_bytes", 0)) > 16_384
            and float(engine.telemetry_snapshot().get("sink_consumed_rms", 0.0)) > 0.01
        ),
        8.0,
    )
    playing = engine.telemetry_snapshot()

    engine.synchronize(
        dict(layer, source_ms=int(playing.get("estimated_source_ms", 0))),
        audible=True,
        paused=True,
        transport_rate=1.0,
        volume=0.25,
    )
    _wait(app, lambda: engine.telemetry_snapshot().get("paused") is True, 2.0)
    paused = engine.telemetry_snapshot()

    engine.synchronize(
        dict(layer, source_ms=1_000),
        audible=True,
        paused=False,
        transport_rate=1.0,
        volume=0.25,
    )
    resumed = _wait(
        app,
        lambda: (
            engine.telemetry_snapshot().get("paused") is False
            and int(engine.telemetry_snapshot().get("sink_consumed_bytes", 0)) > 16_384
        ),
        8.0,
    )
    after_seek = engine.telemetry_snapshot()

    rapid_positions = [((index * 173) % 2_500) for index in range(20)]
    for source_ms in rapid_positions:
        engine.synchronize(
            dict(layer, source_ms=source_ms),
            audible=True,
            paused=False,
            transport_rate=1.0,
            volume=0.25,
        )
        app.processEvents()
        time.sleep(0.01)
    final_source_ms = rapid_positions[-1]
    rapid_seek_recovered = _wait(
        app,
        lambda: (
            int(engine.telemetry_snapshot().get("source_start_ms", -1)) == final_source_ms
            and int(engine.telemetry_snapshot().get("sink_consumed_bytes", 0)) > 16_384
            and float(engine.telemetry_snapshot().get("sink_consumed_rms", 0.0)) > 0.01
        ),
        8.0,
    )
    after_rapid_seek = engine.telemetry_snapshot()
    engine.request_shutdown()
    shutdown = engine.wait_for_shutdown(3.0)
    app.processEvents()

    result = {
        "fixture": str(fixture),
        "generated": True,
        "started": started,
        "resumed_after_seek": resumed,
        "rapid_seek_x20_recovered": rapid_seek_recovered,
        "shutdown": shutdown,
        "playing": playing,
        "paused": paused,
        "after_seek": after_seek,
        "after_rapid_seek": after_rapid_seek,
        "verified": bool(
            started
            and resumed
            and rapid_seek_recovered
            and shutdown
            and int(playing.get("decoded_bytes", 0)) > 0
            and int(playing.get("sink_consumed_bytes", 0)) > 0
            and float(playing.get("decoded_rms", 0.0)) > 0.01
            and float(playing.get("sink_consumed_rms", 0.0)) > 0.01
            and bool(playing.get("output_format"))
        ),
        "evidence_scope": (
            "real QAudioSink consumed non-silent PCM; no Windows loopback capture, "
            "therefore this does not by itself claim human audibility"
        ),
    }
    (output / "audio-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
