"""Real-window check of the 「申请与设置 API」 dialog, round 2 (2026-10-14).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=api-setup`` (isolated data,
offline: external name lookups are refused, so no provider is contacted and no
browser page is opened). Opens the dialog the way a user does
(``window._open_api_setup_guide``) for MOSS Pro, 百炼 录音文件识别, Qwen
Cloud and 讯飞, and checks: picture step cards per provider, the one-key route
listed first, own OSS preselected for 录音文件识别 with the trial upload only
as an explicit choice that shows the official warning, locked prefilled
addresses that reveal their breakdown only after “修改”, one-line hints, the
offline format check, and that no page needs horizontal scrolling. Writes
``result.json`` and screenshots into the output directory.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path


def _offline_dns() -> None:
    import socket
    original = socket.getaddrinfo

    def local_only(host, *args, **kwargs):
        if str(host) not in {'127.0.0.1', '::1', 'localhost', ''}:
            raise socket.gaierror(socket.EAI_NONAME, 'external name lookup disabled in this acceptance run')
        return original(host, *args, **kwargs)
    socket.getaddrinfo = local_only


def start(window, output: Path):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QLineEdit, QPushButton, QToolButton
    from .build_identity import load_build_identity
    _offline_dns()
    opened_urls = []
    QDesktopServices.openUrl = staticmethod(lambda url: opened_urls.append(url.toString()) or True)
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False)

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def grab(widget, name):
        widget.grab().save(str(output / f'{name}.png'))

    def settle(ms=150):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QApplication.processEvents()

    def page_fits(dialog):
        bar = dialog.scroll.horizontalScrollBar()
        return bar.maximum() == 0

    def visible(dialog, widget):
        return widget is not None and widget.isVisibleTo(dialog)

    def steps_of(dialog):
        cards = getattr(dialog, '_step_cards', None)
        if cards is None:
            return []
        return [card.findChild(QLabel, 'stepTitle').text() for card in cards.cards]

    def done_flags(dialog):
        cards = getattr(dialog, '_step_cards', None)
        return list(getattr(cards, '_done', []))

    def wait_for(predicate, timeout=25.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def mosi(dialog):
        dialog.resize(1100, 880)
        settle(300)
        first = dialog.provider_list.item(1)      # row 0 is the group header
        check('one-key route (MOSS Pro) listed first', first is not None and
              (first.data(Qt.ItemDataRole.UserRole) or ('', ''))[1] == 'mosi_moss_pro',
              first.text() if first else None)
        titles = steps_of(dialog)
        check('MOSS Pro: picture steps without OSS', titles == ['注册并登录', '创建 API Key', '贴到下面', '检查并保存'], titles)
        check('MOSS Pro: no upload-route field (local file upload)', 'filetrans_upload' not in dialog._fields)
        # The tutorial is a packaged data file (docs/api-setup); a build that
        # leaves it out shows a "not found" line instead (2026-10-14).
        from PySide6.QtWidgets import QTextBrowser
        guide_box = dialog.findChild(QTextBrowser, 'apiSetupGuide')
        guide_text = guide_box.toPlainText() if guide_box is not None else ''
        check('MOSS Pro: the full tutorial is bundled and loaded', len(guide_text) > 500
              and '找不到教程文件' not in guide_text, guide_text[:80])
        url = dialog._fields['url']
        check('MOSS Pro: address prefilled and locked, breakdown hidden', not url.isEnabled()
              and not visible(dialog, dialog.address_view), url.text())
        check('MOSS Pro: page fits without horizontal scrolling', page_fits(dialog))
        grab(dialog, 'M1-mosi')
        key = dialog._fields['api_key']
        key.setFocus()
        key.insert('sk-' + '0' * 24)
        settle()
        check('MOSS Pro: pasting the key ticks off steps 1–3', done_flags(dialog)[:3] == [True, True, True],
              done_flags(dialog))
        QTest.mouseClick(dialog.findChild(QPushButton, 'apiSetupTest_free'), Qt.MouseButton.LeftButton)
        ok = wait_for(lambda: '正在' not in dialog.status.text() and dialog._result_labels['connection'][0].text() != '—')
        mark, detail = dialog._result_labels['connection']
        check('MOSS Pro: offline free check reports the connection, not a key error',
              ok and mark.text() == '✗' and dialog._result_labels['key'][0].text() != '✗', (mark.text(), detail.text()))
        check('MOSS Pro: a failed check does not tick the last step', done_flags(dialog)[-1] is False, done_flags(dialog))
        settle(400)
        rows = [label for _mark, label in dialog._result_labels.values() if label.isVisibleTo(dialog)]
        check('MOSS Pro: result rows get their full text height', all(
            label.height() >= label.heightForWidth(label.width()) - 1 for label in rows),
            [(label.text()[:20], label.height(), label.heightForWidth(label.width())) for label in rows])
        grab(dialog, 'M2-mosi-offline-check')
        dialog.reject()

    def bailian(dialog):
        dialog.resize(1100, 880)
        settle(300)
        titles = steps_of(dialog)
        check('百炼: picture steps include the private OSS step',
              titles == ['注册并登录', '创建 API Key', '建私有 OSS 与 AccessKey', '贴到下面', '检查并保存'], titles)
        upload = dialog._fields['filetrans_upload']
        check('百炼: own OSS preselected (regular route)', upload.currentData() == 'own_oss', upload.currentData())
        check('百炼: OSS fields shown', all(visible(dialog, dialog._fields[k]) for k in ('oss_bucket', 'oss_access_key_id')))
        trial_label = dialog._field_rows['filetrans_upload_trial'][1][0]
        check('百炼: no trial warning while OSS is chosen', not visible(dialog, trial_label))
        check('百炼: page fits without horizontal scrolling', page_fits(dialog))
        grab(dialog, 'B1-bailian-oss')
        upload.setCurrentIndex(upload.findData('provider_temporary'))
        settle()
        check('百炼: choosing the trial upload shows the official warning and hides OSS fields',
              visible(dialog, trial_label) and '请勿用于生产环境' in trial_label.text()
              and not visible(dialog, dialog._fields['oss_bucket']), trial_label.text())
        grab(dialog, 'B2-bailian-trial')
        upload.setCurrentIndex(upload.findData('own_oss'))
        dialog._fields['api_host'].setFocus()
        dialog._fields['api_host'].clear()   # a fresh profile shows the default address
        dialog._fields['api_host'].insert('https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
        dialog._fields['api_key'].setFocus()
        dialog._fields['api_key'].insert('sk-' + '1' * 24)
        settle()
        shown = dialog.address_view.text()
        check('百炼: pasted chat address becomes one line (region · Base URL), full breakdown on hover',
              len(shown.splitlines()) == 1 and shown.endswith('https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1')
              and '/services/audio/asr/transcription' in dialog.address_view.toolTip(), shown)
        QTest.mouseClick(dialog.findChild(QPushButton, 'apiSetupTest_free'), Qt.MouseButton.LeftButton)
        settle(300)
        mark, detail = dialog._result_labels['format']
        check('百炼: missing OSS fields are caught locally before anything is sent',
              mark.text() == '✗' and 'OSS' in detail.text() and not dialog._threads, detail.text())
        grab(dialog, 'B3-bailian-format')
        hints = [label.text() for label in dialog.findChildren(QLabel, 'fieldHint') if visible(dialog, label)]
        check('百炼: field hints are one short line', all(len(text) <= 60 for text in hints if text and '·' not in text),
              [text for text in hints if len(text) > 60])
        dialog.reject()

    def qwen_cloud(dialog):
        dialog.resize(1100, 880)
        settle(300)
        check('Qwen Cloud: own OSS preselected too', dialog._fields['filetrans_upload'].currentData() == 'own_oss')
        url = dialog._fields['url']
        check('Qwen Cloud: address breakdown hidden while locked', not visible(dialog, dialog.address_view))
        unlock = next((b for b in dialog.findChildren(QToolButton) if b.text() == '修改' and visible(dialog, b)), None)
        if unlock is not None:
            QTest.mouseClick(unlock, Qt.MouseButton.LeftButton)
            settle()
        check('Qwen Cloud: “修改” unlocks the address and shows where requests go',
              url.isEnabled() and visible(dialog, dialog.address_view)
              and 'maas.qwencloudapi.com' in dialog.address_view.text(), dialog.address_view.text())
        check('Qwen Cloud: page fits without horizontal scrolling', page_fits(dialog))
        grab(dialog, 'Q1-qwen-cloud')
        dialog.reject()

    def spark(dialog):
        dialog.resize(1100, 880)
        settle(300)
        titles = steps_of(dialog)
        check('讯飞: steps name the three values', titles[:2] == ['注册并登录', '创建应用，复制三项'], titles)
        grab(dialog, 'S1-spark')
        dialog.reject()

    def deepseek(dialog):
        dialog.resize(1100, 880)
        settle(300)
        titles = steps_of(dialog)
        check('DeepSeek (text AI): picture steps with a button to the key page',
              titles == ['注册并登录', '创建 API Key', '贴到“AI 智能断句设置”并测试']
              and dialog._step_cards.buttons[1] is not None
              and 'platform.deepseek.com/api_keys' in dialog._step_cards.buttons[1].toolTip(), titles)
        toggle = dialog.findChild(QPushButton, 'apiSetupDetailsToggle')
        check('DeepSeek: the long tutorial starts collapsed', toggle is not None and not toggle.isChecked())
        check('DeepSeek: page fits without horizontal scrolling', page_fits(dialog))
        grab(dialog, 'T1-deepseek')
        dialog.reject()

    def run_one(act, provider, name, kind='asr'):
        def act_safely(found):
            try:
                act(found)
            except Exception:  # noqa: BLE001 - reported, then closed
                result.setdefault('errors', []).append(dict(name=name, error=traceback.format_exc()[-2000:]))
                found.reject()

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
            for act, provider, name in ((mosi, 'mosi_moss_pro', 'mosi'), (bailian, 'qwen31_filetrans', 'bailian'),
                                        (qwen_cloud, 'qwen_cloud_filetrans', 'qwen-cloud'), (spark, 'spark_asr_v2', 'spark')):
                run_one(act, provider, name)
                settle(200)
            run_one(deepseek, 'deepseek', 'deepseek', 'text')
            settle(200)
            check('no official page was opened during the run (offline)', not opened_urls, opened_urls)
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
