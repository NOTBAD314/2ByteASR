"""MainWindow task-panel audit with offline providers and isolated synthetic data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(output, window=None):
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output / 'profile')
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from unittest.mock import patch
    from types import SimpleNamespace
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    from twobyteasr.studio.studio_task_progress import SubtitleTask
    from twobyteasr.studio.studio_reasr import LocalReASRResult
    EndpointEditor._queue_model_discovery = lambda *args, **kwargs: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *args, **kwargs: None
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    apply_theme('grape', app)
    checks = []
    calls = []

    def check(name, passed):
        checks.append(dict(name=name, passed=bool(passed)))
        if not passed:
            raise AssertionError(name)

    def settle(seconds=.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def wait(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            settle(.02)
        check('bounded wait', predicate())

    def complete(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        calls.append(payload)
        time.sleep(.35)
        rows = []
        for row in payload['cues']:
            if row['cue_id'] == 'a':
                rows.append(dict(cue_id='a', action='split', split_after_chars=[5]))
            elif row['cue_id'] == 'b':
                if mode[0] == 'failure':
                    continue
                rows.append(dict(cue_id='b', action='keep'))
            else:
                rows.append(dict(cue_id=row['cue_id'], action='keep'))
        return json.dumps({'results': rows}, ensure_ascii=False).replace(']}', '],}')

    mode = ['failure']
    fixture = output / 'fixture.2byteproj'
    media = output / 'fixture.mp4'
    from twobyteasr.system.processes import run_hidden_subprocess
    ffmpeg = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
    run_hidden_subprocess([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=0x293540:s=640x360:r=12:d=12',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=12', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(media)], check=True, purpose='subtitle task audit fixture')
    p = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=12000), cues=[
        StudioCue('a', 0, 4000, '今天天气很好我们继续出发', evidence_refs=['e']),
        StudioCue('b', 5000, 8000, '这场比赛虽然非常精彩')],
        asr_evidence={'e': {'words': [dict(text='今天天气很好', start_ms=0, end_ms=1800),
                                    dict(text='我们继续出发', start_ms=2100, end_ms=4000)]}})
    p.generation_metadata['language'] = {'code': 'zh'}
    save_project(p, fixture)
    win = window or MainWindow([], legacy, object(), None)
    win.resize(1440, 920)
    win.show()
    try:
        if window is not None:
            from twobyteasr.acceptance.ai_tasks_home_b_audit import check_home
            check_home(win, output, check, settle)
        with patch('twobyteasr.providers.ai_providers.provider_for_stage',
                   lambda *args, **kwargs: SimpleNamespace(complete=complete)), \
             patch('twobyteasr.providers.llm_config.text_ai_key_missing', lambda *args: False):
            win.open_studio_project(str(fixture))
            wait(lambda: win.built_page('studio') is not None
                 and win.built_page('studio').project is not None
                 and len(win.built_page('studio').project.cues) == 2
                 and win.built_page('studio').isVisible(), 30)
            page = win.built_page('studio')
            wait(lambda: win.__dict__.get('_studio_loading_session') is None
                 or (not win._studio_loading_session.active and not win._studio_loading_session.view.isVisible()), 60)
            settle(1.)
            wait(lambda: page.subtitle_tasks_button.isEnabled() and page.subtitle_tasks_button.isVisible(), 30)
            page.select_cue('a')
            selected = page.selected_cue_id
            playhead = page.timeline.playhead_ms
            menu = page.cue_ai_button.menu()
            menu.aboutToShow.emit()
            next(action for action in menu.actions() if action.text() == 'AI 断句').trigger()
            task = page._refine_task
            QTest.mouseClick(page.subtitle_tasks_button, Qt.MouseButton.LeftButton)
            panel = page._subtitle_task_panel()
            settle(.15)
            (output/'panel-debug.json').write_text(json.dumps(dict(visible=panel.isVisible(),task_ended=task.ended,button_visible=page.subtitle_tasks_button.isVisible(),button_enabled=page.subtitle_tasks_button.isEnabled(),page_visible=page.isVisible(),rows=task.rows),ensure_ascii=False,default=str),encoding='utf-8')
            check('panel shows during running task', panel.isVisible() and task.ended is None)
            check('progress keeps selection while running', page.selected_cue_id == selected)
            check('running screenshot', panel.grab().save(str(output / '01-running.png')))
            panel.hide()
            wait(lambda: task.ended is not None)
            QTest.mouseClick(page.subtitle_tasks_button, Qt.MouseButton.LeftButton)
            settle(.3)
            panel.refresh()
            check('panel reopens with complete result', panel.isVisible() and panel.table.model().rowCount() == 2)
            check('partial failure and completed source counts', task.counts()['applied'] == 1 and task.counts()['failed'] == 1
                  and task.counts()['total'] == 2)
            check('shared cause visible', '遗漏' in panel.counts_label.text())
            check('writeback keeps playback position', page.timeline.playhead_ms == playhead)
            panel.only_failures.setChecked(True)
            row = panel._row_indexes['b']
            panel.table.selectRow(row)
            settle()
            check('full failure details', '原始响应' in panel.details.toPlainText() and '遗漏' in panel.details.toPlainText())
            check('partial screenshot', panel.grab().save(str(output / '02-partial-failure.png')))
            QTest.mouseClick(panel.locate_button, Qt.MouseButton.LeftButton)
            settle(.2)
            check('explicit locate selects failed cue and time', page.selected_cue_id == 'b'
                  and page.timeline.playhead_ms == 5000)
            mode[0] = 'success'
            QTest.mouseClick(panel.retry_button, Qt.MouseButton.LeftButton)
            retry = page._refine_task
            wait(lambda: retry.ended is not None)
            check('targeted retry owns only failed source', retry.cue_ids == ('b',) and retry.counts()['unchanged'] == 1)
            check('only b sent by targeted retry', [row['cue_id'] for row in calls[-1]['cues']] == ['b'])
            panel.only_failures.setChecked(False)
            settle(.25)
            panel.refresh()
            check('retry screenshot', panel.grab().save(str(output / '03-targeted-retry.png')))
            panel.hide()
            page.project.cues[-1].text += '！'
            page.select_cue('b')
            mode[0] = 'failure'
            menu.aboutToShow.emit()
            next(action for action in menu.actions() if action.text() == 'AI 断句（选中范围）').trigger()
            selected_task = page._refine_task
            wait(lambda: selected_task.ended is not None)
            check('selected menu scope is fixed', selected_task.cue_ids == ('b',) and selected_task.counts()['failed'] == 1)
            mode[0] = 'success'
            menu.aboutToShow.emit()
            next(action for action in menu.actions() if action.text() == '重试断句失败的范围').trigger()
            failed_retry = page._refine_task
            wait(lambda: failed_retry.ended is not None)
            check('failed menu retries only original failed input', failed_retry.cue_ids == ('b',)
                  and failed_retry.counts()['unchanged'] == 1)
            # The existing single-cue entry shares task events and cancellation.
            def transcribe(project, cue_id, settings, ffmpeg, *, on_progress, cancel_check):
                on_progress('准备局部音频')
                time.sleep(.15)
                on_progress('识别中，等待模型返回（含按需加载）')
                time.sleep(.25)
                return LocalReASRResult(cue_id, project.cues[0].text, '', '测试建议', (), '测试建议', 'fixture')
            panel.hide()
            page.select_cue(page.project.cues[0].id)
            with patch('twobyteasr.studio.studio_media_flow.run_local_reasr', transcribe):
                page._reasr_current()
                single = page._reasr_task
                page.show_subtitle_tasks()
                wait(lambda: single.ended is not None)
            settle(.25)
            panel.refresh()
            check('recognition waits for explicit adoption', single.counts()['suggestion'] == 1 and single.counts()['applied'] == 0)
            check('recognition screenshot', panel.grab().save(str(output / '04-recognition-suggestion.png')))
            # Fixed long input, out-of-order completions and a throttled live table.
            large = SubtitleTask('7000 条进度刷新验收', tuple(f'c{i}' for i in range(7000)))
            for i in range(7000):
                large.update(dict(range_id=f'c{i}', cue_ids=[f'c{i}'], start_ms=i*1000, end_ms=i*1000+900,
                                  status='pending', phase='等待处理'))
            began = time.perf_counter()
            panel.add_task(large)
            panel.refresh()
            initial_ms = (time.perf_counter()-began)*1000
            timings = []
            for i in range(20):
                key = f'c{6999-i}'
                large.update(dict(range_id=key, cue_ids=[key], status='unchanged'))
                began = time.perf_counter()
                panel.refresh()
                timings.append((time.perf_counter()-began)*1000)
            check('long progress fixed denominator', large.counts()['processed'] == 20 and large.counts()['total'] == 7000)
            check('incremental refresh under 100ms', max(timings) < 100)
            check('long table screenshot', panel.grab().save(str(output / '05-long-progress.png')))
            (output / 'performance.json').write_text(json.dumps(dict(initial_table_ms=initial_ms,
                incremental_ms=timings, external_calls=0), indent=2), encoding='utf-8')
            panel.hide()
            check('main window screenshot', win.grab().save(str(output / '06-main-window-entry.png')))
            page.undo_stack.setClean()
            save_project(page.project, output / 'result.2byteproj')
    except Exception:
        import traceback
        (output / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        win.grab().save(str(output / 'failure.png'))
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(dict(checks=checks,
            passed=sum(item['passed'] for item in checks), failed=sum(not item['passed'] for item in checks),
            external_calls=0, entry='MainWindow.open_studio_project'), ensure_ascii=False, indent=2), encoding='utf-8')
        win.close()
        settle(2.)
        (output / 'cleanup.json').write_text(json.dumps(dict(
            studio_cleanup_complete=bool(getattr(win, '_studio_close_cleanup_done', False)),
            close_finalizing=bool(getattr(win, '_studio_close_finalizing', False)))), encoding='utf-8')
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp'):
        parser.error('output must stay inside repository tmp')
    if args.child:
        code = child(output)
        cleanup = json.loads((output / 'cleanup.json').read_text(encoding='utf-8'))
        if not cleanup.get('studio_cleanup_complete') or not cleanup.get('close_finalizing'):
            raise RuntimeError('MainWindow cleanup did not finish')
        # Same post-cleanup shutdown as quick_start.py. The Windows media
        # libraries are deliberately retired before interpreter/DLL teardown.
        import ctypes
        from ctypes import wintypes
        sys.stdout.flush()
        sys.stderr.flush()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.TerminateProcess(kernel.GetCurrentProcess(), code)
        os._exit(code)
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='windows', TWOBYTEASR_TEST_ROOT=str(output / 'profile'),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if args.exe or args.normal_entry:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
        startup = output/'startup.2byteproj'
        save_project(SubtitleProject(media=StudioMedia(path='')), startup)
        env.update(LOCALAPPDATA=str(output/'profile/local'),APPDATA=str(output/'profile/roaming'),
            TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='ai-tasks-home-b',
            TWOBYTEASR_STARTUP_PROJECT=str(startup),TWOBYTEASR_INVOKER_CWD=str(ROOT))
        command = [str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
        from audit_launch_bridge import run_audit_on_desktop
        code = run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,
            timeout=180,receipt=output/'result.json')
        (output/'process-exit.json').write_text(json.dumps({'exit_code':code}),encoding='utf-8')
        return code
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
        '--child', '--output', str(output)], cwd=ROOT, env=env, output=output / 'process', timeout=150)
    (output / 'process-exit.json').write_text(json.dumps({'exit_code': code}), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
