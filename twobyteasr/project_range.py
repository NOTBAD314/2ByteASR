"""One persisted project-clock, half-open output interval [I, O)."""
from .studio_edit_sequence import sequence_of, timeline_duration_ms


def range_points(project):
    sequence = sequence_of(project)
    return sequence.in_point_ms, sequence.out_point_ms


def effective_range(project):
    start, end = range_points(project)
    return (0 if start is None else start,
            timeline_duration_ms(project) if end is None else end)


def validated_range(project):
    start, end = effective_range(project)
    total = timeline_duration_ms(project)
    if start < 0 or end > total:
        raise ValueError('导出范围超出当前工程，请修改入点或出点。')
    if start >= end:
        raise ValueError('入点必须早于出点，不能导出零时长或反向范围。')
    return start, end


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
