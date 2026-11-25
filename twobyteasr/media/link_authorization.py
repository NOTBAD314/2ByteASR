"""Ephemeral web authorizations scoped to one canonical download URL."""
from __future__ import annotations

import http.cookiejar
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from .link_catalog import media_url

MAX_COOKIE_BYTES = 48 * 1024
MAX_COOKIES = 128
COOKIE_NAME = re.compile(r"[!#$%&'*+.^_\x60|~0-9A-Za-z-]{1,256}")
SAFE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*")


def _site(host):
    for domain in ("youtube.com", "bilibili.com"):
        if host == domain or host.endswith("." + domain):
            return domain
    return host


class SiteAuthorization:
    def __init__(self, url, records, origin):
        self.url = media_url(url)
        self.origin = origin
        self.valid_until = time.monotonic() + 1800
        self._records = records

    def revoke(self):
        self._records = ()

    def valid_for(self, url):
        return bool(self._records and time.monotonic() < self.valid_until and self.url == media_url(url))

    def netscape(self, url):
        if not self.valid_for(url):
            return b""
        rows = []
        for domain, path, secure, expires, name, value, http_only in self._records:
            if expires and expires <= time.time():
                continue
            prefix = "#HttpOnly_" if http_only else ""
            fields = (prefix + domain, "TRUE" if domain.startswith(".") else "FALSE",
                      path, "TRUE" if secure else "FALSE", str(expires), name, value)
            rows.append("\t".join(fields))
        return ("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n").encode("ascii") if rows else b""

    def jar(self, url):
        if not self.valid_for(url):
            return None
        jar = http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(
            strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))
        for domain, path, secure, expires, name, value, http_only in self._records:
            if expires and expires <= time.time():
                continue
            jar.set_cookie(http.cookiejar.Cookie(0, name, value, None, False,
                domain, domain.startswith("."), domain.startswith("."), path, True,
                secure, expires or None, not expires, None, None, {"HttpOnly": None} if http_only else {}))
        return jar


def _record(site, domain, path, secure, expires, name, value, http_only):
    if not all(isinstance(v, str) for v in (domain, path, name, value)):
        raise ValueError("登录授权资料格式不正确。")
    domain = domain.lower()
    host = domain.removeprefix(".")
    if not re.fullmatch(r"[a-z\d.-]{1,253}", host) or not (host == site or host.endswith("." + site)):
        return None
    if (not isinstance(secure, bool) or not isinstance(http_only, bool) or not isinstance(expires, int)
            or not 0 <= expires <= 253402300799 or not path.startswith("/") or len(path) > 1024
            or any(not 33 <= ord(c) < 127 for c in path)
            or not COOKIE_NAME.fullmatch(name) or len(value) > 4096 or not SAFE_VALUE.fullmatch(value)):
        raise ValueError("登录授权资料格式不正确。")
    return domain, path, secure, expires, name, value, http_only


def from_netscape(url, raw, origin="file"):
    if len(raw) > 512 * 1024:
        raise ValueError("Cookie 文件过大。")
    site = _site(urlsplit(media_url(url)).hostname)
    records = []
    for line in raw.decode("utf-8-sig").splitlines():
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line.removeprefix("#HttpOnly_")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            raise ValueError("请选择 Netscape 格式的 Cookie 文件。")
        domain, scope, path, secure, expires, name, value = parts
        if scope == "FALSE":
            domain = domain.removeprefix(".")
        if scope not in {"TRUE", "FALSE"} or secure not in {"TRUE", "FALSE"} or not expires.isascii():
            raise ValueError("登录授权资料格式不正确。")
        try:
            expiry = int(expires or 0)
        except ValueError:
            raise ValueError("登录授权资料格式不正确。") from None
        item = _record(site, domain, path, secure == "TRUE", expiry, name, value, http_only)
        if item is not None:
            records.append(item)
    return _authorize(url, records, origin)


def from_browser(url, cookies):
    if not isinstance(cookies, list) or not 1 <= len(cookies) <= MAX_COOKIES:
        raise ValueError("浏览器没有提供有效的本站授权。")
    site = _site(urlsplit(media_url(url)).hostname)
    records = []
    for row in cookies:
        if not isinstance(row, dict) or set(row) != {"domain", "path", "secure", "expires", "name", "value", "http_only"}:
            raise ValueError("浏览器授权格式不正确。")
        item = _record(site, **row)
        if item is None:
            raise ValueError("浏览器授权与网站不一致。")
        records.append(item)
    return _authorize(url, records, "browser")


def _authorize(url, records, origin):
    auth = SiteAuthorization(url, tuple(records), origin)
    payload = auth.netscape(url)
    if not payload:
        raise ValueError("没有这个网站可用的登录授权，可能需要重新登录。")
    if len(records) > MAX_COOKIES or len(payload) > MAX_COOKIE_BYTES:
        raise ValueError("该网站的授权资料超过大小限制。")
    return auth


def _private(path):
    if os.name != "nt":
        path.chmod(0o700)
        return
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    security = c.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.c_void_p]
    security.GetSecurityDescriptorDacl.argtypes = [c.c_void_p, c.POINTER(w.BOOL),
                                                  c.POINTER(c.c_void_p), c.POINTER(w.BOOL)]
    security.SetNamedSecurityInfoW.argtypes = [
        w.LPWSTR, w.DWORD, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
    security.SetNamedSecurityInfoW.restype = w.DWORD
    token = w.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)):
        raise c.WinError(c.get_last_error())
    sid_string, descriptor = w.LPWSTR(), c.c_void_p()
    try:
        size = w.DWORD()
        security.GetTokenInformation(token, 1, None, 0, c.byref(size))
        if not size.value:
            raise c.WinError(c.get_last_error())
        buffer = c.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size.value, c.byref(size)):
            raise c.WinError(c.get_last_error())
        sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid, c.byref(sid_string)):
            raise c.WinError(c.get_last_error())
        sddl = f"D:P(A;OICI;FA;;;{sid_string.value})"
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None):
            raise c.WinError(c.get_last_error())
        present, defaulted, acl = w.BOOL(), w.BOOL(), c.c_void_p()
        if not security.GetSecurityDescriptorDacl(descriptor, c.byref(present), c.byref(acl), c.byref(defaulted)):
            raise c.WinError(c.get_last_error())
        if not present.value or not acl:
            raise OSError("无法保护下载临时目录。")
        error = security.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, acl, None)
        if error:
            raise c.WinError(error)
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_string:
            kernel.LocalFree(c.cast(sid_string, c.c_void_p))
        kernel.CloseHandle(token)


def _request_root():
    return Path(tempfile.gettempdir()) / "2ByteASR-link-requests"


def _owner_exited(pid):
    if pid == os.getpid():
        return False
    if os.name == "nt":
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.WaitForSingleObject.restype = w.DWORD
        kernel.CloseHandle.argtypes = [w.HANDLE]
        process = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not process:
            return c.get_last_error() == 87
        try:
            return kernel.WaitForSingleObject(process, 0) == 0
        finally:
            kernel.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def clean_expired_requests():
    root = _request_root()
    if not root.is_dir() or root.is_symlink():
        return
    for path in root.glob("request-*"):
        try:
            if path.is_symlink() or not path.is_dir():
                continue
            owner = re.fullmatch(r"request-(\d{1,9})-[a-z0-9_]+", path.name)
            age = time.time() - path.stat().st_mtime
            if (owner and age > 1 and _owner_exited(int(owner[1]))) or (not owner and age > 7200):
                shutil.rmtree(path)
        except OSError:
            continue


@contextmanager
def private_request_directory():
    root = _request_root()
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink():
        raise OSError("下载临时目录无效。")
    clean_expired_requests()
    with tempfile.TemporaryDirectory(prefix=f"request-{os.getpid()}-", dir=root) as directory:
        path = Path(directory)
        _private(path)
        yield path
