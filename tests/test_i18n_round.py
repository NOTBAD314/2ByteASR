"""2026-09-19 i18n 补齐轮：翻译资源完整性回归。

- en/ja 键完全对齐（不允许只在一种语言存在）
- 占位符（{name}/%s/%d）在译文中原样保留
- zh→en→zh 经 apply_ui_language 往返还原
- 本轮关键新键（方案提示/就绪门/保存状态）必须存在
"""

from __future__ import annotations

import re

import pytest

from twobyteasr.i18n import _TRANSLATIONS, apply_ui_language, translate

PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|%[sd]")


def test_en_ja_keys_are_aligned():
    en_keys = set(_TRANSLATIONS.get("en", {}))
    ja_keys = set(_TRANSLATIONS.get("ja", {}))
    only_en = en_keys - ja_keys
    only_ja = ja_keys - en_keys
    assert not only_en, f"en-only keys ({len(only_en)}): {sorted(only_en)[:8]}"
    assert not only_ja, f"ja-only keys ({len(only_ja)}): {sorted(only_ja)[:8]}"


def test_placeholders_preserved_in_translations():
    mismatches = []
    for language in ("en", "ja"):
        for zh, out in _TRANSLATIONS.get(language, {}).items():
            want = sorted(PLACEHOLDER.findall(zh))
            got = sorted(PLACEHOLDER.findall(str(out)))
            if want != got:
                mismatches.append(f"[{language}] {zh[:50]} zh={want} out={got}")
    assert not mismatches, "\n".join(mismatches[:10])


def test_translate_falls_back_to_source():
    assert translate("不存在的键xyz", "en") == "不存在的键xyz"
    assert translate("不存在的键xyz", "ja") == "不存在的键xyz"
    assert translate("任意", "zh") == "任意"
    assert translate("任意", "klingon") == "任意"


def test_round_20260919_keys_present():
    required = [
        "未保存的方案修改",
        "保存并切换",
        "放弃修改",
        "已应用：",
        "有未保存的识别后端修改",
        "识别后端与密钥已保存",
        "已配置 · 未验证",
        "准备工作台",
        "读取工程",
        "建立时间轴",
        "准备播放器",
        "准备音频",
        "准备字幕",
        "首屏绘制",
        "恢复界面布局",
        "恢复播放位置",
        "已保存",
        "正在自动保存…",
        "媒体加载失败 · 工程仍已打开",
    ]
    missing = [key for key in required if key not in _TRANSLATIONS["en"] or key not in _TRANSLATIONS["ja"]]
    assert not missing, f"missing translations: {missing}"


def test_apply_ui_language_roundtrip_restores_chinese():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    app = QApplication.instance() or QApplication([])
    label = QLabel("读取工程")
    button = QPushButton("放弃修改")
    try:
        apply_ui_language(label, "en")
        en_label, en_button = label.text(), button.text()
        apply_ui_language(label, "ja")
        apply_ui_language(label, "zh")
        assert label.text() == "读取工程", f"roundtrip failed: {label.text()!r}"
        assert button.text() == "放弃修改"
        assert en_label != "读取工程" or en_button != "放弃修改", "translations not applied"
    finally:
        label.deleteLater()
        button.deleteLater()


def test_no_cjk_left_in_english_translations():
    """English values carry no Chinese, except these quoted examples (the
    misheard spelling, the grammar pattern, the hesitation sound) and the
    output file name, which the user sees in Chinese."""
    allowed = {
        "每行一个正确写法；常被听错的写法用 → 连到正确写法，例如：球球 → CHICHOO",
        "动词重叠后不能再接补语（如“叠叠出”）",
        "动词重叠后不能再接“形容词+了”（如“学学聪明了”）",
        "识别原文里两次之间有“呃”等停顿，是起句重来",
    }
    bad = [zh for zh, en in _TRANSLATIONS["en"].items()
           if re.search(r"[一-鿿]", en) and zh not in allowed and not zh.startswith("使用方式：")]
    assert not bad, f"en entries still contain CJK: {bad[:6]}"
