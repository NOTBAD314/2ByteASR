"""兔白助手 install guide (2026-11-26): what it can see and how the steps move."""
import json
import time
from pathlib import Path

import pytest

from twobyteasr.app import browser_helper_setup as setup
from twobyteasr.app.browser_link_protocol import validate

ROOT = Path(__file__).resolve().parents[1]


def test_ping_may_name_its_browser_but_nothing_else():
    assert validate({"version": 1, "action": "ping"}, allow_ping=True) == {"version": 1, "action": "ping"}
    assert validate({"version": 1, "action": "ping", "browser": "Edge"}, allow_ping=True)["browser"] == "Edge"
    for bad in ({"version": 1, "action": "ping", "browser": "Safari"},
                {"version": 1, "action": "ping", "browser": []},
                {"version": 1, "action": "ping", "browser": "Edge", "path": "C:/"}):
        with pytest.raises(ValueError):
            validate(bad, allow_ping=True)
    with pytest.raises(ValueError):
        validate({"version": 1, "action": "ping", "browser": "Edge"})        # only where pings are allowed


def test_reads_the_helper_from_a_chromium_profile_without_writing(tmp_path):
    ident = setup.extension_id(ROOT)
    profile = tmp_path / "Microsoft/Edge/User Data/Profile 2"
    profile.mkdir(parents=True)
    secure = profile / "Secure Preferences"
    secure.write_text(json.dumps({"extensions": {"settings": {
        ident: {"path": str(ROOT / "assets/browser-helper"), "manifest": {"version": "0.1.0"}, "state": 1}}}}),
        encoding="utf-8")
    before = secure.read_bytes()
    (profile / "Preferences").write_text('{"extensions": []}', encoding="utf-8")
    found = setup.helper_in_browser(ROOT, "Edge", local_app_data=tmp_path)
    assert found["loaded"] and found["version"] == "0.1.0" and found["enabled"] and found["profile"] == "Profile 2"
    assert setup.same_folder(ROOT, found["path"])
    assert secure.read_bytes() == before
    secure.unlink()
    assert setup.helper_in_browser(ROOT, "Edge", local_app_data=tmp_path) == {"loaded": False}
    (tmp_path / "Google/Chrome/User Data/Default").mkdir(parents=True)
    assert setup.helper_in_browser(ROOT, "Chrome", local_app_data=tmp_path) == {"loaded": False}
    assert setup.helper_in_browser(ROOT, "Brave", local_app_data=tmp_path) is None     # no profile folder
    assert setup.helper_in_browser(ROOT, "Firefox", local_app_data=tmp_path) is None   # session only


def test_contact_is_kept_per_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_contact_path", lambda: tmp_path / setup.CONTACT_FILE)
    assert setup.last_contact() == {}
    setup.record_contact("Edge")
    setup.record_contact("Netscape")
    seen = setup.last_contact()
    assert set(seen) == {"Edge"} and abs(seen["Edge"] - time.time()) < 60


@pytest.fixture
def window(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    from twobyteasr.app import browser_helper_dialog as mod
    state = dict(linked=False, helper={"loaded": False}, contact={})
    monkeypatch.setattr(mod, "detect", lambda: {"Edge": Path("msedge.exe"), "Chrome": Path("chrome.exe")})
    monkeypatch.setattr(mod, "registration", lambda root, name, change=None: state["linked"] or change == "install")
    monkeypatch.setattr(mod, "helper_in_browser", lambda root, name: state["helper"])
    monkeypatch.setattr(mod, "last_contact", lambda: state["contact"])
    parent = QWidget()
    dialog = mod.HelperWindow(parent)
    yield dialog, state, mod
    dialog.close()
    parent.deleteLater()


def test_guide_opens_at_the_first_unfinished_step_and_ticks_what_it_sees(window):
    dialog, state, mod = window
    assert dialog.pages.currentIndex() == 0 and dialog.browser == "Edge"
    assert mod.STEPS[dialog.step] == "link"                 # choosing a browser counts once one is found
    state["linked"] = True
    dialog.refresh()
    assert "link" in dialog.done_steps("Edge") and dialog.stubs[1].property("state") == "now"
    dialog.go(3)
    assert dialog.path_row.isVisibleTo(dialog) and dialog.primary.text()
    state["helper"] = {"loaded": True, "path": "", "version": "0.2.0", "enabled": True}
    dialog.refresh()
    assert {"dev", "load"} <= dialog.done_steps("Edge")
    assert dialog.stubs[2].property("state") == "done"
    state["contact"] = {"Chromium": time.time()}
    assert "try" not in dialog.done_steps("Edge")
    state["contact"] = {"Edge": time.time()}
    dialog.go(5)
    assert set(mod.STEPS) <= dialog.done_steps("Edge")
    dialog.next.click()                                       # 完成 on the last step opens 我的浏览器
    assert dialog.pages.currentIndex() == 1


def test_stuck_swaps_the_tip_and_browsers_list_shows_each_state(window):
    dialog, state, mod = window
    dialog.go(2)
    tip = dialog.tip_text.text()
    dialog.stuck.click()
    assert dialog.tip_text.text() != tip and dialog.mascot.mood == "sad"
    state.update(linked=True, helper={"loaded": True, "path": "", "version": "0.1.0", "enabled": True},
                 contact={"Edge": time.time()})
    dialog.show_tab("manage")
    texts = [label.text() for label in dialog.pages.widget(1).findChildren(type(dialog.kicker))]
    assert any("0.1.0" in text for text in texts)
    assert dialog.update_bar.isVisibleTo(dialog) and dialog._stale == "Edge"   # loaded 0.1.0, folder has newer
