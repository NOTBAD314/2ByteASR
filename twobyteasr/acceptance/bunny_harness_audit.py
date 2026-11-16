"""Host intake checks, real windows and isolated files, offline providers only."""
import json
import time


def run(window, studio, output, check):
    from PySide6.QtCore import Qt, QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication, QFileDialog, QScrollArea
    from PySide6.QtTest import QTest
    from ..app import bunny_chat, bunny_permissions, bunny_memory
    from ..app.bunny_tools import run_turn, undo_records, edit_context
    from ..app.application_settings_ui import ApplicationSettingsDialog
    from ..providers import ai_providers, deepseek_tools
    from ..design.theme_manager import request_theme
    from ..glossary import term_import_ai
    from ..app import bunny_harness_tools as harness
    app = QApplication.instance()
    legacy = window.legacy
    prior = bunny_permissions.load()
    ready, provider = bunny_chat.ai_readiness, ai_providers.provider_for_stage
    search = harness._deepseek_key
    web_search, web_fetch = deepseek_tools.search, deepseek_tools.fetch
    tidy = term_import_ai.tidy_terms
    pick = QFileDialog.getExistingDirectory
    file_pick = QFileDialog.getOpenFileName
    folder = output / 'allowed'
    folder.mkdir()
    (folder / 'terms.csv').write_bytes('名称,类别,错词\n星见雅,角色,星见鸦\n'.encode('gbk'))
    identity = legacy.create_learned_content('主机验收词库', create_new=True)
    legacy.add_learned_mapping(identity, '打', '大', category='其他')
    card = dialog = None
    def wait(predicate):
        end = time.monotonic() + 20
        while not predicate() and time.monotonic() < end:
            app.processEvents(); time.sleep(.005)
        check('harness bounded worker completed', predicate())
    def rows():
        return {(r['from'], r['to']) for r in legacy.learned_mappings_for_game(identity)}
    try:
        bunny_permissions.save(dict(prior, **{'level': 'ask', 'folders': []}))
        dialog = ApplicationSettingsDialog(window, {}, output/'projects', browse=lambda *a: None,
                                          clear_recent=lambda: None, reset_layout=lambda: None)
        labels = [dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
        dialog.navigation.setCurrentRow(labels.index('兔白权限'))
        dialog.resize(940, 720); dialog.show(); app.processEvents()
        QFileDialog.getExistingDirectory = lambda *a, **kw: str(folder)
        dialog.bunny_folder_add.click(); app.processEvents()
        check('harness real add-folder persists', bunny_permissions.load()['folders'] == [str(folder)])
        dialog.bunny_folder_list.scrollToBottom()
        dialog.bunny_folder_list.setCurrentRow(0)
        dialog.bunny_folder_remove.click(); app.processEvents()
        check('harness real remove-folder persists', not bunny_permissions.load()['folders'])
        dialog.bunny_folder_add.click()
        dialog.bunny_folder_list.setFocus()
        for scroll in dialog.findChildren(QScrollArea):
            if scroll.widget() is not None and scroll.widget().isAncestorOf(dialog.bunny_folder_list):
                scroll.ensureWidgetVisible(dialog.bunny_folder_add)
        QTest.qWait(250)
        check('harness folder controls actually visible', not dialog.bunny_folder_list.visibleRegion().isEmpty()
              and not dialog.bunny_folder_add.visibleRegion().isEmpty())
        dialog.grab().save(str(output/'harness-folders.png'))
        dialog.close(); dialog = None
        denied = run_turn(window, [('read_file', {'path': '../outside.txt'})], bunny_permissions.load())
        check('harness outside folder refused', '没做成' in denied.receipts[0])
        pending = run_turn(window, [('import_terms_file', {'path':'terms.csv','library':identity})], bunny_permissions.load())
        check('harness file import awaits click', bool(pending.pending) and ('星见鸦','星见雅') not in rows())
        done = run_turn(window, pending.pending, bunny_permissions.load(), confirmed=True)
        check('harness confirmed file import writes aliases', ('星见鸦','星见雅') in rows())
        check('harness term import undo restores', undo_records(done.undo) == (1,'') and ('星见鸦','星见雅') not in rows())
        bunny_chat.ai_readiness = lambda settings: (True, 'Offline host audit')
        answers = []
        harness._deepseek_key = lambda settings: 'offline-host-key'
        deepseek_tools.search = lambda *a, **kw: [dict(title='离线验收资料',url='https://example.com/a',
            summary='仅验证后台工具流程',snippet='')]
        deepseek_tools.fetch = lambda *a, **kw: dict(title='离线验收资料',content='离线后台读取结果')
        class Provider:
            def complete(self, messages, **kwargs):
                return json.dumps(answers.pop(0), ensure_ascii=False)
        ai_providers.provider_for_stage = lambda *a, **kw: Provider()
        for theme in ('sand', 'midnight'):
            request_theme(theme); QTest.qWait(200)
            card = bunny_chat.open_bunny_chat(window); card.set_mode('thread')
            answers.extend([{'lines':['先体检词库'], 'tools':[{'name':'start_task','args':{'goal':'体检词库','steps':['检查','提出修改']}},
                {'name':'web_search','args':{'query':'离线验收词条'}},
                {'name':'read_page','args':{'url':'https://example.com/a'}},
                {'name':'change_terms','args':{'library':identity,'changes':[{'to':'朱鸢'}]}}]},
                {'lines':['请确认新增朱鸢']}])
            card.input.setText('体检词库并加朱鸢'); card.send(); wait(lambda:not card.busy)
            card.reveal_all(); app.processEvents()
            check('harness task mode has twenty rounds '+theme, card._round_limit() == 20)
            check('harness background web tools complete '+theme, card._web_calls == 2)
            check('harness chat awaits visible confirmation '+theme, card.do_button.isVisible() and ('朱鸢','朱鸢') not in rows())
            check('harness approval names library and exact change '+theme, '主机验收词库' in card.do_button.text()
                  and 'library:' not in card.do_button.text() and '朱鸢' in card.do_button.toolTip())
            card.grab().save(str(output/('harness-confirm-'+theme+'.png')))
            if theme == 'sand':
                legacy.add_learned_mapping(identity, '后续手工', '后续手工')
                card.do_button.click(); card.reveal_all()
                check('harness stale term confirmation refused', ('朱鸢','朱鸢') not in rows() and '已经变了' in ''.join(card.last_reply_html()))
            else:
                card.do_button.click(); card.reveal_all(); app.processEvents()
                check('harness actual click changes terms', ('朱鸢','朱鸢') in rows())
                card.undo_button.click(); card.reveal_all()
                check('harness actual undo restores terms', ('朱鸢','朱鸢') not in rows())
            key = card._chat_key
            bunny_memory.save_chat('other-harness-project', [('user','OTHER_PROJECT_SENTINEL')])
            card.transcript.append(('user','OLD_HARNESS_CHAT')); card._save_chat()
            card.new_button.click(); card.reveal_all(); app.processEvents()
            check('harness new conversation clears current context '+theme,
                  not bunny_memory.load_chat(key) and 'OLD_HARNESS_CHAT' not in str(card.messages_for('继续')))
            check('harness new conversation preserves other project '+theme, bool(bunny_memory.load_chat('other-harness-project')))
            card.grab().save(str(output/('harness-new-'+theme+'.png')))
            card.close_chat(); card = None
        window._manage_terms(); QTest.qWait(400)
        page = window.term_library_page._ensure_library()
        item = next(page.game_list.item(i) for i in range(page.game_list.count())
                    if page.game_list.item(i).data(257) == identity or page.game_list.item(i).data(256) == '主机验收词库')
        page.game_list.setCurrentItem(item); QTest.qWait(100)
        page.show_import_dialog()
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(folder/'terms.csv'), '')
        page.import_sources.pick.click(); app.processEvents()
        check('harness file-picker GBK preview', any(r['to']=='星见雅' for r in page._import_rows))
        page._import_sheet.grab().save(str(output/'harness-import-gbk.png'))
        (folder/'utf16.tsv').write_text('术语\t分类\n派蒙\t角色\n', encoding='utf-16')
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(folder/'utf16.tsv'))])
        drop = QDropEvent(QPointF(20,20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        page.import_editor.dropEvent(drop); app.processEvents()
        check('harness UTF16 drop preview', any(r['to']=='派蒙' for r in page._import_rows))
        multi = {'games': {'a':{'game':'主机验收词库','mappings':[{'from':'艾莲','to':'艾莲'}]},
                           'b':{'game':'其他游戏','mappings':[{'from':'错误游戏','to':'错误游戏'}]}}}
        page.import_editor.setPlainText(json.dumps(multi, ensure_ascii=False)); app.processEvents()
        check('harness multi-game imports chosen game only', page.import_sources.games.isVisible() and
              any(r['to']=='艾莲' for r in page._import_rows) and all(r['to']!='错误游戏' for r in page._import_rows))
        check('harness actual import saves chosen game', page._import_submit() and ('艾莲','艾莲') in rows() and ('错误游戏','错误游戏') not in rows())
        page.show_import_dialog()
        class TidyProvider:
            def structured_complete(self, messages, schema, **kw):
                return {'terms':[{'term':'派蒙','category':'角色'}, {'term':'凭空编造','category':'角色'}]}
        term_import_ai.tidy_terms = lambda text, game, settings, **kw: tidy(text, game, settings, provider=TidyProvider(), **kw)
        old_settings, old_key = page._ai_update_settings, page._ai_update_needs_key
        page._ai_update_settings = lambda: {}
        page._ai_update_needs_key = lambda settings: False
        try:
            page.import_editor.setPlainText('派蒙是角色。')
            page.import_sources.tidy.click()
            wait(lambda:page.import_sources.tidy.isEnabled())
            app.processEvents()
            check('harness AI tidy preview rejects invented terms', any(r['to']=='派蒙' for r in page._import_rows)
                  and all(r['to']!='凭空编造' for r in page._import_rows) and ('派蒙','派蒙') not in rows())
            page._import_sheet.grab().save(str(output/'harness-ai-tidy.png'))
            page._import_submit()
            check('harness AI tidy writes only after import', ('派蒙','派蒙') in rows())
        finally:
            page._ai_update_settings, page._ai_update_needs_key = old_settings, old_key
        window._switch_page(studio)
    finally:
        if card is not None: card.close_chat()
        if dialog is not None: dialog.close()
        if getattr(locals().get('page'), '_import_cleanup', None): page._import_cleanup()
        QFileDialog.getExistingDirectory = pick
        QFileDialog.getOpenFileName = file_pick
        bunny_chat.ai_readiness, ai_providers.provider_for_stage = ready, provider
        harness._deepseek_key = search
        deepseek_tools.search, deepseek_tools.fetch = web_search, web_fetch
        term_import_ai.tidy_terms = tidy
        bunny_permissions.save(prior)
        window._switch_page(studio)
