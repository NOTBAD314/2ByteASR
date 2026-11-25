"""Controlled yt-dlp subprocesses and exact-track downloads, independent of Qt."""
from __future__ import annotations
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid

from .link_catalog import public_track, video_catalog, youtube_url, media_url, safe_video_filename, YOUTUBE_HOSTS
from .link_authorization import SiteAuthorization, from_netscape, private_request_directory
from .link_manifest import (MANIFEST_NAME, atomic_json, file_receipt, load_manifest, preserve_subtitle,
                            refine_saved_subtitle, resolve_relative)
from .link_reconstruction import MODES
from .link_subtitles import MAX_BYTES
from .link_tools import DownloadCancelled, check_cancel, ensure_tools
from ..system.processes import popen_hidden_subprocess, stop_process_tree, sanitized_child_environment


def redact(value) -> str:
    text = re.sub(r"https?://[^\s\"'<>]+", "[网络地址已隐藏]", str(value))
    text = re.sub(r"(?i)(cookie|authorization|token|password|signature|sig)\s*[:=]\s*\S+", r"\1=[隐藏]", text)
    return text[:1600]


class LinkDownloadError(RuntimeError):
    def __init__(self, message, category="download", *, subtitle_related=False):
        super().__init__(redact(message))
        self.category = category
        self.subtitle_related = subtitle_related


def classify_error(value: str) -> LinkDownloadError:
    text = value.lower()
    cases = (
        (("unsupported url", "no suitable extractor"), "unsupported", "下载工具暂不支持此链接，请使用单个视频的页面链接，或检查更新下载工具。"),
        (("412", "precondition failed", "risk control"), "restricted", "网站暂时拦截了请求，请稍后重试。"),
        (("429", "too many requests", "rate-limit"), "rate_limit", "访问过于频繁，请稍后重试。"),
        (("cookie has expired", "cookies have expired", "cookies are no longer valid"), "expired", "浏览器授权可能已过期。请在网站重新登录并授权。"),
        (("private video", "geo", "copyright", "members-only"), "restricted", "当前账号或地区无权观看，或视频已被移除。"),
        (("sign in", "login", "cookies", "confirm you"), "login", "网站要求登录。请用浏览器助手授权，或选择此网站的 Cookie 文件。"),
        (("403", "forbidden"), "forbidden", "网站拒绝了请求（HTTP 403）。请在浏览器确认视频可访问，再重新获取。"),
        (("proxyerror", "proxy connection", "unable to connect to proxy"), "proxy", "无法连接代理。请检查下载设置中的代理地址。"),
        (("no space left", "not enough space", "winerror 112"), "disk", "保存位置的磁盘空间不足。"),
        (("file name too long", "filename too long", "winerror 206"), "path_length", "保存路径太长，请选择较短的下载位置。"),
        (("permission denied", "access is denied", "winerror 5", "read-only file system"), "directory", "保存位置不可写入，请选择有写入权限的目录。"),
        (("ffmpegpostprocessor", "error opening output", "conversion failed", "error merging"), "merge", "FFmpeg 无法合并音视频。请检查下载工具和保存位置。"),
        (("javascript runtime", "no supported javascript"), "runtime", "缺少可用的 JavaScript 运行库。请在工具页检查程序自带 Node。"),
        (("challenge solver", "yt-dlp-ejs", "challenge solving failed"), "ejs", "网站验证未完成。请检查下载工具及其 EJS 组件。"),
        (("unavailable", "not available"), "restricted", "视频不可访问，请在浏览器检查原链接。"),
        (("certificate", "ssl"), "tls", "证书验证失败，请检查应用网络与证书配置。"),
        (("timed out", "resolve", "connection", "network", "unreachable"), "network", "网络不可达或超时，请检查连接与代理后重试。"),
        (("javascript", "ejs", "ffmpeg", "not found", "unknown option"), "dependency", "下载工具或运行库不可用，请检查/修复下载工具。"),
        (("requested format", "format is not available"), "format_unavailable", "所选格式已不可用，请重新解析并选择格式。"),
    )
    for keys, category, message in cases:
        if any(key in text for key in keys):
            return LinkDownloadError(message, category, subtitle_related=bool(re.search(r"subtitle|caption", text)))
    return LinkDownloadError("下载未完成。请检查视频链接、网络和下载工具后重试。",
        subtitle_related=bool(re.search(r"subtitle|caption", text)))


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
    with (private_request_directory() if proxy or cookie_file else nullcontext()) as temporary:
        if proxy or cookie_file:
            settings = []
            if cookie_file:
                auth = _authorization(cookie_file, args[-1])
                payload = auth.netscape(args[-1])
                if not payload:
                    raise LinkDownloadError("网站授权已过期，请重新授权。", "expired")
                cookie_copy = temporary / "cookies.txt"
                cookie_copy.write_bytes(payload)
                cookie_file = str(cookie_copy)
            for key, value in (("--proxy", proxy), ("--cookies", cookie_file)):
                if value:
                    if "\n" in value or "\r" in value:
                        raise ValueError("代理或 Cookie 路径不能包含换行。")
                    settings.append(key+" "+json.dumps(str(value).replace("\\", "/"), ensure_ascii=False))
            config = temporary/"request.conf"
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
                    # Error classification stays in memory; never persist subprocess stderr.
                    errors.append(line.strip())
                    errors = errors[-30:]
                    if notify and ("[Merger]" in line or "[Fixup" in line):
                        notify(dict(stage="merging"))
            if process.wait() != 0:
                raise classify_error("\n".join(errors))
            warnings = ["warning subtitle" for line in errors
                if re.search(r"(?i)warning|error", line) and re.search(r"(?i)subtitle|caption|po.token", line)]
            return "".join(output), warnings
        finally:
            done.set()
            if process.poll() is None:
                stop_process_tree(process)
            for reader in readers:
                reader.join(timeout=1)


IMAGE_LIMIT = 2 * 1024 * 1024


def _authorization(value, url):
    if isinstance(value, SiteAuthorization):
        return value
    with Path(value).open("rb") as stream:
        return from_netscape(url, stream.read(512 * 1024 + 1))


def _reuse_download(task, root, manifest, cancel):
    source = Path(task["reuse_from"]).resolve()
    if root == source:
        return
    try:
        previous = load_manifest(source / MANIFEST_NAME, verify_media=True)
    except (OSError, KeyError, ValueError):
        return
    if (not previous.get("public_download") or previous["source_url"] != task["url"]
            or previous["video_id"] != task["video_id"]
            or previous.get("platform") != task.get("platform")):
        return
    media = previous.get("media")
    formats = [str(row["format_id"]) for row in previous.get("selected_formats", [])]
    selected = list(filter(None, (task.get("video_format"), task.get("audio_format"))))
    if task["mode"] != "subtitles" and not manifest["media"] and media and formats == selected:
        check_cancel(cancel)
        old = resolve_relative(source, media["path"])
        candidate = root / old.name
        staging = candidate.with_name(candidate.name + ".reuse")
        try:
            with old.open("rb") as reader, staging.open("wb") as writer:
                for block in iter(lambda: reader.read(4 * 1024 * 1024), b""):
                    check_cancel(cancel)
                    writer.write(block)
            receipt = file_receipt(root, staging)
            if receipt["sha256"] == media["sha256"] and not candidate.exists():
                os.replace(staging, candidate)
                manifest["media"] = dict(receipt, path=candidate.name)
                manifest["selected_formats"] = previous["selected_formats"]
                manifest["audio_language"] = previous.get("audio_language", "")
        finally:
            staging.unlink(missing_ok=True)
    existing = {sub["track"]["track_id"] for sub in manifest["subtitles"]}
    for subtitle in previous["subtitles"]:
        track = subtitle["track"]
        if track["track_id"] not in task["track_ids"] or track["track_id"] in existing:
            continue
        check_cancel(cancel)
        path = resolve_relative(source, subtitle["original"]["path"])
        raw = path.read_bytes()
        manifest["subtitles"].append(preserve_subtitle(root, track, raw, subtitle["actual_format"],
            mode=task.get("subtitle_mode", "smart"), keep_sound=task.get("keep_sound", True)))


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
    from urllib.parse import urlsplit
    url = media_url(url)
    if urlsplit(url).hostname not in YOUTUBE_HOSTS:
        # Other extractors supply title/cover with the full result. Do not
        # contact YouTube or fail the quick-card worker for another website.
        return {}
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
        options = dict(cancel=cancel, notify=notify, proxy=proxy)
        if not cookie_file:
            return self._analyze(url, **options)
        try:
            anonymous = self._analyze(url, **options)
            if anonymous["subtitle_status"] != "incomplete":
                return anonymous
        except LinkDownloadError as exc:
            if exc.category not in {"login", "expired", "restricted"}:
                raise
        auth = _authorization(cookie_file, url)
        if not auth.valid_for(url):
            raise LinkDownloadError("当前视频的授权已失效，请重新授权。", "expired")
        catalog = self._analyze(url, cookie_file=auth, **options)
        catalog["used_authorization"] = True
        return catalog

    def _analyze(self, url, *, cancel=None, notify=None, proxy="", cookie_file=""):
        url = media_url(url)
        if notify:
            notify(dict(stage="parsing"))
        tools = self.ready(cancel, notify, proxy)
        if notify:
            notify(dict(stage="parsing"))
        options = dict(cancel=cancel, notify=notify, proxy=proxy, cookie_file=cookie_file, timeout=180)
        subtitle_failed = False
        try:
            output, warnings = run_ytdlp(tools, [
                "--simulate", "--write-subs", "--write-auto-subs", "--flat-playlist",
                "--dump-single-json", "--", url], **options)
        except LinkDownloadError as exc:
            # Some extractors fetch inline subtitles during metadata extraction
            # and abort it if that endpoint fails. Retry once without subtitles
            # so the available video is still offered; never hide the warning.
            if not exc.subtitle_related:
                raise
            check_cancel(cancel)
            subtitle_failed = True
            output, warnings = run_ytdlp(tools, [
                "--simulate", "--no-write-subs", "--no-write-auto-subs", "--flat-playlist",
                "--dump-single-json", "--", url], **options)
        try:
            info = json.loads(output)
            if not isinstance(info, dict):
                raise ValueError("下载器没有返回单个视频信息。")
            incomplete = subtitle_failed or any(re.search(r"(?i)warning|error", warning) and
                re.search(r"(?i)subtitle|caption|po.token", warning) for warning in warnings)
            return video_catalog(info, subtitle_warning=incomplete, source_url=url)
        except (ValueError, KeyError, TypeError) as exc:
            raise LinkDownloadError(f"视频信息解析失败：{exc}", "parse") from exc

    def _subtitle_bytes(self, representation, *, cancel, proxy, cookie_file):
        check_cancel(cancel)
        if isinstance(representation.get("data"), str):
            raw = representation["data"].encode("utf-8")
            if len(raw) > MAX_BYTES:
                raise LinkDownloadError("字幕超过 32 MiB。", "parse")
            return raw
        from ..providers.network_policy import request
        headers = {key: value for key, value in (representation.get("http_headers") or {}).items()
                   if key.lower() in {"user-agent", "accept", "accept-language"}}
        kwargs = dict(stream=True, timeout=(15, 20), headers=headers)
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        if isinstance(cookie_file, SiteAuthorization) and representation["url"].startswith("https://"):
            kwargs["cookies"] = cookie_file.jar(cookie_file.url)
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
        media_url(task["url"])
        platform = task.get("platform") or "Youtube"  # existing persisted tasks
        root = Path(task["directory"]).resolve()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise classify_error(str(exc)) from None
        manifest_path = root/MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else dict(
            version=1, task_id=task["task_id"], platform=platform, video_id=task["video_id"],
            source_url=task["url"], title=task.get("title", task["video_id"]), media=None, subtitles=[],
            primary_track_id=task.get("primary_track_id", ""), translation_track_id=task.get("translation_track_id", ""),
            timing_basis="media_elapsed_ms", container_offset_applied=False, stages=[], errors=[])
        if (manifest["task_id"] != task["task_id"] or manifest["video_id"] != task["video_id"]
                or manifest.get("platform", "Youtube").lower() != platform.lower()):
            raise LinkDownloadError("任务目录身份不一致，未覆盖文件。", "identity")
        manifest["errors"] = []
        manifest["public_download"] = bool(task.get("public_download") and not cookie_file)
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
            def check_identity(value):
                if (value["video_id"] != task["video_id"] or
                        value.get("platform", "Youtube").lower() != platform.lower()):
                    raise LinkDownloadError("视频或分 P 身份已变化，请重新解析；未下载或混用其他视频的字幕。", "identity")
            check_identity(catalog)
            effective_cookie = _authorization(cookie_file, task["url"]) if cookie_file and catalog.get("used_authorization") else ""
            manifest["subtitle_status"] = catalog.get("subtitle_status", "incomplete")
            manifest["tools"] = self.ready()["versions"]
            if manifest["public_download"] and task.get("reuse_from"):
                _reuse_download(task, root, manifest, cancel)
            audio_only = task["mode"] == "audio"
            wanted_formats = [str(task.get(k) or "") for k in ("video_format", "audio_format")]
            if audio_only:
                wanted_formats[0] = ""
            available = {str(f["format_id"]): f for f in catalog["formats"]}
            media_receipt = manifest.get("media")
            if media_receipt:
                final = resolve_relative(root, media_receipt["path"])
                if not final.is_file() or final.stat().st_size != media_receipt["bytes"]:
                    manifest["media"] = None
            if task["mode"] != "subtitles" and not subtitles_only and not manifest.get("media"):
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
                    "--output", str(root).replace("%", "%%")+"/"+safe_video_filename(task["video_id"])+".%(ext)s",
                    # Native JSON keeps missing fields valid (individual templates
                    # otherwise emit bare NA). run_ytdlp whitelists numeric fields.
                    "--progress-template", "download:2BYTE_PROGRESS:%(progress)j",
                    "--progress-template", "postprocess:2BYTE_POST:%(progress.postprocessor)s",
                    "--print", "after_move:2BYTE_FILE:%(filepath)j", "--", task["url"]],
                    cancel=cancel, notify=event, proxy=proxy, cookie_file=effective_cookie)
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
                            check_identity(catalog)
                            effective_cookie = _authorization(cookie_file, task["url"]) if cookie_file and catalog.get("used_authorization") else ""
                        track = next((t for t in catalog["tracks"] if t["track_id"] == track_id), None)
                        if track is None:
                            last_error = LinkDownloadError("选定字幕轨已不可用，请重新解析。", "subtitle_unavailable")
                            break
                        for representation in track["representations"]:
                            check_cancel(cancel)
                            try:
                                event(dict(stage="subtitles", track_id=track_id))
                                raw = self._subtitle_bytes(representation, cancel=cancel, proxy=proxy, cookie_file=effective_cookie)
                                event(dict(stage="organizing", track_id=track_id))
                                sub = preserve_subtitle(root, track, raw, representation["ext"],
                                    mode=task.get("subtitle_mode", "smart"), keep_sound=task.get("keep_sound", True))
                                manifest["subtitles"].append(sub)
                                existing[track_id] = sub
                                atomic_json(manifest_path, manifest)
                                last_error = None
                                break
                            except DownloadCancelled:
                                raise
                            except Exception as exc:
                                last_error = exc if isinstance(exc, LinkDownloadError) else (
                                    LinkDownloadError(str(exc), "parse") if isinstance(exc, ValueError)
                                    else classify_error(str(exc)))
                                if last_error.category == "rate_limit":
                                    if not attempt:
                                        for _ in range(15):
                                            check_cancel(cancel)
                                            time.sleep(.2)
                                    break
                        if track_id in existing:
                            break
                    if last_error:
                        manifest["errors"].append(dict(track_id=track_id, category=last_error.category, message=str(last_error)))
            if task.get("subtitle_mode") == "ai" and manifest["subtitles"]:
                primary_id = task.get("primary_track_id") or task["track_ids"][0]
                primary = next((receipt for receipt in manifest["subtitles"]
                                if receipt["track"]["track_id"] == primary_id), None)
                if primary:
                    event(dict(stage="ai_refining"))
                    refine_saved_subtitle(root, primary, cancel=cancel, progress=lambda update: event(
                        dict(stage="ai_refining", detail=update.get("phase", ""))))
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
              track_ids=(), primary_track_id="", translation_track_id="", target=None, auto_import=True,
              subtitle_mode="smart", keep_sound=True, recognize=False) -> dict:
    if mode not in {"both", "video", "audio", "subtitles"}:
        raise ValueError("无效下载模式。")
    if subtitle_mode not in MODES:
        raise ValueError("无效的在线字幕处理模式。")
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
    root = Path(directory).expanduser().resolve() / (safe_video_filename(catalog["video_id"])+"-"+task_id[:12])
    return dict(task_id=task_id, video_id=catalog["video_id"], platform=catalog.get("platform", "Youtube"),
        url=catalog["url"], title=catalog["title"],
        directory=str(root), mode=mode, video_format=video_format, audio_format=audio_format,
        subtitle_mode=subtitle_mode, keep_sound=bool(keep_sound), recognize=bool(recognize),
        track_ids=chosen, selected_tracks=[public_track(t) for t in catalog["tracks"] if t["track_id"] in chosen],
        primary_track_id=primary_track_id if chosen else "", translation_track_id=translation_track_id if chosen else "",
        target=copy.deepcopy(target or {}), auto_import=bool(auto_import), state="queued")
