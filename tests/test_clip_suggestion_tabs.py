from twobyteasr.studio.studio_context_tabs import (
    CONTEXT_TAB_IDS, context_tab_state, restored_context_tab,
)


def test_every_current_page_saves_and_restores_including_last_media_page():
    assert len(CONTEXT_TAB_IDS) == 6
    for index, name in enumerate(CONTEXT_TAB_IDS):
        saved = context_tab_state(index)
        assert saved['context_tab_id'] == name
        assert restored_context_tab(saved) == index
    assert context_tab_state(5) == {'context_tab_id': 'media', 'context_tab': 5}


def test_legacy_indices_are_not_shifted_by_added_motion_page():
    assert restored_context_tab({'context_tab': 4}) == 4  # clip assistant
    assert restored_context_tab({'context_tab_id': 'video'}) == 3
    for stale in (-1, 88, None, 'bad'):
        assert context_tab_state(stale)['context_tab_id'] == 'style'
