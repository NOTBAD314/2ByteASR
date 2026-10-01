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


from .updater import current_version as _current_product_version

__version__ = _current_product_version()
__all__ = [
    "CancellationToken",
    "CancelledError",
    "MediaResult",
    "PipelineEvent",
    "QueueResult",
    "RunOptions",
    "run_media_queue",
]
