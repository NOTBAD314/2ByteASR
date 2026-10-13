"""Exercise audit boundaries without an external connection or a GUI window."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
@pytest.mark.parametrize("address", [("203.0.113.8", 443), ("example.invalid", 443), ("2001:db8::8", 443)])
def test_pytest_blocks_external_socket_before_transport(method, address):
    # object() cannot reach the real socket descriptor, even if the guard is
    # absent. A missing guard therefore fails safely with TypeError.
    with pytest.raises(RuntimeError, match="Offline regression blocked external connection"):
        getattr(socket.socket, method)(object(), address)


def test_create_connection_blocks_before_dns(monkeypatch):
    def unexpected_lookup(*args, **kwargs):
        raise AssertionError("external hostname reached DNS resolution")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_lookup)
    with pytest.raises(RuntimeError, match="Offline regression blocked external connection"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.parametrize("method", ["connect", "connect_ex", "create_connection"])
def test_loopback_connections_remain_available(method):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)
        address = server.getsockname()
        if method == "create_connection":
            client = socket.create_connection(address, timeout=2)
        else:
            client = socket.socket()
            client.settimeout(2)
            result = getattr(client, method)(address)
            assert result in (None, 0)
        with client, server.accept()[0] as accepted:
            client.sendall(b"local fixture")
            assert accepted.recv(32) == b"local fixture"


@pytest.mark.skipif(os.name != "nt", reason="qtawesome Windows font-install policy")
def test_isolated_child_does_not_invoke_system_font_installer(tmp_path):
    # A fresh child has no pytest conftest patch. The fake install routine
    # represents the forbidden side effect without ever touching GDI/fonts.
    program = r'''
import os, runpy, sys, types
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
calls = []
class IconicFont:
    def _install_fonts(self, directory, system_wide=False):
        calls.append(directory)
        raise AssertionError("system font installer was reached")
module = types.ModuleType("qtawesome.iconic_font")
module.IconicFont = IconicFont
sys.modules[module.__name__] = module
boundary = runpy.run_path("twobyteasr/test_isolation.py")
boundary["install"]()
font = IconicFont()
assert font._install_fonts("bundled-fonts") == "bundled-fonts"
assert font._install_fonts("bundled-fonts", system_wide=True) == "bundled-fonts"
boundary["install"]()
assert not calls
print("private-fonts-pass")
'''
    env = os.environ.copy()
    env["TWOBYTEASR_TEST_ROOT"] = str(tmp_path / "child-profile")
    completed = subprocess.run([sys.executable, "-B", "-c", program], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "private-fonts-pass" in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="qtawesome Windows font-install policy")
def test_fresh_child_lazy_font_import_uses_bundle_without_copying(tmp_path):
    program = r'''
import os, runpy, sys
from pathlib import Path
boundary = runpy.run_path("twobyteasr/test_isolation.py")
boundary["install"]()
boundary["install"]()
assert "qtawesome.iconic_font" not in sys.modules
assert sum(bool(getattr(f, "_twobyte_private_icon_fonts", False)) for f in sys.meta_path) == 1
import qtawesome.iconic_font as iconic
directory = str(Path(iconic.__file__).parent / "fonts")
assert iconic.IconicFont._install_fonts(object(), directory) == directory
assert not (Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts").exists()
print("lazy-fonts-pass")
'''
    env = os.environ.copy()
    env["TWOBYTEASR_TEST_ROOT"] = str(tmp_path / "lazy-font-profile")
    completed = subprocess.run([sys.executable, "-B", "-c", program], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_normal_process_keeps_original_font_and_network_policy():
    program = r'''
import os, runpy, socket, sys
originals = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
os.environ.pop("TWOBYTEASR_TEST_ROOT", None)
boundary = runpy.run_path("twobyteasr/test_isolation.py")
boundary["install"]()
assert not any(getattr(f, "_twobyte_private_icon_fonts", False) for f in sys.meta_path)
assert originals == (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
print("normal-policy-pass")
'''
    completed = subprocess.run([sys.executable, "-B", "-c", program], cwd=ROOT,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_live_driver_collect_requires_opt_in_without_platform_mutation(monkeypatch):
    # Execute its pre-Qt prefix only: old code would remove offscreen, while
    # fixed code must skip before importing any UI modules.
    path = ROOT / "tests/test_p0_live_gui_driver.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prefix = []
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and (statement.module or "").startswith("PySide6"):
            break
        prefix.append(statement)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("TWOBYTEASR_LIVE_GUI_TESTS", raising=False)
    code = compile(ast.Module(body=prefix, type_ignores=[]), str(path), "exec")
    with pytest.raises(pytest.skip.Exception):
        exec(code, {"__file__": str(path), "__name__": "audit_collect_probe"})
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
