"""Resolve the glossary set implied by the current content selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class GlossaryBinding:
    id: str
    label: str
    kind: str
    matched: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GlossaryBindingResolver:
    """Resolve built-in, learned-user and project glossary bindings.

    The runtime still consumes glossary identities. User mappings are stored
    under the same canonical game identity, so the user binding is reported
    separately while its identity is included in ``active_glossaries``.
    """

    def __init__(self, legacy: Any, project_glossary_ids: Iterable[str] = ()):
        self.legacy = legacy
        self.project_glossary_ids = tuple(
            str(value).strip() for value in project_glossary_ids if str(value).strip()
        )

    def _identity(self, value: str) -> str:
        canonicalize = getattr(self.legacy, "canonicalize_runtime_game_name", str)
        identity = getattr(self.legacy, "runtime_game_identity", str)
        return str(identity(canonicalize(str(value or ""))))

    def resolve(
        self,
        content_name: str = "",
        content_id: str = "",
        enhancement_enabled: bool = False,
        *,
        project_glossary_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        name = str(content_name or "").strip()
        identity = self._identity(content_id or name)
        matched: list[GlossaryBinding] = []
        profiles = getattr(self.legacy, "load_game_profiles", lambda: {})() or {}
        for profile_name, profile in profiles.items():
            if not isinstance(profile, Mapping):
                continue
            profile_identity = self._identity(profile.get("identity", profile_name))
            if identity and profile_identity == identity:
                matched.append(
                    GlossaryBinding(
                        id=profile_identity,
                        label=f"{profile_name} · 内置词库",
                        kind="builtin",
                    )
                )
                break

        learned = getattr(self.legacy, "learned_mappings_for_game", lambda _name: [])(name)
        if learned:
            matched.append(
                GlossaryBinding(
                    id=identity,
                    label=f"用户词库 {name or identity}",
                    kind="user",
                )
            )

        project_ids = self.project_glossary_ids if project_glossary_ids is None else tuple(
            str(value).strip() for value in project_glossary_ids if str(value).strip()
        )
        for project_id in project_ids:
            if project_id not in {item.id for item in matched}:
                matched.append(
                    GlossaryBinding(
                        id=project_id,
                        label=f"工程词库 {project_id}",
                        kind="project",
                    )
                )

        active = []
        if enhancement_enabled:
            active = list(dict.fromkeys(item.id for item in matched if item.id))
            # A learned-only glossary still needs the canonical identity for
            # subtitle_core.learned_mappings_for_game().
            if identity and any(item.kind == "user" for item in matched):
                active = list(dict.fromkeys([identity, *active]))
        return {
            "content_name": name,
            "content_id": identity,
            "enhancement_enabled": bool(enhancement_enabled),
            "matched_glossaries": [item.to_dict() for item in matched],
            "active_glossaries": list(active),
        }


__all__ = ["GlossaryBinding", "GlossaryBindingResolver"]
