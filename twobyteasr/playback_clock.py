"""Single presentation-clock authority for Studio playback consumers."""

from __future__ import annotations
from .playback_probe import measured

from collections import deque
from dataclasses import asdict, dataclass, replace
import os
from pathlib import Path
import time
import traceback
from typing import Any


@dataclass(frozen=True, slots=True)
class PlaybackPositionSnapshot:
    playback_generation: int
    source_generation: int
    actor_sequence: int
    observed_media_ms: float
    presentation_media_ms: float
    observed_monotonic_ts: float
    presentation_monotonic_ts: float
    playback_rate: float
    paused: bool
    seeking: bool
    exact_seek_pending: bool
    source: str
    observed_perf_counter_ts: float | None = None


class PlaybackClock:
    """Own observed and presentation time without accepting backward snaps.

    mpv observations are truth anchors, but they are not themselves UI time.
    During forward playback small drift changes the interpolation rate for a
    bounded interval. A seek or another explicit discontinuity is the only
    operation allowed to replace the presentation anchor directly.
    """

    SEEK_ACK_TOLERANCE_MS = 40.0
    # A seek whose acknowledgement never arrives (actor epoch desync, dead
    # pipe, dropped property event) must not pin the playhead to the seek
    # target forever. After this deadline the next fresh observation is
    # adopted as the truth anchor instead.
    SEEK_ACK_TIMEOUT_MS = 2500.0
    MAX_RATE_CORRECTION_RATIO = 0.12
    TRACE_LIMIT = 8192

    def __init__(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        self._generation = 0
        self._source_generation = 0
        self._actor_sequence = 0
        self._observed_media_ms = 0.0
        self._observed_monotonic_ts = current
        self._observed_perf_counter_ts = None
        self._presentation_anchor_ms = 0.0
        self._presentation_anchor_ts = current
        self._playback_rate = 1.0
        self._rate_correction = 0.0
        self._paused = True
        self._seeking = False
        self._exact_seek_pending = False
        self._seek_target_ms: float | None = None
        self._seek_started_ts: float | None = None
        self._pause_target: bool | None = None
        self._last_source_interval_ms = 75.0
        self._source = "reset"
        self._trace: deque[dict[str, Any]] = deque(maxlen=self.TRACE_LIMIT)
        self._write_audit: deque[dict[str, Any]] = deque(maxlen=self.TRACE_LIMIT)
        self._write_audit_enabled = os.environ.get("TWOBYTEASR_PROJECT_CLOCK_AUDIT") == "1"
        self._snapshot = self._make_snapshot(current, 0.0)
        self._record("reset", accepted=True, reason="initial")
        self._audit_write("reset", 0.0, 0.0)

    @property
    def generation(self) -> int:
        return self._generation

    def advance_generation_to(self, value: int) -> None:
        """Re-align the seek epoch with the persistent mpv actor epoch.

        ``unload_project_media`` installs a fresh clock while the mpv actor
        keeps its monotonic ``_source_generation``. Without this sync the
        first seek of the next project is rejected as
        ``seek_generation_not_ready`` forever, pinning the playhead to the
        seek target (the packaged-EXE 0.5 s replay loop).
        """
        target = max(self._generation, int(value))
        if target > self._generation:
            self._generation = target
            self._record("advance_generation", accepted=True, reason="epoch_sync")

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def playback_rate(self) -> float:
        return self._playback_rate

    @property
    def exact_seek_pending(self) -> bool:
        return self._exact_seek_pending

    def _make_snapshot(
        self,
        now: float,
        presentation_ms: float,
    ) -> PlaybackPositionSnapshot:
        return PlaybackPositionSnapshot(
            playback_generation=self._generation,
            source_generation=self._source_generation,
            actor_sequence=self._actor_sequence,
            observed_media_ms=self._observed_media_ms,
            presentation_media_ms=max(0.0, float(presentation_ms)),
            observed_monotonic_ts=self._observed_monotonic_ts,
            presentation_monotonic_ts=float(now),
            playback_rate=self._playback_rate,
            paused=self._paused,
            seeking=self._seeking,
            exact_seek_pending=self._exact_seek_pending,
            source=self._source,
            observed_perf_counter_ts=self._observed_perf_counter_ts,
        )

    def media_frame_ms(self, rate, *, now_perf=None):
        """Latest observed media frame; captions never predict decoder progress.

        Presentation/UI motion still extrapolates via sample_presentation.
        After seek/resume a decoder can remain on its first frame: advancing
        caption identity by wall time showed the next cue, then its predecessor.
        """
        if self._paused or self._exact_seek_pending or rate is None:
            return self._snapshot.presentation_media_ms
        from .caption_frame_time import observed_frame_ms
        return observed_frame_ms(self._observed_media_ms,rate)

    def milliseconds_until_media_frame(self, target_ms, rate, *, now_perf=None):
        if rate is None or self._observed_perf_counter_ts is None:
            return max(0.,float(target_ms)-self._snapshot.presentation_media_ms)/max(.1,self._playback_rate)
        from .caption_frame_time import observed_frame_ms
        base=observed_frame_ms(self._observed_media_ms,rate)
        now=time.perf_counter() if now_perf is None else now_perf
        return max(0.,float(target_ms-base)/max(.1,self._playback_rate)
                   -max(0.,now-self._observed_perf_counter_ts)*1000)

    def _record(self, event: str, *, accepted: bool, reason: str) -> None:
        payload = asdict(self._snapshot)
        payload.update(event=str(event), accepted=bool(accepted), reason=str(reason))
        self._trace.append(payload)

    def trace(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._trace]

    def write_audit(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._write_audit]

    def _audit_write(self, source: str, old_ms: float, new_ms: float) -> None:
        if not self._write_audit_enabled:
            return
        stack = traceback.extract_stack(limit=9)[:-1]
        self._write_audit.append(
            {
                "source": str(source),
                "old_ms": round(float(old_ms), 6),
                "new_ms": round(float(new_ms), 6),
                "monotonic_ts": time.monotonic(),
                "stack": [
                    f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                    for frame in stack
                ],
            }
        )

    def snapshot(self) -> PlaybackPositionSnapshot:
        return self._snapshot

    def presentation_position_ms(
        self,
        *,
        now: float | None = None,
        elapsed_ms: float | None = None,
    ) -> float:
        current = time.monotonic() if now is None else float(now)
        if self._paused:
            return max(0.0, self._presentation_anchor_ms)
        elapsed = (
            max(0.0, float(elapsed_ms)) / 1000.0
            if elapsed_ms is not None
            else max(0.0, current - self._presentation_anchor_ts)
        )
        effective_rate = max(0.0, self._playback_rate + self._rate_correction)
        return max(0.0, self._presentation_anchor_ms + elapsed * 1000.0 * effective_rate)

    @measured('clock_sample')
    def sample_presentation(
        self,
        *,
        now: float | None = None,
        elapsed_ms: float | None = None,
        source: str = "visual_tick",
    ) -> PlaybackPositionSnapshot:
        current = time.monotonic() if now is None else float(now)
        presentation = self.presentation_position_ms(now=current, elapsed_ms=elapsed_ms)
        previous = self._snapshot.presentation_media_ms
        if not self._paused and presentation < previous:
            presentation = previous
        self._source = str(source)
        self._snapshot = self._make_snapshot(current, presentation)
        self._record(source, accepted=True, reason="presentation")
        self._audit_write(source, previous, presentation)
        return self._snapshot

    def force_position(
        self,
        media_ms: float,
        *,
        paused: bool | None = None,
        playback_rate: float | None = None,
        now: float | None = None,
        reason: str = "explicit_discontinuity",
    ) -> PlaybackPositionSnapshot:
        current = time.monotonic() if now is None else float(now)
        target = max(0.0, float(media_ms))
        previous = self._snapshot.presentation_media_ms
        if paused is not None:
            self._paused = bool(paused)
            self._pause_target = None
        if playback_rate is not None:
            self._playback_rate = min(8.0, max(0.1, float(playback_rate)))
        self._rate_correction = 0.0
        self._presentation_anchor_ms = target
        self._presentation_anchor_ts = current
        self._source = str(reason)
        self._snapshot = self._make_snapshot(current, target)
        self._record("force_position", accepted=True, reason=reason)
        self._audit_write(reason, previous, target)
        return self._snapshot

    def set_local_state(
        self,
        presentation_ms: float,
        *,
        paused: bool | None = None,
        playback_rate: float | None = None,
        now: float | None = None,
        reason: str,
    ) -> PlaybackPositionSnapshot:
        snapshot = self.force_position(
            presentation_ms,
            paused=paused,
            playback_rate=playback_rate,
            now=now,
            reason=reason,
        )
        if paused is not None:
            # Keep the optimistic UI state authoritative until mpv confirms
            # the matching pause value. A time-pos event already in the actor
            # queue may still carry the previous pause property.
            self._pause_target = bool(paused)
        return snapshot

    def begin_unattached_position(self, target_ms: float, *, paused: bool) -> PlaybackPositionSnapshot:
        """A timeline gap has no decoder acknowledgement to wait for."""
        self._generation += 1
        self._seek_target_ms = None
        self._exact_seek_pending = self._seeking = False
        self._pause_target = None
        return self.force_position(target_ms, paused=paused, reason="timeline_without_media")

    def begin_seek(
        self,
        target_ms: float,
        *,
        now: float | None = None,
    ) -> PlaybackPositionSnapshot:
        current = time.monotonic() if now is None else float(now)
        previous = self._snapshot.presentation_media_ms
        self._generation += 1
        self._seek_target_ms = max(0.0, float(target_ms))
        self._seek_started_ts = current
        self._exact_seek_pending = True
        self._seeking = True
        self._rate_correction = 0.0
        self._presentation_anchor_ms = self._seek_target_ms
        self._presentation_anchor_ts = current
        self._source = "optimistic_seek"
        self._snapshot = self._make_snapshot(current, self._seek_target_ms)
        self._record("seek", accepted=True, reason="optimistic")
        self._audit_write("user_project_seek", previous, self._seek_target_ms)
        return self._snapshot

    @measured('clock_observe')
    def observe(
        self,
        observed_media_ms: float,
        *,
        source_generation: int,
        actor_sequence: int,
        observed_monotonic_ts: float,
        playback_rate: float,
        paused: bool,
        seeking: bool,
        source: str = "mpv_property_change",
        discontinuity: bool = False,
        now: float | None = None,
        presentation_media_ms: float | None = None,
        align_forward: bool = False,
        observed_perf_counter_ts: float | None = None,
    ) -> tuple[PlaybackPositionSnapshot, bool, str]:
        current_ts = time.monotonic() if now is None else float(now)
        previous_snapshot_ms = self._snapshot.presentation_media_ms
        current_position = (
            self.presentation_position_ms(now=current_ts)
            if presentation_media_ms is None
            else max(0.0, float(presentation_media_ms))
        )
        generation = max(0, int(source_generation))
        sequence = max(0, int(actor_sequence))

        if generation < self._generation:
            self._snapshot = replace(
                self._snapshot,
                presentation_media_ms=current_position,
                presentation_monotonic_ts=current_ts,
            )
            self._record("observation", accepted=False, reason="stale_generation")
            return self._snapshot, False, "stale_generation"
        if generation == self._source_generation and sequence <= self._actor_sequence:
            self._snapshot = replace(
                self._snapshot,
                presentation_media_ms=current_position,
                presentation_monotonic_ts=current_ts,
            )
            self._record("observation", accepted=False, reason="stale_actor_sequence")
            return self._snapshot, False, "stale_actor_sequence"

        observed = max(0.0, float(observed_media_ms))
        seek_gate_expired = False
        if self._exact_seek_pending and self._seek_target_ms is not None:
            if self._seek_started_ts is not None:
                seek_gate_expired = (
                    current_ts - self._seek_started_ts
                ) * 1000.0 > self.SEEK_ACK_TIMEOUT_MS
            if generation != self._generation and not seek_gate_expired:
                reason = "seek_generation_not_ready"
                self._record("observation", accepted=False, reason=reason)
                return self._snapshot, False, reason
            target_delta_ms = observed - self._seek_target_ms
            forward_allowance_ms = self.SEEK_ACK_TOLERANCE_MS
            if not paused and self._seek_started_ts is not None:
                elapsed_ms = max(0.0, (current_ts - self._seek_started_ts) * 1000.0)
                forward_allowance_ms += elapsed_ms * min(
                    8.0, max(0.1, float(playback_rate))
                )
            if (
                not seek_gate_expired
                and (
                    target_delta_ms < -self.SEEK_ACK_TOLERANCE_MS
                    or target_delta_ms > forward_allowance_ms
                )
            ):
                reason = "seek_target_not_acknowledged"
                self._record("observation", accepted=False, reason=reason)
                return self._snapshot, False, reason

        pause_acknowledged = False
        if self._pause_target is not None:
            if bool(paused) != self._pause_target:
                self._snapshot = replace(
                    self._snapshot,
                    presentation_media_ms=current_position,
                    presentation_monotonic_ts=current_ts,
                )
                reason = "pause_target_not_acknowledged"
                self._record("observation", accepted=False, reason=reason)
                return self._snapshot, False, reason
            pause_acknowledged = True

        if self._observed_monotonic_ts > 0.0:
            interval_ms = max(1.0, (float(observed_monotonic_ts) - self._observed_monotonic_ts) * 1000.0)
            self._last_source_interval_ms = min(1000.0, interval_ms)
        self._source_generation = generation
        self._actor_sequence = sequence
        self._observed_media_ms = observed
        self._observed_monotonic_ts = float(observed_monotonic_ts)
        self._observed_perf_counter_ts = observed_perf_counter_ts
        self._playback_rate = min(8.0, max(0.1, float(playback_rate)))
        self._paused = bool(paused)
        self._seeking = bool(seeking)
        self._source = str(source)

        if self._exact_seek_pending:
            self._exact_seek_pending = False
            self._seeking = bool(seeking)
            self._seek_target_ms = None
            self._seek_started_ts = None
            anchor = observed
            reason = "seek_ack_timeout" if seek_gate_expired else "seek_acknowledged"
            self._rate_correction = 0.0
        elif discontinuity:
            anchor = observed
            reason = "explicit_discontinuity"
            self._rate_correction = 0.0
        else:
            drift_ms = observed - current_position
            if self._paused:
                # A normal pause acknowledgement is not a seek. Holding the
                # presentation value avoids a visible backward snap caused by
                # an older time-pos delivered beside the pause event.
                anchor = (current_position if self._pause_target is True else
                          max(observed, current_position - self.SEEK_ACK_TOLERANCE_MS))
                if anchor < current_position:
                    anchor = current_position
                    reason = "paused_backward_suppressed"
                else:
                    reason = "paused_anchor"
                self._rate_correction = 0.0
            else:
                # A fresh frame observation must not leave captions behind an
                # already presented video frame. Late/backward observations
                # still use the existing monotone drift correction.
                frame_now=observed+max(0.,current_ts-float(observed_monotonic_ts))*1000*self._playback_rate
                anchor = max(current_position, frame_now) if align_forward else current_position
                settle_horizon_s = max(0.35, self._last_source_interval_ms * 4.0 / 1000.0)
                desired_correction = drift_ms / 1000.0 / settle_horizon_s
                correction_limit = self._playback_rate * self.MAX_RATE_CORRECTION_RATIO
                self._rate_correction = min(
                    correction_limit,
                    max(-correction_limit, desired_correction),
                )
                reason = (
                    "backward_absorbed"
                    if drift_ms < -self.SEEK_ACK_TOLERANCE_MS
                    else "drift_absorbed"
                )
                if align_forward and frame_now > current_position:
                    self._rate_correction = 0.0
                    reason = 'forward_frame_anchor'

        if pause_acknowledged:
            reason = "pause_acknowledged"

        self._presentation_anchor_ms = max(0.0, anchor)
        self._presentation_anchor_ts = current_ts
        self._snapshot = self._make_snapshot(current_ts, self._presentation_anchor_ms)
        self._record("observation", accepted=True, reason=reason)
        self._audit_write(source, previous_snapshot_ms, self._presentation_anchor_ms)
        return self._snapshot, True, reason


__all__ = ["PlaybackClock", "PlaybackPositionSnapshot", "backward_replay_windows"]


def backward_replay_windows(
    positions_ms: list[float],
    *,
    tolerance_ms: float = 150.0,
) -> list[tuple[int, float, float]]:
    """Detect backward-replay loops in a playback position sequence.

    Returns ``(index, previous_ms, current_ms)`` for every sample that jumps
    backward beyond ``tolerance_ms``. A healthy forward playback (or a pause)
    never produces one; the packaged 0.5 s replay loop produces them in a
    repeating window.
    """
    windows: list[tuple[int, float, float]] = []
    for index in range(1, len(positions_ms)):
        previous = float(positions_ms[index - 1])
        current = float(positions_ms[index])
        if previous - current > tolerance_ms:
            windows.append((index, previous, current))
    return windows
