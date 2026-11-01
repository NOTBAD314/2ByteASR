"""Observable work items, including work outside legacy numbered stages."""
from __future__ import annotations

import time
import contextvars
from contextlib import contextmanager

_PHASE=contextvars.ContextVar('2byteasr_pipeline_phase',default='')


def current_phase():return _PHASE.get()


@contextmanager
def work(legacy, key, label, *, total=0, **details):
    from .run_context import get_runtime_context
    context = get_runtime_context()
    work_id = f'{getattr(context, "shard_id", "") or "media"}:{key}'
    started = time.perf_counter()
    token=_PHASE.set(key)
    last = {'state': 'running'}

    def report(done=0, state='running', **values):
        last['state'] = state
        legacy.record_run_event('pipeline_work_progress', work_id=work_id, label=label,
            state=state, done=int(done), total=int(total),phase=key,
            elapsed_seconds=round(time.perf_counter()-started,3),
            **dict(details, **values))
    report()
    try:
        yield report
    except BaseException as exc:
        report(state='cancelled' if exc.__class__.__name__ == 'CancelledError' else 'failed',
               error_type=type(exc).__name__)
        raise
    else:
        if last['state'] in {'running', 'queued', 'retry'}:
            report(total, 'completed')
    finally:
        _PHASE.reset(token)
