"""YouTube link and subtitle identities. Signed URLs are transient, never receipts.

Selection adapted from imsyy/yt-dlp-gui SubtitleCard.vue (MIT), revision
e3cd1df342c1dd0f543b309cf305210a588a461c; see licenses/yt-dlp-gui-MIT.txt.
Automatic translations and original ASR are separate sources here.
"""
from __future__ import annotations
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

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


def language_matches(left: str, right: str) -> bool:
    return bool(left and right and left.lower().split("-")[0] == right.lower().split("-")[0])


def subtitle_tracks(info: dict) -> list[dict]:
    """Group actual timedtext identities, not display-language keys.

    Translated manual tracks can occur in automatic_captions.
    tlang/kind/lang and stable IDs are evidence; '-orig' alone is not.
    """
    platform, video = str(info.get("extractor_key") or info.get("extractor") or "Youtube"), str(info["id"])
    groups = {}
    for container in ("subtitles", "automatic_captions"):
        for key, entries in (info.get(container) or {}).items():
            if key == "live_chat" or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("ext") not in FORMATS:
                    continue
                url = str(entry.get("url") or "")
                if urlsplit(url).scheme not in ("http", "https"):
                    continue
                q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items() if v}
                original = str(entry.get("languageCode") or q.get("lang") or "")
                target = str(q.get("tlang") or entry.get("translation_language") or "")
                kind = str(entry.get("kind") or q.get("kind") or "")
                source = ("translated" if target else "manual" if container == "subtitles"
                          else "automatic" if kind == "asr" else "unknown")
                language = target or original or key
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
                    track["representations"].append(dict(ext=entry["ext"], url=url, key=key,
                        container=container, http_headers=dict(entry.get("http_headers") or {})))
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


def video_catalog(info: dict, *, subtitle_warning: bool = False) -> dict:
    url, video = youtube_url(info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}")
    if info.get("_type") in ("playlist", "multi_video") or str(info.get("id")) != video:
        raise ValueError("解析结果不是所选单个视频。")
    if info.get("is_live"):
        raise ValueError("正在直播的视频暂不支持；请在直播结束后重试。")
    tracks = subtitle_tracks(info)
    formats = []
    for f in info.get("formats") or ():
        if f.get("has_drm") or f.get("vcodec") == "images" or not f.get("format_id"):
            continue
        if f.get("vcodec") in (None, "none") and f.get("acodec") in (None, "none"):
            continue
        formats.append({k: f.get(k) for k in ("format_id", "ext", "height", "width", "fps",
            "vcodec", "acodec", "filesize", "filesize_approx", "language", "format_note", "abr",
            "audio_channels", "language_preference")})
    return dict(url=url, video_id=video, platform=str(info.get("extractor_key") or "Youtube"),
                title=str(info.get("title") or video), duration=float(info.get("duration") or 0),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                upload_date=str(info.get("upload_date") or ""),
                language=str(info.get("language") or ""), thumbnail=str(info.get("thumbnail") or ""),
                formats=formats, tracks=tracks,
                subtitle_status="incomplete" if (subtitle_warning or not isinstance(info.get("subtitles"), dict)
                    or not isinstance(info.get("automatic_captions"), dict)) else "available" if tracks else "none")


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
