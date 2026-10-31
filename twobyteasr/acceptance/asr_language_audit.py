"""Headed MainWindow language controls, persistence and honest MOSI capability.

Uses a private Windows desktop and an isolated profile, without any paid API.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time


def child(output, reopen):
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication, QScrollArea
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.providers.mosi_asr import LANGUAGE_NOTICE
    from twobyteasr.local_models.model_registry import ModelRegistry
    ModelRegistry.installed_keys = lambda self: set()
    if not reopen:
        legacy.RUNTIME_SETTINGS['models'].update(primary_asr_backend='api', qwen_asr_backend='off',
            firered_asr_backend='off', qwen_asr_api_provider='mosi_moss_pro',
            qwen_asr_api_protocol='mosi_transcriptions', qwen_asr_api_model='moss-transcribe-diarize-pro',
            qwen_asr_api_url='https://api.mosi.cn/v1')
        legacy.RUNTIME_SETTINGS['subtitle_language'] = {'recognition_language': 'it'}
    app = QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    apply_theme('warm', app)
    win = MainWindow([], legacy, object(), None)
    win.resize(1560, 1060)
    win.show()
    def settle(seconds=.2):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents()
            time.sleep(.005)
    settle(.5)
    checks = {}
    if not reopen:
        checks['initial_italian_data'] = win.recognition_language.currentData() == 'it'
        win.recognition_language.setFocus()
        QTest.keyClick(win.recognition_language, Qt.Key.Key_Home)
        for _ in range(4):
            QTest.keyClick(win.recognition_language, Qt.Key.Key_Down)
        settle()
    checks['english_item_data'] = win.recognition_language.currentData() == 'en'
    checks['english_task_option'] = win._subtitle_language_options()['recognition_language'] == 'en'
    checks['capability_visible'] = win.subtitle_language_hint.isVisible() and LANGUAGE_NOTICE in win.subtitle_language_hint.text()
    checks['persisted_english'] = legacy.RUNTIME_SETTINGS['subtitle_language']['recognition_language'] == 'en'
    parent = win.subtitle_language_hint.parentWidget()
    while parent is not None and not isinstance(parent, QScrollArea):
        parent = parent.parentWidget()
    if parent is not None:
        parent.ensureWidgetVisible(win.subtitle_language_hint, 20, 20)
        settle()
        top_left = win.subtitle_language_hint.mapTo(parent.viewport(), win.subtitle_language_hint.rect().topLeft())
        checks['notice_inside_viewport'] = parent.viewport().rect().contains(
            win.subtitle_language_hint.rect().translated(top_left))
    name = 'reopen' if reopen else 'switch'
    win.grab().save(str(output/f'{name}-window.png'))
    win.subtitle_language_hint.grab().save(str(output/f'{name}-hint.png'))
    (output/f'{name}.json').write_text(json.dumps({'checks': checks,
        'hint': win.subtitle_language_hint.text(), 'options': win._subtitle_language_options()},
        ensure_ascii=False, indent=2), encoding='utf8')
    win.close()
    settle()
    assert all(checks.values()), checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--reopen', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if args.child:
        child(out, args.reopen)
        return 0
    root = Path(__file__).resolve().parents[2]
    if out.exists() or not out.is_relative_to(root/'tmp'):
        raise ValueError('Use a new output directory under this source tmp/')
    out.mkdir(parents=True)
    sys.path.insert(0, str(root/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'), QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1')
    codes = []
    for name, extra in [('switch', []), ('reopen', ['--reopen'])]:
        codes.append(run_on_desktop([sys.executable, '-m', 'twobyteasr.acceptance.asr_language_audit',
            '--output', str(out), '--child', *extra], cwd=root, env=env, output=out/name, timeout=90))
        if codes[-1]:
            break
    (out/'exit-codes.json').write_text(json.dumps(codes), encoding='utf8')
    print(json.dumps({'exit_codes': codes, 'output': str(out)}))
    return 0 if codes == [0, 0] else 1


if __name__ == '__main__':
    raise SystemExit(main())
