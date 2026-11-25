"""Task-wide and half-hour limits for automatic source repair."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import math
import time

SLICE_SECONDS = 1800
MAX_WINDOW_SECONDS = 10
CONTEXT_SECONDS = .35
PRESETS = {
    'normal': (8, 72, 180),
    'active': (16, 144, 360),
}


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    zone: int
    rows: tuple[int, ...]
    speaker: str


def plan_windows(rows, suspects, duration):
    """Merge compatible windows and visit every affected half hour in turn."""
    groups = defaultdict(list)
    for index in sorted(suspects, key=lambda number: (rows[number]['start'], number)):
        row = rows[index]
        start = max(0., float(row['start']) - CONTEXT_SECONDS)
        end = min(duration, float(row['end']) + CONTEXT_SECONDS)
        zone = int(float(row['start']) // SLICE_SECONDS)
        speaker = str(row.get('speaker') or '')
        bucket = groups[zone]
        if bucket and speaker == bucket[-1].speaker and start <= bucket[-1].end:
            previous = bucket[-1]
            if max(end, previous.end) - previous.start <= MAX_WINDOW_SECONDS:
                bucket[-1] = Window(previous.start, max(end, previous.end), zone, (*previous.rows, index), speaker)
                continue
        bucket.append(Window(start, end, zone, (index,), speaker))
    pending = deque(deque(group) for _, group in sorted(groups.items()))
    while pending:
        group = pending.popleft()
        yield group.popleft()
        if group:
            pending.append(group)


def _number(section, key, default, upper):
    value = section.get(key)
    if type(value) not in {float, int} or not math.isfinite(value) or value < 0:
        return default
    return min(value, upper)


class RepairBudget:
    def __init__(self, windows, duration, speech, section, *, quote=None, prior_cost_usd=0):
        self.profile = section.get('repair_profile') or 'normal'
        if self.profile not in {*PRESETS, 'custom'}:
            self.profile = 'normal'
        requests, audio, elapsed = PRESETS.get(self.profile, PRESETS['normal'])
        self.quote = quote
        cents = _number(section, 'repair_max_cost_cents', None, 1_000_000)
        self.cost_limit = cents / 100 if cents is not None else _number(section, 'repair_max_usd', None, 10_000)
        self.cost = max(0., float(prior_cost_usd))
        zones = Counter(window.zone for window in windows)
        active_zones = min(12, max(1, len(zones)))
        self.max_requests = min(192, requests * active_zones)
        self.max_audio = min(1728, audio * active_zones)
        if self.profile == 'custom':
            self.max_requests = int(_number(section, 'repair_max_requests', self.max_requests, 192))
            self.max_audio = _number(section, 'repair_max_audio_seconds', self.max_audio, 1728)
        self.max_elapsed = _number(section, 'repair_max_elapsed_seconds', min(1800, elapsed * active_zones), 86400)
        self.zone_limits = {}
        affected_totals = Counter()
        for window in windows:
            affected_totals[window.zone] += window.end - window.start
        for zone, count in zones.items():
            lo, hi = zone * SLICE_SECONDS, min(duration, (zone+1) * SLICE_SECONDS)
            voiced = sum(max(0., min(hi, float(row['end'])) - max(lo, float(row['start']))) for row in speech)
            affected = affected_totals[zone]
            cap = requests if duration <= SLICE_SECONDS else min(requests, max(2, math.ceil(voiced/240) + math.ceil(affected/20)))
            if self.profile == 'custom':
                cap = max(cap, math.ceil(self.max_requests / active_zones))
            self.zone_limits[zone] = (min(2 * count, cap), min(self.max_audio, max(audio, self.max_audio/active_zones)))
        self.requests = Counter()
        self.audio = Counter()
        self.repaired = Counter()
        self.elapsed = Counter()
        self.requests_by_backend = Counter()
        self.started = time.monotonic()

    def reserve(self, window, backend):
        size = window.end - window.start
        if not 0 < size <= MAX_WINDOW_SECONDS:
            return 'window_exceeds_limit'
        expected = self.elapsed[backend] / max(1, self.requests_by_backend[backend]) if self.elapsed[backend] else 0
        if time.monotonic() - self.started + expected >= self.max_elapsed:
            return 'elapsed_limit'
        if sum(self.requests.values()) >= self.max_requests or sum(self.audio.values()) + size > self.max_audio:
            return 'task_limit'
        requests, audio = self.zone_limits[window.zone]
        if self.requests[window.zone] >= requests or self.audio[window.zone] + size > audio:
            return 'section_limit'
        if self.profile == 'normal' and len(self.zone_limits) > 1 and self.requests[window.zone] >= 6 and not self.repaired[window.zone]:
            return 'low_yield'
        if backend == 'api' and self.cost_limit is not None:
            if self.cost >= self.cost_limit:
                return 'cost_limit'
            amount = self.quote(backend, size) if self.quote else None
            if amount is None or not math.isfinite(amount) or amount < 0:
                return 'cost_unverified'
            if self.cost + amount > self.cost_limit:
                return 'cost_limit'
            self.cost += amount
        self.requests[window.zone] += 1
        self.audio[window.zone] += size
        return ''

    def observe(self, window, backend, seconds, repaired):
        self.requests_by_backend[backend] += 1
        self.elapsed[backend] += seconds
        self.repaired[window.zone] += repaired

    def receipt(self):
        return dict(profile=self.profile, max_requests=self.max_requests, max_audio_seconds=self.max_audio,
                    max_elapsed_seconds=self.max_elapsed, max_cost_usd=self.cost_limit,
                    reserved_cost_usd=self.cost if self.cost_limit is not None else None,
                    sections={str(zone): {'requests': self.requests[zone], 'audio_seconds': round(self.audio[zone], 3),
                                         'max_requests': limits[0], 'max_audio_seconds': limits[1],
                                         'repaired': self.repaired[zone]}
                              for zone, limits in sorted(self.zone_limits.items())})
