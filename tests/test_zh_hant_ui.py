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


def test_code_literals_load_only_for_zh_hant_and_cover_untranslated_help(monkeypatch):
    """Help texts without an English key (catalog tooltips) still show 繁體 (2026-10-14)."""
    from twobyteasr import i18n
    from twobyteasr.api_setup_catalog import guide_for
    assert 'zh-Hant' not in i18n._TRANSLATIONS or i18n._TRANSLATIONS['zh-Hant']  # lazy: absent until used
    region = guide_for('qwen31_filetrans').fields[0]
    table = i18n.language_table('zh-Hant')
    assert 'zh-Hant' in i18n._TRANSLATIONS and len(table) > 10000
    literals = json.loads((ROOT / 'twobyteasr/locales/zh-Hant-literals.json').read_text(encoding='utf-8'))
    assert all(key.encode('ascii', 'ignore') == value.encode('ascii', 'ignore') for key, value in literals.items())
    assert i18n.translate(region.help, 'zh-Hant') != region.help or region.help not in literals
    # English / Japanese never pick up the Traditional table.
    assert i18n.translate('只填你自己账户里创建的 Key。', 'en') == '只填你自己账户里创建的 Key。'


def test_ui_literal_converts_composed_program_text_but_translate_keeps_user_text():
    from twobyteasr import i18n
    from twobyteasr.api_setup_catalog import guide_for
    key_help = next(f.help for f in guide_for('mosi_moss_pro').fields if f.key == 'api_key')
    hant = i18n.ui_literal(key_help, 'zh-Hant')
    # Folded ``_KEY_HELP + '…'`` catalog text gets the phrase conversion.
    assert '賬戶裡建立' in hant and '账户' not in hant and '控制台' in hant
    assert i18n.ui_literal(key_help, 'zh') == key_help
    assert i18n.ui_literal('预计剩余 {m} 分 {s} 秒', 'zh-Hant').format(m=3, s=5) == '預計剩餘 3 分 5 秒'
    assert i18n.ui_literal('预计剩余 {m} 分 {s} 秒', 'en') == '预计剩余 {m} 分 {s} 秒'
    assert i18n.translate('这句字幕是用户的内容', 'zh-Hant') == '这句字幕是用户的内容'
