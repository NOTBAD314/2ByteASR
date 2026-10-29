"""Read a main-window page without building it.

MainWindow builds the Workshop, History and Studio pages on first use. Code
that only inspects them (idle maintenance, theme refresh, settings callbacks,
"is a project open?") must not build a page as a side effect.
"""

from __future__ import annotations


def existing_page(owner, name: str):
    """``owner``'s ``<name>_page`` if it has been built, else ``None``."""
    built = getattr(owner, "built_page", None)
    if callable(built):
        return built(name)
    return getattr(owner, f"{name}_page", None)
