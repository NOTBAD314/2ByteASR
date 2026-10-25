"""Connecting AI clients to the local MCP server: config merge, backups, status (2026-10-13).

Every test points APPDATA / LOCALAPPDATA / HOME at tmp_path, so the real
Claude Desktop config of the person running the tests is never read or written.
"""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

from twobyteasr.local_mcp import mcp_clients
from twobyteasr.local_mcp import mcp_common as common

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


def test_claude_desktop_overwrite_is_reported_not_called_unwritten(home):
    """2026-10-16 23:21: written, then Claude rewrote its file from memory (no mcpServers)."""
    folder = claude_folder(home)
    config = folder / mcp_clients.CONFIG_NAME
    claude_own = {"preferences": {"sidebarMode": "code"}}
    config.write_text(json.dumps(claude_own), encoding="utf-8")
    place = mcp_clients.claude_desktop_location("win32")
    mcp_clients.write_entry(place, EXE, ["--mcp-stdio"])
    written = mcp_clients.written_at(mcp_clients.DESKTOP, place)
    assert written and mcp_clients.entry_state(place, EXE, ["--mcp-stdio"]) == "written"
    config.write_text(json.dumps(claude_own), encoding="utf-8")            # Claude writes its memory back
    assert mcp_clients.entry_state(place, EXE, ["--mcp-stdio"]) == "lost"
    lost = mcp_clients.connection_lines({}, True, "lost", written=written, started=0.0)
    assert "覆盖" in lost[0] and "正在运行" not in "".join(lost)
    running = mcp_clients.connection_lines({}, True, "lost", written=written, started=written + 60)
    assert "先完全退出" in running[1]
    # Written while an earlier-started Claude ran: it will overwrite the entry.
    config.write_text(json.dumps(dict(claude_own, mcpServers={"2byteasr": common.server_entry(EXE, [])})),
                      encoding="utf-8")
    early = mcp_clients.config_lines(mcp_clients.DESKTOP, "written", written, started=written - 60)
    assert "写入前就已打开" in early[0]
    assert "已读到" in mcp_clients.config_lines(mcp_clients.DESKTOP, "written", written, started=written + 60)[0]
    mcp_clients.remove_entry(place)                                       # removing forgets the record
    assert not mcp_clients.written_at(mcp_clients.DESKTOP, place)
    assert mcp_clients.entry_state(place, EXE, []) == "not_written"


def test_write_is_read_back(home, monkeypatch):
    folder = claude_folder(home)
    place = mcp_clients.claude_desktop_location("win32")
    real_write = mcp_clients._write
    monkeypatch.setattr(mcp_clients, "_write", lambda path, payload: real_write(path, {"preferences": {}}))
    with pytest.raises(mcp_clients.ConfigError, match="重新读取"):
        mcp_clients.write_entry(place, EXE, [])
    assert not mcp_clients.written_at(mcp_clients.DESKTOP, place)
    assert (folder / mcp_clients.CONFIG_NAME).exists()


def test_only_claude_desktop_processes_count(monkeypatch):
    store = r"C:\Program Files\WindowsApps\Claude_2.42304.0.0_x64__pzs8sxrjxfjjc\app\claude.exe"
    code = r"C:\Users\x\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\2.1.299\claude.exe"
    squirrel = r"C:\Users\x\AppData\Local\AnthropicClaude\app-0.14.10\claude.exe"
    cli = r"C:\Users\x\.local\bin\claude.exe"
    assert mcp_clients.is_claude_desktop_process("claude.exe", store, "win32")
    assert mcp_clients.is_claude_desktop_process("Claude.exe", squirrel, "win32")
    assert not mcp_clients.is_claude_desktop_process("claude.exe", code, "win32")
    assert not mcp_clients.is_claude_desktop_process("claude.exe", cli, "win32")
    assert not mcp_clients.is_claude_desktop_process("other.exe", store, "win32")
    assert mcp_clients.is_claude_desktop_process("Claude", "/Applications/Claude.app/Contents/MacOS/Claude", "darwin")
    monkeypatch.setattr(mcp_clients, "_windows_processes",
                        lambda image: [("claude.exe", code, 50.0), ("claude.exe", store, 200.0), ("claude.exe", store, 100.0)])
    assert mcp_clients.claude_desktop_started_at("win32") == 100.0
    monkeypatch.setattr(mcp_clients, "_windows_processes", lambda image: [("claude.exe", code, 50.0)])
    assert mcp_clients.claude_desktop_started_at("win32") == 0.0
    monkeypatch.setattr(mcp_clients, "_windows_processes", lambda image: None)
    assert mcp_clients.claude_desktop_started_at("win32") is None      # unknown: nothing is refused


def test_real_process_snapshot_runs():
    rows = mcp_clients._windows_processes("python.exe")
    assert rows is not None and any(when > 0 and path.lower().endswith("python.exe") for _n, path, when in rows)


def test_claude_code_user_config_merge(home, monkeypatch):
    config = home / "home" / mcp_clients.CLAUDE_CODE_CONFIG_NAME
    config.parent.mkdir(parents=True)
    original = {"numStartups": 7, "projects": {"C:/work": {"allowedTools": []}},
                "mcpServers": {"files": {"type": "stdio", "command": "npx", "args": ["fs"], "env": {}}}}
    config.write_text(json.dumps(original), encoding="utf-8")
    place = mcp_clients.claude_code_location()
    assert place.path == config and place.installed
    assert mcp_clients.entry_state(place, EXE, ["--mcp-stdio"], mcp_clients.CODE) == "not_written"
    backup = mcp_clients.write_entry(place, EXE, ["--mcp-stdio"], mcp_clients.CODE)
    written = json.loads(config.read_text(encoding="utf-8"))
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    assert written["mcpServers"]["2byteasr"] == {"type": "stdio", "command": EXE, "args": ["--mcp-stdio"]}
    assert written["mcpServers"]["files"] == original["mcpServers"]["files"]
    assert written["projects"] == original["projects"] and written["numStartups"] == 7
    assert mcp_clients.entry_state(place, EXE, ["--mcp-stdio"], mcp_clients.CODE) == "written"
    assert "Claude Code" in mcp_clients.config_lines(mcp_clients.CODE, "written")[0]
    # The Claude Desktop record is separate.
    assert not mcp_clients.written_at(mcp_clients.DESKTOP, place)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "elsewhere"))
    assert mcp_clients.claude_code_location().path == home / "elsewhere" / mcp_clients.CLAUDE_CODE_CONFIG_NAME


def test_settings_page_asks_before_enabling_and_writes_only_after_confirming(home, monkeypatch):
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    app = QApplication.instance() or QApplication([])
    folder = claude_folder(home)
    monkeypatch.setattr(mcp_clients, "claude_desktop_started_at", lambda platform=None: 0.0)  # Claude closed
    answers = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: answers.pop(0) if answers else QMessageBox.StandardButton.No)
    dialog = ApplicationSettingsDialog(None, {}, home / "Projects", browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.ensure_section('外部 AI（MCP）')               # 2026-10-25: built and refreshed when selected
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
    assert dialog.mcp_values()["allow_glossary"] is False
    dialog.mcp_allow_glossary.setChecked(True)
    assert dialog.mcp_values()["allow_glossary"] is True
    dialog.mcp_client.setCurrentIndex(dialog.mcp_client.findData("claude_code"))
    assert not dialog.mcp_write.isHidden() and dialog.mcp_write.text() == "写入 Claude Code 配置"
    assert dialog.mcp_copy.text() == "复制命令" and "Claude Code：这台电脑上没有找到" in dialog.mcp_status.text()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_settings_page_refuses_while_claude_desktop_runs(home, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    app = QApplication.instance() or QApplication([])
    folder = claude_folder(home)
    monkeypatch.setattr(mcp_clients, "claude_desktop_started_at", lambda platform=None: time.time() - 600)
    warnings, questions = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: questions.append(a[2]) or QMessageBox.StandardButton.Yes)
    dialog = ApplicationSettingsDialog(None, {}, home / "Projects", browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.ensure_section('外部 AI（MCP）')               # 2026-10-25: built and refreshed when selected
    assert dialog.mcp_steps.text().startswith("2. 完全退出 Claude")             # quit first, then write
    assert "正在运行" in dialog.mcp_status.text()
    dialog.mcp_write.click()
    assert warnings and "正在运行" in warnings[0] and not questions        # refused before asking
    assert not (folder / mcp_clients.CONFIG_NAME).exists()
    assert "没有写入" in dialog.mcp_status.text()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
