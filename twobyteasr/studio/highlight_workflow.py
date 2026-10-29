"""Explicit preview/adjustment actions for the existing clip-assistant bin."""
from __future__ import annotations
import copy

from ..media.danmaku_binding import normalized_source, analysis_media
from ..timeline.studio_edit_sequence import sequence_of
from ..timeline.studio_edit_commands import replace_candidates_command
from ..i18n import tr, bind_text


def candidate_of(page, candidate_id):
    return next((c for c in sequence_of(page.project).clip_candidates if c.id == candidate_id), None) if page.project else None


def timeline_range(project, source_path, start, end):
    """Map a whole source interval through an unbroken occurrence in V1.

    Source identity, duplicate occurrences, deleted material and clip rates are
    checked before seeking. A raw source timestamp is never a project seek.
    """
    from ..timeline.studio_edit_sequence import recording_sequence
    segments=recording_sequence(project)[1].segments
    key=normalized_source(source_path)
    for index, first in enumerate(segments):
        if normalized_source(first.source_path)!=key or not first.source_in_ms <= start < first.source_out_ms:
            continue
        left=first.timeline_in_ms+round((start-first.source_in_ms)*first.duration_ms/max(1,first.source_duration_ms))
        cursor=start
        prior=None
        for segment in segments[index:]:
            if normalized_source(segment.source_path)!=key or (prior and (
                    prior.timeline_out_ms!=segment.timeline_in_ms or prior.source_out_ms!=segment.source_in_ms)):
                break
            if not segment.source_in_ms <= cursor < segment.source_out_ms:
                break
            if end<=segment.source_out_ms:
                right=segment.timeline_in_ms+round((end-segment.source_in_ms)*segment.duration_ms/max(1,segment.source_duration_ms))
                return left,right
            cursor=segment.source_out_ms
            prior=segment
    return None


def source_at_playhead(page, candidate):
    from ..timeline.studio_sequence_mapper import timeline_to_source
    from ..timeline.studio_edit_sequence import recording_sequence
    mapped=timeline_to_source(recording_sequence(page.project)[1],page.timeline.playhead_ms)
    source=candidate.source_path or analysis_media(page.project).path
    if mapped is None or normalized_source(mapped.source_path)!=normalized_source(source):
        raise ValueError('播放头不在这条建议的原素材上，请先查看现场。')
    return mapped.source_ms


def apply_range(page, candidate_id, start, end, confirmed=False):
    candidate=candidate_of(page,candidate_id)
    if candidate is None:return False
    source=candidate.source_path or analysis_media(page.project).path
    assets=[a for a in page.project.media_pool if normalized_source(a.canonical_source)==normalized_source(source)]
    duration=assets[0].duration_ms if assets else candidate.source_duration_ms or analysis_media(page.project).duration_ms
    if type(start) is not int or type(end) is not int or not 0<=start<end<=duration or end-start<40:
        raise ValueError('起止必须在原素材内，且出点至少晚于入点 40 毫秒。')
    items=copy.deepcopy(sequence_of(page.project).clip_candidates)
    row=next(c for c in items if c.id==candidate_id)
    row.source_in_ms,row.source_out_ms=start,end
    row.source_path,row.source_duration_ms=source,duration
    row.range_status='manual'
    row.boundary_refs=[]
    row.user_adjusted=True
    row.user_confirmed=bool(confirmed)
    row.validate()
    if row.to_dict()==candidate.to_dict():return False
    page.undo_stack.push(replace_candidates_command(page.project,items,'调整建议片段起止',page._sequence_changed))
    page._highlight_preview = None
    page._highlight_active_candidate = candidate_id
    page.timeline._highlight_preview_range = timeline_range(page.project,source,start,end)
    page._refresh_danmaku_status()
    page.timeline.update()
    return True


def preview(page, candidate_id, *, play=True, context=False):
    candidate=candidate_of(page,candidate_id)
    if candidate is None:return
    source=candidate.source_path or analysis_media(page.project).path
    page._highlight_active_candidate = candidate_id
    bounds=(candidate.context_in_ms,candidate.context_out_ms) if context else candidate.view_range
    start,end=bounds
    if start is None or end is None or end<=start:
        page.highlight_panel.show_edit_result(tr('没有可查看的有效范围。'),ok=False)
        return
    page.video.set_paused(True)
    page._sync_play_button(True)
    page._highlight_preview=None
    mapped=timeline_range(page.project,source,start,end)
    if mapped is None:
        # The original footage may already have been cut out. Inspect it with
        # the existing canvas in a separate, read-only source viewer.
        open_source_preview(page,candidate,start,end,play=play)
        return
    page.timeline._highlight_preview_range=mapped
    page.timeline._highlight_key_moment=None
    if candidate.key_moment_ms is not None:
        key=timeline_range(page.project,source,candidate.key_moment_ms,candidate.key_moment_ms+1)
        if key:page.timeline._highlight_key_moment=key[0]
    page.timeline.update()
    page._highlight_seeking=True
    try:
        page._seek(mapped[0]/1000)
    finally:
        page._highlight_seeking=False
    if play:
        page._highlight_preview=(page.project.project_id,candidate_id,mapped[0],mapped[1])
        page.video.set_paused(False)
        page._sync_play_button(False)
    bind_text(page.highlight_panel.edit_result,
              '正在查看前后内容，待加入范围保持不变。' if context else
              '到片段终点会暂停；可用「更多操作 → 调整起止」修改范围。')
    page.highlight_panel.edit_result.show()


def tick(page, milliseconds):
    active=getattr(page,'_highlight_preview',None)
    if not active or not page.project:return
    if page.project.project_id!=active[0]:
        page._highlight_preview=None
        return
    if page.video._paused:return
    clock=getattr(page.video,'_playback_clock',None)
    if clock and clock.exact_seek_pending:return
    if milliseconds>=active[3]:
        page._highlight_preview=None
        page.video.set_paused(True)
        page._sync_play_button(True)
        page._seek(active[3]/1000)


def edit_range(page,candidate_id,*,position=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QPushButton,QHBoxLayout,QCheckBox
    from ..projects.project_range import clock_text,parse_clock
    from ..design.studio_theme import apply_secondary_surface_theme
    candidate=candidate_of(page,candidate_id)
    if candidate is None:return
    previous=getattr(page,'_highlight_range_editor',None)
    if previous:previous.close()
    dialog=QDialog(page)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle(tr('调整建议片段起止'))
    dialog.setObjectName('highlightRangeEditor')
    apply_secondary_surface_theme(dialog)
    dialog.resize(490,290)
    layout=QVBoxLayout(dialog)
    heading=QLabel(candidate.title)
    heading.setTextFormat(Qt.TextFormat.PlainText)
    heading.setWordWrap(True)
    layout.addWidget(heading)
    form=QFormLayout()
    fields=[QLineEdit(),QLineEdit()]
    for i,(label,field) in enumerate(zip(('入点','出点'),fields)):
        field.setObjectName('highlightRangeStart' if i==0 else 'highlightRangeEnd')
        if candidate.clip_range:field.setText(clock_text(candidate.clip_range[i]))
        field.setPlaceholderText('00:00:00.000')
        row=QHBoxLayout();row.addWidget(field)
        button=QPushButton(tr('使用播放头'))
        row.addWidget(button)
        button.clicked.connect(lambda _=False,index=i:mark(index))
        form.addRow(tr(label),row)
    layout.addLayout(form)
    hint=QLabel(tr('在时间轴定位后按 I / O，或输入原素材时间；应用后卡片、预览与待生成清单同步。'))
    hint.setWordWrap(True);layout.addWidget(hint)
    confirmed=QCheckBox(tr('我已观看并确认内容'))
    confirmed.setChecked(candidate.user_confirmed)
    layout.addWidget(confirmed)
    error=QLabel();error.setWordWrap(True);layout.addWidget(error)
    actions=QHBoxLayout()
    apply=QPushButton(tr('使用此范围'));apply.setObjectName('studioPrimary')
    cancel=QPushButton(tr('取消'));cancel.setObjectName('studioButton')
    actions.addWidget(cancel);actions.addWidget(apply);layout.addLayout(actions)
    def mark(index):
        try:
            fields[index].setText(clock_text(position() if position else source_at_playhead(page,candidate)))
            error.clear()
        except ValueError as exc:error.setText(tr(str(exc)))
    def save():
        if page.project is not project:
            dialog.close();return
        try:
            apply_range(page,candidate_id,parse_clock(fields[0].text()),parse_clock(fields[1].text()),confirmed.isChecked())
        except ValueError as exc:
            error.setText(tr(str(exc)));return
        dialog.close()
    project=page.project
    dialog.mark_point=mark
    dialog.range_fields=fields
    apply.clicked.connect(save);cancel.clicked.connect(dialog.close)
    dialog.finished.connect(lambda: setattr(page,'_highlight_range_editor',None))
    page._highlight_range_editor=dialog
    dialog.show()


def open_source_preview(page,candidate,start,end,*,play):
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QSlider
    from .studio_video_canvas import MpvCanvas
    from ..design.studio_theme import apply_secondary_surface_theme
    from ..projects.project_range import clock_text
    existing=getattr(page,'_highlight_source_view',None)
    if existing:existing.close()
    class SourceCanvas(MpvCanvas):
        def _studio_page(self):return None
    dialog=QDialog(page)
    dialog.setWindowTitle(tr('查看原片'))
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    apply_secondary_surface_theme(dialog)
    dialog.resize(880,570)
    layout=QVBoxLayout(dialog)
    label=QLabel(tr('这部分不在当前剪辑中；查看原片不会修改工程或待加入范围。'))
    label.setWordWrap(True);layout.addWidget(label)
    canvas=SourceCanvas(dialog);layout.addWidget(canvas,1)
    dialog.canvas=canvas
    canvas.error.connect(label.setText)
    slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(start,end);layout.addWidget(slider)
    times=QLabel();layout.addWidget(times)
    actions=QHBoxLayout();layout.addLayout(actions)
    replay=QPushButton(tr('播放 / 暂停'));actions.addWidget(replay)
    adjust=QPushButton(tr('设置起止'));actions.addWidget(adjust)
    close=QPushButton(tr('关闭'));actions.addWidget(close)
    def update(seconds):
        ms=round(seconds*1000)
        slider.blockSignals(True);slider.setValue(ms);slider.blockSignals(False)
        times.setText(clock_text(ms)+' / '+clock_text(end))
        if ms>=end and not canvas._paused:canvas.set_paused(True)
    def toggle():
        if canvas.visual_position()*1000>=end:canvas.seek(start/1000)
        canvas.set_paused(not canvas._paused)
    slider.sliderMoved.connect(lambda ms:canvas.seek(ms/1000))
    canvas.position_changed.connect(update)
    replay.clicked.connect(toggle)
    adjust.clicked.connect(lambda:edit_range(page,candidate.id,position=lambda:round(canvas.visual_position()*1000)))
    close.clicked.connect(dialog.close)
    dialog.finished.connect(lambda:(canvas.close_player(),setattr(page,'_highlight_source_view',None)))
    page._highlight_source_view=dialog
    dialog.show()
    def load():
        if getattr(page,'_highlight_source_view',None) is not dialog:return
        canvas.load(candidate.source_path or analysis_media(page.project).path,start_seconds=start/1000)
        # This isolated read-only viewer has no project audio engine. Its mpv
        # owns sound; the paused main project keeps its existing PCM owner.
        if canvas.controller:canvas.controller.post_set_audio_enabled(True)
        if play:canvas.set_paused(False)
    QTimer.singleShot(0,load)
