"""兔白's knowledge base v2 (2026-11-18): difficulties by stage, known problems, craft; found by plain words."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from twobyteasr.app import bunny_lore, bunny_troubleshoot


@pytest.fixture(scope='module')
def lore():
    return bunny_lore.build_entries()


def _source_text() -> str:
    root = Path(bunny_lore.__file__).resolve().parents[1]
    skip = {'bunny_howto.py', 'bunny_lore.py', 'bunny_persona.py', 'bunny_troubleshoot.py', 'bunny_manual.py',
            'bunny_tips.py', 'bunny_events.py'}
    return '\n'.join(path.read_text(encoding='utf-8') for path in root.rglob('*.py')
                     if path.name not in skip and 'acceptance' not in path.parts)


def test_every_quoted_name_in_the_troubleshooting_entries_is_in_the_software():
    source = _source_text()
    entries = (*bunny_troubleshoot.TROUBLE, *bunny_troubleshoot.CRAFT)
    missing = sorted({name for entry in entries for name in re.findall(r'「([^」]+)」', entry.text)
                      if name not in source})
    assert not missing, f'兔白的故障排查条目里有界面上已经没有的名字：{missing}'


def test_every_stage_of_work_and_every_known_problem_is_covered(lore):
    from twobyteasr.recognition.diagnosis_catalog import ISSUES
    keys = [entry.key for entry in lore]
    assert len(keys) == len(set(keys))
    for stage, label in bunny_troubleshoot.STAGES.items():
        found = [entry for entry in bunny_troubleshoot.TROUBLE if entry.key.startswith(f'trouble:{stage}:')]
        assert found, f'没有「{label}」阶段的条目'
        assert all(entry.title.startswith(label) and entry.keywords and len(entry.text) > 40 for entry in found)
    assert len(bunny_troubleshoot.TROUBLE) >= 50 and len(bunny_troubleshoot.CRAFT) >= 12
    issues = {entry.key: entry for entry in lore if entry.key.startswith('issue:')}
    assert set(issues) == {f'issue:{name}' for name in ISSUES}
    for name, issue in ISSUES.items():
        text = issues[f'issue:{name}'].text
        assert '症状：' in text and '原因：' in text and '怎么办：' in text
        assert issue.title in issues[f'issue:{name}'].title


def test_troubleshooting_is_picked_per_question_not_sent_every_time(lore):
    """The fixed prompt (cached, billed cheaply) must not grow with the knowledge base."""
    from twobyteasr.app import bunny_persona
    prompt = bunny_persona.system_prompt(bunny_lore.feature_index())
    assert '未知发布者' not in prompt and '每秒 4–6 个汉字' not in prompt
    assert 'search_knowledge' in prompt
    picked = bunny_lore.select_extra('导出的字幕打开是乱码', lore)
    assert 0 < len(picked) <= bunny_lore.EXTRA_LIMIT
    assert sum(len(entry.text) for entry in picked) < 4000
    assert bunny_lore.select_extra('', lore) == []


# What people actually type -> the entry that must be among the first three.
ASKED = (
    ('安装的时候说未知发布者，是病毒吗', '', 'trouble:install:unknown_publisher'),
    ('界面的字太小了看不清', '', 'trouble:install:ui_size'),
    ('让兔白改了界面之后打不开了', '', 'trouble:install:overlay_broken'),
    ('按了 E 没反应', '字幕工作台', 'trouble:install:which_version'),
    ('工具面板不见了', '字幕工作台', 'trouble:install:layout_messed'),
    ('我是 AMD 显卡能用吗', '首页', 'trouble:mode:no_nvidia'),
    ('本机还是云端，选哪个好', '首页', 'trouble:mode:which_mode'),
    ('识别方案怎么选', '首页', 'trouble:mode:which_plan'),
    ('视频是日语的怎么弄', '首页', 'trouble:mode:language'),
    ('模型下不动', '模型工坊', 'trouble:models:slow_download'),
    ('我要下载哪些模型', '模型工坊', 'trouble:models:which_model'),
    ('C盘满了，模型能放到D盘吗', '', 'trouble:models:disk_space'),
    ('key是什么，去哪申请', '', 'trouble:key:what_is_key'),
    ('测试连接失败 401', '', 'trouble:key:test_failed'),
    ('提示余额不足', '', 'trouble:key:no_balance'),
    ('用这个软件要钱吗', '', 'trouble:key:cost'),
    ('识别卡住不动了', '识别进度', 'trouble:run:stuck'),
    ('识别太慢了要多久', '', 'trouble:run:slow'),
    ('爆显存了', '', 'trouble:run:out_of_memory'),
    ('识别失败了怎么办', '识别记录', 'trouble:run:failed'),
    ('错别字好多', '识别完成的结果页', 'trouble:result:many_errors'),
    ('角色名总是写错', '字幕工作台', 'trouble:result:names_wrong'),
    ('两个人的话串了，说话人分错', '字幕工作台', 'trouble:result:speakers_wrong'),
    ('字幕和声音不同步', '字幕工作台', 'trouble:result:timing_off'),
    ('中间少了一段没识别到', '字幕工作台', 'trouble:result:missing_part'),
    ('字幕里有没说过的话，一直重复', '字幕工作台', 'trouble:result:made_up'),
    ('显示有需复核项是不是出错了', '识别完成的结果页', 'trouble:result:review_items'),
    ('一条字幕太长了', '字幕工作台', 'trouble:ai:cue_too_long'),
    ('字幕太碎，一两个字一条', '字幕工作台', 'trouble:ai:cue_too_short'),
    ('AI断句失败，说使用本地规则', '识别完成的结果页', 'trouble:ai:ai_fallback'),
    ('翻译不通顺，译名也不统一', '字幕工作台', 'trouble:ai:translation_bad'),
    ('同一个错字到处都是，怎么一次改完', '字幕工作台', 'trouble:edit:same_typo'),
    ('改错了想撤销', '字幕工作台', 'trouble:edit:undo'),
    ('时间轴上的字幕挤在一起', '字幕工作台', 'trouble:edit:cant_see_timeline'),
    ('字幕挡住血条了', '字幕工作台', 'trouble:style:position'),
    ('字幕字号太小想加描边', '字幕工作台', 'trouble:style:look'),
    ('双语只改译文的颜色', '字幕工作台', 'trouble:style:bilingual_one_layer'),
    ('想做卡拉OK逐字效果', '字幕工作台', 'trouble:style:karaoke'),
    ('导出选srt还是ass', '字幕工作台', 'trouble:export:which_format'),
    ('导出的字幕是乱码', '', 'trouble:export:garbled'),
    ('压制失败，nvenc报错', '字幕工作台', 'trouble:export:render_failed'),
    ('导出的视频太糊了', '字幕工作台', 'trouble:export:quality_size'),
    ('只导出中间一段', '字幕工作台', 'trouble:export:part_only'),
    ('闪退了没保存，还能找回吗', '', 'trouble:project:lost_work'),
    ('视频挪了地方，工程里找不到素材', '字幕工作台', 'trouble:project:media_moved'),
    ('卸载重装资料还在吗', '', 'trouble:update:data_kept'),
    ('预览很卡', '字幕工作台', 'trouble:speed:laggy'),
    ('为什么兔白不帮我直接做', '', 'trouble:bunny:wont_act'),
    ('兔白能看图吗', '', 'trouble:bunny:cant_see'),
    ('和兔白聊天会上传什么', '', 'trouble:bunny:privacy'),
    ('字幕一行多少字合适', '', 'craft:line_length'),
    ('字幕应该在哪里断句', '', 'craft:line_break'),
    ('软字幕和硬字幕有什么区别', '', 'craft:soft_hard'),
    ('码率是什么，h265好吗', '', 'craft:encoding'),
    ('为什么会多出没说过的话，是幻觉吗', '', 'craft:hallucination'),
    ('逐字时间和句段时间是什么', '', 'craft:word_timing'),
    ('WinError 1455', '', 'issue:pagefile_too_small'),
    ('No space left on device 磁盘空间不足', '', 'issue:disk_full'),
)


@pytest.mark.parametrize('question, page, wanted', ASKED, ids=[row[2] for row in ASKED])
def test_plain_words_find_the_right_entry(lore, question, page, wanted):
    found = [entry.key for entry in bunny_lore.select_extra(question, lore, page=page)]
    assert wanted in found[:3], (question, found)


def test_colloquial_words_page_and_an_open_dialog_all_help(lore):
    assert '崩溃' in bunny_troubleshoot.expand('刚才闪退了') and bunny_troubleshoot.expand('你好') == '你好'
    # The page on screen breaks a tie toward the entry made for it.
    studio = [entry.key for entry in bunny_lore.select_extra('太长了怎么办', lore, page='字幕工作台')]
    assert studio[0] == 'trouble:ai:cue_too_long'
    # "这是什么意思" says nothing by itself; the open dialog's title does.
    assert not [key for key in (entry.key for entry in bunny_lore.select_extra('这是什么意思', lore))
                if key.startswith('trouble:export')]
    seen = [entry.key for entry in bunny_lore.select_extra('这是什么意思', lore, seen='导出失败 · 显卡编码')]
    assert 'trouble:export:render_failed' in seen[:3]


def test_she_can_search_the_knowledge_base_herself():
    from types import SimpleNamespace
    from twobyteasr.app.bunny_tools import TOOLS, ToolError
    tool = TOOLS['search_knowledge']
    assert not (tool.acts or tool.edit or tool.paid)                   # a read: every permission level may use it
    found = tool.run(SimpleNamespace(), {'text': '导出的字幕是乱码'})
    assert 'UTF-8' in found and '只是资料' in found and len(found) < 3200
    assert '没有' in tool.run(SimpleNamespace(), {'text': '量子纠缠'})
    with pytest.raises(ToolError):
        tool.run(SimpleNamespace(), {'text': ''})
