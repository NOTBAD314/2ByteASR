from pathlib import Path
from types import SimpleNamespace
import json

from twobyteasr.app.external_open import classify_open_paths, startup_destination


def test_type_dispatch_never_turns_a_project_into_media():
    paths = ['中文 (校对)&.2byteproj', 'video.mp4', '字幕.ass', 'video.mp4', 'bad.xyz']
    assert [kind for kind, _ in classify_open_paths(paths)] == ['project', 'media', 'subtitle', 'unsupported']
    assert classify_open_paths(['missing.2byteproj']) == [('project', 'missing.2byteproj')]
    assert classify_open_paths(['OLD.2BYTEASRPROJ'])[0][0] == 'project'


def test_startup_precedence_is_explicit_files_then_preference():
    prefs = {'startup_page': 'project_library'}
    assert startup_destination([], {}) == 'recognition'
    assert startup_destination([], prefs) == 'project_library'
    assert startup_destination(['missing.2byteproj'], {}) == 'project_library'
    assert startup_destination(['video.mp4'], prefs) == 'recognition'
    assert startup_destination([], prefs, explicit_operation=True) == 'recognition'


def test_preferences_survive_save_and_keep_unrelated_fields(tmp_path, monkeypatch):
    from twobyteasr.app import application_settings as settings
    path = tmp_path/'studio.json'
    path.write_text(json.dumps({'studio_preferences': {'future': 'kept'}, 'recent_projects': ['kept']}))
    monkeypatch.setattr(settings, 'studio_settings_path', lambda: path)
    settings.save_hub_preferences('', True, 60, 9, True, True, startup_page='project_library')
    assert settings.read_studio_preferences()['startup_page'] == 'project_library'
    settings.save_hub_preferences('', False, 30, 9, True, True)
    assert settings.read_studio_preferences()['startup_page'] == 'project_library'
    assert settings.read_studio_preferences()['future'] == 'kept'
    assert json.loads(path.read_text())['recent_projects'] == ['kept']


def test_external_project_queue_waits_for_readiness_and_retains_subtitle_semantics():
    from PySide6.QtWidgets import QApplication, QWidget, QLabel
    from twobyteasr.app.desktop_intake import DesktopIntake
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window._run_in_progress, window.worker = False, None
    window.header_status = QLabel(window)
    calls = []
    gate = SimpleNamespace(active=True)
    window.studio_page = SimpleNamespace(_readiness=gate,
        _import_subtitle_file=lambda path: calls.append(('subtitle', path)))
    window.open_studio_project = lambda path, **kwargs: calls.append(('project', path, kwargs))
    window._switch_page = lambda page: calls.append(('page', page))
    intake = DesktopIntake(window)
    intake.submit(['中文 & (1).2byteproj', 'caption.srt'])
    assert not calls
    gate.active = False
    intake._next()
    assert calls[0][:2] == ('project', '中文 & (1).2byteproj')
    assert calls[0][2]['source'] == 'external'
    intake._next()
    assert calls[-1] == ('subtitle', Path('caption.srt'))
    intake.timer.stop()
    window.deleteLater()
    app.processEvents()


def test_association_preserves_existing_default_and_never_writes_userchoice(tmp_path):
    from twobyteasr.projects.project_file_association import repair_project_association, PROG_ID
    from contextlib import nullcontext
    values = {('Software\\Classes\\.2byteproj', ''): 'Other.Project'}
    class Registry:
        HKEY_CURRENT_USER, REG_SZ = 1, 1
        def CreateKey(self, hive, path):
            assert 'UserChoice' not in path
            return nullcontext(path)
        def SetValueEx(self, key, name, reserved, kind, value):
            values[(key,name)] = value
        def QueryValueEx(self, key, name):
            if (key,name) not in values:
                raise FileNotFoundError()
            return values[(key,name)], self.REG_SZ
    entry = tmp_path/'中文 (启动)&.exe'
    entry.write_bytes(b'fixture')
    repair_project_association(entry=entry, registry=Registry(), notify=False)
    assert values[('Software\\Classes\\.2byteproj','')] == 'Other.Project'
    assert values[('Software\\Classes\\'+PROG_ID+'\\shell\\open\\command','')] == f'"{entry}" "%1"'
