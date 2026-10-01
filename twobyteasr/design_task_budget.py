"""One absolute deadline and recovery allowance for a whole design task."""
import threading
import time


class DesignTaskBudget:
    def __init__(self, seconds, max_repairs=2, *, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + max(0., seconds)
        self.max_repairs = max(0, min(2, int(max_repairs)))
        self.repairs = []
        self.lock = threading.RLock()

    def remaining(self):
        return max(0., self.deadline - self.clock())

    def check(self, cancel_check=None):
        from .ai_providers import AIProviderError
        if cancel_check and cancel_check():
            raise AIProviderError('字幕生成已取消；已有产物已保留', category='cancelled')
        if self.remaining() <= 0:
            raise AIProviderError('任务总预算已耗尽；已有产物已保留', category='provider_total_timeout')

    def reserve(self, reason, *, candidate_id=None, cancel_check=None):
        from .ai_providers import AIProviderError
        with self.lock:
            self.check(cancel_check)
            if len(self.repairs) >= self.max_repairs:
                raise AIProviderError('自动恢复次数已用完；已有版本与错误已保留', category='repair_budget_exhausted')
            row = dict(attempt=len(self.repairs)+1, reason=str(reason)[:600],
                       candidate_id=candidate_id, elapsed_seconds=self.clock()-self.started)
            self.repairs.append(row)
            return dict(row)

    def snapshot(self):
        with self.lock:
            return dict(task_started_monotonic=self.started, total_seconds=self.deadline-self.started,
                        remaining_seconds=self.remaining(), repairs_used=len(self.repairs),
                        max_repairs=self.max_repairs, attempts=[dict(r) for r in self.repairs])


def transport_retry_delay(error, used=0):
    """Explicit transient errors only; a quiet connection is not an error."""
    category = getattr(error, 'category', '')
    if category not in {'transport_error', 'connection', 'server_error', 'transient',
                        'rate_limit', 'rate_limited', 'connect_timeout', 'read_idle_timeout'}:
        return None
    # Retry-After is a minimum, including waits beyond the task budget.
    return max(min(8., 2. ** used), float(getattr(error, 'retry_after_seconds', 0) or 0))


def wait_for_retry(seconds, budget, cancel_check):
    stop = budget.clock() + seconds
    while budget.clock() < stop:
        budget.check(cancel_check)
        time.sleep(min(.1, stop-budget.clock()))
    budget.check(cancel_check)
