"""术语召回缺口 is for unrecalled names, not stammers or ordinary words.

2026-10-28: the user's 20-minute stream had 22 of 45 review items from this
check and a 1-hour stream 64 of 100; most were speech like the lines below.
"""
from types import SimpleNamespace

from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry
from twobyteasr.glossary.terminology_support import recall_gaps

SNAPSHOT = GlossarySnapshot((GlossaryLibrary('game', 'Game', '1', terms=(TermEntry('CHICHOO', ('CHICHOO',)),)),))


def surfaces(*lines):
    rows = [SimpleNamespace(segment_id=index, text=text) for index, text in enumerate(lines, 1)]
    return {gap['surface'] for gap in recall_gaps(rows, [], SNAPSHOT)}


def test_stammers_idioms_and_ordinary_words_are_not_name_gaps():
    lines = (
        '去去上海参加一个', '啊神神秘的活动啊', '啊龙龙头', '然后有一个流流荡', '就不用一下下点',
        '帅帅帅啊', '拜拜', '离离', '看一下海之之的原型', '啊应应该是应该是只加一次', '又把养分分给它们',
        '我靠 这是冥冥之中有什么暗示吗', '我们小心翼翼地打开了', '看起来饥肠辘辘', '全带带点伤害',
        '这种珠光宝气的啊', '聊天功能', '可能慢慢铺开这个世界观吧', '啊有荣誉标', '给它空间 保持安静',
        '看来清澈的潜水和温暖的阳光', '而且你总不能被一个普通技能秒了吧',
        '我打了这么多PVP了', '他都不用带buff', '状态技能debuff毒之类的',
    )
    assert surfaces(*lines) == set()


def test_doubled_nicknames_names_and_ids_still_are():
    found = surfaces('球球被挡住', '所以莎莎也撑不住了', '是谁把罐罐装饰成这样的', '还在等奥特曼出结果',
                     '啊是叫韦伯斯特吗', 'PlayerB')
    assert found == {'球球', '莎莎', '罐罐', '奥特曼', '韦伯斯特', 'PlayerB'}
