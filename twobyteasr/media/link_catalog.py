"""Single-video link and subtitle identities. Signed subtitle URLs are transient.

Selection adapted from imsyy/yt-dlp-gui SubtitleCard.vue (MIT), revision
e3cd1df342c1dd0f543b309cf305210a588a461c; see licenses/yt-dlp-gui-MIT.txt.
Automatic translations and original ASR are separate sources here.
"""
from __future__ import annotations
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

FORMATS = ("json3", "vtt", "srt")
SOURCES = {"manual": "人工字幕", "automatic": "原语言自动字幕",
           "translated": "自动翻译字幕", "unknown": "来源待确认"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def youtube_url(value: str) -> tuple[str, str]:
    """Accept a single video; discard playlist, tracking and credentials."""
    try:
        u = urlsplit(str(value).strip())
        if u.scheme not in ("https", "http") or u.username or u.password or u.port:
            raise ValueError
        host = (u.hostname or "").lower()
        if host == "youtu.be":
            video = u.path.strip("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            parts = u.path.strip("/").split("/")
            video = (parse_qs(u.query).get("v", [""])[0] if u.path == "/watch"
                     else parts[1] if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"} else "")
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("请粘贴 YouTube 单个视频链接；本轮不支持下载整个播放列表。") from None
    return f"https://www.youtube.com/watch?v={video}", video


YOUTUBE_HOSTS = {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
BILIBILI_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}


def media_url(value: str) -> str:
    """Normalize known single videos; let the extractor validate other websites.

    Keep other sites' queries/fragments: they may identify the requested video.
    Bilibili always selects exactly one part (P1 unless explicitly supplied).
    """
    value = str(value).strip()
    try:
        if not value or len(value) > 8192 or re.search(r"[\s\x00-\x1f\x7f]", value):
            raise ValueError
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            raise ValueError
        _ = u.port  # validate malformed ports
    except (ValueError, TypeError):
        raise ValueError("请粘贴完整的 http(s) 视频链接；不支持本地路径或带账号密码的网址。") from None
    host = u.hostname.lower()
    if host in YOUTUBE_HOSTS:
        return youtube_url(value)[0]
    if host in BILIBILI_HOSTS:
        match = re.fullmatch(r"/video/((?:BV[0-9A-Za-z]{10})|(?:av\d+))/?", u.path)
        if match:
            part = parse_qs(u.query).get("p", ["1"])[-1]
            if not part.isascii() or not part.isdigit() or not 1 <= int(part) <= 10000:
                raise ValueError("Bilibili 分 P 编号无效，请复制该分 P 的视频链接。")
            return f"https://www.bilibili.com/video/{match[1]}?p={int(part)}"
        # Episode URLs also have dedicated extractors. Reject list/home pages
        # before starting a potentially large metadata extraction.
        if not re.fullmatch(r"/bangumi/play/ep\d+/?", u.path):
            raise ValueError("请粘贴 Bilibili 单个视频或分 P 链接；暂不下载整个合集。")
    return urlunsplit(u)


def safe_video_filename(video: str) -> str:
    """Extractor IDs are identifiers, never paths or yt-dlp output templates."""
    if (re.fullmatch(r"[A-Za-z0-9_-]{1,100}", video)
            and not re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", video)):
        return video
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", video)[:60].strip("_") or "video"
    return f"video-{slug}-{digest(video)[:12]}"


def language_matches(left: str, right: str) -> bool:
    return bool(left and right and left.lower().split("-")[0] == right.lower().split("-")[0])


def subtitle_tracks(info: dict) -> list[dict]:
    """Group actual timedtext identities, not display-language keys.

    Translated manual tracks can occur in automatic_captions.
    tlang/kind/lang and stable IDs are evidence; '-orig' alone is not.
    """
    platform, video = str(info.get("extractor_key") or info.get("extractor") or "Youtube"), str(info["id"])
    youtube = platform.lower() == "youtube"
    bilibili = platform.lower().startswith("bilibili")
    groups = {}
    for container in ("subtitles", "automatic_captions"):
        for key, entries in (info.get(container) or {}).items():
            if key == "live_chat" or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("ext") not in FORMATS:
                    continue
                url = str(entry.get("url") or "")
                data = entry.get("data")
                if not isinstance(data, str) and urlsplit(url).scheme not in ("http", "https"):
                    continue
                q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items() if v}
                original = str(entry.get("languageCode") or q.get("lang") or "")
                target = str(q.get("tlang") or entry.get("translation_language") or "")
                kind = str(entry.get("kind") or q.get("kind") or "")
                bili_auto = bilibili and key.startswith("ai-")
                source = ("translated" if target else "automatic" if bili_auto else
                          "manual" if container == "subtitles" else
                          "automatic" if kind == "asr" or not youtube else "unknown")
                language = target or original or (key[3:] if bili_auto else key)
                raw_id = str(entry.get("vssId") or entry.get("id") or q.get("vssId") or "")
                identity = dict(platform=platform, video_id=video, language=language,
                                source=source, original_language=original, kind=kind,
                                raw_id=raw_id, name=q.get("name", ""), xtags=q.get("xtags", ""))
                if not original and not raw_id:
                    identity["unresolved_key"] = key
                track_id = digest(identity)[:24]
                track = groups.setdefault(track_id, dict(identity, track_id=track_id,
                    label=str(entry.get("name") or language), aliases=[], representations=[]))
                if key not in track["aliases"]:
                    track["aliases"].append(key)
                if not any(r["ext"] == entry["ext"] for r in track["representations"]):
                    representation = dict(ext=entry["ext"], url=url, key=key, container=container,
                        http_headers={**(info.get("http_headers") or {}), **(entry.get("http_headers") or {})})
                    if isinstance(data, str):
                        representation["data"] = data
                    track["representations"].append(representation)
    for track in groups.values():
        track["representations"].sort(key=lambda r: FORMATS.index(r["ext"]))
        track["formats"] = [r["ext"] for r in track["representations"]]
        if track["source"] == "translated":
            parents = [p for p in groups.values() if p["source"] in {"manual", "automatic"}
                       and p["original_language"] == track["original_language"]
                       and all(p.get(k) == track.get(k) for k in ("kind", "raw_id", "name", "xtags"))]
            track["parent_track_id"] = parents[0]["track_id"] if len(parents) == 1 else ""
            track["parent_source"] = (parents[0]["source"] if len(parents) == 1
                                      else "automatic" if track["kind"] == "asr" else "unknown")
    return sorted(groups.values(), key=lambda t: (t["language"], t["source"], t["track_id"]))


def public_track(track: dict) -> dict:
    return {k: v for k, v in track.items() if k != "representations"}


def video_catalog(info: dict, *, subtitle_warning: bool = False, source_url: str = "") -> dict:
    if info.get("_type", "video") != "video" or info.get("entries") is not None:
        raise ValueError("解析结果不是所选单个视频。")
    video = str(info.get("id") or "")
    if not video or len(video) > 1024:
        raise ValueError("解析结果缺少有效的视频身份。")
    platform = str(info.get("extractor_key") or info.get("extractor") or "Youtube")
    candidate_url = info.get("webpage_url") or source_url
    if not candidate_url and platform.lower() == "youtube":
        candidate_url = f"https://www.youtube.com/watch?v={video}"
    url = media_url(candidate_url or "")
    if platform.lower() == "youtube":
        if youtube_url(source_url or url)[1] != video:
            raise ValueError("视频身份与链接不一致。")
        url = youtube_url(url)[0]
    elif platform.lower() == "bilibili":
        # The extractor's webpage_url can omit the part query. Its returned ID
        # is BV…_pN; retain this canonical identity for retries and subtitles.
        match = re.fullmatch(r"(BV[0-9A-Za-z]{10})(?:_p(\d+))?", video)
        if match:
            part = int(match[2] or 1)
            if source_url and urlsplit(source_url).hostname in BILIBILI_HOSTS:
                requested = media_url(source_url)
                request_path = urlsplit(requested).path
                if request_path.startswith("/video/BV") and request_path.rsplit("/", 1)[-1] != match[1]:
                    raise ValueError("视频身份与链接不一致。")
                if int(parse_qs(urlsplit(requested).query).get("p", ["1"])[-1]) != part:
                    raise ValueError("解析结果不是所选 Bilibili 分 P。")
            url = f"https://www.bilibili.com/video/{match[1]}?p={part}"
            # A short link to a one-part upload may return BV… while explicit
            # ?p=1 returns BV…_p1. Both must remain the same asset on retry.
            video = f"{match[1]}_p{part}"
            info = dict(info, id=video)
    if info.get("is_live"):
        raise ValueError("正在直播的视频暂不支持；请在直播结束后重试。")
    tracks = subtitle_tracks(info)
    formats = []
    for f in info.get("formats") or ():
        if f.get("has_drm") or f.get("vcodec") == "images" or not f.get("format_id"):
            continue
        if f.get("vcodec") == "none" and f.get("acodec") == "none":
            continue
        # Generic direct media often has no codec metadata until downloaded.
        # Unknown codecs are still selectable, unlike explicit no-audio/video.
        if f.get("vcodec") is None and f.get("acodec") is None:
            if not f.get("url"):
                continue
            audio_only = str(f.get("ext", "")).lower() in {"mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"}
            f = dict(f, vcodec="none" if audio_only else "unknown", acodec="unknown")
        formats.append({k: f.get(k) for k in ("format_id", "ext", "height", "width", "fps",
            "vcodec", "acodec", "filesize", "filesize_approx", "language", "format_note", "abr",
            "audio_channels", "language_preference")})
    return dict(url=url, video_id=video, platform=platform,
                title=str(info.get("title") or video), duration=float(info.get("duration") or 0),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                upload_date=str(info.get("upload_date") or ""),
                language=str(info.get("language") or ""), thumbnail=str(info.get("thumbnail") or ""),
                formats=formats, tracks=tracks,
                subtitle_status="incomplete" if (subtitle_warning or (platform.lower() == "youtube" and (
                    not isinstance(info.get("subtitles"), dict) or not isinstance(info.get("automatic_captions"), dict))))
                    else "available" if tracks else "none")


def preferred_track(catalog: dict, preferences=()) -> str:
    tracks = catalog["tracks"]
    for lang in (catalog.get("language", ""), *preferences):
        candidates = [t for t in tracks if language_matches(t["language"], lang)
                      and t["source"] in ("manual", "automatic")]
        if candidates:
            return min(candidates, key=lambda t: t["source"] != "manual")["track_id"]
    original = [t for t in tracks if t["source"] == "automatic"]
    if original:
        return original[0]["track_id"]
    manual = [t for t in tracks if t["source"] == "manual"]
    return manual[0]["track_id"] if len(manual) == 1 else ""
