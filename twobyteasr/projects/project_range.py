"""One persisted project-clock, half-open output interval [I, O)."""
from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms


# Pressing I / O again within this distance clears that point (M16).
RANGE_TOGGLE_MS = 20


def range_summary(project):
    """(text, has_range) naming the in/out range for menus."""
    start, end = range_points(project)
    if start is None and end is None:
        return '', False
    first, last = effective_range(project)
    return f'{clock_text(first)} – {clock_text(last)} · {clock_text(max(0, last - first))}', True


def range_points(project):
    sequence = sequence_of(project)
    return sequence.in_point_ms, sequence.out_point_ms


def effective_range(project):
    start, end = range_points(project)
    return (0 if start is None else start,
            timeline_duration_ms(project) if end is None else end)


NO_PICTURE = '入点已经在影片画面结束之后，这一段没有画面。请把入点移回影片里面，或清除入出点导出整个视频。'
TOO_SHORT = '导出范围不到一帧画面，请把入点和出点拉开一点。'
# The renderer never encodes less than 50 ms (studio_render: ``-t max(0.05, …)``); a shorter range is
# a slip of the playhead, not an export anyone wants.
MIN_RANGE_MS = 50


def picture_end_ms(project):
    """Where the video and audio end on the project clock; subtitles may run on past it (2026-11-22).

    ``timeline_duration_ms`` also counts timeline-domain cues, so an in point at the video's end
    used to pass as a valid range with no picture at all (user report: export stuck while
    "compressing", 兔白 could not tell why). 0 when the project has no media extent to compare.
    """
    from ..timeline.studio_media_pool import media_graph_duration_ms
    return max(int(sequence_of(project).timeline_duration_ms), media_graph_duration_ms(project), 0)


def validated_range(project):
    start, end = effective_range(project)
    total = timeline_duration_ms(project)
    if start < 0 or end > total:
        raise ValueError('导出范围超出当前工程，请修改入点或出点。')
    if start >= end:
        raise ValueError('入点必须早于出点，不能导出零时长或反向范围。')
    media_end = picture_end_ms(project)
    if media_end and start >= media_end:
        raise ValueError(NO_PICTURE)
    if end - start < MIN_RANGE_MS:
        raise ValueError(TOO_SHORT)
    return start, end


def range_problem(project):
    """The reason the current range cannot be exported, or '' (export dialog, range bar, 兔白)."""
    try:
        validated_range(project)
    except ValueError as exc:
        return str(exc)
    return ''


def set_range(project, start, end, undo_stack=None):
    from PySide6.QtGui import QUndoCommand
    from .studio_runtime_state import DirtyDomain, state_for
    before = range_points(project)
    after = (None if start is None else int(start), None if end is None else int(end))
    if before == after:
        return

    class RangeCommand(QUndoCommand):
        def __init__(self):
            super().__init__('设置导出范围')

        def apply(self, points):
            with state_for(project).transaction(project, action_id='output_range',
                    dirty=DirtyDomain.CLIP_STATUS | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE):
                seq = sequence_of(project)
                seq.in_point_ms, seq.out_point_ms = points

        def redo(self): self.apply(after)
        def undo(self): self.apply(before)

    command = RangeCommand()
    if undo_stack is not None:
        undo_stack.push(command)
    else:
        command.redo()


def text_input_focused():
    from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
    widget = QApplication.focusWidget()
    return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) or bool(
        getattr(widget, 'isEditable', lambda:False)())


def clock_text(ms):
    ms = int(ms)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'


def parse_clock(text):
    from decimal import Decimal, InvalidOperation
    try:
        parts = text.strip().split(':')
        if not 1 <= len(parts) <= 3: raise ValueError()
        values = [Decimal(p) for p in parts]
        if any(v < 0 or not v.is_finite() for v in values): raise ValueError()
        if len(values)>1 and any(v>=60 for v in values[1:]): raise ValueError()
        return round(sum(v*(60**i) for i,v in enumerate(reversed(values)))*1000)
    except (InvalidOperation, ValueError):
        raise ValueError('请输入时:分:秒.毫秒，例如 00:00:12.631。') from None
