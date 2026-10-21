"""Turn one collected support range into the steps a person took.

Runs on the report worker after ``support_bundle.collect``; no Qt. Each event
that matters becomes an *issue*, deduplicated and given a severity, and is
attached to one *step* (an operation, a background task, an unattributed data
change or program start). The relation states only what the record proves:
the same operation_id, the same task_id, or merely that it happened during or
soon after the step. Order is never presented as cause.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import json

from ..i18n import join_text, tr

# Severity order: what a person should look at first.
KIND_ORDER = ("act", "check", "stall", "slow", "auto", "ignore")
KIND_TONE = {"act": "danger", "check": "warn", "stall": "warn", "slow": "warn", "auto": "info", "ignore": "muted"}
PROBLEM_KINDS = {"act", "check", "stall", "slow", "auto"}

ACTION_LABELS = {
    "cue.select": "选取字幕", "cue.multiselect": "多选字幕", "cue.deselect": "取消选取",
    "cue.edit": "修改字幕", "cue.add": "新增字幕", "cue.delete": "删除字幕",
    "cue.merge_pair": "合并字幕", "cue.merge": "合并字幕", "cue.split": "拆分字幕",
    "cue.trim": "修剪字幕", "trim_start": "修剪开头", "trim_end": "修剪结尾",
    "cue.drag_commit": "拖动字幕", "cue.ripple_qw": "Q／W 边界操作", "cue.offset": "平移字幕时间",
    "cue.speaker": "更改说话人", "cue.track": "更改字幕轨", "cue.translation": "修改译文",
    "cue.search": "搜索字幕", "cue.replace_next": "替换文字", "cue.replace_apply": "替换文字",
    "cue.replace_all": "全部替换", "cue.ai_apply": "应用 AI 结果",
    "project.open": "打开工程", "project.load": "读取工程", "project.recover": "恢复工程",
    "project.close": "关闭工程", "project.create": "新建工程", "project_deserialize": "读取工程",
    "project.save": "保存工程", "project.save_revision": "保存工程",
    "media.replace": "替换素材", "settings.open": "打开设置", "settings.ai_open": "打开 AI 设置",
    "studio.leave": "离开工作台", "player.toggle": "播放／暂停", "player.play_pause": "播放／暂停",
    "player.seek": "定位播放位置", "player.speed": "调整播放速度", "subtitle.export": "导出字幕",
    "subtitle.export_readback": "检查导出的字幕", "view.refresh": "刷新工作台",
}
_EDIT = {"cue.select", "cue.multiselect", "cue.deselect", "cue.edit", "cue.trim", "trim_start", "trim_end",
         "cue.drag_commit", "cue.ripple_qw", "cue.offset", "cue.speaker", "cue.track", "cue.translation",
         "cue.search", "cue.replace_next"}
_PLAY = {"player.toggle", "player.play_pause", "player.seek", "player.speed"}
_OPEN = {"project.open", "project.load", "project.recover", "project.close", "project_deserialize", "project.create"}
_SAVE = {"project.save", "project.save_revision"}
# State notifications recorded as operations; a person did not do these.
_NOT_STEPS = {"player.state", "duration", "speed"}
_MERGE_GAP = {"edit": 3.0, "play": 3.0, "open": 2.0, "save": 2.0}

COMMAND_LABELS = {
    "SpliceCuesCommand": "合并／拆分字幕", "SetCueFieldsCommand": "修改字幕",
    "EditCueIntervalsCommand": "调整字幕时间", "ApplyTranslationSnapshotCommand": "应用译文",
    "SetBilingualDisplayCommand": "切换双语显示",
}
PROCESS_NAMES = {
    "mpv studio preview": "播放预览", "Studio audio endpoint": "音频输出",
    "Studio follower video decoder": "视频解码", "Studio audio PCM decoder": "音频解码",
    "ffmpeg encoder probe": "硬件编码器探测", "diagnostic graphics inventory": "读取显卡信息",
}
# (stack function, what the program was doing): first match names a stall.
_STALL_CONTEXT = (
    ("_build_lazy_page", "第一次建立页面"), ("_construct_lazy_page", "第一次建立页面"),
    ("persist_with_progress", "保存工程"), ("_load_style_inspector", "载入样式面板"),
    ("_set_subtitle_editor_visible", "打开字幕编辑框"), ("settle_layout", "切换页面"),
    ("open_studio_project", "打开工程"),
)
_PROBE_PURPOSES = {"ffmpeg encoder probe", "diagnostic graphics inventory"}
_GENERIC_FRAMES = ("threading.py", "contextlib.py", "ntpath.py", "pathlib.py", "genericpath.py",
                   "studio_events.py", "theme_manager.py", "quick_start.py", "runpy.py")


def _ts(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def local_clock(stamp, *, millis=False):
    """Local wall clock of an epoch second; the record itself stays UTC."""
    if stamp is None:
        return "—"
    moment = datetime.fromtimestamp(stamp)
    return moment.strftime("%H:%M:%S") + (f".{moment.microsecond // 1000:03d}" if millis else "")


def seconds_text(value):
    """0.27 / 1.9 / 12 — short, without trailing noise."""
    value = abs(float(value))
    if 0 < value < 0.01:
        value = 0.01
    if value >= 10:
        return f"{value:.0f}"
    if value >= 1:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _exit_text(code):
    if isinstance(code, int) and (code > 0x7FFFFFFF or code < -255):
        return f"0x{code & 0xFFFFFFFF:08X}"
    return str(code)


def _label(action):
    return tr(ACTION_LABELS[action]) if action in ACTION_LABELS else action


def _family(action):
    if action in _EDIT:
        return "edit"
    if action in _PLAY:
        return "play"
    if action in _OPEN:
        return "open"
    if action in _SAVE:
        return "save"
    return action


def _chain_text(exception):
    chain = (exception or {}).get("chain") or []
    if not chain:
        return "", ""
    types = " ← ".join(str(c.get("type")) for c in chain)
    frames = [f for f in (chain[0].get("frames") or []) if isinstance(f, dict)]
    where = " → ".join(f"{str(f.get('module', '')).rsplit('/', 1)[-1]}:{f.get('line')} {f.get('function')}" for f in frames[-2:])
    return types, where


def _stall_location(row):
    """(file:line function, plain context) of the sampled main-thread stack."""
    stacks = sorted((s for s in row.get("stacks") or [] if isinstance(s, dict)),
                    key=lambda s: -(s.get("samples") or 0))
    context = None
    for stack in stacks:
        frames = [str(f) for f in stack.get("frames") or []]
        for _function, label in _STALL_CONTEXT:
            if any(f.endswith(":" + _function) for f in frames):
                context = label
                break
        for frame in frames:
            name = frame.split(":", 1)[0]
            function = frame.rsplit(":", 1)[-1]
            if name in _GENERIC_FRAMES or name.endswith("_audit.py") or function in {"eventFilter", "run_desktop_app", "<module>"}:
                continue
            parts = frame.split(":")
            return (f"{parts[0]}:{parts[1]} {parts[-1]}" if len(parts) >= 3 else frame), context
    return None, context


@dataclass(eq=False)
class Issue:
    kind: str
    title: object
    advice: object
    dev: str
    start: float
    end: float | None = None
    count: int = 1
    members: list = field(default_factory=list)
    operation_id: str | None = None
    task_id: str | None = None
    duration_ms: float | None = None
    lane: str = "problem"
    short: object = None
    relation: object = None
    step: object = None

    @property
    def tone(self):
        return KIND_TONE[self.kind]

    @property
    def rank(self):
        return KIND_ORDER.index(self.kind)


@dataclass(eq=False)
class Step:
    kind: str
    family: str
    start: float
    end: float
    actions: list = field(default_factory=list)
    operation_ids: set = field(default_factory=set)
    task_ids: set = field(default_factory=set)
    issues: list = field(default_factory=list)
    name: object = None
    detail: object = None
    open_until: float | None = None
    slow: bool = False
    id: str = ""

    @property
    def tone(self):
        kinds = {i.kind for i in self.issues}
        for kind in KIND_ORDER:
            if kind in kinds:
                return KIND_TONE[kind]
        return "ok"

    def counted(self, *kinds):
        return [i for i in self.issues if i.kind in kinds]


@dataclass
class Analysis:
    start: float | None
    end: float | None
    anchor: float | None
    anchor_is_mark: bool
    steps: list
    issues: list
    counts: dict
    start_step: Step | None
    running: list
    notes: list
    event_steps: list
    event_problem: list
    event_kind: list
    longest_stall_ms: float | None
    environment: dict

    def step(self, step_id):
        return next((s for s in self.steps if s.id == step_id), None)


def _relation_after(delay):
    return tr("之后 {seconds} 秒 · 时间接近", seconds=seconds_text(delay))


class _Builder:
    def __init__(self, data, report):
        self.rows = list(data.get("events") or [])
        self.data = data
        self.times = [_ts(r.get("time")) for r in self.rows]
        known = [t for t in self.times if t is not None]
        self.first = min(known) if known else None
        self.last = max(known) if known else None
        mark = _ts((report or {}).get("marked_at"))
        if mark is None:
            marked = [t for r, t in zip(self.rows, self.times) if r.get("event_name") == "problem.marked" and t]
            mark = marked[-1] if marked else None
        near = mark is not None and self.first is not None and self.first - 60 <= mark <= (self.last or mark) + 60
        self.anchor = mark if near else self.last
        self.anchor_is_mark = bool(near)
        self.steps = []
        self.by_operation = {}
        self.by_task = {}
        self.issues = []
        self.member_step = {}

    # ---- steps --------------------------------------------------------
    def _operations(self):
        ops = {}
        for index, (row, stamp) in enumerate(zip(self.rows, self.times)):
            op_id = row.get("operation_id")
            if not op_id or stamp is None:
                continue
            if row.get("event_name") == "operation.start":
                ops.setdefault(op_id, {}).update(action=str(row.get("action") or ""), start=stamp,
                                                  parent=row.get("parent_operation_id"), index=index)
            elif row.get("event_name") == "operation.end":
                entry = ops.setdefault(op_id, {"action": str(row.get("action") or ""), "start": stamp, "parent": row.get("parent_operation_id")})
                entry.update(end=stamp, duration_ms=row.get("duration_ms"), result=row.get("result"), slow=bool(row.get("slow")), end_index=index)
        def root(op_id, depth=0):
            parent = ops.get(op_id, {}).get("parent")
            return root(parent, depth + 1) if parent in ops and depth < 16 else op_id
        for op_id, entry in ops.items():
            entry["root"] = root(op_id)
        return ops

    def _open_windows(self):
        windows, pending = [], None
        for row, stamp in zip(self.rows, self.times):
            if stamp is None:
                continue
            if row.get("event_name") == "open.request":
                pending = stamp
            elif row.get("event_name") == "open.finished" and pending is not None:
                windows.append((pending, stamp))
                pending = None
        return windows

    def build_steps(self):
        rows, times = self.rows, self.times
        session = next(((r, t) for r, t in zip(rows, times) if r.get("event_name") == "session.start" and t), None)
        if session:
            ready = next(((r, t) for r, t in zip(rows, times) if r.get("event_name") == "startup.interactive" and t), None)
            step = Step("startup", "startup", session[1], ready[1] if ready else session[1], name=tr("启动程序"))
            if ready and isinstance(ready[0].get("elapsed_ms"), (int, float)):
                step.detail = tr("启动到可以操作用了 {seconds} 秒", seconds=seconds_text(ready[0]["elapsed_ms"] / 1000))
            self.steps.append(step)
        ops = self._operations()
        windows = self._open_windows()
        current = None
        for op_id, entry in sorted(((k, v) for k, v in ops.items() if v["root"] == k), key=lambda kv: kv[1]["start"]):
            action = entry["action"]
            if not action or action.startswith("startup.") or action in _NOT_STEPS:
                continue
            family = _family(action)
            start, end = entry["start"], entry.get("end", entry["start"])
            if current is not None and current.family == "open" and current.open_until and start <= current.open_until:
                current.operation_ids.add(op_id)
                if family == "open":
                    current.actions.append(action)
                current.end = max(current.end, end)
                continue
            gap = _MERGE_GAP.get(family)
            if current is not None and current.family == family and gap is not None and start - current.end <= gap:
                current.actions.append(action)
                current.operation_ids.add(op_id)
                current.end = max(current.end, end)
                current.slow = current.slow or bool(entry.get("slow"))
            else:
                current = Step("operation", family, start, end, actions=[action], operation_ids={op_id},
                               slow=bool(entry.get("slow")))
                self.steps.append(current)
            if family == "open":
                for request, finished in windows:
                    if request - 1.5 <= start <= finished + 0.5 or start <= request <= start + 2.0:
                        current.start = min(current.start, request)
                        current.open_until = max(current.open_until or 0, finished)
                        current.end = max(current.end, finished)
        for op_id, entry in ops.items():
            owner = next((s for s in self.steps if entry["root"] in s.operation_ids), None)
            if owner is not None:
                self.by_operation[op_id] = owner
        for row, stamp in zip(rows, times):
            if row.get("event_name") != "background.start" or not row.get("task_id") or stamp is None:
                continue
            task = row["task_id"]
            done = [t for r, t in zip(rows, times) if t and r.get("task_id") == task]
            step = Step("task", "task", stamp, max(done) if done else stamp, task_ids={task},
                        name=self._task_name(task, str(row.get("purpose") or "")))
            self.steps.append(step)
            self.by_task[task] = step
        self._standalone_commits()
        self._name_steps()

    def _task_name(self, task, purpose=""):
        if purpose == "translation":
            return tr("AI 翻译")
        if purpose == "sentence_refine":
            return tr("AI 断句优化")
        markers = " ".join(str(r.get("validator") or r.get("module") or "") for r in self.rows if r.get("task_id") == task)
        if "grouping" in markers or "boundary" in markers:
            return tr("AI 断句")
        if "translation" in markers:
            return tr("AI 翻译")
        return tr("后台任务：{name}", name=purpose or task)

    def _standalone_commits(self):
        last = None
        for row, stamp in zip(self.rows, self.times):
            if row.get("event_name") not in {"data.commit", "data.rollback"} or stamp is None:
                continue
            op_id = row.get("operation_id")
            if op_id in self.by_operation:
                continue
            command = str(row.get("action") or "transaction").split(".", 1)[0]
            if command == "transaction":
                owner = next((s for s in reversed(self.steps) if s.start <= stamp <= s.end + 1.0), None)
                if owner is not None:
                    if op_id:
                        self.by_operation[op_id] = owner
                    continue
            latest = max((s.start for s in self.steps if s.kind != "task" and s.start <= stamp), default=None)
            if last is not None and stamp - last.end <= 1.0 and latest == last.start:
                last.actions.append(command)
                last.end = stamp
            else:
                last = Step("data", "data", stamp, stamp, actions=[command])
                self.steps.append(last)
            if op_id:
                self.by_operation[op_id] = last

    def _name_steps(self):
        opened = False
        for step in sorted(self.steps, key=lambda s: s.start):
            if step.name is not None:
                continue
            actions = step.actions
            if step.kind == "data":
                names = list(dict.fromkeys(COMMAND_LABELS.get(a, "修改工程数据") for a in actions))
                step.name = join_text([tr(n) for n in names[:3]])
                step.detail = tr("没有对应的界面操作：可能是撤销／重做或程序自动修改")
                continue
            if step.family == "open":
                reopen = opened or "project.close" in actions
                opened = True
                step.name = tr("重新打开工程" if reopen else "打开工程")
                loaded = [r.get("cue_count") for r, t in zip(self.rows, self.times)
                          if r.get("event_name") in {"open.finished", "project.loaded"} and t and step.start - 1 <= t <= step.end + 1
                          and isinstance(r.get("cue_count"), int)]
                if loaded:
                    step.detail = tr("{count} 条字幕", count=loaded[-1])
                continue
            if step.family == "save":
                step.name = tr("保存工程")
                continue
            distinct = list(dict.fromkeys(actions))
            if len(actions) == 1:
                step.name = _label(actions[0])
            elif len(distinct) == 1:
                step.name = tr("{action} ×{count}", action=_label(distinct[0]), count=len(actions))
            elif step.family == "play":
                step.name = tr("播放控制 ×{count}", count=len(actions))
            else:
                step.name = tr("编辑字幕 ×{count}", count=len(actions))
            if len(distinct) > 1:
                step.detail = join_text([_label(a) for a in distinct[:5]])

    # ---- issues -------------------------------------------------------
    def build_issues(self):
        rows, times = self.rows, self.times
        stalls_seen = []
        processes = {}
        ai_groups = {}
        exceptions = {}
        quiet = {}
        fallbacks = {}
        commit_checks = set()
        for index, (row, stamp) in enumerate(zip(rows, times)):
            if stamp is None:
                continue
            name = str(row.get("event_name") or "")
            level = row.get("level")
            failed = level == "ERROR" or row.get("result") == "failed"
            seq = row.get("sequence")
            if name == "gui.stall":
                duration = row.get("duration_ms")
                if not isinstance(duration, (int, float)) or duration < 250:
                    continue
                if any(abs(duration - d) < 0.5 and abs(stamp - t) < 0.2 for d, t in stalls_seen):
                    continue
                stalls_seen.append((duration, stamp))
                where, context = _stall_location(row)
                seconds = seconds_text(duration / 1000)
                title = (tr("画面卡住 {seconds} 秒（{context}）", seconds=seconds, context=tr(context)) if context
                         else tr("画面卡住 {seconds} 秒", seconds=seconds))
                advice = (tr("如果每次都卡这么久，回报时写下当时在做什么和工程有多少条字幕。") if duration >= 1000
                          else tr("偶尔一次不用处理；经常出现请回报。"))
                self.issues.append(Issue("stall", title, advice, f"gui.stall · {where or 'location unknown'} · #{seq}",
                                         stamp - duration / 1000, stamp, members=[index], operation_id=row.get("operation_id"),
                                         duration_ms=float(duration), lane="stall",
                                         short=tr("卡住 {seconds} 秒", seconds=seconds)))
            elif name == "operation.end":
                action = str(row.get("action") or "")
                if row.get("result") == "failed":
                    types, where = _chain_text(row.get("exception"))
                    self.issues.append(Issue("act", tr("{action}失败", action=_label(action)),
                                             tr("重做一次；如果还会失败，导出诊断包并写下步骤。"),
                                             " · ".join(x for x in (f"operation.end {action}", types, where, f"#{seq}") if x),
                                             stamp, members=[index], operation_id=row.get("operation_id"), short=tr("失败")))
                elif (isinstance(row.get("duration_ms"), (int, float)) and (row.get("slow") or row["duration_ms"] > 250)
                      and not action.startswith("startup.") and action not in _NOT_STEPS):
                    seconds = seconds_text(row["duration_ms"] / 1000)
                    self.issues.append(Issue("slow", tr("{action}用了 {seconds} 秒", action=_label(action), seconds=seconds),
                                             tr("工程很大时属正常；如果每次都这么慢，回报时写下工程有多少条字幕。"),
                                             f"operation.end {action} · {round(row['duration_ms'])} ms · {row.get('operation_id')} · #{seq}",
                                             stamp - row["duration_ms"] / 1000, stamp, members=[index],
                                             operation_id=row.get("operation_id"), duration_ms=float(row["duration_ms"]), lane="none",
                                             short=tr("{seconds} 秒", seconds=seconds)))
            elif name in {"process.failure", "process.end"} and failed:
                purpose = str(row.get("purpose") or "")
                code = row.get("exit_code")
                occurrence = (purpose, row.get("child_pid") or row.get("child_operation_id") or seq)
                key = (purpose, None if purpose in _PROBE_PURPOSES else code)
                runs = processes.setdefault(key, [])
                if not runs or stamp - runs[-1]["last"] > 5.0 or any(
                        step.kind == "operation" and runs[-1]["last"] < step.start <= stamp for step in self.steps):
                    runs.append(dict(occurrences=set(), start=stamp, last=stamp, members=[], code=code, codes=[]))
                group = runs[-1]
                if code not in group["codes"]:
                    group["codes"].append(code)
                group["occurrences"].add(occurrence)
                group["members"].append(index)
                group["last"] = stamp
            elif name == "ai.validation" and failed:
                group = ai_groups.setdefault(row.get("task_id"), dict(members=[], codes=Counter(), validators=set(), start=stamp, project=row.get("project_id")))
                group["members"].append(index)
                group["codes"][str(row.get("error_code") or "unknown")] += 1
                group["validators"].add(str(row.get("validator") or ""))
            elif name == "grouping.api.fallback":
                ai_groups.setdefault(row.get("task_id"), dict(members=[], codes=Counter(), validators=set(), start=stamp, project=row.get("project_id")))["members"].append(index)
            elif name == "ai.fallback" and row.get("result") == "completed":
                fallbacks[row.get("task_id")] = (index, row)
            elif name in {"thread.exception", "python.exception", "async.exception"}:
                types, where = _chain_text(row.get("exception"))
                key = (name, types, where)
                group = exceptions.setdefault(key, dict(members=[], start=stamp, row=row))
                group["members"].append(index)
            elif name == "data.commit":
                before, after = row.get("before") or {}, row.get("after") or {}
                was, now_ = before.get("valid_translation_sample_count"), after.get("valid_translation_sample_count")
                if isinstance(was, int) and isinstance(now_, int) and now_ < was:
                    commit_checks.add(row.get("operation_id"))
                    self.issues.append(Issue("check", tr("有效译文从 {before} 条变成 {after} 条", before=was, after=now_),
                                             tr("如果你没有删除译文，这可能就是问题所在：按 Ctrl+Z 撤销这一步，看译文是否回来；导出时勾选“附上选取的字幕”。"),
                                             f"data.commit {row.get('action')} · cues {before.get('cue_count')}→{after.get('cue_count')} · revision {row.get('revision_before')}→{row.get('revision_after')} · {row.get('operation_id')} · #{seq}",
                                             stamp, members=[index], operation_id=row.get("operation_id"),
                                             short=tr("译文 {before} → {after}", before=was, after=now_)))
            elif name == "translation.links" and level == "WARN":
                if row.get("operation_id") in commit_checks:
                    continue
                self.issues.append(Issue("check", tr("显示的译文从 {before} 条变成 {after} 条", before=row.get("before"), after=row.get("after")),
                                         tr("如果你没有删除译文，按 Ctrl+Z 撤销这一步，看译文是否回来。"),
                                         f"translation.links {row.get('action')} · {row.get('operation_id')} · #{seq}", stamp, members=[index],
                                         operation_id=row.get("operation_id"), short=tr("译文 {before} → {after}", before=row.get("before"), after=row.get("after"))))
            elif name in {"data.rollback", "view.failed", "timing.validation"} and failed:
                titles = {"data.rollback": ("这次修改没有通过检查，已恢复原状", "重做一次；如果还会这样，回报时写下改了什么。"),
                          "view.failed": ("数据已修改，但画面没有更新", "切换一次页面或重新打开工程，看画面是否恢复。"),
                          "timing.validation": ("出现了时间不合法的字幕", "按 Ctrl+Z 撤销上一步，再检查这条字幕的开始和结束时间。")}
                title, advice = titles[name]
                types, where = _chain_text(row.get("exception"))
                self.issues.append(Issue("act", tr(title), tr(advice),
                                         " · ".join(x for x in (name, str(row.get("action") or ""), str(row.get("error_code") or ""), types, where, f"#{seq}") if x and x != "None"),
                                         stamp, members=[index], operation_id=row.get("operation_id"), short=tr("错误")))
            elif name == "background.result":
                decision = str(row.get("result") or "")
                found = {"failed": ("act", "后台任务失败", "重试一次；如果还会失败，回报时写下用的是哪个服务。"),
                         "discarded_project_changed": ("check", "后台结果没有套用：期间工程已经改变", "确认需要的话重新运行一次。"),
                         "discarded_no_project": ("check", "后台结果没有套用：工程已经关闭", "确认需要的话重新运行一次。"),
                         "partially_accepted": ("check", "后台结果只套用了一部分", "部分字幕在运行期间被修改过，那几条保持原样。")}.get(decision)
                if found:
                    kind, title, advice = found
                    self.issues.append(Issue(kind, tr(title), tr(advice),
                                             f"background.result {row.get('purpose')} · {decision} · {row.get('task_id')} · #{seq}",
                                             stamp, members=[index], task_id=row.get("task_id"), operation_id=row.get("operation_id"),
                                             short=tr("错误") if kind == "act" else tr("请核对")))
            elif name == "qt.message" and level in {"WARN", "ERROR"}:
                quiet.setdefault("qt", dict(members=[], start=stamp))["members"].append(index)
            elif name == "python.log" and level in {"ERROR", "CRITICAL"}:
                module = str(row.get("module") or "")
                group = exceptions.setdefault(("python.log", module, ""), dict(members=[], start=stamp, row=row))
                group["members"].append(index)
            elif name == "python.log" and level == "WARN":
                quiet.setdefault("log", dict(members=[], start=stamp))["members"].append(index)
            elif failed and name not in {"export.end", "report.dialog"}:
                quiet.setdefault(("other", name), dict(members=[], start=stamp, row=row))["members"].append(index)
        self._process_issues(processes)
        self._ai_issues(ai_groups, fallbacks)
        self._exception_issues(exceptions)
        self._quiet_issues(quiet)

    def _process_issues(self, processes):
        for (purpose, _key_code), runs in processes.items():
            for group in runs:
                self._process_issue(purpose, group)

    def _process_issue(self, purpose, group):
        code = group["code"]
        count = len(group["occurrences"])
        name = PROCESS_NAMES.get(purpose, purpose or "?")
        dev = f"{purpose} · exit {' / '.join(_exit_text(c) for c in group['codes'])} · " + " ".join(f"#{self.rows[i].get('sequence')}" for i in group["members"][:6])
        if purpose == "ffmpeg encoder probe":
            issue = Issue("ignore", tr("硬件编码器探测 ×{count}", count=count),
                          tr("不用处理：这台电脑不支持部分硬件编码器。只有导出视频失败时才值得一看。"), dev, group["start"])
        elif purpose == "diagnostic graphics inventory":
            issue = Issue("ignore", tr("读取显卡信息失败 ×{count}", count=count), tr("不用处理：只影响诊断包里的显卡信息。"), dev, group["start"])
        elif purpose.startswith("nvidia-smi"):
            issue = Issue("ignore", tr("NVIDIA 显卡检查没有结果 ×{count}", count=count),
                          tr("没有 NVIDIA 显卡或驱动时属正常；本来有显卡却看到这条时请回报。"), dev, group["start"])
        elif purpose in {"Studio follower video decoder", "Studio audio PCM decoder"} and code == 1:
            issue = Issue("ignore", tr("旧的解码程序被停止 ×{count}", count=count),
                          tr("不用处理：切换或重新打开工程时程序会停掉旧的解码程序，Windows 记为退出码 1。"), dev, group["start"])
        else:
            title = tr("外部程序失败：{name}（退出码 {code}）", name=tr(name) if purpose in PROCESS_NAMES else name, code=_exit_text(code))
            if count > 1:
                title = tr("{title}（{count} 次）", title=title, count=count)
            issue = Issue("act", title, tr("重做一次；如果固定出现，导出诊断包回报。"), dev, group["start"], short=tr("错误"))
        issue.count, issue.members, issue.end = count, group["members"], group["last"]
        if issue.short is None:
            issue.short = tr("可忽略")
        self.issues.append(issue)

    def _ai_issues(self, groups, fallbacks):
        for task, group in groups.items():
            failures = [i for i in group["members"] if self.rows[i].get("event_name") == "ai.validation"]
            if not failures:
                continue
            fallback = fallbacks.get(task)
            grouping = any("grouping" in v or "boundary" in v for v in group["validators"])
            codes = " / ".join(code for code, _n in group["codes"].most_common(4))
            first, last = self.rows[group["members"][0]].get("sequence"), self.rows[group["members"][-1]].get("sequence")
            members = list(group["members"]) + ([fallback[0]] if fallback else [])
            types, where = _chain_text(self.rows[failures[0]].get("exception"))
            detail = self.rows[failures[0]].get("rule_detail")
            dev = (f"ai.validation ×{len(failures)} ({len(group['codes'])} rules: {codes})"
                   + (" → ai.fallback" if fallback else "") + f" · {task or '—'} · #{first}–#{last}"
                   + "".join(f" · {x}" for x in (types, where, detail) if x))
            if fallback:
                title = (tr("AI 断句结果有 {count} 次没通过检查，已改用本地断句", count=len(failures)) if grouping
                         else tr("AI 结果有 {count} 次没通过检查，已改用本地规则", count=len(failures)))
                issue = Issue("auto", title, tr("字幕不会因此损坏；如果这段结果不理想，换一个 AI 模型或重试。"), dev,
                              group["start"], short=tr("AI ×{count}", count=len(failures)))
            else:
                issue = Issue("act", tr("AI 结果有 {count} 次没通过检查", count=len(failures)),
                              tr("换一个 AI 模型或重试；如果每次都这样，回报时写下用的是哪个服务。"), dev,
                              group["start"], short=tr("AI ×{count}", count=len(failures)))
            issue.count, issue.members, issue.task_id = len(failures), members, task
            issue.end = self.times[members[-1]]
            self.issues.append(issue)

    def _exception_issues(self, groups):
        titles = {"thread.exception": "后台工作出错，这项工作可能没有完成", "python.exception": "程序出错",
                  "async.exception": "异步任务出错", "python.log": "程序记录了错误"}
        for (name, types, where), group in groups.items():
            row = group["row"]
            count = len(group["members"])
            if name == "python.log":
                dev = f"python.log {types} · " + " ".join(f"#{self.rows[i].get('sequence')}" for i in group["members"][:4])
            else:
                dev = " · ".join(x for x in (name, types, where, " ".join(f"#{self.rows[i].get('sequence')}" for i in group["members"][:4])) if x)
            title = tr(titles[name]) if count == 1 else tr("{title}（{count} 次）", title=tr(titles[name]), count=count)
            self.issues.append(Issue("act", title, tr("重做一次出问题前的操作；如果还会出现，导出诊断包并写下步骤。"), dev,
                                     group["start"], count=count, members=group["members"], operation_id=row.get("operation_id"),
                                     task_id=row.get("task_id"), short=tr("错误")))

    def _quiet_issues(self, groups):
        for key, group in groups.items():
            count = len(group["members"])
            seqs = " ".join(f"#{self.rows[i].get('sequence')}" for i in group["members"][:4])
            if key == "qt":
                issue = Issue("ignore", tr("Qt 内部提示 ×{count}", count=count), tr("不用处理：通常不影响使用。"), f"qt.message · {seqs}", group["start"])
            elif key == "log":
                issue = Issue("ignore", tr("程序警告日志 ×{count}", count=count), tr("不用处理：只有和其他错误同时出现时才值得一看。"), f"python.log WARN · {seqs}", group["start"])
            else:
                row = group["row"]
                issue = Issue("act", tr("程序记录到失败 ×{count}", count=count), tr("如果和你遇到的问题同时发生，导出诊断包回报。"),
                              f"{key[1]} · {row.get('error_code') or ''} · {seqs}", group["start"],
                              operation_id=row.get("operation_id"), task_id=row.get("task_id"), short=tr("错误"))
            issue.count, issue.members = count, group["members"]
            if issue.short is None:
                issue.short = tr("可忽略")
            self.issues.append(issue)

    # ---- attach -------------------------------------------------------
    def attach(self):
        for issue in sorted(self.issues, key=lambda i: i.start):
            step = None
            if issue.operation_id and issue.operation_id in self.by_operation:
                step, issue.relation = self.by_operation[issue.operation_id], tr("同一操作")
            elif issue.task_id and issue.task_id in self.by_task:
                step, issue.relation = self.by_task[issue.task_id], tr("同一任务")
            elif issue.task_id and issue.kind in {"act", "auto", "check"}:
                step = Step("task", "task", issue.start, issue.end or issue.start, task_ids={issue.task_id},
                            name=self._task_name(issue.task_id))
                self.steps.append(step)
                self.by_task[issue.task_id] = step
                issue.relation = tr("同一任务")
            else:
                step = self._by_time(issue)
            step.issues.append(issue)
            issue.step = step
            for member in issue.members:
                self.member_step[member] = step

    def _by_time(self, issue):
        ordered = sorted(self.steps, key=lambda s: s.start)
        if issue.lane == "stall" and issue.end is not None:
            overlaps = [(min(issue.end, s.end) - max(issue.start, s.start), s) for s in ordered if s.kind != "task"]
            overlaps = [o for o in overlaps if o[0] > 0]
            if overlaps:
                issue.relation = tr("这一步进行中")
                return max(overlaps, key=lambda o: o[0])[1]
        inside = [s for s in ordered if s.start <= issue.start <= s.end + 0.05 and s.kind != "task"]
        if inside:
            issue.relation = tr("这一步进行中")
            return inside[-1]
        before = [s for s in ordered if s.start <= issue.start]
        if before:
            step = max(before, key=lambda s: (s.end, s.start))
            issue.relation = tr("启动时") if step.kind == "startup" and issue.start - step.end < 3 else _relation_after(issue.start - step.end)
            return step
        step = Step("unknown", "unknown", issue.start, issue.start, name=tr("这段记录开始时"))
        self.steps.append(step)
        issue.relation = tr("这一步进行中")
        return step

    # ---- result -------------------------------------------------------
    def result(self):
        steps = sorted(self.steps, key=lambda s: (s.start, s.end))
        for number, step in enumerate(steps, 1):
            step.id = f"s{number}"
            step.issues.sort(key=lambda i: (i.rank, i.start))
            if step.name is None:
                step.name = tr("操作")
        start_step = self._start_step(steps)
        counts = Counter(i.kind for i in self.issues if i.kind != "ignore")
        counts["ignore"] = len(merged_titles(i for i in self.issues if i.kind == "ignore"))
        running = []
        started, tasks = {}, {}
        for row in self.rows:
            name = row.get("event_name")
            if name == "process.start" and row.get("child_operation_id"):
                started[row["child_operation_id"]] = str(row.get("purpose") or row["child_operation_id"])
            elif name == "process.end":
                started.pop(row.get("child_operation_id"), None)
            elif name == "background.start" and row.get("task_id"):
                tasks[row["task_id"]] = str(row.get("purpose") or row["task_id"])
            elif name == "background.result":
                tasks.pop(row.get("task_id"), None)
        for purpose in dict.fromkeys(started.values()):
            running.append(tr(PROCESS_NAMES[purpose]) if purpose in PROCESS_NAMES else purpose)
        for purpose in dict.fromkeys(tasks.values()):
            running.append(tr("后台任务：{name}", name=purpose))
        event_steps = []
        for index, (row, stamp) in enumerate(zip(self.rows, self.times)):
            step = self.member_step.get(index) or self.by_operation.get(row.get("operation_id")) or self.by_task.get(row.get("task_id"))
            if step is None and stamp is not None:
                step = next((s for s in reversed(steps) if s.kind != "task" and s.start <= stamp <= s.end + 0.05), None)
            event_steps.append(step.id if step else None)
        flagged = {m for i in self.issues if i.kind in PROBLEM_KINDS for m in i.members}
        kinds = {}
        for issue in sorted(self.issues, key=lambda i: -i.rank):
            for member in issue.members:
                kinds[member] = issue.kind
        stalls = [i.duration_ms for i in self.issues if i.kind == "stall"]
        return Analysis(self.first, self.last, self.anchor, self.anchor_is_mark, steps,
                        sorted(self.issues, key=lambda i: (i.rank, i.start)), dict(counts), start_step, running,
                        self._notes(), event_steps, [index in flagged for index in range(len(self.rows))],
                        [kinds.get(index) for index in range(len(self.rows))], max(stalls) if stalls else None, self._environment())

    def _start_step(self, steps):
        anchor = self.anchor if self.anchor is not None else float("inf")
        for kinds in (("act",), ("check",)):
            candidates = [(i.start, i.step) for i in self.issues if i.kind in kinds and i.start <= anchor + 1]
            if not candidates:
                candidates = [(i.start, i.step) for i in self.issues if i.kind in kinds]
            if candidates:
                return max(candidates, key=lambda c: c[0])[1]
        long = [i for i in self.issues if i.kind == "stall" and (i.duration_ms or 0) >= 1000]
        return max(long, key=lambda i: i.duration_ms).step if long else None

    def _notes(self):
        notes = []
        losses = self.data.get("losses") or {}
        serious = {k: v for k, v in losses.items() if v and any(w in k for w in ("failed", "dropped", "rotated", "truncated", "suppressed"))}
        if serious:
            notes.append(tr("记录可能不完整：{detail}", detail=json.dumps(serious, ensure_ascii=False)))
        if losses.get("sampled_events"):
            notes.append(tr("{count} 条高频事件按规则抽样记录", count=losses["sampled_events"]))
        missing = self.data.get("missing_count") or len(self.data.get("missing") or [])
        if missing:
            notes.append(tr("有 {count} 处记录读不到，原因写在 manifest.json", count=missing))
        for session in self.data.get("sessions") or []:
            if session.get("status") in {"previous_not_cleanly_ended", "not_cleanly_ended"}:
                notes.append(tr("上次运行没有正常结束：只表示没看到正常结束的记录，不能据此判定是崩溃、断电还是被强制结束"))
                break
        for session in self.data.get("sessions") or []:
            if session.get("write_error"):
                notes.append(tr("诊断记录写入出错：{error}", error=session["write_error"]))
                break
        return notes

    def _environment(self):
        found = {}
        for row in self.rows:
            name = row.get("event_name")
            if name == "host" and "host" not in found:
                found["host"] = dict(cpu=row.get("cpu"), logical_cpus=row.get("logical_cpus"), ram_gb=row.get("ram_gb"))
            elif name == "screens" and "screens" not in found:
                found["screens"] = [s.get("scale") for s in row.get("screens") or [] if isinstance(s, dict)]
            elif name == "resources":
                main = next((p for p in row.get("processes") or [] if isinstance(p, dict) and p.get("role") == "main"), None)
                if main:
                    found["memory_mb"] = round((main.get("rss_bytes") or 0) / 1048576)
        for session in self.data.get("sessions") or []:
            if session.get("platform"):
                found.setdefault("platform", session.get("platform"))
                found.setdefault("frozen", session.get("frozen"))
                found.setdefault("build", session.get("build") if isinstance(session.get("build"), dict) else {})
        return found


EVENT_LABELS = {
    "session.start": "诊断会话开始", "session.end": "诊断会话结束", "operation.start": "开始操作",
    "operation.end": "操作结束", "command.received": "收到命令", "command.result": "命令结果",
    "data.begin": "开始修改工程数据", "data.commit": "工程数据已提交", "data.rollback": "修改没有通过检查，已恢复",
    "view.begin": "开始更新画面", "view.applied": "画面已更新", "view.failed": "画面更新失败", "problem.marked": "你按下回报",
    "background.start": "后台任务开始", "background.result": "后台任务结果", "project.loaded": "工程已读取",
    "project.saved": "工程已写入", "player.command": "播放器命令", "player.state": "播放器状态",
    "player.intent": "播放／暂停请求", "ai.validation": "AI 结果检查", "ai.fallback": "AI 结果改用本地规则",
    "grouping.api.fallback": "AI 断句改用备用方案", "process.start": "外部程序启动", "process.end": "外部程序结束",
    "process.failure": "外部程序失败", "python.exception": "程序出错", "thread.exception": "后台工作出错",
    "async.exception": "异步任务出错", "qt.message": "Qt 提示", "gui.stall": "画面卡住",
    "diagnostics.mode": "诊断记录模式改变", "export.start": "开始导出诊断包", "export.end": "诊断包导出结束",
    "translation.links": "译文关联变化", "timing.validation": "时间检查", "report.dialog": "回报窗口",
    "python.log": "程序日志", "open.request": "请求打开工程", "open.finished": "工程打开完成",
}
LEVEL_LABELS = {"ERROR": "错误", "WARN": "警告", "INFO": "信息", "DEBUG": "调试"}
KIND_LABELS = {"act": "错误", "check": "请核对", "stall": "卡顿", "slow": "偏慢", "auto": "已处理", "ignore": "可忽略"}


def event_title(row):
    """(what happened, technical detail) for one log row."""
    name = str(row.get("event_name") or "")
    title = tr(EVENT_LABELS[name]) if name in EVENT_LABELS else name
    parts = []
    action = row.get("action")
    if action:
        parts.append(str(_label(str(action))) if str(action) in ACTION_LABELS else str(action))
    for key in ("purpose", "error_code", "validator"):
        if row.get(key):
            parts.append(str(row[key]))
    if row.get("exit_code") is not None:
        parts.append(f"exit {_exit_text(row['exit_code'])}")
    if isinstance(row.get("duration_ms"), (int, float)):
        parts.append(f"{round(row['duration_ms'])} ms")
    types, _where = _chain_text(row.get("exception"))
    if types:
        parts.append(types)
    return title, " · ".join(parts)


def merged_titles(issues):
    """One title per kind of finding: '旧的视频解码程序被停止 ×2' twice reads ×4."""
    totals = {}
    for issue in issues:
        title = issue.title
        arguments = dict(getattr(title, "arguments", None) or {})
        count = arguments.pop("count", None)
        key = (getattr(title, "source", str(title)), tuple(sorted((k, str(v)) for k, v in arguments.items())))
        entry = totals.setdefault(key, [title, arguments, 0, count is not None])
        entry[2] += count if isinstance(count, int) else issue.count
    return [tr(getattr(title, "source", str(title)), **arguments, count=total) if counted else title
            for title, arguments, total, counted in totals.values()]


def analyze(data, report=None):
    """The steps, issues and counts of one ``collect`` result."""
    builder = _Builder(data, report)
    builder.build_steps()
    builder.build_issues()
    builder.attach()
    return builder.result()


def step_chips(step, limit=2):
    """(tone, label) badges for one step, most severe first."""
    chips = []
    act = step.counted("act")
    if act:
        chips.append(("danger", tr("错误 {count}", count=sum(i.count for i in act))))
    for issue in step.counted("check"):
        chips.append(("warn", issue.short))
    slow = step.counted("slow")
    if slow:
        chips.append(("warn", tr("{seconds} 秒", seconds=seconds_text(max(i.duration_ms for i in slow) / 1000))))
    stalls = step.counted("stall")
    if stalls:
        chips.append(("warn", tr("卡住 {seconds} 秒", seconds=seconds_text(max(i.duration_ms for i in stalls) / 1000))
                      if len(stalls) == 1 else tr("卡住 {count} 次", count=len(stalls))))
    if step.counted("auto"):
        chips.append(("info", tr("已处理 {count}", count=len(step.counted("auto")))))
    if not chips and step.counted("ignore"):
        chips.append(("muted", tr("可忽略")))
    return chips[:limit]


def step_headline(step):
    """One sentence: what happened in or right after this step."""
    act, check = step.counted("act"), step.counted("check")
    slow, stalls = step.counted("slow"), step.counted("stall")
    if act:
        total = sum(i.count for i in act)
        if all(i.relation is not None and i.relation.source.startswith("之后") for i in act):
            delay = max(i.start - step.end for i in act)
            return tr("这一步本身完成了，但之后 {seconds} 秒内出现 {count} 个错误", seconds=seconds_text(delay), count=total)
        return tr("这一步出现 {count} 个错误", count=total)
    if check:
        return check[0].title
    if slow and stalls:
        return tr("完成了，但用了 {seconds} 秒，期间画面卡住 {count} 次",
                  seconds=seconds_text(max(i.duration_ms for i in slow) / 1000), count=len(stalls))
    if slow:
        return tr("完成了，但用了 {seconds} 秒", seconds=seconds_text(max(i.duration_ms for i in slow) / 1000))
    if stalls:
        return tr("期间画面卡住 {count} 次，最长 {seconds} 秒", count=len(stalls),
                  seconds=seconds_text(max(i.duration_ms for i in stalls) / 1000))
    if step.counted("auto"):
        return tr("有 {count} 项问题已经自动处理", count=len(step.counted("auto")))
    if step.counted("ignore"):
        return tr("没有问题；有 {count} 项可以忽略的记录", count=len(step.counted("ignore")))
    return tr("没有发现问题")


def ago_text(analysis, stamp):
    """−2.7 秒 relative to the report mark (or the end of the range)."""
    if analysis.anchor is None or stamp is None:
        return "—"
    delta = stamp - analysis.anchor
    if abs(delta) < 0.005:
        return tr("0 秒")
    return tr("{sign}{seconds} 秒", sign="−" if delta < 0 else "+", seconds=seconds_text(delta))


def legend(analysis):
    """(tone, label, number) for the header row."""
    counts = analysis.counts
    return [("danger", tr("需要处理"), counts.get("act", 0)), ("warn", tr("请核对"), counts.get("check", 0)),
            ("warn", tr("卡顿"), counts.get("stall", 0)), ("info", tr("已自动处理"), counts.get("auto", 0)),
            ("muted", tr("可忽略"), counts.get("ignore", 0))]


def render_summary(analysis, *, report_id, description="", generated="", version="", scope="", event_count=0, extra_notes=()):
    """README.txt and the copied text: conclusion first, details after."""
    lines = [str(tr("2ByteASR 诊断摘要 · {report}", report=report_id)),
             str(tr("用户描述：{text}", text=description or tr("未填写")))]
    if analysis.anchor is not None:
        moment = datetime.fromtimestamp(analysis.anchor)
        offset = moment.astimezone().strftime("%z")
        zone = f"UTC{offset[:3]}:{offset[3:]}" if offset else ""
        label = tr("标记时间") if analysis.anchor_is_mark else tr("记录结束")
        lines.append(f"{label}：{moment.strftime('%Y-%m-%d %H:%M:%S')}.{moment.microsecond // 1000:03d}（{zone}）"
                     + " · " + str(tr("范围：{scope}，{count} 笔", scope=scope, count=event_count)))
    if version:
        lines.append(version)
    if generated:
        lines.append(str(tr("生成时间：{time}", time=generated)))
    counts = analysis.counts
    lines += ["", str(tr("【结论】需要处理 {act} · 请核对 {check} · 卡顿 {stall} 次{longest} · 慢操作 {slow} · 已自动处理 {auto} · 可忽略 {ignore}",
                        act=counts.get("act", 0), check=counts.get("check", 0), stall=counts.get("stall", 0),
                        longest=tr("（最长 {seconds} 秒）", seconds=seconds_text(analysis.longest_stall_ms / 1000)) if analysis.longest_stall_ms else "",
                        slow=counts.get("slow", 0), auto=counts.get("auto", 0), ignore=counts.get("ignore", 0)))]
    start = analysis.start_step
    if start is not None:
        lines += ["", str(tr("【从这里开始】{name}（{ago}）", name=start.name, ago=ago_text(analysis, start.start)))]
        for issue in start.issues:
            if issue.kind == "ignore":
                continue
            mark = "●" if issue.kind == "act" else "○"
            lines.append(f"  {mark} {issue.title} · {issue.relation or ''}")
            lines.append(f"    {issue.dev}")
    else:
        lines += ["", str(tr("【从这里开始】这段时间没有记录到错误、资料异常或明显卡顿；不能据此判定没有问题。请写下重现步骤，或打开“详细记录 10 分钟”后重做一次再导出。"))]
    trail = [s for s in reversed(analysis.steps) if s is not start and any(i.kind != "ignore" for i in s.issues)]
    if trail:
        lines += ["", str(tr("【操作轨迹】从标记往前，只列有状况的步骤"))]
        for step in trail[:12]:
            lines.append(f"  {ago_text(analysis, step.start):>8}  {step.name} — {step_headline(step)}")
            for issue in step.issues:
                if issue.kind != "ignore":
                    lines.append(f"      {issue.title} · {issue.dev}")
    ignored = [i for i in analysis.issues if i.kind == "ignore"]
    if ignored:
        lines += ["", str(tr("【可忽略】{items}", items=" · ".join(str(t) for t in merged_titles(ignored))))]
    if analysis.running:
        lines.append(str(tr("【仍在执行】{items}", items="、".join(str(n) for n in analysis.running))))
    notes = [str(n) for n in analysis.notes] + [str(n) for n in extra_notes]
    lines.append(str(tr("【记录】{notes}", notes="；".join(notes) or tr("完整，没有读取失败"))))
    env = analysis.environment
    parts = []
    if env.get("platform"):
        parts.append(str(env["platform"]))
    host = env.get("host") or {}
    if host.get("logical_cpus"):
        parts.append(str(tr("{count} 线程", count=host["logical_cpus"])))
    if host.get("ram_gb"):
        parts.append(f"{host['ram_gb']} GB")
    if env.get("screens"):
        parts.append(str(tr("{count} 个屏幕 {scales}", count=len(env["screens"]),
                            scales="/".join(f"{round(float(s) * 100)}%" for s in env["screens"] if isinstance(s, (int, float))))))
    if env.get("memory_mb"):
        parts.append(str(tr("本程序内存 {mb} MB", mb=env["memory_mb"])))
    if parts:
        lines.append(str(tr("【环境】{items}", items=" · ".join(parts))))
    lines += [str(tr("【查找】用“#序号”或操作 ID 搜索 events.jsonl／readable.log；先后顺序不等于因果。")),
              str(tr("所有文件只在本机生成，由用户自己发送。"))]
    return "\n".join(lines) + "\n"
