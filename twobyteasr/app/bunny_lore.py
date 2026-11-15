"""「问问兔白」的世界书: what 兔白 knows about the software (2026-11-14).

Built from the places the software already describes itself, so it follows the code instead of
going stale like a hand-written FAQ:

* the feature search registry (``feature_search.entries``): every place, its words and where it is;
* the API setup catalog (``api_setup_catalog``): each cloud / text-AI service, its site, the
  first cost and what gets uploaded;
* the shortcut registry (``shortcut_registry.ACTIONS``): every workbench / home key by default;
* the subtitle and video tips 兔白 already says in the tutorial (``tour_mascot.TIPS``);
* step-by-step how-to entries (``bunny_howto.HOWTO``), whose 「names」 a test checks against the code.

Only ``CORE`` (the main flow, the recognition choices, cost and privacy, where to get help) is
written by hand here; it is short and avoids version numbers, sizes and step counts that
change between releases. Each question gets ``CORE`` plus the few entries ``select`` ranks
highest for its words, which keeps the prompt small and cheap.

No Qt at import time; nothing here changes a setting or sends anything.
"""
from __future__ import annotations

from dataclasses import dataclass

CORE = """兔白字幕（2ByteASR）是免费的字幕软件，主要给中文游戏实况做字幕，也能做日语、英语等语言。没有付费功能、注册或订阅。

做一份字幕的流程：
1. 首页：把视频或音频拖进来（也可以贴视频链接）。
2. 选识别方式和「识别方案」，按开始识别。
3. 识别完成后进入完成页，可以直接导出，或者打开「字幕工作台」修改。
4. 字幕工作台：逐条改字、切开或合并字幕、调时间、改说话人和样式，按 R 进入审核模式逐条确认。
5. 导出字幕文件（SRT、ASS、TXT 等）或把字幕压进视频（MP4 等）；工程文件保存全部编辑状态。

识别方式（可以随时在「需要帮忙吗 → 选择识别方式…」重新选）：
- 本机识别：需要 NVIDIA 显卡，要先在「模型工坊」下载模型；能分说话人、逐字时间最准，影音不离开电脑。
- 云端识别：不用显卡也不用下载模型，但要申请服务商的 API Key（密钥），按用量付费，音频会上传给服务商。
- 轻量本机：没有显卡、又不想上传时用，用 CPU，比较慢，不分说话人。
- Mac 本机识别：Apple 芯片的 Mac 用。
没有 NVIDIA 显卡时，需要显卡的选项会直接标出来，首页会给“换成能用的方式”。

费用与隐私：
- 软件本身免费。本机识别下载模型后可以离线用。
- 云端识别和文字 AI 都用小兔纸自己的 Key，按服务商的规则收费，价格以服务商页面为准；软件不会替人开通或付费，开始前会列出用哪个服务、大概费用和上传到哪里。
- 文字 AI（DeepSeek、阿里云百炼、OpenAI、Claude、Gemini、xAI 等）只发送字幕文字，用来做 AI 断句、校对、翻译、词库和 AI 字幕设计。没设置时这些功能不可用或改用本地规则，识别、编辑和导出照常。
- 外部 AI（MCP）默认关闭。

一次识别最多有三种分工：主力转写（写出文字，部分方案能分说话人）、字幕时间轴（给每个字标时间）、文字复核（另一个模型再听一遍，列出写法不同的地方给人挑）。

识别完显示“有需复核项”不是出错：打开字幕工作台，按 R 进入审核模式，逐条确认就好。

遇到问题去哪里：右上角「说明」按钮打开「需要帮忙吗」，里面有新手教学、打开范例工程、选择识别方式、回报问题／导出诊断、重新显示工作台操作提示。新手教学用范例工程演示，不需要模型、不上传、不花钱。"""


@dataclass(frozen=True)
class LoreEntry:
    key: str
    title: str
    keywords: tuple
    text: str


def _feature_entries(window) -> list[LoreEntry]:
    from .feature_search import entries
    items = []
    for entry in entries(window if window is not None else object()):
        if not entry.key:
            continue
        text = f'位置：{entry.where}。可以用 point_to / offer_open 填 {entry.key}。'
        items.append(LoreEntry(f'feature:{entry.key}', entry.title, tuple(entry.keywords), text))
    return items


def _short(text: str, limit: int) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _guide_entries() -> list[LoreEntry]:
    from ..providers.api_setup_catalog import ASR_GUIDES, TEXT_GUIDES
    items = []
    for guide in (*ASR_GUIDES, *TEXT_GUIDES):
        kind = '云端语音识别' if guide.kind == 'asr' else '文字 AI'
        facts = [f'类别：{kind}{"（进阶）" if guide.advanced_only else ""}']
        if guide.site:
            facts.append(f'在哪申请：{guide.site}')
        if guide.minutes:
            facts.append(f'申请大约 {guide.minutes} 分钟')
        if guide.money:
            facts.append(f'起步：{guide.money}')
        if guide.cost:
            facts.append(f'计费：{_short(guide.cost, 140)}')
        if guide.uploads:
            facts.append(f'会上传：{_short(guide.uploads, 110)}')
        where = '申请与设置 API' if guide.kind == 'asr' else 'AI 智能断句设置'
        facts.append(f'设置位置：「{where}」，里面有一步一步的申请教学')
        keywords = (guide.key, guide.name, guide.title, guide.site, 'api', 'key', '密钥', '申请', '充值',
                    '价格', '费用', '多少钱', '免费', '云端' if guide.kind == 'asr' else '文字ai')
        items.append(LoreEntry(f'guide:{guide.kind}:{guide.key}', f'{guide.name}（{kind}）',
                               tuple(word for word in keywords if word), '；'.join(facts) + '。'))
    return items


def _shortcut_entries() -> list[LoreEntry]:
    from ..studio.shortcut_registry import ACTIONS, CATEGORY_ORDER, SCOPE_LABELS
    grouped: dict[str, list] = {}
    for action in ACTIONS:
        grouped.setdefault(action.category, []).append(action)
    items = []
    for category in sorted(grouped, key=lambda name: CATEGORY_ORDER.index(name)
                           if name in CATEGORY_ORDER else len(CATEGORY_ORDER)):
        actions = grouped[category]
        rows = [f'{action.label}：{action.default or "（默认没有）"}'
                f'（{SCOPE_LABELS.get(action.scope, action.scope)}）' for action in actions]
        keywords = ('快捷键', '按键', 'shortcut', category, *(action.label for action in actions))
        text = '默认快捷键，可以在「应用设置 → 快捷键」改。' + '；'.join(rows) + '。'
        items.append(LoreEntry(f'shortcuts:{category}', f'快捷键 · {category}', keywords, text))
    return items


def _tip_entry() -> LoreEntry:
    from .tour_mascot import TIPS
    keywords = ('格式', 'srt', 'ass', 'txt', '剪映', '硬字幕', '软字幕', 'h.264', 'h264', 'h.265', 'h265', 'av1',
                'mp4', '码率', 'crf', '帧率', '关键帧', 'aac', '画质', '一行', '多长', '编码', '压制')
    return LoreEntry('tips', '字幕与视频小常识', keywords, '\n'.join(f'- {tip}' for tip in TIPS))


def build_entries(window=None) -> list[LoreEntry]:
    """Every world-book entry. ``window``: the main window (only its methods are captured, none run).

    The how-to entries (``bunny_howto``) come first so a "how do I…" question that also names
    a feature gets the steps, not only the place.
    """
    from .bunny_howto import HOWTO
    return [*HOWTO, *_feature_entries(window), *_guide_entries(), *_shortcut_entries(), _tip_entry()]


def feature_index(window=None) -> list[tuple[str, str, str]]:
    """(key, title, where) of every place 兔白 may point at or open."""
    from .feature_search import entries
    return [(entry.key, entry.title, entry.where)
            for entry in entries(window if window is not None else object()) if entry.key]


def _bigrams(text: str) -> set:
    text = ''.join(str(text).casefold().split())
    return {text[index:index + 2] for index in range(len(text) - 1)}


def rank(question: str, items) -> list:
    """Items (anything with ``title`` and ``keywords``) whose words the question uses, best first.

    A keyword found in the question counts most (longer keywords more, so 「千问ai平台」 beats
    「ai」); shared two-character pieces of the title break ties.
    """
    text = str(question or '').casefold()
    if not text.strip():
        return []
    pieces = _bigrams(text)
    scored = []
    for index, item in enumerate(items):
        score = 0.0
        for keyword in item.keywords:
            word = str(keyword).casefold().strip()
            if word and word in text:
                score += 3 + min(len(word), 6) * 0.5
        score += 0.5 * len(pieces & _bigrams(item.title))
        if score >= 1:
            scored.append((-score, index, item))
    return [item for _score, _index, item in sorted(scored, key=lambda row: (row[0], row[1]))]


def select(question: str, entries, limit: int = 6) -> list[LoreEntry]:
    return rank(question, entries)[:limit]


# 2026-11-15: the manual, every how-to entry and every default key are in the fixed system prompt
# (``fixed_knowledge``); per question only the rest (places, services, tips) is picked by its words.
FIXED_PREFIXES = ('howto:', 'shortcuts:')


def select_extra(question: str, entries, limit: int = 4) -> list[LoreEntry]:
    return select(question, [entry for entry in entries if not entry.key.startswith(FIXED_PREFIXES)], limit)


def fixed_knowledge() -> str:
    """What 兔白 always knows about the software: the manual, then the how-to steps, then the keys."""
    from .bunny_howto import HOWTO
    from .bunny_manual import MANUAL
    steps = '\n\n'.join(f'## {entry.title}\n{entry.text}' for entry in HOWTO)
    keys = '\n'.join(f'- {entry.title.split("·")[-1].strip()}：{entry.text}' for entry in _shortcut_entries())
    return '\n\n'.join((MANUAL, '# 一步一步怎么做', steps, '# 全部默认快捷键', keys))


__all__ = ['CORE', 'FIXED_PREFIXES', 'LoreEntry', 'build_entries', 'feature_index', 'fixed_knowledge', 'rank',
           'select', 'select_extra']
