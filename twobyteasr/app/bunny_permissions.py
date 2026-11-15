"""「兔白权限」: how much 兔白 may do and read (2026-11-15, agent step 3).

User (2026-11-15): make her a looser, more capable agent, and let people decide. Three levels:

* ``guide``  只指路 — she looks and explains; no tool that changes anything runs;
* ``ask``    每次问我 (default) — the safe moves (pages, playhead, selection, in/out points,
  panels, opening windows) run at once; an edit she proposes waits for 「帮我做」;
* ``auto``   能撤销的直接做 — undoable edits run at once too, with 「撤销兔白刚才做的」 after.

Switches: reading subtitle text, reading the diagnostics / recognition records, her memory of
the user (``remember``), and whether AI processing that spends the user's own credit (AI 断句,
retrying failed AI steps) may run without a click — off by default, and only with 能撤销的直接做;
and whether each project's chat is kept on this computer (2026-11-16, on by default).
Never, at any level: uploading, deleting, starting a recognition or an export. Stored with the
chat's other choices (``onboarding`` state). No Qt.
"""
from __future__ import annotations

KEY = 'bunny_permissions'
LEVELS = ('guide', 'ask', 'auto')
LEVEL_LABELS = {'guide': '只指路（只看、只讲，不动手）',
                'ask': '小操作直接做，修改要我按「帮我做」',
                'auto': '能撤销的修改也直接做'}
CHIP_LABELS = {'guide': '只指路', 'ask': '修改先问我', 'auto': '能撤销的直接做'}     # short, for the settings chips
SWITCHES = ('read_subtitles', 'read_diagnostics', 'remember', 'allow_paid', 'keep_chat')
DEFAULTS = {'level': 'ask', 'read_subtitles': True, 'read_diagnostics': True, 'remember': True, 'allow_paid': False,
            'keep_chat': True}
SUBTITLE_READS = {'read_cues', 'find_cues', 'learned_edits', 'edit_cue', 'merge_cues', 'refine_cues'}
DIAGNOSTIC_READS = {'diagnostics', 'last_task', 'history'}
MEMORY_TOOLS = {'remember', 'forget', 'save_recipe', 'use_recipe'}


def load() -> dict:
    from .onboarding import load_state
    stored = load_state().get(KEY)
    merged = dict(DEFAULTS)
    if isinstance(stored, dict):
        if stored.get('level') in LEVELS:
            merged['level'] = stored['level']
        for name in SWITCHES:
            if isinstance(stored.get(name), bool):
                merged[name] = stored[name]
    return merged


def save(values: dict) -> dict:
    from .onboarding import load_state, save_state
    merged = dict(load())
    if values.get('level') in LEVELS:
        merged['level'] = values['level']
    for name in SWITCHES:
        if isinstance(values.get(name), bool):
            merged[name] = values[name]
    save_state(dict(load_state(), **{KEY: merged}))
    return merged


def describe(values: dict | None = None) -> str:
    """One line for her state: what she may do right now."""
    values = values or load()
    notes = []
    if not values['read_subtitles']:
        notes.append('不能读字幕原文')
    if not values['read_diagnostics']:
        notes.append('不能读诊断和识别记录')
    if not values['remember']:
        notes.append('不能记东西')
    paid_direct = values['allow_paid'] and values['level'] == 'auto'
    notes.append('会计费的 AI 处理' + ('也可以直接跑' if paid_direct else '要小兔纸按「帮我做」'))
    return LEVEL_LABELS[values['level']] + '；' + '、'.join(notes)


def refusal(tool, values: dict) -> str:
    """Why this tool may not run under these permissions, or '' when it may."""
    if tool.name in SUBTITLE_READS and not values['read_subtitles']:
        return '小兔纸在「兔白权限」里关掉了“让兔白读字幕原文”'
    if tool.name in DIAGNOSTIC_READS and not values['read_diagnostics']:
        return '小兔纸在「兔白权限」里关掉了“让兔白读诊断和识别记录”'
    if tool.name in MEMORY_TOOLS and not values['remember']:
        return '小兔纸在「兔白权限」里关掉了“让兔白记住我的习惯”'
    if values['level'] == 'guide' and (tool.acts or tool.edit or tool.paid or tool.name in MEMORY_TOOLS):
        return '小兔纸把兔白设成了「只指路」，兔白只讲不动手'
    return ''


def needs_confirmation(tool, values: dict) -> bool:
    if tool.paid:                                   # spends the user's own AI credit
        return not (values['level'] == 'auto' and values['allow_paid'])
    return bool(tool.edit) and values['level'] != 'auto'


__all__ = ['CHIP_LABELS', 'DEFAULTS', 'KEY', 'LEVELS', 'LEVEL_LABELS', 'SWITCHES', 'describe', 'load',
           'needs_confirmation', 'refusal', 'save']
