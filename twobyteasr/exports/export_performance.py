"""Low-frequency phase evidence; overlapping work is labelled, never subtracted."""
from contextlib import contextmanager
import time


@contextmanager
def export_phase(name, **details):
    from .export_run_log import current_export_log, note_export
    started = time.monotonic()
    note_export('phase_started', dict(name=name, **details))
    status = 'failed'
    try:
        yield
        status = 'finished'
    finally:
        value = dict(name=name, seconds=time.monotonic()-started, status=status, **details)
        logger = current_export_log()
        if logger is not None:
            logger.job.completion_metadata.setdefault('performance_phases', []).append(value)
        note_export('phase_finished', value)
