import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QCheckBox, QDialog, QWidget

@pytest.fixture
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design import theme_manager
    monkeypatch.setattr(theme_manager, '_settings', lambda: QSettings(str(tmp_path/'theme.ini'), QSettings.Format.IniFormat))
    return app

def test_picker_keeps_canceled_selection_in_place_until_reopened(app):
    from twobyteasr.local_models.model_workshop import ModelPickerPanel, CANONICAL_MODEL_ORDER, MODELS, _model_roles
    keys = [key for key in CANONICAL_MODEL_ORDER if any(m.key == key and 'primary' in _model_roles(m) for m in MODELS)]
    class Controller(QObject):
        models_refreshed = Signal()
        api_configure_requested = Signal(str)
        selected = keys[-1]
        def _model_state(self, model, role): return 'selected' if model.key == self.selected else 'installed'
        def _action_text(self, model, state): return ('取消使用' if state == 'selected' else '使用', True)
    controller = Controller()
    picker = ModelPickerPanel(controller, 'primary')
    assert picker.cards_layout.itemAt(0).widget() is picker.cards[keys[-1]]
    controller.selected = ''; picker.refresh()
    assert picker.cards_layout.itemAt(0).widget() is picker.cards[keys[-1]]
    # MainWindow retains the same panel between openings.
    picker.resize(860, 680); picker.show(); app.processEvents()
    picker.scroll.verticalScrollBar().setValue(100)
    picker.begin_session()
    assert picker.cards_layout.itemAt(0).widget() is picker.cards[keys[0]]
    assert picker.scroll.verticalScrollBar().value() == 0
    controller.selected = keys[1]; picker.refresh()
    assert picker.cards_layout.itemAt(0).widget() is picker.cards[keys[1]]
    picker.hide(); picker.deleteLater()

def test_advanced_settings_edit_is_transactional(app, monkeypatch, tmp_path):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.storage import settings as runtime
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    owner = QWidget(); owner.advanced_disclosure = True
    owner.legacy = SimpleNamespace(RUNTIME_SETTINGS={'switches': {}, 'cache': {}})
    for name in ('dialogue_coverage', 'expected_speakers', 'overwrite'):
        control = QComboBox(owner); control.addItem('默认', 'default'); control.addItem('修改', 'changed'); setattr(owner, name, control)
    for name in ('review_track','jianying_txt','speaker_tracks','refresh_polish','refresh_group'):
        setattr(owner, name, QCheckBox(owner))
    saved=[]
    monkeypatch.setattr(runtime, 'save_runtime_settings', lambda data: (saved.append(data.copy()) or data, None, []))
    monkeypatch.setattr(settings, 'save_hub_preferences', lambda *a: None)
    monkeypatch.setattr(settings, 'project_library_root', lambda: tmp_path)
    monkeypatch.setattr(settings, 'apply_theme', lambda *a: None)
    def edit(dialog, accepted):
        assert dialog.pages.count() == 5
        dialog.advanced_controls['review_track'].setChecked(True)
        dialog.advanced_controls['dialogue_coverage'].setCurrentIndex(1)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
    monkeypatch.setattr(ApplicationSettingsDialog, 'exec', lambda d: edit(d, False))
    assert not settings.open_application_settings(owner)
    assert not owner.review_track.isChecked() and owner.dialogue_coverage.currentIndex() == 0 and not saved
    monkeypatch.setattr(ApplicationSettingsDialog, 'exec', lambda d: edit(d, True))
    assert settings.open_application_settings(owner)
    assert owner.review_track.isChecked() and saved[0]['switches']['dialogue_coverage_mode'] == 'changed'
