"""The home plan menu names a chosen plan whose models are still to download (2026-10-24).

On a fresh install the selectors list installed models only, so right after
云端识别 or 本地识别 is chosen the selectors of the models still to download sit
on their 未选择 / 已关闭 fallbacks. The menu read those and said 自定义; it now
reads the saved choice, as the home cards do.
"""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from twobyteasr.app import ui
from twobyteasr.recognition.recognition_plans import plan_options


class Home:
    """The parts of the home page the plan menu and the first-run choice use."""

    _shown_asr_backends = ui.MainWindow._shown_asr_backends
    _show_plan_choice = ui.MainWindow._show_plan_choice
    _refresh_recognition_recommendation = ui.MainWindow._refresh_recognition_recommendation

    def __init__(self, spoken):
        self.legacy = SimpleNamespace(RUNTIME_SETTINGS={"models": {}})
        self.primary_asr_backend, self.qwen_asr_backend, self.firered_asr_backend = (
            QComboBox(), QComboBox(), QComboBox())
        self.qwen_asr_api_provider = QComboBox()
        self.qwen_asr_api_provider.addItem("MOSS Pro", "mosi_moss_pro")
        self.recognition_language = QComboBox()
        self.recognition_language.addItem(spoken, spoken)
        self.recognition_mode_combo = QComboBox()
        for plan in plan_options():
            self.recognition_mode_combo.addItem(plan.label, plan.key)
        self.recognition_plan_hint = QLabel()
        self.media_paths = []
        self._missing_saved_asr_backends = ui.populate_available_asr_choices(
            self.primary_asr_backend, self.qwen_asr_backend, self.firered_asr_backend,
            self.legacy.RUNTIME_SETTINGS)

    def _subtitle_language_options(self):
        return {"recognition_language": str(self.recognition_language.currentData())}

    def _asr_values(self):
        return {"primary_asr_backend": str(self.primary_asr_backend.currentData()),
                "qwen_asr_backend": str(self.qwen_asr_backend.currentData()),
                "firered_asr_backend": str(self.firered_asr_backend.currentData())}

    def _apply_asr_backend_mode(self):
        pass


@pytest.fixture
def fresh_install(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: set())   # nothing downloaded yet
    monkeypatch.setattr(ui, "persist_asr_configuration",
                        lambda legacy, values, **_kwargs: legacy.RUNTIME_SETTINGS["models"].update(values))


@pytest.mark.parametrize(("spoken", "backends", "plan"), [
    ("auto", ("api", "local", "off"), "moss_pro_qwen"),           # 云端识别, Chinese: FireRedASR2 to download
    ("en", ("api", "qwen_aligner", "off"), "moss_pro_qwen"),      # 云端识别, other languages: Qwen3 对齐
    ("auto", ("moss", "local", "local"), "quality"),              # 本地识别: all three to download
    ("ja", ("moss", "qwen_aligner", "local"), "japanese"),
    ("en", ("moss", "qwen_aligner", "local"), "english"),
])
def test_plan_menu_names_the_chosen_plan_while_its_models_download(fresh_install, spoken, backends, plan):
    home = Home(spoken)
    home._refresh_recognition_recommendation()
    assert home.recognition_mode_combo.currentData() == "custom"   # nothing chosen yet

    primary, timeline, review = backends
    keys = ui.GuidedSetupDialog.download_keys_for(primary, timeline, review)
    ui._apply_setup_choice(home, primary, timeline, review, keys, open_workshop=False, auto_download=False)

    # The selectors still fall back (the models are not there) ...
    assert (home.firered_asr_backend.currentData(), home.qwen_asr_backend.currentData()) == ("off", "off")
    # ... and the menu names the plan at once, without 自定义 in it.
    assert home.recognition_mode_combo.currentData() == plan
    assert home.recognition_mode_combo.findData("custom") < 0


def test_a_selector_choice_made_since_wins_over_the_pending_one(fresh_install):
    home = Home("auto")
    ui._apply_setup_choice(home, "moss", "local", "local", (), open_workshop=False, auto_download=False)
    assert home.recognition_mode_combo.currentData() == "quality"

    # 文字复核 switched to the API by hand: no longer 本地识别.
    home.qwen_asr_backend.setCurrentIndex(home.qwen_asr_backend.findData("api"))
    assert home._shown_asr_backends() == ("moss", "local", "api")
    home._refresh_recognition_recommendation()
    assert home.recognition_mode_combo.currentData() == "custom"
