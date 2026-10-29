import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget, QDialog
from twobyteasr.app import application_settings as settings


def test_invalid_numeric_preference_does_not_prevent_settings_open(tmp_path, monkeypatch):
    path = tmp_path / 'studio-settings.json'
    path.write_text(json.dumps({'studio_preferences': {'autosave_interval_seconds': 'broken',
                                                       'recent_project_count': [], 'other': 42}}))
    original = path.read_bytes()
    monkeypatch.setattr(settings, 'studio_settings_path', lambda: path)
    prefs = settings.read_studio_preferences()
    assert prefs['autosave_interval_seconds'] == 60
    assert prefs['recent_project_count'] == 9
    assert prefs['other'] == 42
    assert path.read_bytes() == original


def test_repair_save_backs_up_original_and_preserves_unknown_fields(tmp_path, monkeypatch):
    path=tmp_path/'settings.json'
    original=json.dumps({'studio_preferences':{'autosave_interval_seconds':'bad','other':42},'unrelated':{'keep':True}}).encode()
    path.write_bytes(original)
    monkeypatch.setattr(settings,'studio_settings_path',lambda:path)
    preferences, repaired=settings._preferences_snapshot()
    assert repaired==['autosave_interval_seconds']
    settings._write_settings_json(lambda payload:payload.update(studio_preferences=preferences))
    backups=list(tmp_path.glob('settings.json.before-repair-*'))
    assert len(backups)==1 and backups[0].read_bytes()==original
    actual=json.loads(path.read_text('utf8'))
    assert actual['unrelated']=={'keep':True} and actual['studio_preferences']['other']==42
    assert actual['studio_preferences']['autosave_interval_seconds']==60


def test_settings_constructor_cannot_reenter_or_duplicate():
    from twobyteasr.app.settings_lifecycle import owned_settings, retain
    app = QApplication.instance() or QApplication([])
    owner = QWidget(); calls=[]
    @owned_settings('test')
    def opening(parent):
        calls.append('created')
        assert opening(parent) is False
        dialog = QDialog(parent)
        retain(parent, dialog, 'test')
        dialog.show()
        return dialog
    dialog = opening(owner)
    assert opening(owner) is False
    assert calls == ['created']
    dialog.close(); dialog.deleteLater(); owner.deleteLater()
