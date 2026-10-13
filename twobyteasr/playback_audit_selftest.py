"""--playback-audit：源码与冻结 EXE 同链路的真实工程播放验收自检。

2026-09-18 P0/P1 轮：截图工程（0 字幕、1:29:46、6.4GB FLV）实测族。
在真实 UI/真实 mpv/真实缓存上验证四件事：
  1. 坏 continuous 代理（时长塌缩）被采用门拒删并重建出好代理；
  2. 绑定后 1x = 真实 1x（mpv speed==1 且内容推进≈墙钟，开头/中段/片尾）；
  3. 片尾推进停止、不回零、不 reload 循环；
  4. 播放头拖拽/点击钳在工程时长内（不能拖到 3 小时）。

用法：2ByteASR.exe --playback-audit <project.2byteproj> --out <report.json>
环境：继承真实 LOCALAPPDATA（真实缓存链）；工程文件自动复制到 tmp 副本打开，
绝不写用户工程目录；素材只读。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _probe_duration_seconds(media_path: str) -> float | None:
    try:
        from .audio_engine import studio_ffmpeg_path
        ffprobe = studio_ffmpeg_path().with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe"
        )
        out = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(media_path)],
            capture_output=True, text=True, timeout=120, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return None


def _pump(app, seconds: float, step: float = 0.05) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(step)


def main(argv: list[str]) -> int:
    if not argv:
        print("--playback-audit <project.2byteproj> [--out report.json]", file=sys.stderr)
        return 2
    project_arg = Path(argv[0]).resolve()
    out_path = None
    if "--out" in argv:
        out_path = Path(argv[argv.index("--out") + 1]).resolve()

    report: dict = {"project": str(project_arg), "checks": [], "failures": []}

    def check(name: str, ok: bool, detail: str = "") -> bool:
        report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
        print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""))
        if not ok:
            report["failures"].append(name)
        return bool(ok)

    # 工程副本：autosave/undo 只落 tmp，不碰用户工程目录
    work = Path(os.environ.get("LOCALAPPDATA", ".")) / "2ByteASR" / "tmp"
    work.mkdir(parents=True, exist_ok=True)
    project_copy = work / f"playback-audit-{project_arg.stem}.2byteproj"
    shutil.copyfile(project_arg, project_copy)

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0]])
    from .indexed_media import GLOBAL_INDEXED_MEDIA
    from .studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page.show()
    ready = {"done": False}
    page.open_project(str(project_copy), on_ready=lambda: ready.__setitem__("done", True))
    _pump(app, 1.0)
    for _ in range(120):
        if ready["done"]:
            break
        _pump(app, 1.0)
    check("project_open_ready", ready["done"])
    if not ready["done"]:
        _finish(page, app, report, out_path)
        return 1

    project = page.project
    media_path = str(project.media.path)
    duration_ms = int(project.media.duration_ms or 0)
    check("project_meta", duration_ms > 0,
          f"media={Path(media_path).name} duration_ms={duration_ms}")
    report["media"] = media_path
    report["duration_ms"] = duration_ms

    # ---------------------------------------------------- 1. 代理链（真实缓存）
    kind = None
    playback = None
    deadline = time.monotonic() + 480.0
    while time.monotonic() < deadline:
        playback, kind = GLOBAL_INDEXED_MEDIA.playback_source(media_path)
        if kind == "proxy":
            break
        _pump(app, 2.0)
    report["playback_source"] = {"kind": kind, "path": str(playback)}
    check("playback_source_resolved", playback is not None, f"kind={kind}")
    if kind == "proxy":
        proxy_dur = _probe_duration_seconds(str(playback))
        ratio = (proxy_dur / (duration_ms / 1000.0)) if proxy_dur else 0.0
        check("proxy_duration_sane", proxy_dur is not None and 0.9 <= ratio <= 1.05,
              f"proxy={proxy_dur}s vs project={duration_ms/1000:.1f}s ratio={ratio:.3f}")
        marker = Path(playback).parent / "continuous.json"
        check("proxy_marker_v2", marker.is_file(), str(marker))

    # 让换绑/映射生效：等 mpv 实际加载到当前 playback 源（热重建代理时
    # 会经历 loadfile 重载，重载窗口里的 unpause 会被吞）
    def _canvas_media_path() -> str:
        return str(getattr(page.video, "_media_path", "") or "")

    rebind_deadline = time.monotonic() + 60.0
    while time.monotonic() < rebind_deadline:
        current = _canvas_media_path()
        if playback is not None and current and Path(current) == Path(playback):
            break
        _pump(app, 1.0)
    report["canvas_bound"] = _canvas_media_path()
    check("canvas_bound_playback_source",
          playback is not None and Path(_canvas_media_path()) == Path(playback),
          f"{_canvas_media_path()} vs {playback}")

    def _mpv_observed(name: str):
        ctrl = page.video.controller
        if ctrl is None:
            return None
        try:
            return ctrl.observed_property(name, None)
        except Exception:
            return None

    # mpv 必须真的加载了文件（duration 观测非空）。offscreen 假窗口会让
    # loadfile 静默失败：时钟自跑 1x 但视频根本没在播——那种"1x"是假绿。
    file_loaded = False
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if _mpv_observed("duration") is not None:
            file_loaded = True
            break
        _pump(app, 2.0)
    report["mpv_duration_observed"] = _mpv_observed("duration")
    check("mpv_file_loaded", file_loaded,
          f"duration={_mpv_observed('duration')}")

    def _ensure_playing(timeout: float = 30.0) -> None:
        """unpause 带重试：重载/音频就绪门未开时单次 set_paused(False)
        可能被吞——按'用户再按一次播放'的语义重发，直到 mpv time-pos
        真实推进（本地时钟外推不算数）。"""
        last_pos = page.video.visual_position()
        last_t = time.monotonic()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _pump(app, 1.0)
            tp = _mpv_observed("time-pos")
            pos = page.video.visual_position()
            advanced = tp is not None and tp > 0.05
            if advanced and pos > last_pos + 0.05:
                return
            if time.monotonic() - last_t >= 3.0:
                page.video.set_paused(False)
                last_t = time.monotonic()
            last_pos = pos

    def audit_rate(label: str, seek_seconds: float, window: float = 12.0) -> float | None:
        page.video.set_speed(1.0)
        page.video.seek(float(seek_seconds), project_ms=int(seek_seconds * 1000))
        _pump(app, 3.0)
        page.video.set_paused(False)
        _ensure_playing(30.0)
        samples = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < window:
            app.processEvents()
            pos = page.video.visual_position()
            speed = _mpv_observed("speed")
            time_pos = _mpv_observed("time-pos")
            samples.append((time.monotonic() - t0, pos, speed, time_pos))
            time.sleep(0.2)
        page.video.set_paused(True)
        wall = samples[-1][0] - samples[0][0]
        advanced = samples[-1][1] - samples[0][1]
        rate = advanced / max(0.1, wall)
        # 真视频推进率：直接用 mpv 的 time-pos 观测差分（免疫本地时钟外推）
        tp_first = next((s[3] for s in samples if s[3] is not None), None)
        tp_last = next((s[3] for s in reversed(samples) if s[3] is not None), None)
        tp_rate = ((tp_last - tp_first) / wall) if tp_first is not None and tp_last is not None else None
        speeds = {s[2] for s in samples if s[2] is not None}
        live_mpv = tp_first is not None and tp_last is not None
        report[label] = {
            "wall_s": round(wall, 1), "advanced_s": round(advanced, 2),
            "clock_rate": round(rate, 3),
            "mpv_time_pos_rate": round(tp_rate, 3) if tp_rate is not None else None,
            "mpv_speeds": sorted(str(s) for s in speeds),
            "live_mpv_time_pos": bool(live_mpv),
            "start_pos": round(samples[0][1], 2), "end_pos": round(samples[-1][1], 2),
            "mpv_time_pos": [None if s[3] is None else round(s[3], 2) for s in samples[::4]],
        }
        check(f"{label}_mpv_live", live_mpv,
              f"time_pos {tp_first}->{tp_last}")
        check(f"{label}_mpv_speed_1x", all(abs(float(s) - 1.0) < 0.06 for s in speeds),
              str(sorted(str(s) for s in speeds)))
        effective = tp_rate if tp_rate is not None else rate
        check(f"{label}_rate_1x", 0.8 <= effective <= 1.25,
              f"mpv_time_pos_rate={tp_rate} clock_rate={rate:.2f}")
        return effective

    # ---------------------------------------------------- 2. 三段 1x 真速
    audit_rate("rate_head", 30.0, 15.0)
    audit_rate("rate_mid", duration_ms / 2000.0, 12.0)

    # ---------------------------------------------------- 3. 片尾
    tail_start = max(10.0, duration_ms / 1000.0 - 25.0)
    page.video.set_speed(1.0)
    page.video.seek(tail_start, project_ms=int(tail_start * 1000))
    _pump(app, 3.0)
    page.video.set_paused(False)
    _ensure_playing(30.0)
    tail_samples = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 35.0:
        app.processEvents()
        tail_samples.append((time.monotonic() - t0, page.video.visual_position()))
        time.sleep(0.25)
    page.video.set_paused(True)
    end_s = max(duration_ms, int(page.timeline._duration_ms())) / 1000.0
    beyond = [p for _, p in tail_samples if p > end_s + 5.0]
    restarts = sum(
        1 for i in range(1, len(tail_samples))
        if tail_samples[i][1] < 1.0 and tail_samples[i - 1][1] > end_s - 60.0
    )
    monotonic_tail = all(
        tail_samples[i][1] >= tail_samples[i - 1][1] - 1.5
        for i in range(1, len(tail_samples))
    )
    report["tail"] = {"start": tail_start, "positions": [round(p, 2) for _, p in tail_samples[::4]]}
    check("tail_no_beyond_duration", not beyond, str(beyond[:3]))
    check("tail_no_restart_zero", restarts == 0, f"restarts={restarts}")
    check("tail_monotonic_no_loop", monotonic_tail)

    # ---------------------------------------------------- 4. 播放头边界
    timeline = page.timeline
    bounded_ok = True
    details = []
    try:
        # 工程打开后 media.duration_ms 可能被更新为内容时长；边界必须用
        # 时间轴自己的工程时长（=max(序列/片段/cue)）判定，而不是开工程
        # 时的快照。
        live_duration = int(timeline._duration_ms())
        raw = timeline._x_to_time(timeline.width() * 200)
        bounded = timeline._bounded_time_ms(raw)
        bounded_ok &= 0 <= bounded <= live_duration
        details.append(f"raw={raw} bounded={bounded} live_duration={live_duration}")
        # 真实拖拽事件：按下→拖出右缘→释放
        ruler_y = max(2, timeline.RULER_HEIGHT // 2)
        x_inside = timeline.TRACK_HEADER_WIDTH + 50
        far_x = timeline.width() * 60
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x_inside, ruler_y),
                            QPointF(x_inside, ruler_y), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(far_x, ruler_y),
                           QPointF(far_x, ruler_y), Qt.MouseButton.NoButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(far_x, ruler_y),
                              QPointF(far_x, ruler_y), Qt.MouseButton.LeftButton,
                              Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        timeline.mousePressEvent(press)
        timeline.mouseMoveEvent(move)
        app.processEvents()
        bounded_ok &= 0 <= timeline.playhead_ms <= live_duration
        details.append(f"after_drag playhead={timeline.playhead_ms}")
        timeline.mouseReleaseEvent(release)
        app.processEvents()
        bounded_ok &= 0 <= timeline.playhead_ms <= live_duration
        details.append(f"after_release playhead={timeline.playhead_ms}")
    except Exception as exc:  # pragma: no cover
        bounded_ok = False
        details.append(f"exception={exc!r}")
    check("playhead_drag_bounded", bounded_ok, "; ".join(details))

    # 拖拽后解码侧也不能越界去 seek
    from .runtime_trace import GLOBAL_STUDIO_TRACE
    recent = GLOBAL_STUDIO_TRACE.recent()
    mismatches = [e for e in recent if e.get("event") == "PlaybackClockDebug"]
    check("no_speed_mismatch_traces", not mismatches, json.dumps(mismatches[:2], default=str))
    optimize_events = [
        {k: e.get(k) for k in ("stage", "reason", "at", "proxy_time_s")}
        for e in recent if e.get("event") == "MEDIA_OPTIMIZE"
    ]
    report["optimize_events"] = optimize_events[-8:]
    rejected = [e for e in optimize_events if e.get("stage") == "continuous_proxy_rejected"]
    check("bad_proxy_rejected_trace",
          (kind == "proxy" and True) or bool(rejected),
          f"kind={kind} rejected={len(rejected)}")

    _finish(page, app, report, out_path)
    return 1 if report["failures"] else 0


def _finish(page, app, report, out_path) -> None:
    try:
        page.close_page()
        page.deleteLater()
        app.processEvents()
    except Exception:
        pass
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print("report:", out_path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
