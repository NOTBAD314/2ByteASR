"""Real X11 pixels, playback clock and PulseAudio evidence for the owned fixture."""
from __future__ import annotations
import array
import json
import math
import subprocess
import time

def preserve_preview(page, output, label, pump, check):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from twobyteasr.macos_desktop_evidence import image_colour_observation

    canvas = page.video
    def raster():
        return canvas.screen().grabWindow(int(canvas.winId())).toImage()
    image = raster()
    deadline = time.monotonic() + 8
    while image_colour_observation(image)["colour_fraction"] <= .10 and time.monotonic() < deadline:
        pump(.15)
        image = raster()
    filename = f"preview-{label}-x11.png"
    image.save(str(output / filename))
    record = {"x11": image_colour_observation(image), "file": filename,
              "visible": canvas.isVisible(), "actor": canvas.controller.actor_status()}
    record["passed"] = record["visible"] and record["x11"]["colour_fraction"] > .10
    (output / f"preview-{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")
    check("actual X11 decoded video " + label, record["passed"])
    if label != "ready":
        return record

    page._seek(.25)
    deadline = time.monotonic() + 12
    while (canvas._playback_clock.exact_seek_pending or not page._playback_buffers_ready()) and time.monotonic() < deadline:
        pump(.1)
    record["seek_ready"] = page._playback_buffers_ready()
    before = int(page.timeline.playhead_ms)
    first = raster().scaled(160, 90, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    pcm = output / "preview-pulse.s16le"
    with pcm.open("wb") as stream:
        capture = subprocess.Popen(["parec", "--device=output.monitor", "--format=s16le",
                                    "--rate=16000", "--channels=1"], stdout=stream, stderr=subprocess.PIPE)
        try:
            pump(.2)
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            started = time.monotonic()
            deadline = started + 12
            while int(page.timeline.playhead_ms) < before + 500 and time.monotonic() < deadline:
                pump(.1)
            pump(1.5)
            after = int(page.timeline.playhead_ms)
            elapsed = time.monotonic() - started
            audio = page.audio_engine.telemetry_snapshot()
            second = raster().scaled(160, 90, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            canvas.screen().grabWindow(0).save(str(output / "desktop-playing.png"))
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            pump(.3)
        finally:
            capture.terminate()
            _, stderr = capture.communicate(timeout=5)
    values = array.array("h", pcm.read_bytes())
    rms = math.sqrt(sum((v / 32768) ** 2 for v in values) / max(1, len(values)))
    record["playback"] = {"before_ms": before, "after_ms": after, "elapsed": elapsed,
                          "frame_changed": first != second, "pulse_samples": len(values),
                          "pulse_rms": rms, "pulse_error": stderr.decode("utf8", errors="replace"),
                          "audio": audio}
    record["passed"] = bool(record["passed"] and after - before > 500 and first != second
                            and audio.get("sink_consumed_bytes", 0) > 0 and rms > .00001)
    (output / f"preview-{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")
    check("video playback advances and decoded frame changes", after - before > 500 and first != second)
    check("Studio audio reaches the streaming PulseAudio sink", audio.get("sink_consumed_bytes", 0) > 0 and rms > .00001)
    page._seek(before / 1000)
    pump(.4)
    return record
