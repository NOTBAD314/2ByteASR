"""「申请与设置 API」 guide: coverage of every exposed provider, dialog behaviour (2026-10-13)."""
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_every_exposed_provider_has_its_own_guide_file():
    from twobyteasr import api_setup_catalog as catalog
    from twobyteasr.llm_config import AI_SERVICE_SPECS
    from twobyteasr.ui import ASR_API_PRESETS
    asr_keys = {guide.key for guide in catalog.ASR_GUIDES}
    assert set(ASR_API_PRESETS) <= asr_keys
    for service in AI_SERVICE_SPECS:
        assert catalog.guide_for(service, 'text') is not None, service
    files = {guide.guide_file for guide in catalog.ALL_GUIDES}
    assert len(files) == len(catalog.ALL_GUIDES)  # one tutorial per provider entry
    for guide in catalog.ALL_GUIDES:
        text = guide.guide_text(ROOT)
        assert not text.startswith('（找不到教程文件'), guide.guide_file
        assert '最后核对：' + catalog.CHECKED in text, guide.guide_file


def test_every_guide_covers_the_eight_required_parts():
    """2026-10-14: what it does, links, steps from zero, activation/payment/storage,
    each field, what is prefilled, what a passing test shows, failures with a next step."""
    from twobyteasr import api_setup_catalog as catalog
    markers = (
        ('在兔白里做什么',),
        ('https://',),
        ('从未注册开始', '从零开始', '从头开始', '跟着做', '第一部分'),
        ('开通', '充值', '付费', '储存', 'OSS'),
        ('每一栏', '栏位'),
        ('已预填', '预填'),
        ('测试会看到什么', '测试时会看到什么', '成功时会看到什么'),
        ('常见失败',),
        ('下一步',),
        ('## 来源',),
    )
    for guide in catalog.ALL_GUIDES:
        text = guide.guide_text(ROOT)
        for options in markers:
            assert any(option in text for option in options), (guide.guide_file, options)
    for name in ('mosi-moss-pro.zh-CN.md', 'bailian-filetrans.zh-CN.md', 'qwen-cloud-filetrans.zh-CN.md'):
        text = (ROOT / 'docs' / 'api-setup' / name).read_text(encoding='utf-8')
        assert '待核实' in text
        # Website, API Host, Base URL and full endpoint are named separately.
        for kind in ('API Host', 'Base URL', '完整请求 Endpoint'):
            assert kind in text
    for name in ('bailian-filetrans.zh-CN.md', 'qwen-cloud-filetrans.zh-CN.md'):
        text = (ROOT / 'docs' / 'api-setup' / name).read_text(encoding='utf-8')
        assert '请勿用于生产环境' in text and '仅供试用' in text  # ADR 0112: the trial upload is labelled


def test_guide_links_are_official_and_dated():
    from twobyteasr import api_setup_catalog as catalog
    official = re.compile(r'^https://([a-z0-9.-]+\.)?(mosi\.cn|aliyun\.com|xfyun\.cn|groq\.com|openai\.com|'
                          r'openrouter\.ai|microsoft\.com|deepseek\.com|google\.dev|x\.ai|qwencloud\.com|'
                          r'alibabacloud\.com|azure\.com|google\.com|chatgpt\.com|antigravity\.google)/')
    for guide in catalog.ALL_GUIDES:
        for link in guide.links:
            assert official.match(link.url), link.url
            assert link.checked == catalog.CHECKED


class Host:
    def __init__(self, models=None):
        self.saved = []
        self.models = models or {}

    def make(self):
        from twobyteasr.api_setup_dialog import SetupHost
        return SetupHost(settings=lambda: {'models': dict(self.models)}, saved_key=lambda provider, url: '',
                         saved_oss_credentials=lambda: ('', ''),
                         save=lambda provider, values, primary: (self.saved.append((provider, values, primary))
                                                                 or (True, '已保存。')))


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_builds_every_provider_page(qapp):
    from PySide6.QtCore import Qt
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='asr', initial='mosi_moss_pro', show_advanced=True)
    seen = []
    for row in range(dialog.provider_list.count()):
        data = dialog.provider_list.item(row).data(Qt.ItemDataRole.UserRole)
        if not data:
            continue
        dialog.provider_list.setCurrentRow(row)
        assert dialog._guide is not None and dialog._guide.key == data[1]
        seen.append(tuple(data))
    assert ('asr', 'mosi_moss_pro') in seen and ('text', 'deepseek') in seen
    dialog.deleteLater()


def test_header_close_has_room_for_its_glyph_and_is_not_the_first_focus(qapp):
    """The × got 16 px padding a side in a 32 px box (no room, nothing painted)
    and the role's minimum height made it 38 px tall; it also took the first
    focus, so the dialog opened with an empty focus ring (2026-10-13)."""
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='asr', initial='qwen_cloud_filetrans')
    dialog.show()
    qapp.processEvents()
    close = next(b for b in dialog.findChildren(QPushButton) if b.text() == '×')
    option = QStyleOptionButton()
    close.initStyleOption(option)
    room = close.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, close)
    glyph = close.fontMetrics().tightBoundingRect('×')
    assert (close.width(), close.height()) == (32, 32)
    assert room.width() >= glyph.width() > 0 and room.height() >= glyph.height() > 0
    assert dialog.focusWidget() is dialog.provider_list
    dialog.close()
    dialog.deleteLater()


def test_bailian_page_turns_any_pasted_host_into_exact_addresses(qapp):
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    host = Host({'qwen_asr_api_provider': 'qwen31_filetrans', 'qwen_asr_api_model': 'qwen-audio-3.1-asr-flash-filetrans',
                 'qwen_asr_api_url': 'https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription',
                 'oss_bucket': '2byte', 'oss_region': 'cn-hangzhou'})
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen31_filetrans')
    assert dialog._value('model') == 'qwen-audio-3.1-asr-flash-filetrans'  # an existing choice is kept
    assert 'dashscope.aliyuncs.com' in dialog._value('api_host')
    dialog._fields['api_host'].setText('https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
    # One line on the page (region · Base URL); the four addresses apart on hover.
    shown = dialog.address_view.text()
    assert shown.splitlines()[0].endswith('https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1')
    text = shown + '\n' + dialog.address_view.toolTip()
    assert 'https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription' in text
    assert '/v1/v1' not in text and 'Base URL' in text and 'API Host' in text
    dialog._fields['api_key'].setText('sk-new')
    # 2026-10-14 (ADR 0112): the regular route is the user's own OSS; the
    # provider's temporary upload is never preselected (official: not for production).
    assert dialog._value('filetrans_upload') == 'own_oss'
    assert dialog.collected()['oss_bucket'] == '2byte'
    upload = dialog._fields['filetrans_upload']
    upload.setCurrentIndex(upload.findData('provider_temporary'))
    assert 'oss_bucket' not in dialog.collected()  # hidden fields are not part of a trial setup
    trial_widgets = dialog._field_rows['filetrans_upload_trial'][1]
    assert '请勿用于生产环境' in trial_widgets[0].text()
    upload.setCurrentIndex(upload.findData('own_oss'))
    dialog._fields['oss_bucket'].setText('my-bucket')
    dialog._save(True)
    provider, values, primary = host.saved[-1]
    assert provider == 'qwen31_filetrans' and primary
    assert values['url'] == 'https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription'
    assert values['oss_endpoint'] == 'https://oss-cn-hangzhou.aliyuncs.com' and values['api_key'] == 'sk-new'
    assert values['filetrans_upload'] == 'own_oss' and values['oss_bucket'] == 'my-bucket'
    dialog.deleteLater()


def test_qwen_cloud_page_needs_only_a_key_and_rejects_other_hosts(qapp):
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    host = Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen_cloud_filetrans')
    assert dialog._guide.key == 'qwen_cloud_filetrans'
    assert dialog._value('model') == 'qwen-audio-3.1-asr-flash-filetrans'
    assert not dialog._fields['url'].isEnabled()  # prefilled official address, unlocked only on request
    assert dialog.address_view in dialog._locked_widgets  # its breakdown appears only after “修改”
    assert 'home.qwencloud.com' in dialog.address_view.toolTip()
    assert dialog._value('filetrans_upload') == 'own_oss'  # Qwen Cloud also needs a URL route (ADR 0112)
    dialog._fields['api_key'].setText('sk-ws-abc')
    values = dialog.collected()
    assert values['url'] == 'https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription'
    dialog._fields['url'].setText('https://llm-abc.cn-beijing.maas.aliyuncs.com')
    with pytest.raises(Exception, match='只接受 Qwen Cloud'):
        dialog.collected()
    dialog._fields['url'].setText('https://dashscope-intl.aliyuncs.com')
    assert dialog.collected()['url'].startswith('https://dashscope-intl.aliyuncs.com/api/v1/')
    dialog._fields['api_key'].setText('sk-sp-plan')
    dialog._run_free()  # format check fails locally; nothing is started
    mark, detail = dialog._result_labels['format']
    assert mark.text() == '✗' and 'Token Plan' in detail.text()
    assert not dialog._threads
    dialog.deleteLater()


def test_mosi_page_prefills_base_url_and_never_doubles_v1(qapp):
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    host = Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='mosi_moss_pro')
    assert dialog._value('url') == 'https://api.mosi.cn/v1'
    assert not dialog._fields['url'].isEnabled()  # prefilled, unlocked only on purpose
    assert 'filetrans_upload' not in dialog._fields  # MOSI takes the local file itself: one key is enough
    assert dialog._guide is catalog_first_asr_guide()
    dialog._fields['url'].setText('https://api.mosi.cn/v1/audio/transcriptions')
    dialog._fields['api_key'].setText('sk-mosi')
    dialog._save(False)
    assert host.saved[-1][1]['url'] == 'https://api.mosi.cn/v1'
    dialog.deleteLater()


def catalog_first_asr_guide():
    from twobyteasr import api_setup_catalog as catalog
    return catalog.ASR_GUIDES[0]


def test_upload_route_is_never_chosen_for_the_user():
    from twobyteasr.api_setup_catalog import resolve_upload_mode, upload_mode_label
    assert resolve_upload_mode({}, 'qwen31_filetrans') == 'missing'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'b'}, 'qwen_cloud_filetrans',
                               has_oss_credentials=False) == 'missing'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'b'}, 'qwen_cloud_filetrans',
                               has_oss_credentials=True) == 'own_oss'
    assert resolve_upload_mode({'filetrans_upload': 'provider_temporary'}, 'qwen_cloud_filetrans') == 'provider_temporary'
    assert '仅供试用' in upload_mode_label('provider_temporary') and '正式' in upload_mode_label('own_oss')


def test_missing_upload_route_stops_before_any_upload(monkeypatch):
    from twobyteasr import llm_config
    from twobyteasr.cloud_api_worker import filetrans_storage
    from twobyteasr.recognition_choices import cloud_asr_readiness, run_disclosure
    monkeypatch.setattr(llm_config, 'read_asr_api_key', lambda provider, url: ('sk-test', 'saved'))
    monkeypatch.setattr(llm_config, 'read_oss_credentials', lambda: ('', ''))
    models = {'qwen_asr_api_provider': 'qwen31_filetrans', 'qwen_asr_api_protocol': 'dashscope_filetrans',
              'qwen_asr_api_url': 'https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription',
              'filetrans_upload': 'auto', 'oss_bucket': ''}
    ready, reason = cloud_asr_readiness(models)
    assert not ready and 'MOSS Pro' in reason and '仅供试用' in reason
    endpoint = {'provider': 'qwen31_filetrans', 'model': 'qwen3-asr-flash-filetrans', 'api_key': 'sk-test',
                'url': models['qwen_asr_api_url']}
    with pytest.raises(Exception) as caught:
        filetrans_storage({'settings': {'models': models}}, endpoint)
    assert caught.value.problem.code == 'upload_route_missing'
    info = run_disclosure({'models': dict(models, primary_asr_backend='api',
                                          qwen_asr_api_model='qwen3-asr-flash-filetrans'), 'switches': {}})
    assert any('开始前会停下' in item for item in info['uploads'])
    trial = run_disclosure({'models': dict(models, primary_asr_backend='api', filetrans_upload='provider_temporary',
                                           qwen_asr_api_model='qwen3-asr-flash-filetrans'), 'switches': {}})
    assert any('仅供试用' in item for item in trial['uploads'])


def test_text_provider_guide_opens_from_cli_service_id(qapp):
    from twobyteasr.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='text', initial='grok_account', show_advanced=True)
    assert dialog._guide.key == 'cli_accounts'
    assert not dialog.save_button.isVisible()
    dialog.deleteLater()


def test_recognition_test_cost_note_never_claims_free():
    from twobyteasr.cloud_api_test import estimate_test_cost
    assert '¥' in estimate_test_cost({'model': 'moss-transcribe-diarize-pro'})
    note = estimate_test_cost({'model': 'qwen3-asr-flash-filetrans'})
    assert '免费' not in note and '无法事先估算' in note
    priced = estimate_test_cost({'model': 'qwen3-asr-flash-filetrans'},
                                {'prices': [{'prices': [{'price': '0.00022', 'price_unit': 'second'}]}]})
    assert '¥0.0013' in priced


def test_bailian_free_check_uses_official_model_list(monkeypatch):
    from twobyteasr.cloud_api_test import PASS, FAIL, free_checks

    class Response:
        def __init__(self, code, body):
            self.status_code, self.body = code, body

        def json(self):
            return self.body

    calls = []

    class Client:
        def __init__(self, code, body):
            self.code, self.body = code, body

        def get(self, url, **kw):
            calls.append((url, kw.get('params')))
            return Response(self.code, self.body)

    endpoint = dict(protocol='dashscope_filetrans', model='qwen3-asr-flash-filetrans', api_key='sk',
                    url='https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription')
    ok = free_checks(endpoint, client=Client(200, {'output': {'models': [
        {'model': 'qwen3-asr-flash-filetrans', 'prices': [{'prices': [{'price': '1', 'price_unit': 'second'}]}]}]}}))
    assert calls[-1] == ('https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/models', {'model': 'qwen3-asr-flash-filetrans'})
    assert ok.status('connection') == PASS and ok.status('key') == PASS and ok.status('model') == PASS
    denied = free_checks(dict(endpoint, url='https://llm-abc.ap-southeast-1.maas.aliyuncs.com/api/v1'),
                         client=Client(401, {'code': 'InvalidApiKey'}))
    assert denied.status('key') == FAIL and '同一地域' in next(c.detail for c in denied.checks if c.level == 'key')
    missing = free_checks(endpoint, client=Client(200, {'output': {'models': []}}))
    assert missing.status('model') == FAIL


def test_run_disclosure_names_engine_uploads_and_timestamp_source():
    from twobyteasr.recognition_choices import disclosure_text, run_disclosure
    settings = {'models': {'primary_asr_backend': 'api', 'qwen_asr_api_provider': 'mosi_moss_pro',
                           'qwen_asr_api_model': 'moss-transcribe-diarize-pro', 'qwen_asr_api_url': 'https://api.mosi.cn/v1',
                           'firered_asr_backend': 'off', 'qwen_asr_backend': 'off'}, 'switches': {}}
    info = run_disclosure(settings)
    assert 'api.mosi.cn' in info['uploads'][0] and '句段' in info['timestamps'] and info['paid']
    settings['models']['firered_asr_backend'] = 'qwen_aligner'
    assert '对齐模型实测' in run_disclosure(settings)['timestamps']
    local = {'models': {'primary_asr_backend': 'sensevoice', 'firered_asr_backend': 'off', 'qwen_asr_backend': 'off'},
             'switches': {}}
    text = disclosure_text(local)
    assert '不上传' in text and '不会自动改用' in text


def test_cloud_followups_only_change_what_cannot_run():
    from twobyteasr.recognition_choices import HostProfile, cloud_followups
    no_gpu = HostProfile('win32', 'amd64', nvidia_tool=False, main_runtime=True, mlx_runtime=False)
    patch, notes = cloud_followups({'firered_asr_backend': 'local', 'qwen_asr_backend': 'local'},
                                   {'firered_aed', 'qwen_aligner'}, no_gpu)
    assert patch == {'firered_asr_backend': 'qwen_aligner', 'qwen_asr_backend': 'off'} and notes
    gpu = HostProfile('win32', 'amd64', nvidia_tool=True, main_runtime=True, mlx_runtime=False)
    assert cloud_followups({'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}, {'firered_aed'}, gpu)[0] == {}
    mac = HostProfile('darwin', 'arm64', nvidia_tool=False, main_runtime=False, mlx_runtime=False)
    assert cloud_followups({'firered_asr_backend': 'local'}, {'firered_aed'}, mac)[0] == {'firered_asr_backend': 'off'}
