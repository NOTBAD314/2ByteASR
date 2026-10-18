"""Stable tool page identities and migration of older tab layouts."""
from datetime import datetime

CONTEXT_TAB_IDS = ('ai', 'style', 'motion', 'video', 'highlight', 'media')
LEGACY_TAB_IDS = ('ai', 'checks', 'style', 'video', 'highlight', 'media')
# 0.8.0 added 动效 but still saved through the five-page id table: 动效 / 视频 /
# 剪辑助手 were written as the next page's id and 素材 could not be saved.
# Files carry no app version, so a file without ``context_tab_ids`` saved
# after 0.8.0 shipped is read through this map; older files are 0.7.x ids.
RELEASE_080_SAVED_IDS = {'video': 'motion', 'highlight': 'video', 'media': 'highlight'}
RELEASE_080_PUBLISHED = datetime.fromisoformat('2026-10-18T02:30:13+00:00')


def context_tab_layout(index):
    """Layout keys for the open tool page.

    ``context_tab`` keeps the numbering from before 检查 was removed for old
    readers (动效 had no page then, so it reads as 样式); ``context_tab_ids``
    marks ``context_tab_id`` as written with the six-page table.
    """
    tab_id = CONTEXT_TAB_IDS[index] if 0 <= index < len(CONTEXT_TAB_IDS) else 'style'
    legacy = LEGACY_TAB_IDS.index(tab_id if tab_id in LEGACY_TAB_IDS else 'style')
    return {'context_tab': legacy, 'context_tab_id': tab_id, 'context_tab_ids': list(CONTEXT_TAB_IDS)}


def _saved_by_080(saved_at):
    try:
        moment = datetime.fromisoformat(str(saved_at))
    except ValueError:
        return False
    return moment.tzinfo is not None and moment >= RELEASE_080_PUBLISHED


def restored_context_tab(layout, saved_at=''):
    value = layout.get('context_tab_id')
    if value is None:
        try:
            index = int(layout.get('context_tab', 2))
            value = LEGACY_TAB_IDS[index] if 0 <= index < len(LEGACY_TAB_IDS) else 'style'
        except (TypeError, ValueError):
            value = 'style'
    elif 'context_tab_ids' not in layout and _saved_by_080(saved_at):
        value = RELEASE_080_SAVED_IDS.get(value, value)
    return CONTEXT_TAB_IDS.index(value) if value in CONTEXT_TAB_IDS else CONTEXT_TAB_IDS.index('style')
