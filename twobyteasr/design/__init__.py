"""The application's own look: themes, colour tokens, QSS and shared controls.

Subtitle appearance is not here (see caption_style/ and caption_design/), and
neither is output rendering (rendering/).  Since 2026-10-15 this package also
holds the modules that used to sit beside ``ui.py`` (ui_theme, theme_manager,
studio_theme, timeline_theme, typography, ...).  Importing one of them must
not load Qt widgets, so the convenience names below are resolved on first use.
"""

_EXPORTS = {
    "format_model_evidence_coverage": ".components",
    "map_provider_ui_state": ".components",
    "build_control_qss": ".control_qss",
    "SPACE_SCALE": ".tokens",
    "TYPE_SCALE": ".tokens",
    "p9a_tokens": ".tokens",
}


def __getattr__(name):
    if name in _EXPORTS:
        from importlib import import_module
        return getattr(import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(name)


__all__ = [
    "SPACE_SCALE",
    "TYPE_SCALE",
    "build_control_qss",
    "format_model_evidence_coverage",
    "map_provider_ui_state",
    "p9a_tokens",
]
