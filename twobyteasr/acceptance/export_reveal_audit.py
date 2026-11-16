"""Opt-in, isolated normal-entry checks of the completed video folder button."""
import json
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, lambda: run(window, output))


def run(window, output):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from unittest.mock import patch
    from ..system import file_manager
    from ..design.theme_manager import apply_theme
    app = QApplication.instance()
    result = dict(passed=False, checks=[])
    page = None
    import faulthandler
    fault_file = (output/'reveal-stacks.txt').open('w', encoding='utf8')
    faulthandler.dump_traceback_later(45, file=fault_file)

    def mark(stage):
        with (output/'reveal-progress.jsonl').open('a', encoding='utf8') as stream:
            stream.write(json.dumps(dict(stage=stage, time=time.time()))+'\n')

    def check(name, condition):
        result['checks'].append(dict(name=name, passed=bool(condition)))
        if not condition:
            raise AssertionError(name)

    def settle(seconds=.15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def wait(predicate, seconds=40):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            settle(.05)
        check('normal entry ready: ' + str(predicate), predicate())

    try:
        import shutil
        apply_theme('midnight', app)
        window.resize(1440, 960)
        window.open_studio_project(str(output/'p12/project.2byteproj'))
        wait(lambda: window.built_page('studio') is not None and window.built_page('studio').project is not None)
        page = window.built_page('studio')
        wait(lambda: getattr(window, '_studio_loading_session', None) is None or not window._studio_loading_session.active)
        page.video.set_paused(True)
        page._open_render_dialog(skip_preflight=True)
        settle(.5)
        workspace = page.export_workspace
        check('normal export workspace opened', workspace is not None)
        target = output/'成片 中文 空格 & #1'/'实际成片 [完成].mp4'
        target.parent.mkdir()
        shutil.copyfile(output/'sample.mp4', target)
        mark('before_show_success')
        workspace._show_success(str(target))
        mark('after_show_success')
        settle(.6)
        button = workspace.open_folder_button
        workspace.success_page.scroll.ensureWidgetVisible(button)
        settle()
        check('folder button visible and enabled', button.isVisible() and button.isEnabled())
        calls = []
        native = file_manager._windows_reveal
        def select(path):
            answer = native(path)
            calls.append(dict(path=str(path), succeeded=answer))
            return answer
        with patch.object(file_manager, '_windows_reveal', select):
            mark('before_native_click')
            QTest.mouseClick(button, Qt.LeftButton)
            mark('after_native_click')
            settle(1)
        result['native_calls'] = calls
        result['output_file'] = str(target)
        check('real shell selected the complete Chinese path', bool(calls) and calls[-1]['succeeded'] and Path(calls[-1]['path']) == target)
        check('successful reveal has no error', workspace.success_page.error.isHidden())
        window.grab().save(str(output/'success-reveal.png'))
        # Repeat from the same visible button, including existing folder reuse.
        QTest.mouseClick(button, Qt.LeftButton)
        settle(.5)
        check('repeat click remains usable', workspace.success_page.error.isHidden() and button.isEnabled())
        with patch.object(file_manager, '_windows_reveal', lambda path: False), patch('PySide6.QtGui.QDesktopServices.openUrl', lambda url: False):
            QTest.mouseClick(button, Qt.LeftButton)
            settle()
        check('both shell routes failing shows a readable error', not workspace.success_page.error.isHidden() and '无法打开资源管理器' in workspace.success_page.error.text())
        with patch.object(file_manager, '_windows_reveal', lambda path: False), patch('PySide6.QtGui.QDesktopServices.openUrl', lambda url: True):
            QTest.mouseClick(button, Qt.LeftButton)
            settle()
        check('folder fallback clears earlier error', workspace.success_page.error.isHidden())
        moved = target.with_suffix('.moved.mp4')
        target.rename(moved)
        QTest.mouseClick(button, Qt.LeftButton)
        settle()
        check('moved output shows missing file feedback', not workspace.success_page.error.isHidden() and '找不到成片' in workspace.success_page.error.text())
        moved.rename(target)
        QTest.mouseClick(button, Qt.LeftButton)
        settle(.3)
        check('restored output can be revealed again', workspace.success_page.error.isHidden())
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        faulthandler.cancel_dump_traceback_later()
        if page is not None:
            page._close_export_workspace()
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        window.close()
        QTimer.singleShot(500, app.quit)
