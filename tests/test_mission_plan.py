"""Tests for the slim single-page left-tab ``专名与方案`` model."""
from __future__ import annotations

from types import SimpleNamespace

from twobyteasr.projects.mission_plan import (
    STATION_ORDER,
    MissionPlan,
    attach_to_project,
    build_mission_plan,
    load_from_project,
)


def test_finish_tab_focuses_only_on_terms_and_saved_plan():
    assert STATION_ORDER == ("terms", "plan")
    plan = build_mission_plan(
        term_candidates=[{"from": "杰风", "to": "捷风", "count": 14}],
        review_issues=[{"cue_id": "c324", "title": "一百四十 vs 140", "kind": "text"}],
        series_id="ser_1",
        series_name="瓦罗兰特双排",
        series_delta_count=2,
    )

    # No redundant speakers / export / review stations or pipeline_summary banner
    assert not hasattr(plan, "pipeline_summary")
    assert plan.station("speakers") is None
    assert plan.station("review") is None
    assert plan.station("terms").remaining == 1
    assert plan.review_issue_count == 1
    assert plan.total_pending() == 1
    assert plan.tab_badge_label() == "专名与方案 1"

    assert plan.mark_item_done(plan.station("terms").items[0].id)
    assert plan.total_pending() == 0
    assert plan.tab_badge_label() == "专名与方案"
    assert plan.active_station == "plan"

    # Additive persistence inside studio_state (schema_version 1 untouched)
    fake_project = SimpleNamespace(schema_version=1, studio_state={})
    attach_to_project(fake_project, plan)
    restored = load_from_project(fake_project)
    assert restored is not None
    assert fake_project.schema_version == 1
    assert restored.station("terms").completed is True
    assert restored.review_issue_count == 1

    # Backward compatibility: legacy state containing pipeline_summary still loads cleanly
    legacy_payload = plan.to_state_dict()
    legacy_payload["pipeline_summary"] = "legacy banner text"
    from_legacy = MissionPlan.from_state_dict(legacy_payload)
    assert from_legacy is not None and not hasattr(from_legacy, "pipeline_summary")
