"""Studio commands that became rebindable keys on 2026-10-17.

User: "現在能更改的快捷鍵也太少了最好能多點". Every entry below calls a
feature the workbench already had behind a button, a menu item or nothing
at all (jump to start / end, timeline zoom, nudge, export, panels...). The
page merges :func:`extra_command_callbacks` into its ``_command_callbacks``,
so the registry ids in ``shortcut_registry.ACTIONS`` dispatch exactly like
the older ones.
"""
from __future__ import annotations

SEEK_STEP_MS = 1000
NUDGE_STEP_MS = 100


def _seek_ms(page, ms: int) -> None:
    if page.project:
        page._seek(max(0, int(ms)) / 1000.0)


def _jump_edge(page, end: bool) -> None:
    if not page.project:
        return
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    # One frame short of the end keeps the last picture on screen.
    _seek_ms(page, max(0, timeline_duration_ms(page.project) - 40) if end else 0)


def _seek_by(page, delta_ms: int) -> None:
    if page.project:
        _seek_ms(page, int(page.timeline.playhead_ms) + int(delta_ms))


def _nudge(page, delta_ms: int) -> None:
    """Move the selected subtitles together; one selection moves alone."""
    if not page.project:
        return
    selected = list(page.selected_cue_ids())
    if len(selected) > 1:
        page._apply_timing_offset(selected, int(delta_ms))
    else:
        page._nudge(int(delta_ms))


def _step_speed(page, step: int) -> None:
    box = getattr(page, 'speed_box', None)
    if box is None:
        return
    if step == 0:
        index = box.findData(1.0)
    else:
        index = max(0, min(box.count() - 1, box.currentIndex() + step))
    if index >= 0 and index != box.currentIndex():
        box.setCurrentIndex(index)  # runs the page's own _set_speed


def _toggle(checkbox) -> None:
    if checkbox is not None and checkbox.isEnabled():
        checkbox.setChecked(not checkbox.isChecked())


def _range_edge(page, index: int) -> None:
    if not page.project:
        return
    from ..projects.project_range import effective_range
    _seek_ms(page, effective_range(page.project)[index])


def _when_project(page, callback):
    def run():
        if page.project:
            callback()
    return run


def _paste_link(page):
    """Ctrl+V: open the link quick card when the clipboard holds a video link.

    Returns False otherwise, so the key reaches the focused widget."""
    from ..app.link_download_controller import paste_link
    return paste_link(page)


def extra_command_callbacks(page) -> dict:
    return {
        'jump_start': lambda: _jump_edge(page, False),
        'jump_end': lambda: _jump_edge(page, True),
        'seek_back': lambda: _seek_by(page, -SEEK_STEP_MS),
        'seek_forward': lambda: _seek_by(page, SEEK_STEP_MS),
        'loop_cue': page._toggle_loop_current,
        'speed_down': lambda: _step_speed(page, -1),
        'speed_up': lambda: _step_speed(page, 1),
        'speed_reset': lambda: _step_speed(page, 0),
        'nudge_earlier': lambda: _nudge(page, -NUDGE_STEP_MS),
        'nudge_later': lambda: _nudge(page, NUDGE_STEP_MS),
        'smart_align': _when_project(page, page._smart_align_current),
        'reasr_current': _when_project(page, page._reasr_current),
        'timeline_zoom_in': lambda: page._zoom_timeline(0.8),
        'timeline_zoom_out': lambda: page._zoom_timeline(1.25),
        'timeline_fit': page._fit_timeline,
        'toggle_waveform': lambda: _toggle(getattr(page, 'waveform_toggle', None)),
        'toggle_filmstrip': lambda: _toggle(getattr(page, 'filmstrip_toggle', None)),
        'toggle_follow': lambda: _toggle(getattr(page, 'follow_playhead_toggle', None)),
        'go_to_in': lambda: _range_edge(page, 0),
        'go_to_out': lambda: _range_edge(page, 1),
        'clear_in_out': page._clear_range,
        'open_project': page.open_project_dialog,
        'import_media': page.import_media_dialog,
        'paste_link': lambda: _paste_link(page),
        'export_subtitles': page.export_subtitles,
        'export_video': page._open_render_dialog,
        'toggle_cue_list': page._toggle_cue_list,
        'toggle_tool_panel': page._toggle_context_panel,
        'fullscreen': page._toggle_fullscreen,
        'speaker_manager': _when_project(page, page._open_speaker_manager),
    }
