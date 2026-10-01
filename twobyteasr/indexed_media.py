"""Background, lossless optimized copies for recordings without random access.

FLV sources are remuxed (stream copy, never re-encoded) into an MP4 copy when
the codec combination is MP4-safe, falling back to MKV when MP4 muxing or its
validation fails. Only completed and validated files become active. GUI
requests do no disk work; originals and project paths are preserved, and
failure keeps using the source.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue

from .processes import popen_hidden_subprocess, run_hidden_subprocess
from .runtime_trace import GLOBAL_STUDIO_TRACE


# Codec gates for the MP4 attempt. Anything outside these goes straight to MKV.
MP4_SAFE_VIDEO = {"h264", "hevc", "av1"}
MP4_SAFE_AUDIO = {"aac", "mp3", "ac3", "eac3", "flac", "alac"}
REMUX_TIMEOUT_SECONDS = 1800.0


class IndexedMediaCache:
    def __init__(self, root=None):
        configured = root or os.environ.get('TWOBYTEASR_SEEK_CACHE_ROOT')
        self.root = Path(configured) if configured else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "2ByteASR/cache/media/seek"
        self._ready = {}
        self._requested = set()
        self._queue: Queue[str] = Queue()
        self._lock = threading.Lock()
        self._thread = None
        self.errors = {}
        # source -> {'state','progress','container','target','error','started_at'}
        self._status = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._sync_scans: dict[str, bool] = {}
        self._proxy_builds: dict[str, bool] = {}
        # 2026-09-18 P0 残余：构建产物未过时长门的源，一次会话内不再重试
        # （否则 map 命中→排期→构建→拒用→再排期 无限循环）。
        self._proxy_failures: set[str] = set()

    # ------------------------------------------------------------------ API

    def resolve(self, source: str) -> str:
        """Non-blocking: kick preparation and return the best available path."""
        source = str(source)
        if not source.lower().endswith(".flv"):
            return source
        with self._lock:
            if source not in self._requested:
                self._requested.add(source)
                self._status[source] = dict(self._status.get(source) or {},
                                            state="PENDING", progress=0.0)
                self._queue.put(source)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="studio-seek-index", daemon=True)
                    self._thread.start()
            return self._ready.get(source, source)

    def status(self, source: str) -> dict:
        with self._lock:
            state = dict(self._status.get(str(source)) or {})
        if str(source) in self._ready:
            state.update(state="READY", progress=1.0)
        elif not state:
            state = {"state": "IDLE", "progress": 0.0}
        return state

    def optimized_target(self, source: str) -> Path | None:
        with self._lock:
            target = self._ready.get(str(source))
        if target and target != str(source) and Path(target).is_file():
            return Path(target)
        return None

    def sync_map(self, source: str):
        """Cached AVSyncMap for an FLV source, or None while unknown.

        Kicks (once) a background timestamp scan on the optimized copy when
        no map is cached yet. The scan is a single sequential demux read —
        never an extra concurrent reader of the original file.
        """
        from .avsync import load_sync_map
        source = str(source)
        if not source.lower().endswith(".flv"):
            return None
        self.resolve(source)
        target = self.optimized_target(source)
        if target is None:
            return None
        cached = load_sync_map(target.parent)
        if cached is not None:
            # 2026-09-18 P0 残余：map 命中即早退，坏代理被采用门删除后
            # 永远无人重建（用户 6.4GB 工程实测：336s 塌缩产物删了就没了，
            # 长洞 FLV 的连续代理功能一次性丢失）。缓存命中也要排期重建。
            if cached.gaps:
                self._schedule_continuous_proxy(source, target, cached)
            return cached
        with self._lock:
            scanning = self._sync_scans.setdefault(source, False)
            should_scan = not scanning
            if should_scan:
                self._sync_scans[source] = True
        if should_scan:
            threading.Thread(
                target=self._scan_sync_map,
                args=(source, target),
                daemon=True,
                name="studio-avsync-scan",
            ).start()
        return None

    def playback_source(self, source: str):
        """Best preview-timebase artifact: proxy > optimized > (None, original)."""
        source = str(source)
        if not source.lower().endswith(".flv"):
            return None, "original"
        self.resolve(source)
        target = self.optimized_target(source)
        if target is not None:
            from .avsync import (
                continuous_proxy_marker, continuous_proxy_ready,
                validate_continuous_proxy, write_continuous_proxy_marker,
            )
            proxy = continuous_proxy_ready(target.parent)
            if proxy is not None:
                # §20 采用门：只有带 v2 标记（或一次性通过时长验证的旧
                # 产物）才可投用；验证失败即删除并回退 optimized。
                if not continuous_proxy_marker(target.parent).is_file():
                    from .avsync import load_sync_map
                    cached = load_sync_map(target.parent)
                    expected = int(
                        (cached.content_duration_ms or 0)
                        if cached is not None else 0
                    )
                    ok, reason = validate_continuous_proxy(
                        target.parent, self._ffprobe_path(),
                        expected_duration_ms=expected,
                    )
                    if not ok:
                        try:
                            proxy.unlink(missing_ok=True)
                        except OSError:
                            pass
                        GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                            "source": source,
                            "stage": "continuous_proxy_rejected",
                            "reason": reason,
                            "at": "adoption",
                        })
                        self.sync_map(source)
                        return target, "optimized"
                    write_continuous_proxy_marker(
                        target.parent,
                        expected_duration_ms=expected,
                        folded_gaps=len(cached.gaps) if cached is not None else 0,
                        folded_ms=cached.total_gap_ms if cached is not None else 0,
                    )
                return proxy, "proxy"
            # No proxy yet: make sure the timestamp scan (and, for gappy
            # media, the proxy build) has been kicked — polling this method
            # alone must drive the whole chain.
            self.sync_map(source)
            return target, "optimized"
        return None, "original"

    def _ffprobe_path(self) -> Path:
        from .audio_engine import studio_ffmpeg_path
        return studio_ffmpeg_path().with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe"
        )

    def next_gap_after(self, source: str, content_ms: int, window_ms: int = 2000):
        """Nearest audio-clock hole within window after content_ms, if any."""
        from .avsync import load_sync_map
        target = self.optimized_target(str(source))
        if target is None:
            return None
        sync_map = load_sync_map(target.parent)
        if sync_map is None:
            return None
        for gap in sync_map.gaps:
            if gap.start_ms - window_ms <= content_ms <= gap.end_ms + 500:
                return gap
        return None

    def _scan_sync_map(self, source: str, target: Path) -> None:
        from .avsync import scan_timestamp_gaps, save_sync_map
        try:
            from .audio_engine import studio_ffmpeg_path
            ffprobe = studio_ffmpeg_path().with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            result = scan_timestamp_gaps(target, ffprobe)
            save_sync_map(target.parent, result.map)
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "av_sync_scan",
                "status": result.status, "events": result.event_count,
                "total_gap_ms": result.map.total_gap_ms,
            })
            if result.map.gaps:
                self._schedule_continuous_proxy(source, target, result.map)
        except Exception as exc:
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "av_sync_scan_failed",
                "error": str(exc)[-300:],
            })
        finally:
            with self._lock:
                self._sync_scans.pop(source, None)

    def _schedule_continuous_proxy(self, source: str, target: Path, sync_map) -> None:
        """Fold the joint gaps into a packet-identical continuous preview copy."""
        from .avsync import build_continuous_proxy, continuous_proxy_ready
        if continuous_proxy_ready(target.parent) is not None:
            return
        with self._lock:
            if source in self._proxy_failures:
                return
            building = self._proxy_builds.get(source, False)
            if building:
                return
            self._proxy_builds[source] = True
        threading.Thread(
            target=self._build_continuous_proxy,
            args=(source, target, sync_map),
            daemon=True,
            name="studio-continuous-proxy",
        ).start()

    def _build_continuous_proxy(self, source: str, target: Path, sync_map) -> None:
        from .avsync import build_continuous_proxy
        started = time.perf_counter()
        try:
            from .avsync import write_continuous_proxy_marker, validate_continuous_proxy
            proxy = build_continuous_proxy(target, sync_map, target.parent / "continuous.mkv")
            expected_ms = int(sync_map.content_duration_ms or 0)
            ok, reason = validate_continuous_proxy(
                target.parent, self._ffprobe_path(), expected_duration_ms=expected_ms
            )
            if not ok:
                # §18/§19：比例失衡的代理绝不能投用（8x 折叠=时长塌缩到
                # 1/8 的直接拦截位）。删除产物，回退 optimized+AVSyncMap。
                try:
                    proxy.unlink(missing_ok=True)
                except OSError:
                    pass
                with self._lock:
                    self._proxy_failures.add(source)
                GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                    "source": source, "stage": "continuous_proxy_rejected",
                    "reason": reason,
                    "expected_duration_ms": expected_ms,
                })
                return
            write_continuous_proxy_marker(
                target.parent,
                expected_duration_ms=expected_ms,
                folded_gaps=len(sync_map.gaps),
                folded_ms=sync_map.total_gap_ms,
            )
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "continuous_proxy_ready",
                "target": str(proxy),
                "proxy_time_s": round(time.perf_counter() - started, 2),
                "size_bytes": proxy.stat().st_size,
                "folded_gaps": len(sync_map.gaps),
                "folded_ms": sync_map.total_gap_ms,
                "validated": reason,
            })
        except Exception as exc:
            with self._lock:
                self._proxy_failures.add(source)
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "continuous_proxy_failed",
                "error": str(exc)[-300:],
            })
        finally:
            with self._lock:
                self._proxy_builds.pop(source, None)

    def wait_optimized(
        self, source: str, *, cancelled=None, timeout: float | None = None,
        on_status=None,
    ) -> str:
        """Block until preparation finishes; returns the best path (source on failure).

        Used by worker threads (waveform) that can afford to wait while the
        remux streams the file once. Never waits when the media is not FLV.
        """
        source = str(source)
        current = self.resolve(source)
        if not source.lower().endswith(".flv"):
            return source
        deadline = time.monotonic() + float(timeout) if timeout else None
        while True:
            if cancelled and cancelled():
                return current
            with self._lock:
                done = source in self._ready or source in self.errors
                current = self._ready.get(source, current)
                state = dict(self._status.get(source) or {})
            if done:
                if on_status is not None:
                    try:
                        on_status(state)
                    except Exception:
                        pass
                return current
            if on_status is not None and state:
                try:
                    on_status(state)
                except Exception:
                    pass
            if deadline and time.monotonic() > deadline:
                return current
            time.sleep(0.25)

    def cancel_all(self) -> int:
        with self._lock:
            events = tuple(self._cancel_events.values())
        for event in events:
            event.set()
        return len(events)

    # ------------------------------------------------------------- worker

    def _run(self):
        while True:
            source = self._queue.get()
            cancel_event = threading.Event()
            with self._lock:
                self._cancel_events[source] = cancel_event
            try:
                target = self._prepare(Path(source), cancel_event)
                with self._lock:
                    self._ready[source] = str(target)
                    self._status[source] = {
                        "state": "READY", "progress": 1.0,
                        "container": target.suffix.lstrip(".").lower(),
                        "target": str(target),
                    }
            except Exception as exc:
                self.errors[source] = str(exc)
                with self._lock:
                    self._status[source] = {
                        "state": "FAILED", "progress": 0.0, "error": str(exc),
                    }
            finally:
                with self._lock:
                    self._cancel_events.pop(source, None)
                self._queue.task_done()

    def _set_progress(self, source: str, progress: float, state: str = "RUNNING") -> None:
        with self._lock:
            self._status[source] = dict(self._status.get(source) or {},
                                        state=state, progress=max(0.0, min(0.999, float(progress))))

    # ------------------------------------------------------------- prepare

    def _prepare(self, source: Path, cancel_event: threading.Event) -> Path:
        from .audio_engine import studio_ffmpeg_path
        ffmpeg = studio_ffmpeg_path()
        ffprobe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        stat = source.stat()
        key = hashlib.sha256(
            f"optimize-v2|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        ).hexdigest()[:32]
        folder = self.root / "v2" / key
        manifest = folder / "ready.json"

        # Legacy v1 cache (MKV, round 51) stays fully valid — reuse it.
        legacy_key = hashlib.sha256(
            f"seek-v1|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        ).hexdigest()[:32]
        legacy = self.root / legacy_key / "indexed.mkv"
        legacy_manifest = self.root / legacy_key / "ready.json"
        if legacy.is_file() and legacy_manifest.is_file():
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": str(source), "cache_hit": "legacy-v1", "target": str(legacy),
                "container": "mkv",
            })
            return legacy

        # Warm v2 cache: skip the (expensive, multi-second on long FLV) probe.
        if manifest.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                warm = folder / f"optimized.{payload.get('container', 'mkv')}"
                if warm.is_file():
                    GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                        "source": str(source), "cache_hit": True, "target": str(warm),
                        "container": payload.get('container', 'mkv'),
                    })
                    return warm
            except (OSError, ValueError):
                pass

        def probe(path):
            result = run_hidden_subprocess(
                [str(ffprobe), "-v", "error", "-show_entries",
                 "format=start_time,duration:stream=codec_type,codec_name,start_time",
                 "-of", "json", str(path)],
                capture_output=True, timeout=90, purpose="validate optimized media")
            if result.returncode:
                raise RuntimeError("Cannot validate optimized media")
            return json.loads(result.stdout)

        original = probe(source)
        original_format = original['format']
        original_streams = original.get('streams', [])
        duration_s = float(original_format.get('duration') or 0.0)
        video_codecs = {
            str(s.get('codec_name') or '').lower()
            for s in original_streams if s.get('codec_type') == 'video'
        }
        audio_codecs = {
            str(s.get('codec_name') or '').lower()
            for s in original_streams if s.get('codec_type') == 'audio'
        }
        order = ["mp4", "mkv"]
        if video_codecs and not video_codecs <= MP4_SAFE_VIDEO:
            order = ["mkv"]
        elif audio_codecs and not audio_codecs <= MP4_SAFE_AUDIO:
            order = ["mkv"]

        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("optimized.*.partial.*"):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
        started = time.perf_counter()
        last_error = ""
        for index, container in enumerate(order):
            cancel_event.clear()
            target = folder / f"optimized.{container}"
            partial = folder / f"optimized.{os.getpid()}.partial.{container}"
            try:
                self._remux(ffmpeg, source, partial, container, cancel_event,
                            progress_source=str(source), duration_s=duration_s)
                if cancel_event.is_set():
                    raise InterruptedError("optimized media cancelled")
                indexed = probe(partial)
                self._validate(original, indexed)
                os.replace(partial, target)
                manifest.write_text(json.dumps({
                    'source': str(source), 'size': stat.st_size,
                    'mtime_ns': stat.st_mtime_ns, 'container': container,
                    'duration_ms': round(duration_s * 1000),
                    'video_codecs': sorted(video_codecs),
                    'audio_codecs': sorted(audio_codecs),
                }), encoding="utf-8")
                GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                    "source": str(source),
                    "video": ",".join(sorted(video_codecs)) or "-",
                    "audio": ",".join(sorted(audio_codecs)) or "-",
                    "duration": round(duration_s, 3),
                    "target": str(target), "container": container,
                    "cache_hit": False,
                    "fallback_attempt": index,
                    "remux_time_s": round(time.perf_counter() - started, 3),
                })
                return target
            except InterruptedError:
                raise
            except Exception as exc:
                last_error = str(exc)
                GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                    "source": str(source), "container": container,
                    "error": last_error[-400:], "fallback_attempt": index,
                })
            finally:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
        raise RuntimeError(last_error or "optimized media preparation failed")

    @staticmethod
    def _validate(original: dict, indexed: dict) -> None:
        old_format, new_format = original['format'], indexed['format']
        old_start, new_start = float(old_format.get('start_time', 0)), float(new_format.get('start_time', 0))
        if abs(float(old_format['duration']) - old_start - (float(new_format['duration']) - new_start)) > .2:
            raise RuntimeError("Optimized media duration mismatch")
        old_streams = {s['codec_type']: float(s.get('start_time', old_start)) - old_start
                       for s in original['streams']}
        new_streams = {s['codec_type']: float(s.get('start_time', new_start)) - new_start
                       for s in indexed['streams']}
        if old_streams.keys() != new_streams.keys() or any(
                abs(t - new_streams[k]) > .05 for k, t in old_streams.items()):
            raise RuntimeError("Optimized media stream timing mismatch")

    def _remux(self, ffmpeg: Path, source: Path, target: Path, container: str,
               cancel_event: threading.Event, *, progress_source: str = "",
               duration_s: float = 0.0) -> None:
        """Stream-copy remux with progress and cancellation (never re-encodes)."""
        command = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-copyts", "-start_at_zero", "-i", str(source),
            "-map", "0:v:0?", "-map", "0:a?",
            "-c", "copy", "-avoid_negative_ts", "disabled",
        ]
        if container == "mp4":
            command += ["-movflags", "+faststart"]
        # ``mkv`` is a file extension, not a muxer name; the muxer is matroska.
        muxer = "matroska" if container == "mkv" else container
        command += ["-f", muxer, "-progress", "pipe:1", "-nostats", str(target)]
        process = popen_hidden_subprocess(
            command, purpose="prepare optimized media (stream copy)",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        progress_lines: list[bytes] = []
        stderr_tail: list[bytes] = []

        def drain(stream, sink: list) -> None:
            try:
                while True:
                    chunk = stream.readline()
                    if not chunk:
                        break
                    sink.append(chunk)
                    if len(sink) > 400:
                        del sink[:200]
            except OSError:
                pass

        readers = [
            threading.Thread(target=drain, args=(process.stdout, progress_lines), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_tail), daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + REMUX_TIMEOUT_SECONDS
        try:
            while process.poll() is None:
                if cancel_event.is_set():
                    process.kill()
                    raise InterruptedError("optimized media cancelled")
                if time.monotonic() > deadline:
                    process.kill()
                    raise RuntimeError("optimized media preparation timed out")
                if progress_source and duration_s > 0 and progress_lines:
                    self._publish_progress(progress_lines, duration_s, progress_source)
                time.sleep(0.05)
            for reader in readers:
                reader.join(timeout=1.0)
            stderr = b"".join(stderr_tail).decode("utf-8", errors="replace")
            if process.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
                raise RuntimeError(
                    f"remux failed ({process.returncode}): {stderr[-800:]}"
                )
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

    def _publish_progress(self, lines: list[bytes], duration_s: float, source: str) -> None:
        try:
            payload = {}
            for raw in lines[-40:]:
                text = raw.decode("utf-8", errors="replace").strip()
                if "=" in text:
                    key, value = text.split("=", 1)
                    payload[key.strip()] = value.strip()
            microseconds = payload.get("out_time_us")
            if microseconds is None and payload.get("out_time_ms") not in (None, "N/A"):
                microseconds = payload["out_time_ms"]
            if microseconds in (None, "N/A"):
                return
            seconds = max(0.0, float(microseconds) / 1_000_000.0)
            progress = seconds / duration_s if duration_s > 0 else 0.0
            self._set_progress(source, progress)
        except (ValueError, TypeError):
            pass


GLOBAL_INDEXED_MEDIA = IndexedMediaCache()
