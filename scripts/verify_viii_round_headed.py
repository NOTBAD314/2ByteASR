"""2026-09-18 VIII 轮 headed 真机验证：真实 FLV 工程（1:29:46 蓝色星原）。

五项验证（截图+数字证据落 tmp/viii-round-20260918/）：
A. 波形跨缩放一致性：整段/10min/40s 三档 zoom，同区间同强度（dBFS 绝对标尺）
   + 整段视图不再落 outline 稀疏级。
B. FLV 缩略图：头/中/尾真实送达计数与耗时。
C. 三轨独立调高：右侧 rail + 泳道几何 + 主题接入截图。
D. 播放保护面在 EXE --playback-audit 覆盖，此处不重复。

用法：.venv/Scripts/python.exe scripts/verify_viii_round_headed.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tmp" / "viii-round-20260918"
PROJECT_SRC = Path(os.environ["LOCALAPPDATA"]) / r"2ByteASR\Projects\未命名工程\未命名工程.2byteproj"
WAVEFORM_CACHE = Path(os.environ["LOCALAPPDATA"]) / r"2ByteASR\SubtitleStudioPreview\waveform-cache\9ab36095c80cd6e936e90f17e4f6b28e"
CONTAINER_MS = 5_386_572
PLAYHEAD_MS = 4_165_362  # 01:09:25.362

results: dict[str, object] = {}
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    # 工程副本：autosave/衍生产物全部落在 tmp，绝不动用户工程原件。
    project_copy = OUT / "project" / "未命名工程.2byteproj"
    project_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_SRC, project_copy)

    from twobyteasr.studio_project import load_project
    from twobyteasr.studio_timeline import WaveformTimeline
    from twobyteasr.waveform_cache import WaveformCache

    project = load_project(project_copy)
    timeline = WaveformTimeline()
    timeline.resize(1600, 640)
    timeline.set_project(project)
    timeline.set_cache(WaveformCache(WAVEFORM_CACHE))
    timeline.show()
    app.processEvents()

    def snapshot(name: str) -> None:
        app.processEvents()
        pix = timeline.grab()
        pix.save(str(OUT / f"{name}.png"))
        results.setdefault("shots", []).append(name)

    # ---------------- A. 波形跨缩放 ----------------
    def envelope_stats(start: int, duration: int, pixels: int):
        timeline.set_visible_window(start, min(duration, CONTAINER_MS - start))
        app.processEvents()
        rect = next(iter(timeline._audio_track_rects().values()))
        left, right = timeline.TRACK_HEADER_WIDTH + 2, timeline._content_right() - 2
        path = timeline._waveform_envelope(
            timeline.waveform_caches.get(next(iter(timeline.waveform_caches), ""), None)
            or timeline.cache, start, min(start + duration, CONTAINER_MS), int(right - left), left, right, rect,
        )
        stats = dict(timeline._last_waveform_envelope_stats or {})
        if path is None:
            return stats, None
        top = path.boundingRect().top()
        return stats, (rect.center().y() - top)

    stats_whole, peak_whole = envelope_stats(0, CONTAINER_MS, 1800)
    snapshot("A1_waveform_wholeclip")
    stats_mid, peak_mid = envelope_stats(PLAYHEAD_MS - 300_000, 600_000, 1800)
    snapshot("A2_waveform_10min")
    window = 40_000
    stats_tight, peak_tight = envelope_stats(PLAYHEAD_MS - window // 2, window, 1800)
    snapshot("A3_waveform_40s")

    results["waveform"] = {
        "whole": {"level": stats_whole.get("level_file"), "ms_per_bucket": stats_whole.get("milliseconds_per_bucket")},
        "mid": {"level": stats_mid.get("level_file"), "ms_per_bucket": stats_mid.get("milliseconds_per_bucket")},
        "tight": {"level": stats_tight.get("level_file"), "ms_per_bucket": stats_tight.get("milliseconds_per_bucket")},
        "peak_height_px_whole": peak_whole, "peak_height_px_mid": peak_mid, "peak_height_px_tight": peak_tight,
    }
    check("A1 整段视图用真实 lod 级而非 outline",
          100.0 < float(stats_whole.get("milliseconds_per_bucket") or 0) < 10000.0,
          f"ms/bucket={stats_whole.get('milliseconds_per_bucket')} (outline=57304)")
    # 同一轨高下三档 zoom 的满幅峰值高度应一致（dBFS 绝对标尺；同 rect）。
    heights = [h for h in (peak_whole, peak_mid, peak_tight) if h is not None]
    check("A2 三档 zoom 峰值视觉高度一致（缩放不改强弱）",
          len(heights) == 3 and max(heights) - min(heights) <= 1.5,
          f"heights={heights}")
    # 波形在整段视图非平线：可见包络顶点明显高于中心线（有真实波动）。
    check("A3 整段视图包络有起伏（非平线）",
          bool(heights) and min(heights) >= 4.0,
          f"min_peak_height={min(heights) if heights else None}px")

    # ---------------- B. FLV 缩略图 ----------------
    timeline.filmstrip_visible = True
    timeline.thumbnail_requests_enabled = True
    thumbs = timeline._thumbnails

    def thumb_stage(label: str, start: int, duration: int, budget_s: float = 30.0) -> int:
        thumbs.metrics["decoded"] = thumbs.metrics.get("decoded", 0)
        before = len(thumbs.memory)
        timeline.set_visible_window(start, duration)
        deadline = time.perf_counter() + budget_s
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.05)
        # 绘制端口径：paint 用 canonical（原始 FLV）路径 + 像素密度 LOD 查询；
        # 修复前 collect/解码走 optimized 身份、paint 查 canonical 身份，
        # 送达计数再高也画不上——这里必须查得到才算真显示。
        from twobyteasr.video_filmstrip import filmstrip_lod_ms
        original_source = str(project.media.path)
        content_px = max(1, timeline._content_right() - timeline.TRACK_HEADER_WIDTH)
        pps = content_px * 1000 / max(1, duration)
        lod = filmstrip_lod_ms(pps, 40)
        painted = sum(
            1 for offset in range(1, min(8, duration // 1000))
            if thumbs.get(original_source, start + offset * 1000, lod_ms=lod) is not None
        )
        results.setdefault("thumbnails", {})[label] = {
            "memory_tiles": len(thumbs.memory), "delta": len(thumbs.memory) - before,
            "painted_query_hits": painted,
            "failed": len(thumbs.failed), "errors": thumbs.metrics.get("errors"),
            "decoded": thumbs.metrics.get("decoded"),
        }
        return painted

    delta_head = thumb_stage("head", 0, 120_000, 25)
    snapshot("B1_thumbnails_head")
    delta_mid = thumb_stage("mid@01:09:25", PLAYHEAD_MS - 60_000, 120_000, 30)
    snapshot("B2_thumbnails_mid")
    delta_tail = thumb_stage("tail", CONTAINER_MS - 180_000, 180_000, 35)
    snapshot("B3_thumbnails_tail")
    check("B1 头部可视区有真实缩略图送达", delta_head >= 3, f"delta={delta_head}")
    check("B2 中段(01:09:25)有真实缩略图送达", delta_mid >= 3, f"delta={delta_mid}")
    check("B3 片尾有真实缩略图送达", delta_tail >= 3, f"delta={delta_tail}")
    check("B4 无永久失败格", len(thumbs.failed) == 0, f"failed={len(thumbs.failed)} errors={thumbs.metrics.get('errors')}")

    # ---------------- C. 三轨独立调高 + 主题 ----------------
    timeline.set_visible_window(PLAYHEAD_MS - 300_000, 600_000)
    default_video = timeline._video_track_rects()["V1"].height()
    timeline.set_track_height("video", 140)
    timeline.set_track_height("audio", 84)
    app.processEvents()
    snapshot("C1_track_heights_video140_audio84")
    v = timeline._video_track_rects()["V1"].height()
    a = next(iter(timeline._audio_track_rects().values())).height()
    check("C1 视频/音频轨独立调高生效", v == 140 and a == 84, f"video={v} audio={a}")
    timeline.set_track_height("subtitle", 110)
    app.processEvents()
    snapshot("C2_track_heights_subtitle110")
    check("C2 字幕轨独立调高", timeline._speaker_track_height() == 110, f"subtitle={timeline._speaker_track_height()}")
    rail = timeline._height_rail
    rail_grab = rail.grab(); rail_grab.save(str(OUT / "C3_rail_warm.png"))
    from twobyteasr import theme_manager
    theme_manager.apply_application_theme(app=app, key="grape")
    app.processEvents()
    snapshot("C4_theme_grape")
    rail_grab = rail.grab(); rail_grab.save(str(OUT / "C5_rail_grape.png"))
    check("C3 rail 常驻且三段对齐", {s["kind"] for s in rail._segments} == {"video", "audio", "subtitle"},
          f"kinds={[s['kind'] for s in rail._segments]}")
    timeline._reset_track_height_kind("")
    app.processEvents()
    theme_manager.apply_application_theme(app=app, key="warm")

    timeline.close()
    (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
