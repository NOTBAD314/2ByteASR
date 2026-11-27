"""Windows registration for the packaged 2ByteASR browser helper."""
from __future__ import annotations

import os
from pathlib import Path

from .browser_link_protocol import HOST_NAME

BROWSERS = {
    "Chrome": ("Google\\Chrome", "chrome.exe", "Google/Chrome/Application"),
    "Edge": ("Microsoft\\Edge", "msedge.exe", "Microsoft/Edge/Application"),
    "Brave": ("BraveSoftware\\Brave-Browser", "brave.exe", "BraveSoftware/Brave-Browser/Application"),
    "Firefox": ("Mozilla", "firefox.exe", "Mozilla Firefox"),
}
SHARED_CHROMIUM_HOST = ("Chrome", "Brave")
# Store listings of the helper, by browser. Empty until it is published; the
# install window then offers a store button instead of the manual load.
STORE_PAGES: dict[str, str] = {}
# Where each Chromium browser keeps its profiles (under %LOCALAPPDATA%).
PROFILE_ROOTS = {"Chrome": "Google/Chrome/User Data", "Edge": "Microsoft/Edge/User Data",
                 "Brave": "BraveSoftware/Brave-Browser/User Data"}
CONTACT_FILE = "browser-helper-contact.json"
CONTACT_NAMES = ("Chrome", "Edge", "Brave", "Firefox", "Chromium")


def extension_id(root) -> str:
    """The helper's fixed Chromium ID, derived from the manifest's public key."""
    import base64
    import hashlib
    import json
    key = json.loads((Path(root) / "assets/browser-helper/manifest.json").read_bytes())["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(97 + int(n, 16)) for n in digest)


def helper_version(root) -> str:
    import json
    try:
        return str(json.loads((Path(root) / "assets/browser-helper/manifest.json").read_bytes()).get("version", ""))
    except (OSError, ValueError):
        return ""


def helper_in_browser(root, name, *, local_app_data=None):
    """What a Chromium browser's own settings say about the helper (read only).

    ``None`` when it cannot be known (Firefox keeps loaded helpers only for the
    session, or the browser has no profile folder); otherwise a dict with
    ``loaded`` and, when loaded, ``path``, ``version``, ``enabled``."""
    import json
    if name not in PROFILE_ROOTS:
        return None
    base = Path(local_app_data or os.environ.get("LOCALAPPDATA", "")) / PROFILE_ROOTS[name]
    if not base.is_dir():
        return None
    try:
        ident = extension_id(root)
    except (OSError, ValueError, KeyError):
        return None
    for profile in [base / "Default", *sorted(base.glob("Profile *"))]:
        for filename in ("Secure Preferences", "Preferences"):
            try:
                data = json.loads((profile / filename).read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                continue
            extensions = data.get("extensions") if isinstance(data, dict) else None
            settings = extensions.get("settings") if isinstance(extensions, dict) else None
            entry = settings.get(ident) if isinstance(settings, dict) else None
            if isinstance(entry, dict):
                manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
                return dict(loaded=True, path=str(entry.get("path") or ""), version=str(manifest.get("version") or ""),
                            enabled=not entry.get("disable_reasons") and entry.get("state", 1) != 0,
                            profile=profile.name)
    return dict(loaded=False)


def same_folder(root, path) -> bool:
    try:
        return Path(path).resolve() == (Path(root) / "assets/browser-helper").resolve()
    except (OSError, ValueError):
        return False


def _contact_path():
    from ..runtime_paths import user_data_root
    return user_data_root() / CONTACT_FILE


def record_contact(browser: str) -> None:
    """The helper reached the desktop from this browser (written by the native host)."""
    import json
    import time
    if browser not in CONTACT_NAMES:
        return
    path = _contact_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data = data if isinstance(data, dict) else {}
        data[browser] = time.time()
        from ..media.link_manifest import atomic_json
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, data)
    except (OSError, ValueError):
        pass


def last_contact() -> dict[str, float]:
    import json
    try:
        data = json.loads(_contact_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: float(value) for key, value in data.items()
            if key in CONTACT_NAMES and isinstance(value, (int, float))} if isinstance(data, dict) else {}


def detect():
    if os.name != "nt":
        return {}
    import winreg
    found = {}
    for name, (_, executable, relative) in BROWSERS.items():
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            with_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + executable
            try:
                with winreg.OpenKey(hive, with_path) as key:
                    candidate = Path(winreg.QueryValueEx(key, "")[0].strip('"'))
                if candidate.is_file():
                    found[name] = candidate
                    break
            except OSError:
                continue
        if name not in found:
            for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                if os.environ.get(variable):
                    candidate = Path(os.environ[variable]) / relative / executable
                    if candidate.is_file():
                        found[name] = candidate
                        break
    return found


def registration(root, name, *, change=None):
    if os.name != "nt" or name not in BROWSERS:
        return False
    import winreg
    manifest_name = "browser-helper-host-firefox.json" if name == "Firefox" else "browser-helper-host.json"
    manifest = Path(root).resolve() / "assets" / manifest_name
    # Current Windows Brave looks up this host under Chrome. Write the same
    # two entries as Setup, and expose their shared lifetime in the wizard.
    browsers = SHARED_CHROMIUM_HOST if name in SHARED_CHROMIUM_HOST else (name,)
    paths = [rf"Software\{BROWSERS[browser][0]}\NativeMessagingHosts\{HOST_NAME}" for browser in browsers]
    hive = winreg.HKEY_CURRENT_USER

    def owns(path):
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except FileNotFoundError:
            return False
        return isinstance(value, str) and value.casefold() == str(manifest).casefold()

    if change == "install":
        import sys
        if not getattr(sys, "frozen", False) or not manifest.is_file() or not (manifest.parent.parent / "2ByteASR.exe").is_file():
            raise ValueError("此操作需要包含兔白助手的 Windows 安装版。")
        for path in paths:
            with winreg.CreateKey(hive, path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
        return True
    if change == "remove":
        for path in paths:
            if owns(path):
                winreg.DeleteKey(hive, path)
        return False
    return owns(paths[0]) and manifest.is_file()
