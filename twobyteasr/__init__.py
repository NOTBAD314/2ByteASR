"""Public service types for the 2ByteASR production subtitle workflow.

Importing any ``twobyteasr.<module>`` runs this file first, including inside
model workers that run in other Python environments and the stdlib-only
``--mcp-stdio`` process.  So the public names below are looked up on first
use (PEP 562) instead of importing the recognition service up front.  Only
the opt-in test isolation boundary is installed here, because it must take
effect before any module reads user-data paths.

Package map: twobyteasr/README.md.
"""

from .test_isolation import install as _install_test_isolation
_install_test_isolation()

_SERVICE_EXPORTS = frozenset({
    "CancellationToken",
    "CancelledError",
    "MediaResult",
    "PipelineEvent",
    "QueueResult",
    "RunOptions",
    "run_media_queue",
})


def __getattr__(name):
    if name in _SERVICE_EXPORTS:
        from .recognition import service
        return getattr(service, name)
    # Runtime selection and pre-import diagnostics must work with stdlib
    # alone; update discovery's requests dependency is loaded on demand.
    if name == "__version__":
        from .app.updater import current_version
        return current_version()
    raise AttributeError(name)

__all__ = [
    "CancellationToken",
    "CancelledError",
    "MediaResult",
    "PipelineEvent",
    "QueueResult",
    "RunOptions",
    "run_media_queue",
]
