"""Focused actual-window prompt/frame checks, called only by explicit acceptance runs."""
from pathlib import Path
import copy
import hashlib
import os
import time


def check_chrome(dialog, check, settle):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    check('candy frame is frameless and owns visible title/body', bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
          and dialog.chrome.title_bar.isVisible() and dialog.chrome.body.isVisible())
    before = dialog.geometry()
    QTest.mouseClick(dialog.chrome.buttons.maximize_button, Qt.MouseButton.LeftButton)
    settle(.2)
    check('candy maximize fills available screen', dialog.chrome.window.maximized
          and dialog.geometry() == dialog.screen().availableGeometry())
    QTest.mouseClick(dialog.chrome.buttons.maximize_button, Qt.MouseButton.LeftButton)
    settle(.2)
    check('candy restore keeps normal geometry', not dialog.chrome.window.maximized and dialog.geometry() == before)


def prompt_checks(window, page, out, check, ready):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..app.application_settings import save_recovery_policy, effective_recovery_policy, read_studio_preferences
    from ..design.theme_manager import request_theme, theme_key
    from ..projects.project_dirty_guard import ProjectDirtyGuard
    from ..projects.project_recovery_dialog import RecoveryDialog
    from ..projects.save_changes_dialog import SaveChangesDialog
    from ..projects.studio_project import load_project, save_project, save_autosave
    app = QApplication.instance()
    def visible(kind):
        return next((d for d in app.topLevelWidgets() if isinstance(d, kind) and d.isVisible()), None)
    guard = ProjectDirtyGuard(page)
    for theme in ('sand', 'midnight'):
        request_theme(theme)
        yield lambda: theme_key() == theme and not getattr(app, '_theme_update_pending', False)
        for value in ('cancel', 'discard', 'save'):
            answer = []
            QTimer.singleShot(0, window, lambda answer=answer: answer.append(guard._prompt('退出应用')))
            yield lambda: visible(SaveChangesDialog) is not None
            box = visible(SaveChangesDialog)
            yield .15
            check(theme+' save prompt is modal with three visible choices', box.isModal()
                  and len(box.buttons()) == 3 and all(b.isVisible() and b.width() > 70 for b in box.buttons()))
            check(theme+' save defaults to save and names the project', box.save_button.isDefault()
                  and bool(box.informativeText()) and bool(box.windowFlags() & Qt.WindowType.FramelessWindowHint))
            disc = box.bunny_disc
            if disc is None:
                check(theme+' save prompt shows the bunny charm', False)
            else:
                mascot = disc.mascot
                body = mascot.body_center() + mascot.pos()
                check(theme+' bunny body is centred in the visible charm',
                      mascot.isVisible() and abs(body.x() - disc.centre.x()) <= 1
                      and abs(body.y() - disc.centre.y()) <= 1
                      and mascot.pos().y() + mascot.pad_top >= 0)
            check(theme+' prompt screenshot '+value, box.grab().save(str(out/('save-'+theme+'-'+value+'.png'))))
            if value == 'cancel':
                QTest.keyClick(box, Qt.Key.Key_Escape)
            elif value == 'save':
                QTest.keyClick(box.save_button, Qt.Key.Key_Return)
            else:
                QTest.mouseClick(box.discard_button, Qt.MouseButton.LeftButton)
            yield lambda: bool(answer)
            check(theme+' actual dirty guard returns '+value, answer[0].value == value)
    request_theme('sand')
    yield lambda: theme_key() == 'sand' and not getattr(app, '_theme_update_pending', False)
    folder = out/'prompt-recovery'
    folder.mkdir()
    official_path = folder/'project.2byteproj'
    official = copy.deepcopy(page.project)
    save_project(official, official_path)
    original_text = official.cues[0].text
    original_sha = hashlib.sha256(official_path.read_bytes()).hexdigest()
    recovered = copy.deepcopy(official)
    recovered.cues[0].text = '自动恢复里保留的修改 · acceptance'
    def fixture():
        candidate = save_autosave(recovered, official_path)
        yesterday = time.time()-86400
        os.utime(official_path, (yesterday, yesterday))
        return candidate
    def hub():
        page.undo_stack.setClean()
        page.show_project_hub(skip_dirty_guard=True)
    candidate = fixture()
    check('unselected recovery preference defaults to auto', effective_recovery_policy(read_studio_preferences()) == 'auto')
    hub()
    window.open_studio_project(str(official_path))
    yield lambda: ready(official_path)
    check('actual open recovers newer content without a question', page.project.cues[0].text == recovered.cues[0].text
          and visible(RecoveryDialog) is None)
    for value in ('saved', 'cancel', 'ignore', 'recover'):
        hub()
        candidate = fixture()
        save_recovery_policy('ask')
        window.open_studio_project(str(official_path))
        yield lambda: visible(RecoveryDialog) is not None
        box = visible(RecoveryDialog)
        yield .2
        check('explicit ask opens two distinct version cards '+value, box.isModal() and box.recover_button.isVisible()
              and box.saved_button.isVisible() and box.recover_button.ribbon.isVisible())
        check('recovery shows calendar day and both times '+value, any(label.text() == '昨天' or '昨天' in label.text()
              for label in box.findChildren(type(box.recover_button.ribbon))))
        check('recovery screenshot '+value, box.grab().save(str(out/('recovery-'+value+'.png'))))
        if value == 'cancel':
            QTest.keyClick(box, Qt.Key.Key_Escape)
            yield lambda: not window._studio_loading_session.active
            check('Esc cancels opening and retains autosave', candidate.is_file() and page._project_view_state == 'hub')
        else:
            if value == 'recover':
                QTest.mouseClick(box.always, Qt.MouseButton.LeftButton)
            button = {'saved':box.saved_button, 'ignore':box.delete_button, 'recover':box.recover_button}[value]
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            yield lambda: ready(official_path)
            expected = recovered.cues[0].text if value == 'recover' else original_text
            check('actual recovery route preserves selected content '+value, page.project.cues[0].text == expected)
            if value == 'ignore':
                check('delete link removes only isolated recovery file', not candidate.exists())
            if value == 'recover':
                check('checkbox changes isolated preference to auto', effective_recovery_policy(read_studio_preferences()) == 'auto')
    check('all recovery choices leave official project bytes intact', hashlib.sha256(official_path.read_bytes()).hexdigest() == original_sha)
    hub()
    window.open_studio_project(str(out/'p12/project.2byteproj'))
    yield lambda: ready(out/'p12/project.2byteproj')

    from PySide6.QtGui import QUndoCommand
    original = out/'p12/project.2byteproj'
    draft_text = '加载遮罩上点保存 · acceptance'
    page.project.cues[0].text = draft_text
    page.undo_stack.push(QUndoCommand('Mark the changed fixture dirty'))
    target = out/'p2000/project.2byteproj'
    QTimer.singleShot(0, window, lambda: window.open_studio_project(str(target)))
    yield lambda: visible(SaveChangesDialog) is not None
    box = visible(SaveChangesDialog)
    loading = window._studio_loading_session
    check('dirty project prompts on the actual loading cover',
          loading.active and loading.view.isVisible() and loading._input_lease.held
          and app.activeModalWidget() is box)
    QTest.keyClick(box, Qt.Key.Key_Escape)
    yield lambda: ready(original)
    check('cancelling over the cover retains the original dirty project',
          guard.is_dirty() and load_project(original).cues[0].text != draft_text)

    QTimer.singleShot(0, window, lambda: window.open_studio_project(str(target)))
    yield lambda: visible(SaveChangesDialog) is not None
    box = visible(SaveChangesDialog)
    check('save confirmation over loading cover captured',
          box.grab().save(str(out/'save-over-loading.png')))
    QTest.mouseClick(box.save_button, Qt.MouseButton.LeftButton)
    yield lambda: ready(target)
    check('clicking Save through the cover commits before switching projects',
          visible(SaveChangesDialog) is None and load_project(original).cues[0].text == draft_text)
    window.open_studio_project(str(original))
    yield lambda: ready(original)
