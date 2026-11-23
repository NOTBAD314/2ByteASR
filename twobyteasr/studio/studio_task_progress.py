"""Input-owned task state. Only committed outcomes count as successful work."""

from __future__ import annotations

import time
import uuid
import weakref
from dataclasses import dataclass, field

TERMINAL = {"applied", "unchanged", "review", "failed", "cancelled", "suggestion"}
STATUS_TEXT = {"pending": "等待处理", "running": "处理中", "validated": "等待写回",
               "applied": "已写回", "unchanged": "无需调整", "review": "本地降级，需检查",
               "failed": "失败，保留原文", "cancelled": "取消，未处理", "suggestion": "建议已就绪，待采用"}


@dataclass
class SubtitleTask:
    kind: str
    cue_ids: tuple[str, ...]
    unit_label: str = '条原字幕'
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None
    phase: str = "准备输入"
    rows: dict[str, dict] = field(default_factory=dict)
    cancelled: bool = False
    revision: int = 0
    _cue_id_set: set[str] = field(init=False, repr=False)
    _project_ref: object = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._cue_id_set = set(self.cue_ids)

    @property
    def project(self):
        return self._project_ref() if self._project_ref else None

    @project.setter
    def project(self, project):
        self._project_ref = weakref.ref(project) if project is not None else None

    def update(self, event):
        if self.ended is not None:
            return
        key = str(event.get("range_id") or "")
        if key:
            old = self.rows.get(key, {})
            # Retries can supersede provisional failures. A terminal write is immutable.
            if old.get("status") in {"applied", "unchanged", "suggestion"}:
                return
            self.rows[key] = {**old, **event}
        self.phase = str(event.get("phase") or self.phase)
        self.revision += 1

    def finish(self, *, cancelled=False):
        if self.ended is not None:
            return
        self.cancelled = cancelled
        for row in self.rows.values():
            if row.get("status") not in TERMINAL:
                row.update(status="cancelled" if cancelled else "failed",
                           error="取消后尚未写回" if cancelled else "结果尚未通过写回校验")
        represented = {key for row in self.rows.values() for key in row.get("cue_ids", ())}
        for key in set(self.cue_ids) - represented:
            self.rows[key] = dict(range_id=key, cue_ids=[key], status="cancelled" if cancelled else "failed",
                                  error="取消后尚未处理" if cancelled else "该范围没有返回终态")
        self.ended = time.monotonic()
        self.cancel_action = None
        self.phase = "已取消" if cancelled else "任务已结束"
        self.revision += 1

    @property
    def elapsed(self):
        return max(0., (self.ended or time.monotonic()) - self.started)

    def counts(self):
        # Original IDs are the denominator, independent of output count and retry windows.
        by_id = {}
        for row in self.rows.values():
            if row.get("status") in TERMINAL and (row.get('final', True) or self.ended is not None):
                for key in row.get("cue_ids", ()):
                    if key in self._cue_id_set:
                        by_id[key] = row["status"]
        counts = {status: sum(value == status for value in by_id.values()) for status in TERMINAL}
        counts["processed"] = sum(value != "cancelled" for value in by_id.values())
        if self.kind == 'AI 断句':
            saved = getattr(self, 'saved_output_ids', set())
            counts['validated'] = sum(len(row['cue_ids']) for row in self.rows.values()
                                      if row.get('candidate_verified'))
            counts['saved_verified'] = sum(len(row['cue_ids']) for row in self.rows.values()
                if row.get('status') == 'applied' and row.get('output_ids') and set(row['output_ids']) <= saved)
            counts['conflict'] = sum(len(row['cue_ids']) for row in self.rows.values()
                                    if row.get('category', '').startswith('stale_'))
        counts["total"] = len(self.cue_ids)
        return counts

    def headline(self, counts=None):
        counts = counts or self.counts()
        phase = self.phase
        if self.ended is not None and counts["failed"]:
            phase = "任务已结束，部分范围失败"
        elif self.ended is not None and counts['review']:
            phase = '任务已结束，含需检查范围'
        alignment = getattr(self, 'alignment_progress', None)
        if self.ended is not None and alignment:
            phase += f" · 窗口 {alignment['done']}/{alignment['total']} · 缓存 {alignment['cached']} · 局部重算 {alignment['local']}"
        return phase

    def summary(self):
        counts = self.counts()
        return (f"{self.kind} · {counts['processed']}/{counts['total']} {self.unit_label} · "
                f"{self.headline(counts)} · {self.elapsed:.0f} 秒")
