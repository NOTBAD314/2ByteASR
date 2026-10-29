"""Normal app, real Qt controls, loopback HTTP and actual Stage 9 grouping."""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import traceback
from pathlib import Path


def install_guards():
    from .run_diagnosis_audit import install_guards as loopback_guards
    loopback_guards()


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..providers.ai_config_state import configuration_state
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..storage.settings import load_runtime_settings
    import requests

    app = QApplication.instance()
    phase = os.environ.get('TWOBYTEASR_AI_CONFIG_PHASE', 'live')
    peer = os.environ['TWOBYTEASR_AI_CONFIG_PEER']
    result = {'checks': [], 'observations': [], 'tasks': [], 'errors': [], 'phase': phase,
              'executable': __import__('sys').executable, 'passed': False}

    def check(name, value):
        result['checks'].append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)

    def settle(ms=150):
        deadline = time.monotonic() + ms / 1000
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)

    def wait_for(predicate):
        deadline = time.monotonic() + 20
        while not predicate() and time.monotonic() < deadline:
            settle(20)
        check('background operation completed', predicate())

    def observe(label):
        settings = window.legacy.RUNTIME_SETTINGS
        live = configuration_state(settings)
        disk = configuration_state(load_runtime_settings()[0])
        profile = window.current_project_profile
        result['observations'].append({'point': label, 'disk': disk, 'live': live,
            'card': window.setting_tiles['ai'].view.state,
            'gate': window._ai_gate_state,
            'profile': {'model': getattr(profile, 'llm_config_ref', ''),
                        'enabled': getattr(profile, 'llm_enabled', None)},
            'editors': {role: {'model': getattr(window, role+'_editor').model.currentText(),
                              'live_reference': getattr(window, role+'_editor')._settings_ref is settings}
                        for role in ('polish', 'group')}})
        check(label + ': disk and live agree', disk == live)
        if profile is not None and label != 'before':
            check(label + ': selected profile tracks saved grouping model',
                  profile.llm_config_ref == live['stages']['group']['model'])
        window.grab().save(str(output / (phase + '-' + label + '.png')))
        return live

    def open_settings():
        card = window.setting_tiles['ai']
        button = card.connect_button if not card.connect_button.isHidden() else card.settings_button
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        settle()
        check('home card opens AI settings', window._ai_settings_dialog is not None)

    def select_profile(profile):
        from PySide6.QtWidgets import QMessageBox
        timer=QTimer(window);timer.setInterval(25)
        def accept_switch():
            box=app.activeModalWidget()
            if isinstance(box,QMessageBox):
                for button in box.buttons():
                    if box.buttonRole(button)==QMessageBox.ButtonRole.DestructiveRole:
                        timer.stop();button.click();return
        timer.timeout.connect(accept_switch);timer.start()
        try:
            window.project_profile_combo.setCurrentIndex(window.project_profile_combo.findData(profile.id))
        finally:timer.stop();timer.deleteLater()
        settle(300)

    def configure(model, credential):
        window.ai_polish.setChecked(True)
        window.ai_grouping.setChecked(True)
        window.unified_glm.setChecked(True)
        editor = window.group_editor
        editor.service.setCurrentIndex(editor.service.findData('custom'))
        editor.base_url.setText(peer + '/v1')
        editor.model.setCurrentText(model)
        editor.key.setText('sk-ai-live-' + credential)
        return editor

    def save():
        QTest.mouseClick(window.ai_dialog_save_button, Qt.MouseButton.LeftButton)
        settle(300)
        check('save closes after successful application', window._ai_settings_dialog is None)

    def test(editor):
        QTest.mouseClick(editor.test_button, Qt.MouseButton.LeftButton)
        worker = editor._tester
        check('test started actual worker', worker is not None)
        wait_for(lambda: not worker.isRunning())
        settle(80)
        check('actual HTTP test succeeded', editor.last_connection_ok is True)

    def task(label, settings=None, frozen=None):
        from ..recognition.service import RunOptions
        from ..recognition.run_context import activate_runtime_context
        from ..recognition.text_ai_plan import bind_text_ai_snapshots
        from ..subtitle_rules.grouping import group_subtitles
        settings = settings or window._run_settings_snapshot()
        options = RunOptions(settings_snapshot_json=json.dumps(settings), recognition_language='zh')
        context = options.create_runtime_context(window.legacy)
        context.asr_settings_snapshot = copy.deepcopy(settings)
        plan = bind_text_ai_snapshots(context, settings)
        if frozen is not None:
            context.provider_snapshots['group'] = frozen
            context.provider_snapshot = frozen
        snap = context.provider_snapshots.get('group')
        row = window.legacy.SpeechSegment(1, 0, 4, '我们现在去看看那边的情况', .9, [], speaker='S01')
        with activate_runtime_context(context, legacy=window.legacy):
            cues = group_subtitles([row], use_ai=plan.group, provider_snapshot=snap, max_workers=1)
        check(label + ': real grouping preserves text', ''.join(c.text for c in cues) == row.text)
        check(label + ': actual AI/local origin', bool(getattr(cues, 'validated', False)) == plan.group)
        result['tasks'].append({'point': label, 'enabled': plan.group,
                               'service': snap.provider if snap else '', 'model': snap.model if snap else '',
                               'client_revision': snap.profile_revision if snap else '',
                               'ai_validated': bool(getattr(cues, 'validated', False))})

    def control(model, paused):
        requests.post(peer + '/control', json={'model': model, 'pause': paused}, timeout=3).raise_for_status()

    def run():
        try:
            window._return_to_settings()
            window.resize(1380, 940)
            settle(400)
            if phase == 'restart':
                state = observe('reloaded')
                previous = json.loads((output / 'live-result.json').read_text('utf-8'))
                check('restart preserves effective configuration', state == previous['final_state'])
                check('restart home ready', window.setting_tiles['ai'].view.state == 'ready')
                task('restarted_task')
            else:
                profile = window.profile_store.create('AI 保存验收', **window._profile_configuration())
                window.current_project_profile = profile
                window.profile_store.set_last_selected(profile.id)
                observe('before')
                open_settings()
                editor = configure('model-A', 'A')
                test(editor)
                window.ai_advanced_toggle.setChecked(False)
                settle()
                window._ai_settings_dialog.grab().save(str(output / 'live-tested-dialog.png'))
                save()
                observe('saved_A')
                bookmark_A = copy.deepcopy(window._profile_configuration())
                window._return_to_settings()
                observe('home_A')
                task('first_task_A')
                frozen = resolve_provider_snapshot(window._run_settings_snapshot())
                old_settings = window._run_settings_snapshot()
                control('model-A', True)
                errors = []
                def running_task():
                    try:
                        task('running_task_A', old_settings, frozen)
                    except BaseException:
                        errors.append(traceback.format_exc())
                count = len(requests.get(peer + '/requests', timeout=3).json())
                thread = threading.Thread(target=running_task)
                thread.start()
                wait_for(lambda: len(requests.get(peer + '/requests', timeout=3).json()) > count)
                open_settings()
                editor = configure('model-B', 'B')
                test(editor)
                save()
                observe('saved_B')
                control('model-A', False)
                wait_for(lambda: not thread.is_alive())
                check('running task completes on its original configuration', not errors)
                task('next_task_B')
                for enabled in (False, True, True):
                    open_settings()
                    window.ai_polish.setChecked(enabled)
                    window.ai_grouping.setChecked(enabled)
                    save()
                    check('local glossary remains available', window.terms.isEnabled())
                    task('enabled_' + str(enabled))
                # Explicit Home enable intent differs from ordinary configuration editing.
                window._open_ai_settings_dialog();settle()
                window.ai_polish.setChecked(False);window.ai_grouping.setChecked(False);save()
                observe('configured_not_enabled')
                check('configured OFF has accurate label','已配置' in window.setting_tiles['ai'].state_chip.text())
                window._open_ai_settings_dialog();settle()
                check('ordinary settings preserves OFF',not window.ai_grouping.isChecked())
                window._ai_settings_dialog.reject();settle(300)
                open_settings();check('Home enable selects grouping draft',window.ai_grouping.isChecked())
                window._ai_settings_dialog.reject();settle(300)
                check('cancel enable restores OFF',not window.ai_grouping.isChecked())
                open_settings();save()
                check('Home enable applied to next task',window._run_settings_snapshot()['switches']['use_ai_grouping'])
                check('Home enable preserves polish OFF',not window._run_settings_snapshot()['switches']['enable_ai_polish'])
                from ..app.ui import _ai_unlocked
                check('translation service independent of polish switch',_ai_unlocked(window))
                task('home_explicit_enable_B')
                open_settings();editor=configure('model-failed-check','B')
                editor.test_connection();failed_worker=editor._tester
                wait_for(lambda:not failed_worker.isRunning());settle(100)
                check('failed connection is reported',editor.last_connection_ok is False)
                save();observe('failed_connection_preserved')
                check('failure retains saved configuration',window.group_editor.model.currentText()=='model-failed-check')
                check('failure label differs from OFF',window.setting_tiles['ai'].view.state=='failed')
                open_settings();editor=configure('model-B','B');test(editor);save()
                before = configuration_state(window.legacy.RUNTIME_SETTINGS)
                open_settings()
                configure('cancelled-model', 'C')
                window._ai_settings_dialog.reject()
                settle(300)
                check('cancel preserves live state', configuration_state(window.legacy.RUNTIME_SETTINGS) == before)
                check('cancel restores editor', window.group_editor.model.currentText() == 'model-B')

                open_settings()
                editor = configure('model-C', 'C')
                control('model-C', True)
                count = len(requests.get(peer + '/requests', timeout=3).json())
                editor.test_connection()
                old_test = editor._tester
                wait_for(lambda: len(requests.get(peer + '/requests', timeout=3).json()) > count)
                editor.model.setCurrentText('model-C-new')
                save()
                control('model-C', False)
                wait_for(lambda: not old_test.isRunning())
                settle(80)
                check('old test cannot validate new model', window.setting_tiles['ai'].view.state == 'untested')
                observe('old_result_discarded')

                open_settings()
                editor = window._primary_ai_editor()
                check('saved key is represented by an empty input', not editor.key.text())
                control('model-C-new', True)
                count = len(requests.get(peer + '/requests', timeout=3).json())
                editor.test_connection()
                cleared_test = editor._tester
                wait_for(lambda: len(requests.get(peer + '/requests', timeout=3).json()) > count)
                editor._request_key_clear()
                check('explicit clear retires the old test', editor._tester is None)
                save()
                control('model-C-new', False)
                wait_for(lambda: not cleared_test.isRunning())
                settle(80)
                check('old credential cannot become ready after clear', window.setting_tiles['ai'].view.state == 'untested')

                open_settings()
                editor = configure('model-B', 'B')
                control('model-B', True)
                count = len(requests.get(peer + '/requests', timeout=3).json())
                editor.test_connection()
                same_test = editor._tester
                wait_for(lambda: len(requests.get(peer + '/requests', timeout=3).json()) > count)
                save()
                check('same-config test remains pending across save', editor._tester is same_test)
                check('home shows actual testing', window.setting_tiles['ai'].view.state == 'testing')
                observe('testing_after_save')
                control('model-B', False)
                wait_for(lambda: not same_test.isRunning())
                settle(80)
                check('pending result updates home without restart', window.setting_tiles['ai'].view.state == 'ready')
                task('final_task_B')
                profile_B = window.profile_store.create('切换验收 B', **window._profile_configuration())
                profile_A = window.profile_store.create('切换验收 A', **bookmark_A)
                window._refresh_project_profile_combo(window.current_project_profile.id)
                select_profile(profile_A)
                check('selecting profile A applies its model',window._run_settings_snapshot()['models']['group_model']=='model-A')
                task('selected_profile_A')
                select_profile(profile_B)
                check('selecting profile B restores its model',window._run_settings_snapshot()['models']['group_model']=='model-B')
                task('selected_profile_B')
                result['final_state'] = observe('before_restart')
            result['passed'] = all(c['passed'] for c in result['checks'])
        except BaseException:
            result['errors'].append(traceback.format_exc())
        finally:
            for model in ('model-A', 'model-B', 'model-C', 'model-C-new'):
                control(model, False)
            (output / (phase + '-result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
            QTimer.singleShot(100, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / (phase + '-result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(300, run)
