from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QComboBox, QCheckBox
from twobyteasr.app.ui import MainWindow
from twobyteasr.storage.settings import load_runtime_settings
import json


def owner():
    app = QApplication.instance() or QApplication([])
    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={'glossary': {'enabled_glossary_ids': ['first'], 'enable_domain_terms': True}},
        canonicalize_runtime_game_name=lambda v: v,
        runtime_game_identity=lambda v: v.lower(),
        resolve_glossary_identity=lambda v: {'瓦罗兰特': 'valorant-id'}.get(v, v),
        glossary_catalog=lambda: [{'id': 'valorant-id', 'name': '瓦罗兰特', 'revision': 'v1'}],
        load_game_profiles=lambda: {}, learned_mappings_for_game=lambda _: [],
        load_runtime_game_history=lambda: [], BUILTIN_GAME_PROFILES={},
    )
    result = SimpleNamespace(legacy=legacy, game_box=QComboBox(), terms=QCheckBox(),
                             _save_glossary_settings=lambda: None,
                             _refresh_glossary_chips=lambda: None,
                             _enabled_glossary_ids=lambda: list(legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids']))
    result.game_box.setEditable(True)
    result.game_box.setCurrentText('瓦罗兰特')
    result.terms.setChecked(True)
    result._app = app
    return result


def test_binding_keeps_previous_independent_libraries():
    window = owner()
    MainWindow._resolve_glossary_binding(window)
    assert window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] == ['first', 'valorant-id']


def test_refresh_content_choices_reads_catalog_without_enabling():
    window = owner()
    MainWindow._refresh_content_choices(window)
    assert window.game_box.findData('valorant-id') >= 0
    assert window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] == ['first']
    assert window.game_box.currentText() == '瓦罗兰特'


def test_explicit_empty_batch_does_not_reenable_on_restart(tmp_path):
    (tmp_path/'2byteasr_settings.json').write_text(json.dumps({'glossary': {
        'content_name': '瓦罗兰特', 'selected_glossary': '瓦罗兰特',
        'enabled_glossary_ids': [], 'enable_domain_terms': False}}), encoding='utf-8')
    settings, _, _ = load_runtime_settings(tmp_path)
    assert settings['glossary']['enabled_glossary_ids'] == []


def test_saved_switch_restores_independent_batch_without_content_selection():
    window = owner()
    window.terms.setChecked(False)
    MainWindow._restore_glossary_switch(window)
    assert window.terms.isChecked()
    assert window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] == ['first']
    window.legacy.RUNTIME_SETTINGS['glossary']['enable_domain_terms'] = False
    MainWindow._restore_glossary_switch(window)
    assert not window.terms.isChecked()
    assert window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] == ['first']


def test_studio_task_uses_its_libraries_with_home_disabled():
    window = owner()
    window.terms.setChecked(False)
    window._studio_recognition_context = {'enabled_glossary_ids': ['project-library']}
    assert MainWindow._task_glossary_selection(window) == (('project-library',), True)


def test_explicit_empty_project_does_not_inherit_enabled_home_library():
    window = owner()
    window._studio_recognition_context = {'enabled_glossary_ids': []}
    assert MainWindow._task_glossary_selection(window) == ((), False)
    window._studio_recognition_context = None
    assert MainWindow._task_glossary_selection(window) == (('first',), True)
    window.terms.setChecked(False)
    assert MainWindow._task_glossary_selection(window) == ((), False)
