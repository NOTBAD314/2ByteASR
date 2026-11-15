"""兔白's own hands, step 1 (2026-11-15): what she can see, and the safe things she simply does.

User (2026-11-15): 兔白 should become a smarter agent that really does simple things for
beginners, with looser rules and more permission. Step 1 of the plan:

* she sees more: every question carries a summary of the moment (``snapshot``: the playhead, how
  many subtitles, which one is selected, the in/out points and whether 「只重新识别这一段字幕…」
  can run now and why not, review mode, the home page's language choices). Never subtitle text,
  file paths or keys;
* she can act in rounds: her answer may ask for ``tools``; the chat runs them on the GUI thread,
  hands her the receipts and the new state, and she goes on (``bunny_chat``), at most a few rounds;
* the 🟢 tools here run at once, without a 「帮我做」 click: they only move the view or the
  playhead, select, open a page / panel / window, or set the in/out points (one undo step). Nothing
  here spends money, uploads, deletes, starts a recognition or an export, or changes subtitle text;
  a window she opens is only opened, the user presses its buttons;
* a window opens only after she has finished answering (``deferred``): the dialogs run their own
  modal loop, which must not swallow the conversation.

Every tool returns one short receipt line in plain Chinese, which is what she reports; a tool
that cannot run raises ``ToolError`` with the reason, and she says that instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

MAX_PER_ROUND = 4
MAX_ROUNDS = 5


class ToolError(Exception):
    """A tool could not run; the message says why, in words she can repeat."""


@dataclass(frozen=True)
class Tool:
    name: str
    args: str                      # how to fill ``args``, for the prompt
    summary: str                   # what it does, for the prompt
    run: Callable                  # (window, args: dict) -> receipt line
    choices: dict = field(default_factory=dict)
    deferred: bool = False         # opens a window: runs after her answer is shown
    background: bool = False       # a slow read (bunny_lookup.run_check) beside her next AI request
    acts: bool = False             # moves the view, selects, opens (🟢): not under 「只指路」
    edit: bool = False             # an undoable edit (🟡): waits for 「帮我做」 unless 能撤销的直接做
    paid: bool = False             # AI work on the user's own key: waits for 「帮我做」 unless allowed


# ------------------------------------------------------------------ time and places
def parse_time(value) -> int:
    """'3:10' / '03:10.5' / '1:02:03' / '190' / 190 -> milliseconds."""
    text = str(value if value is not None else '').strip().replace('：', ':')
    if not text:
        raise ToolError('没有给时间')
    if re.fullmatch(r'\d+(\.\d+)?', text):
        return round(float(text) * 1000)
    parts = text.split(':')
    if not 2 <= len(parts) <= 3 or not all(re.fullmatch(r'\d+(\.\d+)?', part) for part in parts):
        raise ToolError(f'看不懂这个时间：{text}（要像 3:10 或 190 这样）')
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return round(seconds * 1000)


def clock(ms) -> str:
    ms = max(0, int(ms or 0))
    minutes, rest = divmod(ms, 60_000)
    hours, minutes = divmod(minutes, 60)
    seconds = rest / 1000
    head = f'{hours}:{minutes:02d}' if hours else f'{minutes}'
    return f'{head}:{seconds:04.1f}'


def _built(window, name):
    return getattr(window, 'built_page', lambda _name: None)(name)


def _studio(window):
    """The workbench page with a project, when it is the page on screen."""
    from .bunny_chat import current_page
    page = _built(window, 'studio')
    if page is None or current_page(window) != '字幕工作台':
        raise ToolError('现在不在字幕工作台（先用 open_page 打开 studio）')
    if getattr(page, 'project', None) is None:
        raise ToolError('字幕工作台还没有打开工程')
    return page


def _duration_ms(page) -> int:
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    project = page.project
    return int(timeline_duration_ms(project) or max((cue.end_ms for cue in project.cues), default=0))


def _cues(project):
    return sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms))


def _within(page, ms: int, what: str) -> int:
    duration = _duration_ms(page)
    if ms < 0 or (duration and ms > duration):
        raise ToolError(f'{what} {clock(ms)} 超出了时间轴（全长 {clock(duration)}）')
    return ms


# ------------------------------------------------------------------ what she sees
def snapshot(window) -> dict:
    """Whitelisted facts about this moment (``bunny_persona.STATE_FIELDS``); never subtitle text."""
    state = {}
    home = {'spoken_language': 'recognition_language', 'subtitle_output': 'subtitle_output',
            'translation_target': 'translation_script'}
    for name, attribute in home.items():
        combo = getattr(window, attribute, None)
        try:
            text = combo.currentText() if combo is not None else ''
        except RuntimeError:
            text = ''
        if text:
            state[name] = text
    try:
        from .bunny_subtitle_tools import break_language, current_rules
        rules = current_rules(break_language(window))
        if rules:
            state['break_rule'] = rules[:120]
    except Exception:  # noqa: BLE001
        pass
    page = _built(window, 'studio')
    project = getattr(page, 'project', None) if page is not None else None
    if project is None:
        return state
    try:
        cues = _cues(project)
        state['cue_count'] = len(cues)
        state['speakers'] = len(getattr(project, 'speakers', ()) or ())
        state['playhead'] = f'{clock(page.timeline.playhead_ms)} / 全长 {clock(_duration_ms(page))}'
        selected = list(page.selected_cue_ids()) if callable(getattr(page, 'selected_cue_ids', None)) else []
        order = {cue.id: index for index, cue in enumerate(cues, 1)}
        current = getattr(page, 'selected_cue_id', None)
        if current in order:
            cue = cues[order[current] - 1]
            extra = f'（一共选中 {len(selected)} 条）' if len(selected) > 1 else ''
            state['selected'] = f'第 {order[current]} 条，{clock(cue.start_ms)}–{clock(cue.end_ms)}{extra}'
        else:
            state['selected'] = '没有选中字幕'
        from ..projects.project_range import range_points
        points = range_points(project)
        state['in_out'] = ('入点 ' + (clock(points[0]) if points[0] is not None else '未设')
                           + '，出点 ' + (clock(points[1]) if points[1] is not None else '未设'))
        from ..studio.studio_range_recognition import range_state
        problem, _ = range_state(page)
        state['range_reasr'] = '可以用' if not problem else f'灰的：{problem}'
        review = getattr(page, 'review_mode_button', None)
        state['review_mode'] = bool(review is not None and review.isChecked())
        state['panels'] = '、'.join(name for name, visible in (
            ('字幕列表', page.source_tabs.isVisible()), ('工具面板', page.context_panel.isVisible())) if visible) or '都收起来了'
        if page.context_panel.isVisible():
            state['panels'] += f'（工具面板在「{page.context_drawer.tabText(page.context_drawer.currentIndex())}」）'
        state['recognizing'] = bool(getattr(page, '_recognition_running', False))
        refine = project.studio_state.get('ai_sentence_refine') or {}
        failed = refine_failed_ids(project)
        worker = getattr(page, '_refine_worker', None)
        if worker is not None and worker.isRunning():
            state['ai_refine'] = 'AI 断句正在跑'
        elif failed or refine.get('last_status'):
            state['ai_refine'] = (f'上次 AI 断句：{refine.get("last_status") or "?"}，{len(failed)} 条失败、保留了原文'
                                  if failed else f'上次 AI 断句：{refine.get("last_status")}')
        from .bunny_subtitle_tools import learned_summary
        from . import bunny_permissions
        learned = learned_summary(page) if bunny_permissions.load()['read_subtitles'] else ''
        if learned:
            state['learned'] = learned
    except Exception:  # noqa: BLE001 - a half-built page gives what it has
        pass
    return state


def _look(window, _args) -> str:
    from .bunny_chat import app_state
    from .bunny_persona import format_state
    return format_state(app_state(window, True)).replace('\n', '；')


# ------------------------------------------------------------------ pages and places
OPEN_PLACE_SKIP = {'issues', 'check_update', 'sample_project', 'tutorial', 'diagnostics'}


def _open_page(window, args) -> str:
    from .bunny_actions import PAGES, _open_page as run
    value = str(args.get('page') or '').strip()
    if value not in PAGES:
        raise ToolError(f'没有这个页面：{value}')
    return run(window, value)


def _place_entries(window):
    from .feature_search import entries
    return {entry.key: entry for entry in entries(window) if entry.key and entry.key not in OPEN_PLACE_SKIP}


def _open_place(window, args) -> str:
    key = str(args.get('key') or '').strip()
    entry = _place_entries(window).get(key)
    if entry is None:
        raise ToolError(f'这个地方兔白不能直接打开：{key}')
    return f'「{entry.title}」（位置：{entry.where}）会在兔白说完后打开'


# ------------------------------------------------------------------ the workbench
def _seek(window, args) -> str:
    page = _studio(window)
    ms = _within(page, parse_time(args.get('time')), '时间')
    if getattr(page, '_empty_playback_state', False) or not getattr(getattr(page, 'video', None), 'controller', None):
        raise ToolError('现在没有能播放的素材，播放头跳不过去')
    page._seek(ms / 1000.0)
    return f'播放头到 {clock(ms)} 了'


def _select_cue(window, args) -> str:
    page = _studio(window)
    cues = _cues(page.project)
    try:
        number = int(str(args.get('number')).strip())
    except (TypeError, ValueError):
        raise ToolError('要给第几条（数字）') from None
    if not 1 <= number <= len(cues):
        raise ToolError(f'没有第 {number} 条（一共 {len(cues)} 条）')
    cue = cues[number - 1]
    page.select_cue(cue.id)
    page._seek(cue.start_ms / 1000.0)
    return f'选中了第 {number} 条（{clock(cue.start_ms)}–{clock(cue.end_ms)}），播放头也到了那里'


def _set_in_out(window, args) -> str:
    page = _studio(window)
    start = _within(page, parse_time(args.get('start')), '入点')
    end = _within(page, parse_time(args.get('end')), '出点')
    if start >= end:
        raise ToolError('入点要早于出点')
    from ..projects.project_range import set_range
    set_range(page.project, start, end, page.undo_stack)
    page.timeline.update()
    from ..studio.studio_range_recognition import range_state
    problem, _ = range_state(page)
    tail = '，「只重新识别这一段字幕…」现在可以用' if not problem else f'，但「只重新识别这一段字幕…」还是灰的：{problem}'
    return f'入点 {clock(start)}、出点 {clock(end)} 设好了（Ctrl+Z 可以撤销）{tail}'


def _clear_in_out(window, _args) -> str:
    page = _studio(window)
    page._clear_range()
    return '入点和出点都清掉了（Ctrl+Z 可以撤销）'


def _play_pause(window, _args) -> str:
    page = _studio(window)
    page._toggle_playback()
    return '按了一下播放 / 暂停'


ZOOMS = {'in': '放大', 'out': '缩小', 'fit': '显示全部'}


def _zoom(window, args) -> str:
    page = _studio(window)
    how = str(args.get('how') or '').strip()
    if how == 'fit':
        page._fit_timeline()
    elif how in ('in', 'out'):
        page._zoom_timeline(0.5 if how == 'in' else 2.0)
    else:
        raise ToolError('how 只能是 in / out / fit')
    return f'时间轴{ZOOMS[how]}了'


PANELS = {'cue_list': '字幕列表', 'tool_panel': '工具面板', 'AI设计': 'AI设计', '样式': '样式', '动效': '动效',
          '视频': '视频', '剪辑助手': '剪辑助手', '素材': '素材'}


def _show_panel(window, args) -> str:
    page = _studio(window)
    name = str(args.get('name') or '').strip()
    if name not in PANELS:
        raise ToolError(f'没有这个面板：{name}')
    if name == 'cue_list':
        page._set_major_panel_visible('cue_list', True)
        return '字幕列表打开了'
    page._show_context_panel()
    if name == 'tool_panel':
        return '右边的工具面板打开了'
    drawer = page.context_drawer
    index = next((i for i in range(drawer.count()) if drawer.tabText(i) == name), -1)
    if index < 0:
        raise ToolError(f'工具面板里没有「{name}」')
    drawer.setCurrentIndex(index)
    return f'工具面板切到「{name}」了'


def _review(window, args) -> str:
    page = _studio(window)
    on = str(args.get('on', 'true')).strip().lower() not in ('false', '0', 'off', 'no')
    button = getattr(page, 'review_mode_button', None)
    if button is None or not button.isEnabled():
        raise ToolError('审核模式现在进不去')
    button.setChecked(on)
    return '进入了审核模式' if button.isChecked() else '退出了审核模式'


WINDOWS = {'export_subtitles': '导出字幕', 'export_video': '导出音视频（导出字幕视频）', 'find_replace': '批量替换',
           'speaker_manager': '说话人管理', 'subtitle_tasks': '字幕任务进度与结果',
           'range_recognition': '只重新识别这一段字幕', 'ai_proofread': 'AI 词库校对', 'ai_cleanup': 'AI 清理'}


def _open_window(window, args) -> str:
    page = _studio(window)
    name = str(args.get('name') or '').strip()
    if name not in WINDOWS:
        raise ToolError(f'没有这个窗口：{name}')
    if name == 'range_recognition':
        from ..studio.studio_range_recognition import range_state
        problem, _ = range_state(page)
        if problem:
            raise ToolError(f'「只重新识别这一段字幕」现在是灰的：{problem}')
    return f'「{WINDOWS[name]}」窗口会在兔白说完后打开，里面的按钮由小兔纸自己按'


def open_window_later(window, args) -> None:
    """The deferred half of ``open_window`` (and ``open_place``): runs after her answer."""
    page = _built(window, 'studio')
    name = str(args.get('name') or '').strip()
    if name == 'range_recognition':
        from ..studio.studio_range_recognition import open_range_recognition
        open_range_recognition(page)
        return
    {'export_subtitles': lambda: page.export_subtitles(), 'export_video': lambda: page._open_render_dialog(),
     'find_replace': lambda: page._open_find_replace(), 'speaker_manager': lambda: page._open_speaker_manager(),
     'subtitle_tasks': lambda: page.show_subtitle_tasks(),
     'ai_proofread': lambda: page.glossary_proofread_requested.emit(), 'ai_cleanup': lambda: page._open_ai_cleanup()}[name]()


# ------------------------------------------------------------------ step 2: reading (2026-11-15)
# User: she should see almost everything in the software and reason from it. These only read.
# Subtitle text does leave the computer here (to the user's own text AI), so it is only read when
# she asks for it, a bounded window at a time, and the manual says so to the user.
TEXT_LIMIT = 90
READ_LIMIT = 30


def _cue_line(number, cue, translations, flagged) -> str:
    def short(text):
        text = ' '.join(str(text or '').split())
        return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT - 1] + '…'
    parts = [f'第 {number} 条 {clock(cue.start_ms)}–{clock(cue.end_ms)}', f'说话人 {cue.speaker_id or "?"}',
             f'原文：{short(cue.text)}']
    if translations.get(cue.id):
        parts.append(f'译文：{short(translations[cue.id])}')
    if cue.id in flagged:
        parts.append('（待检查）')
    return ' | '.join(parts)


def _flagged(project) -> set:
    try:
        from ..subtitle_rules.current_issues import current_issue_view
        return {row.cue_id for row in current_issue_view(project).records if row.disposition == 'actionable'}
    except Exception:  # noqa: BLE001 - the issue view is a nicety
        return set()


def _read_cues(window, args) -> str:
    page = _studio(window)
    cues = _cues(page.project)
    if not cues:
        return '这个工程还没有字幕'
    if args.get('from') not in (None, ''):
        try:
            start = int(str(args.get('from')).strip())
        except ValueError:
            raise ToolError('from 要给第几条（数字）') from None
    else:                                           # around the playhead
        here = int(page.timeline.playhead_ms)
        start = next((i for i, cue in enumerate(cues, 1) if cue.end_ms >= here), len(cues)) - 2
    try:
        count = max(1, min(READ_LIMIT, int(args.get('count') or 10)))
    except (TypeError, ValueError):
        count = 10
    start = max(1, min(start, len(cues)))
    translations = page.project.generation_metadata.get('translations') or {}
    flagged = _flagged(page.project)
    rows = [_cue_line(n, cues[n - 1], translations, flagged) for n in range(start, min(len(cues), start + count - 1) + 1)]
    return f'一共 {len(cues)} 条，这是第 {start}–{start + len(rows) - 1} 条：\n' + '\n'.join(rows)


def _find_cues(window, args) -> str:
    page = _studio(window)
    needle = str(args.get('text') or '').strip()
    if not needle:
        raise ToolError('要给要找的字')
    cues = _cues(page.project)
    translations = page.project.generation_metadata.get('translations') or {}
    hits = [(n, cue) for n, cue in enumerate(cues, 1)
            if needle.casefold() in str(cue.text or '').casefold()
            or needle.casefold() in str(translations.get(cue.id) or '').casefold()]
    if not hits:
        return f'没有字幕包含「{needle}」'
    flagged = _flagged(page.project)
    rows = [_cue_line(n, cue, translations, flagged) for n, cue in hits[:15]]
    more = f'（一共 {len(hits)} 条，只列前 15 条）' if len(hits) > 15 else f'（一共 {len(hits)} 条）'
    return f'包含「{needle}」的字幕{more}：\n' + '\n'.join(rows)


def _project_info(window, _args) -> str:
    page = _studio(window)
    project = page.project
    cues = _cues(project)
    lines = [f'字幕 {len(cues)} 条，时间轴全长 {clock(_duration_ms(page))}']
    counts = {}
    for cue in cues:
        counts[cue.speaker_id] = counts.get(cue.speaker_id, 0) + 1
    speakers = [f'{getattr(s, "name", "") or s.id}（{s.id}，{counts.get(s.id, 0)} 条）' for s in getattr(project, 'speakers', ())]
    lines.append('说话人：' + ('、'.join(speakers) or '没有'))
    translations = project.generation_metadata.get('translations') or {}
    if translations:
        done = sum(1 for cue in cues if translations.get(cue.id))
        lines.append(f'译文：{done}/{len(cues)} 条有译文')
    flagged = _flagged(project)
    lines.append(f'待检查的字幕：{len(flagged)} 条')
    media = getattr(project, 'media', None)
    if media is not None:
        size = f'，画面 {media.width}×{media.height}' if getattr(media, 'width', 0) else ''
        lines.append(f'素材时长 {clock(getattr(media, "duration_ms", 0))}{size}；素材库里 {len(getattr(project, "media_pool", ()) or ())} 个素材，'
                     f'{len(getattr(project, "audio_tracks", ()) or ())} 条音轨')
    lines.append(f'用了 {len(getattr(project, "glossary_ids", ()) or ())} 个词库')
    stack = getattr(page, 'undo_stack', None)
    if stack is not None:
        lines.append('有还没保存的修改' if not stack.isClean() else '修改都保存了')
    return '\n'.join(lines)


def _ui_info(window, _args) -> str:
    """What is on screen beyond the page: open windows, the status line, the home page's readiness."""
    from PySide6.QtWidgets import QApplication
    from .bunny_chat import current_page
    lines = [f'当前页面：{current_page(window) or "不清楚"}']
    modal = QApplication.activeModalWidget()
    if modal is not None and modal.windowTitle():
        lines.append(f'正开着一个必须先处理的窗口：「{modal.windowTitle()}」')
    others = [top.windowTitle() for top in QApplication.topLevelWidgets()
              if top.isVisible() and top is not window and top.windowTitle() and top is not modal
              and top.objectName() not in ('bunnyChat', 'bunnyCarrier')]
    if others:
        lines.append('其他开着的窗口：' + '、'.join(f'「{title}」' for title in others[:6]))
    status = getattr(window, 'action_status', None)
    start = getattr(window, 'start_button', None)
    if status is not None and status.text():
        lines.append(f'首页底部提示：{" ".join(status.text().split())}')
    if start is not None:
        lines.append('「开始生成字幕」' + ('可以按' if start.isEnabled() else '现在是灰的') +
                     (f'（{start.toolTip()}）' if start.toolTip() and not start.isEnabled() else ''))
    lines.append(f'首页选了 {len(getattr(window, "media_paths", None) or [])} 个素材')
    retry = getattr(window, 'retry_failed_button', None)
    if retry is not None and retry.isVisible():
        card = getattr(getattr(window, 'result_todo', None), 'retry_card', None)
        title = ' '.join(card.title.text().split()) if card is not None and hasattr(card, 'title') else ''
        body = ' '.join(card.toolTip().split()) if card is not None else ''
        lines.append(f'完成页有「{title or " ".join(retry.text().split()) or "重试"}」' + ('可以按' if retry.isEnabled() else '（灰的）')
                     + (f'：{body[:140]}' if body else ''))
    page = _built(window, 'studio')
    if page is not None and getattr(page, 'project', None) is not None:
        state_label = getattr(page, 'save_state', None)
        if state_label is not None and state_label.text():
            lines.append(f'工作台状态栏：{" ".join(state_label.text().split())[:120]}')
    return '\n'.join(lines)


# ------------------------------------------------------------------ step 3: undoable edits (2026-11-15)
# Each goes through the same command the user's own click pushes, so Ctrl+Z works, and returns
# (receipt, undo record) so 「撤销兔白刚才做的」 can take exactly her steps back.
@dataclass
class UndoRecord:
    kind: str                       # 'stack': undo `steps` on `target`; 'combo': back to `index`;
                                    # 'call': `target()` restores, returns '' or why not; 'group': records
    target: object
    index: int
    steps: int = 0
    commands: tuple = ()
    after: int | None = None


def _pushed(page, before: int, what: str):
    stack = page.undo_stack
    steps = stack.index() - before
    if steps <= 0:
        hint = getattr(getattr(page, 'save_state', None), 'text', lambda: '')()
        raise ToolError(f'{what}没改成' + (f'：{hint}' if hint else ''))
    return UndoRecord('stack', stack, stack.index(), steps,
                      tuple(stack.command(i) for i in range(before, stack.index())))


def _shift_timing(window, args):
    page = _studio(window)
    try:
        ms = int(round(float(args.get('ms'))))
    except (TypeError, ValueError):
        raise ToolError('ms 要给毫秒数，负数是提前，例如 -500') from None
    if not ms or abs(ms) > 60_000:
        raise ToolError('一次最多移 60 秒，也不能是 0')
    scope = str(args.get('scope') or 'selected').strip()
    ids = [cue.id for cue in page.project.cues] if scope == 'all' else list(page.selected_cue_ids())
    if not ids:
        raise ToolError('没有选中的字幕（可以用 scope=all 移全部）')
    before = page.undo_stack.index()
    page.cue_controller.apply_timing_offset(ids, ms)
    undo = _pushed(page, before, '整体偏移')
    which = '全部' if scope == 'all' else '选中的'
    return f'把{which} {len(ids)} 条字幕{"提前" if ms < 0 else "推后"}了 {abs(ms) / 1000:g} 秒（Ctrl+Z 可以撤销）', undo


def _speaker_by(project, value):
    text = str(value or '').strip()
    from ..projects.speaker_names import display_speaker_name
    for speaker in getattr(project, 'speakers', ()):
        names = {speaker.id, str(speaker.name or '')}
        try:
            names.add(str(display_speaker_name(project, speaker.id)))
        except Exception:  # noqa: BLE001
            pass
        if text and text in names:
            return speaker
    return None


def _rename_speaker(window, args):
    page = _studio(window)
    speaker = _speaker_by(page.project, args.get('speaker'))
    name = ' '.join(str(args.get('name') or '').split())[:40]
    if speaker is None:
        known = '、'.join(f'{s.name or s.id}（{s.id}）' for s in page.project.speakers) or '没有说话人'
        raise ToolError(f'找不到说话人「{args.get("speaker")}」（现在有：{known}）')
    if not name:
        raise ToolError('要给新名字')
    from ..timeline.studio_commands import SetSpeakerCommand
    before = page.undo_stack.index()
    page.undo_stack.push(SetSpeakerCommand(page.project, speaker.id, {'name': name}, text='修改说话人名称',
                                           changed=page._speaker_structure_changed))
    return f'把 {speaker.id} 改名为「{name}」（Ctrl+Z 可以撤销）', _pushed(page, before, '改名')


def _show_speaker_names(window, args):
    page = _studio(window)
    on = str(args.get('on', 'true')).strip().lower() not in ('false', '0', 'off', 'no')
    from ..studio.speaker_name_controls import SetSpeakerNamesCommand
    before = page.undo_stack.index()
    page.undo_stack.push(SetSpeakerNamesCommand(page.project, on))
    return ('每句字幕前面会显示说话人的名字' if on else '字幕前面不再显示名字') + '（Ctrl+Z 可以撤销）', \
        _pushed(page, before, '显示名字')


STYLE_SCOPES = {'current': '当前字幕', 'selected': '选中字幕', 'speaker': '该说话人', 'all': '全片'}


def _apply_style(window, args):
    from PySide6.QtGui import QColor
    page = _studio(window)
    scope = str(args.get('scope') or 'current').strip()
    if scope not in STYLE_SCOPES:
        raise ToolError('scope 只能是 current / selected / speaker / all')
    changes = {}
    for key in ('fill_color', 'outline_color'):
        if args.get(key) not in (None, ''):
            value = str(args[key]).strip()
            if not QColor(value).isValid():
                raise ToolError(f'看不懂这个颜色：{value}（要像 #FFD400 这样）')
            changes[key] = QColor(value).name().upper()
    for key, low, high in (('font_size', 8, 300), ('outline_width', 0, 30)):
        if args.get(key) not in (None, ''):
            try:
                number = float(args[key])
            except (TypeError, ValueError):
                raise ToolError(f'{key} 要给数字') from None
            if not low <= number <= high:
                raise ToolError(f'{key} 要在 {low} 到 {high} 之间')
            changes[key] = number
    if isinstance(args.get('bold'), bool):
        changes['bold'] = args['bold']
    if not changes:
        raise ToolError('没有给要改的样式（font_size / fill_color / outline_color / outline_width / bold）')
    if not getattr(page, 'selected_cue_id', None):
        first = _cues(page.project)[0] if page.project.cues else None
        if first is None:
            raise ToolError('工程里没有字幕')
        page.select_cue(first.id)
    page._show_context_panel()
    drawer = page.context_drawer
    drawer.setCurrentIndex(next((i for i in range(drawer.count()) if drawer.tabText(i) == '样式'), drawer.currentIndex()))
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    index = page.style_scope.findData(scope)
    if index < 0:
        raise ToolError('样式面板还没准备好')
    page.style_scope.setCurrentIndex(index)
    if 'font_size' in changes:
        page.style_font_size.setValue(changes['font_size'])
    if 'fill_color' in changes:
        page.style_fill_color.setText(changes['fill_color'])
    if 'outline_color' in changes:
        page.style_outline_color.setText(changes['outline_color'])
    if 'outline_width' in changes:
        page.style_outline_width.setValue(changes['outline_width'])
    if 'bold' in changes:
        page.style_bold.setChecked(changes['bold'])
    before = page.undo_stack.index()
    page.style_controller._apply_style()
    undo = _pushed(page, before, '改样式')
    said = '、'.join(f'{name}={value}' for name, value in changes.items())
    return f'给「{STYLE_SCOPES[scope]}」改了样式：{said}（Ctrl+Z 可以撤销）', undo


HOME_FIELDS = {'spoken_language': ('set_spoken_language', 'recognition_language'),
               'subtitle_output': ('set_subtitle_output', 'subtitle_output'),
               'translation_target': ('set_translation_target', 'translation_script')}


def _set_home(window, args):
    from .bunny_actions import ACTIONS
    field_name = str(args.get('field') or '').strip()
    if field_name not in HOME_FIELDS:
        raise ToolError('field 只能是 spoken_language / subtitle_output / translation_target')
    action_key, attribute = HOME_FIELDS[field_name]
    action = ACTIONS[action_key]
    value = str(args.get('value') or '').strip()
    if value not in action.choices:
        raise ToolError(f'没有这个选项：{value}（可填：{"、".join(action.choices)}）')
    combo = getattr(window, attribute, None)
    previous = combo.currentIndex() if combo is not None else -1
    try:
        done = action.run(window, value)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from None
    return done, (UndoRecord('combo', combo, previous, after=combo.currentIndex()) if combo is not None else None)


# ------------------------------------------------------------------ step 4: fixing with AI, memory (2026-11-15)
# User: when AI 断句 / 校对 fell back to the local rules, she should fix and fill it in herself.
# These spend the user's own AI credit, so they wait for 「帮我做」 unless the user allowed them.
def refine_failed_ids(project) -> list:
    return list((project.studio_state.get('ai_sentence_refine') or {}).get('failed_cue_ids', ()) or ())


def _ai_refine(window, args):
    page = _studio(window)
    scope = str(args.get('scope') or 'failed').strip()
    if scope not in ('failed', 'all', 'selected'):
        raise ToolError('scope 只能是 failed（只重跑失败的）/ all / selected')
    worker = getattr(page, '_refine_worker', None)
    if worker is not None and worker.isRunning():
        raise ToolError('AI 断句已经在跑了，等它做完')
    from ..providers.llm_config import text_ai_key_missing
    from ..storage.settings import load_runtime_settings
    settings = load_runtime_settings()
    settings = settings[0] if isinstance(settings, tuple) else settings
    if text_ai_key_missing(settings, 'group'):
        raise ToolError('还没填文字 AI 的 API Key（「AI 智能断句设置」）')
    if scope == 'failed':
        count = len(refine_failed_ids(page.project))
        if not count:
            raise ToolError('上次 AI 断句没有失败的范围')
    elif scope == 'selected':
        count = len(page.selected_cue_ids())
        if not count:
            raise ToolError('没有选中的字幕')
    else:
        count = len(page.project.cues)
    page.run_sentence_refine(whole_project=scope == 'all', retry_failed=scope == 'failed')
    started = getattr(page, '_refine_worker', None)
    if started is None or not started.isRunning():
        hint = getattr(getattr(page, 'save_state', None), 'text', lambda: '')()
        raise ToolError(f'AI 断句没开始{"：" + hint if hint else ""}')
    from .bunny_subtitle_tools import watch_refine
    watch_refine(page, 'full', [])
    what = {'failed': '上次失败的', 'all': '整个工程的', 'selected': '选中的'}[scope]
    return f'开始用 AI 重新断句{what} {count} 条（用小兔纸自己的 Key 计费）；做完会写回字幕，可以 Ctrl+Z，进度在「字幕任务进度与结果」'


def _retry_failed(window, _args):
    from .bunny_chat import current_page
    button = getattr(window, 'retry_failed_button', None)
    if current_page(window) != '识别完成的结果页' or button is None or not button.isVisible():
        raise ToolError('现在不在识别完成的结果页，或者那里没有要重试的东西')
    if not button.isEnabled():
        raise ToolError('完成页的「重试」现在是灰的')
    return f'完成页的「{" ".join(button.text().split()) or "重试"}」会在兔白说完后按下（会用小兔纸的 Key，可能计费）；结果出来要小兔纸确认才写回'


def retry_later(window, _args) -> None:
    button = getattr(window, 'retry_failed_button', None)
    if button is not None and button.isVisible() and button.isEnabled():
        button.click()


def _remember(window, args):
    from . import bunny_memory
    try:
        entry = bunny_memory.add(args.get('text'), 'memory', source='bunny')
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return f'记下了 [{entry["id"]}]：{entry["text"]}（小兔纸可以在「设置」→「兔白权限」里看和删）'


def _forget(window, args):
    from . import bunny_memory
    gone = bunny_memory.remove(args.get('id'))
    if gone is None:
        raise ToolError(f'没有编号 {args.get("id")} 的记忆')
    return f'忘掉了：{gone["text"]}'


def undo_records(records) -> tuple[int, str]:
    """Take her last edits back, newest first. (steps undone, '' or why it stopped)."""
    undone = 0
    for record in reversed(list(records)):
        if record is None:
            continue
        if record.kind == 'group':
            count, why = undo_records(record.target)
            undone += 1 if count else 0
            if why:
                return undone, why
            continue
        if record.kind == 'call':
            why = record.target()
            if why:
                return undone, why
            undone += 1
            continue
        if record.kind == 'combo':
            if record.target.currentIndex() != record.after:
                return undone, '之后又有别的修改，兔白不敢乱撤；请手动恢复首页选项'
            record.target.setCurrentIndex(record.index)
            undone += 1
            continue
        stack = record.target
        if (stack.index() != record.index or
                tuple(stack.command(i) for i in range(record.index - record.steps, record.index)) != record.commands):
            return undone, '之后又有别的修改，兔白不敢乱撤；请用 Ctrl+Z 一步步撤回'
        for _ in range(record.steps):
            stack.undo()
        undone += 1
    return undone, ''


def edit_context(window) -> tuple:
    """Bind deferred consent to the project, selection and current edit history."""
    from .bunny_chat import current_page
    page = _built(window, 'studio')
    stack = getattr(page, 'undo_stack', None)
    index = stack.index() if stack is not None else 0
    selected = tuple(page.selected_cue_ids()) if callable(getattr(page, 'selected_cue_ids', None)) else ()
    home = tuple(getattr(window, name).currentIndex() if getattr(window, name, None) is not None else None
                 for _action, name in HOME_FIELDS.values())
    return (current_page(window), id(getattr(page, 'project', None)), selected, index,
            stack.command(index - 1) if index else None, home)


# Background tools: slow reads that run beside her AI request, off the GUI thread (bunny_lookup).
BACKGROUND = {
    'last_task': '最近一次识别任务：状态、用的模型、问题和本机诊断',
    'history': '最近几次识别任务的列表',
    'diagnostics': '软件自己的诊断摘要（和「回报问题／导出诊断」同一份，已隐藏路径）：最近的错误、卡顿、异常操作',
    'hardware': '这台电脑：显卡显存、处理器、内存、磁盘、现在的方案要不要 NVIDIA',
    'settings': '现在的识别和 AI 设置（模型、开关；不含 Key）',
    'models': '本机装了哪些模型、哪些不完整、哪些在下载',
}


def _tools() -> dict:
    from .bunny_actions import PAGES
    from .bunny_subtitle_tools import tools as subtitle_tools
    items = (
        Tool('look', '{}', '重新看一眼现在的软件状态（做完操作后会自动附上，一般不用单独叫）', _look),
        Tool('open_page', '{"page": "studio"}', '切换页面', _open_page, dict(PAGES), acts=True),
        Tool('open_place', '{"key": "shortcuts"}', '打开「可以指的位置」里的一个地方（设置的某一页、AI 设置、申请 API、模型工坊……）；'
             '不能打开：' + '、'.join(sorted(OPEN_PLACE_SKIP)), _open_place, deferred=True, acts=True),
        Tool('seek', '{"time": "3:10"}', '工作台：把播放头移到某个时间', _seek, acts=True),
        Tool('select_cue', '{"number": 12}', '工作台：选中第几条字幕（按时间顺序数，从 1 开始），播放头也跳过去', _select_cue, acts=True),
        Tool('set_in_out', '{"start": "3:10", "end": "4:05"}', '工作台：设好入点和出点（一步可撤销）', _set_in_out, acts=True),
        Tool('clear_in_out', '{}', '工作台：清掉入点和出点', _clear_in_out, acts=True),
        Tool('play_pause', '{}', '工作台：按一下播放 / 暂停', _play_pause, acts=True),
        Tool('zoom_timeline', '{"how": "in"}', '工作台：时间轴放大 / 缩小 / 显示全部', _zoom, dict(ZOOMS), acts=True),
        Tool('show_panel', '{"name": "样式"}', '工作台：打开字幕列表、工具面板，或切到工具面板的某一页', _show_panel,
             dict(PANELS), acts=True),
        Tool('review_mode', '{"on": true}', '工作台：进入或退出审核模式', _review, acts=True),
        Tool('open_window', '{"name": "export_video"}', '工作台：打开一个窗口（只是打开，开始导出、替换、识别这些按钮由小兔纸自己按）',
             _open_window, dict(WINDOWS), deferred=True, acts=True),
        Tool('shift_timing', '{"scope": "all", "ms": -500}', '【修改】工作台：把全部（all）或选中的（selected）字幕整体提前（负数）或推后，单位毫秒，一步可撤销', _shift_timing, {'all': '全部', 'selected': '选中的'}, edit=True),
        Tool('rename_speaker', '{"speaker": "S01", "name": "主播"}', '【修改】工作台：给说话人改名（speaker 填编号或现在的名字）', _rename_speaker, edit=True),
        Tool('show_speaker_names', '{"on": true}', '【修改】工作台：每句字幕前显示 / 不显示说话人名字（「字幕前显示名字」）', _show_speaker_names, edit=True),
        Tool('apply_style', '{"scope": "all", "fill_color": "#FFD400", "outline_color": "#000000", "outline_width": 4, "font_size": 60, "bold": true}', '【修改】工作台：改字幕样式（只填要改的项），套到当前 / 选中 / 该说话人 / 全片', _apply_style, dict(STYLE_SCOPES), edit=True),
        Tool('set_home', '{"field": "subtitle_output", "value": "bilingual"}', '【修改】首页的「视频里说的话」（spoken_language）、「字幕显示」（subtitle_output）、「翻译成」（translation_target），value 用「可以帮忙做的事」里的选项', _set_home, edit=True),
        Tool('ai_refine', '{"scope": "failed"}', '【花 Key】工作台：用 AI 重新断句：failed=只重跑上次失败、退回本地规则的范围（最常用）、all=整个工程、selected=选中的；后台跑，做完写回，可撤销', _ai_refine, {'failed': '只重跑失败的', 'all': '整个工程', 'selected': '选中的'}, paid=True),
        Tool('retry_failed', '{}', '【花 Key】识别完成的结果页：按「重试」，只补做没跑完的 AI 校对 / 可选阶段 / 失败的识别；结果出来由小兔纸确认写回', _retry_failed, deferred=True, paid=True),
        Tool('remember', '{"text": "做原神实况，喜欢黄色描边"}', '记住小兔纸的一个长期习惯或喜好（一句话，最多 160 字）；不记密钥、密码、账号、一次性的小事', _remember),
        Tool('forget', '{"id": 3}', '忘掉一条记忆（编号见「兔白记住的小兔纸」）', _forget),
        *subtitle_tools(),
        Tool('read_cues', '{"from": 37, "count": 10}', f'工作台：读字幕（第几条开始、几条，最多 {READ_LIMIT} 条；不填 from 就读播放头附近）：时间、说话人、原文、译文、是否待检查', _read_cues),
        Tool('find_cues', '{"text": "派门"}', '工作台：找包含某些字的字幕（原文或译文），列出第几条', _find_cues),
        Tool('project_info', '{}', '工作台：工程概况：说话人和各自条数、译文有多少、待检查几条、素材和音轨、词库、有没有没保存的修改', _project_info),
        Tool('ui_info', '{}', '屏幕上的情况：开着哪些窗口、首页底部提示和「开始生成字幕」能不能按、工作台状态栏', _ui_info),
        *(Tool(name, '{}', f'（后台查，稍慢）{summary}', None, background=True) for name, summary in BACKGROUND.items()),
    )
    return {tool.name: tool for tool in items}


TOOLS = _tools()


def valid_calls(value) -> list[tuple[str, dict]]:
    """The AI's ``tools`` list cleaned: known names only, dict args, at most ``MAX_PER_ROUND``."""
    calls = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if name not in TOOLS:
            continue
        args = item.get('args')
        if not isinstance(args, dict):
            # The AI sometimes writes {"name": "select_cue", "number": 25} or {"args": 25}: same meaning.
            loose = {key: val for key, val in item.items() if key not in ('name', 'args')}
            params = list(_params(name))
            if args not in (None, '') and not loose and len(params) == 1:
                loose = {params[0]: args}
            args = loose
        calls.append((name, args))
    return calls[:MAX_PER_ROUND]


def _params(name: str) -> dict:
    import json
    try:
        example = json.loads(TOOLS[name].args)
    except ValueError:
        return {}
    return example if isinstance(example, dict) else {}


def split_calls(calls, permissions=None) -> tuple[list, list]:
    """(calls handled on the GUI thread, background reads for the worker). A background read the
    permissions refuse stays with the GUI calls, so its refusal is reported there."""
    from . import bunny_permissions
    background = [name for name, _args in calls if TOOLS[name].background
                  and not (permissions is not None and bunny_permissions.refusal(TOOLS[name], permissions))]
    now = [(name, args) for name, args in calls if name not in background]
    return now, background


def run_background(names, *, ai_ready=None, settings=None) -> list[str]:
    """The slow reads, on the worker thread; one receipt each."""
    from .bunny_lookup import run_check
    receipts = []
    for name in dict.fromkeys(names):
        try:
            from . import bunny_permissions
            refused = bunny_permissions.refusal(TOOLS[name], bunny_permissions.load())
            if refused:
                receipts.append(f'- {name}：没有读取。{refused}')
                continue
            found = run_check(name, ai_ready=ai_ready, settings=settings) or '（没有查到内容）'
            receipts.append(f'- {name}：\n{found}')
        except Exception as exc:  # noqa: BLE001
            receipts.append(f'- {name}：没查到。{type(exc).__name__}')
    return receipts


@dataclass
class TurnResult:
    receipts: list = field(default_factory=list)
    later: list = field(default_factory=list)       # windows to open after her answer
    pending: list = field(default_factory=list)     # edits waiting for 「帮我做」
    undo: list = field(default_factory=list)        # UndoRecord of the edits that ran


def call_text(name: str, args: dict) -> str:
    return f'{name}(' + ', '.join(f'{key}={value}' for key, value in args.items()) + ')'


def run_turn(window, calls, permissions=None, *, confirmed: bool = False) -> TurnResult:
    """Run the calls under 「兔白权限」 (``bunny_permissions``); ``None`` permits everything (tests, audits)."""
    from . import bunny_permissions
    result = TurnResult()
    for name, args in calls:
        tool = TOOLS[name]
        shown = call_text(name, args)
        refused = bunny_permissions.refusal(tool, permissions) if permissions is not None else ''
        if refused:
            result.receipts.append(f'- {shown}：没做成。{refused}')
            continue
        if tool.background:
            continue                               # read on the worker (split_calls)
        if (permissions is not None and not confirmed and bunny_permissions.needs_confirmation(tool, permissions)):
            result.pending.append((name, args))
            result.receipts.append(f'- {shown}：还没做，等小兔纸按「帮我做」才会做（现在的「兔白权限」是修改要先问）')
            continue
        try:
            done = tool.run(window, args)
            if isinstance(done, tuple):
                done, record = done
                result.undo.append(record)
            result.receipts.append(f'- {shown}：成功。{done}')
            if tool.deferred:
                result.later.append((name, args))
        except ToolError as exc:
            result.receipts.append(f'- {shown}：没做成。{exc}')
        except Exception as exc:  # noqa: BLE001 - a surprise is reported, never raised into the chat
            result.receipts.append(f'- {shown}：没做成。{type(exc).__name__}: {str(exc)[:80]}')
    return result


def run_calls(window, calls) -> tuple[list[str], list[tuple[str, dict]]]:
    """Run the calls now, everything permitted; (receipt lines, windows to open after her answer)."""
    result = run_turn(window, calls, None)
    return result.receipts, result.later


def pending_summary(pending) -> str:
    """What 「帮我做」 will do, in a few words for the button."""
    words = {'ai_refine': lambda a: {'failed': '用 AI 重跑失败的断句', 'all': '用 AI 重新断句整个工程', 'selected': '用 AI 重新断句选中的'}.get(a.get('scope', 'failed'), 'AI 断句'),
             'retry_failed': lambda a: '按完成页的「重试」补做',
             'shift_timing': lambda a: f'{"全部" if a.get("scope") == "all" else "选中的"}字幕{"提前" if float(a.get("ms") or 0) < 0 else "推后"} {abs(float(a.get("ms") or 0)) / 1000:g} 秒',
             'rename_speaker': lambda a: f'{a.get("speaker")} 改名为「{a.get("name")}」',
             'show_speaker_names': lambda a: '字幕前显示名字' if str(a.get('on', True)).lower() not in ('false', '0') else '不显示名字',
             'apply_style': lambda a: f'改{STYLE_SCOPES.get(a.get("scope", "current"), "")}的样式',
             'set_home': lambda a: f'首页{a.get("field")}改成 {a.get("value")}',
             'set_break_rule': lambda a: f'断句偏好改成「{str(a.get("rule") or "")[:18]}」' if a.get('rule') else '清掉断句偏好',
             'refine_cues': lambda a: f'用 AI 试断第 {a.get("from", 1)} 条起 {a.get("count", 5)} 条' if not a.get('numbers') else f'用 AI 断句第 {"、".join(str(n) for n in a["numbers"][:4])} 条',
             'fix_subtitles': lambda a: '安全修复体检出的问题',
             'edit_cue': lambda a: f'第 {a.get("number")} 条{"译文" if a.get("layer") == "translation" else ""}改成「{str(a.get("text") or "")[:14]}」',
             'replace_text': lambda a: f'「{a.get("find")}」全换成「{a.get("replace")}」',
             'merge_cues': lambda a: f'合并第 {a.get("from")}–{a.get("to")} 条',
             'use_recipe': lambda a: f'照配方「{a.get("name")}」套用'}
    parts = []
    for name, args in pending:
        try:
            parts.append(words[name](args))
        except Exception:  # noqa: BLE001
            parts.append(name)
    return '、'.join(parts[:2]) + (f' 等 {len(parts)} 项' if len(parts) > 2 else '')


def run_later(window, name: str, args: dict) -> None:
    if name == 'retry_failed':
        retry_later(window, args)
    elif name == 'open_window':
        open_window_later(window, args)
    elif name == 'open_place':
        entry = _place_entries(window).get(str(args.get('key') or '').strip())
        if entry is not None:
            entry.run()


def describe_for_prompt() -> str:
    rows = []
    for tool in TOOLS.values():
        choices = f'。可填：{"、".join(f"{key}={label}" for key, label in tool.choices.items())}' if tool.choices else ''
        rows.append(f'- {tool.name} {tool.args}：{tool.summary}{choices}')
    return '\n'.join(rows)


__all__ = ['MAX_PER_ROUND', 'MAX_ROUNDS', 'TOOLS', 'Tool', 'ToolError', 'clock', 'describe_for_prompt', 'parse_time',
           'run_calls', 'run_later', 'snapshot', 'valid_calls']
