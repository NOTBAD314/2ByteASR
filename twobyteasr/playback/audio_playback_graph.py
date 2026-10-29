"""Single-owner audio routing for the Studio media graph.

The project graph stores intent (master, mute, solo, clip audio).  This module
resolves that intent into one concrete output owner so mpv and secondary
decoders cannot independently decide to create audible sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class AudioPlaybackDecision:
    master_track_id: str
    audible_track_id: str = ""
    # Compatibility field; Studio owns every audible output, including V1.
    mpv_output_enabled: bool = False
    secondary_track_id: str = ""
    reason: str = "no-active-audio"
    source_path: str = ""
    source_ms: int = 0
    playback_rate: float = 1.0
    # Mix inputs share one application sink and are synchronized together.
    mix_mode: bool = False
    mix_track_ids: tuple[str, ...] = ()
    secondary_layers: tuple[dict, ...] = ()

    @property
    def has_owner(self) -> bool:
        return bool(self.audible_track_id) or bool(self.mix_track_ids)


class AudioPlaybackGraph:
    """Resolve exactly one audio sink for a multitrack composition."""

    def __init__(self, *, master_track_id: str = "") -> None:
        self.master_track_id = str(master_track_id or "")
        self.solo_track_ids: frozenset[str] = frozenset()
        self.generation = 0
        self.last_decision = AudioPlaybackDecision(self.master_track_id)

    def configure(self, *, master_track_id: str, solo_track_ids: Iterable[str] = ()) -> None:
        self.master_track_id = str(master_track_id or "")
        self.solo_track_ids = frozenset(str(item) for item in solo_track_ids if str(item))
        self.generation += 1

    def decide(
        self,
        layers: Iterable[Mapping[str, Any]],
        *,
        base_track_id: str = "",
        volume: float = 1.0,
    ) -> AudioPlaybackDecision:
        del volume  # volume is applied by the selected sinks, never for ownership.
        active = [dict(layer) for layer in layers]
        master = self.master_track_id
        if not master:
            if self.solo_track_ids:
                # DAW 语义：多轨 solo = 所有被 solo 的轨同时出声（mix）。
                return self._decide_mix(
                    [layer for layer in active if str(layer.get("track_id") or "") in self.solo_track_ids],
                    active,
                    base_track_id,
                    reason="mix-solo",
                )
            # 2026-09-06（四图反馈·图二）：无 master（皇冠已取消）= 全轨混音。
            return self._decide_mix(active, active, base_track_id, reason="mix-all")
        if self.solo_track_ids and master not in self.solo_track_ids:
            self.last_decision = AudioPlaybackDecision(master, reason="master-not-soloed")
            return self.last_decision
        candidate = next(
            (
                layer
                for layer in active
                if str(layer.get("track_id") or "") == master
                and bool(layer.get("audio_enabled", True))
                and not bool(layer.get("track_muted", False))
            ),
            None,
        )
        if candidate is None:
            self.last_decision = AudioPlaybackDecision(master, reason="master-inactive-or-muted")
            return self.last_decision
        track_id = str(candidate.get("track_id") or "")
        self.last_decision = AudioPlaybackDecision(
            master_track_id=master,
            audible_track_id=track_id,
            mpv_output_enabled=False,
            secondary_track_id="",
            reason="studio-sink",
            source_path=str(candidate.get("source_path") or ""),
            source_ms=max(0, int(candidate.get("source_ms") or 0)),
            playback_rate=max(0.125, float(candidate.get("playback_rate") or 1.0)),
        )
        return self.last_decision

    def consume_resolved(
        self, layers: Iterable[Mapping[str, Any]], *, base_track_id: str = "",
    ) -> AudioPlaybackDecision:
        """Route the shared graph's resolved inputs without choosing another master.

        The captured graph already applied the persisted track selection,
        master, mute and solo settings used by export. A transient clip
        selection in the timeline must not discard those surviving inputs.
        """
        active = [dict(layer) for layer in layers]
        self.configure(master_track_id=str(active[0].get("track_id") or "") if len(active) == 1 else "")
        return self.decide(active, base_track_id=base_track_id)

    def _decide_mix(
        self,
        audible_layers: list[dict],
        routing_layers: list[dict],
        base_track_id: str,
        *,
        reason: str,
    ) -> AudioPlaybackDecision:
        """Resolve all audible inputs for one application-owned mix sink."""

        audible = [
            layer
            for layer in audible_layers
            if bool(layer.get("audio_enabled", True))
            and not bool(layer.get("track_muted", False))
        ]
        del routing_layers
        base = str(base_track_id or "")
        base_layer = next(
            (layer for layer in audible if str(layer.get("track_id") or "") == base),
            None,
        )
        # Every lane contributes to the same PCM stream and hardware clock.
        overlays = [
            layer for layer in audible if layer is not base_layer
        ]
        mix_ids = tuple(
            str(layer.get("track_id") or "")
            for layer in ([base_layer] if base_layer is not None else []) + overlays
            if str(layer.get("track_id") or "")
        )
        decision = AudioPlaybackDecision(
            master_track_id="",
            audible_track_id=base if base_layer is not None else "",
            mpv_output_enabled=False,
            secondary_track_id="",
            reason=reason if mix_ids else f"{reason}-silent",
            source_path=str(base_layer.get("source_path") or "") if base_layer is not None else "",
            source_ms=max(0, int(base_layer.get("source_ms") or 0)) if base_layer is not None else 0,
            playback_rate=max(
                0.125,
                float(base_layer.get("playback_rate") or 1.0) if base_layer is not None else 1.0,
            ),
            mix_mode=True,
            mix_track_ids=mix_ids,
            secondary_layers=tuple(([base_layer] if base_layer is not None else []) + overlays),
        )
        self.last_decision = decision
        return decision


def solo_track_ids(project: Any) -> frozenset[str]:
    value = getattr(project, "studio_state", {}).get("audio_solo_track_ids", ())
    if isinstance(value, str):
        value = (value,)
    ids = {str(item) for item in (value or ()) if str(item)}
    ids.update(
        str(track.id)
        for track in (*getattr(project, "video_tracks", ()), *getattr(project, "audio_tracks", ()))
        if bool(getattr(track, "soloed", False))
    )
    aliases = {g.audio_track_id:g.video_track_id for g in getattr(project,'av_track_groups',()) if g.linked and g.video_track_id}
    return frozenset(aliases.get(key,key) for key in ids)


def set_audio_track_solo(project: Any, track_id: str, enabled: bool) -> None:
    current = set(solo_track_ids(project))
    track_id = str(track_id or "")
    track_id = next((g.video_track_id for g in getattr(project,'av_track_groups',()) if g.linked and g.audio_track_id==track_id and g.video_track_id),track_id)
    if enabled:
        current.add(track_id)
    else:
        current.discard(track_id)
    project.studio_state["audio_solo_track_ids"] = sorted(current)


__all__ = [
    "AudioPlaybackDecision",
    "AudioPlaybackGraph",
    "set_audio_track_solo",
    "solo_track_ids",
]
