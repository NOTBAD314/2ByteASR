"""Real ffprobe/proxy/waveform acceptance for P7.2.

This is automated runtime evidence. It does not represent real-user clicks.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p72" / "media-runtime"
FIXTURE = ROOT / "tmp" / "p72" / "media" / "p72-av-8s.mp4"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
RUN_ROOT = OUTPUT / f"run-{int(time.time())}-{os.getpid()}"
RUN_ROOT.mkdir(parents=True, exist_ok=False)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(RUN_ROOT / "child-processes.jsonl")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.media_service import MediaService
from twobyteasr.resource_governor import ResourceGovernor
from twobyteasr.runtime_cache import RuntimeCacheManager
from twobyteasr.waveform_cache import WaveformCache, generate_progressive_waveform_cache


def measured(callback):
    started = time.perf_counter()
    value = callback()
    return value, round((time.perf_counter() - started) * 1000.0, 3)


def main() -> int:
    if not FIXTURE.is_file():
        raise FileNotFoundError(FIXTURE)
    cache = RuntimeCacheManager(
        memory_budget_bytes=32 * 1024 * 1024,
        disk_budget_bytes=512 * 1024 * 1024,
    )
    service = MediaService(
        ffprobe_path=FFPROBE,
        ffmpeg_path=FFMPEG,
        cache_root=RUN_ROOT / "media-cache",
        cache_manager=cache,
        governor=ResourceGovernor(background_limit=2),
    )
    result: dict[str, object] = {
        "schema": "2byteasr.p72-media-runtime.v1",
        "evidence_class": "AUTOMATED REAL MEDIA RUNTIME",
        "real_user_click": False,
        "fixture": str(FIXTURE),
        "fixture_bytes": FIXTURE.stat().st_size,
        "run_root": str(RUN_ROOT),
    }
    try:
        cold, cold_ms = measured(lambda: service.metadata(FIXTURE))
        warm, warm_ms = measured(lambda: service.metadata(FIXTURE))
        proxy_job = service.start_proxy(FIXTURE)
        proxy, proxy_ms = measured(lambda: proxy_job.wait(90))
        if proxy is None:
            raise RuntimeError("proxy job did not complete")
        persisted_proxy = service.proxy_manifest(FIXTURE)
        proxy_metadata = service.metadata(proxy.proxy_path, refresh=True)
        result["metadata"] = {
            "cold_ms": cold_ms,
            "warm_ms": warm_ms,
            "same_snapshot_object": cold is warm,
            "snapshot": asdict(cold),
        }
        result["proxy"] = {
            "elapsed_ms": proxy_ms,
            "manifest": asdict(proxy),
            "persisted_manifest": asdict(persisted_proxy) if persisted_proxy else None,
            "switch_ready": proxy.switch_ready,
            "metadata": asdict(proxy_metadata),
            "duration_delta_ms": abs(proxy_metadata.duration_ms - cold.duration_ms),
            "fps_delta": abs(proxy_metadata.fps - cold.fps),
            "streams_match": (
                proxy_metadata.has_video == cold.has_video
                and proxy_metadata.has_audio == cold.has_audio
            ),
        }

        waveform_ready: list[dict[str, object]] = []
        waveform_started = time.perf_counter()

        def waveform_published(tier: str, path: Path) -> None:
            waveform_ready.append({
                "tier": tier,
                "at_ms": round((time.perf_counter() - waveform_started) * 1000.0, 3),
                "path": str(path),
                "frames": WaveformCache(path).metadata.levels[0].frames,
            })

        waveform_path, waveform_cold_ms = measured(lambda: generate_progressive_waveform_cache(
            FIXTURE,
            FFMPEG,
            cache_root=RUN_ROOT / "waveform-cache",
            on_ready=waveform_published,
        ))
        _warm_waveform, waveform_warm_ms = measured(lambda: generate_progressive_waveform_cache(
            FIXTURE,
            FFMPEG,
            cache_root=RUN_ROOT / "waveform-cache",
        ))

        cancelled = False
        cancel_after_coarse = False
        cancel_ready: list[str] = []

        def cancel_published(tier: str, _path: Path) -> None:
            nonlocal cancel_after_coarse
            cancel_ready.append(tier)
            cancel_after_coarse = tier == "coarse"

        try:
            generate_progressive_waveform_cache(
                FIXTURE,
                FFMPEG,
                cache_root=RUN_ROOT / "waveform-cancel-cache",
                cancelled=lambda: cancel_after_coarse,
                on_ready=cancel_published,
            )
        except InterruptedError:
            cancelled = True
        result["waveform"] = {
            "cold_ms": waveform_cold_ms,
            "warm_ms": waveform_warm_ms,
            "published": waveform_ready,
            "final_path": str(waveform_path),
            "cancelled_after_coarse": cancelled,
            "cancel_published": cancel_ready,
        }
        result["cache"] = cache.snapshot()
        child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
        result["child_process_records"] = (
            [json.loads(line) for line in child_log.read_text(encoding="utf-8").splitlines()]
            if child_log.is_file() else []
        )
        metadata_ok = bool(
            cold.duration_ms == 8_000
            and cold.has_video
            and cold.has_audio
            and cold.fps > 29.9
            and cold.video_timebase
            and cold.audio_timebase
            and cold is warm
        )
        proxy_ok = bool(
            proxy.switch_ready
            and persisted_proxy is not None
            and persisted_proxy.switch_ready
            and result["proxy"]["duration_delta_ms"] <= 100
            and result["proxy"]["fps_delta"] <= 0.05
            and result["proxy"]["streams_match"]
        )
        waveform_ok = bool(
            [item["tier"] for item in waveform_ready] == ["coarse", "full"]
            and waveform_warm_ms < waveform_cold_ms
            and cancelled
            and cancel_ready == ["coarse"]
        )
        result["checks"] = {
            "metadata": metadata_ok,
            "proxy": proxy_ok,
            "waveform": waveform_ok,
            "all_children_hidden": all(
                bool(item.get("hidden")) for item in result["child_process_records"]
            ),
        }
        result["pass"] = all(result["checks"].values())
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    target = RUN_ROOT / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target, flush=True)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
