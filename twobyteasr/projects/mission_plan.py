"""Studio Finish Tab model (专名与方案): clean single-page panel in plain Chinese.

2026-11-25 v5 refinement:
  - Export stays on the top-right toolbar; disputed sentences stay in ``字幕列表``.
  - No redundant top status banner ("已为你准备就绪……"): applied actions reflect
    directly in the canvas, speaker list, and counts.
  - Left 3rd tab (``专名与方案``) stays ultra-clean on ONE scroll page:
      1. ``terms`` - 本片重复错词（替换并加入词库 / 跳过，可 Ctrl+Z 撤回）
      2. Optional 1-line link: ``待确认 N 处 → 字幕列表``
      3. ``plan``  - 常用方案（3 个 <=6 字自动开关 + 加入常用方案）

Persists additively inside ``project.studio_state['mission_plan']`` so
``.2byteproj`` schema_version 1 stays 100% compatible.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

MISSION_STATE_KEY = "mission_plan"
STATION_ORDER = ("terms", "plan")
STATION_TITLES = {
    "terms": "专名",
    "plan": "常用方案",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class MissionItem:
    id: str
    station: str
    title: str
    subtitle: str = ""
    count: int = 1
    cue_ids: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    done: bool = False


@dataclass
class MissionStation:
    key: str
    title: str
    items: list[MissionItem] = field(default_factory=list)
    note: str = ""
    skipped: bool = False

    @property
    def remaining(self) -> int:
        return sum(1 for item in self.items if not item.done)

    @property
    def completed(self) -> bool:
        if self.skipped:
            return True
        if self.key == "plan":
            return bool(self.items) and all(item.done for item in self.items)
        return self.remaining == 0


@dataclass
class MissionPlan:
    stations: list[MissionStation]
    series_id: str = ""
    series_name: str = ""
    review_issue_count: int = 0
    completion_fixed_count: int = 0
    active_station: str = "terms"
    collapsed: bool = False
    updated_at: str = field(default_factory=_utc_now)

    def station(self, key: str) -> MissionStation | None:
        return next((s for s in self.stations if s.key == key), None)

    def total_pending(self) -> int:
        """Count actionable repeated term fixes (badge count for left tab)."""
        st = self.station("terms")
        return 0 if (st is None or st.skipped) else st.remaining

    def tab_badge_label(self) -> str:
        n = self.total_pending()
        return f"专名与方案 {n}" if n > 0 else "专名与方案"

    def next_open_station(self) -> str:
        for key in STATION_ORDER:
            st = self.station(key)
            if st is not None and not st.completed:
                return key
        return "plan"

    def mark_item_done(self, item_id: str, done: bool = True) -> bool:
        for st in self.stations:
            for item in st.items:
                if item.id == item_id:
                    item.done = bool(done)
                    self.updated_at = _utc_now()
                    if st.completed and self.active_station == st.key:
                        self.active_station = self.next_open_station()
                    return True
        return False

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "version": 4,
            "series_id": self.series_id,
            "series_name": self.series_name,
            "review_issue_count": int(self.review_issue_count),
            "completion_fixed_count": int(self.completion_fixed_count),
            "active_station": self.active_station,
            "collapsed": bool(self.collapsed),
            "updated_at": self.updated_at,
            "stations": [
                {
                    "key": st.key,
                    "title": st.title,
                    "note": st.note,
                    "skipped": st.skipped,
                    "items": [asdict(it) for it in st.items],
                }
                for st in self.stations
            ],
        }

    @classmethod
    def from_state_dict(cls, data: dict[str, Any]) -> "MissionPlan | None":
        if not isinstance(data, dict) or not isinstance(data.get("stations"), list):
            return None
        stations: list[MissionStation] = []
        for row in data["stations"]:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "")
            if key == "finish":
                key = "plan"
            if key not in STATION_TITLES:
                continue
            items = [
                MissionItem(
                    id=str(it.get("id") or ""),
                    station=key,
                    title=str(it.get("title") or ""),
                    subtitle=str(it.get("subtitle") or ""),
                    count=max(1, int(it.get("count", 1) or 1)),
                    cue_ids=[str(c) for c in (it.get("cue_ids") or ())],
                    payload=copy.deepcopy(it.get("payload") or {}),
                    done=bool(it.get("done", False)),
                )
                for it in (row.get("items") or ())
                if isinstance(it, dict) and it.get("id")
            ]
            stations.append(MissionStation(
                key=key,
                title=STATION_TITLES[key],
                items=items,
                note=str(row.get("note") or ""),
                skipped=bool(row.get("skipped", False)),
            ))
        if not stations:
            return None
        active = str(data.get("active_station") or stations[0].key)
        if active not in STATION_TITLES:
            active = stations[0].key
        return cls(
            stations=stations,
            series_id=str(data.get("series_id") or ""),
            series_name=str(data.get("series_name") or ""),
            review_issue_count=max(0, int(data.get("review_issue_count", 0) or 0)),
            completion_fixed_count=max(0, int(data.get("completion_fixed_count", 0) or 0)),
            active_station=active,
            collapsed=bool(data.get("collapsed", False)),
            updated_at=str(data.get("updated_at") or _utc_now()),
        )


def build_mission_plan(
    *,
    term_candidates: Sequence[dict[str, Any]] = (),
    review_issues: Sequence[dict[str, Any]] = (),
    series_id: str = "",
    series_name: str = "",
    series_delta_count: int = 0,
    completion_fixed_count: int = 0,
    previous_state: dict[str, Any] | None = None,
) -> MissionPlan:
    """Build the clean single-page ``专名与方案`` model while preserving done items."""
    done_ids: set[str] = set()
    if isinstance(previous_state, dict):
        for st in previous_state.get("stations") or ():
            for it in (st.get("items") or ()) if isinstance(st, dict) else ():
                if isinstance(it, dict) and it.get("done") and it.get("id"):
                    done_ids.add(str(it["id"]))

    # 1. 专名（全片重复错词 -> 替换并加入词库）
    term_items: list[MissionItem] = []
    seen_term_keys: set[str] = set()
    for row in term_candidates:
        src = str(row.get("from") or row.get("source") or "").strip()
        dst = str(row.get("to") or row.get("target") or "").strip()
        if not dst:
            continue
        key = f"term:{src.casefold()}->{dst.casefold()}"
        if key in seen_term_keys:
            continue
        seen_term_keys.add(key)
        hits = max(1, int(row.get("count") or row.get("left") or 1))
        term_items.append(MissionItem(
            id=key,
            station="terms",
            title=f"{src} → {dst}" if src and src != dst else dst,
            subtitle=f"全片 {hits} 处",
            count=hits,
            cue_ids=[str(c) for c in (row.get("cue_ids") or ())],
            payload={"from": src, "to": dst, "category": str(row.get("category") or "其他")},
            done=key in done_ids,
        ))

    # 2. 常用方案（把本片新改动加入常用方案）
    plan_items: list[MissionItem] = []
    if series_id or series_delta_count > 0:
        plan_items.append(MissionItem(
            id="plan:save",
            station="plan",
            title=f"新增 {max(1, int(series_delta_count))} 项设置",
            subtitle=series_name,
            count=max(1, int(series_delta_count)),
            done="plan:save" in done_ids,
        ))

    stations = [
        MissionStation(key="terms", title=STATION_TITLES["terms"], items=term_items),
        MissionStation(key="plan", title=STATION_TITLES["plan"], items=plan_items),
    ]
    plan = MissionPlan(
        stations=stations,
        series_id=series_id,
        series_name=series_name,
        review_issue_count=len(list(review_issues)),
        completion_fixed_count=max(0, int(completion_fixed_count)),
    )
    plan.active_station = plan.next_open_station()
    return plan


def attach_to_project(project: Any, plan: MissionPlan) -> None:
    """Persist ``MissionPlan`` into ``project.studio_state`` without altering schema_version 1."""
    state = getattr(project, "studio_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(project, "studio_state", state)
    state[MISSION_STATE_KEY] = plan.to_state_dict()


def load_from_project(project: Any) -> MissionPlan | None:
    state = getattr(project, "studio_state", None)
    if not isinstance(state, dict):
        return None
    raw = state.get(MISSION_STATE_KEY)
    return MissionPlan.from_state_dict(raw) if isinstance(raw, dict) else None


__all__ = [
    "MISSION_STATE_KEY",
    "MissionItem",
    "MissionPlan",
    "MissionStation",
    "STATION_ORDER",
    "STATION_TITLES",
    "attach_to_project",
    "build_mission_plan",
    "load_from_project",
]
