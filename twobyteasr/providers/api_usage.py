"""Provider-reported API usage, per call and summed per step and task (2026-10-15).

Only numbers a provider returned are counted. A call whose response carried no
usage object is counted as "未返回用量"; nothing is estimated from characters.
Each dispatched HTTP attempt is recorded. Missing usage is unknown, including
cancelled or interrupted requests; it is never evidence of zero billing.

Imports only the standard library at module level: the cloud ASR worker
process records usage too.
"""
from __future__ import annotations

FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "uncached_input_tokens", "reasoning_tokens",
          "total_tokens", "audio_seconds")

# Field -> where providers put it. The first path present wins; the
# normalized names come first so normalizing twice changes nothing.
_PATHS = {
    "input_tokens": ("input_tokens", "prompt_tokens", "promptTokenCount", "prompt_token_count"),
    "output_tokens": ("output_tokens", "completion_tokens", "candidatesTokenCount",
                      "candidates_token_count"),
    # DeepSeek repeats its cache hits as prompt_tokens_details.cached_tokens.
    "cached_input_tokens": ("cached_input_tokens", "prompt_cache_hit_tokens",
                            "prompt_tokens_details.cached_tokens", "input_tokens_details.cached_tokens",
                            "cache_read_input_tokens", "cachedContentTokenCount"),
    "reasoning_tokens": ("reasoning_tokens", "completion_tokens_details.reasoning_tokens",
                         "output_tokens_details.reasoning_tokens", "thoughtsTokenCount"),
    "uncached_input_tokens": ("uncached_input_tokens", "prompt_cache_miss_tokens"),
    "total_tokens": ("total_tokens", "totalTokenCount"),
    # Duration-billed speech APIs: OpenAI {"type": "duration", "seconds": n},
    # DashScope ASR {"seconds": n}, DashScope file transcription {"duration": n}.
    "audio_seconds": ("audio_seconds", "seconds", "duration"),
}


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    import math
    if not math.isfinite(value) or value < 0:
        return None
    return int(value) if float(value).is_integer() else float(value)


def _lookup(mapping, path):
    value = mapping
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return _count(value)


def normalize_usage(usage):
    """One provider usage object -> the counted fields, or None when it has none."""
    if not isinstance(usage, dict):
        return None
    counted = {}
    for field, paths in _PATHS.items():
        for path in paths:
            value = _lookup(usage, path)
            if value is not None:
                counted[field] = value
                break
    # Anthropic-style usage reports cache reads and writes beside input_tokens;
    # elsewhere cached tokens are part of the input count.
    if "prompt_tokens" not in usage and "cached_input_tokens" not in usage:
        extra = sum(_count(usage.get(key)) or 0 for key in ("cache_read_input_tokens",
                                                            "cache_creation_input_tokens"))
        if extra and "input_tokens" in counted:
            counted["input_tokens"] += extra
    return counted or None


def call_payload(*, stage, provider="", model="", usage=None, request_mode="", batch_index=None,
                 request_id='', status='', estimated_cost=None):
    """The ``api_usage`` run event for one answered request."""
    counted = normalize_usage(usage)
    payload = dict(stage=str(stage or "unknown"), provider=str(provider or ""), model=str(model or ""),
                   request_mode=str(request_mode or ""), reported=counted is not None, **(counted or {}))
    if batch_index is not None:
        payload["batch_index"] = batch_index
    if request_id:
        payload['request_id'] = request_id
    if status:
        payload['status'] = status
    if estimated_cost is not None:
        payload['estimated_cost'] = estimated_cost
    return payload


def record_api_call(**kwargs):
    """Emit one ``api_usage`` event; usage accounting never breaks a request."""
    try:
        payload = call_payload(**kwargs)
        import sys
        core = sys.modules.get("subtitle_core")
        recorder = getattr(core, "record_run_event", None) if core is not None else None
        if not callable(recorder):
            from ..recognition.cache import record_run_event as recorder
        recorder("api_usage", **payload)
    except Exception:
        pass


class UsageTotals:
    """Running sum of ``api_usage`` events."""

    def __init__(self):
        self.calls = 0
        self.reported_calls = 0
        self.values = {}
        self._requests = {}
        self.costs = {}
        self.cost_unknown_calls = 0
        self.has_costs = False

    def add(self, payload):
        payload = payload or {}
        request_id = payload.get('request_id')
        if request_id and request_id in self._requests:
            previous = self._requests[request_id]
            if previous.get('reported') and not payload.get('reported'):
                return self
            rows = dict(self._requests)
            rows[request_id] = dict(payload)
            self.__init__()
            for row in rows.values():
                self.add(row)
            return self
        self._requests[request_id or f'legacy-{self.calls}'] = dict(payload)
        self.calls += 1
        if 'estimated_cost' in payload:
            from decimal import Decimal
            self.has_costs = True
            cost = payload['estimated_cost']
            if cost.get('known'):
                totals = self.costs.setdefault(cost['currency'], [Decimal(0), Decimal(0)])
                totals[0] += Decimal(cost['low']); totals[1] += Decimal(cost['high'])
            else:
                self.cost_unknown_calls += 1
        if not payload.get("reported"):
            return self
        self.reported_calls += 1
        for field in FIELDS:
            value = _count(payload.get(field))
            if value is not None:
                self.values[field] = self.values.get(field, 0) + value
        return self

    @property
    def unreported_calls(self):
        return self.calls - self.reported_calls

    def to_dict(self):
        result = dict(calls=self.calls, reported_calls=self.reported_calls,
                      unreported_calls=self.unreported_calls, **self.values)
        if self.has_costs:
            result.update(estimated_costs={key:[str(x) for x in value] for key,value in self.costs.items()},
                          cost_unknown_calls=self.cost_unknown_calls)
        return result

    @classmethod
    def from_events(cls, events):
        totals = cls()
        for event in events:
            totals.add(event)
        return totals


def summarize(events, step_of=None):
    """Report section: totals, per step, per API stage and per provider/model."""
    events = [dict(event) for event in events]
    total = UsageTotals.from_events(events)
    groups = {"steps": {}, "api_stages": {}, "models": {}}
    for event in events:
        keys = {"steps": step_of(event) if step_of else event.get("step_label"),
                "api_stages": event.get("stage"),
                "models": "/".join(part for part in (event.get("provider"), event.get("model")) if part)}
        for group, key in keys.items():
            if key:
                groups[group].setdefault(str(key), UsageTotals()).add(event)
    return dict(total.to_dict(), **{group: {key: value.to_dict() for key, value in rows.items()}
                                    for group, rows in groups.items()})


def _number(value):
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def usage_text(totals, *, plain=False):
    """Words for a ``UsageTotals`` (or its dict); '' when no call was made.

    ``plain`` gives the Chinese source text (task report) instead of a
    translated UI value.
    """
    if plain:
        def say(source, **arguments):
            return source.format(**arguments)
    else:
        from ..i18n import tr as say
    data = totals if isinstance(totals, dict) else totals.to_dict()
    calls = int(data.get("calls") or 0)
    if not calls:
        return ""
    reported = int(data.get("reported_calls") or 0)
    if not reported:
        return say("未返回用量（{count} 次调用）", count=calls)
    parts = []
    if "input_tokens" in data or "output_tokens" in data:
        cached = data.get("cached_input_tokens") or 0
        parts.append(say("输入 {input}（缓存命中 {cached}）", input=_number(data.get("input_tokens") or 0),
                         cached=_number(cached)) if cached
                     else say("输入 {input}", input=_number(data.get("input_tokens") or 0)))
        parts.append(say("输出 {output} tokens", output=_number(data.get("output_tokens") or 0)))
    if data.get("audio_seconds"):
        parts.append(say("音频 {seconds} 秒", seconds=_number(data["audio_seconds"])))
    if not parts:
        # Reported, but only fields shown nowhere above (e.g. reasoning only).
        parts.append(say("总计 {total} tokens", total=_number(data.get("total_tokens") or 0)))
    unreported = int(data.get("unreported_calls") or calls - reported)
    if unreported:
        parts.append(say("{count} 次未返回用量", count=unreported))
    for currency, amounts in data.get('estimated_costs', {}).items():
        low, high = amounts
        parts.append(say('估算费用 {currency} {amount}', currency=currency,
                         amount=low if low == high else f'{low}–{high}'))
    if data.get('cost_unknown_calls'):
        parts.append(say('{count} 次费用未知', count=data['cost_unknown_calls']))
    if plain:
        return " · ".join(parts)
    from ..i18n import join_text
    return join_text(parts)
