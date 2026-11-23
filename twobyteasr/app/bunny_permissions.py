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
2026-11-16 (user): whether she may take a picture of 2ByteASR's own windows (``see_screen``, off by
default, ``bunny_vision``); and changes that stay after a restart (``user_overlay``: styles, texts,
notes, scripts) always wait for 「帮我做」, even with 能撤销的直接做.
2026-11-16 (user, harness plan P3): folders the user adds (``folders``, none by default) — only inside
them she lists, reads, writes new files (always after 「帮我做」, never over an existing file) and imports
term lists (``bunny_files``).
2026-11-20 (user): she may change existing files in those folders too (``edit_file``: the old file is kept
aside, undoable, always after 「帮我做」) and save the workbench subtitles there (``export_subtitles``);
``files_anywhere`` (off by default) lets her read and write files anywhere on this computer by full path,
never in Windows, the program folders or this app's own data.
Never, at any level: uploading, deleting, starting a recognition or a video export. Stored with the
chat's other choices (``onboarding`` state). No Qt.
"""
from __future__ import annotations

KEY = 'bunny_permissions'
LEVELS = ('guide', 'ask', 'auto')
LEVEL_LABELS = {'guide': '只指路（只看、只讲，不动手）',
                'ask': '小操作直接做，修改要我按「帮我做」',
                'auto': '能撤销的修改也直接做'}
CHIP_LABELS = {'guide': '只指路', 'ask': '修改先问我', 'auto': '能撤销的直接做'}     # short, for the settings chips
SWITCHES = ('read_subtitles', 'read_diagnostics', 'remember', 'allow_paid', 'keep_chat', 'see_screen', 'files_anywhere')
DEFAULTS = {'level': 'ask', 'read_subtitles': True, 'read_diagnostics': True, 'remember': True, 'allow_paid': False,
            'keep_chat': True, 'see_screen': False, 'files_anywhere': False}
FOLDERS_KEY = 'folders'      # 2026-11-16: folders she may list, read and write new files in (default none)
MAX_FOLDERS = 12
FILE_TOOLS = {'list_folder', 'search_files', 'read_file', 'write_file', 'edit_file', 'export_subtitles', 'import_terms_file'}
SUBTITLE_READS = {'read_cues', 'find_cues', 'learned_edits', 'edit_cue', 'merge_cues', 'refine_cues',
                  'ui_snapshot', 'ui_set', 'recent_actions', 'replay_action'}
DIAGNOSTIC_READS = {'diagnostics', 'last_task', 'history', 'recent_results', 'open_result',
                    'recent_projects', 'open_project', 'ui_snapshot', 'recent_actions', 'replay_action',
                    'analyze_recognition', 'review_issues', 'exports'}
MEMORY_TOOLS = {'remember', 'forget', 'save_recipe', 'use_recipe'}
MEMORY_READS = {'recent_actions', 'replay_action'}
SCREEN_TOOLS = {'look_screen'}
SCREEN_ACK_KEY = 'bunny_see_screen_explained'     # the first-time explanation was shown and accepted


def load() -> dict:
    from .onboarding import load_state
    stored = load_state().get(KEY)
    merged = dict(DEFAULTS, folders=[])
    if isinstance(stored, dict):
        if stored.get('level') in LEVELS:
            merged['level'] = stored['level']
        for name in SWITCHES:
            if isinstance(stored.get(name), bool):
                merged[name] = stored[name]
        merged['folders'] = clean_folders(stored.get(FOLDERS_KEY))
    return merged


def clean_folders(value) -> list[str]:
    """Absolute folder paths, each once, at most ``MAX_FOLDERS``."""
    from pathlib import Path
    result = []
    for item in value if isinstance(value, (list, tuple)) else ():
        text = str(item or '').strip()
        if not text:
            continue
        try:
            path = Path(text)
        except (TypeError, ValueError):
            continue
        if path.is_absolute() and str(path) not in result:
            result.append(str(path))
    return result[:MAX_FOLDERS]


def save(values: dict) -> dict:
    from .onboarding import load_state, save_state
    merged = dict(load())
    if values.get('level') in LEVELS:
        merged['level'] = values['level']
    for name in SWITCHES:
        if isinstance(values.get(name), bool):
            merged[name] = values[name]
    if FOLDERS_KEY in values:
        merged['folders'] = clean_folders(values[FOLDERS_KEY])
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
    notes.append('能截图看 2ByteASR 的画面' if values.get('see_screen') else '不能截图看画面')
    folders = values.get('folders') or []
    if values.get('files_anywhere'):
        notes.append('已开启读写整台电脑文件（给完整路径，写入按当前操作权限）'
                     + (f'，另有 {len(folders)} 个授权文件夹' if folders else ''))
    else:
        notes.append(f'能看 {len(folders)} 个授权文件夹（在里面读文件、写新文件、改文件）' if folders else '没有授权文件夹')
    paid_direct = values['allow_paid'] and values['level'] == 'auto'
    notes.append('会计费的 AI 处理' + ('也可以直接跑' if paid_direct else '要小兔纸按「帮我做」'))
    return LEVEL_LABELS[values['level']] + '；' + '、'.join(notes)


def refusal(tool, values: dict) -> str:
    """Why this tool may not run under these permissions, or '' when it may."""
    if tool.name in SUBTITLE_READS and not values['read_subtitles']:
        return '小兔纸在「兔白权限」里关掉了“让兔白读字幕原文”'
    if tool.name in DIAGNOSTIC_READS and not values['read_diagnostics']:
        return '小兔纸在「兔白权限」里关掉了“让兔白读诊断和识别记录”'
    if tool.name in MEMORY_TOOLS | MEMORY_READS and not values['remember']:
        return '小兔纸在「兔白权限」里关掉了“让兔白记住我的习惯”'
    if tool.name in SCREEN_TOOLS and not values.get('see_screen'):
        return '小兔纸还没在「兔白权限」里打开“让兔白截图看 2ByteASR 的画面”'
    if tool.name in FILE_TOOLS and not values.get('folders') and not values.get('files_anywhere'):
        return '小兔纸还没在「兔白权限」里加“兔白可以看的文件夹”'
    if values['level'] == 'guide' and (tool.acts or tool.edit or tool.paid or tool.name in MEMORY_TOOLS):
        return '小兔纸把兔白设成了「只指路」，兔白只讲不动手'
    return ''


def needs_confirmation(tool, values: dict) -> bool:
    if tool.paid:                                   # spends the user's own AI credit
        return not (values['level'] == 'auto' and values['allow_paid'])
    if tool.name in {'write_file', 'edit_file', 'export_subtitles', 'import_terms_file'}:
        return values['level'] != 'auto'
    if getattr(tool, 'persistent', False):          # persisted app extensions have their own confirmation
        return True
    return bool(tool.edit) and values['level'] != 'auto'


def screen_explained() -> bool:
    from .onboarding import load_state
    return bool(load_state().get(SCREEN_ACK_KEY))


def mark_screen_explained() -> None:
    from .onboarding import load_state, save_state
    save_state(dict(load_state(), **{SCREEN_ACK_KEY: True}))


__all__ = ['CHIP_LABELS', 'DEFAULTS', 'FILE_TOOLS', 'FOLDERS_KEY', 'KEY', 'LEVELS', 'LEVEL_LABELS', 'SCREEN_TOOLS',
           'SWITCHES', 'clean_folders', 'describe', 'load',
           'mark_screen_explained', 'needs_confirmation', 'refusal', 'save', 'screen_explained']
