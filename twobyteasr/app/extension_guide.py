"""What 兔白 reads before she writes or fixes an extension script (2026-11-20, tool ``script_guide``).

The whole ``ScriptAPI`` (``user_overlay_runtime``) in plain words, the events (``extension_events``)
and one complete example: the 识别后自动整理术语 a user asked for (2026-11-20). The example is only
text for her: the program never runs it by itself; a script exists only after the user's 「帮我做」 and
runs only after he switches it on. Kept out of her prompt (it is long); she asks for it. No Qt.
"""
from __future__ import annotations

EXAMPLE_AUTO_TERMS = '''API_VERSION = 1
# 识别后自动整理术语：记下小兔纸在工作台改对的词，保存工程时让 AI 挑出专有名词、分好类，加进术语库。
import json

LIBRARY = '我的自动术语'     # 新词放进这个术语库，没有就自动建一个


def setup(api):
    seen, waiting = set(), []

    def edited(event):
        for source, target in event.get('replacements') or ():
            if source and target and (source, target) not in seen:
                seen.add((source, target))
                waiting.append((source, target))

    def saved(event):
        if not waiting:
            return
        batch = waiting[:60]
        del waiting[:60]
        pairs = '\\n'.join(f'{source} -> {target}' for source, target in batch)
        prompt = ('下面是用户把字幕里识别错的词改对的记录（左边识别出来的，右边改对的）。'
                  '只挑出专有名词（角色、地名、技能、道具、组织等），每个给一个分类。'
                  '只回 JSON 数组，例如 [{"from": "派门", "to": "派蒙", "category": "角色"}]；不是专有名词的不要列。\\n'
                  + pairs)

        def done(text, error):
            if error is not None:
                api.log(f'AI 没有回答：{error}')
                return
            try:
                rows = json.loads(text[text.index('['):text.rindex(']') + 1])
            except ValueError:
                api.log('AI 回的不是 JSON：' + str(text)[:200])
                return
            rows = [row for row in rows if isinstance(row, dict) and row.get('to')]
            if rows:
                api.say(api.glossary.add(api.glossary.create(LIBRARY), rows))
        api.ai(prompt, done)

    api.on('subtitle_edited', edited)
    api.on('project_saved', saved)
'''


def guide() -> str:
    from .extension_events import EVENTS
    from .user_overlay import API_VERSION
    events = '\n'.join(f'  - {name}：{text}' for name, text in EVENTS.items())
    return f'''【扩展脚本怎么写（API_VERSION = {API_VERSION}）】
脚本是一个 Python 文件：第一行附近写 API_VERSION = {API_VERSION}，入口是 def setup(api):，程序启动（或小兔纸打开它）时调用一次。
用 propose_change kind=script 存新脚本，用 edit_script 改已有的；存下来都是关着的，要小兔纸在「设置 → 我的改动」看过再打开
（还要打开「允许运行我的扩展脚本」）。出错的脚本会被停用，错误在 read_change 的「脚本记录」里，看了再用 edit_script 修。
api 能用的：
  - api.on(事件, 函数)：到某个时候调用 函数(event)，event 是 dict：
{events}
  - api.glossary.libraries() 术语库列表；api.glossary.find(文字, 库名) 找词条；
    api.glossary.create(库名) 建库（已有就直接用），返回库 id；
    api.glossary.add(库名或 id, [{{"to": "派蒙", "from": "派门", "category": "角色"}}, "规范词", ...]) 加词（重复的跳过，一次最多 200）
  - api.learned()：软件记下的“小兔纸反复手动改的词”（original_term → corrected_term、occurrence_count、status）
  - api.project()：工作台打开的工程（project.cues 每条有 text、start_ms、end_ms），没有就 None
  - api.ai(提示词, 完成函数, system="", max_tokens=2000)：后台问小兔纸设置的文字 AI（花他的 Key），完成函数(text, error)
  - api.in_background(函数, 完成函数)：慢的事放后台，完成函数(结果, error) 回到界面线程
  - api.say(一句话)：兔白在气泡里说一句；api.log(文字) 写进脚本记录
  - api.every(毫秒, 函数)：定时；api.find("控件名")：找界面控件；api.window：主窗口；api.data_dir：这个脚本自己的资料文件夹
规矩：回调里不要做很慢的事（会卡界面），慢的用 api.ai / api.in_background；不要删用户的文件；
改术语库只用 api.glossary（会记下是哪个脚本加的）；写自己的资料放 api.data_dir。

【完整例子：识别后自动整理术语】
{EXAMPLE_AUTO_TERMS}'''


__all__ = ['EXAMPLE_AUTO_TERMS', 'guide']
