"""Connecting AI clients to the local MCP server: config merge, backups, status (2026-10-13).

Every test points APPDATA / LOCALAPPDATA / HOME at tmp_path, so the real
Claude Desktop config of the person running the tests is never read or written.
"""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

from twobyteasr import mcp_clients
from twobyteasr import mcp_common as common

EXE = r"C:\Program Files\兔白 字幕\2ByteASR.exe"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.delenv("2BYTEASR_USER_DATA_ROOT", raising=False)
    return tmp_path


def claude_folder(home):
    folder = home / "Roaming" / "Claude"
    folder.mkdir(parents=True)
    return folder


def test_merge_keeps_other_servers_and_backs_up_first(home):
    folder = claude_folder(home)
    original = {"mcpServers": {"files": {"command": "npx", "args": ["fs"], "env": {"TOKEN": "keep"}}},
                "preferences": {"theme": "dark"}, "unknownFutureKey": [1, 2]}
    config = folder / mcp_clients.CONFIG_NAME
    config.write_text(json.dumps(original), encoding="utf-8")
    before = config.read_bytes()
    place = mcp_clients.claude_desktop_location("win32")
    assert place.path == config and place.installed and not place.store_app
    assert mcp_clients.entry_state(place, EXE, ["--mcp-stdio"]) == "not_written"
    backup = mcp_clients.write_entry(place, EXE, ["--mcp-stdio"])
    assert backup.read_bytes() == before
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["mcpServers"]["files"] == original["mcpServers"]["files"]
    assert written["preferences"] == original["preferences"] and written["unknownFutureKey"] == [1, 2]
    assert written["mcpServers"]["2byteasr"] == {"command": EXE, "args": ["--mcp-stdio"]}  # spaces + Chinese intact
    assert mcp_clients.entry_state(place, EXE, ["--mcp-stdio"]) == "written"
    assert mcp_clients.entry_state(place, r"D:\moved\2ByteASR.exe", ["--mcp-stdio"]) == "outdated"
    mcp_clients.remove_entry(place)
    after = json.loads(config.read_text(encoding="utf-8"))
    assert "2byteasr" not in after["mcpServers"] and after["mcpServers"]["files"] == original["mcpServers"]["files"]


def test_unreadable_config_is_never_rewritten(home):
    folder = claude_folder(home)
    config = folder / mcp_clients.CONFIG_NAME
    for broken in ('{"mcpServers": {', '[1, 2]', '{"mcpServers": []}'):
        config.write_text(broken, encoding="utf-8")
        place = mcp_clients.claude_desktop_location("win32")
        assert mcp_clients.entry_state(place, EXE, []) == "invalid"
        with pytest.raises(mcp_clients.ConfigError):
            mcp_clients.write_entry(place, EXE, [])
        assert config.read_text(encoding="utf-8") == broken
    assert not list(folder.glob("*" + mcp_clients.BACKUP_MARK + "*"))


def test_store_build_reads_its_package_copy(home):
    roaming = claude_folder(home) / mcp_clients.CONFIG_NAME
    roaming.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    package = home / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc"
    package.mkdir(parents=True)
    place = mcp_clients.claude_desktop_location("win32")
    assert place.store_app and place.source == roaming
    assert place.path == package / "LocalCache" / "Roaming" / "Claude" / mcp_clients.CONFIG_NAME
    assert mcp_clients.write_entry(place, EXE, ["--mcp-stdio"]) is None  # nothing to back up there yet
    packaged = json.loads(place.path.read_text(encoding="utf-8"))
    assert set(packaged["mcpServers"]) == {"other", "2byteasr"}          # merged from what the app read
    assert json.loads(roaming.read_text(encoding="utf-8")) == {"mcpServers": {"other": {"command": "x"}}}
    again = mcp_clients.claude_desktop_location("win32")
    assert again.source == again.path and mcp_clients.entry_state(again, EXE, ["--mcp-stdio"]) == "written"


def test_missing_client_platforms_and_backup_pruning(home, monkeypatch):
    assert mcp_clients.claude_desktop_location("linux") is None
    assert mcp_clients.entry_state(None, EXE, []) == "missing_client"
    place = mcp_clients.claude_desktop_location("win32")
    assert not place.installed and mcp_clients.entry_state(place, EXE, []) == "missing_client"
    mac = mcp_clients.claude_desktop_location("darwin")
    assert mac.path == home / "home" / "Library" / "Application Support" / "Claude" / mcp_clients.CONFIG_NAME
    folder = claude_folder(home)
    place = mcp_clients.claude_desktop_location("win32")
    times = iter(range(100))
    monkeypatch.setattr(mcp_clients.time, "strftime", lambda _fmt: f"2026-{next(times):04d}")
    for _ in range(8):
        mcp_clients.write_entry(place, EXE, [])
    assert len(list(folder.glob("*" + mcp_clients.BACKUP_MARK + "*"))) == mcp_clients.KEEP_BACKUPS


def test_data_folder_is_passed_on_and_claude_code_command_is_quoted(home, monkeypatch):
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", r"D:\兔白 数据")
    entry = common.server_entry(EXE, ["--mcp-stdio"])
    assert entry["env"] == {"2BYTEASR_USER_DATA_ROOT": r"D:\兔白 数据"}
    command = mcp_clients.claude_code_command(EXE, ["--mcp-stdio"])
    assert command == (r'claude mcp add --scope user -e 2BYTEASR_USER_DATA_ROOT="D:\兔白 数据" 2byteasr -- '
                       r'"C:\Program Files\兔白 字幕\2ByteASR.exe" --mcp-stdio')
    config = json.loads(common.client_config(EXE, ["--mcp-stdio"]))
    assert config["mcpServers"]["2byteasr"]["command"] == EXE


def test_status_tells_written_apart_from_connected():
    off = mcp_clients.connection_lines({}, False, "written", now=100)
    assert "已写入" in off[0] and "拒绝" in off[1]
    waiting = mcp_clients.connection_lines({}, True, "written", now=100)
    assert "正在等待客户端" in waiting[1] and "实际已连线" not in "".join(waiting)
    started = mcp_clients.connection_lines({"client_started_at": 90}, True, "written", now=100)
    assert "还没有调用工具" in started[1]
    connected = mcp_clients.connection_lines({"client_started_at": 90, "last_tool_at": 95, "client": "Claude",
                                              "last_method": "get_cues"}, True, "not_written", now=100)
    assert "实际已连线" in connected[1] and "Claude" in connected[1] and "get_cues" in connected[1]


def test_settings_page_asks_before_enabling_and_writes_only_after_confirming(home, monkeypatch):
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog
    app = QApplication.instance() or QApplication([])
    folder = claude_folder(home)
    answers = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: answers.pop(0) if answers else QMessageBox.StandardButton.No)
    dialog = ApplicationSettingsDialog(None, {}, home / "Projects", browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    notice = dialog.findChild(QLabel, "mcpDataNotice")
    assert notice is not None and "AI 服务" in notice.text()
    assert not dialog.mcp_enabled.isChecked()
    dialog.mcp_enabled.setChecked(True)                    # declined → stays off
    assert not dialog.mcp_enabled.isChecked() and dialog.mcp_values()["acknowledged"] is False
    answers.append(QMessageBox.StandardButton.Yes)
    dialog.mcp_enabled.setChecked(True)
    assert dialog.mcp_enabled.isChecked() and dialog.mcp_values()["acknowledged"] is True
    config = folder / mcp_clients.CONFIG_NAME
    dialog.mcp_write.click()                              # confirmation declined → nothing written
    assert not config.exists()
    answers.append(QMessageBox.StandardButton.Yes)
    dialog.mcp_write.click()
    assert "2byteasr" in json.loads(config.read_text(encoding="utf-8"))["mcpServers"]
    assert "已写入" in dialog.mcp_status.text() and "实际已连线" not in dialog.mcp_status.text()
    dialog.mcp_export_dir.setText(str(home / "exports"))
    assert dialog.mcp_values()["export_dir"] == str(home / "exports")
    dialog.mcp_client.setCurrentIndex(dialog.mcp_client.findData("claude_code"))
    assert dialog.mcp_write.isHidden() and dialog.mcp_copy.text() == "复制命令"
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
