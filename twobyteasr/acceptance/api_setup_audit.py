"""Real-window check of the 「申请与设置 API」 walkthrough (2026-10-14, redone 2026-10-18).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=api-setup`` (isolated data,
offline: external name lookups are refused and ``QDesktopServices.openUrl``
only records the address, so no provider is contacted and no browser opens).
Theme from ``TWOBYTEASR_API_SETUP_THEME`` (grape / warm). Opens the dialog the
way a user does (``window._open_api_setup_guide``) and checks, at a narrow and
a wide size: the service, time and cost on top with no provider list; one step
per page with the official screenshot and the button ringed; the official
page behind each button; “已经有 Key？直接贴上”; model and addresses folded
into “更多设置”; the offline free check staying on the paste page; the
“检查通过” page; the “换一家” menu; 百炼 / Qwen Cloud OSS fields, the trial
upload warning and locked addresses; 讯飞's three values; DeepSeek's
“先充值 10 元” and “去填写”; the full tutorial. Writes ``result.json`` and
screenshots into the output directory.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

SIZES = {'narrow': (720, 560), 'wide': (1280, 760)}


def _offline_dns() -> None:
    import socket
    original = socket.getaddrinfo

    def local_only(host, *args, **kwargs):
        if str(host) not in {'127.0.0.1', '::1', 'localhost', ''}:
            raise socket.gaierror(socket.EAI_NONAME, 'external name lookup disabled in this acceptance run')
        return original(host, *args, **kwargs)
    socket.getaddrinfo = local_only


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidget, QPushButton, QTextBrowser, QToolButton
    from ..diagnostics.build_identity import load_build_identity
    from ..providers import api_setup_catalog as catalog
    from ..providers import cloud_api_test as tests
    from ..providers.api_setup_dialog import ShotView
    _offline_dns()
    opened_urls = []
    QDesktopServices.openUrl = staticmethod(lambda url: opened_urls.append(url.toString()) or True)
    theme = os.environ.get('TWOBYTEASR_API_SETUP_THEME', 'grape')
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], identity=load_build_identity().to_dict(), theme=theme, passed=False)

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=f'[{theme}] {name}', passed=bool(ok), detail=detail))

    def settle(ms=150):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QApplication.processEvents()

    def grab(widget, name):
        settle(120)
        widget.grab().save(str(output / f'{theme}-{name}.png'))

    def visible(dialog, widget):
        return widget is not None and widget.isVisibleTo(dialog)

    def page(dialog):
        return dialog.stack.currentWidget()

    def texts(dialog, name):
        return [label.text() for label in page(dialog).findChildren(QLabel, name)]

    def labels_fit(dialog):
        """Every visible wrapped label on the page gets its full text height; nothing scrolls sideways."""
        bad = []
        for label in page(dialog).findChildren(QLabel):
            if visible(dialog, label) and label.wordWrap() and label.text():
                if label.height() < label.heightForWidth(label.width()) - 1:
                    bad.append((label.text()[:24], label.height(), label.heightForWidth(label.width())))
        scroll = getattr(dialog, 'scroll', None)
        if scroll is not None and visible(dialog, scroll) and scroll.horizontalScrollBar().maximum() > 0:
            bad.append(('horizontal scroll', scroll.horizontalScrollBar().maximum()))
        return bad

    def buttons_fit(dialog):
        bad = []
        for button in dialog.findChildren(QPushButton):
            # The header × is a 32 px glyph button by design (test_api_setup_guide checks its glyph room).
            if visible(dialog, button) and len(button.text()) > 1 and button.objectName() != 'helpLink':
                need = button.fontMetrics().horizontalAdvance(button.text()) + (20 if button.icon().isNull() else 40)
                if button.width() < need - 8:
                    bad.append((button.text(), button.width(), need))
        return bad

    def wait_for(predicate, timeout=25.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def click(widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        settle()

    def mosi(dialog, size):
        dialog.resize(*SIZES[size])
        settle(300)
        tag = f'{size}: MOSS'
        check(f'{tag}: no provider list; the service, time and cost on top',
              not [w for w in dialog.findChildren(QListWidget) if visible(dialog, w)]
              and dialog.name_label.text() == 'MOSS 云端识别'
              and any('约 5 分钟' in t for t in [l.text() for l in dialog.findChildren(QLabel, 'apiSetupFactText')])
              and any('免费积分' in t for t in [l.text() for l in dialog.findChildren(QLabel, 'apiSetupFactText')]),
              [l.text() for l in dialog.findChildren(QLabel, 'apiSetupFactText')])
        check(f'{tag}: three steps, starting at step 1', [b.text() for b in dialog.progress.labels]
              == ['注册登录', '创建 Key', '贴上检查'] and dialog._page_kind == 'step' and dialog._index == 0,
              [b.text() for b in dialog.progress.labels])
        shot = page(dialog).findChild(ShotView)
        check(f'{tag}: step 1 shows the official screenshot with the button ringed',
              shot is not None and shot.pixmap is not None and shot.ring is not None and shot.width() >= 280)
        note = ' '.join(texts(dialog, 'apiSetupNoteText'))
        check(f'{tag}: step 1 says the daily free credit', '50 积分' in note, note)
        check(f'{tag}: step 1 text and buttons fit', not labels_fit(dialog) and not buttons_fit(dialog),
              labels_fit(dialog) + buttons_fit(dialog))
        grab(dialog, f'{size}-M1-step1')
        before = len(opened_urls)
        click(page(dialog).findChild(QPushButton, 'apiSetupOpen_0'))
        check(f'{tag}: “打开 MOSI 网站” opens the official site', opened_urls[before:] == ['https://platform.mosi.cn/'],
              opened_urls[before:])
        click(page(dialog).findChild(QPushButton, 'apiSetupNext'))
        shot = page(dialog).findChild(ShotView)
        check(f'{tag}: “做好了，下一步” → step 2 with its screenshot, step 1 ticked',
              dialog._index == 1 and dialog._done[0] and shot is not None and shot.pixmap is not None)
        grab(dialog, f'{size}-M2-step2')
        click(dialog.skip_button)
        key = dialog._fields['api_key']
        check(f'{tag}: “已经有 Key？直接贴上” → the key field, focused',
              dialog._page_kind == 'paste' and dialog.focusWidget() is key)
        check(f'{tag}: model and address fold into “更多设置”', not visible(dialog, dialog._fields['model'])
              and not visible(dialog, dialog._fields['url']) and visible(dialog, key))
        check(f'{tag}: paste page fits', not labels_fit(dialog) and not buttons_fit(dialog),
              labels_fit(dialog) + buttons_fit(dialog))
        grab(dialog, f'{size}-M3-paste')
        click(dialog.more_toggle)
        url = dialog._fields['url']
        check(f'{tag}: “更多设置” shows the model and the locked prefilled address',
              visible(dialog, dialog._fields['model']) and visible(dialog, url) and not url.isEnabled()
              and not visible(dialog, dialog.address_view), url.text())
        grab(dialog, f'{size}-M4-more')
        click(dialog.more_toggle)
        key.setFocus()
        key.insert('sk-' + '0' * 24)
        settle()
        click(page(dialog).findChild(QPushButton, 'apiSetupTest_free'))
        ok = wait_for(lambda: '正在' not in dialog.status.text() and dialog._result_labels['connection'][0].text() != '—')
        mark, detail = dialog._result_labels['connection']
        check(f'{tag}: offline free check reports the connection and stays on the paste page',
              ok and mark.text() == '✗' and dialog._result_labels['key'][0].text() != '✗'
              and dialog._page_kind == 'paste', (mark.text(), detail.text(), dialog._page_kind))
        check(f'{tag}: result rows fit', not labels_fit(dialog), labels_fit(dialog))
        grab(dialog, f'{size}-M5-offline-check')
        passed = tests.Report().add('format', tests.PASS, '').add('connection', tests.PASS, '').add('key', tests.PASS, '')
        dialog._show_report(passed)     # what a passing check shows (offline run)
        settle()
        check(f'{tag}: a passing check leads to “检查通过，可以保存了”, save as the main button',
              dialog._page_kind == 'done' and dialog.save_primary_button.property('buttonRole') == 'primary'
              and visible(dialog, dialog.save_primary_button) and all(dialog._done))
        after = ' '.join(page(dialog).findChild(QLabel, 'apiSetupAfterNote').text().split())
        check(f'{tag}: the done page says when to top up', '¥2' in after, after)
        grab(dialog, f'{size}-M6-done')
        click(dialog.tutorial_button)
        guide_box = page(dialog).findChild(QTextBrowser, 'apiSetupGuide')
        guide_text = guide_box.toPlainText() if guide_box is not None else ''
        check(f'{tag}: “看完整教程” shows the bundled tutorial and the official links',
              len(guide_text) > 500 and '找不到教程文件' not in guide_text
              and len(page(dialog).findChildren(QPushButton, 'helpLink')) >= 4, guide_text[:60])
        grab(dialog, f'{size}-M7-tutorial')
        click(dialog.prev_button)
        check(f'{tag}: “返回” from the tutorial goes back to the done page', dialog._page_kind == 'done')
        if size == 'wide':
            dialog.provider_menu.popup(dialog.switch_button.mapToGlobal(QPoint(0, dialog.switch_button.height())))
            settle(400)
            menu_texts = [a.text().split('\t')[0] for a in dialog.provider_menu.actions() if a.data()]
            check(f'{tag}: “换一家” lists the services only when asked',
                  'MOSS 云端识别' in menu_texts and 'DeepSeek' in menu_texts and len(menu_texts) >= 10, menu_texts)
            grab(dialog.provider_menu, 'menu')
            dialog.provider_menu.close()
        dialog.reject()

    def bailian(dialog):
        dialog.resize(*SIZES['narrow'])
        settle(300)
        check('百炼: four steps with the private OSS step',
              [b.text() for b in dialog.progress.labels] == ['注册登录', '创建 Key', '建 OSS', '贴上检查'],
              [b.text() for b in dialog.progress.labels])
        shot = page(dialog).findChild(ShotView)
        check('百炼: step 1 shows the 阿里云 sign-up page with the form ringed',
              shot is not None and shot.pixmap is not None and shot.ring is not None)
        grab(dialog, 'B0-step1')
        dialog._go(1)
        shot = page(dialog).findChild(ShotView)
        check('百炼: step 2 shows the API Key page (signed-in picture)', shot is not None and shot.pixmap is not None)
        grab(dialog, 'B0-step2')
        dialog._go(len(dialog._walk) - 1)
        settle()
        upload = dialog._fields['filetrans_upload']
        check('百炼: own OSS preselected; OSS fields shown', upload.currentData() == 'own_oss'
              and all(visible(dialog, dialog._fields[k]) for k in ('oss_bucket', 'oss_access_key_id')))
        trial_label = dialog._field_rows['filetrans_upload_trial'][1][0]
        check('百炼: no trial warning while OSS is chosen', not visible(dialog, trial_label))
        check('百炼: paste page fits at the narrow size', not labels_fit(dialog) and not buttons_fit(dialog),
              labels_fit(dialog) + buttons_fit(dialog))
        grab(dialog, 'B1-paste-oss')
        upload.setCurrentIndex(upload.findData('provider_temporary'))
        settle()
        check('百炼: the trial upload shows the official warning and hides OSS fields',
              visible(dialog, trial_label) and '请勿用于生产环境' in trial_label.text()
              and not visible(dialog, dialog._fields['oss_bucket']), trial_label.text())
        grab(dialog, 'B2-trial')
        upload.setCurrentIndex(upload.findData('own_oss'))
        dialog._fields['api_host'].setFocus()
        dialog._fields['api_host'].clear()
        dialog._fields['api_host'].insert('https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
        dialog._fields['api_key'].setFocus()
        dialog._fields['api_key'].insert('sk-' + '1' * 24)
        settle()
        shown = dialog.address_view.text()
        check('百炼: a pasted chat address becomes one line (region · Base URL)',
              len(shown.splitlines()) == 1 and shown.endswith('https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1')
              and '/services/audio/asr/transcription' in dialog.address_view.toolTip(), shown)
        click(page(dialog).findChild(QPushButton, 'apiSetupTest_free'))
        mark, detail = dialog._result_labels['format']
        check('百炼: missing OSS fields are caught locally before anything is sent',
              mark.text() == '✗' and 'OSS' in detail.text() and not dialog._threads, detail.text())
        grab(dialog, 'B3-format')
        dialog.reject()

    def qwen_cloud(dialog):
        dialog.resize(840, 600)
        settle(300)
        # 2026-10-25: Simplified Chinese starts on 中国站 (千问AI平台); the switch beside the name goes to 国际站.
        box = dialog.qwen_site_box
        check('Qwen: the page opens on 中国站 (千问AI平台) with the site switch beside the name',
              visible(dialog, box) and box.currentData() == 'cn' and dialog._guide.site_variant == 'cn', box.currentText())
        shot = page(dialog).findChild(ShotView)
        check('千问AI平台: step 1 shows its sign-in page', shot is not None and shot.pixmap is not None)
        grab(dialog, 'Q0-china-step1')
        topup = dialog._walk[1]
        check('千问AI平台: step 2 is “认证与充值” on its own billing page',
              topup.title == '认证与充值' and topup.url.startswith('https://platform.qianwenai.com/'), topup.url)
        dialog._go(len(dialog._walk) - 1)
        click(dialog.more_toggle)
        unlock = next((b for b in dialog.findChildren(QToolButton) if b.text() == '修改' and visible(dialog, b)), None)
        if unlock is not None:
            click(unlock)
        check('千问AI平台: requests go to maas.qianwenaiapi.com',
              'maas.qianwenaiapi.com' in dialog.address_view.text(), dialog.address_view.text())
        grab(dialog, 'Q0-china-address')
        box.setCurrentIndex(box.findData('intl'))
        settle(300)
        check('Qwen: switching to 国际站 shows the Qwen Cloud steps', dialog._guide.site_variant == 'intl', dialog._guide.name)
        topup = dialog._walk[1]
        check('Qwen Cloud: step 2 is “补全付款信息” (free quota after payment info)',
              topup.role == 'topup' and topup.title == '补全付款信息', topup.title)
        dialog._go(len(dialog._walk) - 1)
        click(dialog.more_toggle)
        url = dialog._fields['url']
        unlock = next((b for b in dialog.findChildren(QToolButton) if b.text() == '修改' and visible(dialog, b)), None)
        if unlock is not None:
            click(unlock)
        check('Qwen Cloud: “修改” unlocks the address and shows where requests go',
              url.isEnabled() and visible(dialog, dialog.address_view)
              and 'maas.qwencloudapi.com' in dialog.address_view.text(), dialog.address_view.text())
        grab(dialog, 'Q1-more-unlocked')
        dialog.reject()

    def spark(dialog):
        dialog.resize(840, 600)
        settle(300)
        titles = [step.title for step in dialog._walk]
        check('讯飞: steps name the real-name check, the free quota and the three values',
              titles[:3] == ['注册并登录', '领免费额度', '创建应用，复制三项'] and titles[-1] == '把三项贴到这里', titles)
        dialog._go(2)
        shot = page(dialog).findChild(ShotView)
        check('讯飞: the three-values step shows the service page with them blocked out',
              shot is not None and shot.pixmap is not None)
        grab(dialog, 'S0-credentials')
        dialog._go(len(dialog._walk) - 1)
        grab(dialog, 'S1-paste')
        dialog.reject()

    def deepseek(dialog):
        dialog.resize(840, 600)
        settle(300)
        titles = [step.title for step in dialog._walk]
        check('DeepSeek (text AI): 注册 › 先充值 10 元 › 创建 Key › 去填写',
              titles == ['注册并登录', '先充值 10 元', '创建 API Key', '贴到“AI 智能断句设置”并测试'], titles)
        pictures = []
        for index in range(3):
            dialog._go(index)
            shot = page(dialog).findChild(ShotView)
            pictures.append(shot is not None and shot.pixmap is not None)
            grab(dialog, f'T0-step{index + 1}')
        check('DeepSeek: sign-in, top-up and key steps each show the official page', all(pictures), pictures)
        dialog._go(2)
        button = page(dialog).findChild(QPushButton, 'apiSetupOpen_2')
        check('DeepSeek: the key step opens the official key page',
              button is not None and 'platform.deepseek.com/api_keys' in button.toolTip())
        grab(dialog, 'T1-key-step')
        dialog._go(3)
        check('DeepSeek: last step goes to “AI 智能断句设置”',
              page(dialog).findChild(QPushButton, 'apiSetupFill') is not None and not visible(dialog, dialog.save_button))
        grab(dialog, 'T2-fill')
        # Step 1 of the other services shows their official sign-up / sign-in page (public pages, 2026-10-18).
        missing = []
        for kind, key in (('text', 'claude'), ('text', 'gemini'), ('text', 'xai'), ('asr', 'groq'), ('asr', 'openai'),
                          ('asr', 'qwen_cloud_filetrans')):
            dialog.choose(kind, key)
            settle(200)
            shot = page(dialog).findChild(ShotView)
            if shot is None or shot.pixmap is None:
                missing.append(key)
            grab(dialog, f'P-{key}-step1')
        check('step 1 of Claude, Gemini, xAI, Groq, OpenAI and Qwen Cloud shows the official page', not missing, missing)
        dialog.reject()

    def mai(dialog):
        """2026-10-25: the MAI card's 配置 opens OpenRouter with MAI-Transcribe 2 filled in, and saving works."""
        dialog.resize(840, 600)
        settle(300)
        model = dialog._fields.get('model')
        check('MAI card: 配置 opens OpenRouter with microsoft/mai-transcribe-2 already filled in',
              dialog._guide.key == 'openrouter_word' and model is not None
              and model.text() == 'microsoft/mai-transcribe-2', model.text() if model is not None else None)
        dialog._fields['api_key'].setFocus()
        dialog._fields['api_key'].insert('sk-or-v1-' + 'a' * 48)   # placeholder: nothing is sent in this run
        settle()
        grab(dialog, 'M1-mai-filled')
        status = []
        click(dialog.save_primary_button)
        status.append(dialog.status.text())
        check('MAI card: “保存并用于识别” saves it (no refusal of mai-transcribe-2)',
              '已保存' in status[0] and wait_for(lambda: not dialog.isVisible(), 5), status[0])
        if dialog.isVisible():
            dialog.reject()

    def mai_card():
        window._open_model_workshop()
        workshop = window.workshop_page
        settle(300)
        card = workshop._cards['mai_latest']
        check('MAI card is named MAI-Transcribe 2 and waits for a key',
              card.model.name == 'MAI-Transcribe 2' and workshop._model_state(card.model) == 'configure',
              (card.model.name, workshop._model_state(card.model)))
        workshop._view_model('mai_latest')
        settle(300)
        grab(window, 'M0-mai-card')
        done = []

        def poll(deadline=time.monotonic() + 20):
            found = next((w for w in QApplication.topLevelWidgets()
                          if isinstance(w, QDialog) and w.isVisible() and w.objectName() == 'apiSetupDialog'), None)
            if found is None:
                if time.monotonic() < deadline:
                    QTimer.singleShot(120, lambda: poll(deadline))
                else:
                    result.setdefault('errors', []).append(dict(name='mai', error='dialog did not open'))
                return
            try:
                mai(found)
            except Exception:  # noqa: BLE001
                result.setdefault('errors', []).append(dict(name='mai', error=traceback.format_exc()[-2000:]))
                found.reject()
            done.append(True)
        QTimer.singleShot(250, poll)
        click(workshop.detail_action)
        wait_for(lambda: bool(done), 30)
        settle(400)
        workshop._state_memo = None
        state = workshop._model_state(card.model, 'primary')
        check('MAI card: after saving, recognition uses OpenRouter · microsoft/mai-transcribe-2 and the card is in use',
              window.qwen_asr_api_provider.currentData() == 'openrouter_word'
              and window.qwen_asr_api_model.text() == 'microsoft/mai-transcribe-2' and state in {'selected', 'configured'},
              (window.qwen_asr_api_provider.currentData(), window.qwen_asr_api_model.text(), state))
        workshop._view_model('mai_latest')
        settle(300)
        grab(window, 'M2-mai-card-after')

    def run_one(act, provider, name, kind='asr', *args):
        done = []

        def act_safely(found):
            try:
                act(found, *args)
            except Exception:  # noqa: BLE001 - reported, then closed
                result.setdefault('errors', []).append(dict(name=name, error=traceback.format_exc()[-2000:]))
                found.reject()
            done.append(True)

        def poll(deadline=time.monotonic() + 20):
            found = next((w for w in QApplication.topLevelWidgets()
                          if isinstance(w, QDialog) and w.isVisible() and w.objectName() == 'apiSetupDialog'), None)
            if found is None:
                if time.monotonic() < deadline:
                    QTimer.singleShot(120, lambda: poll(deadline))
                else:
                    result.setdefault('errors', []).append(dict(name=name, error='dialog did not open'))
                return
            act_safely(found)
        QTimer.singleShot(250, poll)
        window._open_api_setup_guide(provider, kind)

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            settle(300)
            for size in ('wide', 'narrow'):
                run_one(mosi, 'mosi_moss_pro', f'mosi-{size}', 'asr', size)
                settle(200)
            for act, provider, name in ((bailian, 'qwen31_filetrans', 'bailian'),
                                        (qwen_cloud, 'qwen_cloud_filetrans', 'qwen-cloud'), (spark, 'spark_asr_v2', 'spark')):
                run_one(act, provider, name)
                settle(200)
            run_one(deepseek, 'deepseek', 'deepseek', 'text')
            settle(200)
            mai_card()
            settle(200)
            expected = {'https://platform.mosi.cn/'}
            check('only the official pages the user clicked were requested (offline run)',
                  set(opened_urls) <= expected and opened_urls, opened_urls)
        except Exception:  # noqa: BLE001
            result['error'] = traceback.format_exc()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) \
            and not result.get('error') and not result.get('errors')
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
    QApplication.instance().aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
