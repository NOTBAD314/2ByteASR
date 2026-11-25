"""Discover browser profiles without reading site data until explicitly selected."""
from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from ..media.link_authorization import MAX_COOKIES, _authorize, _record, _site
from ..media.link_catalog import media_url
from .browser_helper_setup import detect

CHROMIUM_ROOTS = {
    "Chrome": "Google/Chrome/User Data",
    "Edge": "Microsoft/Edge/User Data",
    "Brave": "BraveSoftware/Brave-Browser/User Data",
}


def discover_profiles():
    profiles = []
    local = os.environ.get("LOCALAPPDATA")
    binaries = detect()
    for browser, relative in CHROMIUM_ROOTS.items():
        if browser not in binaries or not local:
            continue
        state = Path(local) / relative / "Local State"
        try:
            if state.stat().st_size > 4 * 1024 * 1024:
                continue
            entries = json.loads(state.read_bytes()).get("profile", {}).get("info_cache", {})
            for directory, row in entries.items():
                if re.fullmatch(r"Default|Profile \d{1,4}", directory):
                    profiles.append((browser, str(row.get("name") or directory), directory, binaries[browser]))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    roaming = os.environ.get("APPDATA")
    if roaming:
        root = Path(roaming) / "Mozilla/Firefox"
        ini = configparser.ConfigParser(interpolation=None)
        try:
            ini.read(root / "profiles.ini", encoding="utf-8")
            for section in ini.sections():
                if not section.startswith("Profile") or not ini[section].get("Path"):
                    continue
                row = ini[section]
                path = root / row["Path"] if row.get("IsRelative") == "1" else Path(row["Path"])
                database = path / "cookies.sqlite"
                if database.is_file():
                    profiles.append(("Firefox", row.get("Name") or "Default", database, None))
        except (OSError, UnicodeError, configparser.Error):
            pass
    return profiles


def load_firefox_site(url, database):
    """Use only the ordinary container and the selected HTTPS site's hosts."""
    target = urlsplit(media_url(url))
    if target.scheme != "https":
        raise ValueError("浏览器授权只支持 HTTPS 视频。")
    host = target.hostname
    site = _site(host)
    hosts = tuple(sorted({site, "." + site, host, "." + host}))
    fields = ",".join("?" for _ in hosts)
    db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=.4)
    try:
        records = []
        query = (
            "SELECT host, path, isSecure, expiry, name, value, isHttpOnly "
            f"FROM moz_cookies WHERE host IN ({fields}) AND originAttributes = '' LIMIT ?"
        )
        for domain, path, secure, expires, name, value, http_only in db.execute(query, (*hosts, MAX_COOKIES + 1)):
            record = _record(site, domain, path, bool(secure), int(expires), name, value, bool(http_only))
            if record:
                records.append(record)
        return _authorize(url, records, "firefox")
    finally:
        db.close()
