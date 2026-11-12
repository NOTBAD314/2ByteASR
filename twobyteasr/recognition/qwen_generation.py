"""Bound one retry using measured termination, never inferred text length."""
import math


def retry_token_budget(seconds, previous, *, ceiling=1024):
    # Only called after a measured limit hit. Japanese output can contain
    # several tokens per spoken word; keep the retry bounded and per-window.
    return min(ceiling, max(int(previous)*2, int(previous)+64, math.ceil(max(0,seconds)*12)+32))


def generation_measure(ids, *, eos_ids, limit, input_tokens):
    eos=set(eos_ids if isinstance(eos_ids,(tuple,list,set)) else [eos_ids])-{None}
    stop=next((i for i,token in enumerate(ids) if token in eos),None)
    count=stop+1 if stop is not None else len(ids)
    hit=stop is None and count>=limit
    return dict(output_tokens=count,input_tokens=int(input_tokens),max_new_tokens=int(limit),
        eos_observed=stop is not None,token_limit_reached=hit,
        stop_reason='eos' if stop is not None else 'max_new_tokens' if hit else 'other_stop')
