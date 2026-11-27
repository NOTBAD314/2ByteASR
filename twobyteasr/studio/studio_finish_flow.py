"""Live Studio bridge for FinishChecklistPanel (left tab), MicroUpgradePill,
and Speaker Manager cast memory (2026-11-25).

Connects UI actions directly to real undoable Studio commands:
  - Term fix -> ``BatchReplaceTextCommand`` (Ctrl+Z undoable) + glossary commit
  - Review jump -> ``page.select_cue(cue_id)`` + seek playhead
  - Save to plan -> ``SeriesStore.settle(...)``
  - Manual edit observer -> ``MicroUpgradeTracker`` -> ``page.micro_upgrade_pill``
"""
from __future__ import annotations

from typing import Any

from ..app.micro_upgrade import MicroUpgradeOffer, MicroUpgradeTracker
from ..projects.mission_plan import (
    MissionItem,
    MissionPlan,
    attach_to_project,
    build_mission_plan,
    load_from_project,
)
from ..projects.series_store import SeriesStore


def ensure_tracker(page: Any) -> MicroUpgradeTracker:
    tracker = getattr(page, "_micro_upgrade_tracker", None)
    if tracker is None:
        tracker = MicroUpgradeTracker()
        page._micro_upgrade_tracker = tracker
    return tracker


def _active_series(page: Any) -> tuple[SeriesStore, str, str]:
    store = SeriesStore()
    project = getattr(page, "project", None)
    state = getattr(project, "studio_state", None) if project is not None else None
    binding = state.get("series_binding") if isinstance(state, dict) else None
    sid = str(binding.get("series_id") or "") if isinstance(binding, dict) else ""
    rec = store.get(sid) if sid else None
    if rec is None:
        last_id = store.last_selected_id()
        rec = store.get(last_id) if last_id else None
    return (store, rec.id, rec.name) if rec is not None else (store, "", "")


def _project_review_issues(page: Any, limit: int = 30) -> list[dict[str, Any]]:
    project = getattr(page, "project", None)
    if project is None:
        return []
    try:
        from ..subtitle_rules.current_issues import published_issue_view
        view = published_issue_view(project)
    except Exception:  # noqa: BLE001
        return []
    if view is None:
        return []
    cue_by_id = {c.id: c for c in getattr(project, "cues", ())}
    out: list[dict[str, Any]] = []
    for rec in getattr(view, "records", ()):
        if getattr(rec, "disposition", "") != "actionable":
            continue
        if getattr(rec, "level", "") not in {"high", "suggested"}:
            continue
        cid = str(getattr(rec, "cue_id", "") or "")
        cue = cue_by_id.get(cid)
        title = str(getattr(cue, "text", "") or getattr(rec, "summary", "") or cid)[:48]
        reason = str(getattr(rec, "reason", "") or getattr(rec, "category", "") or "建议听一下确认")
        out.append({"cue_id": cid, "title": title, "reason": reason, "kind": str(getattr(rec, "category", "issue"))})
        if len(out) >= limit:
            break
    return out


def _update_tab_chrome(page: Any, plan: MissionPlan | None) -> None:
    tabs = getattr(page, "source_tabs", None)
    panel = getattr(page, "finish_checklist_panel", None)
    if tabs is None or panel is None:
        return
    idx = tabs.indexOf(panel)
    if idx < 0:
        return
    label = plan.tab_badge_label() if plan is not None else "专名与方案"
    tabs.setTabText(idx, label)
    pending = plan.total_pending() if plan is not None else 0
    desired = "true" if pending > 0 else "false"
    if tabs.property("finishPending") != desired:
        tabs.setProperty("finishPending", desired)
        try:
            tabs.style().unpolish(tabs)
            tabs.style().polish(tabs)
            tabs.tabBar().style().unpolish(tabs.tabBar())
            tabs.tabBar().style().polish(tabs.tabBar())
        except Exception:  # noqa: BLE001
            pass
    try:
        from PySide6.QtGui import QColor
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        t = theme_definition(theme_key())
        tabs.tabBar().setTabTextColor(idx, QColor(t.accent_text if pending > 0 else t.text_secondary))
    except Exception:  # noqa: BLE001
        pass


def _scheme_counts(rec: Any) -> dict[str, int]:
    """What the scheme card's three stamps count (2026-11-26, draft B): term libraries, cast, style."""
    if rec is None:
        return {"glossary": 0, "cast": 0, "style": 0}
    visual = getattr(rec, "visual", None) or {}
    has_style = bool(visual.get("subtitle_style_preset") or visual.get("style_overrides") or visual.get("preset")) if isinstance(visual, dict) else False
    return {
        "glossary": len(getattr(rec, "glossary_ids", ()) or ()),
        "cast": len(getattr(rec, "cast", ()) or ()),
        "style": 1 if has_style else 0,
    }


def run_scheme_now(page: Any) -> str:
    """「现在套用到本片」 on the scheme card: run the scheme's lit parts on this episode once."""
    from ..projects.auto_pipeline import AutoPipelineConfig, run_auto_pipeline

    store, series_id, _name = _active_series(page)
    project = getattr(page, "project", None)
    rec = store.get(series_id) if series_id else None
    if project is None or rec is None:
        return ""
    cfg = AutoPipelineConfig.from_dict(rec.pipeline)
    receipt = run_auto_pipeline(project, rec, config=cfg, store=store)
    changed = getattr(page, "_speaker_structure_changed", None) or getattr(page, "_changed", None)
    if callable(changed):
        changed()
    refresh_finish_checklist(page)
    return receipt.one_line_summary()


def refresh_finish_checklist(page: Any) -> MissionPlan | None:
    """Rebuild ``收尾清单`` from live project learned pairs, review issues, and series delta."""
    panel = getattr(page, "finish_checklist_panel", None)
    project = getattr(page, "project", None)
    if panel is None or project is None:
        _update_tab_chrome(page, None)
        return None

    try:
        from ..app.bunny_subtitle_tools import learned_pairs
        pairs = [r for r in learned_pairs(page, limit=12) if int(r.get("left", 0)) > 0]
    except Exception:  # noqa: BLE001
        pairs = []

    issues = _project_review_issues(page)
    store, series_id, series_name = _active_series(page)
    save_items: list[dict[str, Any]] = []
    if series_id:
        speakers = [
            {"name": str(getattr(sp, "name", "") or ""), "color": str(getattr(sp, "color", "") or "")}
            for sp in getattr(project, "speakers", ())
        ]
        save_items = store.compute_delta(
            series_id,
            speakers=speakers,
            pending_terms=[{"from": r["source"], "to": r["target"]} for r in pairs],
        )

    from ..projects.auto_pipeline import AutoPipelineConfig
    rec = store.get(series_id) if series_id else None
    pipe_cfg = AutoPipelineConfig.from_dict(rec.pipeline) if rec is not None else AutoPipelineConfig()
    prev = load_from_project(project)
    plan = build_mission_plan(
        term_candidates=pairs,
        review_issues=issues,
        series_id=series_id,
        series_name=series_name,
        series_delta_count=len(save_items),
        previous_state=prev.to_state_dict() if prev is not None else None,
    )
    attach_to_project(project, plan)
    panel.set_plan(plan, save_items=save_items, pipeline_config=pipe_cfg, scheme_counts=_scheme_counts(rec))
    _update_tab_chrome(page, plan)
    return plan


def replace_all_and_add_term(page: Any, source: str, target: str) -> int:
    """Undoably replace all occurrences of ``source`` -> ``target`` and save into active glossary."""
    project = getattr(page, "project", None)
    if project is None or not source or not target or source == target:
        return 0

    values: dict[str, str] = {}
    hits = 0
    for cue in getattr(project, "cues", ()):
        if source in (cue.text or ""):
            new_text = cue.text.replace(source, target)
            if new_text.strip():
                values[cue.id] = new_text
                hits += cue.text.count(source)

    if values:
        from ..timeline.studio_commands import BatchReplaceTextCommand, MutationOrigin
        undo_stack = getattr(page, "undo_stack", None)
        changed_cb = getattr(page, "_changed", None) or (lambda: None)
        cmd = BatchReplaceTextCommand(
            project, values, needle=source, changed=changed_cb, origin=MutationOrigin.USER_EDIT
        )
        if undo_stack is not None:
            undo_stack.push(cmd)
        else:
            cmd.redo()

    # Best-effort add to user's active glossary (never blocks or breaks replacement)
    try:
        from ..glossary.quick_term_capture import QuickTermCandidate, commit_candidates
        window = page.window() if hasattr(page, "window") else None
        legacy = getattr(window, "legacy", None)
        if legacy is not None:
            enabled = getattr(window, "_enabled_glossary_ids", lambda: ())()
            lib = enabled[0] if enabled else "通用词库"
            commit_candidates(legacy, lib, [QuickTermCandidate(source=source, target=target, category="本片纠错")])
    except Exception:  # noqa: BLE001
        pass

    try:
        from ..app import newbie_tasks
        newbie_tasks.mark("add_term")
    except Exception:  # noqa: BLE001
        pass
    return hits


def handle_checklist_action(page: Any, action_kind: str, item: MissionItem) -> None:
    project = getattr(page, "project", None)
    if project is None:
        return
    plan = load_from_project(project)
    if action_kind == "skip":
        if plan is not None:
            plan.mark_item_done(item.id, True)
            attach_to_project(project, plan)
            refresh_finish_checklist(page)
        return

    if item.station == "terms":
        src = str(item.payload.get("from") or "")
        dst = str(item.payload.get("to") or "")
        replace_all_and_add_term(page, src, dst)
        if plan is not None:
            plan.mark_item_done(item.id, True)
            attach_to_project(project, plan)
        refresh_finish_checklist(page)
    elif item.station == "review":
        cid = item.cue_ids[0] if item.cue_ids else ""
        if cid and hasattr(page, "select_cue"):
            page.select_cue(cid)
            cue = next((c for c in project.cues if c.id == cid), None)
            if cue is not None and hasattr(page, "_seek"):
                page._seek(cue.start_ms / 1000.0)


def _project_title(project: Any) -> str:
    if project is None:
        return "我的常用方案"
    for candidate in (
        getattr(project, "name", ""),
        getattr(getattr(project, "media", None), "display_name", ""),
    ):
        clean = str(candidate or "").strip()
        if clean:
            return clean[:24]
    return "我的常用方案"


def handle_save_to_plan(page: Any, selected_items: list[dict[str, Any]]) -> None:
    store, series_id, _name = _active_series(page)
    project = getattr(page, "project", None)
    if not series_id:
        base_name = _project_title(project)
        rec = store.find_by_name(base_name) or store.create(base_name)
        series_id = rec.id
    store.settle(series_id, selected_items, episode_label=_project_title(project))
    refresh_finish_checklist(page)


def on_manual_text_edited(page: Any, old_text: str, new_text: str) -> MicroUpgradeOffer | None:
    """Called after a manual Studio text edit; checks local friction detectors & shows pill."""
    pill = getattr(page, "micro_upgrade_pill", None)
    if pill is None:
        return None
    tracker = ensure_tracker(page)

    offer = tracker.note_text_diff(old_text, new_text)
    if offer is None:
        try:
            from ..app.bunny_subtitle_tools import learned_pairs
            pairs = learned_pairs(page, limit=6)
            offer = tracker.check_repeated_typo(pairs)
        except Exception:  # noqa: BLE001
            offer = None

    if offer is not None:
        pill.show_offer(offer)
    refresh_finish_checklist(page)
    return offer


def handle_micro_upgrade_action(page: Any, offer: MicroUpgradeOffer) -> None:
    tracker = ensure_tracker(page)
    tracker.record_accepted(offer.kind)
    if offer.kind == "repeated_typo":
        replace_all_and_add_term(
            page,
            str(offer.payload.get("source") or ""),
            str(offer.payload.get("target") or ""),
        )
        refresh_finish_checklist(page)
    elif offer.kind == "manual_review":
        if hasattr(page, "_toggle_review_mode"):
            page._toggle_review_mode(True)


_IGNORED_SPEAKER_IDS = frozenset({"GAME_BACKGROUND", "SUBTITLES"})


def is_anonymous_speaker_name(name: str, speaker_id: str = "") -> bool:
    """Return True when ``name`` looks like an unnamed machine label (S00 / SPEAKER_01 / 说话人 1)."""
    clean = str(name or "").strip()
    if not clean:
        return True
    if speaker_id and clean == speaker_id and clean.upper().startswith(("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "SPEAKER_", "R00", "API_", "LOCAL_")):
        return True
    up = clean.upper()
    if up.startswith(("SPEAKER_", "R00", "API_", "LOCAL_")):
        return True
    if len(up) >= 2 and up[0] == "S" and up[1:].isdigit():
        return True
    if clean.startswith("说话人") and clean[3:].strip().isdigit():
        return True
    return False


def remember_project_speakers(
    page: Any,
    *,
    store: SeriesStore | None = None,
    series_id: str = "",
) -> tuple[str, list[str]]:
    """Save named speakers (name, color, host role) from current project into a saved scheme."""
    project = getattr(page, "project", None)
    if project is None:
        return "", []
    if store is None:
        store, active_id, _active_name = _active_series(page)
        series_id = series_id or active_id
    rec = store.get(series_id) if series_id else None
    if rec is None:
        base_name = _project_title(project)
        rec = store.find_by_name(base_name) or store.create(base_name)
    store.set_last_selected(rec.id)

    items: list[dict[str, Any]] = []
    saved_names: list[str] = []
    known = {m.name.casefold(): m for m in rec.cast}
    for sp in getattr(project, "speakers", ()):
        if getattr(sp, "id", "") in _IGNORED_SPEAKER_IDS:
            continue
        name = str(getattr(sp, "name", "") or "").strip()
        if is_anonymous_speaker_name(name, str(getattr(sp, "id", "") or "")):
            continue
        color = str(getattr(sp, "color", "") or "").strip()
        role = "host" if getattr(sp, "is_host", False) else ""
        existing = known.get(name.casefold())
        if existing is None:
            items.append({
                "kind": "cast_add",
                "checked": True,
                "payload": {"name": name, "color": color, "role": role},
            })
            saved_names.append(name)
        elif color and color != existing.color:
            items.append({
                "kind": "cast_update",
                "checked": True,
                "payload": {"cast_id": existing.cast_id, "color": color},
            })
            saved_names.append(name)
        else:
            saved_names.append(name)

    if items:
        store.settle(rec.id, items, episode_label=_project_title(project))
    state = getattr(project, "studio_state", None)
    if isinstance(state, dict):
        state["series_binding"] = {"series_id": rec.id, "series_name": rec.name}
    refresh_finish_checklist(page)
    return rec.name, saved_names


def apply_series_cast_to_project(
    page: Any,
    series_id: str,
    *,
    selected_ids: tuple[str, ...] | list[str] = (),
    store: SeriesStore | None = None,
) -> tuple[list[tuple[str, str]], str]:
    """Undoably apply saved speaker names & colors onto anonymous (or selected) speakers."""
    import copy as _copy

    project = getattr(page, "project", None)
    if project is None:
        return [], "当前没有打开工程"
    store = store or SeriesStore()
    rec = store.get(series_id)
    if rec is None or not rec.cast:
        return [], "这个常用方案里还没有记住说话人"

    cue_counts: dict[str, int] = {}
    for cue in getattr(project, "cues", ()):
        cue_counts[cue.speaker_id] = cue_counts.get(cue.speaker_id, 0) + 1

    selected_set = {str(s) for s in selected_ids if str(s) and str(s) not in _IGNORED_SPEAKER_IDS}
    present = [sp for sp in getattr(project, "speakers", ()) if sp.id not in _IGNORED_SPEAKER_IDS]
    already_used_names = {
        str(sp.name or "").strip().casefold()
        for sp in present
        if not is_anonymous_speaker_name(str(sp.name or ""), sp.id) and sp.id not in selected_set
    }
    available_cast = [m for m in rec.cast if m.name.casefold() not in already_used_names]
    if not available_cast:
        return [], f"「{rec.name}」记住的说话人名字已经全部在工程里了"

    if selected_set:
        targets = [sp for sp in present if sp.id in selected_set]
    else:
        targets = [sp for sp in present if is_anonymous_speaker_name(str(sp.name or ""), sp.id)]
    targets.sort(key=lambda sp: cue_counts.get(sp.id, 0), reverse=True)
    if not targets:
        return [], "当前所有说话人都已命名；若想替换名字，请先选中要改的说话人再点套用"

    speakers_copy = _copy.deepcopy(project.speakers)
    by_id = {sp.id: sp for sp in speakers_copy}
    applied: list[tuple[str, str]] = []
    for sp, member in zip(targets, available_cast):
        target_sp = by_id.get(sp.id)
        if target_sp is None:
            continue
        target_sp.name = member.name
        if member.color:
            target_sp.color = member.color
        applied.append((sp.id, member.name))

    if not applied:
        return [], "没有可套用的说话人"

    from ..timeline.studio_commands import SpeakerStateCommand
    changed_cb = getattr(page, "_speaker_structure_changed", None) or getattr(page, "_changed", None) or (lambda: None)
    cmd = SpeakerStateCommand(project, speakers_copy, project.cues, "套用常用说话人", changed_cb)
    undo_stack = getattr(page, "undo_stack", None)
    if undo_stack is not None:
        undo_stack.push(cmd)
    else:
        cmd.redo()

    state = getattr(project, "studio_state", None)
    if isinstance(state, dict):
        state["series_binding"] = {"series_id": rec.id, "series_name": rec.name}
    store.set_last_selected(rec.id)
    refresh_finish_checklist(page)
    names_str = "、".join(name for _, name in applied[:4]) + ("…" if len(applied) > 4 else "")
    return applied, f"已从「{rec.name}」套用 {len(applied)} 位说话人（{names_str}），可按 Ctrl+Z 撤销。"


def handle_pipeline_quick_toggle(page: Any, cfg: Any) -> None:
    """Persist inline 3-switch auto-pipeline changes directly to the active scheme."""
    store, series_id, _name = _active_series(page)
    project = getattr(page, "project", None)
    rec = store.get(series_id) if series_id else None
    if rec is None:
        base_name = _project_title(project)
        rec = store.find_by_name(base_name) or store.create(base_name)
    rec.pipeline = cfg.to_dict()
    store.save(rec)
    store.set_last_selected(rec.id)
    state = getattr(project, "studio_state", None) if project is not None else None
    if isinstance(state, dict):
        state["series_binding"] = {"series_id": rec.id, "series_name": rec.name}
    refresh_finish_checklist(page)


def open_auto_pipeline_dialog(page: Any) -> None:
    """Open the 3-switch auto-pipeline dialog bound to the active scheme & project."""
    from ..projects.auto_pipeline import AutoPipelineConfig, run_auto_pipeline
    from .auto_pipeline_ui import AutoPipelineDialog

    store, series_id, series_name = _active_series(page)
    project = getattr(page, "project", None)
    rec = store.get(series_id) if series_id else None
    if rec is None:
        base_name = _project_title(project)
        rec = store.find_by_name(base_name) or store.create(base_name)
        series_id, series_name = rec.id, rec.name

    def _save_cfg(cfg: AutoPipelineConfig) -> str:
        latest = store.get(series_id)
        if latest is None:
            return "常用方案不存在"
        latest.pipeline = cfg.to_dict()
        store.save(latest)
        store.set_last_selected(latest.id)
        refresh_finish_checklist(page)
        return f"✓ 已保存到「{latest.name}」"

    def _run_now(cfg: AutoPipelineConfig) -> str:
        if project is None:
            return "请先打开一个工程"
        latest = store.get(series_id)
        if latest is None:
            return "常用方案不存在"
        latest.pipeline = cfg.to_dict()
        store.save(latest)
        store.set_last_selected(latest.id)
        receipt = run_auto_pipeline(project, latest, config=cfg, store=store)
        changed = getattr(page, "_speaker_structure_changed", None) or getattr(page, "_changed", None)
        if callable(changed):
            changed()
        refresh_finish_checklist(page)
        return f"✓ 已完成：{receipt.one_line_summary()}"

    dlg = AutoPipelineDialog(
        scheme_name=series_name or rec.name,
        config=AutoPipelineConfig.from_dict(rec.pipeline),
        on_save=_save_cfg,
        on_run_now=_run_now if project is not None else None,
        parent=page if hasattr(page, "window") else None,
    )
    dlg.exec()


def install_studio_finish_wiring(page: Any) -> None:
    """Connect ``FinishChecklistPanel`` & ``MicroUpgradePill`` signals cleanly once."""
    panel = getattr(page, "finish_checklist_panel", None)
    tabs = getattr(page, "source_tabs", None)
    if panel is not None:
        panel.item_action_requested.connect(lambda kind, it: handle_checklist_action(page, kind, it))
        panel.save_to_plan_requested.connect(lambda rows: handle_save_to_plan(page, rows))

        def _jump_to_subtitle_review() -> None:
            if tabs is not None:
                tabs.setCurrentIndex(0)
            if hasattr(page, "_set_review_mode"):
                page._set_review_mode(True)
            elif hasattr(page, "_toggle_review_mode"):
                page._toggle_review_mode(True)

        panel.open_review_requested.connect(_jump_to_subtitle_review)
        panel.open_proofread_requested.connect(
            lambda: page.glossary_proofread_requested.emit() if hasattr(page, "glossary_proofread_requested") else None
        )
        panel.open_pipeline_config_requested.connect(lambda: open_auto_pipeline_dialog(page))
        panel.pipeline_config_changed.connect(lambda cfg: handle_pipeline_quick_toggle(page, cfg))
        panel.apply_now_requested.connect(lambda: run_scheme_now(page))
    if tabs is not None and panel is not None:
        tabs.currentChanged.connect(
            lambda idx: refresh_finish_checklist(page) if tabs.widget(idx) is panel else None
        )
    pill = getattr(page, "micro_upgrade_pill", None)
    if pill is not None:
        pill.action_clicked.connect(lambda offer: handle_micro_upgrade_action(page, offer))
        pill.dismissed.connect(lambda kind: ensure_tracker(page).record_dismissed(kind))


__all__ = [
    "apply_series_cast_to_project",
    "ensure_tracker",
    "handle_checklist_action",
    "handle_micro_upgrade_action",
    "handle_pipeline_quick_toggle",
    "handle_save_to_plan",
    "install_studio_finish_wiring",
    "run_scheme_now",
    "is_anonymous_speaker_name",
    "on_manual_text_edited",
    "open_auto_pipeline_dialog",
    "refresh_finish_checklist",
    "remember_project_speakers",
    "replace_all_and_add_term",
]
