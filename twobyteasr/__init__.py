"""Public service types for the 2ByteASR production subtitle workflow."""

from .test_isolation import install as _install_test_isolation
_install_test_isolation()

from .service import (
    CancellationToken,
    CancelledError,
    MediaResult,
    PipelineEvent,
    QueueResult,
    RunOptions,
    run_media_queue,
)


def __getattr__(name):
    # Runtime selection and pre-import diagnostics must work with stdlib
    # alone; update discovery's requests dependency is loaded on demand.
    if name == "__version__":
        from .updater import current_version
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
