"""A finite endpoint recovery budget per project session or explicit retry."""
from dataclasses import dataclass


@dataclass
class EndpointRecovery:
    attempts: int = 0
    next_attempt_at: float = 0.
    maximum: int = 3

    def begin(self, now):
        if self.attempts >= self.maximum:
            return False, 'exhausted'
        if now < self.next_attempt_at:
            return False, 'backoff'
        self.attempts += 1
        self.next_attempt_at = now + (0.5, 2., 8.)[min(self.attempts-1, 2)]
        return True, 'starting'

    def reset(self):
        self.attempts = 0
        self.next_attempt_at = 0.
