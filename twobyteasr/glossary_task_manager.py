"""全局术语库更新任务管理器（VII 轮）。

任务有独立身份（task_id / 目标游戏 / 模式 / AI / 启动时间 / 阶段 / 批次），
不随"术语库页面当前选中的游戏"变化。串行队列（并发 = 1，绝不并行付费调用）；
同一游戏同一模式的 queued/running 任务去重；取消保留已完成批次的检查点，
可从检查点续跑；迟到回调以 task_id 代次校验，取消后的迟到结果直接丢弃。
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from PySide6.QtCore import QObject, QThread, Signal

from .glossary_skill import GlossarySearchError, run_term_search

STAGE_LABELS = {
    "检索来源": "检索来源",
    "提取候选": "提取候选",
    "去重/比较": "去重 / 比较",
    "目录检索": "检索官方目录",
    "资料抓取": "抓取目录页",
    "名称提取": "提取名称 / 比缺口",
    "分批整理": "分批整理术语",
    "社区用语": "检索社区用语",
    "模型整理": "模型整理术语",
    "汇总比对": "汇总 / 与现有词库比较",
    "恢复检查点": "恢复检查点",
}


@dataclass
class GlossaryTaskState:
    """一个更新任务的完整身份与进度（UI 任务栏直接读取）。"""

    task_id: str
    game: str
    mode: str                     # full = 完整建库 / incremental = 版本增量
    service_label: str
    model_label: str
    started_at: float
    game_id: str = ""
    status: str = "queued"        # queued / running / finished / failed / cancelled
    stage: str = ""
    stage_note: str = ""
    batch_done: int = 0
    batch_total: int = 0
    candidates: int = 0
    cancel_requested: bool = False
    started: bool = False                 # 是否真正开始执行（排队即取消的任务没有检查点）
    waiting_note: str = ""                # "模型请求已发出，等待返回"之类的等待锚点（业务事件清除）
    last_event_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    partial_candidates: list = field(default_factory=list)
    result: dict | None = None
    review_choices: dict[str, bool] = field(default_factory=dict)
    error: str = ""
    events: list = field(default_factory=list)
    event_sequence: int = 0
    event_path: str = ""
    error_code: str = ""

    @property
    def mode_label(self) -> str:
        return "完整建库" if self.mode == "full" else "版本增量更新"

    def elapsed_seconds(self) -> int:
        end = self.finished_at or time.time()
        return max(0, int(end - self.started_at))

    def idle_seconds(self) -> int:
        if self.status not in {"queued", "running"}:
            return 0
        return max(0, int(time.time() - self.last_event_at))

    def progress_line(self) -> str:
        if self.status == "queued":
            return "排队中（前置任务完成后自动开始）"
        if self.status == "finished":
            diffs = (self.result or {}).get("diffs", ()) or ()
            new = sum(1 for d in diffs if getattr(d, "change_type", "") == "new")
            alias = sum(1 for d in diffs if getattr(d, "change_type", "") == "alias_supplement")
            return f"完成：候选 {self.candidates} · 新增 {new} · 别名补充 {alias}"
        if self.status == 'partial':
            return f"部分完成：候选 {self.candidates} · {(self.result or {}).get('quality_status', '可继续补齐')}"
        if self.status == "cancelled":
            if not self.started:
                return "已取消排队（未开始执行）"
            return "已取消（已完成批次保留，可从检查点继续）"
        if self.status == "failed":
            return f"失败：{self.error[:60]}"
        if self.waiting_note:
            label = f"{self.waiting_note}（已等待 {self.idle_seconds()} 秒）"
            if self.candidates:
                label = f"已获得 {self.candidates} 个候选。{label}"
            if self.cancel_requested:
                label = f"正在取消…{label}"
            return label
        label = STAGE_LABELS.get(self.stage, self.stage or "准备中")
        note = f" {self.stage_note}" if self.stage_note else ""
        if self.batch_total:
            label = f"{label}（批次 {self.batch_done}/{self.batch_total}）"
        elif self.candidates:
            label = f"{label}（已得 {self.candidates} 候选）"
        if self.cancel_requested:
            label = f"正在取消…{label}"
        return label + note


class GlossaryTaskRunner(QThread):
    """执行单个任务（manager 串行调度）；重活全在 run() 里。"""

    progress = Signal(str, str, str, int, int, int)   # task_id, stage, note, batch_done, batch_total, candidates
    execution_event = Signal(str, object)
    candidates_snapshot = Signal(str, list)           # task_id, 实时候选快照（序列化 dict 列表）
    finished_ok = Signal(str, str, object)            # task_id, game, result
    failed = Signal(str, str, str, str)               # task_id, game, code, message

    def __init__(self, legacy, task: GlossaryTaskState, settings: Mapping[str, Any],
                 resume: Mapping[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.legacy = legacy
        self.task = task
        self.settings = dict(settings) if isinstance(settings, Mapping) else {}
        self.resume = resume
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):  # noqa: C901 - 线程体，保持直线可读
        task = self.task
        try:
            import json, threading
            from .glossary_build import build_task_checkpoint_path
            from .provider_diagnostics import redact_diagnostics
            task.event_path=str(build_task_checkpoint_path(task.task_id).with_suffix('.events.jsonl'))
            event_lock=threading.Lock()
            sequence=0
            def on_event(row):
                nonlocal sequence
                if self._cancelled:return
                with event_lock:
                    sequence+=1
                    row=redact_diagnostics(dict(row,task_id=task.task_id,seq=sequence))
                    from pathlib import Path
                    path=Path(task.event_path)
                    path.parent.mkdir(parents=True,exist_ok=True)
                    # At most 8 MiB per attempt journal; in-memory tail stays bounded.
                    if not path.exists() or path.stat().st_size < 8*1024*1024:
                        with path.open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                    self.execution_event.emit(task.task_id,row)
            if task.mode == "full":
                from .glossary_build import run_full_library_update, save_task_checkpoint, serialize_term

                def report(stage: str, note: str, counters: Mapping[str, int] | None = None):
                    counters = counters or {}
                    self.progress.emit(
                        task.task_id, stage, note,
                        int(counters.get("batch_done", 0) or 0),
                        int(counters.get("batch_total", 0) or 0),
                        int(counters.get("candidates", 0) or 0),
                    )

                def push_candidates(candidates):
                    self.candidates_snapshot.emit(
                        task.task_id, [serialize_term(term) for term in candidates]
                    )

                result = run_full_library_update(
                    self.legacy,
                    task.game,
                    dict(self.settings, models=dict(self.settings.get('models', {}), glossary_task_id=task.task_id)),
                    report=report,
                    cancel_check=lambda: self._cancelled,
                    resume=self.resume,
                    checkpoint_writer=lambda payload: save_task_checkpoint(task.task_id, payload),
                    on_candidates=push_candidates,
                    on_event=on_event,
                )
            else:
                def report(stage: str, note: str = ""):
                    self.progress.emit(task.task_id, stage, note, 0, 0, 0)

                result = run_term_search(
                    self.legacy,
                    task.game,
                    self.settings,
                    progress=report,
                    on_event=on_event,
                    cancel_check=lambda: self._cancelled,
                )
                result["mode"] = "incremental"
            if self._cancelled:
                self.failed.emit(task.task_id, task.game, "cancelled", "已取消（已完成批次保留在检查点）。")
                return
            result['task_id']=task.task_id
            self.finished_ok.emit(task.task_id, task.game, result)
        except GlossarySearchError as exc:
            self.failed.emit(task.task_id, task.game, exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001 - 线程必须上报可用错误
            self.failed.emit(task.task_id, task.game, "unexpected", " ".join(str(exc).split())[:240])


class GlossaryUpdateManager(QObject):
    """应用级单例：任务队列 + 生命周期信号。UI 任务栏 / 按钮语义都读它。"""

    task_added = Signal(str)                     # task_id
    task_removed = Signal(str)                   # task_id（终态任务被移出）
    task_progress = Signal(str)                  # task_id（读 state 拿最新字段）
    task_finished = Signal(str, str, object)     # task_id, game, result
    task_failed = Signal(str, str, str, str)     # task_id, game, code, message

    _instance: "GlossaryUpdateManager | None" = None

    def __init__(self, legacy, parent=None):
        super().__init__(parent)
        self.legacy = legacy
        self._tasks: dict[str, GlossaryTaskState] = {}
        self._queue: list[str] = []
        self._runner: GlossaryTaskRunner | None = None
        self._serial = itertools.count(1)
        self._settings_by_task: dict[str, dict] = {}
        self._resume_by_task: dict[str, str] = {}

    # ------------------------------------------------------------ 单例
    @classmethod
    def instance(cls, legacy=None) -> "GlossaryUpdateManager":
        if cls._instance is None:
            if legacy is None:
                raise RuntimeError("GlossaryUpdateManager 需要先带 legacy 初始化。")
            cls._instance = cls(legacy)
        return cls._instance

    @classmethod
    def reset(cls):
        """测试隔离用：丢弃单例（调用方负责先停掉 runner）。"""
        cls._instance = None

    # ------------------------------------------------------------ 提交 / 取消
    def submit(
        self,
        game_name: str,
        mode: str,
        settings: Mapping[str, Any],
        *,
        service_label: str = "",
        model_label: str = "",
        resume_task_id: str = "",
    ) -> tuple[str, bool]:
        """提交任务；相同词库身份的 queued/running 跨模式去重。"""
        game_name = str(game_name or "").strip()
        canonicalize = getattr(self.legacy, 'canonicalize_runtime_game_name', str)
        game_name = str(canonicalize(game_name))
        game_id = self._game_identity(game_name)
        mode = "full" if mode == "full" else "incremental"
        for task in self._tasks.values():
            if (task.game_id or self._game_identity(task.game)) == game_id and task.status in {"queued", "running"}:
                return task.task_id, False
        sequence = next(self._serial)
        task_id = f"gt{int(time.time() * 1000):x}-{sequence:03d}-{uuid.uuid4().hex[:6]}"
        state = GlossaryTaskState(
            task_id=task_id,
            game=game_name,
            mode=mode,
            service_label=str(service_label or ""),
            model_label=str(model_label or ""),
            started_at=time.time(),
            game_id=game_id,
        )
        self._tasks[task_id] = state
        self._settings_by_task[task_id] = dict(settings) if isinstance(settings, Mapping) else {}
        self._queue.append(task_id)
        if resume_task_id:
            self._resume_by_task[task_id] = str(resume_task_id)
            parent = self._tasks.get(str(resume_task_id))
            if parent and (parent.game_id or self._game_identity(parent.game)) == game_id:
                state.review_choices = parent.review_choices
            state.stage = "恢复检查点"
            state.stage_note = f"续接 {resume_task_id}"
        self.task_added.emit(task_id)
        self._pump()
        return task_id, True

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(str(task_id or ""))
        if task is None:
            return False
        task.cancel_requested = True
        if task.status == "queued":
            task.status = "cancelled"
            task.finished_at = time.time()
            self.task_failed.emit(task.task_id, task.game, "cancelled", "排队任务已取消。")
        elif self._runner is not None and self._runner.task.task_id == task.task_id:
            self._runner.cancel()
            self.task_progress.emit(task.task_id)
        return True

    def shutdown(self, wait_ms: int = 4000):
        for task_id in list(self._queue):
            task = self._tasks.get(task_id)
            if task is not None and task.status == "queued":
                task.status = "cancelled"
                task.finished_at = time.time()
        self._queue.clear()
        runner = self._runner
        if runner is not None and runner.isRunning():
            runner.cancel()
            runner.wait(wait_ms)

    # ------------------------------------------------------------ 查询
    def tasks(self) -> list[GlossaryTaskState]:
        return list(self._tasks.values())

    def get(self, task_id: str) -> GlossaryTaskState | None:
        return self._tasks.get(str(task_id or ""))

    def pending_for_game(self, game_name: str) -> GlossaryTaskState | None:
        """该游戏是否有 queued/running 任务（按钮语义用）。"""
        for task in self._tasks.values():
            if (task.game_id or self._game_identity(task.game)) == self._game_identity(game_name) and task.status in {"queued", "running"}:
                return task
        return None

    def _game_identity(self, name):
        canonicalize = getattr(self.legacy, 'canonicalize_runtime_game_name', str)
        identity = getattr(self.legacy, 'runtime_game_identity', lambda value:value.strip().casefold())
        return str(identity(canonicalize(str(name or ''))))

    def running_task(self) -> GlossaryTaskState | None:
        if self._runner is not None:
            return self._runner.task
        return None

    def resumable_tasks(self, game_name: str = "") -> list[GlossaryTaskState]:
        return [
            task
            for task in self._tasks.values()
            if task.mode == "full"
            and task.status in {"cancelled", "failed", "partial"}
            and task.started
            and (not game_name or task.game == game_name)
        ]

    def remove(self, task_id: str) -> bool:
        """把终态任务移出任务栏（不影响已入库结果与检查点文件）。"""
        task = self._tasks.get(str(task_id or ""))
        if task is None or task.status in {"queued", "running"}:
            return False
        self._tasks.pop(task.task_id, None)
        self._settings_by_task.pop(task.task_id, None)
        self._resume_by_task.pop(task.task_id, None)
        self.task_removed.emit(task.task_id)
        return True

    # ------------------------------------------------------------ 调度
    def _pump(self):
        if self._runner is not None:
            return
        while self._queue:
            task_id = self._queue.pop(0)
            task = self._tasks.get(task_id)
            if task is None or task.status != "queued":
                continue
            resume = None
            resume_task_id = self._resume_by_task.pop(task_id, "")
            if resume_task_id:
                from .glossary_build import load_task_checkpoint

                resume = load_task_checkpoint(resume_task_id)
            runner = GlossaryTaskRunner(
                self.legacy, task, self._settings_by_task.get(task_id, {}), resume, self
            )
            runner.progress.connect(self._on_progress)
            runner.execution_event.connect(self._on_event)
            runner.candidates_snapshot.connect(self._on_snapshot)
            runner.finished_ok.connect(self._on_finished_ok)
            runner.failed.connect(self._on_failed)
            runner.finished.connect(self._on_runner_done)
            self._runner = runner
            task.status = "running"
            task.started = True
            task.last_event_at = time.time()
            runner.start()
            self.task_progress.emit(task.task_id)
            return

    def _on_progress(self, task_id: str, stage: str, note: str,
                     batch_done: int, batch_total: int, candidates: int):
        task = self._tasks.get(task_id)
        if task is None or task.status != "running" or task.cancel_requested:
            return
        task.stage = stage
        if note.startswith("请求已发出"):
            # 等待锚点：等待秒数由 UI 计时刷新，不重置"距上次有效进展"
            task.waiting_note = note.split("：", 1)[-1] or "等待返回"
        else:
            task.waiting_note = ""
        task.stage_note = note
        task.batch_done = batch_done
        task.batch_total = batch_total
        if candidates:
            task.candidates = candidates
        self.task_progress.emit(task_id)

    def _on_event(self, task_id, row):
        task=self._tasks.get(task_id)
        if task is None or task.status != "running" or task.cancel_requested:return
        sequence=int(row.get("seq",0))
        if sequence <= task.event_sequence:return
        task.event_sequence=sequence
        task.events.append(row)
        del task.events[:-1500]
        if row.get("source") in {"provider","http"}:
            task.last_event_at=float(row.get("timestamp") or time.time())
            task.waiting_note="等待下一条服务端事件"
            task.stage_note=str(row.get("payload", ""))[:160]
        self.task_progress.emit(task_id)

    def _on_snapshot(self, task_id: str, snapshot: list):
        task = self._tasks.get(task_id)
        if task is None or task.status != "running":
            return
        task.partial_candidates = list(snapshot or [])
        task.candidates = len(task.partial_candidates)
        task.last_event_at = time.time()
        self.task_progress.emit(task_id)

    def _on_finished_ok(self, task_id: str, game: str, result):
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.status not in {"running"}:
            return  # 迟到回调防护：取消后到达的结果丢弃
        task.status = "partial" if (result or {}).get('partial') else "finished"
        outcome = (result or {}).get('outcome') or {}
        if outcome.get('status') in {'blocked', 'failed', 'no_verified_content'}:
            task.status = 'failed'
            task.error_code = outcome['status']
            task.error = outcome.get('message', '')
        task.finished_at = time.time()
        task.candidates = int((result or {}).get("candidate_count", 0) or 0)
        task.result = result
        result['review_choices'] = task.review_choices
        result['execution_events'] = task.events
        self.task_finished.emit(task_id, game, result)

    def _on_failed(self, task_id: str, game: str, code: str, message: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.status not in {"running"}:
            return  # 迟到回调防护
        task.status = "cancelled" if code == "cancelled" else "failed"
        task.finished_at = time.time()
        from .provider_diagnostics import redact_diagnostics
        task.error = redact_diagnostics(message)
        task.error_code = code
        self.task_failed.emit(task_id, game, code, message)

    def _on_runner_done(self):
        self._runner = None
        self._pump()
