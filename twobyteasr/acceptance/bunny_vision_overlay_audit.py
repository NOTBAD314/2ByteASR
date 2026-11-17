"""New bunny delivery through the normal isolated Windows entry; no external AI requests."""
def run(window, page, output, check):
    import json
    import time
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtTest import QTest
    from ..app import bunny_chat, bunny_permissions, bunny_vision, user_overlay, user_overlay_runtime
    from ..app.application_settings_ui import ApplicationSettingsDialog
    from ..app.bunny_tools import run_turn, undo_records
    from ..app.onboarding import load_state, save_state
    from ..design.theme_manager import request_theme
    from .. import i18n
    app = QApplication.instance()
    def wait(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        raise TimeoutError('bunny vision overlay acceptance')
    prior_permissions = bunny_permissions.load()
    prior_ready, prior_run, prior_support = bunny_chat.ai_readiness, bunny_chat.BunnyChatWorker.run, bunny_vision.support
    original_size = window.size()
    dialog = card = None
    first_snapshot = None
    check('overlay audit uses isolated user data', user_overlay.root().resolve().is_relative_to(output.resolve()))
    try:
        bunny_chat.ai_readiness = lambda _settings: (True, 'Offline controlled image provider')
        bunny_vision.support = lambda _settings: (True, '')
        permission = dict(bunny_permissions.DEFAULTS, level='auto')
        bunny_permissions.save(permission)
        refused = run_turn(window, [('look_screen', {})], permission)
        check('screen is disabled by default and returns no image', not refused.images and '权限' in refused.receipts[0])
        state = load_state();state.pop(bunny_permissions.SCREEN_ACK_KEY, None);save_state(state)
        dialog = ApplicationSettingsDialog(window, {}, output/'overlay-projects', browse=lambda *a:None,
                                          clear_recent=lambda:None, reset_layout=lambda:None)
        labels = [dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
        dialog.navigation.setCurrentRow(labels.index('兔白权限'));dialog.resize(980,760);dialog.show();app.processEvents()
        acknowledgments = []
        def answer(role):
            box = app.activeModalWidget()
            if isinstance(box, QMessageBox):
                acknowledgments.append('字幕' in box.informativeText() and 'AI' in box.informativeText())
                next(button for button in box.buttons() if box.buttonRole(button) == role).click()
        QTimer.singleShot(100, lambda:answer(QMessageBox.ButtonRole.RejectRole))
        dialog.bunny_see_screen.setChecked(True)
        check('screen first explanation can be declined', not dialog.bunny_see_screen.isChecked() and not bunny_permissions.screen_explained())
        QTimer.singleShot(100, lambda:answer(QMessageBox.ButtonRole.AcceptRole))
        dialog.bunny_see_screen.setChecked(True)
        dialog._save_bunny_permissions()
        check('screen first explanation accepted through actual button', bunny_permissions.screen_explained() and all(acknowledgments) and len(acknowledgments)==2)
        dialog._input_baseline = dict(dialog._input_values());dialog.reject();dialog.deleteLater();dialog=None;app.processEvents()

        page.cue_bunny_button.click();app.processEvents();card=window._bunny_chat;card.set_mode('dialog');card.reveal_all()
        check('workbench bunny entry opens actual chat', card.isVisible() and page.cue_bunny_button.isVisible())
        sent=[];answers=[{'lines':['兔白看一眼'], 'tools':[{'name':'look_screen'}, {'name':'look_screen'}]},
                         {'lines':['这是离线验收回复，图像已经收到。']}, {'lines':['下一题只带文字。']}]
        def worker_run(worker):
            messages=list(worker._messages)
            if worker._receipts is not None or worker._background:
                turn=bunny_chat.bunny_persona.tool_results_message(worker._receipts or [],worker._state_text)
                messages.append(bunny_vision.with_images(turn,worker._images));worker.looked_up.emit(turn)
            sent.append(messages)
            worker.answered.emit(json.dumps(answers.pop(0),ensure_ascii=False))
        bunny_chat.BunnyChatWorker.run=worker_run
        card.input.setText('看看工作台的排版');card.send();wait(lambda:not card.busy and len(sent)==2);card.reveal_all()
        check('image sent once with a tool result', isinstance(sent[1][-1]['content'],list) and sent[1][-1]['content'][1]['type']=='image_url')
        check('duplicate screenshot request is bounded', '一轮只截一张' in sent[1][-1]['content'][0]['text'])
        check('dialog screenshot thumbnail is visible', card.shot_label.isVisible() and not card.shot_label.pixmap().isNull())
        card.grab().save(str(output/'vision-dialog.png'))
        check('chat history keeps no image payload', all(isinstance(turn['content'],str) for turn in card._history) and 'data:image' not in json.dumps(card._history))
        card.input.setText('继续');card.send();wait(lambda:not card.busy and len(sent)==3);card.reveal_all()
        check('next question does not resend screenshot', all(isinstance(turn['content'],str) for turn in sent[-1]))
        card.set_mode('thread');shot=bunny_vision.capture(window);card._show_shot(shot);QTest.qWait(350)
        check('picture is bounded and excludes chat window', max(shot.width,shot.height)<=1280 and card not in bunny_vision._own_windows(window))
        card.grab().save(str(output/'vision-thread.png'))
        card.close_chat();card=None;app.processEvents()

        entry, first_snapshot=user_overlay.add('note','','离线验收说明')
        user_overlay_runtime.reapply()
        button=page.cue_bunny_button;before=button.styleSheet()
        proposed=[('propose_change',dict(kind='style',target='#cueBunnyButton',value='font-size: 19px;',why='验收字号'))]
        pending=run_turn(window,proposed,bunny_permissions.load())
        check('persistent changes wait even in auto mode', bool(pending.pending) and button.styleSheet()==before)
        done=run_turn(window,pending.pending,bunny_permissions.load(),confirmed=True)
        check('confirmed user style reaches real studio button', bool(done.undo) and 'font-size: 19px' in button.styleSheet())
        check('user overlay undo restores actual widget', undo_records(done.undo)==(1,'') and button.styleSheet()==before)
        entry,_=user_overlay.add('text','保存更改','验收存起来',by='bunny');user_overlay_runtime.reapply()
        check('user text applies through actual translation path', i18n.translate('保存更改','zh')=='验收存起来')
        script,_=user_overlay.add('script','','验收脚本',code='API_VERSION = 1\ndef setup(api):\n    api.log("acceptance")\n',by='bunny')
        check('AI script is saved disabled behind global gate', not script['enabled'] and not user_overlay.load()['scripts_allowed'])
        dialog=ApplicationSettingsDialog(window,{},output/'overlay-projects',browse=lambda *a:None,clear_recent=lambda:None,reset_layout=lambda:None)
        labels=[dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
        dialog.navigation.setCurrentRow(labels.index('我的改动'));dialog.resize(980,760);dialog.show();app.processEvents()
        check('actual overlay settings lists persisted entries', dialog.overlay_list.count()==len(user_overlay.entries()))
        row=next(dialog.overlay_list.item(i) for i in range(dialog.overlay_list.count()) if dialog.overlay_list.item(i).data(Qt.ItemDataRole.UserRole)==entry['id'])
        row.setCheckState(Qt.CheckState.Unchecked);app.processEvents()
        check('settings checkbox disables text immediately', i18n.translate('保存更改','zh')=='保存更改')
        for theme in ('sand','midnight'):
            request_theme(theme);QTest.qWait(250)
            from ..design.studio_theme import refresh_secondary_surface_theme
            refresh_secondary_surface_theme(dialog);app.processEvents()
            check('overlay settings actions visible '+theme, all(not b.visibleRegion().isEmpty() for b in (dialog.overlay_edit,dialog.overlay_remove,dialog.overlay_new_script,dialog.overlay_restore)))
            dialog.grab().save(str(output/('overlay-'+theme+'.png')))
        dialog._input_baseline=dict(dialog._input_values());dialog.reject();dialog.deleteLater();dialog=None;app.processEvents()
        user_overlay.restore(first_snapshot);user_overlay_runtime.reapply();first_snapshot=None
        check('overlay restore preserves empty initial layer', user_overlay.entries()==[])

        page._set_cue_filter('all');page._set_review_mode(True);QTest.qWait(250)
        check('new candy review strip enters through review flow', page._review_mode and page.review_summary_strip.isVisible())
        for theme in ('sand','midnight'):
            request_theme(theme);QTest.qWait(250)
            check('review confirmation and key legend visible '+theme, page.review_confirm_button.isVisible() and page.review_legend.isVisible())
            window.grab().save(str(output/('review-'+theme+'.png')))
        page._set_review_mode(False)
        button.click();app.processEvents();card=window._bunny_chat;card.reveal_all();card._say_tip();card.reveal_all()
        check('studio tip is visible without a request', not card.busy and bool(card.transcript))
        card.grab().save(str(output/'bunny-tip.png'))
    finally:
        if card is not None:card.close_chat()
        if dialog is not None:dialog._input_baseline=dict(dialog._input_values());dialog.reject()
        if first_snapshot is not None:user_overlay.restore(first_snapshot);user_overlay_runtime.reapply()
        bunny_chat.ai_readiness=prior_ready;bunny_chat.BunnyChatWorker.run=prior_run;bunny_vision.support=prior_support
        bunny_permissions.save(prior_permissions)
        page._set_review_mode(False);page._set_cue_filter('all');page.select_cue('a');window.resize(original_size)
