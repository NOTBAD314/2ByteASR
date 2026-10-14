"""Real recognition run of the self-made demo clip, captured from the real window.

Outer: prepares a fresh profile under tmp (settings, runtime registry copy),
then launches the inner part on a private Windows desktop.
Inner: normal MainWindow; imports the clip, clicks 开始生成字幕, captures the
progress page while the local MOSS + FireRed + Qwen run executes, then the
completion page. Every pipeline event and console line is recorded so the
progress surface can be re-shot from the same real run without re-running.

User data, caches, reports and projects all live under the run folder. The
registered local runtimes and the repository model folder are only read.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[2]
# Work folder (media, runs, assets); keep it under the repository tmp/.
BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()


def outer(args):
    out = (BASE / 'runs' / args.name).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; choose a fresh name')
    profile = out / 'profile'
    data = profile / 'local' / '2ByteASR'
    (data / 'runtimes').mkdir(parents=True)
    for folder in ('roaming', 'temp', 'home', 'hf-cache', 'modelscope-cache', 'torch-cache'):
        (profile / folder).mkdir(parents=True, exist_ok=True)
    real_registry = Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / 'runtimes' / 'registry.json'
    registry = json.loads(real_registry.read_text('utf-8-sig'))
    registry['runtimes'] = {k: v for k, v in registry['runtimes'].items() if k in ('main', 'moss', 'firered_llm')}
    (data / 'runtimes' / 'registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=1), 'utf8')
    sys.path.insert(0, str(REPO))
    from twobyteasr.settings import DEFAULT_SETTINGS
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(primary_asr_backend='moss', speaker_source='moss', qwen_asr_backend='local',
                              firered_asr_backend='local')
    settings['switches'].update(enable_ai_polish=False, use_ai_grouping=False, unified_glm_processing=False,
                                output_speaker_tracks=True)
    settings['ui'].update(language=args.lang)
    (data / '2byteasr_settings.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), 'utf8')
    media_dir = out / 'media'
    media_dir.mkdir()
    media = media_dir / args.media_name
    shutil.copy2(BASE / 'media' / 'forest-run.mp4', media)
    spec = dict(media=str(media), size=args.size, theme=args.theme, lang=args.lang, scale=args.scale,
                interval=args.interval, started=time.strftime('%Y-%m-%dT%H:%M:%S'))
    (out / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf8')
    env = {k: v for k, v in os.environ.items() if not k.endswith(('_API_KEY', '_ACCESS_TOKEN', '_AUTH_TOKEN'))}
    for key in ('TWOBYTEASR_TEST_ROOT', 'TWOBYTEASR_STARTUP_PROJECT', 'TWOBYTEASR_ACCEPTANCE_SCENARIO',
                'TWOBYTEASR_ACCEPTANCE_DIR', 'QT_SCALE_FACTOR', 'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI',
                'QT_SCALE_FACTOR_ROUNDING_POLICY'):
        env.pop(key, None)
    env.update(LOCALAPPDATA=str(profile / 'local'), APPDATA=str(profile / 'roaming'), TEMP=str(profile / 'temp'),
               TMP=str(profile / 'temp'), USERPROFILE=str(profile / 'home'), HF_HOME=str(profile / 'hf-cache'),
               MODELSCOPE_CACHE=str(profile / 'modelscope-cache'), TORCH_HOME=str(profile / 'torch-cache'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1', QT_QPA_PLATFORM='windows',
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_SHOWCASE_OUT=str(out),
               **{'2BYTEASR_USER_DATA_ROOT': str(profile / 'local'), '2BYTEASR_MODEL_ROOT': str(REPO / 'models')})
    if args.scale != 'natural':
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96',
                   QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    sys.path.insert(0, str(REPO / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--inner', str(out)]
    code = run_on_desktop(command, cwd=REPO, env=env, output=out / 'process', timeout=args.timeout)
    result_path = out / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(error='no receipt')
    result['process_exit'] = code
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(exit=code, shots=len(result.get('shots', [])), errors=result.get('errors', []),
                          project=result.get('project')), ensure_ascii=False, indent=1))
    return 0 if code == 0 else 1


def inner(out: Path):
    sys.path.insert(0, str(REPO))
    spec = json.loads((out / 'spec.json').read_text('utf8'))
    # QSettings redirect from the test boundary, then hand model/runtime
    # discovery back to the normal path (registered runtimes, repo models).
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    from twobyteasr.test_isolation import install
    install()
    os.environ.pop('TWOBYTEASR_TEST_ROOT', None)
    os.environ['2BYTEASR_MODEL_ROOT'] = str(REPO / 'models')
    os.environ['USERPROFILE'] = str(out / 'profile' / 'home')
    from twobyteasr.blank_project_audit import install_offline_guards, _capture
    install_offline_guards()
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import moss_firered_pipeline
    import subtitle_core
    from twobyteasr import ui
    from twobyteasr.theme_manager import apply_application_theme
    from twobyteasr.i18n import save_language

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('2ByteASR')
    app.setWindowIcon(ui._app_icon())
    app.setStyle('Fusion')
    save_language(spec['lang'])
    apply_application_theme(app, spec['theme'])
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {'id': 'readme-showcase', 'checks': 0})
    width, height = (int(v) for v in spec['size'].split('x'))
    window.showNormal()
    window.resize(width, height)
    window.move(0, 0)
    window.show()
    result = dict(shots=[], errors=[], spec=spec, pid=os.getpid())
    events_path = out / 'events.jsonl'
    console_path = out / 'console.jsonl'
    t0 = time.monotonic()

    def write():
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    original_event = window._handle_event

    def logged_event(event):
        try:
            from dataclasses import asdict
            row = asdict(event)
        except Exception:
            row = dict(kind=getattr(event, 'kind', ''), payload=getattr(event, 'payload', {}))
        row['_t'] = round(time.monotonic() - t0, 3)
        with events_path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        return original_event(event)

    window._handle_event = logged_event
    original_console = window._append_console_line

    def logged_console(line, *args, **kwargs):
        with console_path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(dict(t=round(time.monotonic() - t0, 3), line=str(line)), ensure_ascii=False) + '\n')
        return original_console(line, *args, **kwargs)

    window._append_console_line = logged_console

    def shot(name, widget=None):
        widget = widget or window
        QApplication.processEvents()
        target = out / 'shots' / f'{name}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _capture(widget, target)
        except Exception:
            widget.grab().save(str(target), 'PNG')
        result['shots'].append(dict(name=name, t=round(time.monotonic() - t0, 2), page=type(window.pages.currentWidget()).__name__))
        write()

    def close_modals():
        for widget in QApplication.topLevelWidgets():
            if widget is not window and widget.isVisible() and widget.isWindow():
                if type(widget).__name__ in {'QMenu'}:
                    widget.close()
                elif hasattr(widget, 'reject'):
                    widget.reject()
                elif type(widget).__name__ == 'CompletionDialog':
                    widget.close()
        host = getattr(window, '_modal_host', None)
        if host is not None and host.isVisible():
            host.hide_content()

    def steps():
        yield 2.0
        window._return_to_settings()
        yield 1.0
        shot('01-home-empty')
        window.import_media([spec['media']], replace=True)
        yield 2.0
        window.settings_scroll.verticalScrollBar().setValue(0)
        yield 0.5
        shot('02-home-media')
        result['home'] = dict(primary=window.primary_asr_backend.currentData(), start_enabled=window.start_button.isEnabled())
        write()
        QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
        started = time.monotonic()
        index = 0
        yield 0.8
        while time.monotonic() - started < 1500:
            index += 1
            shot(f'progress-{index:04d}')
            if not window._run_in_progress and time.monotonic() - started > 5:
                break
            yield float(spec['interval'])
        result['run_seconds'] = round(time.monotonic() - started, 1)
        result['block_reason'] = getattr(window, '_run_block_reason', '')
        yield 2.5
        shot('03-after-run')
        close_modals()
        yield 1.0
        window.pages.setCurrentIndex(2)
        yield 1.0
        shot('04-completion')
        result['project'] = getattr(window, '_last_studio_project', '')
        result['report'] = getattr(window, '_last_recognition_report', '')
        try:
            result['completion'] = dict(count=window.result_stat_values['count'].text(),
                                        rows=[list(r) for r in window.result_preview.rows()][:40])
        except Exception:
            result['errors'].append(dict(scene='completion', error=traceback.format_exc()[-800:]))
        write()

    class Runner(QObject):
        def __init__(self):
            super().__init__(window)
            self.gen = steps()
            self.until = 0.0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def tick(self):
            if time.monotonic() < self.until:
                return
            try:
                delay = next(self.gen)
                self.until = time.monotonic() + float(delay or 0)
            except StopIteration:
                self.timer.stop()
                result['finished'] = True
                write()
                os._exit(0)
            except Exception:
                result['errors'].append(dict(scene='runner', error=traceback.format_exc()[-1500:]))
                write()
                self.timer.stop()
                os._exit(3)

    runner = Runner()  # noqa: F841
    app.exec()
    write()
    os._exit(0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--inner':
        return inner(Path(sys.argv[2]))
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--size', default='1440x900')
    parser.add_argument('--scale', default='2')
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--lang', default='zh')
    parser.add_argument('--interval', default='1.5')
    parser.add_argument('--media-name', default='林间小径·双人实况.mp4')
    parser.add_argument('--timeout', type=int, default=1800)
    return outer(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
