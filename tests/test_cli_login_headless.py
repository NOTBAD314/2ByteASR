"""Headless OAuth login for subscription CLI providers (agy / grok).

The login flow must never require a console window the user has to keep
open: the hidden login stream surfaces the OAuth URL in-app, a readiness
poll finishes the flow, and every login process is terminated on success.
"""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from twobyteasr.providers import ai_providers
from twobyteasr.providers.ai_providers import (
    AntigravityCLIProvider,
    GrokCLIProvider,
    ProviderStatus,
    extract_login_url,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeLoginProcess:
    """Process stub: stays alive until stopped or its lifetime expires."""

    def __init__(self, *, lifetime: float = 600.0, pid: int = 424242) -> None:
        self._deadline = time.monotonic() + lifetime
        self.stopped = False
        self.pid = pid
        self.stdout = self.stderr = None

    def poll(self):
        if self.stopped or time.monotonic() > self._deadline:
            return 0
        return None


@pytest.fixture()
def stop_tracker(monkeypatch):
    stopped: list[object] = []
    monkeypatch.setattr(
        ai_providers, "stop_process_tree", lambda process: stopped.append(process)
    )
    return stopped


def _install_fake_stream(monkeypatch, provider, *, url: str, process: FakeLoginProcess):
    state = {"url": url, "output": [f"visit {url}\n" if url else "waiting\n"], "lock": threading.Lock()}

    def fake_start(command):
        return process, state

    monkeypatch.setattr(provider, "_start_hidden_login_stream", fake_start)
    return state


def test_extract_login_url_strips_ansi_and_finds_first_url():
    assert extract_login_url("请访问 https://accounts.google.com/o/oauth2/auth?x=1 完成") == (
        "https://accounts.google.com/o/oauth2/auth?x=1"
    )
    assert extract_login_url("\x1b[1mhttps://example.com/login\x1b[0m next") == (
        "https://example.com/login"
    )
    assert extract_login_url("no url here") == ""


def test_login_short_circuits_when_already_authenticated(monkeypatch, stop_tracker):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    monkeypatch.setattr(
        provider, "detect_installation",
        lambda **_k: ProviderStatus(True, False, "installed"),
    )
    monkeypatch.setattr(
        provider, "validate",
        lambda **_k: ProviderStatus(True, True, "ready", ("gemini-3.7-flash-high",)),
    )
    launched: list[object] = []
    monkeypatch.setattr(
        provider, "_start_hidden_login_stream",
        lambda command: launched.append(command) or (_ for _ in ()).throw(AssertionError()),
    )
    progress: list[str] = []
    status = provider.login(on_progress=progress.append)
    assert status.authenticated
    assert not launched
    assert not stop_tracker
    assert any("已处于登录状态" in item for item in progress)


def test_login_hidden_stream_surfaces_url_polls_and_closes(monkeypatch, stop_tracker):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    hidden = FakeLoginProcess()
    _install_fake_stream(
        monkeypatch, provider,
        url="https://accounts.google.com/o/oauth2/auth?code=abc", process=hidden,
    )
    monkeypatch.setattr(
        provider, "detect_installation",
        lambda **_k: ProviderStatus(True, False, "installed"),
    )
    monkeypatch.setattr(provider, "validate", lambda **_k: ProviderStatus(True, False, "not logged in"))
    probes: list[int] = []

    def fake_probe(**_k):
        probes.append(1)
        if len(probes) >= 2:
            return ProviderStatus(True, True, "ok", ("gemini-3.7-flash-high",))
        return ProviderStatus(True, False, "尚未登录")

    monkeypatch.setattr(provider, "_login_probe", fake_probe)
    visible: list[object] = []
    monkeypatch.setattr(provider, "_launch_visible_login", lambda: visible.append(1))
    progress: list[str] = []
    status = provider.login(on_progress=progress.append)
    assert status.authenticated
    assert "无需保持任何外部窗口" in status.message
    assert any(item.startswith("https://accounts.google.com") for item in progress)
    assert hidden in stop_tracker
    assert not visible


def test_login_escalates_to_visible_console_without_url(monkeypatch, stop_tracker):
    provider = GrokCLIProvider(executable=r"C:\tools\grok.exe")
    hidden = FakeLoginProcess()
    _install_fake_stream(monkeypatch, provider, url="", process=hidden)
    monkeypatch.setattr(
        provider, "detect_installation",
        lambda **_k: ProviderStatus(True, False, "installed"),
    )
    monkeypatch.setattr(provider, "validate", lambda **_k: ProviderStatus(True, False, "not logged in"))
    probes: list[int] = []

    def fake_probe(**_k):
        probes.append(1)
        if len(probes) >= 3:
            return ProviderStatus(True, True, "ok", ("grok-4.6",))
        return ProviderStatus(True, False, "尚未登录")

    monkeypatch.setattr(provider, "_login_probe", fake_probe)
    visible_process = FakeLoginProcess()
    monkeypatch.setattr(provider, "_launch_visible_login", lambda: visible_process)
    clock = FakeClock()
    monkeypatch.setattr(ai_providers.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ai_providers.time, "sleep", lambda seconds: clock.advance(seconds))
    status = provider.login(url_wait_seconds=5.0)
    assert status.authenticated
    assert hidden in stop_tracker and visible_process in stop_tracker


def test_login_reports_captured_url_when_flow_times_out(monkeypatch, stop_tracker):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    hidden = FakeLoginProcess()
    _install_fake_stream(
        monkeypatch, provider, url="https://accounts.google.com/device", process=hidden,
    )
    monkeypatch.setattr(
        provider, "detect_installation",
        lambda **_k: ProviderStatus(True, False, "installed"),
    )
    monkeypatch.setattr(provider, "validate", lambda **_k: ProviderStatus(True, False, "not logged in"))
    monkeypatch.setattr(
        provider, "_login_probe",
        lambda **_k: ProviderStatus(True, False, "尚未登录"),
    )
    monkeypatch.setattr(provider, "_launch_visible_login", lambda: FakeLoginProcess())
    clock = FakeClock()
    monkeypatch.setattr(ai_providers.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ai_providers.time, "sleep", lambda seconds: clock.advance(seconds))
    status = provider.login(timeout=90.0, url_wait_seconds=10.0)
    assert not status.authenticated
    assert "https://accounts.google.com/device" in status.message


def test_grok_visible_login_uses_console_wrapper(monkeypatch):
    provider = GrokCLIProvider(executable=r"C:\tools\grok.exe")
    captured: dict[str, object] = {}

    def fake_popen(command, *, purpose, **kwargs):
        captured["command"] = list(command)
        captured["visible_console"] = kwargs.get("visible_console")
        return FakeLoginProcess()

    monkeypatch.setattr(ai_providers, "popen_hidden_subprocess", fake_popen)
    assert provider._login_command() == [r"C:\tools\grok.exe", "login", "--oauth"]
    provider._launch_visible_login()
    assert captured["command"] == [r"C:\tools\grok.exe", "login", "--oauth"]
    assert captured["visible_console"] is True


def test_antigravity_login_command_is_bare_repl(monkeypatch):
    provider = AntigravityCLIProvider(executable=r"C:\tools\agy.exe")
    captured: dict[str, object] = {}

    def fake_popen(command, *, purpose, **kwargs):
        captured["command"] = list(command)
        captured["visible"] = kwargs.get("visible_console", False)
        captured["stderr"] = kwargs.get("stderr")
        return FakeLoginProcess()

    monkeypatch.setattr(ai_providers, "popen_hidden_subprocess", fake_popen)
    assert provider._login_command() == [r"C:\tools\agy.exe"]
    provider._launch_visible_login()
    assert captured["command"] == [r"C:\tools\agy.exe"]
    assert not captured["visible"]
    assert captured["stderr"] == subprocess.PIPE


def test_login_probe_requires_models_listing(monkeypatch):
    provider = GrokCLIProvider(executable=r"C:\tools\grok.exe")

    def fake_run(command, **_k):
        if "models" in command:
            return subprocess.CompletedProcess(command, 0, "grok-4.6\n", "")
        return subprocess.CompletedProcess(command, 1, "", "not authenticated")

    monkeypatch.setattr(provider, "_run_cli_command", fake_run)
    assert provider._login_probe().authenticated

    def fake_run_denied(command, **_k):
        return subprocess.CompletedProcess(command, 1, "", "please login")

    monkeypatch.setattr(provider, "_run_cli_command", fake_run_denied)
    assert not provider._login_probe().authenticated
