from types import SimpleNamespace

import subtitle_core
from twobyteasr.recognition import cache as cache_module
from twobyteasr.recognition.run_context import (
    RuntimeContext,
    activate_runtime_context,
    get_runtime_context,
)
from twobyteasr.recognition.service import RunOptions


def _legacy_namespace():
    return SimpleNamespace(
        canonicalize_runtime_game_name=lambda value: str(value).strip(),
        RUNTIME_GAME_NAME="",
        RUNTIME_ENABLE_DOMAIN_TERMS=False,
        RUNTIME_DISCOVERED_TERMS=set(),
        RUNTIME_OUTPUT_REVIEW_TRACK=False,
        RUNTIME_FORCE_REFRESH_API_CACHE=False,
        RUNTIME_FORCE_REFRESH_POLISH_CACHE=False,
        RUNTIME_FORCE_REFRESH_GROUP_CACHE=False,
        RUNTIME_EXPECTED_SPEAKERS=0,
        RUNTIME_CANCELLATION_TOKEN=None,
        RUN_EVENT_LOG_PATH="",
        RUN_REVIEW_ITEMS=[],
    )


def test_runtime_context_scope_mirrors_legacy_and_restores_previous_context():
    previous = get_runtime_context()
    legacy = _legacy_namespace()
    context = RuntimeContext(
        game_name="原神",
        enable_domain_terms=True,
        expected_speakers=3,
        output_review_track=True,
    )

    with activate_runtime_context(context, legacy=legacy):
        assert get_runtime_context() is context
        assert legacy.RUNTIME_GAME_NAME == "原神"
        assert legacy.RUNTIME_EXPECTED_SPEAKERS == 3
        assert legacy.RUN_REVIEW_ITEMS is context.review_items

    assert get_runtime_context() is previous
    assert legacy.RUNTIME_GAME_NAME == previous.game_name
    assert legacy.RUN_REVIEW_ITEMS is previous.review_items


def test_run_options_can_build_isolated_context_without_changing_active_one():
    previous = get_runtime_context()
    legacy = _legacy_namespace()
    options = RunOptions(
        content_name=" 原神 ",
        enable_domain_terms=True,
        force_refresh_group=True,
        expected_speakers=3,
    )

    context = options.apply(legacy)

    assert context is not previous
    assert get_runtime_context() is previous
    assert context.game_name == "原神"
    assert context.enable_domain_terms is True
    assert context.force_refresh_group_cache is True
    assert context.expected_speakers == 3


def test_cache_refresh_flags_come_from_active_context():
    context = RuntimeContext(
        force_refresh_polish_cache=True,
        force_refresh_group_cache=False,
    )
    with activate_runtime_context(context):
        assert cache_module.api_stage_force_refresh("polished") is True
        assert cache_module.api_stage_force_refresh("grouped") is False


def test_review_items_are_isolated_by_runtime_context():
    previous = get_runtime_context()
    previous_items = list(previous.review_items)
    context = RuntimeContext()
    try:
        with activate_runtime_context(context, legacy=subtitle_core):
            subtitle_core.add_review_item(1.0, "测试", "context isolated")
            assert len(context.review_items) == 1
            assert context.review_items[0]["category"] == "测试"
        assert previous.review_items == previous_items
    finally:
        previous.review_items[:] = previous_items
