"""兔白's little tips (2026-11-16): what she says when clicked, and now and then on her own.

User (2026-11-16): 「点击兔白的时候也多让它说说关于软件内的相关知识和小窍门 tips，让用户在聊天或无聊的时候
她也能多多教会用户一些操作，还有一些不定期小对话气泡也可以显示」.

Every tip comes from her manual (``bunny_manual``): only buttons and keys that exist (every 「name」
is checked against the source by ``tests/test_bunny_tips.py``). Tips for the page on screen come
first; the ones already said are skipped until all of that page's were heard, and where she is in
the list is kept with her other state, so the next start goes on instead of starting over. No Qt.
"""
from __future__ import annotations

import random

SEEN_KEY = 'bunny_tips_seen'
IDLE_KEY = 'bunny_idle_tips'          # 「兔白不定期说小窍门」 on/off (in 「兔白权限」, on by default)
HOME, STUDIO, ANY = '首页', '字幕工作台', ''

# (where it helps, the tip). Short: one or two of her bubbles, ~40 characters each.
TIPS = (
    (ANY, '按 **Ctrl+=** 放大界面，Ctrl+- 缩小，Ctrl+0 复原；只缩放界面，不影响字幕和导出哦。'),
    (ANY, '按 **Ctrl+,** 能直接打开「设置」。'),
    (ANY, '「说明」里有「打开范例工程」，不用自己的视频也能先玩一玩～'),
    (ANY, '花了多少 Key 钱？「设置」里的「查看用量与估算费用」能按日期和步骤筛选。'),
    (ANY, '在「设置」→「兔白权限」可以决定兔白能帮你做多少，还能「教兔白一件事」。'),
    (ANY, '想让兔白看得到画面？「兔白权限」里打开“让兔白截图看 2ByteASR 的画面”，要能看图的 AI 才行。'),
    (ANY, '兔白帮你改的界面样式和文字都在「设置」→「我的改动」，更新也不会盖掉，随时能关掉。'),
    (ANY, '改坏了界面打不开？启动时按住 **Shift**，这次就先不套用「我的改动」。'),
    (ANY, '按键分地方生效：Ctrl+K 在首页是搜索功能，在工作台是分割视频轨。'),
    (HOME, '首页按 **Ctrl+K** 打开「搜索功能与设置」，忘了按钮在哪就搜一下～'),
    (HOME, '剪贴板里是视频链接时，在首页直接 **Ctrl+V** 就能下载。'),
    (HOME, '「游戏 / 内容名称」填上游戏名，人名和术语更容易写对。'),
    (HOME, '已经有稿子？用「匹配文稿」，不用从头听写。'),
    (HOME, '一切就绪按 **Ctrl+Enter** 就是「开始生成字幕」。'),
    (HOME, '可以一次拖好几个视频进来，做好一个就能先打开校对，其他的在后台继续跑。'),
    (HOME, '「字幕显示」选「原文 + 翻译（双语）」就能做双语字幕。'),
    (STUDIO, '字幕挤成一团看不清？按 **=** 放大时间轴，Shift+Z 显示全部。'),
    (STUDIO, '整片字幕慢半拍：Ctrl+A 全选，再按 **Alt+←** 五次，就提前 0.5 秒。'),
    (STUDIO, '中间一段没字幕？用 **I / O** 框起来，右键「只重新识别这一段字幕…」，别的不会动。'),
    (STUDIO, '同一个错字到处都是：**Ctrl+H**「批量替换」，一次撤销也行。'),
    (STUDIO, '**Ctrl+L** 循环播放当前字幕，反复听一句最方便。'),
    (STUDIO, '**J / K / L** 是倒放、暂停、正放，再按 L 会加速。'),
    (STUDIO, '按 **E** 编辑播放头这条，Ctrl+Enter 提交并编辑下一条。'),
    (STUDIO, '想从字中间切开：编辑时把光标放好按 **Shift+C**。'),
    (STUDIO, '**Shift+Q / Shift+W** 和上一条 / 下一条合并。'),
    (STUDIO, '按 **R** 进入审核模式，1–4 选候选，Enter 确认。'),
    (STUDIO, '**G** 打开「轨道音量（分贝）」调音台，游戏声和麦克风能分开调。'),
    (STUDIO, '「工程音量 / 响度」先「重新测量」再选目标，整部片一起调大调小，不压缩起伏。'),
    (STUDIO, '画面上直接按住字幕就能拖位置，双语时按住哪层就拖哪层。'),
    (STUDIO, '复制样式 **Ctrl+Shift+C**，贴到别的字幕 Ctrl+Shift+V。'),
    (STUDIO, '只想导出中间一段？设好 I / O，「导出音视频」范围选「入点到出点」。'),
    (STUDIO, '**Ctrl+Alt+F** 保存当前帧当截图。'),
    (STUDIO, '在字幕上点右键选「问兔白这条」，兔白就带着那一条来帮你。'),
    (STUDIO, '字幕列表上面的「AI 工具」里有校对、清理、断句、翻译，一个菜单全找得到。'),
    (STUDIO, '每句前面想带名字：「说话人管理」改好名字，再勾「字幕前显示名字」。'),
    (STUDIO, '「AI设计」里用一句话描述想要的字幕样子，兔白的同事会出几个候选。'),
    (STUDIO, 'Esc 取消、Ctrl+Z 撤销，改坏了别怕～'),
)
OPENERS = ('小窍门时间～', '兔白偷偷告诉你：', '你知道吗？', '嘿嘿，教你一招：', '记一下这个：')


def _seen() -> list:
    from .onboarding import load_state
    value = load_state().get(SEEN_KEY)
    return [int(index) for index in value if isinstance(index, int)] if isinstance(value, list) else []


def _remember_seen(seen: list) -> None:
    from .onboarding import load_state, save_state
    save_state(dict(load_state(), **{SEEN_KEY: seen[-len(TIPS):]}))


def next_tip(page: str = '', *, rng=random) -> tuple[int, str]:
    """(index, text) of a tip she has not said yet, the page on screen first."""
    seen = set(_seen())
    here = [index for index, (where, _text) in enumerate(TIPS) if where in (page, ANY)]
    fresh = [index for index in here if index not in seen and TIPS[index][0] == page] or \
            [index for index in here if index not in seen]
    if not fresh:                                         # all heard here: start this page's round again
        seen -= set(here)
        _remember_seen([index for index in _seen() if index in seen])
        fresh = here
    index = rng.choice(fresh)
    _remember_seen([*[i for i in _seen() if i != index], index])
    return index, TIPS[index][1]


def tip_lines(page: str = '', *, rng=random) -> list[str]:
    """Her bubbles for one tip: a short opener, then the tip."""
    _index, text = next_tip(page, rng=rng)
    return [rng.choice(OPENERS), text]


def idle_allowed() -> bool:
    from .onboarding import load_state
    return load_state().get(IDLE_KEY, True) is not False


def set_idle_allowed(on: bool) -> None:
    from .onboarding import load_state, save_state
    save_state(dict(load_state(), **{IDLE_KEY: bool(on)}))


__all__ = ['IDLE_KEY', 'OPENERS', 'TIPS', 'idle_allowed', 'next_tip', 'set_idle_allowed', 'tip_lines']
