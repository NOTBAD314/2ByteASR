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
