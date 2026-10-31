"""MAI-Transcribe 2 through OpenRouter, and the 千问AI平台 / Qwen Cloud site switch (2026-10-25).

MAI: OpenRouter's current Microsoft transcription model is
``microsoft/mai-transcribe-2`` (there is no "MAI 2.1"); the card is named after
it, the preset fills it in, and nothing refuses it any more. Its word list has
no punctuation and no spaces, so English words are joined with spaces while
Chinese characters stay together (real response, 2026-10-25).

Qwen: one entry with two official sites, 千问AI平台 (maas.qianwenaiapi.com,
Beijing) and Qwen Cloud (maas.qwencloudapi.com, Singapore). The saved address
says which one is in use; without one the Simplified Chinese interface starts
on 千问AI平台.
"""
import pytest

CN_URL = 'https://maas.qianwenaiapi.com/api/v1/services/audio/asr/transcription'
INTL_URL = 'https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription'


# ----------------------------------------------------------------- MAI

def test_mai_preset_card_and_validation_use_mai_transcribe_2():
    from twobyteasr.app.ui import ASR_API_PRESETS
    from twobyteasr.local_models.model_workshop import MODELS
    from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint
    preset = ASR_API_PRESETS['openrouter_word']
    assert preset['model'] == 'microsoft/mai-transcribe-2'
    assert '2.1' not in preset['label'] and 'MAI-Transcribe 2' in preset['label']
    assert '2.1' not in ASR_API_PRESETS['azure']['label']
    card = next(model for model in MODELS if model.key == 'mai_latest')
    assert card.name == 'MAI-Transcribe 2' and 'microsoft/mai-transcribe-2' in card.summary
    assert {'TIMESTAMP', 'DIARIZATION'} <= set(card.asr_capabilities)
    validate_qwen_asr_endpoint(dict(provider='openrouter_word', protocol=preset['protocol'], url=preset['url'],
                                    model='microsoft/mai-transcribe-2', api_key='sk-or-test'))


@pytest.mark.parametrize('provider', ['openrouter_word', 'azure'])
def test_saved_mai_transcribe_2_is_kept_when_settings_load(provider):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, {'models': {
        'qwen_asr_api_provider': provider, 'qwen_asr_api_model': 'microsoft/mai-transcribe-2',
        'qwen_asr_api_protocol': 'openrouter_verbose_json' if provider == 'openrouter_word' else 'azure_transcription'}})
    assert settings['models']['qwen_asr_api_model'] == 'microsoft/mai-transcribe-2'
    assert not any('MAI' in warning for warning in warnings)


def test_mai_card_with_a_saved_key_is_usable(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    from pathlib import Path
    monkeypatch.setattr('twobyteasr.providers.llm_config.read_asr_api_key', lambda *a: ('saved-key', 'test'))
    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(Path(__file__).resolve().parents[1],
                             {'models': {'qwen_asr_api_provider': 'openrouter_word',
                                         'qwen_asr_api_model': 'microsoft/mai-transcribe-2',
                                         'primary_asr_backend': 'api'}})
    assert page._model_state(page._cards['mai_latest'].model) in {'selected', 'configured'}
    page.deleteLater()
    app.processEvents()


def test_word_texts_join_english_with_spaces_and_keep_chinese_together():
    from twobyteasr.recognition.asr import _join_word_texts
    assert _join_word_texts(['大', '家', '好']) == '大家好'
    assert _join_word_texts(['Hello', 'everyone', 'I', 'am', 'here']) == 'Hello everyone I am here'
    assert _join_word_texts(['我', '用', 'OpenRouter', '测', '试']) == '我用OpenRouter测试'
    assert _join_word_texts(['Hello,', 'world']) == 'Hello, world'      # space after punctuation
    assert _join_word_texts(['Hello', ' world']) == 'Hello world'       # no double space
    assert _join_word_texts(['こ', 'ん', 'に', 'ち', 'は']) == 'こんにちは'


def test_mai_response_rows_have_word_times_two_speakers_and_spaced_english():
    from twobyteasr.recognition.asr import _api_transcription_rows
    # Trimmed from the real 2026-10-25 OpenRouter response (verbose_json, speaker ids from 0).
    words = [dict(word=w, start=s, end=s + 0.08, speaker=0) for w, s in (('大', 0.68), ('家', 0.84), ('好', 1.04))]
    words += [dict(word=w, start=s, end=s + 0.3, speaker=1)
              for w, s in (('Hello', 8.0), ('everyone', 8.4), ('I', 9.0), ('am', 9.2), ('here', 9.5))]
    words += [dict(word=w, start=s, end=s + 0.08, speaker=0) for w, s in (('好', 14.8), ('的', 15.0))]
    result = dict(text='', words=words, segments=[
        dict(id=0, start=0.68, end=1.2, text='大家好', speaker=0),
        dict(id=1, start=8.0, end=9.8, text='Hello everyone, I am here.', speaker=1),
        dict(id=2, start=14.8, end=15.1, text='好的', speaker=0)])
    rows = _api_transcription_rows(result, dict(start=0.0, end=20.0))
    assert [row['text'] for row in rows] == ['大家好', 'Hello everyone, I am here.', '好的']
    assert rows[0]['speaker'] == rows[2]['speaker'] != rows[1]['speaker']
    assert all(row.get('timing_precision') == 'word' for row in rows)
    assert abs(float(rows[1]['start']) - 8.0) < 0.05


@pytest.mark.parametrize('saved', [{}, {'qwen_asr_api_provider': 'openrouter_word', 'qwen_asr_api_model': ''}])
def test_openrouter_setup_shows_mai_transcribe_2_in_the_model_box(qapp, saved):
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    host = _Host(saved)
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='openrouter_word')
    assert dialog._guide.key == 'openrouter_word'
    assert dialog._fields['model'].text() == 'microsoft/mai-transcribe-2'
    dialog._fields['api_key'].setText('sk-or-v1-test')
    dialog._save(True)
    provider, values, primary = host.saved[-1]
    assert provider == 'openrouter_word' and values['model'] == 'microsoft/mai-transcribe-2' and primary
    dialog.deleteLater()


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.reason = 'OK'
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _fake_requests(responses):
    import types
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return responses[min(len(calls) - 1, len(responses) - 1)]
    module = types.ModuleType('requests')
    module.post = post
    return module, calls


MAI_ENDPOINT = dict(provider='openrouter_word', protocol='openrouter_verbose_json', model='microsoft/mai-transcribe-2',
                    url='https://openrouter.ai/api/v1/audio/transcriptions', api_key='or-secret')


def test_mai_request_carries_all_five_options():
    """Measured 2026-10-25 through OpenRouter: style works only inside enhancedMode; the phrase list fixed 鸣潮/今汐."""
    import numpy as np
    from twobyteasr.recognition.asr import call_qwen_asr_api
    module, bodies = _fake_requests([_Response(200, {'text': '文', 'segments': [], 'words': []})])
    call_qwen_asr_api(np.zeros(1600, dtype=np.float32), '', requests_module=module,
                      endpoint=dict(MAI_ENDPOINT, azure_phrases=['鸣潮', '今汐']))
    body = bodies[0]
    assert body['response_format'] == 'verbose_json'
    assert body['timestamp_granularities'] == ['segment', 'word']
    azure = body['provider']['options']['azure']
    assert azure['diarization'] == {'enabled': True}
    assert azure['enhancedMode'] == {'modelOptions': {'transcribeStyle': 'clean'}}
    assert azure['phraseList'] == {'phrases': ['鸣潮', '今汐']}
    assert 'modelOptions' not in azure


def test_a_rejected_phrase_list_is_dropped_first_and_alone():
    import numpy as np
    from twobyteasr.recognition.asr import call_qwen_asr_api
    module, bodies = _fake_requests([_Response(400, {'error': {'message': 'bad phrase'}}),
                                     _Response(200, {'text': '文', 'segments': [], 'words': []})])
    call_qwen_asr_api(np.zeros(1600, dtype=np.float32), '', requests_module=module,
                      endpoint=dict(MAI_ENDPOINT, azure_phrases=['鸣潮']))
    assert len(bodies) == 2 and 'phraseList' in bodies[0]['provider']['options']['azure']
    second = bodies[1]
    assert 'phraseList' not in second['provider']['options']['azure']
    assert second['timestamp_granularities'] == ['segment', 'word'] and second['response_format'] == 'verbose_json'
    assert second['provider']['options']['azure']['diarization'] == {'enabled': True}


def test_mai_phrase_hints_follow_the_ranked_glossary_and_report_what_is_left_out(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.providers import asr_api_process
    terms = ['鸣潮', '今汐', '鸣潮', '', 'x' * 51] + [f'词{i}' for i in range(120)]
    hints = asr_api_process.mai_phrase_hints(terms)
    assert hints['azure_phrases'][:3] == ['鸣潮', '今汐', '词0'] and len(hints['azure_phrases']) == 100
    reasons = {item['reason'] for item in hints['azure_phrases_dropped']}
    assert reasons == {'longer_than_50_characters', 'over_100_phrases'}
    assert hints['hint_counts'] == {'phrase_list': 100, 'dropped': 1 + 22}
    monkeypatch.setattr('twobyteasr.glossary.terminology.runtime_snapshot',
                        lambda: SimpleNamespace(hotword_terms=('今汐', '长离')))
    assert asr_api_process.cloud_request_hints(MAI_ENDPOINT, {})['azure_phrases'] == ['今汐', '长离']
    other = dict(MAI_ENDPOINT, model='openai/whisper-large-v3')
    assert asr_api_process.cloud_request_hints(other, {}) == {}
    first = asr_api_process.cache_hint_signature(MAI_ENDPOINT, {})
    monkeypatch.setattr('twobyteasr.glossary.terminology.runtime_snapshot',
                        lambda: SimpleNamespace(hotword_terms=('今汐',)))
    assert first and asr_api_process.cache_hint_signature(MAI_ENDPOINT, {}) != first


# ----------------------------------------------------------------- Qwen sites

def test_qianwen_host_is_the_china_site_of_the_same_entry():
    from twobyteasr.providers.api_endpoints import describe_dashscope, parse_dashscope_address
    address = parse_dashscope_address('maas.qianwenaiapi.com')
    assert address.qwen_cloud and address.qwen_site == 'cn' and address.region == 'cn-beijing'
    assert address.filetrans_url == CN_URL
    info = describe_dashscope('https://maas.qianwenaiapi.com/api/v1')
    assert info['website'] == 'https://platform.qianwenai.com/home' and info['qwen_site'] == 'cn'
    assert '千问AI平台' in info['notes'][0]
    assert parse_dashscope_address(INTL_URL).qwen_site == 'intl'
    assert parse_dashscope_address('https://llm-abc.cn-beijing.maas.aliyuncs.com').qwen_site == ''


def test_site_follows_the_saved_address_then_the_interface_language():
    from twobyteasr.providers import api_setup_catalog as catalog
    assert catalog.qwen_site_for('', 'zh') == 'cn'
    assert {catalog.qwen_site_for('', lang) for lang in ('zh-Hant', 'en', 'ja')} == {'intl'}
    assert catalog.qwen_site_for(INTL_URL, 'zh') == 'intl'
    assert catalog.qwen_site_for('https://dashscope-intl.aliyuncs.com', 'zh') == 'intl'
    assert catalog.qwen_site_for(CN_URL, 'en') == 'cn'
    assert catalog.guide_for('qwen_cloud_filetrans', url=CN_URL) is catalog.QIANWEN_FILETRANS_GUIDE
    assert catalog.guide_for('qwen_cloud_filetrans', url=INTL_URL) is catalog.guide_for('qwen_cloud_filetrans')
    # The provider list keeps one row for both sites.
    assert sum(guide.key == 'qwen_cloud_filetrans' for guide in catalog.ASR_GUIDES) == 1


def test_china_site_guide_links_fields_and_tutorial():
    from twobyteasr.providers import api_setup_catalog as catalog
    guide = catalog.QIANWEN_FILETRANS_GUIDE
    intl = catalog.QWEN_SITE_GUIDES['intl']
    assert guide.key == intl.key and guide.models == intl.models and guide.site_variant == 'cn'
    urls = [link.url for link in guide.links]
    assert 'https://platform.qianwenai.com/home/api-keys' in urls and 'https://oss.console.aliyun.com/' in urls
    assert not any('qwencloud' in url or 'alibabacloud' in url for url in urls)
    url_field = next(spec for spec in guide.fields if spec.key == 'url')
    assert url_field.prefilled == 'https://maas.qianwenaiapi.com'
    region = next(spec for spec in guide.fields if spec.key == 'oss_region')
    assert region.example.startswith('cn-beijing')
    # 2026-10-28: the provider's temporary space by default; “建 OSS” only with own OSS chosen.
    assert [step.role for step in catalog.walkthrough(guide)] == ['account', 'topup', 'key', 'paste']
    steps = catalog.walkthrough(guide, own_storage=True)
    assert [step.role for step in steps] == ['account', 'topup', 'key', 'storage', 'paste']
    assert all('qianwenai.com' in step.url or 'aliyun.com' in step.url for step in steps if step.url)
    text = guide.guide_text(language='zh')
    assert text.startswith('# 申请与设置 千问AI平台')
    assert {link.checked for link in guide.links} == {'2026-10-25'} and '最后核对：2026-10-25' in text
    assert '千问AI平台' in guide.guide_text(language='zh-Hant').replace('千問', '千问')


def test_china_site_errors_point_at_its_own_console():
    from twobyteasr.providers.dashscope_service import explain, explain_token_plan_key
    host = 'maas.qianwenaiapi.com'
    assert explain(400, {'code': 'Arrearage'}, host=host).link == 'https://platform.qianwenai.com/home/billing/overview'
    key = explain(401, {'code': 'InvalidApiKey'}, host=host, region_label='华北2（北京）')
    assert key.link == 'https://platform.qianwenai.com/home/api-keys' and '地域' not in key.action
    free = explain(400, {'code': 'AllocationQuota.FreeTierOnly'}, host=host)
    assert '免费额度用完即停' in free.message and 'qianwenai' in free.link
    offline = explain(None, host=host, exception=TimeoutError('timed out'))
    assert '新加坡' not in offline.action
    assert explain_token_plan_key(host).link == 'https://platform.qianwenai.com/home/api-keys'
    assert 'qwencloud' in explain_token_plan_key('maas.qwencloudapi.com').link


class _Host:
    def __init__(self, models=None):
        self.saved = []
        self.models = models or {}
        self.key_urls = []

    def make(self):
        from twobyteasr.providers.api_setup_dialog import SetupHost

        def saved_key(provider, url):
            self.key_urls.append(url)
            return ''
        return SetupHost(settings=lambda: {'models': dict(self.models)}, saved_key=saved_key,
                         saved_oss_credentials=lambda: ('', ''),
                         save=lambda provider, values, primary: (self.saved.append((provider, values, primary))
                                                                 or (True, '已保存。')))


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _language(monkeypatch, language):
    monkeypatch.setattr('twobyteasr.i18n.current_language', lambda: language)


def test_simplified_chinese_opens_the_china_site_and_can_switch(qapp, monkeypatch):
    from twobyteasr.providers import api_setup_catalog as catalog
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    _language(monkeypatch, 'zh')
    host = _Host()
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen_cloud_filetrans')
    assert dialog._guide is catalog.QIANWEN_FILETRANS_GUIDE
    assert not dialog.qwen_site_box.isHidden() and dialog.qwen_site_box.currentData() == 'cn'
    assert 'platform.qianwenai.com' in dialog.address_view.toolTip()
    dialog._fields['api_key'].setText('sk-ws-abc')
    assert dialog.collected()['url'] == CN_URL
    menu_names = [guide.name for guide in dialog._guides('asr')]
    assert '千问AI平台 录音文件识别' in menu_names and 'Qwen Cloud 录音文件识别' not in menu_names

    dialog.qwen_site_box.setCurrentIndex(dialog.qwen_site_box.findData('intl'))
    assert dialog._guide is catalog.QWEN_SITE_GUIDES['intl']
    assert 'home.qwencloud.com' in dialog.address_view.toolTip()
    dialog._fields['api_key'].setText('sk-ws-abc')
    assert dialog.collected()['url'] == INTL_URL
    dialog._fields['url'].setText('https://llm-abc.cn-beijing.maas.aliyuncs.com')
    with pytest.raises(Exception, match='只接受千问AI平台或 Qwen Cloud'):
        dialog.collected()
    # Other providers never show the switch.
    dialog.choose('asr', 'mosi_moss_pro')
    assert dialog.qwen_site_box.isHidden()
    dialog.deleteLater()


def test_saved_international_address_wins_over_the_language(qapp, monkeypatch):
    from twobyteasr.providers import api_setup_catalog as catalog
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    _language(monkeypatch, 'zh')
    host = _Host({'qwen_asr_api_provider': 'qwen_cloud_filetrans', 'qwen_asr_api_url': INTL_URL})
    dialog = ApiSetupDialog(None, host.make(), kind='asr', initial='qwen_cloud_filetrans')
    assert dialog._guide is catalog.QWEN_SITE_GUIDES['intl']
    assert dialog._value('url') == INTL_URL
    # Switching sites starts from that site's own address and key slot, not the saved one.
    host.key_urls.clear()
    dialog.qwen_site_box.setCurrentIndex(dialog.qwen_site_box.findData('cn'))
    assert dialog._value('url') == 'https://maas.qianwenaiapi.com'
    assert host.key_urls and all('qianwenai' in url for url in host.key_urls)
    dialog.deleteLater()


def test_english_interface_opens_the_international_site(qapp, monkeypatch):
    from twobyteasr.providers import api_setup_catalog as catalog
    from twobyteasr.providers.api_setup_dialog import ApiSetupDialog
    _language(monkeypatch, 'en')
    dialog = ApiSetupDialog(None, _Host().make(), kind='asr', initial='qwen_cloud_filetrans')
    assert dialog._guide is catalog.QWEN_SITE_GUIDES['intl']
    dialog.deleteLater()


def test_run_disclosure_names_the_china_site():
    from twobyteasr.recognition.recognition_choices import run_disclosure
    info = run_disclosure({'models': {'primary_asr_backend': 'api', 'qwen_asr_api_provider': 'qwen_cloud_filetrans',
                                      'qwen_asr_api_model': 'qwen-audio-3.1-asr-flash-filetrans',
                                      'qwen_asr_api_url': CN_URL, 'filetrans_upload': 'own_oss',
                                      'oss_bucket': 'b'}})
    assert '千问AI平台' in info['engine'] and 'maas.qianwenaiapi.com' in ' '.join(info['uploads'])
