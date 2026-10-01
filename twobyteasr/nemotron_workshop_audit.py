"""Explicitly package and dispatch as nemotron-workshop; never arbitrary runpy.

This hook does not run standalone. It drives real Qt controls/installer/worker.
Only the installer child's filesystem boundary is explicitly restored to the
authorized stable runtime. GUI QSettings and all normal user data stay isolated.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def start(window, out):
    from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QDialogButtonBox, QLineEdit
    from twobyteasr.build_identity import load_build_identity
    from twobyteasr.studio_acceptance_audit import require
    from twobyteasr.runtime_registry import resolve_runtime_python

    config = json.loads((out / 'nemotron-audit-config.json').read_text('utf8'))
    stage = os.environ.get('TWOBYTEASR_NEMOTRON_AUDIT_PHASE', 'install')
    require(stage in {'install', 'reopen'}, 'explicit audit phase required')
    require(config.get('allow_stable_runtime_validation') is True, 'explicit stable runtime validation opt-in required')
    result = dict(build=vars(load_build_identity()), phase=stage, executable=sys.executable,
                  checks=[], started_at=time.time(), completed=False, paid_calls=0,
                  boundary='GUI settings isolated; only Nemotron installer child uses authorized stable runtime',
                  execution='Real workshop action, sample picker, downloader button and independent worker; contract-derived target')
    dialog = None
    old_picker = QFileDialog.getOpenFileName
    managed_base = Path(config['managed_data_base']).resolve()
    runtime_python = Path(config['runtime_python']).resolve()
    models = Path(config['models']).resolve()
    sample = Path(config['sample']).resolve()
    stable_registry = managed_base / '2ByteASR/runtimes/registry.json'
    registry_before = json.loads(stable_registry.read_text('utf8'))
    fresh_target = stage == 'install' and not config['target_existed_at_prepare']
    result['fresh_target'] = fresh_target
    result['runtime_id'] = config['runtime_id']
    result['registry_before'] = registry_before.get('runtimes', {}).get('nemotron')
    result['registry_publication_observations'] = []

    def save():
        (out / f'{stage}-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def check(name, value):
        result['checks'].append(dict(name=name, passed=bool(value)))
        save()
        require(value, name)

    def wait_until(predicate, seconds, message):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(100)
        check(message, predicate())

    def run():
        nonlocal dialog
        try:
            check('final frozen EXE identity', bool(getattr(sys, 'frozen', False)) and sha(sys.executable) == config['exe_sha256'])
            check('QSettings remains in audit root', Path(QSettings('2ByteASR', '2ByteASR').fileName()).resolve().is_relative_to(out.resolve()))
            check('GUI data root remains isolated', Path(os.environ['2BYTEASR_USER_DATA_ROOT']).resolve().is_relative_to(out.resolve()))
            check('candidate contract identity', sha(Path(sys.executable).parent/'dependencies.lock.json') == config['contract_sha256'])
            check('stable runtime is outside tmp', runtime_python.is_relative_to(managed_base/'2ByteASR/runtimes/nemotron') and not runtime_python.is_relative_to(out.resolve()) and 'tmp' not in [p.lower() for p in runtime_python.parts])
            if fresh_target:
                check('first pass target interpreter absent', not runtime_python.is_file())
                check('old registration retained before new install', registry_before['runtimes']['nemotron'] == config['registered_before_prepare'])
            else:
                check('existing target interpreter present', runtime_python.is_file())
            for protected_path, expected_hash in config['protected_old_files'].items():
                check('old environment artifact intact before: '+protected_path, Path(protected_path).is_file() and sha(protected_path) == expected_hash)
            check('speech sample identity', sample.is_file() and sha(sample) == config['sample_sha256'])
            window._open_model_workshop()
            page = window.workshop_page
            tab = next(button for button in page.tab_group.buttons() if button.property('role') == 'speaker')
            QTest.mouseClick(tab, Qt.LeftButton)
            QTest.mouseClick(page._cards['nemotron'], Qt.LeftButton)
            QTest.qWait(200)
            check('Nemotron detail selected', page.detail_model_key == 'nemotron')
            model = page._cards['nemotron'].model
            wait_until(lambda: page._model_state(model) != 'checking', 90, 'runtime discovery completed')
            result['state_before'] = page._model_state(model)
            discovered = resolve_runtime_python('nemotron')
            if fresh_target:
                check('absent target does not discover old stable registration', not discovered)
                check('ordinary missing environment action available', result['state_before'] in {'runtime_missing', 'missing'})
            else:
                check('resolved intended stable interpreter', bool(discovered) and Path(discovered).resolve() == runtime_python)
                check('reopened target is already ready', result['state_before'] in {'installed', 'selected'})
            window.grab().save(str(out / f'{stage}-workshop-before.png'))
            result['workshop_action'] = 'detail_action' if fresh_target else 'detail_repair'
            QTest.mouseClick(page.detail_action if fresh_target else page.detail_repair, Qt.LeftButton)
            QTest.qWait(200)
            dialogs = [item for item in page._download_dialogs if item.download_keys == ('nemotron',)]
            check('ordinary workshop action opened single-model downloader', len(dialogs) == 1)
            dialog = dialogs[0]
            check('sample selection control exists', hasattr(dialog, 'sample_button'))

            def controlled_picker(*args, **kwargs):
                kwargs['options'] = kwargs.get('options', QFileDialog.Option(0)) | QFileDialog.DontUseNativeDialog
                return old_picker(*args, **kwargs)

            QFileDialog.getOpenFileName = controlled_picker
            picker_deadline = time.monotonic() + 12

            def choose_sample():
                picker = QApplication.activeModalWidget()
                if not isinstance(picker, QFileDialog):
                    if time.monotonic() < picker_deadline:
                        QTimer.singleShot(100, choose_sample)
                    return
                field=picker.findChild(QLineEdit,'fileNameEdit')
                if field is None:
                    result['picker_error']='File name editor unavailable';picker.reject();return
                clipboard=QApplication.clipboard();previous=clipboard.text()
                clipboard.setText(str(sample))
                QTest.mouseClick(field,Qt.LeftButton);QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier);clipboard.setText(previous)
                picker.grab().save(str(out / f'{stage}-sample-picker.png'))
                box = picker.findChild(QDialogButtonBox)
                if box is None or box.button(QDialogButtonBox.Open) is None:
                    result['picker_error'] = 'Real QFileDialog Open button unavailable'
                    picker.reject()
                    return
                QTest.mouseClick(box.button(QDialogButtonBox.Open), Qt.LeftButton)

            def cancel_stalled_picker():
                picker = QApplication.activeModalWidget()
                if isinstance(picker, QFileDialog):
                    result['picker_error'] = 'Sample picker exceeded 15 seconds'
                    picker.reject()

            QTimer.singleShot(150, choose_sample)
            QTimer.singleShot(15000, cancel_stalled_picker)
            QTest.mouseClick(dialog.sample_button, Qt.LeftButton)
            QFileDialog.getOpenFileName = old_picker
            check('sample chosen through real QFileDialog', Path(dialog.nemotron_sample).resolve() == sample)
            dialog.source_combo.setCurrentIndex(dialog.source_combo.findData('HF_OFFICIAL'))
            original_env_setter = dialog.process.setProcessEnvironment
            original_start = dialog.process.start

            def installer_environment(environment):
                child = QProcessEnvironment(environment)
                # Scope restoration is only for this user-authorized installer.
                # Removing TEST_ROOT prevents imported twobyteasr.__init__ from
                # redirecting Python back into the temporary test runtime root.
                child.remove('TWOBYTEASR_TEST_ROOT')
                child.insert('2BYTEASR_USER_DATA_ROOT', str(managed_base))
                child.insert('2BYTEASR_MODEL_ROOT', str(models))
                windows = Path(child.value('SystemRoot') or os.environ['SystemRoot'])
                child.insert('PATH', str(windows/'System32')+';'+str(windows))
                result['installer_environment'] = {
                    'TWOBYTEASR_TEST_ROOT': child.value('TWOBYTEASR_TEST_ROOT'),
                    '2BYTEASR_USER_DATA_ROOT': child.value('2BYTEASR_USER_DATA_ROOT'),
                    '2BYTEASR_MODEL_ROOT': child.value('2BYTEASR_MODEL_ROOT'),
                    'TEMP': child.value('TEMP'),
                    'PATH': child.value('PATH'),
                    'TWOBYTEASR_NEMOTRON_SAMPLE': child.value('TWOBYTEASR_NEMOTRON_SAMPLE'),
                }
                save()
                original_env_setter(child)

            def capture_start(program, arguments):
                result['installer_command'] = [program, *arguments]
                check('installer belongs to final frozen candidate', str(Path(sys.executable).parent / 'scripts/download_models.ps1') in arguments)
                original_start(program, arguments)

            dialog.process.setProcessEnvironment = installer_environment
            dialog.process.start = capture_start
            completions = []
            dialog.completed.connect(lambda ok, message: completions.append(dict(ok=bool(ok), message=message)))
            invoked = time.time()

            def completion_with_registration_check():
                current = json.loads(stable_registry.read_text('utf8'))['runtimes']['nemotron']
                previous = result['registry_publication_observations'][-1]['entry'] if result['registry_publication_observations'] else None
                if current != previous:
                    if current != registry_before['runtimes']['nemotron']:
                        require(Path(current['python_executable']).resolve() == runtime_python,
                                'registry may publish only the intended new interpreter')
                        receipt_path = Path(current.get('readiness', ''))
                        require(receipt_path.is_file() and receipt_path.resolve().is_relative_to(runtime_python.parent.parent),
                                'new registration requires its immutable validation receipt')
                        published = json.loads(receipt_path.read_text('utf8'))
                        require(published.get('inference_verified') and published.get('sample_sha256') == config['sample_sha256']
                                and published.get('started_at', 0) >= invoked-2,
                                'old registry entry must persist until new real sample validation succeeds')
                    result['registry_publication_observations'].append(dict(observed_at=time.time(), entry=current))
                    save()
                return bool(completions)

            dialog.grab().save(str(out / f'{stage}-download-before.png'))
            completion_with_registration_check()
            QTest.mouseClick(dialog.start_button, Qt.LeftButton)
            wait_until(completion_with_registration_check, 1800, 'ordinary download workflow completed')
            check('installer returned success', completions[-1]['ok'])
            result['completion'] = completions[-1]
            dialog.grab().save(str(out / f'{stage}-download-complete.png'))
            check('installer process exited', dialog.process.state() == QProcess.NotRunning)
            after = json.loads(stable_registry.read_text('utf8'))
            before_others = {k: v for k, v in registry_before['runtimes'].items() if k != 'nemotron'}
            after_others = {k: v for k, v in after['runtimes'].items() if k != 'nemotron'}
            check('other registered runtimes unchanged', before_others == after_others)
            entry = after['runtimes']['nemotron']
            check('registration remains intended runtime', Path(entry['python_executable']).resolve() == runtime_python)
            for protected_path, expected_hash in config['protected_old_files'].items():
                check('old environment artifact preserved after: '+protected_path, Path(protected_path).is_file() and sha(protected_path) == expected_hash)
            readiness = json.loads((runtime_python.parent.parent / 'nemotron-readiness.json').read_text('utf8'))
            result['readiness'] = readiness
            check('new sample inference from this invocation', readiness.get('inference_verified') and readiness.get('started_at', 0) >= invoked - 2 and readiness.get('sample_sha256') == config['sample_sha256'])
            check('actual expected device', readiness.get('device') == config['expected_device'])
            check('no model root divergence', Path(readiness['model_path']).resolve() == models / 'Nemotron-3-Diarization')
            worker = Path(sys.executable).parent / 'workers/nemotron_worker.py'
            check('frozen independent worker present', worker.is_file())
            result['frozen_worker_sha256'] = sha(worker)
            page.refresh()
            wait_until(lambda: page._model_state(model) in {'installed', 'selected'}, 90, 'workshop offers verified runtime')
            result['state_after'] = page._model_state(model)
            window.grab().save(str(out / f'{stage}-workshop-complete.png'))
            check('GUI isolation remains intact after installation', Path(os.environ['2BYTEASR_USER_DATA_ROOT']).resolve().is_relative_to(out.resolve()))
            result['completed'] = True
            window.result_exit_code = 0
        except Exception:
            result['error'] = traceback.format_exc()
            window.result_exit_code = 1
        finally:
            QFileDialog.getOpenFileName = old_picker
            if dialog is not None:
                (out / f'{stage}-installer.log').write_text(dialog.log.toPlainText(), 'utf8')
                if dialog.process.state() != QProcess.NotRunning:
                    # Cancel only the installer owned by this audit after failure.
                    QTest.mouseClick(dialog.pause_button, Qt.LeftButton)
                    QTest.qWait(1500)
            result['finished_at'] = time.time()
            save()
            studio = getattr(window, 'studio_page', None)
            if studio is not None and hasattr(studio, 'undo_stack'):
                studio.undo_stack.setClean()
            window.close()

    QTimer.singleShot(3500, run)


if __name__ == '__main__':
    raise SystemExit('This is an explicit frozen acceptance module; do not run standalone.')
