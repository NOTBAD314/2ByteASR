"""Main / secondary speaker roles in the Studio timeline (2026-10-12).

``studio_state["speaker_roles"]`` (absent on older projects, which keep one
track per speaker until the user organizes them):

    {"policy": "speaker-roles-v1", "grouped": true, "expanded": false,
     "auto": {"S07": "secondary", ...},   # classification snapshot
     "manual": {"S03": "own"},            # user choices, always win
     "rule": "...", "media_ms": 1440000, "source": "recognition" | "organize"}

The automatic part is a snapshot taken when roles are decided (new
recognition, or the explicit "organize" action). Later edits, splits and
merges never re-run it, so a speaker cannot flip between the group and an own
track while the user works; "重新判断" runs it again on purpose. A speaker that
appears later (reassigned cues) has no snapshot entry and keeps an own track.

Roles only change the timeline display: cue ownership, speaker identity,
colour, style, visibility, exports and audio stay as they are.
"""
from __future__ import annotations

import copy

from PySide6.QtGui import QUndoCommand

from .i18n import tr
from .speaker_roles import (GROUP_KEY, KEY, decide, effective_roles, group_members,  # noqa: F401
                            initialize_for_recognition, media_ms_of, state_of)

ROLE_LABELS = {"main": "主要角色", "secondary": "次要角色", "own": "固定独立轨"}


class SetSpeakerRolesCommand(QUndoCommand):
    """One undoable change of the role state (organize, ungroup, manual role)."""

    def __init__(self, project, after: dict | None, label: str, changed=None):
        super().__init__(label)
        self.project = project
        self.before = copy.deepcopy(project.studio_state.get(KEY))
        self.after = copy.deepcopy(after)
        self.changed = changed

    def _apply(self, value):
        from .studio_commands import _commit_mutation
        from .studio_runtime_state import DirtyDomain

        def mutate():
            if value is None:
                self.project.studio_state.pop(KEY, None)
            else:
                self.project.studio_state[KEY] = copy.deepcopy(value)

        _commit_mutation(self.project, action_id=self.text(),
                         dirty=DirtyDomain.TIMELINE_INDEX | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE,
                         cue_ids=(), mutate=mutate, changed=self.changed, snapshot_cues=False)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def _push(page, after, label):
    page.undo_stack.push(SetSpeakerRolesCommand(page.project, after, tr(label)))
    page.timeline.reindex_project()


def organize(page, cap: int | None = None) -> None:
    """按主要/次要角色整理轨道: classify now, keep manual roles, collapse the group.

    ``cap``: a new limit of automatic main tracks (else the project's last)."""
    if page.project is None:
        return
    state = decide(page.project, expanded=False, cap=cap)
    _push(page, state, "按主要/次要角色整理轨道" if cap is None else "调整主要角色上限")
    members = group_members(page.project)
    message = tr("已整理：{main} 条独立轨，{secondary} 位次要角色收进一条轨道（可撤销）",
                 main=len(effective_roles(page.project)) - len(members), secondary=len(members))
    label = getattr(page, "save_state", None)
    if label is not None:
        from .i18n import bind_text
        bind_text(label, message)


def ungroup(page) -> None:
    """Every speaker on an own track again; manual roles are kept for later."""
    state = copy.deepcopy(state_of(page.project))
    if not state.get("grouped"):
        return
    state["grouped"] = False
    _push(page, state, "取消次要角色分组")


def set_role(page, speaker_id: str, role: str | None) -> None:
    """Manual role for one speaker (None: back to the automatic choice)."""
    state = copy.deepcopy(state_of(page.project)) or decide(page.project, manual={})
    manual = dict(state.get("manual") or {})
    if role is None:
        manual.pop(speaker_id, None)
    else:
        manual[speaker_id] = role
    state["manual"] = manual
    state["grouped"] = True
    label = "恢复自动判断角色" if role is None else {"main": "设为主要角色", "secondary": "移入次要角色组",
                                                  "own": "固定为独立轨"}[role]
    _push(page, state, label)


def set_expanded(page, expanded: bool) -> None:
    """Expand/collapse is a view choice: saved with the project, not an undo step."""
    page.timeline.set_group_expanded(expanded)


def role_menu(page, menu, speaker_id: str) -> None:
    """Role entries for one speaker track (track header or cue menu)."""
    roles = effective_roles(page.project)
    state = state_of(page.project)
    manual = (state.get("manual") or {}).get(speaker_id)
    current = roles.get(speaker_id, "main")
    sub = menu.addMenu(tr("角色分组（当前：{role}{how}）", role=tr(ROLE_LABELS.get(current, current)),
                          how=tr("，手动") if manual else ""))
    for role in ("main", "secondary", "own"):
        action = sub.addAction(tr({"main": "设为主要角色", "secondary": "移入次要角色组",
                                   "own": "固定为独立轨（不参与自动分组）"}[role]),
                               lambda value=role: set_role(page, speaker_id, value))
        action.setCheckable(True)
        action.setChecked(manual == role)
    if manual:
        sub.addAction(tr("恢复自动判断"), lambda: set_role(page, speaker_id, None))
    sub.addSeparator()
    sub.addAction(tr("选择该说话人的全部字幕"), lambda: page.timeline.select_speakers([speaker_id]))
    group_actions(page, sub)


def group_actions(page, menu) -> None:
    state = state_of(page.project)
    members = group_members(page.project)
    if members:
        expanded = bool(state.get("expanded"))
        menu.addAction(tr("收起次要角色") if expanded else tr("展开次要角色（{count} 位）", count=len(members)),
                       lambda: set_expanded(page, not expanded))
        menu.addAction(tr("选择次要角色组的全部字幕"), lambda: page.timeline.select_speakers(list(members)))
    menu.addAction(tr("按主要/次要角色整理轨道（可撤销）") if not state else tr("重新判断主要/次要角色（可撤销）"),
                   lambda: organize(page))
    from .speaker_roles import CAP_CHOICES, MAIN_CAP
    current_cap = int(state.get("cap") or MAIN_CAP) if state.get("policy") != "speaker-roles-v1" else None
    caps = menu.addMenu(tr("自动主要角色上限"))
    for value in CAP_CHOICES:
        action = caps.addAction(tr("最多 {count} 条（可撤销）", count=value),
                                lambda value=value: organize(page, cap=value))
        action.setCheckable(True)
        action.setChecked(value == current_cap)
    if state.get("grouped"):
        menu.addAction(tr("取消分组，全部显示为独立轨（可撤销）"), lambda: ungroup(page))
    rule = state.get("rule")
    if rule:
        info = menu.addAction(tr("规则：{rule}", rule=rule))
        info.setEnabled(False)
