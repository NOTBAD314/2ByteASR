"""Start-up update reminder: check at every start, pop up a newer version, can be turned off (2026-10-24)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

from twobyteasr.app import application_settings, update_dialog, updater
from twobyteasr.app.updater import UpdatePlan


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "2byteasr_settings.json"
    monkeypatch.setattr(application_settings, "studio_settings_path", lambda: path)
    return path


def _check(version="0.9.0", newer=True):
    manifest = SimpleNamespace(note_for=lambda language: "新版本说明")
    plan = UpdatePlan("setup", (), 1_000_000, 1_000_000, "", (), ())
    return SimpleNamespace(manifest=manifest, plan=plan, latest_version=version, current_version="0.8.4",
                           newer=newer, release_url="https://example.invalid/r", installer_url="https://example.invalid/s")


@pytest.mark.parametrize("enabled, reminded, busy, tries, expected", [
    (True, "", False, 0, "show"),
    (True, "", True, 0, "later"),                       # in the middle of something: wait
    (True, "", True, update_dialog.REMINDER_MAX_TRIES, ""),
    (True, "0.9.0", False, 0, ""),                      # once per start for one version
    (False, "", False, 0, ""),                          # the user turned it off
])
def test_reminder_shows_once_when_the_user_is_free(enabled, reminded, busy, tries, expected):
    assert update_dialog.reminder_action(_check(), enabled=enabled, reminded_version=reminded, busy=busy,
                                         tries=tries) == expected
    assert update_dialog.reminder_action(_check(newer=False), enabled=True, reminded_version="", busy=False) == ""


def test_reminder_check_runs_at_every_start_and_reuses_a_recent_answer(monkeypatch):
    calls, results = [], []
    monkeypatch.setattr(update_dialog, "check_for_update", lambda **kw: calls.append(kw) or "checked")
    monkeypatch.setattr(update_dialog, "automatic_check_due", lambda: False)   # checked an hour ago
    worker = update_dialog.UpdateCheckWorker(automatic=True, reminder=True)
    worker.result_ready.connect(results.append)
    worker.run()
    assert results == ["checked"]
    assert calls == [dict(use_cache=True, cache_seconds=updater.STARTUP_RECHECK_SECONDS)]
    # Reminder off: the old once-a-day background check.
    skipped = []
    quiet = update_dialog.UpdateCheckWorker(automatic=True, reminder=False)
    quiet.skipped.connect(lambda: skipped.append(True))
    quiet.run()
    assert skipped == [True] and len(calls) == 1
    assert update_dialog.UpdateCheckWorker(reminder=True).reminder is False   # only the automatic check


def test_the_reminder_runs_soon_after_start(monkeypatch):
    monkeypatch.delenv(updater.AUTO_DELAY_ENV, raising=False)
    assert updater.automatic_check_delay_ms(True) == updater.REMINDER_DELAY_MS == 5_000
    assert updater.automatic_check_delay_ms() == updater.AUTO_DELAY_MS
    monkeypatch.setenv(updater.AUTO_DELAY_ENV, "200")
    assert updater.automatic_check_delay_ms(True) == 200


def test_the_popped_up_offer_has_the_switch(app):
    dialog = update_dialog.UpdateOfferDialog(_check(), reminder=True)
    box = dialog.findChild(QCheckBox, "updateReminderBox")
    assert box is not None and box.isChecked() and dialog.keep_reminding
    box.setChecked(False)
    assert dialog.keep_reminding is False
    assert update_dialog.UpdateOfferDialog(_check()).findChild(QCheckBox, "updateReminderBox") is None


def test_preference_defaults_on_and_saving_keeps_other_settings(settings_file):
    assert application_settings.update_reminder_enabled() is True
    settings_file.write_text(json.dumps({"project_root": "D:/p", "studio_preferences": {"reduce_motion": True}}),
                             "utf-8")
    application_settings.save_update_reminder(False)
    payload = json.loads(settings_file.read_text("utf-8"))
    assert payload["studio_preferences"] == {"reduce_motion": True, "update_reminder": False}
    assert payload["project_root"] == "D:/p" and application_settings.update_reminder_enabled() is False
    application_settings.save_hub_preferences("", True, 60, 9, True, True, update_reminder=True)
    assert json.loads(settings_file.read_text("utf-8"))["studio_preferences"]["update_reminder"] is True
    application_settings.save_hub_preferences("", True, 60, 9, True, True)      # not given: kept
    assert application_settings.update_reminder_enabled() is True


def test_settings_page_shows_the_switch(app, tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    for value in (True, False):
        dialog = ApplicationSettingsDialog(None, {"update_reminder": value}, tmp_path / "Projects",
                                           browse=lambda *a: None, clear_recent=lambda: None, reset_layout=None)
        dialog.ensure_section("关于")                     # 2026-10-25: a category is built when first shown
        box = dialog.findChild(QCheckBox, "updateReminderSetting")
        assert box is dialog.update_reminder_box and box.isChecked() is value
        dialog.deleteLater()


def test_unticking_in_the_popped_up_offer_turns_the_reminder_off(app, monkeypatch):
    from twobyteasr.app import ui
    saved = []
    monkeypatch.setattr(application_settings, "save_update_reminder", saved.append)

    def answer(dialog):
        dialog.remind_box.setChecked(False)
        return 0
    monkeypatch.setattr(ui.UpdateOfferDialog, "exec", answer)
    host = QWidget()
    ui.MainWindow._offer_update(host, _check(), reminder=True)
    assert saved == [False] and host._update_offer_dialog is None
    monkeypatch.setattr(ui.UpdateOfferDialog, "exec", lambda dialog: 0)
    ui.MainWindow._offer_update(host, _check(), reminder=True)     # left ticked: nothing saved
    ui.MainWindow._offer_update(host, _check())                    # 检查更新 by hand: no switch
    assert saved == [False]
    host.deleteLater()


def test_a_busy_user_gets_the_reminder_later_and_only_once(app, monkeypatch):
    from twobyteasr.app import ui
    monkeypatch.setattr(application_settings, "update_reminder_enabled", lambda: True)
    scheduled, offered = [], []
    monkeypatch.setattr(ui.QTimer, "singleShot", lambda delay, receiver, slot: scheduled.append((delay, slot)))
    host = QWidget()
    check = _check()
    host._available_update = check
    host._offer_update = lambda c, reminder=False: offered.append((c.latest_version, reminder))
    host._update_reminder_busy = lambda: True
    ui.MainWindow._remind_update(host, check)
    assert offered == [] and scheduled[0][0] == update_dialog.REMINDER_RETRY_MS
    host._update_reminder_busy = lambda: False
    ui.MainWindow._remind_update(host, check, 1)
    ui.MainWindow._remind_update(host, check, 2)               # already offered at this start
    assert offered == [("0.9.0", True)] and len(scheduled) == 1
    host.deleteLater()
