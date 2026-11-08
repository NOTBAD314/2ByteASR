"""Budgeted request-only source slices and bounded local quality retries."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
import threading
import time

from .grouping_quality import SourceIndex


def context_text(context, side):
    value = (context or {}).get(side, "")
    if isinstance(value,list):
        value = "".join(str(row.get("text", "")) for row in value)
    return str(value)[-96:] if side=="before" else str(value)[:96]


class QualityRetryBudget:
    """Shared by all batches/children in one grouping operation."""

    def __init__(self, *, requests=2, tokens=4096, seconds=12., clock=time.monotonic):
        self.requests = requests
        self.tokens = tokens
        self.seconds = seconds
        self.clock = clock
        self.started = None
        self.lock = threading.Lock()

    def take(self, max_tokens):
        with self.lock:
            now = self.clock()
            if self.started is None:
                self.started = now
            remaining = self.seconds-(now-self.started)
            reserve = min(2048, max_tokens, self.tokens)
            if self.requests <= 0 or reserve <= 0 or remaining <= .1:
                return None
            self.requests -= 1
            self.tokens -= reserve
            return reserve, min(6., remaining)


def retry_quality_windows(quality, original, local, *, provider, snapshot, schema,
                          budget, record, batch_index=None, source_spans=(), cancel_check=lambda: False):
    """One try per small failed neighbourhood, with immutable read-only context."""
    from .grouping_contract import parse_grouping_response
    from ..providers.provider_input_budget import prepare_input, InputBudgetError
    from ..providers.asr_provider_snapshot import classify_request_error
    from ..recognition.service import CancelledError
    result = list(local)
    issues = quality.inspect(original)
    edges = [0, *original]
    covered = []
    correction_number = 0
    for issue in issues:
        position = issue["start"]
        if any(left <= position < right for left,right in covered):
            continue
        centre = max(0, next((i for i,x in enumerate(edges) if x >= position), len(edges)-1)-1)
        left, right = edges[max(0,centre-1)], edges[min(len(edges)-1,centre+3)]
        # A single pathological source/model span can itself be huge. Only
        # neighbouring legal word edges within 192 countable units are owned.
        if right-left > 192:
            choices = [x for x in quality.allowed if left < x <= left+192]
            right = choices[-1] if choices else min(right, left+192)
        if left not in {0,*result} or right not in result:
            # Keep the already accepted outer boundaries immutable.
            left = max((x for x in [0,*result] if x <= left), default=0)
            right = min((x for x in result if x >= right), default=quality.total)
        if right-left > 224 or right <= left:
            continue
        reservation = budget.take(snapshot.max_output_tokens)
        if reservation is None:
            break
        max_tokens, timeout = reservation
        covered.append((left,right))
        correction_number += 1
        retry_batch_id = f"{batch_index}.quality-{correction_number}"
        if cancel_check():
            raise CancelledError("断句纠错已取消。")
        body = dict(source_text=quality.index.slice(left,right), total_length=right-left,
            index_unit="content_exact_unicode_codepoints", body_range=[left,right],
            read_only_context=dict(before=quality.index.slice(max(0,left-32),left),
                                   after=quality.index.slice(right,min(quality.total,right+32))),
            allowed_boundaries=[x-left for x in quality.allowed if left < x <= right],
            required_boundaries=sorted(x-left for x in quality.required | quality.semantic_required | quality.stable_boundaries if left < x < right),
            illegal_positions=[x-left for x in original if left < x < right and x in quality.forbidden],
            failed_constraints=[dict(x,start=x["start"]-left,end=min(right,x["end"])-left)
                                for x in issues if left <= x["start"] < right],
            max_characters=quality.max_chars,
            current_boundaries=[x-left for x in result if left < x <= right])
        body["source_spans"] = [dict(
            source_id=span.get("source_mapping",{}).get("source_id",span["id"]),
            speaker=span["speaker"], time_domain="source_seconds",
            source_start=span["start"], source_end=span["end"],
            content_start=max(left,span["content_start"])-left,
            content_end=min(right,span["content_end"])-left,
            global_content_start=span["global_content_start"]+max(0,left-span["content_start"]),
            global_content_end=span["global_content_start"]+min(right,span["content_end"])-span["content_start"])
            for span in source_spans if span["content_start"] < right and left < span["content_end"]]
        messages = [dict(role="system", content=(
            "只纠正本次正文范围的字幕断点。source_text不可改写，邻文只读。只返回JSON对象"
            '{"boundaries":[整数]}。断点仅从allowed_boundaries选择，严格递增并以total_length结束，'
            "保留required_boundaries。不能采用illegal_positions或违反长度、词语和关联词归属。")),
            dict(role="user",content=json.dumps(body,ensure_ascii=False,separators=(",",":")))]
        started = time.perf_counter()
        category, accepted, response = "semantic_quality", False, ""
        candidate = []
        diagnostics = {}
        dispatched = False
        try:
            prepare_input(messages, schema=schema, max_tokens=max_tokens, operation="group")
            policy = replace(snapshot.timeout_policy, connect=min(timeout,snapshot.timeout_policy.connect),
                read_idle=min(timeout,snapshot.timeout_policy.read_idle), total=timeout,
                queue=min(timeout,snapshot.timeout_policy.queue))
            dispatched = True
            response = provider.complete(messages, stage="grouped", operation_kind="group",
                batch_index=retry_batch_id, max_tokens=max_tokens, temperature=0.,
                timeout=timeout, _timeout_policy=policy, request_diagnostics=diagnostics,
                cancel_check=cancel_check, enable_thinking=snapshot.enable_thinking,
                thinking_protocol=snapshot.thinking_protocol, response_format={"type":"json_object"},
                json_schema=schema, structured_retry_system_prompt=None, structured_retry_max_tokens=())
            cuts, _ = parse_grouping_response(response, body["source_text"])
            candidate = sorted({x for x in result if not left < x <= right} | {left+x for x in cuts})
            accepted, category = quality.accept_change(result,candidate)
            local_issues = [x for x in quality.inspect(candidate) if left <= x["start"] < right]
            if local_issues:
                accepted, category = False, "semantic_or_length_quality"
            if accepted:
                result = candidate
        except Exception as exc:
            category = "input_budget_conflict" if isinstance(exc,InputBudgetError) else classify_request_error(exc)
            if category == "cancelled" or isinstance(exc,CancelledError):
                raise
        record("grouping_quality_retry", batch_index=batch_index,rule="bounded_ai_quality_correction",
            retry_batch_id=retry_batch_id,parent_batch_id=batch_index,request_dispatched=dispatched,
            content_start=left, content_end=right, original_boundaries=body["current_boundaries"],
            candidate_boundaries=[x-left for x in candidate if left < x <= right],
            old_positions=[left+x for x in body["current_boundaries"]],
            new_positions=[x for x in candidate if left < x <= right],
            before=SourceIndex.build(body["source_text"]).pieces(body["current_boundaries"]),
            after=[quality.index.slice(a,b) for a,b in zip([left,*[x for x in candidate if left < x <= right]],
                [x for x in candidate if left < x <= right])],
            accepted=accepted, reason=category, output_token_reserve=max_tokens,
            elapsed_ms=round((time.perf_counter()-started)*1000,3),
            response_length=len(response), finish_reason=diagnostics.get("finish_reason"),
            completion_tokens=diagnostics.get("completion_tokens"))
    return result


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
