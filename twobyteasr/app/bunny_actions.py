"""What 兔白 may do for the user, only after they press 「帮我做」 (2026-11-14).

User (2026-11-14): she should be as capable as MCP — able to operate the software for the user
and float over to where it happens. This is the first, deliberately small set: each action is a
visible, reversible interface change the user could make with one click themselves (switch a
page, pick a language in a dropdown). Nothing here starts a recognition, spends money, uploads,
deletes or changes a file. The AI can only name an action and a value listed here; the chat shows
「帮我做：…」 and runs it when the user presses it, with 兔白 floating to the control first.

No Qt at import time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

LANGUAGES = {'auto': '自动识别语言', 'zh': '简体中文', 'zh-Hant': '繁体中文', 'ja': '日语', 'en': '英语', 'ko': '韩语',
             'es': '西班牙语', 'de': '德语', 'fr': '法语', 'pt': '葡萄牙语', 'it': '意大利语', 'ru': '俄语'}
OUTPUTS = {'original': '只显示原文', 'bilingual': '原文 + 翻译（双语）', 'translation': '只显示翻译'}
PAGES = {'home': '首页', 'workshop': '模型工坊', 'terms': '术语库', 'history': '识别记录', 'studio': '字幕工作台'}


def _translation_targets() -> dict:
    try:
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, TARGETS
        return {value: str(TARGET_LABELS[value]) for value in TARGETS}
    except Exception:  # noqa: BLE001
        return {'zh-Hans': '简体中文', 'zh-Hant': '繁體中文', 'en': 'English', 'ja': '日本語', 'ko': '한국어'}


@dataclass(frozen=True)
class BunnyAction:
    key: str
    title: str                      # 「帮我做：{title}」 (with the chosen value's label)
    describe: str                   # for the AI
    choices: dict = field(default_factory=dict)
    target: Callable | None = None  # window -> the control she floats to, or None
    run: Callable | None = None     # (window, value) -> a short line about what changed


def _home(window):
    back = getattr(window, '_return_to_settings', None)
    if callable(back):
        back()


def _set_combo(window, attribute: str, value: str, label: str, field_name: str) -> str:
    _home(window)
    combo = getattr(window, attribute, None)
    if combo is None:
        raise RuntimeError('首页还没准备好')
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f'{field_name}里没有「{label}」')
    combo.setCurrentIndex(index)
    return f'好啦，**{field_name}** 改成「{label}」了。'


def _open_page(window, value: str) -> str:
    methods = {'home': '_return_to_settings', 'workshop': '_open_model_workshop', 'terms': '_manage_terms',
               'history': '_open_recognition_history', 'studio': '_open_subtitle_studio'}
    method = getattr(window, methods[value], None)
    if not callable(method):
        raise RuntimeError('这个页面现在打不开')
    method()
    return f'到「{PAGES[value]}」啦。'


def _page_button(window, value: str):
    return getattr(window, {'workshop': 'model_workshop_button', 'studio': 'subtitle_studio_button',
                            'home': 'return_recognition_button'}.get(value, ''), None)


def _actions() -> dict:
    targets = _translation_targets()
    items = (
        BunnyAction('open_page', '打开{label}', '切换到软件里的一个页面', PAGES,
                    target=lambda window, value: _page_button(window, value), run=_open_page),
        BunnyAction('set_spoken_language', '把「视频里说的话」改成{label}', '首页「字幕语言与输出」：视频里说的是哪种话',
                    LANGUAGES, target=lambda window, value: getattr(window, 'recognition_language', None),
                    run=lambda window, value: _set_combo(window, 'recognition_language', value, LANGUAGES[value], '视频里说的话')),
        BunnyAction('set_subtitle_output', '把「字幕显示」改成{label}', '首页「字幕显示」：只要原文、双语还是只要翻译（翻译要先设置文字 AI）',
                    OUTPUTS, target=lambda window, value: getattr(window, 'subtitle_output', None),
                    run=lambda window, value: _set_combo(window, 'subtitle_output', value, OUTPUTS[value], '字幕显示')),
        BunnyAction('set_translation_target', '把「翻译成」改成{label}', '首页「翻译成」：翻译的目标语言',
                    targets, target=lambda window, value: getattr(window, 'translation_script', None),
                    run=lambda window, value: _set_combo(window, 'translation_script', value, targets[value], '翻译成')),
    )
    return {action.key: action for action in items}


ACTIONS = _actions()


def valid(do) -> tuple[str, str] | None:
    """(action, value) when ``do`` (the AI's ``"do"`` field) names a known action and choice."""
    if not isinstance(do, dict):
        return None
    action = ACTIONS.get(str(do.get('action') or '').strip())
    value = str(do.get('value') or '').strip()
    if action is None or (action.choices and value not in action.choices):
        return None
    return action.key, value


def button_text(key: str, value: str) -> str:
    action = ACTIONS[key]
    return action.title.format(label=action.choices.get(value, value))


def describe_for_prompt() -> str:
    rows = []
    for action in ACTIONS.values():
        choices = '、'.join(f'{value}={label}' for value, label in action.choices.items())
        rows.append(f'- {action.key}：{action.describe}。value 可填：{choices}')
    return '\n'.join(rows)


__all__ = ['ACTIONS', 'BunnyAction', 'button_text', 'describe_for_prompt', 'valid']
