"""Original-first playback with explicit, rebuildable compatibility copies.

mpv/PyAV decode FLV directly. Stream-copy MP4/MKV is reserved for a reported
compatibility/seek need; measured timestamp gaps may require a continuous
packet-identical proxy. Canonical project paths and time mapping are preserved.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import shutil
import threading
import time
from contextlib import contextmanager
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
        if configured:
            self.root = Path(configured)
        else:
            from .runtime_paths import get_runtime_paths
            self.root = get_runtime_paths().cache_root / "media" / "seek"
        self._ready = {}
        self._requested = set()
        self._queue: Queue[str] = Queue()
        self._lock = threading.Lock()
        self._thread = None
        self.errors = {}
        # source -> {'state','progress','container','target','error','started_at'}
        self._status = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancelled_sources: set[str] = set()
        self._sync_scans: dict[str, bool] = {}
        self._proxy_builds: dict[str, bool] = {}
        # 2026-09-18 P0 残余：构建产物未过时长门的源，一次会话内不再重试
        # （否则 map 命中→排期→构建→拒用→再排期 无限循环）。
        self._proxy_failures: set[str] = set()
        self._sync_scan_done: set[str] = set()
        self._media_touched: dict[str, float] = {}
        self._ready_identities: dict[str, tuple[int, int]] = {}
        # source -> (checked_at, {"path","offset_ms"} | None)
        self._audio_seek: dict[str, tuple[float, dict | None]] = {}
        self._audio_seek_builds: set[str] = set()
        self._audio_seek_failures: set[str] = set()
        self._legacy_map_checked: set[str] = set()

    # ------------------------------------------------------------------ API

    def resolve(self, source: str, *, reason: str = "") -> str:
        """Use the original; prepare a stream-copy only for an explicit need.

        mpv and PyAV both accept FLV. A suffix alone is not evidence that an
        entire recording needs another copy. Existing callers that genuinely
        need an indexed container use ``wait_optimized`` or a reason here.
        """
        source = str(source)
        if not source.lower().endswith(".flv"):
            return source
        with self._lock:
            ready = self._ready.get(source)
            changed = False
            if ready and source in self._ready_identities and Path(source).is_file():
                stat = Path(source).stat()
                changed = self._ready_identities[source] != (stat.st_size, stat.st_mtime_ns)
            if ready and (changed or not Path(ready).is_file()):
                self._ready.pop(source, None)
                self._ready_identities.pop(source, None)
                self._requested.discard(source)
                self.errors.pop(source, None)
                self._sync_scan_done.discard(source)
                self._proxy_failures.discard(source)
            if not reason:
                current = self._ready.get(source, source)
                if current == source and not Path(source).is_file():
                    recovered = self._recover_missing_source(source)
                    if recovered:
                        self._ready[source] = str(recovered)
                        return str(recovered)
                return current
            if self._status.get(source, {}).get('state') == 'CANCELLED':
                self._requested.discard(source)
                self.errors.pop(source, None)
            if source not in self._requested:
                self._requested.add(source)
                self._status[source] = dict(self._status.get(source) or {},
                                            state="PENDING", progress=0.0, reason=str(reason))
                self._queue.put(source)
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="studio-seek-index", daemon=True)
                    self._thread.start()
            return self._ready.get(source, source)

    def _recover_missing_source(self, source: str) -> Path | None:
        """A validated cache may be the only remaining playable copy."""
        from .storage_service import safe_path
        for manifest in self.root.glob('v2/*/ready.json'):
            try:
                payload = json.loads(manifest.read_text(encoding='utf-8'))
                if str(payload.get('source')) != source:
                    continue
                container = payload.get('container')
                if container not in {'mp4', 'mkv'}:
                    continue
                target = manifest.parent / f'optimized.{container}'
                if safe_path(target, (self.root,)) and target.is_file():
                    self._register_media(target, source, 'compatibility-stream-copy')
                    return target
            except (OSError, ValueError, TypeError):
                continue
        for manifest in self.root.glob('v2/*/origin.json'):
            try:
                payload = json.loads(manifest.read_text(encoding='utf-8'))
                if payload.get('producer') != 'indexed_media' or payload.get('source') != source:
                    continue
                target = manifest.parent / 'continuous.mkv'
                if safe_path(target, (self.root,)) and target.is_file() and (manifest.parent/'continuous.json').is_file():
                    self._register_media(target, source, 'timestamp-gap-folding')
                    return target
            except (OSError, ValueError, TypeError):
                continue
        return None

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

    def _cache_folder(self, source: str) -> Path | None:
        target = self.optimized_target(source)
        if target is not None:
            return target.parent
        try:
            stat = Path(source).stat()
        except OSError:
            return None
        key = hashlib.sha256(
            f"optimize-v2|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        ).hexdigest()[:32]
        return self.root / "v2" / key

    def sync_map(self, source: str):
        """Cached AVSyncMap for an FLV source, or None while unknown.

        Kicks once a background timestamp scan on the original source (or an
        explicitly requested compatibility copy). Scanning timestamps does not
        require a full copy; the persisted map keeps preview/audio sync intact.
        """
        from .avsync import load_sync_map
        source = str(source)
        if not source.lower().endswith(".flv"):
            return None
        target = self.optimized_target(source)
        folder = self._cache_folder(source)
        if folder is None:
            return None
        from .storage_service import safe_path
        if not safe_path(folder, (self.root,)):
            return None
        cached = load_sync_map(folder)
        if cached is not None and cached.gaps and cached.stream_indices is None:
            # Saved before streams were classified by codec type (2026-10-12):
            # verify in the background that stream 0 really was the video.
            self._verify_legacy_sync_map(source, folder)
        if cached is not None:
            # 2026-09-18 P0 残余：map 命中即早退，坏代理被采用门删除后
            # 永远无人重建（用户 6.4GB 工程实测：336s 塌缩产物删了就没了，
            # 长洞 FLV 的连续代理功能一次性丢失）。缓存命中也要排期重建。
            if cached.gaps:
                self._schedule_continuous_proxy(source, target or Path(source), cached, folder)
            return cached
        with self._lock:
            if source in self._sync_scan_done:
                return None
            scanning = self._sync_scans.setdefault(source, False)
            should_scan = not scanning
            if should_scan:
                self._sync_scans[source] = True
        if should_scan:
            threading.Thread(
                target=self._scan_sync_map,
                args=(source, target or Path(source), folder),
                daemon=True,
                name="studio-avsync-scan",
            ).start()
        return None

    def _verify_legacy_sync_map(self, source: str, folder: Path) -> None:
        with self._lock:
            if source in self._legacy_map_checked:
                return
            self._legacy_map_checked.add(source)

        def verify():
            from .avsync import load_sync_map, probe_av_stream_indices, save_sync_map
            try:
                video, audio = probe_av_stream_indices(source, self._ffprobe_path())
                cached = load_sync_map(folder)
                if cached is None:
                    return
                if (video, audio) == (0, 1):
                    cached.stream_indices = {"video": 0, "audio": 1}
                    save_sync_map(folder, cached)
                    return
                # Holes were assigned to the wrong streams: drop the map and
                # any proxy folded with it; the next lookup rescans.
                for name in ("sync-map.json", "continuous.mkv", "continuous.json"):
                    (Path(folder) / name).unlink(missing_ok=True)
                with self._lock:
                    self._sync_scan_done.discard(source)
                GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {"source": source, "stage": "legacy_sync_map_dropped",
                                                            "video_index": video, "audio_index": audio})
            except Exception as exc:
                GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {"source": source, "stage": "legacy_sync_map_check_failed",
                                                            "error": str(exc)[-300:]})
        threading.Thread(target=verify, daemon=True, name="studio-avsync-verify").start()

    def playback_source(self, source: str):
        """Best preview-timebase artifact: proxy > optimized > (None, original)."""
        source = str(source)
        if not source.lower().endswith(".flv"):
            return None, "original"
        self.resolve(source)
        target = self.optimized_target(source)
        folder = self._cache_folder(source)
        if folder is not None:
            from .avsync import (
                continuous_proxy_marker, continuous_proxy_ready,
                validate_continuous_proxy, write_continuous_proxy_marker,
            )
            proxy = continuous_proxy_ready(folder)
            if proxy is not None:
                # §20 采用门：只有带 v2 标记（或一次性通过时长验证的旧
                # 产物）才可投用；验证失败即删除并回退 optimized。
                if not continuous_proxy_marker(folder).is_file():
                    from .avsync import load_sync_map
                    cached = load_sync_map(folder)
                    expected = int(
                        (cached.content_duration_ms or 0)
                        if cached is not None else 0
                    )
                    ok, reason = validate_continuous_proxy(
                        folder, self._ffprobe_path(),
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
                        return (target, "optimized") if target else (None, "original")
                    write_continuous_proxy_marker(
                        folder,
                        expected_duration_ms=expected,
                        folded_gaps=len(cached.gaps) if cached is not None else 0,
                        folded_ms=cached.total_gap_ms if cached is not None else 0,
                    )
                self._register_media(proxy, source, "timestamp-gap-folding")
                return proxy, "proxy"
            # No proxy yet: make sure the timestamp scan (and, for gappy
            # media, the proxy build) has been kicked — polling this method
            # alone must drive the whole chain.
            self.sync_map(source)
            if target is not None:
                self._register_media(target, source, "compatibility-stream-copy")
                return target, "optimized"
        return None, "original"

    def _ffprobe_path(self) -> Path:
        from .audio_engine import studio_ffmpeg_path
        return studio_ffmpeg_path().with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe"
        )

    # --------------------------------------------- audio seek copy (FLV)
    def audio_seek_source(self, source: str) -> dict | None:
        """Indexed audio-only copy of an FLV for the preview audio decoder.

        Returns ``{"path", "offset_ms"}`` when a validated copy for this exact
        source (path, size, mtime, generator version) exists; otherwise starts
        one background build and returns None (the decoder keeps reading the
        original). Cheap enough for every playback tick: answers are memoised
        and an unknown result is re-checked at most every two seconds.
        """
        source = str(source or "")
        if not source.lower().endswith(".flv"):
            return None
        now = time.monotonic()
        with self._lock:
            known = self._audio_seek.get(source)
        if known is not None and (known[1] is not None or now - known[0] < 2.0):
            return known[1]
        result = None
        try:
            folder = self._cache_folder(source)
            if folder is not None:
                result = audio_seek_copy_ready(folder, source)
                if result is None:
                    self._schedule_audio_seek_copy(source, folder)
        except OSError:
            result = None
        with self._lock:
            self._audio_seek[source] = (now, result)
        return result

    def _schedule_audio_seek_copy(self, source: str, folder: Path) -> None:
        from .storage_service import safe_path
        if not safe_path(folder, (self.root,)):
            return
        with self._lock:
            if source in self._audio_seek_builds or source in self._audio_seek_failures:
                return
            self._audio_seek_builds.add(source)
        threading.Thread(target=self._build_audio_seek_copy, args=(source, folder),
                         daemon=True, name="studio-audio-seek-copy").start()

    def _build_audio_seek_copy(self, source: str, folder: Path) -> None:
        started = time.perf_counter()
        cancel = threading.Event()
        with self._lock:
            self._cancel_events['audio-seek:' + source] = cancel
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with self._generation_lock(folder, cancel):
                if audio_seek_copy_ready(folder, source) is None:
                    from .audio_engine import studio_ffmpeg_path
                    marker = build_audio_seek_copy(source, folder, studio_ffmpeg_path(),
                                                   self._ffprobe_path(), cancelled=cancel.is_set)
                    self._register_media(folder / AUDIO_SEEK_COPY_NAME, source, "audio-seek-copy")
                    GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                        "source": source, "stage": "audio_seek_copy_ready",
                        "seconds": round(time.perf_counter() - started, 2),
                        "size_bytes": marker.get("size_bytes"), "offset_ms": marker.get("offset_ms")})
        except Exception as exc:
            with self._lock:
                if not isinstance(exc, InterruptedError):
                    self._audio_seek_failures.add(source)
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "audio_seek_copy_failed", "error": str(exc)[-300:]})
        finally:
            with self._lock:
                self._audio_seek_builds.discard(source)
                self._cancel_events.pop('audio-seek:' + source, None)
                self._audio_seek.pop(source, None)

    def prepare_timeline_source(self, source: str, *, ffmpeg=None, cancelled=None) -> dict:
        """Resolve one source's content clock for a worker, never the UI thread.

        An export/ASR job may not silently fall back to timestamp addressing
        while a gappy source's preview uses the continuous proxy. Reuse the
        preview cache and its generation lock, and fail if that clock cannot
        be prepared. No clip position is changed and no offset is applied to
        an already continuous file.
        """
        from .avsync import (load_sync_map, save_sync_map, scan_timestamp_gaps,
                             continuous_proxy_ready, validate_continuous_proxy)
        source = str(Path(source).resolve())
        receipt = dict(contract="timeline-content-v2", original_path=source,
                       path=source, time_domain="content", kind="identity")
        if cancelled and cancelled():
            raise InterruptedError("timeline media preparation cancelled")
        if not source.lower().endswith('.flv'):
            return receipt
        folder = self._cache_folder(source)
        from .storage_service import safe_path
        if folder is None or not safe_path(folder, (self.root,)):
            raise OSError("无法准备素材时间映射：" + source)
        folder.mkdir(parents=True, exist_ok=True)
        ffprobe = (Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
                   if ffmpeg else self._ffprobe_path())

        class Cancellation:
            def is_set(self):
                return bool(cancelled and cancelled())
            def wait(self, seconds):
                time.sleep(seconds)

        cancel = Cancellation()
        with self._generation_lock(folder, cancel):
            sync = load_sync_map(folder)
            if sync is None:
                scan = scan_timestamp_gaps(source, ffprobe, cancelled=cancelled)
                if scan.scanned_packets == 0 or scan.negative_jumps:
                    raise RuntimeError("素材时间戳无法可靠映射，已停止任务：" + source)
                sync = scan.map
                save_sync_map(folder, sync)
            receipt['sync_map'] = sync.to_dict()
            if sync.gaps:
                if continuous_proxy_ready(folder) is None:
                    self._build_continuous_proxy_locked(source, Path(source), sync, folder, cancel)
                if cancelled and cancelled():
                    raise InterruptedError("timeline media preparation cancelled")
                proxy = continuous_proxy_ready(folder)
                ok, reason = validate_continuous_proxy(folder, ffprobe,
                    expected_duration_ms=sync.content_duration_ms)
                if proxy is None or not ok:
                    # Preserve the evidence; never recognize/export a different
                    # clock because proxy preparation failed.
                    raise RuntimeError(f"连续时间轴媒体不可用，已停止任务：{source} ({reason})")
                stat = proxy.stat()
                receipt.update(path=str(proxy), kind="continuous_proxy",
                    proxy_identity=dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns),
                    proxy_version=2)
        return receipt

    def next_gap_after(self, source: str, content_ms: int, window_ms: int = 2000):
        """Nearest audio-clock hole within window after content_ms, if any."""
        from .avsync import load_sync_map
        folder = self._cache_folder(str(source))
        if folder is None:
            return None
        sync_map = load_sync_map(folder)
        if sync_map is None:
            return None
        for gap in sync_map.gaps:
            if gap.start_ms - window_ms <= content_ms <= gap.end_ms + 500:
                return gap
        return None

    def _scan_sync_map(self, source: str, target: Path, folder: Path | None = None) -> None:
        from .avsync import scan_timestamp_gaps, save_sync_map
        try:
            from .audio_engine import studio_ffmpeg_path
            ffprobe = studio_ffmpeg_path().with_name(
                "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            result = scan_timestamp_gaps(target, ffprobe)
            folder = folder or target.parent
            save_sync_map(folder, result.map)
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "av_sync_scan",
                "status": result.status, "events": result.event_count,
                "total_gap_ms": result.map.total_gap_ms,
            })
            if result.map.gaps:
                self._schedule_continuous_proxy(source, target, result.map, folder)
        except Exception as exc:
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "av_sync_scan_failed",
                "error": str(exc)[-300:],
            })
        finally:
            with self._lock:
                self._sync_scans.pop(source, None)
                self._sync_scan_done.add(source)

    def _schedule_continuous_proxy(self, source: str, target: Path, sync_map, folder: Path | None = None) -> None:
        """Fold the joint gaps into a packet-identical continuous preview copy."""
        from .avsync import build_continuous_proxy, continuous_proxy_ready
        folder = folder or target.parent
        if continuous_proxy_ready(folder) is not None:
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
            args=(source, target, sync_map, folder),
            daemon=True,
            name="studio-continuous-proxy",
        ).start()

    def _build_continuous_proxy(self, source: str, target: Path, sync_map, folder: Path | None = None) -> None:
        folder = folder or target.parent
        from .storage_service import safe_path
        if not safe_path(folder, (self.root,)):
            with self._lock:
                self._proxy_builds.pop(source, None)
            return
        folder.mkdir(parents=True, exist_ok=True)
        cancel = threading.Event()
        with self._lock:
            self._cancel_events['proxy:' + source] = cancel
        try:
            with self._generation_lock(folder, cancel):
                from .avsync import continuous_proxy_ready
                if continuous_proxy_ready(folder) is None:
                    self._build_continuous_proxy_locked(source, target, sync_map, folder, cancel)
        except (OSError, InterruptedError) as exc:
            GLOBAL_STUDIO_TRACE.emit('MEDIA_OPTIMIZE', {'source': source, 'stage': 'proxy_deferred', 'error': str(exc)})
        finally:
            with self._lock:
                self._cancel_events.pop('proxy:' + source, None)
                self._proxy_builds.pop(source, None)

    def _build_continuous_proxy_locked(self, source: str, target: Path, sync_map, folder: Path, cancel) -> None:
        from .avsync import build_continuous_proxy
        started = time.perf_counter()
        try:
            from .avsync import write_continuous_proxy_marker, validate_continuous_proxy
            folder = folder or target.parent
            folder.mkdir(parents=True, exist_ok=True)
            self._check_space(target, folder, copies=2)
            proxy = build_continuous_proxy(target, sync_map, folder / "continuous.mkv", cancelled=cancel.is_set)
            expected_ms = int(sync_map.content_duration_ms or 0)
            ok, reason = validate_continuous_proxy(
                folder, self._ffprobe_path(), expected_duration_ms=expected_ms
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
                folder,
                expected_duration_ms=expected_ms,
                folded_gaps=len(sync_map.gaps),
                folded_ms=sync_map.total_gap_ms,
            )
            source_stat = Path(source).stat()
            (folder/'origin.json').write_text(json.dumps(dict(producer='indexed_media',
                source=source,size=source_stat.st_size,mtime_ns=source_stat.st_mtime_ns,
                purpose='timestamp-gap-folding',created_at=time.time(),
                parameters=dict(codec='copy',folded_gaps=len(sync_map.gaps),folded_ms=sync_map.total_gap_ms))),encoding='utf-8')
            self._register_media(proxy, source, "timestamp-gap-folding")
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
                if not isinstance(exc, InterruptedError):
                    self._proxy_failures.add(source)
            GLOBAL_STUDIO_TRACE.emit("MEDIA_OPTIMIZE", {
                "source": source, "stage": "continuous_proxy_cancelled" if isinstance(exc, InterruptedError) else "continuous_proxy_failed",
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

        Explicit compatibility consumers may wait while the remux streams the
        file once. Direct audio decoding never waits for this copy. Non-FLV
        media keeps its source path.
        """
        source = str(source)
        current = self.resolve(source, reason="compatibility-stream-copy")
        if not source.lower().endswith(".flv"):
            return source
        deadline = time.monotonic() + float(timeout) if timeout else None
        while True:
            if cancelled and cancelled():
                with self._lock:
                    event = self._cancel_events.get(source)
                    if event is not None:
                        event.set()
                    else:
                        self._cancelled_sources.add(source)
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
            pending = {source for source in self._requested
                       if self._status.get(source, {}).get('state') == 'PENDING'}
            self._cancelled_sources.update(pending)
        for event in events:
            event.set()
        return len(events) + len(pending)

    # ------------------------------------------------------------- worker

    def _run(self):
        while True:
            source = self._queue.get()
            cancel_event = threading.Event()
            with self._lock:
                self._cancel_events[source] = cancel_event
                self._status[source] = dict(self._status.get(source) or {}, state="RUNNING")
                if source in self._cancelled_sources:
                    cancel_event.set()
            try:
                target = self._prepare(Path(source), cancel_event)
                try:
                    stat = Path(source).stat()
                    source_identity = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    source_identity = None  # Keep the now-unique validated copy.
                with self._lock:
                    self._ready[source] = str(target)
                    if source_identity is not None:
                        self._ready_identities[source] = source_identity
                    self._status[source] = {
                        "state": "READY", "progress": 1.0,
                        "container": target.suffix.lstrip(".").lower(),
                        "target": str(target),
                    }
            except Exception as exc:
                self.errors[source] = str(exc)
                with self._lock:
                    self._status[source] = {
                        "state": "CANCELLED" if isinstance(exc, InterruptedError) else "FAILED",
                        "progress": 0.0, "error": str(exc),
                    }
            finally:
                with self._lock:
                    self._cancel_events.pop(source, None)
                    self._cancelled_sources.discard(source)
                self._queue.task_done()

    def _set_progress(self, source: str, progress: float, state: str = "RUNNING") -> None:
        with self._lock:
            self._status[source] = dict(self._status.get(source) or {},
                                        state=state, progress=max(0.0, min(0.999, float(progress))))

    # ------------------------------------------------------------- prepare

    @staticmethod
    def _check_space(source: Path, folder: Path, *, copies: int = 1) -> None:
        required = source.stat().st_size * copies + 64 * 1024 * 1024
        if shutil.disk_usage(folder).free < required:
            raise OSError(f"中间媒体空间不足：预计需要 {required} 字节")

    def _register_media(self, target: Path, source: str, purpose: str) -> None:
        key = str(target)
        now = time.monotonic()
        if now - self._media_touched.get(key, -60) < 30:
            return
        from .storage_service import register_cache, touch_cache
        try:
            register_cache(target, "media", source=source, producer="indexed_media",
                           rebuild="local")
            touch_cache(target)
        except Exception as exc:
            # A storage-index failure does not require a second full remux.
            # The validated manifest remains recoverable and the unknown
            # leaf stays protected until registration succeeds on next use.
            GLOBAL_STUDIO_TRACE.emit('MEDIA_OPTIMIZE', {'source': source,
                'stage': 'storage_registration_failed', 'error': str(exc)[-300:]})
            return
        self._media_touched[key] = now

    @contextmanager
    def _generation_lock(self, folder: Path, cancel_event: threading.Event):
        """Only one process may generate this identity; stale owners are checked."""
        import psutil
        lock = folder / "generation.lock"
        process = psutil.Process()
        owner = {"pid": process.pid, "create_time": process.create_time()}
        while True:
            if cancel_event.is_set():
                raise InterruptedError("optimized media cancelled")
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(owner, stream)
                break
            except FileExistsError:
                try:
                    previous = json.loads(lock.read_text(encoding="utf-8"))
                    alive = abs(psutil.Process(int(previous["pid"])).create_time()
                                - float(previous["create_time"])) < .01
                except psutil.NoSuchProcess:
                    alive = False
                except FileNotFoundError:
                    continue
                except (KeyError, ValueError, OSError):
                    # A newly created lock may not have its payload yet. An
                    # unreadable old owner cannot safely be assumed dead.
                    if time.time() - lock.stat().st_mtime >= 5:
                        raise RuntimeError('无法确认中间媒体生成锁归属，请查看存储详情')
                    alive = True
                if not alive:
                    lock.unlink(missing_ok=True)
                    continue
                cancel_event.wait(.05)
        try:
            yield
        finally:
            try:
                if json.loads(lock.read_text(encoding="utf-8")) == owner:
                    lock.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

    def _prepare(self, source: Path, cancel_event: threading.Event) -> Path:
        folder = self._cache_folder(str(source))
        if folder is None:
            raise FileNotFoundError(source)
        from .storage_service import safe_path
        if not safe_path(folder, (self.root,)):
            raise OSError('中间媒体目录包含越界链接，无法生成缓存')
        folder.mkdir(parents=True, exist_ok=True)
        with self._generation_lock(folder, cancel_event):
            return self._prepare_locked(source, cancel_event)

    def _prepare_locked(self, source: Path, cancel_event: threading.Event) -> Path:
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
            self._register_media(legacy, str(source), "compatibility-stream-copy")
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
                    self._register_media(warm, str(source), "compatibility-stream-copy")
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
        self._check_space(source, folder)
        for stale in folder.glob("optimized.*.partial.*"):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
        started = time.perf_counter()
        last_error = ""
        for index, container in enumerate(order):
            if cancel_event.is_set():
                raise InterruptedError("optimized media cancelled")
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
                    'producer': 'indexed_media', 'purpose': 'compatibility-stream-copy',
                    'created_at': time.time(),
                    'parameters': {'copyts': True, 'start_at_zero': True,
                                   'video': '0:v:0?', 'audio': '0:a?', 'codec': 'copy'},
                }), encoding="utf-8")
                self._register_media(target, str(source), "compatibility-stream-copy")
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
        old_streams = [(s['codec_type'], float(s.get('start_time', old_start)) - old_start)
                       for s in original['streams'] if s['codec_type'] in {'video', 'audio'}]
        new_streams = [(s['codec_type'], float(s.get('start_time', new_start)) - new_start)
                       for s in indexed['streams'] if s['codec_type'] in {'video', 'audio'}]
        if len(old_streams) != len(new_streams) or any(
                kind != new_kind or abs(t - new_t) > .05
                for (kind, t), (new_kind, new_t) in zip(old_streams, new_streams)):
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


# ------------------------------------------------- audio seek copy helpers
AUDIO_SEEK_COPY_NAME = "audio-seek.mka"
AUDIO_SEEK_MARKER_NAME = "audio-seek.json"
# Bump when the copy or its time mapping changes; older copies are rebuilt.
AUDIO_SEEK_COPY_VERSION = 1


def audio_seek_copy_ready(folder: Path, source: str) -> dict | None:
    folder = Path(folder)
    try:
        marker = json.loads((folder / AUDIO_SEEK_MARKER_NAME).read_text(encoding="utf-8"))
        stat = Path(source).stat()
        copy = folder / AUDIO_SEEK_COPY_NAME
        if (int(marker.get("generator_version") or 0) != AUDIO_SEEK_COPY_VERSION
                or int(marker.get("source_size") or -1) != stat.st_size
                or int(marker.get("source_mtime_ns") or -1) != stat.st_mtime_ns
                or copy.stat().st_size != int(marker.get("size_bytes") or -1)):
            return None
        return {"path": str(copy), "offset_ms": int(marker.get("offset_ms") or 0)}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _probe_times(ffprobe: Path, path) -> dict:
    result = run_hidden_subprocess(
        [str(ffprobe), "-v", "error", "-show_entries",
         "format=start_time,duration:stream=index,codec_type,start_time",
         "-of", "json", str(path)],
        purpose="probe audio seek copy times", capture_output=True, timeout=120, check=False)
    payload = json.loads(result.stdout or "{}")
    fmt = payload.get("format") or {}
    audio = next((s for s in payload.get("streams") or () if s.get("codec_type") == "audio"), {})
    def ms(value):
        try:
            return float(value) * 1000.0
        except (TypeError, ValueError):
            return None
    return {"start_ms": ms(fmt.get("start_time")), "duration_ms": ms(fmt.get("duration")),
            "audio_start_ms": ms(audio.get("start_time")),
            "streams": [s.get("codec_type") for s in payload.get("streams") or ()]}


def build_audio_seek_copy(source: str, folder: Path, ffmpeg: Path, ffprobe: Path, *, cancelled=None) -> dict:
    """Stream-copy the first audio stream into an indexed Matroska file.

    Packets are copied byte for byte with their original timestamps
    (``-copyts``, no genpts, no resampling, no fixed delay), so the copy's
    audio at source time T is exactly the original's audio at T; the marker
    stores the container-start offset that keeps ``-ss`` in that domain.
    """
    folder = Path(folder)
    source_path = Path(source)
    stat = source_path.stat()
    required = stat.st_size // 10 + 64 * 1024 * 1024
    if shutil.disk_usage(folder).free < required:
        raise OSError(f"中间媒体空间不足：预计需要 {required} 字节")
    original = _probe_times(ffprobe, source_path)
    if "audio" not in original["streams"] or original["start_ms"] is None:
        raise ValueError("no audio stream or container start time")
    partial = folder / f".audio-seek.{os.getpid()}.partial.mka"
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(source_path), "-map", "0:a:0", "-c", "copy", "-copyts",
               "-avoid_negative_ts", "disabled", "-f", "matroska", str(partial)]
    process = popen_hidden_subprocess(command, purpose="audio seek copy",
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while process.poll() is None:
            if cancelled is not None and cancelled():
                process.kill()
                raise InterruptedError("audio seek copy cancelled")
            time.sleep(0.2)
        error = (process.stderr.read() if process.stderr else b"").decode("utf-8", "replace")
        if process.returncode != 0 or not partial.is_file():
            raise RuntimeError(f"audio seek copy failed ({process.returncode}): {error[-300:]}")
        copied = _probe_times(ffprobe, partial)
        if copied["streams"] != ["audio"] or copied["start_ms"] is None or copied["duration_ms"] is None:
            raise ValueError(f"audio seek copy probe mismatch: {copied}")
        expected_start = original["audio_start_ms"]
        if expected_start is not None and abs(copied["start_ms"] - expected_start) > 2.0:
            raise ValueError(f"audio seek copy start {copied['start_ms']} != {expected_start}")
        if original["duration_ms"] is not None:
            source_end = original["start_ms"] + original["duration_ms"]
            copy_end = copied["start_ms"] + copied["duration_ms"]
            if abs(copy_end - source_end) > 1500.0:
                raise ValueError(f"audio seek copy ends at {copy_end} vs source {source_end}")
        target = folder / AUDIO_SEEK_COPY_NAME
        os.replace(partial, target)
        marker = {
            "generator_version": AUDIO_SEEK_COPY_VERSION,
            "source": str(source_path), "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns,
            "container_start_ms": round(original["start_ms"], 3),
            "copy_start_ms": round(copied["start_ms"], 3),
            "offset_ms": int(round(original["start_ms"] - copied["start_ms"])),
            "duration_ms": round(copied["duration_ms"], 3),
            "size_bytes": target.stat().st_size, "created_at": time.time(),
            "parameters": {"codec": "copy", "copyts": True, "stream": "0:a:0"},
        }
        temporary = folder / f".{AUDIO_SEEK_MARKER_NAME}.tmp"
        temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, folder / AUDIO_SEEK_MARKER_NAME)
        return marker
    finally:
        if process.poll() is None:
            process.kill()
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass


GLOBAL_INDEXED_MEDIA = IndexedMediaCache()
