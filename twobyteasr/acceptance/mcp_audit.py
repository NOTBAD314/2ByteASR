"""Real-window end-to-end check of local MCP access (2026-10-12).

Inside the running app (isolated data): MCP is off at start (nothing loaded,
no key); the real settings dialog turns it on; an official-SDK client
(scripts/mcp_client_flow.py) spawns the product's own stdio server and runs
discover → read → search → preview → apply. This audit plays the user on
the approval dialog (real mouse clicks), checks the change in Studio, lets the
client undo it, rejects a role regrouping, sees a stale plan refused after a
user edit, and revokes access from the settings dialog.

2026-10-17: the settings page refuses to write Claude Desktop's config while
Claude runs (played: the process check is machine-wide), reports an entry
Claude overwrote, writes Claude Code's user config in the isolated home; a
term-library plan is approved with a real click and the open term library
page shows the new rows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..local_mcp import mcp_common as common
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, approvals=[])
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')
    root = Path(spec['repo'])

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def server_command():
        if getattr(sys, 'frozen', False):
            return [sys.executable, '--mcp-stdio']
        return [str(root / '.venv-main/Scripts/python.exe'), '-B', str(root / 'quick_start.py'), '--mcp-stdio']

    def client(phase):
        env = {k: os.environ[k] for k in ('TWOBYTEASR_TEST_ROOT', '2BYTEASR_USER_DATA_ROOT', 'LOCALAPPDATA',
                                          'TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY') if k in os.environ}
        command = [str(root / '.venv-main/Scripts/python.exe'), '-X', 'utf8', str(root / 'scripts/mcp_client_flow.py'),
                   '--phase', phase, '--out', str(output), '--server-json', json.dumps(server_command()),
                   '--env-json', json.dumps(env)]
        event('client', phase=phase, server=server_command())
        stderr = (output / f'client-{phase}.stderr.txt').open('w', encoding='utf-8')
        return subprocess.Popen(command, cwd=str(root), stdout=subprocess.DEVNULL, stderr=stderr,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def dialogs():
        from ..local_mcp.mcp_approval import ApprovalDialog
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, ApprovalDialog) and w.isVisible()]

    def settings_dialog():
        from ..app.application_settings_ui import ApplicationSettingsDialog
        return next((w for w in QApplication.topLevelWidgets() if isinstance(w, ApplicationSettingsDialog) and w.isVisible()), None)

    def answer_question(name, yes=True, ok=False):
        """Click the real QMessageBox the next user step opens (consent / write confirmation;
        ``ok``: a warning that only has OK)."""
        from PySide6.QtWidgets import QMessageBox

        def run():
            box = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()), None)
            if box is None:
                QTimer.singleShot(150, run)
                return
            result.setdefault('questions', []).append(dict(name=name, title=box.windowTitle(), text=box.text()))
            box.grab().save(str(output / f'question-{name}.png'))
            button = box.button(QMessageBox.StandardButton.Ok if ok else
                                QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTimer.singleShot(300, run)

    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.03)

    claude_config = Path(os.environ.get('APPDATA', '')) / 'Claude' / 'claude_desktop_config.json'

    def drive_settings(action):
        def run():
            dialog = settings_dialog()
            if dialog is None:
                QTimer.singleShot(200, run)
                return
            items = dialog.navigation.findItems('外部 AI（MCP）', Qt.MatchFlag.MatchContains)
            if not items:
                items = [dialog.navigation.item(dialog.navigation.count() - 2)]
            dialog.navigation.setCurrentItem(items[0])
            QApplication.processEvents()
            if action == 'enable':
                dialog.grab().save(str(output / '01-settings-off.png'))
                answer_question('consent', yes=False)            # declining leaves access off
                QTest.mouseClick(dialog.mcp_enabled, Qt.MouseButton.LeftButton)
                result['declined_stays_off'] = not dialog.mcp_enabled.isChecked()
                answer_question('consent', yes=True)
                for box in (dialog.mcp_enabled, dialog.mcp_allow_edits, dialog.mcp_allow_export,
                            dialog.mcp_allow_glossary):
                    if not box.isChecked():
                        QTest.mouseClick(box, Qt.MouseButton.LeftButton)
                authorized = output / 'authorized folder 授权'
                authorized.mkdir(exist_ok=True)
                dialog.mcp_export_dir.setText(str(authorized))   # what the folder picker fills in
                QTest.mouseClick(dialog.mcp_copy, Qt.MouseButton.LeftButton)
                result['client_config'] = QApplication.clipboard().text()
                from PySide6.QtWidgets import QScrollArea
                scroll = dialog.mcp_status.parent()
                while scroll is not None and not isinstance(scroll, QScrollArea):
                    scroll = scroll.parent()
                # Claude Desktop config inside the isolated APPDATA: another server must survive.
                claude_config.parent.mkdir(parents=True, exist_ok=True)
                claude_config.write_text(json.dumps({'mcpServers': {'other': {'command': 'other.exe'}},
                                                     'preferences': {'keep': True}}), 'utf-8')
                # 2026-10-17: whether Claude Desktop runs is a machine-wide fact; record the real
                # answer, then play "Claude open" (refused) and "Claude quit" (written).
                from ..local_mcp import mcp_clients
                result['real_claude_desktop_started'] = mcp_clients.claude_desktop_started_at()
                mcp_clients.claude_desktop_started_at = lambda platform=None: time.time() - 600
                answer_question('claude-running', ok=True)
                QTest.mouseClick(dialog.mcp_write, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                result['while_running'] = dict(config=json.loads(claude_config.read_text('utf-8')),
                                               status=dialog.mcp_status.text())
                if scroll is not None:
                    scroll.ensureWidgetVisible(dialog.mcp_status)
                    QApplication.processEvents()
                dialog.grab().save(str(output / '02a-settings-claude-running.png'))
                mcp_clients.claude_desktop_started_at = lambda platform=None: 0.0
                answer_question('write-claude', yes=True)
                QTest.mouseClick(dialog.mcp_write, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                result['claude_written'] = json.loads(claude_config.read_text('utf-8'))
                result['claude_backups'] = sorted(p.name for p in claude_config.parent.glob('*2byteasr-backup*'))
                result['status_after_write'] = dialog.mcp_status.text()
                dialog.grab().save(str(output / '02-settings-on.png'))
                if scroll is not None:
                    scroll.ensureWidgetVisible(dialog.mcp_revoke)
                    QApplication.processEvents()
                    dialog.grab().save(str(output / '02b-settings-claude-written.png'))
                # Claude writes its in-memory settings back (what happened on 2026-10-16 23:22).
                claude_config.write_text(json.dumps({'mcpServers': {'other': {'command': 'other.exe'}},
                                                     'preferences': {'keep': True}}), 'utf-8')
                pump(1.5)                                        # the page re-reads every second
                result['status_overwritten'] = dialog.mcp_status.text()
                dialog.grab().save(str(output / '02c-settings-claude-overwritten.png'))
                answer_question('write-claude-again', yes=True)
                QTest.mouseClick(dialog.mcp_write, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                result['claude_rewritten'] = json.loads(claude_config.read_text('utf-8'))
                # Claude Code's user config in the isolated home.
                code_config = Path.home() / '.claude.json'
                isolated = Path(os.environ.get('TWOBYTEASR_TEST_ROOT') or '/nonexistent').resolve()
                if mcp_clients.claude_code_location().path != code_config or isolated not in code_config.resolve().parents:
                    raise RuntimeError(f'Claude Code config is not inside the isolated root: {code_config}')
                code_config.write_text(json.dumps({'numStartups': 3, 'projects': {}}), 'utf-8')
                dialog.mcp_client.setCurrentIndex(dialog.mcp_client.findData('claude_code'))
                QApplication.processEvents()
                answer_question('write-claude-code', yes=True)
                QTest.mouseClick(dialog.mcp_write, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                result['claude_code_written'] = json.loads(code_config.read_text('utf-8'))
                result['status_claude_code'] = dialog.mcp_status.text()
                result['steps_claude_code'] = dialog.mcp_steps.text()
                dialog.grab().save(str(output / '02d-settings-claude-code.png'))
                dialog.mcp_client.setCurrentIndex(dialog.mcp_client.findData('claude_desktop'))
                QApplication.processEvents()
                from PySide6.QtWidgets import QDialogButtonBox
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
            else:
                from PySide6.QtWidgets import QScrollArea
                scroll = dialog.mcp_status.parent()
                while scroll is not None and not isinstance(scroll, QScrollArea):
                    scroll = scroll.parent()
                if scroll is not None:
                    scroll.ensureWidgetVisible(dialog.mcp_revoke)
                QApplication.processEvents()
                result['status_before_revoke'] = dialog.mcp_status.text()
                dialog.grab().save(str(output / '07-settings-connected.png'))
                QTest.mouseClick(dialog.mcp_revoke, Qt.MouseButton.LeftButton)
                QApplication.processEvents()
                result['revoke_status'] = dialog.mcp_status.text()
                dialog.grab().save(str(output / '08-settings-revoked.png'))
                dialog.reject()
        QTimer.singleShot(600, run)

    def cue(cue_id):
        return next((c for c in page.project.cues if c.id == cue_id), None)

    def steps():
        from ..app.application_settings import open_application_settings
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='mcp_audit')
        yield ready
        yield 1.5
        check('MCP off at start: no bridge module, no key, no pipe', 'twobyteasr.local_mcp.mcp_bridge' not in sys.modules
              and not common.read_key() and not Path(common.pipe_path()).exists())
        drive_settings('enable')
        open_application_settings(page)          # the real dialog; driven above, Save clicked
        yield 1.0
        from ..local_mcp.mcp_bridge import _BRIDGE
        settings = common.read_settings()
        check('consent is asked first; declining keeps access off', result.get('declined_stays_off')
              and len(result.get('questions') or []) >= 2, result.get('questions'))
        check('settings dialog turns MCP on with edit/export permissions and one authorized folder',
              settings.get('enabled') and settings.get('allow_edits') and settings.get('allow_export')
              and settings.get('acknowledged') and settings.get('scope') == 'current'
              and settings.get('export_dir', '').endswith('authorized folder 授权')
              and _BRIDGE is not None and _BRIDGE.listening(), settings)
        config = json.loads(result.get('client_config') or '{}')
        check('copied client config runs the product with --mcp-stdio',
              (config.get('mcpServers', {}).get('2byteasr', {}).get('args') or [''])[-1] == '--mcp-stdio', config)
        written = result.get('claude_written') or {}
        check('Claude Desktop config: our entry added, other server and preferences kept, backup made',
              set(written.get('mcpServers', {})) == {'other', '2byteasr'} and written.get('preferences') == {'keep': True}
              and len(result.get('claude_backups') or []) == 1 and '已写入' in (result.get('status_after_write') or '')
              and '实际已连线' not in (result.get('status_after_write') or ''),
              dict(written=written, backups=result.get('claude_backups'), status=result.get('status_after_write')))
        running = result.get('while_running') or {}
        check('while Claude Desktop runs the write is refused with the reason, file unchanged',
              '2byteasr' not in (running.get('config') or {}).get('mcpServers', {'2byteasr': 1})
              and any(q['name'] == 'claude-running' and '正在运行' in q['text'] for q in result.get('questions') or [])
              and '正在运行' in (running.get('status') or ''), running)
        check('an entry Claude overwrote is reported as overwritten, and can be written again',
              '覆盖' in (result.get('status_overwritten') or '')
              and '2byteasr' in (result.get('claude_rewritten') or {}).get('mcpServers', {}),
              result.get('status_overwritten'))
        code_written = (result.get('claude_code_written') or {})
        check('Claude Code user config: entry added as stdio, other keys kept',
              (code_written.get('mcpServers') or {}).get('2byteasr', {}).get('type') == 'stdio'
              and code_written.get('numStartups') == 3 and 'Claude Code 配置：已写入' in (result.get('status_claude_code') or ''),
              dict(config=code_written, status=result.get('status_claude_code')))
        check('glossary permission saved from the settings page', settings.get('allow_glossary') is True, settings)
        before = {c.id: (c.text, c.start_ms, c.end_ms, c.speaker_id) for c in page.project.cues}
        # ---- full flow ----
        process = client('full')
        approvals = 0
        saw_change = False
        until = time.monotonic() + 300
        while process.poll() is None and time.monotonic() < until:
            for dialog in dialogs():
                text = dialog.details.toPlainText()
                approve = '整理轨道' not in text
                approvals += 1
                _capture(window, output / f'0{2 + approvals}-approval-{approvals}.png')
                dialog.grab().save(str(output / f'approval-{approvals}-dialog.png'))
                result['approvals'].append(dict(title=dialog.windowTitle(), approve=approve, text=text[:400]))
                button = dialog.approve_button if approve else dialog.reject_button
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            flag = output / 'client-applied.flag'
            if flag.exists() and not saw_change:
                changed = cue(flag.read_text('utf-8'))
                saw_change = changed is not None and changed.text.endswith('（MCP）')
                check('applied text is in the open Studio project', saw_change, changed.text if changed else None)
                check('one undo step named for the external AI', page.undo_stack.text(page.undo_stack.index() - 1).startswith('外部 AI'),
                      page.undo_stack.text(page.undo_stack.index() - 1))
                page.select_cue(changed.id)
                yield .8
                _capture(window, output / '05-applied-visible.png')
                (output / 'app-saw-change.flag').write_text('1', 'utf-8')
            styled_flag = output / 'client-styled.flag'
            if styled_flag.exists() and not (output / 'app-saw-style.flag').exists():
                from ..caption_style.bilingual_layout import project_display_cues
                from ..subtitle_rules.punctuation_style import project_mode
                shown = project_display_cues(page.project)
                manuscript = {c.id: c.text for c in page.project.cues}
                marks = set('，。、；：')  # never protected (decimals and URLs may keep '.' and ':')
                check('punctuation style from the client: display has no sentence marks, manuscript unchanged',
                      project_mode(page.project) == 'none' and all(not (set(c.text) & marks) for c in shown)
                      and {c.id: c.text for c in page.project.cues} == manuscript
                      and {k: v[0] for k, v in before.items()} == manuscript,
                      dict(mode=project_mode(page.project), sample=[c.text for c in shown[:3]]))
                yield .8
                _capture(window, output / '06-punctuation-none.png')
                (output / 'app-saw-style.flag').write_text('1', 'utf-8')
            yield .1
        full = json.loads((output / 'client-full.json').read_text('utf-8')) if (output / 'client-full.json').exists() else {}
        summary = full.get('summary') or {}
        result['client_full'] = summary
        check('official SDK client: discover/read/search/preview/apply/undo/export', summary.get('applied') == 'applied'
              and summary.get('undone') == 'undone' and summary.get('reuse_refused') and summary.get('bad_name_refused')
              and len(summary.get('export_files') or []) == 3, summary)
        check('rejected regrouping changed nothing', summary.get('rejected') == 'rejected'
              and 'speaker_roles' not in page.project.studio_state)
        check('search by speaker and time range with readable times', summary.get('speaker_matches')
              and summary.get('time_range_cues') and ':' in str(summary.get('readable_time') or ''), summary)
        check('batch replace and punctuation style: previewed, approved in the app, undone by the client',
              summary.get('replace_changes') == 1 and summary.get('replaced') == 'applied'
              and summary.get('replace_undone') == 'undone' and summary.get('styled') == 'applied'
              and summary.get('style_undone') == 'undone' and 'punctuation' not in page.project.studio_state, summary)
        after = {c.id: (c.text, c.start_ms, c.end_ms, c.speaker_id) for c in page.project.cues}
        check('after undo the project equals the start', after == before)
        exported = sorted(p.name for p in (Path(spec['project']).parent / common.EXPORT_FOLDER).glob('*'))
        formats = summary.get('format_files') or []
        check('exports landed in the project folder without overwriting', len(exported) == 3 + len(formats) == 6
              and any(name.endswith(' (2).srt') for name in exported), exported)
        check('this-export-only punctuation leaves the project style alone', summary.get('format_punctuation') == 'add'
              and 'punctuation' not in page.project.studio_state, summary.get('format_punctuation'))
        authorized = Path(common.read_settings().get('export_dir') or '')
        check('export into the one authorized folder', (authorized / 'to-folder.srt').is_file()
              and summary.get('authorized_files') == ['to-folder.srt'], sorted(p.name for p in authorized.glob('*')))
        check('no file escaped the project folder', not (Path(spec['project']).parent.parent / 'outside.ja.srt').exists())
        protocol = next((s for s in full.get('steps', []) if s['name'] == 'initialize'), {})
        result['protocol'] = protocol
        # ---- stale plan ----
        process = client('stale')
        yield lambda: (output / 'client-previewed.flag').exists() or process.poll() is not None
        target = page.project.cues[0]
        page.cue_controller.set_text(target.id, target.text + '·')          # the user's own edit
        (output / 'app-edited.flag').write_text('1', 'utf-8')
        yield lambda: process.poll() is not None
        stale = json.loads((output / 'client-stale.json').read_text('utf-8')).get('summary') or {}
        check('a plan previewed before a user edit is refused as stale', stale.get('stale_refused') and not dialogs(), stale)
        page.undo_stack.undo()
        yield .5
        # ---- switching projects between preview and apply ----
        from ..app.sample_project import ensure_sample_project
        sample = ensure_sample_project()
        process = client('switch')
        yield lambda: (output / 'client-switch-previewed.flag').exists() or process.poll() is not None
        original_id = page.project.project_id
        page.session.undo_stack.setClean()                   # the start state; nothing to save
        window.open_studio_project(str(sample), mode='edit', source='mcp_audit')
        yield lambda: ready() and page.project.project_id != original_id
        yield .8
        _capture(window, output / '06b-switched-project.png')
        sample_texts = [c.text for c in page.project.cues]
        (output / 'app-switched.flag').write_text('1', 'utf-8')
        yield lambda: process.poll() is not None
        switched = json.loads((output / 'client-switch.json').read_text('utf-8')).get('summary') or {}
        check('a plan for the previous project is refused after switching', switched.get('switch_refused')
              and not dialogs() and [c.text for c in page.project.cues] == sample_texts, switched)
        # ---- term libraries (2026-10-17): approval in the app, the open library page refreshes ----
        legacy = window.legacy
        legacy.add_learned_mapping('MCP 验收词库', '洛克', '洛克', category='角色', origin='手动')
        library_id = legacy.resolve_glossary_identity('MCP 验收词库')
        window._manage_terms()
        yield lambda: window.term_library_page.library is not None
        terms_page = window.term_library_page.library
        yield lambda: any(terms_page.game_list.item(i).data(Qt.ItemDataRole.UserRole + 1) == library_id
                          for i in range(terms_page.game_list.count()))
        item = next(terms_page.game_list.item(i) for i in range(terms_page.game_list.count())
                    if terms_page.game_list.item(i).data(Qt.ItemDataRole.UserRole + 1) == library_id)
        terms_page.game_list.scrollToItem(item)
        QTest.mouseClick(terms_page.game_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=terms_page.game_list.visualItemRect(item).center())
        yield 1.0

        def shown_pairs():
            model = getattr(terms_page, '_term_model', None)
            rows = [model.data_for_row(i) for i in range(model.rowCount())] if model is not None else []
            return {(r.get('source'), r.get('target')) for r in rows if r}
        result['library_rows_before'] = sorted(map(list, shown_pairs()))
        _capture(window, output / '06c-term-library-before.png')
        process = client('glossary')
        until = time.monotonic() + 180
        while process.poll() is None and time.monotonic() < until:
            for dialog in dialogs():
                _capture(window, output / '06d-glossary-approval.png')
                dialog.grab().save(str(output / 'glossary-approval-dialog.png'))
                result['glossary_approval'] = dict(title=dialog.windowTitle(), text=dialog.details.toPlainText()[:1200],
                                                   button=dialog.approve_button.text())
                QTest.mouseClick(dialog.approve_button, Qt.MouseButton.LeftButton)
            yield .1
        yield 1.0
        glossary = json.loads((output / 'client-glossary.json').read_text('utf-8')).get('summary') or {}
        result['client_glossary'] = glossary
        stored = {(r['from'], r['to']): r for r in legacy.learned_mappings_for_game(library_id)}
        result['library_rows_after'] = sorted(map(list, shown_pairs()))
        _capture(window, output / '06e-term-library-after.png')
        approval = result.get('glossary_approval') or {}
        check('glossary tools: list, search, preview changes nothing, approval saves, undo_plan refused',
              glossary.get('listed') and glossary.get('found') == 1 and glossary.get('unchanged_after_preview')
              and glossary.get('applied') == 'applied' and glossary.get('undo_refused'), glossary)
        check('glossary approval dialog: plain text, alias warning, "approve and save"',
              approval.get('title') == '外部 AI 请求修改术语库' and '替换' in approval.get('text', '')
              and '<b>' in approval.get('text', '') and approval.get('button') == '批准并保存', approval)
        check('approved rows are in the library file (origin 外部 AI)', stored.get(('落克', '洛克'), {}).get('origin') == '外部 AI'
              and ('兔白字幕 <b>测试</b>', '兔白字幕 <b>测试</b>') in stored, sorted(stored))
        check('the open term library page shows the new rows without reopening',
              {('落克', '洛克')} <= shown_pairs() and ('落克', '洛克') not in set(map(tuple, result['library_rows_before'])),
              result['library_rows_after'])
        # ---- revoke ----
        drive_settings('revoke')
        open_application_settings(page)
        yield .5
        check('settings status said "actually connected" with the client name before revoking',
              '实际已连线' in (result.get('status_before_revoke') or '') and bool(_BRIDGE.stats.get('client')),
              dict(status=result.get('status_before_revoke'), client=_BRIDGE.stats.get('client')))
        check('revoke turns access off and deletes the key', not common.read_settings()['enabled']
              and not common.read_key() and not _BRIDGE.listening(), result.get('revoke_status'))
        process = client('revoked')
        yield lambda: process.poll() is not None
        revoked = json.loads((output / 'client-revoked.json').read_text('utf-8')).get('summary') or {}
        check('after revoke the client is refused', revoked.get('refused'), revoked)
        _capture(window, output / '09-final.png')
        result['passed'] = all(c['passed'] for c in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        save()
        log.close()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
        if state.get('ticking'):
            return
        state['ticking'] = True
        try:
            if state['wait'] is not None:
                if state['wait']():
                    state['wait'] = None
                elif time.monotonic() > state['deadline']:
                    raise TimeoutError('Real GUI condition did not settle')
                else:
                    return
            if time.monotonic() < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 240)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                _capture(window, output / 'failure.png')
            except Exception:
                pass
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
