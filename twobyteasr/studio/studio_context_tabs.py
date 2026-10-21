"""Stable tool page identities and migration of the former six-tab layout."""
CONTEXT_TAB_IDS = ('ai', 'style', 'video', 'highlight', 'media')
LEGACY_TAB_IDS = ('ai', 'checks', 'style', 'video', 'highlight', 'media')


def restored_context_tab(layout):
    value = layout.get('context_tab_id')
    if value is None:
        try:
            index = int(layout.get('context_tab', 2))
            value = LEGACY_TAB_IDS[index] if 0 <= index < len(LEGACY_TAB_IDS) else 'style'
        except (TypeError, ValueError):
            value = 'style'
    return CONTEXT_TAB_IDS.index(value) if value in CONTEXT_TAB_IDS else CONTEXT_TAB_IDS.index('style')
