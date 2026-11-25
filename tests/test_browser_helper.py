import io
import json
from pathlib import Path
import struct

import pytest

from twobyteasr.app.browser_link_protocol import NATIVE_LIMIT, public_protocol, serve, validate
from twobyteasr.media.link_authorization import from_browser, from_netscape, private_request_directory


URL = "https://www.youtube.com/watch?v=zC88fer6JCA"
COOKIE = dict(domain=".youtube.com", path="/", secure=True, expires=0, name="YSC",
              value="fictional_test_value", http_only=True)
ROOT = Path(__file__).resolve().parents[1]


def frame(payload):
    data = json.dumps(payload).encode()
    return io.BytesIO(struct.pack("<I", len(data)) + data)


def test_manifest_pins_the_packaged_extension_public_key():
    import base64
    import hashlib
    extension = json.loads((ROOT / "assets/browser-helper/manifest.json").read_bytes())
    host = json.loads((ROOT / "assets/browser-helper-host.json").read_bytes())
    letter_id = "".join(chr(97 + int(n, 16)) for n in hashlib.sha256(base64.b64decode(extension["key"])).hexdigest()[:32])
    assert host["allowed_origins"] == [f"chrome-extension://{letter_id}/"]
    assert host["path"] == "../2ByteASR.exe"
    assert set(extension["optional_host_permissions"]) == {
        "https://www.youtube.com/*", "https://www.bilibili.com/*"}
    assert "cookies" not in extension["permissions"]


def test_bilibili_parts_and_generic_public_links_use_the_existing_wire_format():
    message = dict(version=1, action="download", mode="both")
    source = "https://m.bilibili.com/video/BV1az421X7jh?p=3&from=share"
    assert validate(dict(message, url=source))["url"] == "https://www.bilibili.com/video/BV1az421X7jh?p=3"
    generic = "https://example.org/media/demo.mp4"
    assert validate(dict(message, url=generic))["url"] == generic
    with pytest.raises(ValueError):
        validate(dict(message, url=generic, cookies=[dict(COOKIE, domain=".example.org")]))
    cookies = [dict(COOKIE, domain=".bilibili.com")]
    assert validate(dict(message, url=source, cookies=cookies))["cookies"] == cookies


def test_firefox_native_registration_is_bound_to_the_installed_manifest():
    from twobyteasr.app.browser_native_host import allowed_launch

    chromium = json.loads((ROOT / "assets/browser-helper-host.json").read_bytes())
    gecko = json.loads((ROOT / "assets/browser-helper/manifest.json").read_bytes())["browser_specific_settings"]["gecko"]
    assert gecko["data_collection_permissions"] == {
        "required": ["browsingActivity"],
        "optional": ["authenticationInfo", "websiteContent"],
    }
    manifest = ROOT / "assets/browser-helper-host-firefox.json"
    assert allowed_launch(ROOT, [str(manifest), gecko["id"]]) == "firefox"
    assert not allowed_launch(ROOT, [str(manifest), "other@example.org"])
    assert not allowed_launch(ROOT, [str(manifest.with_name("fake.json")), gecko["id"]])
    assert allowed_launch(ROOT, [chromium["allowed_origins"][0], "--parent-window=0"]) == "chromium"


def test_chrome_and_brave_use_the_shared_windows_registration(tmp_path, monkeypatch):
    from contextlib import nullcontext
    import sys
    from types import SimpleNamespace
    from twobyteasr.app import browser_helper_setup as setup

    manifest = tmp_path / "assets" / "browser-helper-host.json"
    manifest.parent.mkdir()
    manifest.touch()
    (tmp_path / "2ByteASR.exe").touch()
    paths = {
        name: rf"Software\{setup.BROWSERS[name][0]}\NativeMessagingHosts\{setup.HOST_NAME}"
        for name in ("Chrome", "Brave")
    }
    values = {paths["Brave"]: str(manifest)}

    def open_key(_hive, path):
        if path not in values:
            raise FileNotFoundError(path)
        return nullcontext(path)

    registry = SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        REG_SZ=1,
        OpenKey=open_key,
        QueryValueEx=lambda path, _name: (values[path], 1),
        CreateKey=lambda _hive, path: nullcontext(path),
        SetValueEx=lambda path, _name, _reserved, _type, value: values.update({path: value}),
        DeleteKey=lambda _hive, path: values.pop(path),
    )
    monkeypatch.setattr(setup, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert not setup.registration(tmp_path, "Brave")
    assert setup.registration(tmp_path, "Brave", change="install")
    assert values == dict.fromkeys(paths.values(), str(manifest))
    assert setup.registration(tmp_path, "Chrome")
    assert setup.registration(tmp_path, "Brave")
    values[paths["Brave"]] = str(tmp_path / "another-installation.json")
    assert not setup.registration(tmp_path, "Chrome", change="remove")
    assert values == {paths["Brave"]: str(tmp_path / "another-installation.json")}


def test_rejects_other_sites_credentials_unknown_fields_and_oversized_input():
    message = dict(version=1, action="download", url=URL, mode="both")
    for changes in [dict(url="file:///C:/private"), dict(url="https://www.youtube.com@other.test/watch?v=zC88fer6JCA"),
                    dict(url=URL.replace("www.youtube.com", "youtube.com.attacker.test")),
                    dict(path="C:/private"), dict(cookies=[dict(COOKIE, domain=".other.test")])]:
        with pytest.raises(ValueError):
            validate(dict(message, **changes))
    sink = io.BytesIO()
    serve(io.BytesIO(struct.pack("<I", NATIVE_LIMIT + 1)), sink, lambda value: pytest.fail("invalid request delivered"))
    assert json.loads(sink.getvalue()[4:])["code"] == "invalid_message"
    assert public_protocol("2byteasr://video/zC88fer6JCA?mode=subtitles")["url"] == URL
    with pytest.raises(ValueError):
        public_protocol("2byteasr://video/zC88fer6JCA?cookie=x")


def test_native_reply_omits_payload_and_window_scope_can_be_revoked():
    message = dict(version=1, action="download", url=URL, mode="both", cookies=[COOKIE])
    sink = io.BytesIO()
    observed = []
    serve(frame(message), sink, lambda value: (observed.append(value), {"ok": True})[1])
    wire_response = sink.getvalue()
    assert struct.unpack("<I", wire_response[:4])[0] == len(wire_response[4:])
    assert b"fictional_test_value" not in wire_response
    auth = from_browser(URL, observed[0]["cookies"])
    assert auth.netscape(URL)
    assert not auth.netscape(URL.replace("zC88fer6JCA", "BaW_jenozKc"))
    auth.revoke()
    assert not auth.netscape(URL)


def test_netscape_discards_unrelated_domains_and_private_temp_cleans_up():
    raw = (b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tYSC\tordinary_test\n"
           b".other.test\tTRUE\t/\tTRUE\t0\tsecret\tunrelated_test\n")
    auth = from_netscape(URL, raw)
    material = auth.netscape(URL)
    assert b"ordinary_test" in material and b"unrelated_test" not in material
    with private_request_directory() as directory:
        path = directory / "cookies.txt"
        path.write_bytes(material)
    assert not directory.exists()


def test_firefox_profile_read_only_selects_one_site_and_default_container(tmp_path):
    import sqlite3
    from twobyteasr.app.browser_profiles import load_firefox_site
    path = tmp_path / "cookies.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE moz_cookies (host, path, isSecure, expiry, name, value, isHttpOnly, originAttributes)")
        db.executemany("INSERT INTO moz_cookies VALUES (?, '/', 1, 0, ?, ?, 1, ?)", [
            (".youtube.com", "YSC", "chosen_test_site", ""),
            (".youtube.com", "YSC", "other_container", "^userContextId=2"),
            (".example.net", "test", "other_site", ""),
        ])
    before = path.read_bytes()
    result = load_firefox_site(URL, path)
    assert b"chosen_test_site" in result.netscape(URL)
    assert b"other_container" not in result.netscape(URL)
    assert b"other_site" not in result.netscape(URL)
    assert path.read_bytes() == before


def test_browser_download_asks_before_guessing_between_author_tracks(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app.browser_link_intake import enqueue
    from twobyteasr.media.link_catalog import video_catalog

    tracks = {"en": [dict(ext="json3", url="https://www.youtube.com/api/timedtext?lang=en")],
              "de": [dict(ext="json3", url="https://www.youtube.com/api/timedtext?lang=de")]}
    catalog = video_catalog(dict(id="zC88fer6JCA", subtitles=tracks, automatic_captions={}))
    choices = []
    controller = SimpleNamespace(dialog=SimpleNamespace(preferences={}),
                                 offer_browser_choices=lambda *parts: choices.append(parts))
    assert enqueue(controller, (catalog, "both", None, {})) is None
    assert choices == [(catalog, "both", None)]
