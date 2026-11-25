"""Millisecond timing edits on the currently selected Studio cue."""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QWidget,
)

from ..i18n import tr
from ..projects.project_range import clock_text, parse_clock
from ..timeline.caption_frame_time import project_frame_rate
from ..timeline.studio_edit_sequence import map_timing_to_source, timeline_duration_ms


def show(page):
    project = page.project
    cue_id = page.selected_cue_id
    cue = page.timeline._timeline_cue_by_id.get(cue_id)
    stored = page._cue_lookup.get(cue_id)
    if project is None or cue is None or stored is None:
        page._show_studio_hint(tr("请先选中一条字幕"))
        return
    if cue.speaker_id in page.timeline.locked_speakers:
        page._show_studio_hint(tr("轨道已锁定，请先解锁"))
        return

    dialog = QDialog(page)
    dialog.setObjectName("ExactCaptionTiming")
    dialog.setWindowTitle(tr("精确字幕时间"))
    form = QFormLayout(dialog)
    start = QLineEdit(clock_text(cue.start_ms), dialog)
    end = QLineEdit(clock_text(cue.end_ms), dialog)
    duration = QLineEdit(clock_text(cue.end_ms - cue.start_ms), dialog)
    start.setObjectName("ExactCaptionStart")
    end.setObjectName("ExactCaptionEnd")
    duration.setObjectName("ExactCaptionDuration")
    target = QComboBox(dialog)
    for label, value in (("起点", "start"), ("终点", "end"), ("整条字幕", "both")):
        target.addItem(tr(label), value)
    step = QComboBox(dialog)
    for value in (1, 5, 10, 20, 50, 100):
        step.addItem(f"{value} ms", value)
    frame_rate = project_frame_rate(project)
    if frame_rate:
        step.addItem(tr("1 影片帧"), "frame")
    step.addItem(tr("自定义"), "custom")
    custom = QSpinBox(dialog)
    custom.setRange(1, 60000)
    custom.setValue(250)
    custom.setSuffix(" ms")
    custom.hide()
    step.currentIndexChanged.connect(lambda: custom.setVisible(step.currentData() == "custom"))

    def set_times(first, last):
        start.setText(clock_text(first))
        end.setText(clock_text(last))
        duration.setText(clock_text(last - first))

    def read_times():
        first, last = parse_clock(start.text()), parse_clock(end.text())
        if first is None or last is None or not 0 <= first < last <= timeline_duration_ms(project):
            return None
        return first, last

    def update_duration():
        result = read_times()
        if result is not None:
            duration.setText(clock_text(result[1] - result[0]))

    def update_end():
        first, length = parse_clock(start.text()), parse_clock(duration.text())
        if first is not None and length and first + length <= timeline_duration_ms(project):
            end.setText(clock_text(first + length))
        else:
            problem.setText(tr("请检查字幕开始时间及持续时间"))

    def move(direction):
        result = read_times()
        if result is None:
            problem.setText(tr("时间必须在工程内，且终点晚于起点"))
            return
        first, last = result
        mode, amount = target.currentData(), step.currentData()
        if amount == "frame":
            edge = last if mode == "end" else first
            destination = round((round(edge * frame_rate / 1000) + direction) * 1000 / frame_rate)
            delta = destination - edge
        else:
            delta = direction * (custom.value() if amount == "custom" else amount)
        new_first = first if mode == "end" else first + delta
        new_last = last if mode == "start" else last + delta
        if 0 <= new_first < new_last <= timeline_duration_ms(project):
            problem.clear()
            set_times(new_first, new_last)

    start.editingFinished.connect(update_duration)
    end.editingFinished.connect(update_duration)
    duration.editingFinished.connect(update_end)
    form.addRow(tr("开始"), start)
    form.addRow(tr("结束"), end)
    form.addRow(tr("时长"), duration)
    form.addRow(tr("调整位置"), target)

    controls = QWidget(dialog)
    row = QHBoxLayout(controls)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(step)
    row.addWidget(custom)
    for label, direction in (("提前", -1), ("推后", 1)):
        button = QPushButton(tr(label), controls)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False, sign=direction: move(sign))
        row.addWidget(button)
    form.addRow(tr("步长"), controls)

    form.addRow(QLabel(tr("编辑与 SRT 使用毫秒。ASS 按百分之一秒，视频按帧显示。"), dialog))
    problem = QLabel(dialog)
    problem.setWordWrap(True)
    form.addRow(problem)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    def apply():
        result = read_times()
        if result is None:
            problem.setText(tr("时间必须在工程内，且终点晚于起点"))
            return
        if page.project is not project or page._cue_lookup.get(cue_id) is not stored:
            problem.setText(tr("字幕已变更，请重新打开精确时间"))
            return
        mapped = map_timing_to_source(project, stored, *result)
        if mapped is None or mapped[0] < 0 or mapped[1] <= mapped[0]:
            problem.setText(tr("时间范围无法映射回原字幕"))
            return
        page.cue_controller.set_timing(cue_id, *mapped)
        dialog.accept()

    buttons.accepted.connect(apply)
    dialog.exec()
