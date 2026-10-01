"""One non-secret decision about optional text AI for a recognition task."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextAIPlan:
    polish: bool
    group: bool

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(role for role in ("polish", "group") if getattr(self, role))


def text_ai_plan(settings: dict, *, purpose: str = "final") -> TextAIPlan:
    switches = settings.get("switches", {})
    # Old configurations used unconditional polishing. Preserve that behavior
    # until the user explicitly turns it off; do not infer consent from keys.
    return TextAIPlan(
        polish=purpose != "analysis" and bool(switches.get("enable_ai_polish", True)),
        group=purpose != "analysis" and bool(switches.get("use_ai_grouping", True)),
    )


def bind_text_ai_snapshots(context, settings: dict, *, resolver=None) -> TextAIPlan:
    from .asr_provider_snapshot import resolve_provider_snapshot
    plan = text_ai_plan(settings, purpose=context.recognition_purpose)
    resolver = resolver or resolve_provider_snapshot
    context.provider_snapshots = {role: resolver(settings, stage=role) for role in plan.roles}
    context.provider_snapshot = context.provider_snapshots.get("group")
    return plan
