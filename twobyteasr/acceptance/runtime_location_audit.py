# SPDX-License-Identifier: GPL-3.0-only
"""Packaged-build check of where runtimes live (2026-10-17, ADR 0129).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=runtime-location``. It runs
*without* ``TWOBYTEASR_TEST_ROOT``, because that root turns the program-folder
default off; app data is still the output's own ``local``/``roaming``
(``audit_directory`` checks that) and Qt preferences go to ini files in the
output (``QSettings.setDefaultFormat`` does not reach ``QSettings(org, app)``,
which would otherwise write ``HKCU\\Software\\2ByteASR``).

``TWOBYTEASR_RUNTIME_LOCATION_PHASE`` picks what to do:

  paths      record the folders this start chose and the model cards, then quit
  download   record, then the workshop-download driver (card button, 开始下载)
  move       record, 应用设置 → 存储与缓存 → 移到其他位置… to ``target`` from
             ``<output>/runtime-location.json``, record again, then quit
  recognize  record, then the home-release-flow driver (real local recognition)

Each phase writes ``<output>/runtime-location-<phase>.json``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

PHASE_ENV = 'TWOBYTEASR_RUNTIME_LOCATION_PHASE'


def isolate(output: Path) -> None:
    """Qt preferences into ``<output>/qsettings``; no background AI requests."""
    from PySide6 import QtCore
    original = QtCore.QSettings
    root = output / 'qsettings'
    root.mkdir(parents=True, exist_ok=True)

    class OwnedSettings(original):
        def __init__(self, *args, **kwargs):
            if len(args) >= 2 and isinstance(args[1], original.Format):
                path = Path(str(args[0])).resolve()
                if not path.is_relative_to(output):
                    path = root / f'explicit-{hashlib.sha256(str(path).encode()).hexdigest()[:20]}.ini'
                super().__init__(str(path), original.Format.IniFormat)
                return
            strings = [value for value in args if isinstance(value, str)]
            organization = (kwargs.get('organization') or (strings[0] if strings else '')
                            or QtCore.QCoreApplication.organizationName() or 'default')
            application = (kwargs.get('application') or (strings[1] if len(strings) > 1 else '')
                           or QtCore.QCoreApplication.applicationName() or 'default')
            label = re.sub(r'[^\w.-]', '_', f'{organization}/{application}')[:90]
            super().__init__(str(root / f'{label}.ini'), original.Format.IniFormat)
            self.setFallbacksEnabled(False)

    QtCore.QSettings = OwnedSettings
    from ..app.ui import EndpointEditor
    from ..providers.provider_service import ProviderService
    from ..studio.studio_ai_flow import StudioAIFlowMixin
    EndpointEditor._queue_model_discovery = lambda *a: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **kw: None

    def blocked(*args, **kwargs):
        raise RuntimeError('Background provider requests are not authorized in this audit')
    ProviderService.submit = blocked


def _folders(phase: str) -> dict:
    from .. import runtime_paths
    from ..system import runtime_registry
    paths = runtime_paths.get_runtime_paths()
    config = runtime_paths.user_data_root() / runtime_paths.RUNTIME_PATHS_FILENAME
    try:
        saved = json.loads(config.read_text('utf-8-sig'))
    except (OSError, ValueError) as exc:
        saved = f'{type(exc).__name__}: {exc}'
    runtime_registry.reset_runtime_registry_cache()
    try:
        main_python = runtime_registry.resolve_runtime_python('main', register=False)
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        main_python = f'{type(exc).__name__}: {exc}'
    return dict(phase=phase, time=time.strftime('%Y-%m-%d %H:%M:%S'), executable=sys.executable,
                frozen=bool(getattr(sys, 'frozen', False)), test_root=os.environ.get('TWOBYTEASR_TEST_ROOT', ''),
                install_root=str(paths.install_root), user_data_root=str(paths.user_data_root),
                runtime_root=str(paths.managed_runtime_root), runtime_root_source=paths.runtime_root_source,
                model_root=str(paths.model_root), model_root_source=paths.model_root_source,
                registry=str(runtime_registry.registry_path()), registry_entries=runtime_registry.load_registry(),
                main_python=main_python, saved=saved)


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    phase = os.environ.get(PHASE_ENV, 'paths')
    config_file = output / 'runtime-location.json'
    config = json.loads(config_file.read_text('utf-8')) if config_file.is_file() else {}
    report = dict(phase=phase, records=[], passed=None, errors=[])
    report_file = output / f'runtime-location-{phase}.json'

    def save():
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), 'utf-8')

    def record(label):
        try:
            report['records'].append(dict(label=label, **_folders(label)))
        except Exception:  # noqa: BLE001
            report['errors'].append(traceback.format_exc())
        save()

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'runtime-location-{phase}-{name}.png'))
        except Exception as exc:  # noqa: BLE001
            report['errors'].append(f'grab {name}: {exc}')

    def pump_until(predicate, seconds, label):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QApplication.processEvents()
            value = predicate()
            if value:
                return value
            time.sleep(.05)
        raise TimeoutError(label)

    def cards():
        window._open_model_workshop()
        QApplication.processEvents()
        page = window.workshop_page
        if hasattr(page, 'refresh'):
            page.refresh()
        QApplication.processEvents()
        found = {}
        for key in config.get('cards', ['sensevoice']):
            card = page._cards.get(key)
            if card is not None:
                found[key] = dict(action=card.action.text(), badge=card.state_badge.text(),
                                  action_enabled=card.action.isEnabled())
        report['cards'] = found
        grab(window, 'workshop')
        save()

    def finish(passed):
        report['passed'] = bool(passed) and not report['errors']
        save()
        QTimer.singleShot(800, QApplication.instance().quit)

    record(f'{phase}-start')
    QApplication.instance().aboutToQuit.connect(lambda: record(f'{phase}-quit'))

    if phase == 'download':
        from .workshop_download_audit import start as download
        download(window, output)
        return
    if phase == 'recognize':
        from .home_release_flow_audit import start as recognize
        recognize(window, output)
        return

    def paths_phase():
        try:
            cards()
            finish(True)
        except Exception:  # noqa: BLE001
            report['errors'].append(traceback.format_exc())
            finish(False)

    def move_phase():
        target = Path(config['target'])
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(target))
        moved = report.setdefault('move', dict(target=str(target)))

        def relocation_dialog():
            return next((w for w in QApplication.topLevelWidgets()
                         if w.objectName() == 'storageRelocationDialog' and w.isVisible()), None)

        def drive_relocation():
            try:
                dialog = pump_until(relocation_dialog, 60, 'relocation dialog')
                pump_until(lambda: dialog.plan is not None, 900, 'relocation plan')
                moved.update(plan_ok=dialog.plan.ok, plan_text=dialog.summary.text(), problems=dialog.problems.text())
                grab(dialog, '1-plan')
                if dialog.plan.ok:
                    started = time.monotonic()
                    dialog.start_button.click()
                    pump_until(lambda: dialog.result is not None, 7200, 'relocation result')
                    moved.update(seconds=round(time.monotonic() - started, 1), status=dialog.result.status,
                                 messages=dialog.result.messages, leftovers=dialog.result.leftovers,
                                 dialog_text=dialog.status.text())
                grab(dialog, '2-result')
                save()
                dialog.cancel_button.click()
            except Exception:  # noqa: BLE001
                report['errors'].append(traceback.format_exc())
                dialog = relocation_dialog()
                if dialog is not None:
                    dialog.done(0)

        def drive_settings():
            try:
                from ..app.application_settings_ui import ApplicationSettingsDialog
                settings = pump_until(lambda: next((w for w in QApplication.topLevelWidgets()
                                                    if isinstance(w, ApplicationSettingsDialog) and w.isVisible()),
                                                   None), 30, 'settings dialog')
                panel = settings.storage_panel
                pump_until(lambda: panel.isVisible(), 10, 'storage page')
                moved['settings_model_root_before'] = settings.model_root_edit.text()
                grab(settings, '0-storage-before')
                QTimer.singleShot(200, drive_relocation)
                panel.move_button.click()  # modal; drive_relocation runs inside its loop
                QApplication.processEvents()
                moved['settings_model_root_after'] = settings.model_root_edit.text()
                grab(settings, '3-storage-after')
                save()
                settings.reject()
            except Exception:  # noqa: BLE001
                report['errors'].append(traceback.format_exc())
                for widget in QApplication.topLevelWidgets():
                    if widget.isVisible() and hasattr(widget, 'storage_panel'):
                        widget.reject()

        try:
            QTimer.singleShot(300, drive_settings)
            window._open_application_settings(initial_section='存储与缓存')  # modal
            from .. import runtime_paths
            runtime_paths.reset_runtime_paths()
            record('move-after')
            finish(moved.get('status') == 'moved')
        except Exception:  # noqa: BLE001
            report['errors'].append(traceback.format_exc())
            finish(False)

    QTimer.singleShot(3000, move_phase if phase == 'move' else paths_phase)
