"""Offline agent controls through the normal MainWindow and real Studio commands."""
import json
import time


def run(window, page, output, check):
    from PySide6.QtWidgets import QApplication
    from ..app import bunny_chat, bunny_permissions, bunny_lookup, bunny_memory
    from ..app.bunny_tools import run_turn, undo_records, edit_context
    from ..app.application_settings_ui import ApplicationSettingsDialog
    from ..providers import ai_providers
    app = QApplication.instance()
    def wait(predicate):
        deadline = time.monotonic() + 20
        while not predicate() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        check('agent bounded request completed', predicate())
    original_ready, original_provider = bunny_chat.ai_readiness, ai_providers.provider_for_stage
    original_lookup = bunny_lookup.run_check
    prior_permissions = bunny_permissions.load()
    prior_memory = bunny_memory.load()
    card = None
    try:
        bunny_permissions.save(dict(bunny_permissions.DEFAULTS))
        bunny_memory.clear()
        allowed = dict(bunny_permissions.DEFAULTS)
        remembered = run_turn(window, [('remember', {'text':'习惯使用黄色描边'})], allowed)
        check('memory persists through tool', '成功' in remembered.receipts[0] and len(bunny_memory.load()) == 1)
        item = bunny_memory.load()[0]
        denied_memory = run_turn(window, [('forget', {'id':item['id']})], dict(allowed, level='guide'))
        check('guide cannot erase memory', '只指路' in denied_memory.receipts[0] and bunny_memory.load() == [item])
        denied_memory = run_turn(window, [('remember', {'text':'禁止记忆'})], dict(allowed, remember=False))
        check('memory off prevents writes', '没做成' in denied_memory.receipts[0] and bunny_memory.load() == [item])
        from ..app.bunny_persona import system_prompt
        from ..app.bunny_lore import feature_index
        check('memory included when enabled', '习惯使用黄色描边' in system_prompt(feature_index()))
        bunny_permissions.save(dict(allowed, remember=False))
        check('memory off excludes prompt', '习惯使用黄色描边' not in system_prompt(feature_index()))
        bunny_permissions.save(allowed)
        for level, paid in [('ask', True), ('auto', False)]:
            result = run_turn(window, [('ai_refine', {'scope':'failed'})], dict(allowed, level=level, allow_paid=paid))
            check('paid processing awaits confirmation '+level, bool(result.pending) and not getattr(page, '_refine_worker', None))
        page.select_cue(page.project.cues[0].id)
        starts = [c.start_ms for c in page.project.cues]
        changed = run_turn(window, [('shift_timing', {'scope':'all','ms':250}),
                                   ('apply_style', {'scope':'all','fill_color':'#FFD400'})],
                           dict(prior_permissions, level='auto'))
        check('agent real timing and style commands succeed', len(changed.undo)==2 and all('成功' in r for r in changed.receipts))
        check('agent timing reaches real project', [c.start_ms for c in page.project.cues] == [s+250 for s in starts])
        count, reason = undo_records(changed.undo)
        check('agent batch undo restores project', count==2 and not reason and [c.start_ms for c in page.project.cues]==starts)
        changed = run_turn(window, [('shift_timing', {'scope':'all','ms':250})])
        page.undo_stack.undo()
        page.cue_controller.apply_timing_offset([page.project.cues[0].id], 100)
        user_starts = [c.start_ms for c in page.project.cues]
        count, reason = undo_records(changed.undo)
        check('agent undo preserves replaced history at same index', count==0 and bool(reason) and [c.start_ms for c in page.project.cues]==user_starts)
        page.undo_stack.undo()
        guide=dict(level='guide',read_subtitles=False,read_diagnostics=False)
        denied=run_turn(window,[('seek',{'time':1}),('read_cues',{}),('shift_timing',{'ms':200})],guide)
        check('agent guide and subtitle permissions deny calls', len(denied.receipts)==3 and all('没做成' in r for r in denied.receipts))
        bunny_chat.ai_readiness=lambda settings:(True,'Offline audit')
        answers=[]; sent=[]
        class Provider:
            def complete(self,messages,**kwargs):
                sent.append(messages)
                return json.dumps(answers.pop(0),ensure_ascii=False)
        ai_providers.provider_for_stage=lambda *a,**kw:Provider()
        card=bunny_chat.open_bunny_chat(window)
        card.set_mode('thread');card.reveal_all()
        check('thinking button names current level', bool(card.reasoning_button.text()))
        def ask_edit():
            answers.extend([{'lines':['准备修改'],'tools':[{'name':'shift_timing','args':{'scope':'all','ms':200}}]},
                            {'lines':['请按帮我做确认']}])
            card.input.setText('把全部字幕推后 0.2 秒');card.send()
            wait(lambda:not card.busy);card.reveal_all();app.processEvents()
        ask_edit()
        check('agent chat asks before edits', card.do_button.isVisible() and [c.start_ms for c in page.project.cues]==starts)
        check('agent explanation agrees with real confirmation button', '没法直接帮你按' not in ''.join(card.last_reply_html()))
        card.grab().save(str(output/'agent-confirm.png'))
        card.do_button.click();card.reveal_all();app.processEvents()
        check('agent confirmation applies exact shift', [c.start_ms for c in page.project.cues]==[s+200 for s in starts])
        check('agent undo button is visible', card.undo_button.isVisible())
        card.grab().save(str(output/'agent-undo.png'))
        card.undo_button.click();card.reveal_all()
        check('agent chat undo restores exact timestamps', [c.start_ms for c in page.project.cues]==starts)
        ask_edit()
        page.select_cue(page.project.cues[-1].id);app.processEvents()
        card.do_button.click();card.reveal_all()
        check('agent stale confirmation refuses changed selection', [c.start_ms for c in page.project.cues]==starts and '已经变了' in ''.join(card.last_reply_html()))
        bunny_permissions.save(guide)
        looked=[]
        bunny_lookup.run_check=lambda *a,**kw:looked.append(a) or 'forbidden diagnostic content'
        answers.extend([{'lines':['查一下'],'check':'diagnostics'}, {'lines':['权限关闭，没有读取']}])
        card.input.setText('查诊断');card.send();wait(lambda:not card.busy);card.reveal_all()
        check('agent legacy diagnostic request obeys permission', not looked and any(
            '没有读取' in m['content'] or '关掉了' in m['content'] for m in sent[-1]))
        bunny_permissions.save(dict(allowed, remember=False))
        card._history.append({'role':'user','content':'MEMORY_PRIVATE_SENTINEL'})
        answers.append({'lines':['记忆已关闭']})
        card.input.setText('再回答一次');card.send();wait(lambda:not card.busy);card.reveal_all()
        check('memory off omits prior chat receipts', not any('MEMORY_PRIVATE_SENTINEL' in m['content'] for m in sent[-1]))
        card.close_chat();card=None;app.processEvents()
        dialog=ApplicationSettingsDialog(window,{},output/'agent-projects',browse=lambda *a:None,
                                         clear_recent=lambda:None,reset_layout=lambda:None)
        try:
            labels=[dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
            dialog.navigation.setCurrentRow(labels.index('兔白权限'));dialog.resize(940,720);dialog.show();app.processEvents()
            check('agent permissions page renders', dialog.bunny_level.isVisible() or not dialog.bunny_read_subtitles.isHidden())
            check('memory list shows saved preference', dialog.bunny_memory_list.count() == 1 and '黄色描边' in dialog.bunny_memory_list.item(0).text())
            dialog.bunny_teach.setPlainText('频道称呼：小明')
            dialog.bunny_memory_add.click()
            check('knowledge base saves through real button', any(r['kind']=='knowledge' for r in bunny_memory.load()))
            from ..design.theme_manager import request_theme
            from PySide6.QtTest import QTest
            for theme in ('sand','midnight'):
                request_theme(theme);QTest.qWait(350)
                from ..design.studio_theme import refresh_secondary_surface_theme
                refresh_secondary_surface_theme(dialog);app.processEvents()
                dialog.grab().save(str(output/('agent-memory-'+theme+'.png')))
            dialog.grab().save(str(output/'agent-permissions.png'))
            dialog.bunny_level.setCurrentIndex(dialog.bunny_level.findData('auto'))
            dialog.bunny_read_subtitles.setChecked(False)
            dialog._save_bunny_permissions()
            saved=bunny_permissions.load()
            check('agent permission choices save and read back', saved['level']=='auto' and not saved['read_subtitles'])
            dialog._input_baseline=dict(dialog._input_values())
        finally:
            dialog.reject();dialog.deleteLater();app.processEvents()
    finally:
        if card is not None:card.close_chat()
        bunny_chat.ai_readiness=original_ready
        ai_providers.provider_for_stage=original_provider
        bunny_lookup.run_check=original_lookup
        bunny_permissions.save(prior_permissions)
        bunny_memory._write(prior_memory)
        page.select_cue('a')
