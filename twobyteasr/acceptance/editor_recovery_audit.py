"""Crash and recovery through the ordinary application's actual dialogs."""
from .studio_acceptance_audit import require
import ctypes, json, os, sys, time, traceback, zipfile
from pathlib import Path

def run(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QPushButton, QFileDialog, QDialog
    from PySide6.QtTest import QTest
    from ..projects.studio_project import load_project
    from ..projects.editor_recovery import candidates
    from ..diagnostics import editor_diagnostics as diagnostics
    from ..diagnostics.diagnostics_report import open_diagnostics_dialog
    from .blank_project_audit import _capture
    phase = os.environ['TWOBYTEASR_RECOVERY_PHASE']
    fixture = Path(os.environ['TWOBYTEASR_RECOVERY_FIXTURE'])
    expected = dict(first='第一次提交、已自动保存的中文', committed='已提交但未正式保存的中文',
                    draft='尚未确认的草稿 日本語\n第二行')
    page = window.studio_page
    result = dict(passed=False, phase=phase, pid=os.getpid(), frozen=bool(getattr(sys, 'frozen', False)), decisions=[], checks={})

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError('recovery acceptance')
            QTest.qWait(25)
    timer = QTimer(window)
    timer.setInterval(100)

    def dialogs():
        for dialog in QApplication.topLevelWidgets():
            if not isinstance(dialog, QDialog) or not dialog.isVisible():
                continue
            title = dialog.windowTitle()
            wanted = None
            if '发现未保存的自动恢复版本' in title:
                wanted = '恢复自动保存'
            if '发现未确认的编辑草稿' in title:
                wanted = '恢复到编辑框'
            if wanted:
                for button in dialog.findChildren(QPushButton):
                    if button.text() == wanted:
                        _capture(dialog, output / f"dialog-{len(result['decisions'])}.png")
                        result['decisions'].append(wanted)
                        button.click()
                        return
    if phase == 'restore':
        timer.timeout.connect(dialogs)
        timer.start()
    try:
        window.resize(1440, 900)
        window.show()
        window.open_studio_project(fixture, mode='edit', source='recovery_acceptance')
        wait(lambda : page.project is not None and page._readiness.ready)
        if phase in ('terminate', 'native'):
            # 2026-10-22: the first autosave writes the checkpoint, the next
            # one only an overlay; recovery must bring back the overlay's edit.
            page.cue_controller.set_text('c0', expected['first'])
            wait(lambda : getattr(page, '_draft_autosave_base', None) is not None
                 and (not page._autosave_worker_running), 120)
            checkpoint = Path(page._draft_autosave_base[1])
            overlay = checkpoint.with_name(checkpoint.name + '.overlay')
            checkpoint_bytes = checkpoint.read_bytes()
            page.cue_controller.set_text('c0', expected['committed'])
            wait(lambda : overlay.is_file() and (not page._autosave_worker_running), 120)
            require(checkpoint.read_bytes() == checkpoint_bytes, 'second autosave rewrote the checkpoint')
            result['checks'].update(checkpoint_then_overlay=True)
            page.select_cue('c1')
            page._begin_canvas_inline_edit()
            page.subtitle_edit_input.setPlainText(expected['draft'])
            wait(lambda : bool(candidates(page.project.project_id)) and (not page._autosave_worker_running))
            rows = candidates(page.project.project_id)
            row = next((r for r in rows if r['text'] == expected['draft']))
            saved = load_project(row['autosave'])
            require(saved.cues[0].text == expected['committed'], 'acceptance requirement failed')
            require(saved.cues[1].text != '尚未确认的草稿 日本語\n第二行', 'acceptance requirement failed')
            require(load_project(fixture).cues[0].text != expected['committed'], 'acceptance requirement failed')
            result['checks'].update(committed_autosave=True, draft_separate=True, official_untouched=True)
            result['passed'] = True
            save()
            diagnostics.record('ACCEPTANCE_CONTROLLED_EXIT', mode=phase)
            QTest.qWait(1200)
            ctypes.windll.kernel32.SetErrorMode(1 | 2 | 32768)
            if phase == 'native':
                import faulthandler
                for runtime in ('ucrtbase', 'msvcrt'):
                    try:
                        crt = ctypes.CDLL(runtime)
                        crt._set_abort_behavior(0, 3)
                        crt._set_error_mode(2)
                    except (AttributeError, OSError):
                        pass
                faulthandler._sigsegv()
            os._exit(77)
        wait(lambda : getattr(page, '_canvas_editor', None) is not None and page.subtitle_edit_input.toPlainText() == expected['draft'])
        require(page.project.cues[0].text == expected['committed'], 'acceptance requirement failed')
        require(page.project.cues[1].text != expected['draft'], 'acceptance requirement failed')
        result['checks'].update(committed_recovered=True, unconfirmed_draft_recovered=True, draft_not_committed=True)
        require(set(result['decisions']) == {'恢复自动保存', '恢复到编辑框'}, 'acceptance requirement failed')
        QTest.qWait(350)
        require(getattr(page, '_canvas_editor', None) is not None and page.subtitle_edit_input.isVisible() and page.subtitle_edit_input.toPlainText() == expected['draft'], 'recovered draft must remain visible after dialog closes')
        _capture(window, output / 'restored-draft.png')
        page._cancel_canvas_inline_edit()
        wait(lambda : not candidates(page.project.project_id))
        result['checks']['cancel_removes_draft'] = True
        page.project_path = output / 'recovered-copy.2byteproj'
        page.save()
        recovered = load_project(page.project_path)
        require(recovered.cues[0].text == expected['committed'] and recovered.cues[1].text != expected['draft'], 'saved recovery text differs')
        result['checks']['recovered_copy_saved'] = True
        timer.stop()
        target = output / 'exported-diagnostics.zip'
        old = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(target), 'ZIP (*.zip)')

        def click_export():
            for dialog in QApplication.topLevelWidgets():
                if dialog.objectName() == 'diagnosticsDialog':
                    button = dialog.findChild(QPushButton, 'diagnosticExportButton')
                    if button and button.isEnabled() and (not target.exists()):
                        button.click()
                    if target.exists():
                        _capture(dialog, output / 'diagnostic-export.png')
                        dialog.accept()
        export_timer = QTimer(window)
        export_timer.timeout.connect(click_export)
        export_timer.start(150)
        try:
            open_diagnostics_dialog(window)
        finally:
            QFileDialog.getSaveFileName = old
            export_timer.stop()
        require(target.is_file(), 'acceptance requirement failed')
        with zipfile.ZipFile(target) as bundle:
            raw = b'\n'.join((bundle.read(name) for name in bundle.namelist()))
            require(expected['committed'].encode('utf8') not in raw, 'acceptance requirement failed')
            require(expected['draft'].encode('utf8') not in raw, 'acceptance requirement failed')
            require(not any((name.endswith('.dmp') for name in bundle.namelist())), 'acceptance requirement failed')
            result['checks']['export_no_private_text'] = True
            result['checks']['previous_unclean_marker'] = b'previous_not_cleanly_ended' in raw
        require(result['checks']['previous_unclean_marker'], 'acceptance requirement failed')
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        timer.stop()
        if getattr(page, '_canvas_editor', None) is not None:
            page._cancel_canvas_inline_edit()
        page.undo_stack.setClean()
        save()
    return 0 if result['passed'] else 1

def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(window, output)
        except Exception:
            (output / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = output / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)
