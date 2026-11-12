"""Normal-entry UI and collision checks for the combined local daily."""
import json
import os
import sys
import time
import traceback


def install_guards():
    from .ai_tasks_home_b_audit import install_guards as install
    install()


def verify_ui(window, output):
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from ..design.theme_manager import apply_theme
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project

    app = QApplication.instance()
    checks = []

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))
        (output/'progress.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), 'utf8')
        if not passed:
            raise AssertionError(name)

    def settle(seconds=.2):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)

    def wait(predicate, seconds=40):
        deadline = time.monotonic()+seconds
        while not predicate() and time.monotonic() < deadline:
            settle(.02)
        if not predicate():
            raise TimeoutError(str(predicate))

    window._ensure_recognition_page()
    window._return_to_settings()
    settle(.5)
    check('home hint rows hidden', window.subtitle_language_summary.isHidden() and window.subtitle_language_hint.isHidden())
    target = window.subtitle_language_hint
    event = QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), target.mapToGlobal(QPoint(1, 1)))
    check('home hover hints suppressed', window._home_tooltip_mute.eventFilter(target, event))
    for theme in ('grape', 'warm'):
        apply_theme(theme, app)
        settle(.4)
        check(theme+' home screenshot', window.grab().save(str(output/f'home-{theme}.png')))

    class Shows(QObject):
        def __init__(self):
            super().__init__()
            self.names = []

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                self.names.append(obj.objectName() or type(obj).__name__)
            return False

    from ..app.link_download_widgets import TaskCard
    shows = Shows()
    app.installEventFilter(shows)
    cards = [TaskCard('audit-full'), TaskCard('audit-compact', compact=True)]
    settle()
    app.removeEventFilter(shows)
    check('constructing task cards creates no transient windows', shows.names == [], shows.names)
    from ..app.link_download_controller import show_link_download
    controller = show_link_download(window)
    settle(.4)
    check('normal link download dialog opens', controller.dialog.isVisible())
    check('link dialog screenshot', controller.dialog.grab().save(str(output/'link-download.png')))
    controller.dialog.hide()
    for card in cards:
        card.deleteLater()

    fixture = output/'ui.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path=str(output/'ui-media.mp4'), duration_ms=7000, width=960, height=540),
                                cues=[StudioCue('a', 0, 1000, '联合日常验收')]), fixture)
    window.open_studio_project(str(fixture))
    wait(lambda: window.built_page('studio') is not None and window.built_page('studio').project is not None)
    wait(lambda: window.__dict__.get('_studio_loading_session') is None
         or (not window._studio_loading_session.active and not window._studio_loading_session.view.isVisible()))
    page = window.studio_page
    page.select_cue('a')
    settle(.5)
    for theme in ('grape', 'warm'):
        apply_theme(theme, app)
        settle(.3)
        menu = page.cue_ai_button.menu()
        menu.aboutToShow.emit()
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        check(theme+' AI commands grouped by scope', labels[:5] == ['整个工程', 'AI 校对', 'AI 清理', 'AI 断句', '翻译整个工程…']
              and '当前 / 选中的字幕' in labels and 'AI 断句（选中范围）' in labels)
        menu.popup(page.cue_ai_button.mapToGlobal(QPoint(0, page.cue_ai_button.height())))
        settle(.3)
        check(theme+' AI menu visible', menu.isVisible())
        check(theme+' AI menu screenshot', menu.grab().save(str(output/f'ai-menu-{theme}.png')))
        rect = app.primaryScreen().availableGeometry()
        check(theme+' AI menu fits the screen', rect.contains(menu.frameGeometry()),
              dict(screen=rect.getRect(), menu=menu.frameGeometry().getRect()))
        menu.close()
        calls = []
        original_refine = page.run_sentence_refine
        page.run_sentence_refine = lambda **kwargs: calls.append(kwargs)
        try:
            action = page.ai_refine_project_action
            menu.popup(page.cue_ai_button.mapToGlobal(QPoint(0, page.cue_ai_button.height())))
            settle(.1)
            row = next(widget for widget in action.createdWidgets() if widget.isVisible())
            QTest.mouseClick(row, Qt.MouseButton.LeftButton)
            settle(.1)
            check(theme+' rich menu mouse activation', calls == [dict(whole_project=True)] and not menu.isVisible())
            menu.popup(page.cue_ai_button.mapToGlobal(QPoint(0, page.cue_ai_button.height())))
            menu.setActiveAction(action)
            QTest.keyClick(menu, Qt.Key.Key_Return)
            settle(.1)
            check(theme+' rich menu keyboard activation', len(calls) == 2 and not menu.isVisible())
        finally:
            page.run_sentence_refine = original_refine
            menu.close()
        options = page.timeline_options_button.menu()
        options.aboutToShow.emit()
        check(theme+' timeline menu keeps display switches',
              {'波形', '缩略图', '跟随播放头', '自动吸附'} <= {a.text() for a in options.actions()}
              and page.selection_center_toggle.isVisible() and not page.selection_center_toggle.isCheckable())
        more = page.cue_more_button.menu()
        more.aboutToShow.emit()
        check(theme+' cue menu keeps collision setting', any('避让' in a.text() for a in more.actions()))
        check(theme+' math switch stays connected', page.style_math_button.isCheckable()
              and page.style_math_button.isChecked() == page.math_formulas_action.isChecked())

    task = page._new_subtitle_task('合流验收', page.project.cues)
    page._refresh_subtitle_task_entry()
    check('task button expands while running', page.subtitle_tasks_button.property('taskState') == 'active')
    task.update(dict(range_id='a', cue_ids=['a'], status='unchanged'))
    task.finish()
    page._refresh_subtitle_task_entry()
    check('finished task has unread dot', page.subtitle_tasks_dot.isVisible())
    QTest.mouseClick(page.subtitle_tasks_button, Qt.MouseButton.LeftButton)
    settle()
    check('task panel opens and unread dot clears', page._subtitle_task_panel().isVisible() and not page.subtitle_tasks_dot.isVisible())
    page._subtitle_task_panel().hide()
    for cycle in range(3):
        page.undo_stack.setClean()
        page.show_project_hub()
        settle(.3)
        window._return_to_settings()
        settle(.3)
        check(f'home return {cycle} leaves editor and video hidden',
              page.workspace_layers.currentWidget() is page.studio_empty
              and not page.workspace_splitter.isVisible() and not page.video.isVisible())
        window.pages.setCurrentWidget(page)
        page.show()
        settle(.2)
        check(f'library return {cycle} keeps library visible', page.studio_empty.isVisible()
              and not page.video.isVisible())
    check('library screenshot', page.grab().save(str(output/'library-after-home.png')))
    (output/'result.json').write_text(json.dumps(dict(checks=checks), ensure_ascii=False, indent=2), 'utf8')
    window.close()
    settle(2.)


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        from ..diagnostics.build_identity import load_build_identity
        code = 0
        try:
            if os.environ.get('TWOBYTEASR_JOINT_AUDIT_MODE') == 'collision':
                from .collision_layout_audit import run
                run(output, window=window)
            else:
                verify_ui(window, output)
        except Exception:
            code = 1
            (output/'audit-error.txt').write_text(traceback.format_exc(), 'utf8')
            window.grab().save(str(output/'failure.png'))
            window.close()
        path = output/'result.json'
        result = json.loads(path.read_text('utf8')) if path.exists() else {}
        checks = result.get('checks', [])
        result.update(passed=code == 0 and bool(checks) and all(row['passed'] for row in checks),
                      checks_passed=sum(row['passed'] for row in checks),
                      executable=sys.executable, pid=os.getpid(), frozen=bool(getattr(sys, 'frozen', False)),
                      identity=load_build_identity().to_dict())
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().exit(0 if result['passed'] else 1)

    QTimer.singleShot(600, execute)
