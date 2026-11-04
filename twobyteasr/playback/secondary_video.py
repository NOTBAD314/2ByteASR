"""Default process-isolated secondary decoder; legacy backend is test-only."""
from .secondary_video_process import (
    SecondaryFrame, SecondaryVideoSource, SourceState, frame_is_stale,
    set_defer_media_destruction,
)

__all__ = ['SecondaryFrame', 'SecondaryVideoSource', 'SourceState', 'frame_is_stale']
