"""Host intake: real controls and completion page, isolated profile, no cloud."""
def run(window, page, output, check):
    import time
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
    from PySide6.QtTest import QTest
    from ..app import bunny_nav_tools, bunny_permissions
    from ..app.application_settings_ui import ApplicationSettingsDialog
    from ..app.bunny_tools import run_turn, undo_records
    from ..design.theme_manager import request_theme
    app = QApplication.instance()
    permissions = dict(bunny_permissions.load(), level='auto', read_subtitles=True, read_diagnostics=True)
    saved = bunny_permissions.load()
    records = bunny_nav_tools.result_records
    dialog = None
    def wait(predicate):
        end = time.monotonic() + 15
        while not predicate() and time.monotonic() < end:
            app.processEvents();QTest.qWait(10)
        check('universal bounded wait', predicate())
    def call(name, args=None, values=None, confirmed=False):
        return run_turn(window, [(name, args or {})], values or permissions, confirmed=confirmed)
    try:
        bunny_permissions.save(permissions)
        for theme in ('sand', 'midnight'):
            request_theme(theme);QTest.qWait(200)
            dialog = ApplicationSettingsDialog(window, {}, output/'projects', browse=lambda *a: None,
                clear_recent=lambda: None, reset_layout=lambda: None)
            labels = [dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
            dialog.navigation.setCurrentRow(labels.index('工程与保存'))
            dialog.resize(940, 720);dialog.show();app.processEvents()
            listing = call('ui_snapshot', {'window': dialog.windowTitle()}).receipts[0]
            check('universal actual settings snapshot '+theme, '5 分钟' in listing and '保存更改' in listing)
            asked = call('ui_press', {'text': '5 分钟'}, dict(permissions, level='ask'))
            check('universal settings change waits for actual approval '+theme,
                bool(asked.pending) and dialog.interval.currentData() != 300)
            done = run_turn(window, asked.pending, dict(permissions, level='ask'), confirmed=True)
            QTest.qWait(50)
            check('universal approved real radio changes interval '+theme,
                '成功' in done.receipts[0] and dialog.interval.currentData() == 300)
            call('ui_snapshot')
            again = run_turn(window, asked.pending, permissions, confirmed=True)
            check('universal new snapshot invalidates old approval '+theme, '过期' in again.receipts[0])
            dialog.grab().save(str(output/('universal-settings-'+theme+'.png')))
            save = call('ui_press', {'text': '保存更改'}, dict(permissions, level='ask'))
            check('universal real save requires approval '+theme, bool(save.pending))
            run_turn(window, save.pending, dict(permissions, level='ask'), confirmed=True)
            wait(lambda: not dialog.isVisible())
            check('universal real save accepts settings '+theme, dialog.result() == QDialog.DialogCode.Accepted)
            dialog.deleteLater();dialog = None;app.processEvents()
        closed = dict(permissions, read_subtitles=False, read_diagnostics=False)
        for name in ('ui_snapshot', 'recent_results', 'recent_projects'):
            check('universal closed read switch '+name, '关掉了' in call(name, values=closed).receipts[0])
        window._switch_page(page);page.select_cue(page.project.cues[0].id)
        before = page.undo_stack.index()
        done = call('run_command', {'id': 'nudge_later'})
        check('universal actual editing command makes undo', bool(done.undo) and page.undo_stack.index() > before)
        check('universal command undo restores stack', undo_records(done.undo) == (1, '') and page.undo_stack.index() == before)
        deletion = call('run_command', {'id': 'delete'})
        check('universal actual deletion always waits', bool(deletion.pending) and page.undo_stack.index() == before)
        media = page.project.media.path
        record = SimpleNamespace(media_name=str(media), completed_at='2026-11-17 17:00',
            status='completed', status_label='已完成', cue_count=len(page.project.cues),
            payload={'status':'completed','media':{'path':str(media)},'task':{},'events':[],
                     'result':{'outputs':{'project':str(window._startup_project if hasattr(window,'_startup_project') else '')},'elapsed_seconds':1}},
            path=output/'owned-history.json',outcome=SimpleNamespace(result_usable=True))
        # The production startup fixture is already a saved project.
        import os
        record.payload['result']['outputs']['project'] = os.environ['TWOBYTEASR_STARTUP_PROJECT']
        bunny_nav_tools.result_records = lambda limit=10, roots=None: [(record.path, record)]
        listing = call('recent_results').receipts[0]
        check('universal recognition names never reveal profile path', '能打开结果' in listing and str(output) not in listing)
        done = call('open_result')
        check('universal actual history opens completion page', '成功' in done.receipts[0]
            and window.pages.currentWidget() is window.pages.widget(2))
        window.grab().save(str(output/'universal-opened-result.png'))
        window._switch_page(page)
    finally:
        bunny_nav_tools.result_records = records
        bunny_permissions.save(saved)
        if dialog is not None:
            dialog.done(QDialog.DialogCode.Rejected);dialog.deleteLater()
        app.processEvents()
