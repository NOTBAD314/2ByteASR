"""Real-window check of onboarding, punctuation, the Qwen Cloud guide and shortcuts (2026-10-13).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=onboarding-settings`` (isolated
data, offline guards, DNS refused for remote hosts). The phase comes from
``TWOBYTEASR_ONBOARDING_PHASE``:

* ``fresh``    a new data folder: no dialog at startup, the home card, the
  example project, the plan step after choosing media, dismiss and reopen from
  “说明”, feature search, the Qwen Cloud guide checks (offline), punctuation
  styles with export comparison and the permanent write, shortcut recording with
  a conflict, immediate effect, typing safety, Q in one native key press, and
  the diagnostics text;
* ``restart``  the same data folder again: the saved shortcut and onboarding
  stamp are kept and the new key works at once;
* ``upgraded`` older settings with a recent project, opened like a
  double-clicked project file: Studio directly, no home card, old keys migrated.

Writes ``result-<phase>.json`` and captures into ``<output>/<phase>/``.
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from pathlib import Path

PUNCTUATION_LINES = (
    '大家好 今天我们来玩 S0pp 的新版本 v1.2.3',
    '胜率提升到 98.5% 了 真的吗',
    "It's 12:30 now see you at the U.S. server",
    '我们去 bilibili.com 看看 好不好',
    'Zhe 和 CHIOCHOO 一起上 一个人守家',
    '温度是 -3 度 记得穿外套',
)


def _offline_dns() -> None:
    import socket
    original = socket.getaddrinfo

    def local_only(host, *args, **kwargs):
        if str(host) not in {'127.0.0.1', '::1', 'localhost', ''} and not str(host).startswith('\\\\.'):
            raise socket.gaierror(socket.EAI_NONAME, 'external name lookup disabled in this acceptance run')
        return original(host, *args, **kwargs)
    socket.getaddrinfo = local_only


def start(window, output: Path):
    from PySide6.QtCore import QRectF, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    _offline_dns()
    phase = os.environ.get('TWOBYTEASR_ONBOARDING_PHASE', 'fresh')
    folder = output / phase
    folder.mkdir(parents=True, exist_ok=True)
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(phase=phase, checks=[], identity=load_build_identity().to_dict(), passed=False)
    log = (folder / 'operations.jsonl').open('w', encoding='utf-8')
    page_holder = {}

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def capture(name):
        try:
            _capture(window, folder / f'{name}.png')
        except Exception as exc:  # noqa: BLE001 - a missing picture is reported, not fatal
            event('capture_failed', name=name, error=str(exc))

    def grab(widget, name):
        widget.grab().save(str(folder / f'{name}.png'))

    def studio():
        return window.built_page('studio') if hasattr(window, 'built_page') else None

    def ready():
        page = studio()
        return page is not None and page.project is not None and page._readiness.ready and not page._readiness.active

    def on_modal(kind, act, name, timeout=20.0):
        """Act on the next visible modal of ``kind`` (exec() blocks the step runner)."""
        deadline = time.monotonic() + timeout

        def run():
            found = next((w for w in QApplication.topLevelWidgets()
                          if isinstance(w, kind) and w.isVisible() and w is not window), None)
            if found is None:
                if time.monotonic() < deadline:
                    QTimer.singleShot(120, run)
                else:
                    event('modal_missing', name=name)
                return
            try:
                act(found)
            except Exception:  # noqa: BLE001
                result.setdefault('modal_errors', []).append(dict(name=name, error=traceback.format_exc()[-1500:]))
                try:
                    found.close()
                except Exception:
                    pass
        QTimer.singleShot(250, run)

    def visible_dialogs():
        return [type(w).__name__ + ':' + (w.objectName() or w.windowTitle())
                for w in QApplication.topLevelWidgets()
                if w.isVisible() and w is not window and isinstance(w, (QDialog, QMessageBox))]

    def post_key(vk):
        """One real Win32 key press to the main window (native filter + Qt, as the keyboard does)."""
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        scan = user32.MapVirtualKeyW(vk, 0)
        user32.PostMessageW(hwnd, 0x0100, vk, 1 | (scan << 16))
        user32.PostMessageW(hwnd, 0x0101, vk, 1 | (scan << 16) | (1 << 30) | (1 << 31))

    # ------------------------------------------------------------ fresh
    def fresh():
        from . import onboarding
        from .i18n import tr
        from .quick_setup import QuickSetupDialog
        quick = {}

        def first_run(dialog):
            # Let the background GPU check finish, then look like a user who decides later.
            def decide():
                quick['cards'] = list(dialog.cards)
                quick['selected'] = dialog.choice
                quick['status'] = {k: (c.status.text(), c.isEnabled()) for k, c in dialog.cards.items()}
                quick['go'] = dialog.go_button.text()
                grab(dialog, 'A0-quick-setup')
                QTest.mouseClick(dialog.later_button, Qt.MouseButton.LeftButton)
            QTimer.singleShot(3000, decide)
        on_modal(QuickSetupDialog, first_run, 'quick-setup', timeout=15)
        window.showMaximized()
        yield lambda: 'cards' in quick
        yield 1.0
        check('first launch offers the quick chooser once: cards for this computer, nothing downloaded',
              quick.get('cards') == ['local', 'cloud', 'light'] and onboarding.load_state().get('setup_offered') is True,
              quick)
        check('after "稍后再说" no other dialog is open', not visible_dialogs(), visible_dialogs())
        # The tutorial follows once: demo video, language, the three cards, AI key, glossary,
        # a pretend result, proofreading step by step, export, the workbench (edit, review,
        # speakers, batch replace, timeline, punctuation, export). Interactive steps are done
        # with "帮我做", which drives the same page methods a click or key would.
        from .home_tour import GuidedTour
        yield lambda: window.findChild(GuidedTour) is not None and window.findChild(GuidedTour).isVisible()
        tour = window.findChild(GuidedTour)
        seen = []
        ai_suggested = False
        bubble_beside = []
        review_cards = []
        for _ in range(60):
            yield lambda: window.findChild(GuidedTour) is None or tour.bubble.isVisible()
            if window.findChild(GuidedTour) is None:
                break
            yield 0.7  # the outline glides to the next part
            page = window.pages.currentWidget()
            part = tour._target(tour.index)
            seen.append(dict(index=tour.index, page=page.objectName() if page is not None else '',
                             text=tour.text.text()[:80], hole=[round(v) for v in tour.hole.getRect()],
                             part=[round(v) for v in tour._rect_of(part).getRect()] if part is not None else None,
                             fits=tour.bubble.height() >= tour.bubble.sizeHint().height(),
                             anim=tour.anim.name if tour.anim.isVisible() else '', expect_anim=bool(tour.steps[tour.index].anim),
                             interactive=tour.steps[tour.index].interactive))
            studio_page = window.built_page('studio') if hasattr(window, 'built_page') else None
            if tour.steps[tour.index].anim == 'review' and getattr(studio_page, '_review_mode', False):
                review_cards.append(len(getattr(studio_page, '_review_candidates', None) or ()))
            proof = window.__dict__.get('glossary_proofread_page')
            ai_suggested = ai_suggested or any(issue.get('kind') == 'ai' for row in (getattr(proof, '_by_id', None) or {}).values()
                                               for issue in row.get('issues') or ())
            if part is not None and tour.pointer is not None:
                bubble_beside.append(not QRectF(tour.bubble.geometry()).intersects(tour.hole))
            capture(f'T{tour.index + 1:02d}-tutorial')
            # Do what the step offers: an advancing action (demo video, pretend result), "帮我做" on an
            # interactive step (the step then moves on by itself once it sees the result), else 下一步.
            step = tour.steps[tour.index]
            moving = next((i for i, a in enumerate(step.actions) if a.advance), None)
            if moving is not None:
                button = tour.action_buttons[moving]
            elif step.interactive and tour.action_buttons:
                button = tour.action_buttons[0]
            else:
                button = tour.next
            before = tour.index
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            if step.interactive:
                yield lambda: window.findChild(GuidedTour) is None or tour.index != before
        yield lambda: window.findChild(GuidedTour) is None
        yield 1.0
        state = onboarding.load_state()
        total = len(tour.steps)
        check(f'first launch: the tutorial walks all {total} steps with demo data, then closes',
              total >= 30 and [s['index'] for s in seen] == list(range(total)) and state.get('tour_done') is True, seen)
        check('tutorial: every step that shows a tool or gesture plays its animation',
              sum(1 for s in seen if s['expect_anim']) >= 20 and all(s['anim'] for s in seen if s['expect_anim']),
              [(s['index'], s['anim']) for s in seen if s['expect_anim']])
        check('tutorial: bubbles sit beside their target with a pointer, not on top of it',
              len(bubble_beside) >= 20 and all(bubble_beside), bubble_beside)
        check('tutorial: review mode opens on the line where the three recognizers disagree (keys 1/2/3)',
              review_cards and review_cards[0] == 3, review_cards)
        from .sample_project import tutorial_project_path
        from .studio_project import load_project as _load
        proof = window.__dict__.get('glossary_proofread_page')
        fixed_text = next((cue.text for cue in _load(tutorial_project_path()).cues if cue.id == 'tutorial-2'), '')
        check('tutorial: 原神 ticked, the offline "AI 校对" added its suggestions, 至东 was fixed and saved; '
              'the stand-in is gone afterwards',
              ai_suggested and '至冬' in fixed_text and getattr(proof, 'ai_stand_in', 'x') is None,
              dict(ai=ai_suggested, text=fixed_text))
        check('tutorial: every bubble is tall enough for its text and buttons (nothing hidden)',
              all(s['fits'] for s in seen), [s['index'] for s in seen if not s['fits']])
        check('tutorial: every outline sits on its part when the step is read (pages that settle late too)',
              all(s['part'] is None or all(abs(a - b) <= 3 for a, b in zip(s['hole'], s['part'])) for s in seen),
              [(s['index'], s['hole'], s['part']) for s in seen if s['part'] is not None])
        recent_names = []
        try:
            from .studio_project import studio_settings_path
            recent_names = [str(item.get('path', '')) for item in json.loads(
                studio_settings_path().read_text(encoding='utf-8')).get('recent_projects', [])]
        except (OSError, ValueError):
            pass
        check('tutorial: the demo project is not left in recent projects and leaves no autosave',
              not any('tutorial-v' in name for name in recent_names)
              and not list((studio_settings_path().parent / 'autosaves').glob('*.2byteproj')),
              recent_names)
        check('tutorial: the result page, proofreading page and workbench were really shown',
              {'completionScroll', 'glossaryProofreadPage', 'subtitleStudio'} <= {s['page'] for s in seen},
              [s['page'] for s in seen])
        check('tutorial: the pretend result is not a first task, pops no completion alert; demo media removed; '
              'back on the home page',
              not state.get('first_task_done') and not getattr(window, 'media_paths', None) and not visible_dialogs()
              and window.pages.currentWidget() is window.__dict__.get('settings_scroll'),
              dict(state=state, media=getattr(window, 'media_paths', None), dialogs=visible_dialogs()))
        check('the 2ByteASR title is not a button (no hand cursor, no hover style)',
              window.brand.cursor().shape() != Qt.CursorShape.PointingHandCursor
              and 'brand:hover' not in QApplication.instance().styleSheet())
        card = window.__dict__.get('next_step_card')
        yield lambda: card is not None and card.isVisible()
        check('fresh install: home shows step 1 of the guide with one main button',
              card.step.key == 'welcome' and card.step.step == 0
              and [a for _l, a in card.step.actions] == ['choose_media', 'tour', 'open_sample'],
              dict(message=card.message.text()))
        capture('A1-home-welcome')
        # Dismiss and bring back from 说明.
        QTest.mouseClick(card.close_button, Qt.MouseButton.LeftButton)
        yield 0.4
        check('the welcome card can be closed', not card.isVisible() and onboarding.load_state().get('guide') is False)
        chosen = {}

        def pick_guide(menu):
            grab(menu, 'A4-help-menu')
            chosen['action'] = next(a for a in menu.actions() if a.text().startswith('显示新手引导'))
            menu.close()
        on_modal(QMenu, pick_guide, 'help-menu')
        QTest.mouseClick(window.help_button, Qt.MouseButton.LeftButton)
        yield lambda: 'action' in chosen
        yield 0.3
        chosen['action'].trigger()                     # after the menu closed, as a click would
        yield lambda: card.isVisible()
        check('说明 → 显示新手引导 brings it back', card.isVisible() and onboarding.load_state().get('guide') is True)
        # Example project: no model, no key, nothing uploaded.
        from PySide6.QtWidgets import QPushButton
        button = card.findChild(QPushButton, 'nextStepAction_open_sample')
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        yield lambda: ready() and studio().project.generation_metadata.get('sample_project')
        yield 1.5
        page = studio()
        check('example project opens in the workbench without models or API keys',
              len(page.project.cues) == 8 and page.project.media.duration_ms > 0,
              dict(cues=len(page.project.cues), media=page.project.media.path))
        capture('A2-example-project')
        window._return_to_settings()
        yield lambda: window.pages.currentIndex() == 0
        # Choosing media: the card now says what is missing for this computer.
        media = Path(spec['media'])
        window.import_media([str(media)], replace=True)
        yield lambda: bool(getattr(window, 'media_paths', None))
        yield lambda: getattr(window, '_onboarding_facts', None) is not None and card.step.key in ('plan', 'ready')
        yield 0.8
        facts = window._onboarding_facts
        offered = [a for _l, a in card.step.actions]
        check('after choosing media the card names the next step for this computer',
              card.step.key in ('plan', 'ready') and '最快' not in card.message.text() and '最准' not in card.message.text(),
              dict(step=card.step.key, message=card.message.text(), actions=offered,
                   nvidia=getattr(facts.host, 'nvidia', None)))
        cuda_ok = any(o.key == 'windows_cuda' and o.available for o in facts.options)
        check('a plan this computer cannot run is never offered as "use"',
              cuda_ok or 'use_plan:windows_cuda' not in offered, offered)
        capture('A3-home-plan-step')
        # 2026-10-14: English on the home language row; the bilingual item names the pair.
        language_combo, output_combo = window.recognition_language, window.subtitle_output
        before = (language_combo.currentIndex(), output_combo.currentIndex())
        language_combo.setCurrentIndex(language_combo.findData('en'))
        output_combo.setCurrentIndex(output_combo.findData('bilingual'))
        yield 0.3
        window.home_scroll.ensureWidgetVisible(output_combo) if hasattr(window, 'home_scroll') else None
        scroll = window.__dict__.get('settings_scroll')
        if scroll is not None:
            scroll.ensureWidgetVisible(output_combo, 40, 160)
        yield 0.4
        capture('A3b-english-language-row')
        label = output_combo.itemText(output_combo.findData('bilingual'))
        hint = window.subtitle_language_hint.text()
        saved = dict(window.legacy.RUNTIME_SETTINGS.get('subtitle_language') or {})
        language_combo.setCurrentIndex(language_combo.findData('ja'))
        yield 0.2
        ja_label = output_combo.itemText(output_combo.findData('bilingual'))
        check('home: 英语 can be chosen; the bilingual item reads 英中双语 (日中双语 for Japanese); the choice is saved',
              language_combo.findData('en') >= 0 and label == '英中双语' and ja_label == '日中双语'
              and '英语' in hint and saved.get('recognition_language') == 'en' and saved.get('output') == 'bilingual',
              dict(label=label, ja_label=ja_label, hint=hint[:120], saved=saved))
        language_combo.setCurrentIndex(before[0])
        output_combo.setCurrentIndex(before[1])
        yield 0.2
        # Feature search on the home page.
        def search(dialog):
            from PySide6.QtWidgets import QLineEdit, QListWidget
            event('step', name='feature-search:found')
            field = dialog.findChild(QLineEdit, 'featureSearchField')
            if field is None:
                raise RuntimeError(f'not the search dialog: {type(dialog).__name__} {dialog.objectName()!r} '
                                   f'{dialog.windowTitle()!r} {visible_dialogs()}')
            field.setFocus()
            field.insert('标点')                       # what an IME commit does
            event('step', name='feature-search:typed')
            QApplication.processEvents()
            results = dialog.findChild(QListWidget, 'featureSearchResults')
            result['feature_search'] = [results.item(i).text() for i in range(min(4, results.count()))]
            grab(dialog, 'A5-feature-search')
            dialog.reject()
        on_modal(QDialog, search, 'feature-search')
        event('step', name='feature-search:ctrl+k', dialogs=visible_dialogs())
        focus = QApplication.focusWidget() or window
        QTest.keyClick(focus, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        event('step', name='feature-search:returned')
        yield 1.0
        check('Ctrl+K on the home page finds 标点', (result.get('feature_search') or [''])[0].startswith('字幕标点'),
              result.get('feature_search'))
        # Qwen Cloud guide (offline: the real service is not contacted).
        def qwen(dialog):
            from PySide6.QtWidgets import QLineEdit, QPushButton
            dialog.resize(1100, 860)
            QApplication.processEvents()
            links = [b.toolTip().split('\n')[0] for b in dialog.findChildren(QPushButton, 'helpLink')]
            fields = [e.objectName() for e in dialog.findChildren(QLineEdit) if e.objectName().startswith('apiSetupField_')
                      and e.isVisibleTo(dialog) and e.isEnabled()]   # the address is prefilled and locked
            result['qwen_links'], result['qwen_fields'] = links, fields
            grab(dialog, 'Q1-qwen-guide')
            key = dialog.findChild(QLineEdit, 'apiSetupField_api_key')
            key.setText('sk-sp-' + '0' * 24)
            QTest.mouseClick(dialog.findChild(QPushButton, 'apiSetupTest_free'), Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            result['qwen_token_plan'] = [d.text() for _m, d in dialog._result_labels.values()]
            grab(dialog, 'Q2-token-plan-key')
            key.setText('sk-ws-' + '0' * 24)
            # ADR 0112: own OSS is the default; the network test needs the trial upload or OSS fields.
            from PySide6.QtWidgets import QComboBox
            upload = dialog.findChild(QComboBox, 'apiSetupField_filetrans_upload')
            if upload is not None and upload.findData('provider_temporary') >= 0:
                upload.setCurrentIndex(upload.findData('provider_temporary'))
                QApplication.processEvents()
            QTest.mouseClick(dialog.findChild(QPushButton, 'apiSetupTest_free'), Qt.MouseButton.LeftButton)
            deadline = time.monotonic() + 25

            def wait_result():
                texts = [d.text() for _m, d in dialog._result_labels.values()]
                busy = any(t == '正在检查…' for t in texts) or '正在' in dialog.status.text()
                if busy and time.monotonic() < deadline:
                    QTimer.singleShot(200, wait_result)
                    return
                result['qwen_offline'] = texts + [dialog.status.text()]
                grab(dialog, 'Q3-offline-check')
                dialog.reject()
            QTimer.singleShot(600, wait_result)
        on_modal(QDialog, qwen, 'qwen-guide')
        event('step', name='qwen:open')
        window._open_api_setup_guide('qwen_cloud_filetrans')
        event('step', name='qwen:closed')
        yield 0.5
        links = result.get('qwen_links') or []
        check('Qwen Cloud guide links only to official Qwen Cloud / Alibaba Cloud pages',
              links and all(re.match(r'https://([a-z0-9-]+\.)*(qwencloud\.com|qwen\.ai|alibabacloud\.com|aliyun\.com)/', u)
                            for u in links), links)
        fields = result.get('qwen_fields') or []
        check('Qwen Cloud guide: the key comes first; the only other fields are the OSS ones (ADR 0112), address locked',
              fields[:1] == ['apiSetupField_api_key'] and all(f.startswith('apiSetupField_oss') for f in fields[1:]),
              result.get('qwen_fields'))
        token = ' '.join(result.get('qwen_token_plan') or [])
        check('a Token Plan key is explained before anything is sent', 'Token Plan' in token or 'sk-sp' in token, token)
        offline = ' '.join(result.get('qwen_offline') or [])
        check('offline: the failure says connection, not "API Key 错误"', ('连' in offline or '网络' in offline)
              and 'API Key 错误' not in offline, offline)
        # A text-AI guide's "去填写这家服务的密钥" opens the AI settings on that service.
        from .ui import EndpointEditor
        window._api_setup_host().open_text_settings('deepseek')
        yield 0.6
        ai_dialog = getattr(window, '_ai_settings_dialog', None)
        editor = ai_dialog.findChild(EndpointEditor) if ai_dialog is not None else None
        check('a text-AI guide opens the AI settings on the same service',
              editor is not None and editor.service.currentData() == 'deepseek',
              editor.service.currentData() if editor is not None else None)
        if ai_dialog is not None:
            ai_dialog.reject()
            yield 0.4
        # Punctuation styles on a real project.
        event('step', name='punctuation')
        yield from punctuation()
        event('step', name='shortcuts')
        yield from shortcuts()
        # Diagnostics text: what will be copied.
        def diagnostics(dialog):
            from PySide6.QtWidgets import QPlainTextEdit
            text = dialog.findChild(QPlainTextEdit, 'diagnosticsText').toPlainText()
            result['diagnostics_len'] = len(text)
            result['diagnostics_leaks'] = [s for s in (str(Path.home()), os.environ.get('USERNAME', '@@'), 'sk-ws-', 'sk-sp-')
                                           if s and s in text]
            grab(dialog, 'D1-diagnostics')
            dialog.reject()
        window._return_to_settings()
        yield lambda: window.pages.currentIndex() == 0
        on_modal(QDialog, diagnostics, 'diagnostics')
        window._open_diagnostics_dialog()
        yield 0.5
        check('diagnostics text has no home folder, user name or keys', result.get('diagnostics_len', 0) > 100
              and not result.get('diagnostics_leaks'), result.get('diagnostics_leaks'))

    def punctuation():
        from .bilingual_layout import project_display_cues
        from .punctuation_style import project_mode
        from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts
        window.open_studio_project(spec['project'], mode='edit', source='onboarding_audit')
        yield lambda: ready() and studio().project.project_id == spec['project_id']
        yield 1.5
        page = studio()
        manuscript = [(c.id, c.start_ms, c.end_ms, c.speaker_id, c.text) for c in page.project.cues]
        check('punctuation: a project starts as recognized (保留原文)', project_mode(page.project) == 'original')
        page.punctuation_mode_actions['add'].trigger()
        yield 0.8
        shown = [c.text for c in project_display_cues(page.project)]
        result['punctuation_add'] = shown
        protected = ('S0pp', 'v1.2.3', '98.5%', "It's", '12:30', 'U.S.', 'bilibili.com', 'Zhe', 'CHIOCHOO', '一个人', '-3')
        joined = '\n'.join(shown)
        check('添加标点: pauses become commas, protected words untouched',
              '，' in joined and all(token in joined for token in protected), shown)
        check('添加标点: manuscript, timings, speakers and ids unchanged',
              [(c.id, c.start_ms, c.end_ms, c.speaker_id, c.text) for c in page.project.cues] == manuscript)
        exports = folder / 'export-add'
        artifacts = export_subtitle_artifacts(page.project, exports, 'demo',
                                              SubtitleExportOptions(formats=frozenset({'srt', 'txt', 'json'})))
        srt = (exports / 'demo.srt').read_text('utf-8')
        data = json.loads((exports / 'demo.json').read_text('utf-8'))
        check('SRT / TXT / JSON follow the same style; JSON keeps the manuscript',
              all(line in srt for line in shown) and all(line in (exports / 'demo.txt').read_text('utf-8') for line in shown)
              and [c.get('original_text') for c in data.get('cues', [])][:2] == [m[4] for m in manuscript][:2],
              dict(files=[a.path.name for a in artifacts]))
        page.timeline.seek_requested.emit((page.project.cues[0].start_ms + 400) / 1000.0)
        yield 1.0
        capture('P1-add-punctuation')
        undo_before = page.undo_stack.count()
        QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        yield 0.6
        check('Ctrl+Z restores 保留原文 in one step', project_mode(page.project) == 'original', page.undo_stack.count() - undo_before)
        page.punctuation_mode_actions['none'].trigger()
        yield 0.6
        shown_none = [c.text for c in project_display_cues(page.project)]
        check('不加标点: no sentence marks, protected words untouched',
              not any(ch in ''.join(shown_none) for ch in '，。、；：') and all(t in '\n'.join(shown_none) for t in protected),
              shown_none)
        capture('P2-no-punctuation')
        page.punctuation_mode_actions['add'].trigger()
        yield 0.4

        def permanent(dialog):
            grab(dialog, 'P3-write-into-manuscript')
            dialog.accept()
        on_modal(QDialog, permanent, 'permanent')
        before_steps = page.undo_stack.index()
        page.punctuation_permanent_action.trigger()
        yield 1.0
        written = [c.text for c in page.project.cues]
        check('writing the style into the manuscript is one step; timings unchanged',
              written != [m[4] for m in manuscript] and page.undo_stack.index() == before_steps + 1
              and [(c.id, c.start_ms, c.end_ms, c.speaker_id) for c in page.project.cues] == [m[:4] for m in manuscript],
              written[:3])
        QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        yield 0.6
        QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        yield 0.6
        check('undo returns the original manuscript (timings, speakers, ids unchanged throughout)',
              [(c.id, c.start_ms, c.end_ms, c.speaker_id, c.text) for c in page.project.cues] == manuscript, project_mode(page.project))
        page.punctuation_mode_actions['original'].trigger()
        yield 0.3

    def shortcuts():
        from . import shortcut_registry as registry
        from .application_settings import open_application_settings
        page = studio()

        def settings(dialog):
            from PySide6.QtWidgets import QKeySequenceEdit
            items = dialog.navigation.findItems('快捷键', Qt.MatchFlag.MatchExactly)
            dialog.navigation.setCurrentItem(items[0])
            panel = dialog.shortcut_panel
            panel.search.insert('吸附')                 # an IME commit (QTest cannot type Chinese)
            QApplication.processEvents()
            editor = panel.findChild(QKeySequenceEdit, 'shortcutEditor_toggle_snap')
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
            QTest.keyClick(editor, Qt.Key.Key_Q)              # Q is 字幕起点至播放头: same scope
            QApplication.processEvents()
            result['conflict_text'] = panel.conflict_label.text()
            result['save_enabled_in_conflict'] = panel._save_button.isEnabled()
            result['resolve_visible'] = panel.resolve_button.isVisible()
            grab(dialog, 'S1-shortcut-conflict')
            editor.clear()
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
            QTest.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ShiftModifier)
            QApplication.processEvents()
            result['after_rebind'] = panel.conflict_label.text()
            grab(dialog, 'S2-shortcut-rebound')
            QTest.mouseClick(panel._save_button, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            dialog.reject()
        on_modal(QDialog, settings, 'shortcut-settings')
        open_application_settings(page)
        yield 0.5
        check('a key used by another action in the same place is named and must be resolved first',
              '字幕起点' in (result.get('conflict_text') or '') and result.get('save_enabled_in_conflict') is False
              and result.get('resolve_visible'), result.get('conflict_text'))
        check('the new binding is saved for every launch', registry.current_values().get('toggle_snap') == 'Shift+S',
              registry.read_stored().get('toggle_snap'))
        window.showMaximized()
        yield lambda: ready()
        yield 0.5
        page.timeline.setFocus()
        snap = page.snap_toggle.isChecked()
        QTest.keyClick(page.timeline, Qt.Key.Key_S, Qt.KeyboardModifier.ShiftModifier)
        yield 0.4
        changed = page.snap_toggle.isChecked() != snap
        QTest.keyClick(page.timeline, Qt.Key.Key_S)
        yield 0.4
        check('the new key works at once and the old one no longer does', changed
              and page.snap_toggle.isChecked() == (not snap), dict(before=snap, after=page.snap_toggle.isChecked()))
        # Typing in a text box never runs single-key shortcuts.
        from PySide6.QtWidgets import QLineEdit
        fields = [w for w in page.findChildren(QLineEdit) if w.isVisible() and w.isEnabled() and not w.isReadOnly()
                  and not w.inputMask() and w.validator() is None and 'timecode' not in w.objectName().lower()]
        fields.sort(key=lambda w: 'search' not in w.objectName().lower())
        field = fields[0] if fields else None
        result['typing_field'] = field.objectName() if field is not None else None
        steps_before = page.undo_stack.count()
        playing_before = not page.video._paused
        if field is not None:
            field.setFocus()
            field.clear()
            QTest.keyClicks(field, 'qwe a')
            yield 0.4
            check('typing q w e a and Space into a text box inserts text and runs nothing',
                  field.text() == 'qwe a' and page.undo_stack.count() == steps_before
                  and (not page.video._paused) == playing_before, dict(field=field.objectName(), text=field.text()))
            field.clear()
        # Q in one real key press: exactly one edit.
        page.timeline.setFocus()
        cue = page.project.cues[1]
        middle = (cue.start_ms + cue.end_ms) // 2
        page.video.set_paused(True)
        page.timeline.seek_requested.emit(middle / 1000.0)
        yield 0.8
        count = page.undo_stack.count()
        post_key(0x51)
        yield 0.8
        moved = next(c for c in page.project.cues if c.id == cue.id)
        check('Q pressed once (native key) makes exactly one edit',
              page.undo_stack.count() == count + 1 and abs(moved.start_ms - page.timeline.playhead_ms) <= 50,
              dict(steps=page.undo_stack.count() - count, start=moved.start_ms, playhead=page.timeline.playhead_ms))
        capture('S3-q-one-press')
        page.undo_stack.undo()
        yield 0.3
        page.session.undo_stack.setClean()

    # ------------------------------------------------------------ restart
    def restart():
        from . import onboarding, shortcut_registry as registry
        window.showMaximized()
        yield 1.5
        from .home_tour import HomeTour
        check('restart: no dialog or tour at startup', not visible_dialogs() and window.findChild(HomeTour) is None,
              visible_dialogs())
        state = onboarding.load_state()
        check('restart: the first-run stamp is kept (not reset)', state.get('fresh') is True and 'guide' in state, state)
        check('restart: the custom shortcut is kept', registry.current_values().get('toggle_snap') == 'Shift+S')
        capture('R1-home-after-restart')

        def recovery(box):
            # The first launch left unsaved edits: the app offers its recovery point.
            result['recovery_prompt'] = dict(title=box.windowTitle(), text=box.text(),
                                             buttons=[b.text() for b in box.buttons()])
            grab(box, 'R2-recovery-offered')
            saved = next(b for b in box.buttons() if b.text() == '打开正式保存')
            QTest.mouseClick(saved, Qt.MouseButton.LeftButton)
        from .studio_project import studio_settings_path
        autosaves = list((studio_settings_path().parent / 'autosaves').glob('*.2byteproj'))
        on_modal(QMessageBox, recovery, 'recovery', timeout=15)
        window.open_studio_project(spec['project'], mode='edit', source='onboarding_audit')
        yield ready
        check('restart: the project opens; an autosave left by the last session is offered, never forced',
              bool(result.get('recovery_prompt')) == bool(autosaves),
              dict(autosaves=len(autosaves), prompt=result.get('recovery_prompt')))
        yield 1.0
        page = studio()
        page.timeline.setFocus()
        snap = page.snap_toggle.isChecked()
        QTest.keyClick(page.timeline, Qt.Key.Key_S, Qt.KeyboardModifier.ShiftModifier)
        yield 0.4
        check('restart: Shift+S toggles snapping', page.snap_toggle.isChecked() != snap)
        page.session.undo_stack.setClean()

    # ------------------------------------------------------------ upgraded
    def upgraded():
        from . import onboarding, shortcut_registry as registry
        yield ready
        yield 1.5
        page = studio()
        check('upgraded user: a double-clicked project opens straight in the workbench',
              page.project.project_id == spec['project_id'] and window.pages.currentWidget() is not window.__dict__.get('settings_scroll'))
        from .home_tour import HomeTour
        check('upgraded user: no dialog or tour at startup', not visible_dialogs() and window.findChild(HomeTour) is None,
              visible_dialogs())
        capture('U1-opened-project')
        values = registry.current_values()
        check('upgraded user: old custom keys kept and migrated', values.get('play_pause') == 'K'
              and values.get('merge_tool') == 'B', dict(play_pause=values.get('play_pause'), merge=values.get('merge_tool')))
        page.session.undo_stack.setClean()
        window._return_to_settings()
        yield lambda: window.pages.currentIndex() == 0
        yield 2.0
        card = window.__dict__.get('next_step_card')
        state = onboarding.load_state()
        check('upgraded user: no tutorial card on the home page', state.get('fresh') is False
              and (card is None or not card.isVisible() or card.step.key not in ('welcome',)), dict(state=state,
              step=getattr(getattr(card, 'step', None), 'key', None)))
        capture('U2-home-upgraded')

    steps_by_phase = dict(fresh=fresh, restart=restart, upgraded=upgraded)
    iterator = steps_by_phase[phase]()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / f'result-{phase}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result.get('error')
        save()
        log.close()
        page = studio()
        if page is not None and getattr(page, 'session', None) is not None:
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
                state.update(wait=value, deadline=time.monotonic() + 120)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            capture('failure')
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start(50)
