"""Controlled yt-dlp subprocesses and exact-track downloads, independent of Qt."""
from __future__ import annotations
import copy
import http.cookiejar
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import shutil
import tempfile
import threading
import time
import uuid

from .link_catalog import public_track, video_catalog, youtube_url
from .link_manifest import MANIFEST_NAME, atomic_json, file_receipt, preserve_subtitle, resolve_relative
from .link_subtitles import MAX_BYTES
from .link_tools import DownloadCancelled, check_cancel, ensure_tools
from ..system.processes import popen_hidden_subprocess, stop_process_tree, sanitized_child_environment


def redact(value) -> str:
    text = re.sub(r"https?://[^\s\"'<>]+", "[网络地址已隐藏]", str(value))
    text = re.sub(r"(?i)(cookie|authorization|token|password|signature|sig)\s*[:=]\s*\S+", r"\1=[隐藏]", text)
    return text[:1600]


class LinkDownloadError(RuntimeError):
    def __init__(self, message, category="download"):
        super().__init__(redact(message))
        self.category = category


def classify_error(value: str) -> LinkDownloadError:
    text = value.lower()
    cases = (
        (("429", "too many requests", "rate-limit"), "rate_limit", "访问过于频繁，请稍后重试。"),
        (("sign in", "login", "cookies", "confirm you"), "login", "此视频需要登录验证；可在高级设置主动选择 Cookie 文件。"),
        (("private video", "not available", "403", "geo", "copyright", "members-only"), "restricted", "视频存在访问限制，请确认账号与所在区域是否可观看。"),
        (("certificate", "ssl"), "tls", "证书验证失败，请检查应用网络与证书配置。"),
        (("timed out", "resolve", "connection", "network", "unreachable"), "network", "网络不可达或超时，请检查连接与代理后重试。"),
        (("javascript", "ejs", "ffmpeg", "not found", "unknown option"), "dependency", "下载工具或运行库不可用，请检查/修复下载工具。"),
        (("requested format", "format is not available"), "format_unavailable", "所选格式已不可用，请重新解析并选择格式。"),
    )
    for keys, category, message in cases:
        if any(key in text for key in keys):
            return LinkDownloadError(message, category)
    return LinkDownloadError("下载未完成：" + redact(value[-600:]))


def base_arguments(tools: dict) -> list[str]:
    return [tools["ytdlp"], "--ignore-config", "--no-plugin-dirs", "--no-playlist",
        "--no-remote-components", "--no-js-runtimes", "--js-runtimes", "node:"+tools["node"],
        "--ffmpeg-location", str(Path(tools["ffmpeg"]).parent), "--no-cache-dir",
        "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
        "--no-colors", "--newline", "--progress", "--progress-delta", "0.5", "--no-check-formats"]


def run_ytdlp(tools: dict, args: list[str], *, cancel=None, notify=None, proxy="", cookie_file="",
               timeout=3600) -> tuple[str, list[str]]:
    """Drain both pipes, cap output, poll cancellation even while stdout is silent."""
    from ..providers.network_policy import ca_bundle
    env = sanitized_child_environment()
    for key in ("PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "NODE_PATH", "YTDLP_NO_LAZY_EXTRACTORS"):
        env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    env["SSL_CERT_FILE"] = ca_bundle()[0]
    command = base_arguments(tools)
    # Pass opt-in credentials through a short-lived explicit config, never command logs.
    from ..runtime_paths import get_runtime_paths
    temporary_root = get_runtime_paths().user_data_root/"cache/link-download"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="request-", dir=temporary_root) as temporary:
        if proxy or cookie_file:
            settings = []
            if cookie_file:
                cookie_copy = Path(temporary)/"cookies.txt"
                shutil.copyfile(cookie_file, cookie_copy)
                cookie_file = str(cookie_copy)
            for key, value in (("--proxy", proxy), ("--cookies", cookie_file)):
                if value:
                    if "\n" in value or "\r" in value:
                        raise ValueError("代理或 Cookie 路径不能包含换行。")
                    settings.append(key+" "+json.dumps(str(value).replace("\\", "/"), ensure_ascii=False))
            config = Path(temporary)/"request.conf"
            config.write_text("\n".join(settings), encoding="utf-8")
            command += ["--config-locations", str(config)]
        command += list(args)
        process = popen_hidden_subprocess(command, purpose="link download", log_command=[tools["ytdlp"], "[受控下载参数]"], own_process_tree=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            env=env, text=True, encoding="utf-8", errors="replace")
        incoming = queue.Queue(maxsize=256)
        done = threading.Event()

        def read(stream, channel):
            try:
                for line in iter(stream.readline, ""):
                    while not done.is_set():
                        try:
                            incoming.put((channel, line), timeout=.1)
                            break
                        except queue.Full:
                            pass
            finally:
                stream.close()

        readers = [threading.Thread(target=read, args=(stream, name), daemon=True)
                   for stream, name in ((process.stdout, "out"), (process.stderr, "err"))]
        for reader in readers:
            reader.start()
        started, last_progress = time.monotonic(), 0.0
        output, errors, size = [], [], 0
        try:
            while process.poll() is None or any(t.is_alive() for t in readers) or not incoming.empty():
                check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise LinkDownloadError("操作超时，可重试或取消。", "network")
                try:
                    channel, line = incoming.get(timeout=.1)
                except queue.Empty:
                    continue
                if line.startswith("2BYTE_PROGRESS:"):
                    if notify and time.monotonic()-last_progress >= .25:
                        try:
                            raw_progress = json.loads(line.split(":", 1)[1])
                            safe_progress = {k: raw_progress[k] for k in
                                ("downloaded_bytes", "total_bytes", "total_bytes_estimate", "speed", "eta", "status")
                                if k in raw_progress}
                            notify(dict(stage="downloading", progress=safe_progress))
                        except ValueError:
                            pass
                        last_progress = time.monotonic()
                elif line.startswith("2BYTE_POST:"):
                    if notify:
                        notify(dict(stage="merging"))
                elif channel == "out":
                    size += len(line)
                    if size > 32*1024*1024:
                        raise LinkDownloadError("解析输出超过安全上限。", "parse")
                    output.append(line)
                else:
                    errors.append(redact(line.strip()))
                    errors = errors[-30:]
                    if notify and ("[Merger]" in line or "[Fixup" in line):
                        notify(dict(stage="merging"))
            if process.wait() != 0:
                raise classify_error("\n".join(errors))
            return "".join(output), errors
        finally:
            done.set()
            if process.poll() is None:
                stop_process_tree(process)
            for reader in readers:
                reader.join(timeout=1)


IMAGE_LIMIT = 2 * 1024 * 1024


def fetch_image(url: str, *, cancel=None, proxy="", timeout=(5, 8)) -> bytes:
    """A cover image, at most 2 MiB; empty on any failure (covers are optional)."""
    from ..providers.network_policy import request
    try:
        with request("get", url, timeout=timeout, stream=True,
                     **({"proxies": {"http": proxy, "https": proxy}} if proxy else {})) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(64*1024):
                check_cancel(cancel)
                size += len(chunk)
                if size > IMAGE_LIMIT:
                    return b""
                chunks.append(chunk)
            return b"".join(chunks)
    except DownloadCancelled:
        raise
    except Exception:
        return b""


def quick_preview(url: str, *, cancel=None, proxy="") -> dict:
    """Title, channel and cover in well under a second (2026-10-26).

    yt-dlp needs 4-5 s for the formats and subtitles; the Ctrl+V card shows
    this meanwhile. YouTube's public oEmbed answer plus its fixed thumbnail
    address; no cookies, nothing written. Any failure just means no preview."""
    from ..providers.network_policy import request
    from urllib.parse import urlencode
    url, video = youtube_url(url)
    preview = dict(video_id=video, title="", uploader="", thumbnail=b"")
    cover = {}
    fetcher = threading.Thread(daemon=True, name="link-preview-cover", target=lambda: cover.update(
        image=fetch_image(f"https://i.ytimg.com/vi/{video}/mqdefault.jpg", cancel=cancel, proxy=proxy)))
    fetcher.start()   # both requests at once
    try:
        query = urlencode({"url": f"https://www.youtube.com/watch?v={video}", "format": "json"})
        with request("get", "https://www.youtube.com/oembed?" + query, timeout=(4, 5),
                     **({"proxies": {"http": proxy, "https": proxy}} if proxy else {})) as response:
            if response.ok:
                data = response.json()
                preview.update(title=str(data.get("title") or "")[:300],
                               uploader=str(data.get("author_name") or "")[:120])
    except Exception:
        pass
    fetcher.join(timeout=10)
    check_cancel(cancel)
    preview["thumbnail"] = cover.get("image", b"")
    return preview


class DownloadEngine:
    def __init__(self, *, tools=None, root=None):
        self.tools = tools
        self.root = root

    def preview(self, url, *, cancel=None, proxy=""):
        return quick_preview(url, cancel=cancel, proxy=proxy)

    def ready(self, cancel=None, notify=None, proxy=""):
        if self.tools is None:
            self.tools = ensure_tools(cancel=cancel, progress=notify, root=self.root, proxy=proxy)
        return self.tools

    def analyze(self, url, *, cancel=None, notify=None, proxy="", cookie_file=""):
        url, video = youtube_url(url)
        if notify:
            notify(dict(stage="parsing"))
        tools = self.ready(cancel, notify, proxy)
        if notify:
            notify(dict(stage="parsing"))
        output, warnings = run_ytdlp(tools, [
            "--skip-download", "--dump-single-json", "--", url], cancel=cancel, notify=notify,
            proxy=proxy, cookie_file=cookie_file, timeout=180)
        try:
            info = json.loads(output)
            if str(info.get("id")) != video:
                raise ValueError("视频身份与链接不一致。")
            incomplete = any(re.search(r"(?i)subtitle|caption|po.token", warning) for warning in warnings)
            return video_catalog(info, subtitle_warning=incomplete)
        except (ValueError, KeyError, TypeError) as exc:
            raise LinkDownloadError(f"视频信息解析失败：{exc}", "parse") from exc

    def _subtitle_bytes(self, representation, *, cancel, proxy, cookie_file):
        from ..providers.network_policy import request
        kwargs = dict(stream=True, timeout=(15, 20), headers=representation.get("http_headers") or {})
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        if cookie_file:
            jar = http.cookiejar.MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=False)
            kwargs["cookies"] = jar
        with request("get", representation["url"], **kwargs) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(64*1024):
                check_cancel(cancel)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise LinkDownloadError("字幕超过 32 MiB。", "parse")
                chunks.append(chunk)
            return b"".join(chunks)

    def download(self, task: dict, *, cancel=None, notify=None, proxy="", cookie_file="", subtitles_only=False):
        """Retry starts by re-extracting signed endpoints; output resumes in the same task directory."""
        if youtube_url(task["url"])[1] != task["video_id"]:
            raise LinkDownloadError("任务视频身份与来源链接不一致。", "identity")
        root = Path(task["directory"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root/MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else dict(
            version=1, task_id=task["task_id"], platform="Youtube", video_id=task["video_id"],
            source_url=task["url"], title=task.get("title", task["video_id"]), media=None, subtitles=[],
            primary_track_id=task.get("primary_track_id", ""), translation_track_id=task.get("translation_track_id", ""),
            timing_basis="media_elapsed_ms", container_offset_applied=False, stages=[], errors=[])
        if manifest["task_id"] != task["task_id"] or manifest["video_id"] != task["video_id"]:
            raise LinkDownloadError("任务目录身份不一致，未覆盖文件。", "identity")
        manifest["errors"] = []
        begun = time.monotonic()
        stage_started, stage_name = begun, ""

        def event(payload):
            nonlocal stage_started, stage_name
            name = payload.get("stage", "")
            if name != stage_name:
                if stage_name:
                    manifest["stages"].append(dict(stage=stage_name, elapsed_ms=round((time.monotonic()-stage_started)*1000)))
                    manifest["stages"] = manifest["stages"][-80:]
                stage_started, stage_name = time.monotonic(), name
                atomic_json(manifest_path, manifest)
                from ..diagnostics.event_log import emit
                emit("link.download.stage", result=name, task_id=task["task_id"], video_id=task["video_id"],
                     stage=name, track_id=payload.get("track_id", ""),
                     output_file=(manifest.get("media") or {}).get("path", ""),
                     subtitle_count=sum(s.get("cue_count", 0) for s in manifest["subtitles"]))
            if notify:
                notify(dict(payload, task_id=task["task_id"], video_id=task["video_id"]))

        try:
            catalog = self.analyze(task["url"], cancel=cancel, notify=event, proxy=proxy, cookie_file=cookie_file)
            manifest["tools"] = self.ready()["versions"]
            audio_only = task["mode"] == "audio"
            wanted_formats = [str(task.get(k) or "") for k in ("video_format", "audio_format")]
            if audio_only:
                wanted_formats[0] = ""
            available = {str(f["format_id"]): f for f in catalog["formats"]}
            if task["mode"] != "subtitles" and not subtitles_only:
                for selected in filter(None, wanted_formats):
                    if selected not in available:
                        raise LinkDownloadError("所选音视频格式已失效，请重新解析并选择。", "format_unavailable")
                if audio_only and not wanted_formats[1]:
                    raise LinkDownloadError("请选择音轨。", "format_unavailable")
                if not audio_only and not wanted_formats[0]:
                    raise LinkDownloadError("请选择视频格式。", "format_unavailable")
                if (not audio_only and wanted_formats[1]
                        and available[wanted_formats[0]].get("acodec") not in (None, "none")):
                    raise LinkDownloadError("该画质已包含音轨；切换音轨前请选择单独的视频画质。", "format_unavailable")
                format_ids = "+".join(dict.fromkeys(filter(None, wanted_formats)))
                # No recode, subtitle burn-in, section cuts or postprocessing time shift.
                event(dict(stage="downloading"))
                output, _ = run_ytdlp(self.ready(), ["--no-write-subs", "--no-write-auto-subs",
                    "--format", format_ids, "--continue", "--no-overwrites", "--windows-filenames",
                    "--output", str(root).replace("%", "%%")+"/"+task["video_id"]+".%(ext)s",
                    # Native JSON keeps missing fields valid (individual templates
                    # otherwise emit bare NA). run_ytdlp whitelists numeric fields.
                    "--progress-template", "download:2BYTE_PROGRESS:%(progress)j",
                    "--progress-template", "postprocess:2BYTE_POST:%(progress.postprocessor)s",
                    "--print", "after_move:2BYTE_FILE:%(filepath)j", "--", task["url"]],
                    cancel=cancel, notify=event, proxy=proxy, cookie_file=cookie_file)
                paths = [json.loads(line.partition(":")[2]) for line in output.splitlines() if line.startswith("2BYTE_FILE:")]
                if len(paths) != 1:
                    raise LinkDownloadError("下载器没有给出唯一的最终视频路径。", "parse")
                final = Path(paths[0]).resolve()
                if not final.is_relative_to(root) or not final.is_file():
                    raise LinkDownloadError("最终视频路径不属于本任务。", "identity")
                event(dict(stage="verifying"))
                manifest["media"] = file_receipt(root, final)
                manifest["selected_formats"] = [available[f] for f in dict.fromkeys(filter(None, wanted_formats))]
                manifest["audio_language"] = available[wanted_formats[1] or wanted_formats[0]].get("language") or ""
                atomic_json(manifest_path, manifest)
            elif manifest.get("media"):
                final = resolve_relative(root, manifest["media"]["path"])
                if not final.is_file():
                    manifest["media"] = None
            if task["mode"] in ("both", "subtitles"):
                existing = {s["track"]["track_id"]: s for s in manifest["subtitles"]}
                for track_id in task.get("track_ids", []):
                    check_cancel(cancel)
                    if track_id in existing:
                        continue
                    last_error = None
                    for attempt in range(2):
                        if attempt:
                            catalog = self.analyze(task["url"], cancel=cancel, notify=event, proxy=proxy, cookie_file=cookie_file)
                        track = next((t for t in catalog["tracks"] if t["track_id"] == track_id), None)
                        if track is None:
                            last_error = LinkDownloadError("选定字幕轨已不可用，请重新解析。", "subtitle_unavailable")
                            break
                        for representation in track["representations"]:
                            check_cancel(cancel)
                            try:
                                event(dict(stage="subtitles", track_id=track_id))
                                raw = self._subtitle_bytes(representation, cancel=cancel, proxy=proxy, cookie_file=cookie_file)
                                event(dict(stage="organizing", track_id=track_id))
                                sub = preserve_subtitle(root, track, raw, representation["ext"])
                                manifest["subtitles"].append(sub)
                                existing[track_id] = sub
                                atomic_json(manifest_path, manifest)
                                last_error = None
                                break
                            except DownloadCancelled:
                                raise
                            except Exception as exc:
                                last_error = classify_error(str(exc)) if not isinstance(exc, ValueError) else LinkDownloadError(str(exc), "parse")
                        if track_id in existing:
                            break
                    if last_error:
                        manifest["errors"].append(dict(track_id=track_id, category=last_error.category, message=str(last_error)))
            manifest["status"] = "partial" if manifest["errors"] else "completed"
            event(dict(stage=manifest["status"]))
            return str(manifest_path)
        except DownloadCancelled:
            manifest["status"] = "cancelled"
            raise
        except Exception as exc:
            manifest["status"] = "partial" if manifest.get("media") or manifest["subtitles"] else "failed"
            error = exc if isinstance(exc, LinkDownloadError) else classify_error(str(exc))
            manifest["errors"].append(dict(category=error.category, message=str(error)))
            raise error
        finally:
            if stage_name:
                manifest["stages"].append(dict(stage=stage_name, elapsed_ms=round((time.monotonic()-stage_started)*1000)))
            manifest["elapsed_ms"] = round((time.monotonic()-begun)*1000)
            atomic_json(manifest_path, manifest)


def make_task(catalog: dict, directory: str, *, mode="both", video_format="", audio_format="",
              track_ids=(), primary_track_id="", translation_track_id="", target=None, auto_import=True) -> dict:
    if mode not in {"both", "video", "audio", "subtitles"}:
        raise ValueError("无效下载模式。")
    chosen = list(dict.fromkeys(track_ids)) if mode in ("both", "subtitles") else []
    if mode in ("video", "audio"):
        primary_track_id = translation_track_id = ""
    if mode == "audio":
        if not audio_format:
            raise ValueError("仅音频需要选择一条音轨。")
        video_format = ""
    allowed = {t["track_id"] for t in catalog["tracks"]}
    if set(chosen)-allowed or (primary_track_id and primary_track_id not in chosen) or (
            translation_track_id and translation_track_id not in chosen):
        raise ValueError("请选择当前视频提供的字幕轨。")
    if mode == "subtitles" and not chosen:
        raise ValueError("仅字幕模式需要选择字幕。")
    task_id = uuid.uuid4().hex
    root = Path(directory).expanduser().resolve() / (catalog["video_id"]+"-"+task_id[:12])
    return dict(task_id=task_id, video_id=catalog["video_id"], url=catalog["url"], title=catalog["title"],
        directory=str(root), mode=mode, video_format=video_format, audio_format=audio_format,
        track_ids=chosen, selected_tracks=[public_track(t) for t in catalog["tracks"] if t["track_id"] in chosen],
        primary_track_id=primary_track_id if chosen else "", translation_track_id=translation_track_id if chosen else "",
        target=copy.deepcopy(target or {}), auto_import=bool(auto_import), state="queued")
