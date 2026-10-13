"""繁體中文 (zh-Hant) UI language (2026-10-14)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_covers_the_ui_and_keeps_placeholders():
    from string import Formatter
    en = json.loads((ROOT / 'twobyteasr/locales/en.json').read_text(encoding='utf-8'))
    hant = json.loads((ROOT / 'twobyteasr/locales/zh-Hant.json').read_text(encoding='utf-8'))
    assert set(hant) <= set(en) and len(hant) >= 0.95 * len(en)

    def fields(text):
        return sorted(name for _l, name, _s, _c in Formatter().parse(text) if name is not None)
    assert all(fields(key) == fields(value) for key, value in hant.items())
    assert hant['申请与设置 API'] == '申請與設定 API'
    assert hant['识别方案与 {n} 个词库已就绪'] == '識別方案與 {n} 個詞庫已就緒'


def test_translate_uses_the_table_then_the_character_fallback_but_never_user_text(monkeypatch):
    from twobyteasr import i18n
    assert i18n.translate('保存并用于识别', 'zh-Hant') == '儲存並用於識別'
    # A UI string added after zh-Hant.json was generated: character fallback.
    monkeypatch.setattr(i18n, '_KNOWN_KEYS', i18n._KNOWN_KEYS | {'新加的界面说明'})
    assert i18n.translate('新加的界面说明', 'zh-Hant') == '新加的界面說明'
    # Anything that is not a known UI string (subtitles, file names) is untouched.
    assert i18n.translate('这句字幕是用户的内容', 'zh-Hant') == '这句字幕是用户的内容'
    assert i18n.translate('保存并用于识别', 'zh') == '保存并用于识别'


def test_language_setting_accepts_zh_hant():
    from twobyteasr import i18n
    assert 'zh-Hant' in i18n.SUPPORTED_LANGUAGES and 'zh-Hant' in i18n.TRANSLATED_LANGUAGES
    text = i18n.TranslatedText.__new__(i18n.TranslatedText, '已保存（···{value0}）；留空表示不修改', {'value0': 'abcd'})
    assert isinstance(text, str)


def test_api_setup_tutorial_follows_the_ui_language():
    from twobyteasr.api_setup_catalog import guide_for
    guide = guide_for('mosi_moss_pro')
    hant = guide.guide_text(ROOT, language='zh-Hant')
    hans = guide.guide_text(ROOT, language='zh')
    assert hant.startswith('<!-- 由 scripts/make_zh_hant.py') and '申請與設定' in hant
    assert hans.startswith('# 申请与设置') and hant != hans
    assert all((ROOT / 'docs/api-setup' / g.guide_file.replace('.zh-CN.md', '.zh-Hant.md')).is_file()
               for g in __import__('twobyteasr.api_setup_catalog', fromlist=['ALL_GUIDES']).ALL_GUIDES)
