"""Budgeted request-only source slices and bounded local quality retries."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import threading
import time
from collections import Counter

from .grouping_quality import SourceIndex


def context_text(context, side):
    value = (context or {}).get(side, "")
    if isinstance(value,list):
        value = "".join(str(row.get("text", "")) for row in value)
    return str(value)[-96:] if side=="before" else str(value)[:96]


class QualityRetryBudget:
    """Correction allowance shared by all batches/children in one grouping run.

    2026-11-18: the allowance used to be taken in batch order (a later batch
    waited for every earlier one), so the first batches spent all 16 requests
    and the second half of a long video went straight to local fallback. Each
    batch now has its own fair share of the task allowance, computed from the
    registered batch count, and every request carries all of that batch's
    failed windows. Grants depend only on the batch's own use, so the result
    does not depend on thread completion order. Totals stay capped.
    """

    MIN_SHARE = 2       # first window request plus one feedback round
    MAX_SHARE = 4       # a short task with one batch never needs more
    MAX_REQUESTS = 64   # absolute ceiling, independent of task length
    RESERVE_CAP = 1024  # output tokens reserved for one multi-window request

    def __init__(self, *, requests=16, tokens=4096, seconds=90., clock=time.monotonic):
        self.base_requests = int(requests)
        self.base_tokens = int(tokens)
        self.seconds = seconds
        self.clock = clock
        self.started = None
        self.lock = threading.Lock()
        self.order = threading.Condition(self.lock)
        self.pending_batches = set()
        self.registered = set()
        self.used = Counter()
        self.requests_used = 0
        self.tokens_reserved = 0
        self.tokens_used = 0
        self.outcomes = Counter()

    # Limits are derived from the registered batches; a direct caller that
    # never registers is one batch.
    def _batches(self):
        return max(1, len(self.registered))

    @property
    def requests(self):
        base = self.base_requests
        if base <= 0:
            return 0
        if base < self.MIN_SHARE:
            return base
        return min(self.MAX_REQUESTS, max(base, self.MIN_SHARE*self._batches()))

    @property
    def tokens(self):
        return max(self.base_tokens, 256*self.requests) if self.base_tokens > 0 else 0

    def share(self):
        total = self.requests
        if total <= 0:
            return 0
        return max(1, min(self.MAX_SHARE, total//self._batches()))

    def record_outcome(self,outcome):
        with self.lock:
            self.outcomes[outcome]+=1

    def summary(self):
        with self.lock:
            result = dict(self.outcomes)
            result.update(requests_used=self.requests_used, requests_allowed=self.requests,
                          batch_share=self.share(), output_tokens_reserved=self.tokens_reserved,
                          output_tokens_used=self.tokens_used)
            return result

    def register_batches(self, indices):
        with self.order:
            indices = set(indices)
            self.pending_batches.update(indices)
            self.registered.update(indices)

    def finish_batch(self, index):
        with self.order:
            self.pending_batches.discard(index)
            self.order.notify_all()

    def take(self, max_tokens, batch_index=None, *, windows=1):
        """Reserve one request for ``batch_index``; None when nothing is left.

        Returns (output_token_reserve, timeout_seconds). The reason for a
        refusal is in ``refusal_reason(batch_index)``.
        """
        first = str(batch_index).split('.')[0]
        key = first if batch_index is not None else '_'
        with self.lock:
            now = self.clock()
            if self.started is None:
                self.started = now
            remaining = self.seconds-(now-self.started)
            wanted = max(256, 64+48*max(1, int(windows)))
            reserve = min(self.RESERVE_CAP, wanted, int(max_tokens), self.tokens-self.tokens_reserved)
            if (self.used[key] >= self.share() or self.requests_used >= self.requests
                    or reserve <= 0 or remaining <= .1):
                return None
            self.used[key] += 1
            self.requests_used += 1
            self.tokens_reserved += reserve
            return reserve, min(6.+1.5*max(1, int(windows)), 24., remaining)

    def settle(self, reserve, used):
        """Return the unused part of a reservation (reserve vs actual use)."""
        with self.lock:
            used = max(0, min(int(reserve), int(used or 0)))
            self.tokens_used += used
            self.tokens_reserved -= int(reserve)-used

    def refusal_reason(self, batch_index=None):
        first = str(batch_index).split('.')[0]
        key = first if batch_index is not None else '_'
        with self.lock:
            if self.requests <= 0:
                return 'retry_disabled'
            if self.used[key] >= self.share():
                return 'batch_share_used'
            if self.requests_used >= self.requests:
                return 'task_request_limit'
            if self.started is not None and self.seconds-(self.clock()-self.started) <= .1:
                return 'task_time_limit'
            return 'task_token_limit'


# Statuses recorded for each owned window (grouping_quality_retry.status and
# the fallback receipt's reason); a window that never got a request is not
# reported as an exhausted retry.
RETRY_STATUSES = ('not_allocated', 'input_budget_conflict', 'request_failed', 'no_answer',
                  'rejected_by_gate', 'unchanged_with_violations', 'unchanged', 'improved')
MAX_WINDOWS_PER_REQUEST = 12


def owned_windows(quality, boundaries, *, advisory=True):
    """Failed neighbourhoods with immutable outer edges, as retry owns them."""
    from .ai_boundary_policy import windows
    result = []
    for left, right in windows(quality, boundaries, advisory=advisory):
        # A single pathological source/model span can itself be huge. Only
        # neighbouring legal word edges within 192 countable units are owned.
        if right-left > 192:
            choices = [x for x in quality.allowed if left < x <= left+192]
            right = choices[-1] if choices else min(right, left+192)
        if left not in {0, *boundaries} or right not in boundaries:
            # Keep the already accepted outer boundaries immutable.
            left = max((x for x in [0, *boundaries] if x <= left), default=0)
            right = min((x for x in boundaries if x >= right), default=quality.total)
        if right-left > 224 or right <= left:
            continue
        if result and left < result[-1][1]:
            result[-1] = (result[-1][0], max(right, result[-1][1]))
        else:
            result.append((left, right))
    return result


def _window_body(quality, result, original, left, right, number):
    from .ai_boundary_policy import inspect
    current_issues = inspect(quality, result, advisory=True)
    return dict(id=number, source_text=quality.index.slice(left,right), total_length=right-left,
        body_range=[left,right],
        read_only_context=dict(before=quality.index.slice(max(0,left-32),left),
                               after=quality.index.slice(right,min(quality.total,right+32))),
        allowed_boundaries=[x-left for x in quality.allowed if left < x <= right],
        required_boundaries=sorted(x-left for x in quality.required if left < x < right),
        preferred_boundaries=sorted(x-left for x in quality.semantic_required if left < x < right),
        illegal_positions=[x-left for x in result if left < x < right and x in quality.forbidden],
        failed_constraints=[dict(x,start=x["start"]-left,end=min(right,x["end"])-left)
                            for x in current_issues if left <= x["start"] < right],
        current_boundaries=[x-left for x in result if left < x <= right],
        current_answer=[quality.index.slice(a,b) for a,b in zip([left,*[x for x in result if left < x < right]],
                                                                [*[x for x in result if left < x < right],right])],
        original_ai_boundaries=[x-left for x in original if left < x <= right])


def _parse_windows(response, bodies):
    """{"windows":[{"id":n,"boundaries":[...]}]} → {id: cuts}; bad rows drop."""
    from .grouping_contract import parse_grouping_response
    raw = str(response or "").lstrip("﻿").strip()
    fence = chr(96)*3
    if raw.startswith(fence) and raw.endswith(fence):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1])
    data = json.loads(raw)
    rows = data.get("windows") if isinstance(data, dict) else None
    if rows is None and isinstance(data, dict) and len(bodies) == 1 and "boundaries" in data:
        rows = [dict(id=bodies[0]["id"], boundaries=data["boundaries"])]
    answers, errors = {}, {}
    by_id = {body["id"]: body for body in bodies}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("id") not in by_id or row["id"] in answers:
            continue
        body = by_id[row["id"]]
        try:
            cuts, _ = parse_grouping_response(json.dumps(dict(boundaries=row.get("boundaries"))),
                                              body["source_text"])
            answers[row["id"]] = list(cuts)
        except Exception as exc:
            errors[row["id"]] = str(exc)[:200]
    return answers, errors


WINDOW_SCHEMA = {
    'type': 'object',
    'properties': {'windows': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'id': {'type': 'integer'}, 'boundaries': {'type': 'array', 'items': {'type': 'integer'}}},
        'required': ['id', 'boundaries']}}},
    'required': ['windows'],
}


DEPENDENT_OPENERS = frozenset('了的得地着过吗呢吧么嘛')


def correction_regression(quality, before, candidate, left, right):
    """Why a changed window answer is worse than the answer it replaces, or ''.

    2026-11-19 (reported job, 18 corrections all logged "improved"): the gate
    only compared issue counts, so answers that fixed one flagged edge while
    opening a line with a particle (可以翻｜了一千二, 弱兵｜的花衣蝶,
    那不对｜了没事) or turning two lines into five (但是圣剑｜一个涅河｜拖拉机…)
    replaced acceptable model lines. A correction may not open a line with
    such a particle, and may not split the window into more than one extra
    line beyond what its length requires.
    """
    old = {x for x in before if left < x < right}
    new = {x for x in candidate if left < x < right}
    added = new-set(getattr(quality, 'required', ()))-old
    content = quality.index.content
    # Only a line opening with a particle that completes the previous words.
    # Local word/POS sets are not used here: they also flag real fixes
    # (都一直在更新｜记得在主页…, 快速移动｜到上一条…). 的确, 地刺 and 过来
    # open words of their own and stay allowed.
    if any(x < len(content) and content[x] in DEPENDENT_OPENERS and x in quality.awkward
           and x+1 not in getattr(quality, 'known_word_interiors', ())
           for x in added):
        return 'new_syntactic_damage'
    needed = -(-(right-left)//max(1, int(quality.max_chars)))
    if len(new)+1 > max(len(old)+1, needed)+1:
        return 'over_fragmented'
    return ''


def retry_quality_windows(quality, original, local, *, provider, snapshot, schema,
                          budget, record, batch_index=None, source_spans=(), cancel_check=lambda: False,
                          receipts=None, statuses=None):
    """Correct every failed neighbourhood of one batch in as few requests as possible.

    All failed windows of the batch go into one request (split only when the
    request exceeds MAX_WINDOWS_PER_REQUEST or the input budget). A second
    round, within the batch's fair share, sends the windows still failing
    back with the updated constraints. Text outside each window is read-only.
    ``statuses`` (optional dict) receives {(left, right): status}.
    """
    from ..providers.provider_input_budget import prepare_input, InputBudgetError
    from ..providers.asr_provider_snapshot import classify_request_error
    from ..recognition.service import CancelledError
    from .ai_boundary_policy import inspect, HARD_KINDS
    result = list(local)
    statuses = {} if statuses is None else statuses
    request_number = 0
    exhausted = False
    for round_number in (1, 2):
        targets = [w for w in owned_windows(quality, result)
                   if statuses.get(w) not in {'not_allocated', 'input_budget_conflict'}]
        if round_number == 2:
            # Only windows whose first answer was rejected or still failing.
            targets = [w for w in targets if statuses.get(w) in {
                'rejected_by_gate', 'unchanged_with_violations', 'no_answer', 'request_failed'}]
        if not targets or exhausted:
            break
        groups = [targets[i:i+MAX_WINDOWS_PER_REQUEST]
                  for i in range(0, len(targets), MAX_WINDOWS_PER_REQUEST)]
        while groups:
            group = groups.pop(0)
            bodies = [_window_body(quality, result, original, left, right, number)
                      for number, (left, right) in enumerate(group, 1)]
            request = dict(index_unit="content_exact_unicode_codepoints",
                           max_characters=quality.max_chars, round=round_number, windows=bodies)
            messages = [dict(role="system", content=(
                "只纠正每个window正文范围内的字幕断点。source_text不可改写，邻文只读。"
                '只返回JSON对象{"windows":[{"id":整数,"boundaries":[整数]}]}，每个window一项。'
                "boundaries相对该window的source_text，严格递增并以total_length结束，"
                "只从allowed_boundaries选择，保留required_boundaries，不采用illegal_positions。"
                "failed_constraints是当前断点的问题：length超长必须重分；semantic_boundary是词语或依附结构被切开；"
                "dependent_tail是依附前句的短尾巴。"
                f"每条{quality.max_chars}个可计数字符以内，是上限不是目标。"
                "按完整意群选点：不拆词和固定短语，不把动词的宾语、量词后的名词、方位数量短语"
                "（上一条）或连词谓语留到下一条，也不把下一句的开头词挂在上一条末尾。"
                "逗号、连接词和短气口不单独触发切分。current_answer是当前结果，可整体重排本window内的断点。")),
                dict(role="user", content=json.dumps(request, ensure_ascii=False, separators=(",",":")))]
            try:
                prepare_input(messages, schema=WINDOW_SCHEMA, max_tokens=QualityRetryBudget.RESERVE_CAP,
                              operation="group")
            except InputBudgetError:
                if len(group) > 1:
                    half = len(group)//2
                    groups[:0] = [group[:half], group[half:]]
                    continue
                statuses[group[0]] = 'input_budget_conflict'
                _record_window(record, budget, batch_index, f"{batch_index}.quality-input", group[0],
                               bodies[0], result, result, quality, 'input_budget_conflict',
                               dispatched=False, round_number=round_number)
                continue
            reservation = budget.take(snapshot.max_output_tokens, batch_index=batch_index, windows=len(group))
            if reservation is None:
                reason = budget.refusal_reason(batch_index)
                for window, body in zip(group, bodies):
                    if statuses.get(window) is None:
                        statuses[window] = 'not_allocated'
                    _record_window(record, budget, batch_index, None, window, body, result, result,
                                   quality, statuses[window], dispatched=False, round_number=round_number,
                                   refusal=reason)
                for later in groups:
                    for window in later:
                        statuses.setdefault(window, 'not_allocated')
                exhausted = True
                break
            max_tokens, timeout = reservation
            request_number += 1
            retry_batch_id = f"{batch_index}.quality-{request_number}"
            if cancel_check():
                raise CancelledError("断句纠错已取消。")
            started = time.perf_counter()
            diagnostics, response, answers, errors = {}, "", {}, {}
            failure = None
            record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}', label='断句：局部重试',
                   phase='grouping_quality_retry', state='running', done=0, total=1, batch_index=batch_index)
            try:
                policy = replace(snapshot.timeout_policy, connect=min(timeout,snapshot.timeout_policy.connect),
                    read_idle=min(timeout,snapshot.timeout_policy.read_idle), total=timeout,
                    queue=min(timeout,snapshot.timeout_policy.queue))
                response = provider.complete(messages, stage="grouped", operation_kind="group",
                    batch_index=retry_batch_id, max_tokens=max_tokens, temperature=0.,
                    timeout=timeout, _timeout_policy=policy, request_diagnostics=diagnostics,
                    cancel_check=cancel_check, enable_thinking=snapshot.enable_thinking,
                    thinking_protocol=snapshot.thinking_protocol, response_format={"type":"json_object"},
                    json_schema=WINDOW_SCHEMA, structured_retry_system_prompt=None,
                    structured_retry_max_tokens=())
                answers, errors = _parse_windows(response, bodies)
            except Exception as exc:
                from ..providers.provider_diagnostics import redact_diagnostics
                diagnostics['error'] = redact_diagnostics(str(exc))
                failure = classify_request_error(exc) if not isinstance(exc, (ValueError, TypeError)) else 'parse_failure'
                if failure == "cancelled" or isinstance(exc, CancelledError):
                    record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}',
                           label='断句：局部重试已取消', phase='grouping_quality_retry', state='cancelled',
                           done=0, total=1, batch_index=batch_index)
                    raise
            finally:
                budget.settle(max_tokens, diagnostics.get("completion_tokens") or max_tokens)
            improved_any = False
            for window, body in zip(group, bodies):
                left, right = window
                before = list(result)
                cuts = answers.get(body["id"])
                if failure is not None:
                    status, reason = 'request_failed', failure
                elif cuts is None:
                    status, reason = 'no_answer', errors.get(body["id"], 'window_missing_in_response')
                else:
                    candidate = sorted({x for x in result if not left < x <= right} | {left+x for x in cuts})
                    local_issues = [x for x in inspect(quality, candidate, advisory=True)
                                    if left <= x["start"] < right]
                    hard_issues = [x for x in inspect(quality, candidate) if left <= x["start"] < right]
                    old_issues = [x for x in inspect(quality, result, advisory=True) if left <= x["start"] < right]
                    regression = correction_regression(quality, result, candidate, left, right)
                    if candidate == result:
                        status = 'unchanged_with_violations' if local_issues else 'unchanged'
                        reason = status
                    elif hard_issues or (len(local_issues) > len(old_issues)
                                         and not any(x['kind'] in HARD_KINDS for x in old_issues)):
                        # A changed answer must pass the hard gate and may not
                        # add advisory risks (POS tags can be wrong: 更新/d).
                        status, reason = 'rejected_by_gate', 'semantic_or_length_quality'
                    elif regression:
                        status, reason = 'rejected_by_gate', regression
                    else:
                        status, reason = 'improved', 'quality_improved'
                        result = candidate
                        improved_any = True
                        if receipts is not None:
                            receipts.append(dict(content_start=left, content_end=right,
                                origin='ai_targeted_correction',
                                before=[x for x in before if left < x <= right],
                                after=[x for x in candidate if left < x <= right],
                                retry_batch_id=retry_batch_id))
                statuses[window] = status
                _record_window(record, budget, batch_index, retry_batch_id, window, body, before, result,
                               quality, status, dispatched=True, round_number=round_number, reason=reason,
                               elapsed=time.perf_counter()-started, response=response, diagnostics=diagnostics,
                               reserve=max_tokens, candidate=None if cuts is None else
                               sorted({x for x in before if not left < x <= right} | {left+x for x in cuts}))
            record('pipeline_work_progress', work_id=f'grouped:{retry_batch_id}',
                   label='断句：局部重试有改善' if improved_any else '断句：局部重试未变化',
                   phase='grouping_quality_retry', state='completed', done=1, total=1,
                   batch_index=batch_index, windows=len(group),
                   review_required=bool(inspect(quality, result)), request_dispatched=True)
    return result


def _record_window(record, budget, batch_index, retry_batch_id, window, body, before, after, quality,
                   status, *, dispatched, round_number, reason=None, refusal=None, elapsed=0.,
                   response="", diagnostics=None, reserve=0, candidate=None):
    from .ai_boundary_policy import inspect
    left, right = window
    diagnostics = diagnostics or {}
    outcome = {'improved': 'improved', 'unchanged': 'unchanged',
               'unchanged_with_violations': 'unchanged_with_violations'}.get(status, 'rejected')
    if dispatched:
        budget.record_outcome(outcome)
    else:
        budget.record_outcome(status)
    candidate = before if candidate is None else candidate
    record("grouping_quality_retry", batch_index=batch_index, rule="bounded_ai_quality_correction",
        retry_batch_id=retry_batch_id, parent_batch_id=batch_index, request_dispatched=dispatched,
        round=round_number, window_id=body.get("id"), status=status, budget_refusal=refusal,
        content_start=left, content_end=right, original_boundaries=body["current_boundaries"],
        candidate_boundaries=[x-left for x in candidate if left < x <= right],
        old_positions=[x for x in before if left < x <= right],
        new_positions=[x for x in after if left < x <= right],
        before=list(body["current_answer"]),
        after=[quality.index.slice(a,b) for a,b in zip([left,*[x for x in after if left < x < right]],
               [*[x for x in after if left < x < right],right])],
        accepted=status == 'improved', improved=status == 'improved', outcome=outcome,
        review_required=bool([x for x in inspect(quality, after) if left <= x["start"] < right]),
        reason=reason or status, output_token_reserve=reserve,
        elapsed_ms=round(elapsed*1000,3), response_length=len(response or ""),
        finish_reason=diagnostics.get("finish_reason"), error=diagnostics.get('error'),
        completion_tokens=diagnostics.get("completion_tokens"))


def split_request_source(segment, build_messages, *, schema, max_tokens, tokens=(),
                         global_start=0, context_before="", context_after=""):
    """Slice a singleton only after its actual serialized request fails budget.

    Each child retains source identity, global countable and raw spans, words,
    speaker and source-seconds. Context is outside the owned body. The caller
    reconciles the request seams against the original full source afterwards.
    """
    from .grouping_quality import quality_for_segments
    from ..providers.provider_input_budget import prepare_input, InputBudgetError
    quality = quality_for_segments([segment],tokens)
    index = quality.index
    children = []
    start = 0

    def child_at(left,right):
        child = copy.copy(segment)
        child.caption_arbitration = dict(segment.caption_arbitration)
        child.segment_id = f"{segment.segment_id}@{left}:{right}"
        child.text = index.slice(left,right)
        child.start = max(segment.start, quality.units[left].start)
        child.end = min(segment.end, max(child.start+.001,quality.units[right-1].end))
        # Preserve existing valid observations, never manufacture word evidence
        # from the display estimates used to determine the coarse envelope.
        child.words = [w for w in child.words if child.start <= w.start < w.end <= child.end+.001]
        child.caption_arbitration["grouping_request_source"] = dict(
            source_id=segment.segment_id, content_start=left,content_end=right,
            global_content_start=global_start+left, global_content_end=global_start+right,
            raw_start=index.raw_edges[left],raw_end=index.raw_edges[right],
            source_start=segment.start,source_end=segment.end,
            original_text=segment.text, time_domain="source_seconds",
            index_unit="content_exact_unicode_codepoints")
        child.caption_arbitration["grouping_read_only_context"] = dict(
            before=(context_before+index.slice(max(0,left-32),left))[-96:],
            after=(index.slice(right,min(quality.total,right+32))+context_after)[:96])
        child.caption_arbitration["grouping_request_allowed"] = sorted({right-left} | {
            x-left for x in quality.allowed if left < x < right})
        return child

    while start < quality.total:
        low, high = start+1, quality.total
        fitting = start
        while low <= high:
            middle = (low+high)//2
            child = child_at(start,middle)
            try:
                prepare_input(build_messages([child]), schema=schema,
                              max_tokens=max_tokens, operation="group")
                fitting, low = middle, middle+1
            except InputBudgetError:
                high = middle-1
        if fitting <= start:
            raise ValueError("请求固定协议和最小正文仍超过输入预算。")
        legal = [x for x in quality.allowed if start < x <= fitting]
        if fitting == quality.total:
            end = fitting
        elif legal:
            # Prefer a nearby actual pause/phrase boundary, without allowing
            # an attractive distant pause to waste most of the request budget.
            near = [x for x in legal if x >= max(start+1,fitting-64)] or legal[-1:]
            end = max(near,key=lambda x:(quality.pauses.get(x,0.)*60+
                (8 if x in quality.restarts else 0)-(5 if x in quality.awkward else 0)-.1*(fitting-x)))
        else:
            # An indivisible name may exceed the request budget itself. It is
            # still submitted in owned request pieces; the seam is not adopted
            # as a subtitle cut and the final quality gate reports its conflict.
            end = fitting
        child = child_at(start,end)
        # Check again including the exact final context and mapping overhead.
        prepare_input(build_messages([child]),schema=schema,max_tokens=max_tokens,operation="group")
        children.append(child)
        start = end
    if "".join(c.text for c in children) != segment.text:
        raise ValueError("请求切块未完整重建原始正文。")
    return children
