"""One cancellable buffered-play intent, fenced by its media/clock owner."""
from dataclasses import dataclass


@dataclass
class PendingPlay:
    owner: tuple
    started: float
    deadline: float

    def decision(self, owner, now, *, ready=False, failure=False):
        if self.owner != owner:
            return 'cancelled'
        if failure:
            return 'failed'
        if ready:
            return 'ready'
        if now >= self.deadline:
            return 'timeout'
        return 'waiting'
