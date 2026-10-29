"""「选择要识别的音轨」: which audio tracks of a multi-track source to recognize.

2026-10-24 (user): a multi-track MP4/MKV used to be recognized from one
track only (the first, or whatever the timeline mix happened to be). When the
timeline carries such a source, 识别字幕 asks first: every audio lane with
its stream name, language and channels, a preview, the selected count and
what happens to existing captions. Nothing is extracted, uploaded or
recognized before 开始识别; 取消 leaves everything as it was.

Preselection, in this order: the lane(s) the user selected on the timeline,
this project's previous choice (bound to the source file's fingerprint and
stream, never a row number), the file's default stream, the first lane. The
widget only reports the choice; the Studio page starts the run.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..i18n import bind_text, tr
from ..i18n_widgets import user_text


def default_choice(rows, *, selected_lanes=(), remembered=()) -> list[str]:
    """Lane ids to tick when the picker opens (see the module docstring)."""
    from ..timeline.audio_stream_lanes import source_key
    usable = [row for row in rows if not row.get("problem")]
    explicit = [row["lane_id"] for row in usable if row["lane_id"] in set(selected_lanes)]
    if explicit:
        return explicit
    remembered = [str(key) for key in remembered or ()]
    previous = [row["lane_id"] for row in usable if source_key(row) in remembered]
    if previous:
        return previous
    marked = [row["lane_id"] for row in usable if (row.get("record") or {}).get("default") and not row.get("follower")]
    marked = marked or [row["lane_id"] for row in usable if (row.get("record") or {}).get("default")]
    if marked:
        return marked[:1]
    return [usable[0]["lane_id"]] if usable else []


def _details(row) -> str:
    from ..media.audio_streams import channel_text
    record = row.get("record") or {}
    parts = [row["lane_id"]]
    codec = str(record.get("codec") or "").upper()
    if codec:
        parts.append(codec)
    duration = int(record.get("duration_ms") or 0)
    if duration > 0:
        minutes, seconds = divmod(duration // 1000, 60)
        parts.append(str(tr("时长 {minutes}:{seconds:02d}", minutes=minutes, seconds=seconds)))
    else:
        parts.append(str(tr("时长未标明")))
    start = float(record.get("start_ms") or 0.0)
    if start >= 1.0:
        parts.append(str(tr("在 {seconds:.2f} 秒处开始", seconds=start / 1000.0)))
    if record.get("default"):
        parts.append(str(tr("文件默认音轨")))
    if row.get("muted"):
        parts.append(str(tr("当前静音（仍会识别）")))
    if not record:
        parts.append(str(channel_text(0)))
    return " · ".join(parts)


class AudioTrackPicker(QWidget):
    """Tick boxes for the audio lanes; reports the picked rows or a cancel."""

    accepted = Signal(list)
    cancelled = Signal()
    preview_started = Signal()

    def __init__(self, project, rows, checked, *, start_ms=0, previous=None, single=False, parent=None):
        super().__init__(parent)
        self.setObjectName("audioTrackPicker")
        self.project = project
        # 仅本地识别 (a fast analysis transcript) reads one track at a time.
        self.single = bool(single)
        self.rows = list(rows)
        self.start_ms = int(start_ms or 0)
        self.checks: dict[str, QCheckBox] = {}
        self.preview_buttons: dict[str, QPushButton] = {}
        self._player = None
        self._previewed = False
        self._apply_style()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 14)
        outer.setSpacing(10)
        intro = QLabel()
        intro.setObjectName("audioTrackPickerIntro")
        intro.setWordWrap(True)
        bind_text(intro, '素材里有 {count} 条音轨。勾选要识别的音轨；每条会分别识别。', count=len(self.rows))
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setObjectName("audioTrackPickerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("audioTrackPickerBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        groups: dict[str, list] = {}
        for row in self.rows:
            groups.setdefault(row.get("source_name") or row.get("source_path") or "", []).append(row)
        problems = (previous or {}).get("problems") or []
        failed = {str(item.get("source_key")): str(item.get("error") or "") for item in problems}
        from ..timeline.audio_stream_lanes import source_key
        for name, members in groups.items():
            header = user_text(QLabel(name))
            header.setObjectName("audioTrackSource")
            header.setToolTip(str(members[0].get("source_path") or name))
            column.addWidget(header)
            for row in members:
                column.addWidget(self._row(row, row["lane_id"] in set(checked), failed.get(source_key(row), "")))
        column.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("audioTrackCount")
        self.note = QLabel()
        self.note.setObjectName("audioTrackNote")
        self.note.setWordWrap(True)
        self.impact = QLabel()
        self.impact.setObjectName("audioTrackImpact")
        self.impact.setWordWrap(True)
        self.problem = QLabel()
        self.problem.setObjectName("audioTrackProblem")
        self.problem.setWordWrap(True)
        self.problem.hide()
        for label in (self.count_label, self.note, self.impact, self.problem):
            outer.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        from ..design.presentation import button_role
        self.cancel_button = button_role(QPushButton("取消"), "secondary")
        self.start_button = button_role(QPushButton("开始识别"), "primary")
        self.start_button.setObjectName("audioTrackStart")
        self.cancel_button.setObjectName("audioTrackCancel")
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)
        outer.addLayout(buttons)
        self.cancel_button.clicked.connect(self._cancel)
        self.start_button.clicked.connect(self._start)
        self._refresh()

    # ------------------------------------------------------------------ rows
    def _row(self, row, checked, failure):
        from ..design.presentation import button_role
        from ..media.audio_streams import stream_label
        frame = QFrame()
        frame.setObjectName("audioTrackRow")
        line = QHBoxLayout(frame)
        line.setContentsMargins(10, 6, 8, 6)
        line.setSpacing(10)
        record = row.get("record")
        check = QCheckBox()
        check.setObjectName("audioTrackCheck")
        check.setProperty("laneId", row["lane_id"])
        user_text(check)
        check.setText(str(stream_label(record)) if record else str(tr("{lane} 音轨", lane=row["lane_id"])))
        check.setChecked(bool(checked) and not row.get("problem"))
        check.setEnabled(not row.get("problem"))
        check.toggled.connect(lambda on, lane=row["lane_id"]: self._toggled(lane, on))
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(check)
        details = user_text(QLabel(_details(row)))
        details.setObjectName("audioTrackDetails")
        details.setWordWrap(True)
        texts.addWidget(details)
        if row.get("problem"):
            reason = QLabel()
            reason.setObjectName("audioTrackRowProblem")
            reason.setWordWrap(True)
            bind_text(reason, '不能识别：{reason}', reason=tr(str(row["problem"])))
            texts.addWidget(reason)
        elif failure:
            reason = user_text(QLabel(str(tr("上次识别失败：{reason}", reason=failure))))
            reason.setObjectName("audioTrackRowProblem")
            reason.setWordWrap(True)
            texts.addWidget(reason)
        line.addLayout(texts, 1)
        preview = button_role(QPushButton("试听"), "secondary", size="compact")
        preview.setObjectName("audioTrackPreview")
        preview.setProperty("laneId", row["lane_id"])
        preview.setEnabled(not row.get("problem"))
        bind_text(preview, '从播放头附近试听这一条音轨的几秒', property='toolTip')
        preview.clicked.connect(lambda _checked=False, lane=row["lane_id"]: self._toggle_preview(lane))
        line.addWidget(preview, 0, Qt.AlignmentFlag.AlignVCenter)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.checks[row["lane_id"]] = check
        self.preview_buttons[row["lane_id"]] = preview
        return frame

    def _toggled(self, lane_id: str, on: bool) -> None:
        if on and self.single:
            for lane, box in self.checks.items():
                if lane != lane_id and box.isChecked():
                    box.blockSignals(True)
                    box.setChecked(False)
                    box.blockSignals(False)
        self._refresh()

    def chosen(self) -> list[dict]:
        return [row for row in self.rows if self.checks[row["lane_id"]].isChecked()]

    def _refresh(self) -> None:
        from ..recognition.audio_lane_results import caption_counts
        from ..timeline.audio_stream_lanes import source_key
        chosen = self.chosen()
        bind_text(self.count_label, '已选 {count} 条音轨', count=len(chosen))
        if self.single and chosen:
            bind_text(self.note, '仅本地识别一次分析一条音轨。')
            self.note.show()
        elif len(chosen) >= 2:
            bind_text(self.note, '将分别识别所选音轨，并按来源保留字幕结果。')
            self.note.show()
        elif not chosen:
            bind_text(self.note, '至少勾选一条音轨才能开始识别。')
            self.note.show()
        else:
            self.note.hide()
        replaced, kept = caption_counts(self.project, {source_key(row) for row in chosen}) if chosen else (0, 0)
        if replaced and kept:
            bind_text(self.impact, '会替换所选音轨原有的 {replaced} 条字幕；其他音轨的 {kept} 条字幕保留。',
                      replaced=replaced, kept=kept)
        elif replaced:
            bind_text(self.impact, '会替换所选音轨原有的 {replaced} 条字幕。', replaced=replaced)
        elif kept:
            bind_text(self.impact, '其他音轨的 {kept} 条字幕保留。', kept=kept)
        self.impact.setVisible(bool(chosen and (replaced or kept)))
        self.start_button.setEnabled(bool(chosen))

    # --------------------------------------------------------------- preview
    def _ensure_player(self):
        if self._player is None:
            from ..glossary.glossary_proofread import CuePlayer
            self._player = CuePlayer(self)
            self._player.state_changed.connect(self._preview_state)
            self._player.failed.connect(self._preview_failed)
        return self._player

    def _toggle_preview(self, lane_id: str) -> None:
        player = self._ensure_player()
        if player.cue_id == str(lane_id):
            player.stop()
            return
        from ..playback.cue_audio_preview import PreviewUnavailable, plan_lane_preview
        try:
            plan = plan_lane_preview(self.project, lane_id, self.start_ms)
        except PreviewUnavailable as exc:
            self._preview_failed(str(exc))
            return
        if not self._previewed:
            self._previewed = True
            self.preview_started.emit()
        self.problem.hide()
        player.play_plan(plan, str(lane_id))

    def _preview_state(self, lane_id: str, state: str) -> None:
        for lane, button in self.preview_buttons.items():
            if lane == lane_id and state == "loading":
                bind_text(button, '载入中…')
            elif lane == lane_id and state == "playing":
                bind_text(button, '停止')
            elif lane == lane_id or not state:
                bind_text(button, '试听')

    def _preview_failed(self, message: str) -> None:
        bind_text(self.problem, '试听失败：{reason}', reason=tr(str(message)))
        self.problem.show()

    def shutdown(self) -> None:
        """Stop the preview and its decoder; nothing keeps playing afterwards."""
        if self._player is not None:
            self._player.shutdown()

    @property
    def previewed(self) -> bool:
        return self._previewed

    # ---------------------------------------------------------------- result
    def _start(self) -> None:
        chosen = self.chosen()
        if not chosen:
            self._refresh()
            return
        self.shutdown()
        self.accepted.emit(chosen)

    def _cancel(self) -> None:
        self.shutdown()
        self.cancelled.emit()

    def _apply_style(self) -> None:
        from ..design.theme_manager import theme_key
        from ..design.tokens import RADIUS_SCALE, TYPE_SCALE
        from ..design.ui_theme import blend_hex, hex_luminance, theme_definition
        palette = theme_definition(theme_key())
        light = hex_luminance(palette.surface) > 0.5
        self.setStyleSheet(
            f"QWidget#audioTrackPicker QLabel#audioTrackPickerIntro {{ color: {palette.text};"
            f" font-size: {TYPE_SCALE['body']}px; }}"
            f"QScrollArea#audioTrackPickerScroll, QWidget#audioTrackPickerBody,"
            f" QScrollArea#audioTrackPickerScroll > QWidget#qt_scrollarea_viewport {{ background: transparent; border: 0; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackSource {{ color: {palette.text_secondary};"
            f" font-size: {TYPE_SCALE['small']}px; font-weight: 700; padding-top: 4px; }}"
            f"QWidget#audioTrackPicker QFrame#audioTrackRow {{"
            f" background: {blend_hex(palette.surface, palette.text, 0.035 if light else 0.05)};"
            f" border: 1px solid {palette.border}; border-radius: {RADIUS_SCALE['control']}px; }}"
            f"QWidget#audioTrackPicker QFrame#audioTrackRow QLabel, QWidget#audioTrackPicker QFrame#audioTrackRow QCheckBox"
            f" {{ background: transparent; border: 0; }}"
            f"QWidget#audioTrackPicker QCheckBox#audioTrackCheck {{ color: {palette.text};"
            f" font-size: {TYPE_SCALE['body']}px; font-weight: 600; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackDetails {{ color: {palette.text_muted};"
            f" font-size: {TYPE_SCALE['caption']}px; padding-left: 26px; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackRowProblem, QWidget#audioTrackPicker QLabel#audioTrackProblem"
            f" {{ color: {palette.warning}; font-size: {TYPE_SCALE['small']}px; font-weight: 600; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackRowProblem {{ padding-left: 26px; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackCount {{ color: {palette.text};"
            f" font-size: {TYPE_SCALE['small']}px; font-weight: 700; }}"
            f"QWidget#audioTrackPicker QLabel#audioTrackNote, QWidget#audioTrackPicker QLabel#audioTrackImpact"
            f" {{ color: {palette.accent_text}; font-size: {TYPE_SCALE['small']}px; font-weight: 600; }}"
        )


__all__ = ["AudioTrackPicker", "default_choice"]
