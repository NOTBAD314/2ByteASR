"""进入工程全链计时（2026-09-19 轮）：真实工程副本 + 真实 mpv。

- open_project → on_ready（就绪门关闭）
- 主线程停顿窗口（>80ms tick gap）
- 大 JSON 主线程解析探针（json.loads 耗时>150ms 记录调用方与规模）
- 首帧/首音频里程碑（GLOBAL_STUDIO_TRACE）
- 进程内二次进入对比；增量落盘防中途崩溃丢数据

用法：.venv/Scripts/python.exe scripts/verify_entry_timing_headed.py [--project <.2byteproj>] [--runs N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_PROJECT = ROOT / "tmp" / "entry-round-20260919" / "proj" / "未命名工程.2byteproj"
OUT = ROOT / "tmp" / "entry-round-20260919"


def _pump(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


class StallDetector:
    def __init__(self, threshold_ms=80.0):
        from PySide6.QtCore import QTimer, Qt

        self.threshold_ms = float(threshold_ms)
        self.gaps: list[dict] = []
        self._last = time.perf_counter()
        self._t0 = self._last
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        delta_ms = (now - self._last) * 1000.0
        if delta_ms > self.threshold_ms:
            self.gaps.append({"at_ms": round((now - self._t0) * 1000.0, 1), "gap_ms": round(delta_ms, 1)})
        self._last = now

    def start(self):
        self._last = time.perf_counter()
        self._t0 = self._last
        self._timer.start()

    def stop(self):
        self._timer.stop()


class JsonProbe:
    """记录主线程上 >150ms 的 json 解析（调用方+载荷规模）。"""

    def __init__(self, threshold_ms=150.0):
        self.threshold_ms = threshold_ms
        self.hits: list[dict] = []
        self._orig_loads = json.loads
        self._orig_load = json.load

    def install(self):
        probe = self

        def loads(s, *a, **k):
            t0 = time.perf_counter()
            try:
                return probe._orig_loads(s, *a, **k)
            finally:
                probe._record(t0, s if isinstance(s, str) else "", caller="json.loads")

        def load(fp, *a, **k):
            t0 = time.perf_counter()
            try:
                return probe._orig_load(fp, *a, **k)
            finally:
                name = getattr(fp, "name", "")
                probe._record(t0, name, caller="json.load")

        json.loads = loads
        json.load = load

    def _record(self, t0, hint, caller):
        ms = (time.perf_counter() - t0) * 1000.0
        if ms >= self.threshold_ms:
            frames = traceback.extract_stack(limit=6)[:-1]
            path = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(frames))
            self.hits.append({
                "ms": round(ms, 1),
                "hint": str(hint)[:180],
                "caller": caller,
                "stack": path,
            })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(DEFAULT_PROJECT))
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.runtime_trace import GLOBAL_STUDIO_TRACE

    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    _pump(app, 1.0)

    project_path = Path(args.project).resolve()
    stall = StallDetector()
    probe = JsonProbe()
    probe.install()

    report_path = OUT / "entry-timing.json"
    report = {"project": str(project_path), "runs": []}
    for run_index in range(1, args.runs + 1):
        label = "cold-1" if run_index == 1 else f"reopen-inproc-{run_index}"
        ready = {"done": False, "t": None}
        stall.gaps.clear()
        probe.hits.clear()
        stall.start()
        t0 = time.perf_counter()

        def on_ready():
            ready["done"] = True
            ready["t"] = (time.perf_counter() - t0) * 1000.0

        page.open_project(str(project_path), on_ready=on_ready)
        # 泵到 ready 后再泵 12s：覆盖恢复播放头/首音频/波形
        waited = 0.0
        while waited < 60:
            _pump(app, 0.1)
            waited += 0.1
            if ready["done"] and waited >= 14.0:
                break
        stall.stop()

        records = [dict(r) for r in GLOBAL_STUDIO_TRACE.recent()]
        milestones = {}
        for r in records:
            milestones.setdefault(r.get("event", ""), r)
        run_result = {
            "label": label,
            "ready_ms": ready["t"],
            "stalls": list(stall.gaps),
            "json_hits": list(probe.hits),
            "ready_gate": milestones.get("STUDIO_READY_GATE", {}).get("stages_ms"),
            "first_frame_stamp": milestones.get("MPV_FIRST_FRAME", {}).get("stamp"),
            "first_audio_stamp": milestones.get("MPV_FIRST_AUDIO", {}).get("stamp"),
            "qc_scan": milestones.get("QC_SCAN_FINISHED", {}).get("elapsed_ms"),
        }
        report["runs"].append(run_result)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[RUN {label}] ready={ready['t'] and round(ready['t'])}ms stalls={len(stall.gaps)} json={len(probe.hits)}", flush=True)

        if run_index < args.runs:
            page.close_page()
            _pump(app, 2.0)

    (OUT / "trace-records.json").write_text(
        json.dumps([dict(r) for r in GLOBAL_STUDIO_TRACE.recent()], ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
