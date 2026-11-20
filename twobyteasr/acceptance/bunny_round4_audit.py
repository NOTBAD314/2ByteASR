"""Fourth-round tools and visible chat controls in the normal isolated Windows GUI."""
def run(window, page, output, check):
    import json
    import shiboken6
    from types import SimpleNamespace
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication, QPushButton, QListWidget
    from PySide6.QtTest import QTest
    from ..app import bunny_chat, bunny_memory, bunny_permissions
    from ..app.bunny_tools import run_turn, undo_records, snapshot
    from ..app.bunny_persona import BunnyReply
    from ..design.theme_manager import request_theme
    app=QApplication.instance()
    prior=bunny_permissions.load();memory=bunny_memory.load();ready=bunny_chat.ai_readiness
    store=getattr(page,'_learning_store',None);card=None
    allowed=dict(bunny_permissions.DEFAULTS,level='auto')
    before=[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]
    try:
        bunny_permissions.save(allowed);bunny_memory.clear_chats()
        bunny_chat.ai_readiness=lambda settings:(True,'Offline acceptance')
        report=run_turn(window,[('check_subtitles',{'scope':'all'})],allowed)
        check('round4 health report from actual project','成功' in report.receipts[0] and '查了' in report.receipts[0])
        result=run_turn(window,[('set_break_rule',{'rule':'语气词不要单独成条'})],allowed)
        check('round4 grouping preference saves and is undoable',len(result.undo)==1 and undo_records(result.undo)==(1,''))
        corrected=before[0][1].replace('营第','营地')
        edited=run_turn(window,[('edit_cue',{'number':1,'text':corrected})],allowed)
        check('round4 text edit reaches real timeline',len(edited.undo)==1 and page.project.cues[0].text==corrected)
        card=bunny_chat.open_bunny_chat(window);card.reveal_all()
        card._question='修改第一条字幕';card._log(edited.receipts,edited.undo)
        card.log_button.click();app.processEvents();dialog=card._log_dialog
        check('round4 action log opens by actual toolbar button',dialog.isVisible() and dialog.findChild(QListWidget,'bunnyLogList').count()==1)
        dialog.grab().save(str(output/'round4-log.png'))
        dialog.findChild(QPushButton,'bunnyLogUndo').click();app.processEvents()
        check('round4 action log undo restores actual text',page.project.cues[0].text==before[0][1])
        dialog.close()
        translated=run_turn(window,[('edit_cue',{'number':1,'text':'Audited translation','layer':'translation'})],allowed)
        check('round4 translation is undoable',len(translated.undo)==1 and undo_records(translated.undo)==(1,''))
        replaced=run_turn(window,[('replace_text',{'find':'营第','replace':'营地','scope':'all'})],allowed)
        check('round4 replacement is marked AI adoption',bool(replaced.undo) and all(getattr(c,'origin',None).value=='model_adoption' for c in replaced.undo[0].commands))
        check('round4 replace undo restores actual project',undo_records(replaced.undo)==(1,''))
        pending=run_turn(window,[('refine_cues',{'from':1,'count':2})],dict(allowed,level='ask'))
        check('round4 paid trial waits for user confirmation',bool(pending.pending) and not getattr(page,'_refine_worker',None))
        page._learning_store=SimpleNamespace(load=lambda:{'candidates':[dict(status='pending',original_term='PRIVATE_SOURCE',corrected_term='PRIVATE_TARGET',occurrence_count=3)]})
        bunny_permissions.save(dict(allowed,read_subtitles=False))
        check('round4 disabled read excludes learned text from state','learned' not in snapshot(window))
        bunny_permissions.save(allowed)
        saved=run_turn(window,[('save_recipe',{'name':'验收配方'})],allowed)
        check('round4 recipe persisted locally',any(r['kind']=='recipe' and r['text']=='验收配方' for r in bunny_memory.load()))
        denied=run_turn(window,[('use_recipe',{'name':'验收配方'})],dict(allowed,remember=False))
        check('round4 disabled memory cannot read recipe','关掉了' in denied.receipts[0])
        for theme in ('sand','midnight'):
            card.close_chat();card=None;app.processEvents()
            request_theme(theme);QTest.qWait(300)
            card=bunny_chat.open_bunny_chat(window);card.reveal_all()
            card.say(BunnyReply(lines=['先检查字幕，再确认需要修改的地方。'],steps=('检查字幕','确认修改','检查结果'),step_now=1));card.reveal_all()
            for mode in ('dialog','thread'):
                old_frames=[card.thread.rows.itemAt(i).layout().itemAt(0).widget() for i in range(1,card.thread.rows.count())] if mode=='thread' else []
                card.set_mode(mode);card.reveal_all();card.refresh_suggestions();app.processEvents()
                check('round4 retired bubbles hidden '+theme+mode,all(f is None or not shiboken6.isValid(f) or f.isHidden() for f in old_frames))
                check('round4 steps and suggestions visible '+theme+mode,card.steps_label.isVisible() and card.suggest_row.isVisible())
                card.grab().save(str(output/('round4-'+theme+'-'+mode+'.png')))
        card.transcript.append(('user','ROUND4_CHAT_PRIVATE'));card._save_chat();key=card._chat_key
        check('round4 project chat actually persisted',any('ROUND4_CHAT_PRIVATE' in text for _,text in bunny_memory.load_chat(key)))
        bunny_memory.clear_chats();card._save_chat();card._sync_chat_context()
        check('round4 clear prevents open chat resurrection',not bunny_memory.load_chat(key) and not any('ROUND4_CHAT_PRIVATE' in m['content'] for m in card.messages_for('新问题')))
        card.close_chat();card=None;app.processEvents()
        # Capture the actual menu from its factory so another popup cannot consume the input.
        from ..studio import studio_ui
        from PySide6.QtCore import Qt
        original_factory = studio_ui.create_studio_menu
        chosen = []

        def capture_menu(*args, **kwargs):
            menu = original_factory(*args, **kwargs)
            timer = QTimer(menu)
            timer.setInterval(25)
            attempts = 0

            def choose():
                nonlocal attempts
                attempts += 1
                action = next((a for a in menu.actions() if a.text() == '问兔白这条'), None)
                if menu.isVisible() and action is not None:
                    timer.stop()
                    menu.setActiveAction(action)
                    QTest.keyClick(menu, Qt.Key_Return)
                    chosen.append(True)
                    if menu.isVisible():
                        menu.close()
                elif attempts >= 120:
                    timer.stop()
                    menu.close()

            timer.timeout.connect(choose)
            menu.aboutToShow.connect(timer.start)
            return menu

        studio_ui.create_studio_menu = capture_menu
        try:
            page._show_timeline_menu(page.project.cues[0].id, page.mapToGlobal(QPoint(300, 300)))
        finally:
            studio_ui.create_studio_menu = original_factory
        card=getattr(window,'_bunny_chat',None)
        check('round4 actual subtitle context menu opens populated chat',bool(chosen) and card is not None and '第 1 条' in card.input.text())
        card.grab().save(str(output/'round4-context.png'))
        check('round4 original project restored',[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]==before)
    finally:
        if card is not None:card.close_chat()
        bunny_chat.ai_readiness=ready;page._learning_store=store
        bunny_permissions.save(prior);bunny_memory._write(memory);bunny_memory.clear_chats()
        page.select_cue('a')
