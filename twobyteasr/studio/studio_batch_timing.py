"""Preview and apply scoped timing rules without moving other speakers."""
from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import dataclass
import json

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QInputDialog, QLabel, QPlainTextEdit,
    QPushButton, QSpinBox,
)

from ..i18n import tr
from ..projects.project_range import clock_text, range_points
from ..projects.studio_project import studio_settings_path
from ..storage.atomic_files import write_text_atomic
from ..timeline.caption_frame_time import project_frame_rate
from ..timeline.studio_edit_sequence import map_timing_to_source, source_cue_id_of, timeline_duration_ms
from ..timeline.timeline_cue_gesture import CueInterval


@dataclass(frozen=True)
class TimingRules:
    start_delta: int = 0
    end_delta: int = 0
    shift: int = 0
    min_gap: int = 0
    fill_gap: int = 0
    min_duration: int = 50
    max_duration: int = 0
    frame_rate: float = 0


def preview(cues, targets, protected, rules, duration, *, preserves_pause=None):
    by_speaker = defaultdict(list)
    original = {}
    for cue in cues:
        by_speaker[cue.speaker_id].append(cue)
        original[cue.id] = CueInterval(cue.start_ms, cue.end_ms, cue.speaker_id)
    proposed = dict(original)
    issues = {}
    candidates = targets - protected
    for cue_id in candidates:
        cue = original[cue_id]
        start = cue.start_ms + rules.shift + rules.start_delta
        end = cue.end_ms + rules.shift + rules.end_delta
        if rules.max_duration and end - start > rules.max_duration:
            issues[cue_id] = "duration_too_long"
            continue
        if end - start < rules.min_duration:
            end = start + rules.min_duration
        if rules.frame_rate:
            start, end = (round(round(point * rules.frame_rate / 1000) * 1000 / rules.frame_rate)
                          for point in (start, end))
        if not 0 <= start <= end - rules.min_duration or end > duration:
            issues[cue_id] = "outside_project"
            continue
        proposed[cue_id] = CueInterval(start, end, cue.speaker_id)

    for lane in by_speaker.values():
        lane.sort(key=lambda row: (row.start_ms, row.end_ms, row.id))
        pending = deque(range(len(lane) - 1))
        while pending:
            index = pending.popleft()
            left, right = lane[index:index + 2]
            a, b = proposed[left.id], proposed[right.id]
            old_gap = right.start_ms - left.end_ms
            gap = b.start_ms - a.end_ms
            if gap < min(old_gap, rules.min_gap):
                for position, item in ((index, left), (index + 1, right)):
                    if proposed[item.id] != original[item.id]:
                        issues[item.id] = "same_speaker_overlap" if gap < 0 else "minimum_gap_requires_review"
                        proposed[item.id] = original[item.id]
                        pending.extend(i for i in (position - 1, position) if 0 <= i < len(lane) - 1)
    # A fill does not cross a new entrance on another lane. An existing
    # overlap stays on its original tracks and receives no timing changes
    # on the other speaker's lane.
    starts = sorted(cue.start_ms for cue in proposed.values())

    for lane in by_speaker.values():
        for left, right in zip(lane, lane[1:]):
            a, b = proposed[left.id], proposed[right.id]
            gap = b.start_ms - a.end_ms
            if left.id not in candidates or left.id in issues or gap < 0:
                continue
            if 0 <= gap < rules.min_gap:
                # Leave existing speech-bearing tails in place. A shorter cue
                # requires an explicit offset or an acoustically reviewed edit.
                issues[left.id] = "minimum_gap_requires_review"
            elif rules.min_gap <= gap <= rules.fill_gap and gap > rules.min_gap:
                end = b.start_ms - rules.min_gap
                if rules.max_duration and end - a.start_ms > rules.max_duration:
                    continue
                if bisect_left(starts, end) > bisect_left(starts, a.end_ms):
                    issues[left.id] = "other_speaker_overlap"
                    continue
                if preserves_pause is not None and preserves_pause(left, right):
                    issues[left.id] = "measured_pause"
                    continue
                proposed[left.id] = CueInterval(a.start_ms, end, a.speaker_id)

    changes = {key: value for key, value in proposed.items() if value != original[key]}
    return changes, issues


_FIELDS = (
    ("shift", "整体偏移", -60000, 60000, 0),
    ("start_delta", "入点偏移", -60000, 60000, 0),
    ("end_delta", "出点偏移", -60000, 60000, 0),
    ("min_gap", "同说话人最小间隔", 0, 5000, 0),
    ("fill_gap", "衔接不超过此值的短间隙", 0, 5000, 500),
    ("min_duration", "最短时长", 50, 5000, 50),
    ("max_duration", "最长时长（0 不限）", 0, 60000, 0),
)
_MESSAGES = {
    "duration_too_long": "超过最长时长，待检查",
    "outside_project": "会超出工程或产生无效时码",
    "same_speaker_overlap": "会增加同一说话人的重叠",
    "minimum_gap_requires_review": "需要检查语音尾部才能设置最小间隔",
    "mapping": "时间无法无损映射到原片，本批暂停套用",
    "other_speaker_overlap": "延长会盖到其他字幕，已保留空白",
    "measured_pause": "词时码显示这里有明确停顿，已保留空白",
}

_PRESET_KEY = "batch_caption_timing_presets"


def _preset_settings():
    path = studio_settings_path()
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("工作台设置格式无效")
    return path, settings


def load_timing_presets():
    try:
        _, settings = _preset_settings()
    except (OSError, ValueError):
        return {}
    data = settings.get(_PRESET_KEY, {})
    if not isinstance(data, dict):
        return {}
    return {name: values for name, values in data.items() if isinstance(values, dict)}


def save_timing_preset(name, values):
    path, settings = _preset_settings()
    presets = settings.get(_PRESET_KEY)
    if not isinstance(presets, dict):
        presets = {}
    clean = {key: min(hi, max(lo, int(values.get(key, initial)))) for key, _, lo, hi, initial in _FIELDS}
    clean["frame_snap"] = bool(values.get("frame_snap"))
    settings[_PRESET_KEY] = {**presets, name: clean}
    write_text_atomic(path, json.dumps(settings, ensure_ascii=False, indent=2))


def protected_cue_ids(project, cues, locked_speakers):
    from ..subtitle_rules.display_continuity import boundary_blocked
    from ..timeline.studio_caption_timeline import KEY

    locked = set(locked_speakers)
    confirmations = project.studio_state.get("review_confirmations") or {}
    receipts = (project.studio_state.get(KEY) or {}).get("instances") or {}
    return {cue.id for cue in cues if (
        cue.speaker_id in locked or confirmations.get(cue.id)
        or confirmations.get(source_cue_id_of(cue.id))
        or boundary_blocked(cue, receipts.get(cue.id))
        or (receipts.get(cue.id) or {}).get("protected_start")
    )}


def show(page):
    project = page.project
    if project is None:
        return
    cues = list(page.timeline._timeline_cue_by_id.values())
    selected = set(page.selected_cue_ids())
    active = page.timeline._timeline_cue_by_id.get(page.selected_cue_id)
    in_point, out_point = range_points(project)
    protected = protected_cue_ids(project, cues, page.timeline.locked_speakers)
    duration = timeline_duration_ms(project)
    fps = project_frame_rate(project)
    dialog = QDialog(page)
    dialog.setObjectName("BatchCaptionTiming")
    dialog.setWindowTitle(tr("批量调整字幕时间"))
    form = QFormLayout(dialog)
    preset = QComboBox(dialog)
    preset.addItem(tr("视频剪辑"), ("builtin", 500))
    preset.addItem(tr("专业字幕"), ("builtin", 0))
    saved_presets = load_timing_presets()
    for name in sorted(saved_presets):
        preset.addItem(name, ("saved", name))
    form.addRow(tr("时间轴预设"), preset)
    scope = QComboBox(dialog)
    for label, key in (("选中字幕", "selected"), ("当前说话人", "speaker"),
                       ("I/O 范围内的字幕", "range"), ("全部字幕", "all")):
        scope.addItem(tr(label), key)
    form.addRow(tr("范围"), scope)
    controls = {}
    for key, title, low, high, initial in _FIELDS:
        spin = QSpinBox(dialog)
        spin.setObjectName(f"BatchCaptionTiming_{key}")
        spin.setRange(low, high)
        spin.setValue(initial)
        spin.setSuffix(" ms")
        form.addRow(tr(title), spin)
        controls[key] = spin
    align = QCheckBox(tr("对齐影片帧"), dialog)
    align.setEnabled(bool(fps))
    form.addRow(align)
    save_preset = QPushButton(tr("保存规则预设…"), dialog)
    form.addRow(save_preset)
    counts = QLabel(dialog)
    form.addRow(counts)
    changes_view = QPlainTextEdit(dialog)
    changes_view.setReadOnly(True)
    changes_view.setMinimumHeight(130)
    form.addRow(changes_view)
    show_preview = QPushButton(tr("预览调整"), dialog)
    show_preview.setObjectName("PreviewBatchCaptionTiming")
    apply = QPushButton(tr("套用预览"), dialog)
    apply.setObjectName("ApplyBatchCaptionTiming")
    apply.setEnabled(False)
    close = QPushButton(tr("关闭"), dialog)
    form.addRow(show_preview, apply)
    form.addRow(close)
    result = {}

    def load_preset():
        kind, key = preset.currentData()
        if kind == "builtin":
            for field, _, _, _, initial in _FIELDS:
                controls[field].setValue(key if field == "fill_gap" else initial)
            align.setChecked(False)
            return
        values = saved_presets[key]
        for field, _, _, _, initial in _FIELDS:
            value = values.get(field, initial)
            controls[field].setValue(value if type(value) is int else initial)
        align.setChecked(bool(fps and values.get("frame_snap") is True))

    def store_preset():
        name, accepted = QInputDialog.getText(dialog, tr("保存规则预设"), tr("预设名称"))
        name = name.strip()
        if not accepted or not name:
            return
        values = {key: spin.value() for key, spin in controls.items()}
        values["frame_snap"] = align.isChecked()
        try:
            save_timing_preset(name, values)
        except (OSError, ValueError):
            counts.setText(tr("预设无法写入工作台设置"))
            return
        saved_presets[name] = values
        index = preset.findData(("saved", name))
        if index < 0:
            preset.addItem(name, ("saved", name))
            index = preset.count() - 1
        preset.setCurrentIndex(index)

    def refresh():
        mode = scope.currentData()
        if mode == "speaker":
            targets = {cue.id for cue in cues if active is not None and cue.speaker_id == active.speaker_id}
        elif mode == "range":
            targets = {cue.id for cue in cues if in_point is not None and out_point is not None
                       and in_point <= cue.start_ms < cue.end_ms <= out_point}
        elif mode == "all":
            targets = {cue.id for cue in cues}
        else:
            targets = selected
        rules = TimingRules(**{key: spin.value() for key, spin in controls.items()},
                            frame_rate=fps if align.isChecked() else 0)
        if rules.max_duration and rules.max_duration < rules.min_duration:
            apply.setEnabled(False)
            counts.setText(tr("最长时长应大于或等于最短时长"))
            changes_view.clear()
            return
        from ..timeline.acoustic_span import acoustic_span
        measured = {}

        def span(cue):
            if cue.id not in measured:
                measured[cue.id] = acoustic_span(project, cue)
            return measured[cue.id]

        def protects_silence(left, right):
            a, b = span(left), span(right)
            return bool(a and b and a.end_grade not in {"unreliable", "unmeasured"}
                        and b.start_grade not in {"unreliable", "unmeasured"}
                        and b.start_ms - a.end_ms >= 650)

        changes, issues = preview(cues, targets, protected, rules, duration,
                                  preserves_pause=protects_silence)
        lines = []
        mapping_failed = False
        for cue in cues:
            value = changes.get(cue.id)
            if value is not None:
                stored = page._cue_lookup.get(source_cue_id_of(cue.id)) or page._cue_lookup.get(cue.id)
                mapped = map_timing_to_source(project, stored, value.start_ms, value.end_ms) if stored else None
                if mapped is None or mapped[0] < 0 or mapped[1] - mapped[0] < 50:
                    issues[cue.id] = "mapping"
                    mapping_failed = True
                else:
                    lines.append(f"{clock_text(cue.start_ms)}–{clock_text(cue.end_ms)} → "
                                 f"{clock_text(value.start_ms)}–{clock_text(value.end_ms)}  {cue.text[:80]}")
            if cue.id in issues:
                lines.append(f"{clock_text(cue.start_ms)}  {tr(_MESSAGES[issues[cue.id]])}  {cue.text[:80]}")
        counts.setText(tr("调整 {changed} 条 · 锁定或已确认 {protected} 条 · 待检查 {issues} 条",
                          changed=len(changes), protected=len(targets & protected), issues=len(issues)))
        changes_view.setPlainText("\n".join(lines[:120]))
        result.clear()
        result.update(changes)
        apply.setEnabled(bool(changes) and not mapping_failed)

    def invalidate():
        apply.setEnabled(False)
        counts.setText(tr("设置已改动，请重新预览"))

    for spin in controls.values():
        spin.valueChanged.connect(invalidate)
    for box in (preset, scope):
        box.currentIndexChanged.connect(invalidate)
    align.toggled.connect(invalidate)
    preset.currentIndexChanged.connect(load_preset)
    save_preset.clicked.connect(store_preset)

    def commit():
        current = page.timeline._timeline_cue_by_id
        if page.project is not project or any(current.get(cue.id) is not cue for cue in cues):
            invalidate()
            counts.setText(tr("字幕已改变，请重新打开批量工具"))
            return
        page.cue_controller.commit_timeline_edit(result)
        dialog.accept()

    show_preview.clicked.connect(refresh)
    apply.clicked.connect(commit)
    close.clicked.connect(dialog.reject)
    dialog.resize(570, 570)
    dialog.exec()
