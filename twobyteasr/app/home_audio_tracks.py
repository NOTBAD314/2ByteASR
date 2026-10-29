"""Home page: which audio tracks of a multi-track file to recognize (2026-10-24).

The home page recognizes whole files without a timeline, and used to let
FFmpeg pick the audio stream of a multi-track MP4/MKV. Now 开始识别 first
looks at every queued file; a file with two or more audio streams gets the
Studio picker 「选择要识别的音轨」 (tick boxes, name, language, channels,
preview, selected count), one file at a time in queue order. 开始识别 on the
last picker starts the run with the picks (``RunOptions.audio_streams_json``);
取消 on any of them starts nothing, extracts nothing and uploads nothing.
Files with one audio stream (stereo and 5.1 included) never see a picker and
run exactly as before.

The picker works on a throwaway project of the file (the lanes Studio would
make on import), so rows, labels and the preview are the Studio ones. Probe
results are warmed in the background when files are added, so 开始识别 does
not wait for ffprobe on the UI thread.
"""

from __future__ import annotations

import threading
from pathlib import Path

_WARMED: set[str] = set()
_WARMED_LOCK = threading.Lock()


def _key(path) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, ValueError):
        return str(path)


def warm_up(paths) -> None:
    """Probe new queue files off the UI thread (fills the metadata cache)."""
    with _WARMED_LOCK:
        todo = [str(path) for path in paths if _key(path) not in _WARMED]
        _WARMED.update(_key(path) for path in todo)
    if not todo:
        return

    def run() -> None:
        from ..media.media_service import GLOBAL_MEDIA_SERVICE
        for path in todo:
            try:
                GLOBAL_MEDIA_SERVICE.metadata(path)
            except Exception:  # noqa: BLE001 - the run reports unreadable files itself
                continue

    threading.Thread(target=run, name="home-audio-track-probe", daemon=True).start()


def picker_sources(paths) -> list[tuple[str, object, list]]:
    """(path, project, rows) of each queued file that needs a track choice."""
    from ..media.audio_streams import normalize_streams
    from ..media.media_service import GLOBAL_MEDIA_SERVICE
    from ..projects.studio_project import project_from_runtime_cues
    from ..timeline.audio_stream_lanes import has_multitrack_source, recognizable_lanes
    sources = []
    for path in paths:
        try:
            identity = GLOBAL_MEDIA_SERVICE.metadata(path).to_dict()
        except Exception:  # noqa: BLE001 - unreadable here, the run says why
            continue
        if len(normalize_streams(identity.get("audio_streams"))) < 2:
            continue
        project = project_from_runtime_cues(path, [], media_identity=identity, initialize_layout=False)
        # Home has no timeline to mute on: no 「当前静音」 note on the rows.
        rows = [dict(row, muted=False) for row in recognizable_lanes(project)]
        if has_multitrack_source(project) and len(rows) >= 2:
            sources.append((str(path), project, rows))
    return sources


def picks_of(rows) -> list[dict]:
    return [{"ordinal": int(row["ordinal"]), "stream_index": int(row["stream_index"])} for row in rows]


class HomeTrackChoice:
    """Show the pickers of ``sources`` in turn; report the picks or a cancel."""

    def __init__(self, window, sources, on_done, on_cancel):
        self.window = window
        self.pending = list(sources)
        self.picks: dict[str, list[dict]] = {}
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.picker = None
        self.finished = False

    def start(self) -> None:
        self._next()

    def _next(self) -> None:
        if not self.pending:
            self.finished = True
            self.on_done(self.picks)
            return
        from ..studio.audio_track_picker import AudioTrackPicker, default_choice
        path, project, rows = self.pending.pop(0)
        # What this file was recognized with last time in this session, else its default track.
        remembered = self.window.__dict__.setdefault("_home_audio_track_memory", {}).get(_key(path), ())
        checked = default_choice(rows, remembered=remembered)
        picker = AudioTrackPicker(project, rows, checked, start_ms=0)
        self.picker = picker
        picker.accepted.connect(lambda chosen, path=path: self._accepted(picker, path, chosen))
        picker.cancelled.connect(lambda: self._cancelled(picker, close=True))
        modal = self.window._modal_host
        # Intro, source header, a ~70 px row per track, count, note, buttons.
        height = min(max(420, self.window.height() - 48), 380 + 72 * len(rows))
        modal.show_content(picker, title="选择要识别的音轨", size=(660, height), min_size=(520, 360),
                           on_closed=lambda: self._cancelled(picker, close=False))

    def _accepted(self, picker, path, chosen) -> None:
        from ..timeline.audio_stream_lanes import source_key
        if picker is not self.picker or self.finished:
            return
        picker.shutdown()
        self.window._modal_host.hide_content()
        self.window.__dict__.setdefault("_home_audio_track_memory", {})[_key(path)] = [source_key(row) for row in chosen]
        self.picks[str(path)] = picks_of(chosen)
        self._next()

    def _cancelled(self, picker, *, close: bool) -> None:
        if picker is not self.picker or self.finished:
            return
        self.finished = True
        picker.shutdown()
        if close:
            self.window._modal_host.hide_content()
        self.on_cancel()


def begin(window, resume) -> bool:
    """Ask for tracks when a queued file has several; ``resume(json)`` continues.

    Returns False when no file needs a choice (the caller just goes on).
    """
    paths = list(window.media_paths)
    sources = picker_sources(paths)
    if not sources:
        return False
    from ..recognition.audio_stream_choice import request_json
    flow = HomeTrackChoice(window, sources,
                           on_done=lambda picks: resume(tuple(paths), request_json(picks)),
                           on_cancel=lambda: None)
    window._home_audio_track_flow = flow
    flow.start()
    return True


__all__ = ["HomeTrackChoice", "begin", "picker_sources", "picks_of", "warm_up"]
