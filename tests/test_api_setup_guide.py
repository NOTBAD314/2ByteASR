"""「申请与设置 API」 guide: coverage of every exposed provider, dialog behaviour (2026-10-13)."""
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_every_exposed_provider_has_its_own_guide_file():
    from twobyteasr.providers import api_setup_catalog as catalog
    from twobyteasr.providers.llm_config import AI_SERVICE_SPECS
    from twobyteasr.app.ui import ASR_API_PRESETS
    asr_keys = {guide.key for guide in catalog.ASR_GUIDES}
    assert set(ASR_API_PRESETS) <= asr_keys
    for service in AI_SERVICE_SPECS:
        assert catalog.guide_for(service, 'text') is not None, service
    files = {guide.guide_file for guide in catalog.ALL_GUIDES}
    assert len(files) == len(catalog.ALL_GUIDES)  # one tutorial per provider entry
    for guide in catalog.ALL_GUIDES:
        text = guide.guide_text(ROOT)
        assert not text.startswith('（找不到教程文件'), guide.guide_file
        # A guide is dated by its own links (2026-10-18: Claude, checked that day).
        dates = {link.checked for link in guide.links} or {catalog.CHECKED}
        assert len(dates) == 1, guide.guide_file
        assert '最后核对：' + dates.pop() in text, guide.guide_file


def test_every_guide_covers_the_eight_required_parts():
    """2026-10-14: what it does, links, steps from zero, activation/payment/storage,
    each field, what is prefilled, what a passing test shows, failures with a next step."""
    from twobyteasr.providers import api_setup_catalog as catalog
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
    for name in ('bailian-filetrans.zh-CN.md', 'qwen-cloud-filetrans.zh-CN.md', 'qianwen-filetrans.zh-CN.md'):
        text = (ROOT / 'docs' / 'api-setup' / name).read_text(encoding='utf-8')
        # 2026-10-28: the temporary space is the default, its official limit quoted; own OSS stays a choice.
        assert '不用建 OSS' in text and '请勿用于生产环境' in text and '自己的 OSS' in text, name
        assert '仅供试用' not in text, name


def test_guide_links_are_official_and_dated():
    from twobyteasr.providers import api_setup_catalog as catalog
    official = re.compile(r'^https://([a-z0-9.-]+\.)?(mosi\.cn|aliyun\.com|xfyun\.cn|groq\.com|openai\.com|'
                          r'openrouter\.ai|microsoft\.com|deepseek\.com|google\.dev|x\.ai|qwencloud\.com|'
                          r'alibabacloud\.com|azure\.com|google\.com|chatgpt\.com|antigravity\.google|'
                          r'claude\.com|anthropic\.com)/')
    for guide in catalog.ALL_GUIDES:
        for link in guide.links:
            assert official.match(link.url), link.url
            assert link.checked == (guide.links[0].checked if guide.key == 'claude' else catalog.CHECKED)


class Host:
    def __init__(self, models=None, oss=('', '')):
        self.saved = []
        self.models = models or {}
        self.oss = oss

    def make(self):
        from twobyteasr.providers.api_setup_dialog import SetupHost
        return SetupHost(settings=lambda: {'models': dict(self.models)}, saved_key=lambda provider, url: '',
                         saved_oss_credentials=lambda: self.oss,
                         save=lambda provider, values, primary: (self.saved.append((provider, values, primary))
                                                                 or (True, '已保存。')))


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_builds_every_provider_page(qapp):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='asr', initial='mosi_moss_pro', show_advanced=True)
    seen = dialog.provider_choices()
    for kind, key in seen:
        dialog.choose(kind, key)
        assert dialog._guide is not None and (dialog._guide.kind, dialog._guide.key) == (kind, key)
        assert dialog.stack.count() >= 2  # its steps (or form / notes) plus 看完整教程
    assert ('asr', 'mosi_moss_pro') in seen and ('text', 'deepseek') in seen
    assert ('asr', 'custom') in seen and ('text', 'cli_accounts') in seen  # 进阶 entries shown on request
    dialog.deleteLater()


def test_header_close_has_room_for_its_glyph_and_is_not_the_first_focus(qapp):
    """The × got 16 px padding a side in a 32 px box (no room, nothing painted)
    and the role's minimum height made it 38 px tall; it also took the first
    focus, so the dialog opened with an empty focus ring (2026-10-13)."""
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
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
    # 2026-10-18: it opens on step 1, focus on the button that opens the official page.
    assert dialog.focusWidget() is not close and dialog.focusWidget().objectName() == 'apiSetupOpen_0'
    dialog.close()
    dialog.deleteLater()


def test_bailian_page_turns_any_pasted_host_into_exact_addresses(qapp):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
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
    # A saved bucket whose AccessKey is gone opens on own OSS (with “建 OSS”), so the missing fields show.
    assert dialog._value('filetrans_upload') == 'own_oss'
    assert [step.role for step in dialog._walk] == ['account', 'key', 'storage', 'paste']
    assert dialog.collected()['oss_bucket'] == '2byte'
    upload = dialog._fields['filetrans_upload']
    upload.setCurrentIndex(upload.findData('provider_temporary'))
    assert 'oss_bucket' not in dialog.collected()  # hidden fields are not part of this setup
    note = dialog._field_rows['filetrans_upload_note'][1][0]
    assert '48 小时' in note.text() and '自己的 OSS' in note.text()
    assert [step.role for step in dialog._walk] == ['account', 'key', 'paste']
    upload.setCurrentIndex(upload.findData('own_oss'))
    dialog._fields['oss_bucket'].setText('my-bucket')
    dialog._save(True)
    provider, values, primary = host.saved[-1]
    assert provider == 'qwen31_filetrans' and primary
    assert values['url'] == 'https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription'
    assert values['oss_endpoint'] == 'https://oss-cn-hangzhou.aliyuncs.com' and values['api_key'] == 'sk-new'
    assert values['filetrans_upload'] == 'own_oss' and values['oss_bucket'] == 'my-bucket'
    dialog.deleteLater()


def test_qwen_cloud_page_needs_only_a_key_and_rejects_other_hosts(qapp, monkeypatch):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    # The international site (2026-10-25: Simplified Chinese starts on 千问AI平台 instead).
    monkeypatch.setattr('twobyteasr.i18n.current_language', lambda: 'en')
    host = Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen_cloud_filetrans')
    assert dialog._guide.key == 'qwen_cloud_filetrans'
    assert dialog._value('model') == 'qwen-audio-3.1-asr-flash-filetrans'
    assert not dialog._fields['url'].isEnabled()  # prefilled official address, unlocked only on request
    assert dialog.address_view in dialog._locked_widgets  # its breakdown appears only after “修改”
    assert 'home.qwencloud.com' in dialog.address_view.toolTip()
    # 2026-10-28: the provider's temporary space by default; no OSS step.
    assert dialog._value('filetrans_upload') == 'provider_temporary'
    assert [step.role for step in dialog._walk] == ['account', 'topup', 'key', 'paste']
    dialog._fields['api_key'].setText('sk-ws-abc')
    values = dialog.collected()
    assert values['url'] == 'https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription'
    dialog._fields['url'].setText('https://llm-abc.cn-beijing.maas.aliyuncs.com')
    with pytest.raises(Exception, match='只接受千问AI平台或 Qwen Cloud'):
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
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
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
    from twobyteasr.providers import api_setup_catalog as catalog
    return catalog.ASR_GUIDES[0]


def test_upload_route_defaults_to_the_providers_temporary_space():
    """2026-10-28 (the user): no OSS by default; own OSS stays a choice and an existing setup keeps it."""
    from twobyteasr.providers.api_setup_catalog import resolve_upload_mode, upload_mode_label
    assert resolve_upload_mode({}, 'qwen31_filetrans') == 'provider_temporary'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': ''}, 'qwen_cloud_filetrans',
                               has_oss_credentials=True) == 'provider_temporary'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'b'}, 'qwen_cloud_filetrans',
                               has_oss_credentials=False) == 'missing'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'b'}, 'qwen_cloud_filetrans',
                               has_oss_credentials=True) == 'own_oss'
    assert resolve_upload_mode({'filetrans_upload': 'own_oss'}, 'qwen31_filetrans') == 'own_oss'
    assert resolve_upload_mode({'filetrans_upload': 'provider_temporary', 'oss_bucket': 'b'}, 'qwen31_filetrans',
                               has_oss_credentials=True) == 'provider_temporary'
    assert '48 小时' in upload_mode_label('provider_temporary') and 'OSS' in upload_mode_label('own_oss')
    assert '仅供试用' not in upload_mode_label('provider_temporary')


BAILIAN_URL = 'https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription'


def bailian_models(**extra):
    return dict({'qwen_asr_api_provider': 'qwen31_filetrans', 'qwen_asr_api_protocol': 'dashscope_filetrans',
                 'qwen_asr_api_url': BAILIAN_URL, 'filetrans_upload': 'auto', 'oss_bucket': ''}, **extra)


BAILIAN_ENDPOINT = {'provider': 'qwen31_filetrans', 'model': 'qwen3-asr-flash-filetrans', 'api_key': 'sk-test',
                    'url': BAILIAN_URL}


def test_recognition_without_oss_uses_the_temporary_space(monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.cloud_api_worker import filetrans_storage
    from twobyteasr.providers.dashscope_service import DashScopeTemporaryStorage
    from twobyteasr.recognition.recognition_choices import cloud_asr_readiness, run_disclosure
    monkeypatch.setattr(llm_config, 'read_asr_api_key', lambda provider, url: ('sk-test', 'saved'))
    monkeypatch.setattr(llm_config, 'read_oss_credentials', lambda: ('', ''))
    models = bailian_models()
    assert cloud_asr_readiness(models) == (True, '')
    storage = filetrans_storage({'settings': {'models': models}}, BAILIAN_ENDPOINT)
    assert isinstance(storage, DashScopeTemporaryStorage)
    assert storage.root == 'https://llm-abc.cn-beijing.maas.aliyuncs.com' and storage.model == 'qwen3-asr-flash-filetrans'
    info = run_disclosure({'models': dict(models, primary_asr_backend='api',
                                          qwen_asr_api_model='qwen3-asr-flash-filetrans'), 'switches': {}})
    assert any('服务商临时空间' in item and '48 小时' in item for item in info['uploads'])


def test_half_set_oss_stops_before_any_upload(monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.cloud_api_worker import filetrans_storage
    from twobyteasr.recognition.recognition_choices import cloud_asr_readiness, run_disclosure
    monkeypatch.setattr(llm_config, 'read_asr_api_key', lambda provider, url: ('sk-test', 'saved'))
    monkeypatch.setattr(llm_config, 'read_oss_credentials', lambda: ('', ''))
    models = bailian_models(oss_bucket='mine')
    ready, reason = cloud_asr_readiness(models)
    assert not ready and 'AccessKey' in reason and '服务商临时空间' in reason
    with pytest.raises(Exception) as caught:
        filetrans_storage({'settings': {'models': models}}, BAILIAN_ENDPOINT)
    assert caught.value.problem.code == 'upload_route_missing'
    info = run_disclosure({'models': dict(models, primary_asr_backend='api',
                                          qwen_asr_api_model='qwen3-asr-flash-filetrans'), 'switches': {}})
    assert any('开始前会停下' in item for item in info['uploads'])


def test_own_oss_setup_keeps_its_route(monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.cloud_api_worker import filetrans_storage
    from twobyteasr.providers.temp_audio_storage import OssTemporaryStorage
    from twobyteasr.recognition.recognition_choices import cloud_asr_readiness, run_disclosure
    monkeypatch.setattr(llm_config, 'read_asr_api_key', lambda provider, url: ('sk-test', 'saved'))
    monkeypatch.setattr(llm_config, 'read_oss_credentials', lambda: ('LTAIid', 'secret'))
    for choice in ('auto', 'own_oss'):   # an older setup (auto) and one chosen in the guide
        models = bailian_models(filetrans_upload=choice, oss_bucket='mine', oss_region='cn-hangzhou',
                                oss_endpoint='https://oss-cn-hangzhou.aliyuncs.com')
        assert cloud_asr_readiness(models) == (True, ''), choice
        request = {'settings': {'models': models}, 'storage_credentials': ('LTAIid', 'secret')}
        assert isinstance(filetrans_storage(request, BAILIAN_ENDPOINT), OssTemporaryStorage), choice
        info = run_disclosure({'models': dict(models, primary_asr_backend='api',
                                              qwen_asr_api_model='qwen3-asr-flash-filetrans'), 'switches': {}})
        assert any('你的 OSS 私有存储：mine' in item for item in info['uploads']), choice


def test_filetrans_walkthrough_has_no_oss_step_unless_chosen():
    from twobyteasr.providers import api_setup_catalog as catalog
    guides = [catalog.guide_for('qwen31_filetrans'), catalog.QIANWEN_FILETRANS_GUIDE, catalog.QWEN_SITE_GUIDES['intl']]
    for guide in guides:
        plain = catalog.walkthrough(guide)
        assert 'storage' not in [step.role for step in plain] and plain[-1].title == '把 Key 贴到这里', guide.title
        own = catalog.walkthrough(guide, own_storage=True)
        assert [step.role for step in own][-2:] == ['storage', 'paste'], guide.title
        assert 'oss.console' in own[-2].url and own[-1].title == '贴上 Key 和存储信息'
        assert guide.tag == '不用建 OSS' and '不用建 OSS' in guide.role
        upload = next(f for f in guide.fields if f.key == 'filetrans_upload')
        assert upload.prefilled == 'provider_temporary'
    assert [step.label for step in catalog.walkthrough(guides[0])] == ['注册登录', '创建 Key', '贴上检查']


def test_choosing_own_oss_adds_the_oss_step_and_back(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    host = Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen31_filetrans')
    dialog.show()
    qapp.processEvents()
    assert [label.text() for label in dialog.progress.labels] == ['注册登录', '创建 Key', '贴上检查']
    dialog._go(len(dialog._walk) - 1)
    upload = dialog._fields['filetrans_upload']
    assert upload.currentData() == 'provider_temporary'
    assert not dialog._fields['oss_bucket'].isVisible() and not dialog.oss_button.isVisible()
    assert dialog._field_rows['filetrans_upload_note'][1][0].isVisible()
    link = dialog._field_rows['filetrans_upload_oss_step'][1][0]
    assert not link.isVisible()

    upload.setCurrentIndex(upload.findData('own_oss'))
    qapp.processEvents()
    assert [label.text() for label in dialog.progress.labels] == ['注册登录', '创建 Key', '建 OSS', '贴上检查']
    assert dialog._page_kind == 'paste' and dialog._index == 3 and dialog.stack.currentWidget() is dialog._pages[3]
    assert dialog._fields['oss_bucket'].isVisible() and dialog.oss_button.isVisible() and link.isVisible()
    texts = [page.findChild(QLabel, 'apiSetupStepOf').text() for page in dialog._pages]
    assert texts == ['第 1 步，共 4 步', '第 2 步，共 4 步', '第 3 步，共 4 步', '第 4 步，共 4 步']
    assert dialog._pages[3].findChild(QLabel, 'apiSetupStepTitle').text() == '贴上 Key 和存储信息'
    link.click()
    assert dialog._page_kind == 'step' and dialog._index == 2
    opener = dialog._pages[2].findChild(QPushButton, 'apiSetupOpen_2')
    assert opener is not None and opener.text() == '打开 OSS 控制台' and 'oss.console.aliyun.com' in opener.toolTip()
    dialog._finish_step(2)
    assert dialog._page_kind == 'paste' and dialog._index == 3

    upload.setCurrentIndex(upload.findData('provider_temporary'))
    qapp.processEvents()
    assert [label.text() for label in dialog.progress.labels] == ['注册登录', '创建 Key', '贴上检查']
    assert len(dialog._pages) == len(dialog._done) == 3 and dialog._index == 2
    assert dialog._pages[2].findChild(QLabel, 'apiSetupStepOf').text() == '第 3 步，共 3 步'
    assert dialog._pages[2].findChild(QLabel, 'apiSetupStepTitle').text() == '把 Key 贴到这里'
    dialog._back()
    assert dialog._index == 1 and dialog._walk[1].role == 'key'

    dialog._fields['api_host'].setText('llm-abc.cn-beijing.maas.aliyuncs.com')
    dialog._fields['api_key'].setText('sk-new')
    dialog._save(False)
    provider, values, _primary = host.saved[-1]
    assert provider == 'qwen31_filetrans' and values['filetrans_upload'] == 'provider_temporary'
    assert not [key for key in values if key.startswith('oss_') and key != 'oss_auto_delete']
    dialog.close()
    dialog.deleteLater()


def test_filetrans_guide_strings_are_translated_in_every_ui_language():
    """2026-10-28: the new default's words (choices, note, link, tag, steps) exist in each catalog."""
    from twobyteasr import i18n
    from twobyteasr.providers import api_setup_catalog as catalog
    guides = [catalog.guide_for('qwen31_filetrans'), catalog.QIANWEN_FILETRANS_GUIDE, catalog.QWEN_SITE_GUIDES['intl']]
    texts = {catalog.TEMPORARY_UPLOAD_NOTE, catalog.OWN_OSS_STEP_LINK, catalog._UPLOAD_HINT,
             catalog.MISSING_UPLOAD_MESSAGE, '音频会先上传到服务商临时空间（48 小时后由服务商自动删除），再提交识别。'}
    texts |= {label for _value, label in catalog.UPLOAD_CHOICES}
    for guide in guides:
        texts |= {guide.role, guide.tag, guide.uploads}
        if guide.key == 'qwen_cloud_filetrans':
            texts.add(guide.account_note)   # 百炼's note did not change (and has no translation yet)
    steps = set()
    for guide in guides:
        for own in (False, True):
            for step in catalog.walkthrough(guide, own_storage=own):
                steps |= {text for text in (step.label, step.title, step.note, step.action, *step.lines) if text}
    cjk = re.compile(r'[一-鿿]')
    for language in i18n.TRANSLATED_LANGUAGES:
        table = i18n.language_table(language)
        missing = sorted(text for text in texts | steps if text not in table)
        assert not missing, (language, missing)
        if language not in {'ja', 'zh-Hant'}:
            # This round's words read without Chinese (step lines may quote a site's Chinese button names).
            leftovers = sorted(text for text in texts if cjk.search(table[text]))
            assert not leftovers, (language, leftovers)


def test_filetrans_guide_reads_in_english(qapp, monkeypatch):
    from PySide6.QtWidgets import QComboBox
    from twobyteasr import i18n
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    monkeypatch.setattr(i18n, '_CURRENT_LANGUAGE_CACHE', 'en')
    dialog = ApiSetupDialog(None, Host().make(), kind='asr', initial='qwen31_filetrans')
    assert [label.text() for label in dialog.progress.labels] == ['Sign up', 'Create key', 'Paste & check']
    upload = dialog._fields['filetrans_upload']
    assert isinstance(upload, QComboBox) and upload.currentText().startswith("Provider's temporary storage")
    assert [upload.itemText(i) for i in range(upload.count())][1].startswith('My own private Alibaba Cloud OSS')
    note = dialog._field_rows['filetrans_upload_note'][1][0].text()
    link = dialog._field_rows['filetrans_upload_oss_step'][1][0].text()
    assert '48 hours' in note and link.startswith('No OSS yet?')
    upload.setCurrentIndex(upload.findData('own_oss'))
    assert [label.text() for label in dialog.progress.labels] == ['Sign up', 'Create key', 'Set up OSS', 'Paste & check']
    dialog.deleteLater()


def test_existing_oss_user_keeps_the_oss_step_and_route(qapp):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    host = Host({'qwen_asr_api_provider': 'qwen31_filetrans', 'filetrans_upload': 'auto', 'oss_bucket': 'mine',
                 'oss_region': 'cn-hangzhou'}, oss=('LTAIid', 'secret'))
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen31_filetrans')
    assert dialog._value('filetrans_upload') == 'own_oss'
    assert [step.label for step in dialog._walk] == ['注册登录', '创建 Key', '建 OSS', '贴上检查']
    dialog._fields['api_host'].setText('llm-abc.cn-beijing.maas.aliyuncs.com')
    dialog._fields['api_key'].setText('sk-new')
    dialog._save(False)
    values = host.saved[-1][1]
    assert values['filetrans_upload'] == 'own_oss' and values['oss_bucket'] == 'mine'
    dialog.deleteLater()


def test_text_provider_guide_opens_from_cli_service_id(qapp):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='text', initial='grok_account', show_advanced=True)
    assert dialog._guide.key == 'cli_accounts'
    assert not dialog.save_button.isVisible()
    dialog.deleteLater()


def test_recognition_test_cost_note_never_claims_free():
    from twobyteasr.providers.cloud_api_test import estimate_test_cost
    assert '¥' in estimate_test_cost({'model': 'moss-transcribe-diarize-pro'})
    note = estimate_test_cost({'model': 'qwen3-asr-flash-filetrans'})
    assert '免费' not in note and '无法事先估算' in note
    priced = estimate_test_cost({'model': 'qwen3-asr-flash-filetrans'},
                                {'prices': [{'prices': [{'price': '0.00022', 'price_unit': 'second'}]}]})
    assert '¥0.0013' in priced


def test_bailian_free_check_uses_official_model_list(monkeypatch):
    from twobyteasr.providers.cloud_api_test import PASS, FAIL, free_checks

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
    from twobyteasr.recognition.recognition_choices import disclosure_text, run_disclosure
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
    from twobyteasr.recognition.recognition_choices import HostProfile, cloud_followups
    no_gpu = HostProfile('win32', 'amd64', nvidia_tool=False, main_runtime=True, mlx_runtime=False)
    patch, notes = cloud_followups({'firered_asr_backend': 'local', 'qwen_asr_backend': 'local'},
                                   {'firered_aed', 'qwen_aligner'}, no_gpu)
    assert patch == {'firered_asr_backend': 'qwen_aligner', 'qwen_asr_backend': 'off'} and notes
    gpu = HostProfile('win32', 'amd64', nvidia_tool=True, main_runtime=True, mlx_runtime=False)
    assert cloud_followups({'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}, {'firered_aed'}, gpu)[0] == {}
    mac = HostProfile('darwin', 'arm64', nvidia_tool=False, main_runtime=False, mlx_runtime=False)
    assert cloud_followups({'firered_asr_backend': 'local'}, {'firered_aed'}, mac)[0] == {'firered_asr_backend': 'off'}


# ---------------------------------------------------------------- 2026-10-18 walkthrough

def test_walkthrough_steps_follow_the_official_pages():
    from twobyteasr.providers import api_setup_catalog as catalog
    roles = {(g.kind, g.key): [s.role for s in catalog.walkthrough(g)] for g in catalog.ALL_GUIDES}
    # User (2026-10-18): MOSI gives free credit, so trying it needs no top-up step.
    assert roles[('asr', 'mosi_moss_pro')] == ['account', 'key', 'paste']
    # User (2026-10-28): 录音文件识别 uses the provider's temporary space by default; “建 OSS” only for own OSS.
    assert roles[('asr', 'qwen31_filetrans')] == ['account', 'key', 'paste']
    assert roles[('asr', 'qwen_cloud_filetrans')] == ['account', 'topup', 'key', 'paste']
    assert [s.role for s in catalog.walkthrough(catalog.guide_for('qwen31_filetrans'), own_storage=True)] == [
        'account', 'key', 'storage', 'paste']
    assert roles[('text', 'deepseek')] == ['account', 'topup', 'key', 'fill']
    assert roles[('asr', 'custom')] == [] and roles[('text', 'cli_accounts')] == []
    for guide in catalog.ALL_GUIDES:
        links = {link.url for link in guide.links}
        for step in catalog.walkthrough(guide) + catalog.walkthrough(guide, own_storage=True):
            assert not step.url or step.url in links  # every button opens a catalogued official page
            # Lines are broken by hand: short phrases (about 16 Chinese characters), never one long sentence.
            widths = [sum(2 if ord(ch) > 0x2E7F else 1 for ch in line) for line in step.lines]
            assert all(width <= 32 for width in widths), (guide.key, step.lines)
            assert step.label and step.title
        if catalog.walkthrough(guide) and guide.kind == 'asr' and not guide.advanced_only:
            assert guide.minutes and guide.money and guide.tag, guide.key   # the honest line on top


def test_mosi_walkthrough_says_free_credit_and_rings_real_screenshots():
    from twobyteasr.providers import api_setup_catalog as catalog
    guide = catalog.guide_for('mosi_moss_pro', 'asr')
    account, key, paste = catalog.walkthrough(guide)
    assert '50 积分' in account.note and account.note_kind == 'free'
    assert '免费' in guide.money and '¥2' in guide.after_note   # top up later, said plainly
    for step in (account, key):
        assert step.shot is not None
    assert paste.title == '把 Key 贴到这里'


def test_every_screenshot_shows_the_page_its_button_opens():
    """2026-10-18: official-site pictures; signed-in ones were taken in the user's session, keys blocked out."""
    from PIL import Image
    from twobyteasr.providers import api_setup_catalog as catalog
    shots = 0
    guides = catalog.ALL_GUIDES + (catalog.QWEN_SITE_GUIDES['cn'],)   # 千问AI平台 shares Qwen Cloud's row (2026-10-25)
    for guide in guides:
        for step in catalog.walkthrough(guide):
            shot = step.shot
            if shot is None:
                continue
            shots += 1
            assert shot.source == step.url, (guide.key, step.role)   # the picture is the page the button opens
            assert shot.path(ROOT).is_file() and shot.captured, shot.file
            width, height = Image.open(shot.path(ROOT)).size
            assert abs(width / height - 1.6) < 0.01 and width >= 470, shot.file   # 16:10, as ShotView draws it
            x, y, w, h = shot.ring
            assert 0 <= x and 0 <= y and x + w <= 1 and y + h <= 1, shot.file
    assert shots >= 10
    used = {step.shot.file for guide in guides for step in catalog.walkthrough(guide) if step.shot}
    assert {path.name for path in (ROOT / 'assets' / 'api-setup').iterdir()} == used   # no stale pictures


def test_saved_key_opens_on_paste_and_ticks_the_web_steps(qapp):
    from dataclasses import replace
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    host = replace(Host().make(), saved_key=lambda provider, url: 'sk-saved-abcd')
    dialog = ApiSetupDialog(None, host, kind='asr', initial='mosi_moss_pro')
    assert dialog._page_kind == 'paste' and dialog._done[:2] == [True, True] and dialog._done[2] is False
    assert '···abcd' in dialog._fields['api_key'].placeholderText()
    dialog.deleteLater()


def test_steps_advance_and_a_passing_check_leads_to_saving(qapp):
    from twobyteasr.providers import cloud_api_test as tests
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    host = Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='mosi_moss_pro')
    assert dialog._page_kind == 'step' and dialog._index == 0
    assert not dialog.save_button.isVisibleTo(dialog) and dialog.skip_button.isVisibleTo(dialog)
    dialog._finish_step(0)
    assert dialog._index == 1 and dialog._done[0]
    dialog.skip_button.click()
    assert dialog._page_kind == 'paste' and dialog.save_primary_button.property('buttonRole') == 'secondary'
    # Model and the prefilled address fold into “更多设置”; the key does not.
    assert dialog._more_box.isAncestorOf(dialog._fields['model'])
    assert dialog._more_box.isAncestorOf(dialog._fields['url'])
    assert not dialog._more_box.isAncestorOf(dialog._fields['api_key'])
    failed = tests.Report().add('format', tests.PASS, '').add('connection', tests.FAIL, '连不上').add('key', tests.SKIP, '')
    dialog._show_report(failed)
    assert dialog._page_kind == 'paste' and dialog._results_box.isVisibleTo(dialog)
    passed = tests.Report().add('format', tests.PASS, '').add('connection', tests.PASS, '').add('key', tests.PASS, '')
    dialog._fields['api_key'].setText('sk-mosi')
    dialog._show_report(passed)
    assert dialog._page_kind == 'done' and all(dialog._done)
    assert dialog.save_primary_button.property('buttonRole') == 'primary'
    dialog._back()
    assert dialog._page_kind == 'paste'   # 返回修改
    dialog._save(True)
    assert host.saved[-1][0] == 'mosi_moss_pro' and host.saved[-1][2] is True
    dialog.deleteLater()


def test_text_ai_last_step_opens_the_ai_settings(qapp):
    from dataclasses import replace
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    opened = []
    host = replace(Host().make(), open_text_settings=opened.append)
    dialog = ApiSetupDialog(None, host, kind='text', initial='deepseek')
    topup = dialog._walk[1]
    assert topup.role == 'topup' and '10 元' in topup.title and topup.url.endswith('/top_up')
    dialog._go(len(dialog._walk) - 1)
    assert dialog._page_kind == 'fill'
    dialog.stack.currentWidget().findChild(QPushButton, 'apiSetupFill').click()
    assert opened == ['deepseek']
    dialog.deleteLater()


def test_provider_menu_lists_services_with_a_few_honest_words(qapp):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    dialog = ApiSetupDialog(None, Host().make(), kind='asr', initial='mosi_moss_pro')
    dialog._fill_provider_menu()
    texts = [action.text() for action in dialog.provider_menu.actions()]
    assert any(text.startswith('MOSS 云端识别\t只要一把 Key') for text in texts)
    assert '更多：自架接口、待验证服务' in texts and ('asr', 'custom') not in dialog.provider_choices()
    current = next(a for a in dialog.provider_menu.actions() if a.data() == ('asr', 'mosi_moss_pro'))
    assert current.isChecked()
    next(a for a in dialog.provider_menu.actions() if a.data() == ('text', 'gemini')).trigger()
    assert dialog._guide.key == 'gemini' and dialog._page_kind == 'step'
    dialog.deleteLater()
