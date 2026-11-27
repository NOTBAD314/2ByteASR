"""Wire format for the browser helper. Secrets never enter launch arguments."""
from __future__ import annotations

import json
import re
import struct
from urllib.parse import parse_qs, urlsplit

from ..media.link_authorization import from_browser
from ..media.link_catalog import BILIBILI_HOSTS, YOUTUBE_HOSTS, media_url

HOST_NAME = "org.twobyteasr.helper"
NATIVE_LIMIT = 64 * 1024
MODES = {"both", "subtitles", "recognize"}
PING_BROWSERS = {"Chrome", "Edge", "Brave", "Firefox"}


def browser_video_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise ValueError("视频链接无效。")
    parsed = urlsplit(value)
    if any(key.casefold() in {"cookie", "cookies", "set-cookie"} for key in parse_qs(parsed.query, keep_blank_values=True)):
        raise ValueError("请通过助手授权传递 Cookie。")
    host = parsed.hostname or ""
    permitted_aliases = YOUTUBE_HOSTS | BILIBILI_HOSTS | {"b23.tv"}
    if host not in permitted_aliases and any(
            marker in host for marker in ("youtube.com.", "youtu.be.", "bilibili.com.", "b23.tv.")):
        raise ValueError("视频域名无效。")
    return media_url(value)


def validate(data, *, allow_ping=False):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("助手协议版本不相容。")
    if allow_ping and data.get("action") == "ping" and set(data) <= {"version", "action", "browser"}:
        # 2026-11-26: the helper names its browser so the install window can
        # tick "tried it" and show the last contact per browser.
        browser = data.get("browser")
        if browser is None:
            return {"version": 1, "action": "ping"}
        if isinstance(browser, str) and browser in PING_BROWSERS:
            return {"version": 1, "action": "ping", "browser": browser}
        raise ValueError("助手操作无效。")
    if (data.get("action") != "download" or set(data) - {"version", "action", "url", "mode", "cookies"}
            or not isinstance(data.get("mode"), str) or data["mode"] not in MODES):
        raise ValueError("助手操作无效。")
    url = browser_video_url(data.get("url"))
    clean = dict(version=1, action="download", url=url, mode=data["mode"])
    if "cookies" in data:
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc not in {"www.youtube.com", "www.bilibili.com"}:
            raise ValueError("此网站尚未接入助手授权。")
        from_browser(url, data["cookies"])
        clean["cookies"] = data["cookies"]
    return clean


def public_protocol(value):
    match = re.fullmatch(r"2byteasr://video/([A-Za-z0-9_-]{11})(?:\?mode=(both|subtitles|recognize))?", value)
    if not match:
        raise ValueError("助手链接无效。")
    return validate(dict(version=1, action="download", url="https://www.youtube.com/watch?v=" + match[1],
                         mode=match[2] or "both"))


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError()
        data.extend(chunk)
    return data


def serve(source, sink, deliver):
    """One bounded message per browser-launched process."""
    try:
        size = struct.unpack("<I", _read_exact(source, 4))[0]
        if not 1 <= size <= NATIVE_LIMIT:
            raise ValueError("助手消息超过大小限制。")
        message = validate(json.loads(_read_exact(source, size)), allow_ping=True)
        result = deliver(message)
    except (EOFError, TypeError, ValueError, RecursionError):
        result = {"ok": False, "code": "invalid_message"}
    except (OSError, RuntimeError):
        result = {"ok": False, "code": "desktop_unavailable"}
    reply = json.dumps(result, separators=(",", ":")).encode("ascii")
    sink.write(struct.pack("<I", len(reply)) + reply)
    sink.flush()
