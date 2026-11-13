"""Isolated Windows MainWindow audit of selected Chinese range refinement."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(output, window=None):
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from unittest.mock import patch
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    import subtitle_core as core
    from twobyteasr.app.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
    from twobyteasr.system.processes import run_hidden_subprocess
    EndpointEditor._queue_model_discovery = lambda *a, **k: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **k: None
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    checks, requests = [], []

    def check(name, passed):
        checks.append(dict(name=name, passed=bool(passed)))
        if not passed:
            raise AssertionError(name)

    def settle(seconds=.1):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def wait(predicate):
        deadline = time.monotonic()+60
        while not predicate() and time.monotonic() < deadline:
            settle()
        check('bounded background completion', predicate())

    media = output/'fixture.mp4'
    run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin'/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')), '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=0x293540:s=1280x720:r=25:d=12',
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '12',
        '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', str(media)], check=True, purpose='acceptance.fixture')
    cues = [StudioCue('outside', 0, 800, '范围外'),
            StudioCue('a', 1000, 2000, '他进我们罗隐的'), StudioCue('b', 2180, 3000, '斩杀线了'),
            StudioCue('c', 4500, 5500, '我们先走到前面'), StudioCue('d', 5850, 7000, '然后看一下情况'),
            StudioCue('blue', 6000, 6600, '等一下', speaker_id='S01')]
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=12000), cues=cues)
    project.generation_metadata.update(language={'code': 'zh'}, translations={'a': 'He is within', 'b': 'our kill range'})
    fixture = output/'fixture.2byteproj'
    save_project(project, fixture)
    window = window or MainWindow([], core, object(), None)
    window.resize(1440, 920)
    window.show()

    model_action = 'keep'
    def complete(messages, **kwargs):
        requests.append(messages)
        payload = json.loads(messages[-1]['content'])
        return json.dumps({'results': [dict(cue_id=row['cue_id'], action=model_action,
            split_after_chars=[]) for row in payload['cues']]})

    try:
        with patch('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete)), \
             patch('twobyteasr.providers.llm_config.text_ai_key_missing', lambda *a: False):
            window.open_studio_project(str(fixture))
            wait(lambda: window.built_page('studio') is not None and window.built_page('studio').project is not None)
            page = window.built_page('studio')
            wait(lambda: window.__dict__.get('_studio_loading_session') is None or not window._studio_loading_session.active)
            settle(1.)
            before = copy.deepcopy(page.project.cues)
            check('before screenshot', window.grab().save(str(output/'01-before.png')))
            page.run_sentence_refine(whole_project=False, retry_ids=['a', 'b'])
            wait(lambda: page._refine_task.ended is not None)
            check('qualified AI keep preserves all original boundaries', page.project.cues == before)
            # In the current protocol keep retains source boundaries; an empty
            # split list explicitly requests one complete range with no cut.
            model_action = 'split'
            page.run_sentence_refine(whole_project=False, retry_ids=['a', 'b'])
            wait(lambda: page._refine_task.ended is not None)
            check('selected eleven-character expression merges', page.project.cues[1].text == '他进我们罗隐的斩杀线了')
            check('unselected cues stay identical', page.project.cues[0] == before[0] and page.project.cues[2:] == before[3:])
            check('translation retained', 'our kill range' in next(iter(page.project.generation_metadata['translations'].values())))
            page.undo_stack.undo()
            check('undo restores every original cue', page.project.cues == before)
            page.undo_stack.redo()
            check('redo merges once', len(page.project.cues) == 5)
            page.run_sentence_refine(whole_project=False, retry_ids=['c', 'd'])
            wait(lambda: page._refine_task.ended is not None)
            check('fourteen characters survive short pause', any(c.text == '我们先走到前面然后看一下情况' for c in page.project.cues))
            check('overlapping blue speaker retains exact interval', next(c for c in page.project.cues if c.id == 'blue') == before[-1])
            check('bounded requests', len(requests) == 3)
            page.select_cue(page.project.cues[1].id)
            settle(.5)
            check('after screenshot', window.grab().save(str(output/'02-after.png')))
            save_project(page.project, output/'result.2byteproj')
            reopened = load_project(output/'result.2byteproj')
            check('saved project reopens exactly', reopened.cues == page.project.cues)
            exported = export_language_layers(reopened, output/'export', 'complete', layers=('original',))
            srt = next(artifact.path for artifact in exported.artifacts if artifact.format == 'srt' and not artifact.speaker_id)
            parsed, errors = parse_srt(srt.read_text('utf-8-sig'))
            check('SRT framing and time ranges are valid', not errors)
            check('SRT carries both complete expressions', {c.text for c in parsed} >= {'他进我们罗隐的斩杀线了', '我们先走到前面然后看一下情况'})
            (output/'requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
            page.undo_stack.setClean()
    except Exception:
        import traceback
        (output/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        window.grab().save(str(output/'failure.png'))
        raise
    finally:
        (output/'result.json').write_text(json.dumps(dict(checks=checks, external_calls=0,
            entry='MainWindow.open_studio_project → QThread → RefineCuesCommand'), ensure_ascii=False, indent=2), encoding='utf-8')
        window.close()
        settle(2.)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        parser.error('output must stay inside repository tmp')
    if args.child:
        try:
            code = child(output)
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess(kernel.GetCurrentProcess(), code)
        return code
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, QT_QPA_PLATFORM='windows', TWOBYTEASR_TEST_ROOT=str(output/'profile'),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if args.exe or args.normal_entry:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
        startup = output/'startup.2byteproj'
        save_project(SubtitleProject(media=StudioMedia(path='')), startup)
        env.update(LOCALAPPDATA=str(output/'profile/local'), APPDATA=str(output/'profile/roaming'),
            TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='chinese-complete-expression',
            TWOBYTEASR_STARTUP_PROJECT=str(startup), TWOBYTEASR_INVOKER_CWD=str(ROOT))
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
        from audit_launch_bridge import run_audit_on_desktop
        code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=output,
                                    timeout=180, receipt=output/'result.json')
        (output/'process-exit.json').write_text(json.dumps(dict(exit_code=code)), encoding='utf-8')
        return code
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--child', '--output', str(output)],
                          cwd=ROOT, env=env, output=output/'process', timeout=180)
    (output/'process-exit.json').write_text(json.dumps(dict(exit_code=code)), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
