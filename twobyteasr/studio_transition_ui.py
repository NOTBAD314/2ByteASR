"""Studio actions and inspector for saved video/audio transitions."""
from __future__ import annotations
from .i18n import tr, bind_text
from .studio_transitions import set_transition, transition_records, KEY


def _push(page, mutate, label):
    from .studio_clip_edit import _working_copy, _finalize_edit
    try:
        working=_working_copy(page.project)
        mutate(working)
        command=_finalize_edit(page.project,working,label,page=page)
    except (ValueError,KeyError) as exc:
        page.save_state.setText(tr(str(exc)))
        return False
    page.undo_stack.push(command)
    page._sync_multitrack_preview_at(page.timeline.playhead_ms)
    page.timeline.update()
    return True


def targets(page, media, edge=None):
    project=page.project
    timeline=page.timeline
    tracks=project.video_tracks if media=='video' else project.audio_tracks
    selected=set(timeline.selected_segment_ids if media=='video' else timeline.selected_audio_clip_ids)
    if media=='video' and timeline.selected_video_clip_id:
        selected.add(timeline.selected_video_clip_id)
    if media=='audio' and not selected:
        selected={c.id for t in tracks for c in t.clips if c.linked_video_clip_id in timeline.selected_segment_ids
                  or c.linked_video_clip_id==timeline.selected_video_clip_id}
    explicit=timeline.selected_clip_edge
    if edge is None and explicit and explicit[0]==media:
        _,tid,cid,end=explicit
        return [(tid,cid if end=='out' else '',cid if end=='in' else '',end)]
    if edge in ('in','out'):
        matches=[(t,c) for t in tracks for c in t.clips if c.id in selected and not t.locked]
        if len(matches)!=1:
            raise ValueError('请选择一个片段，再指定淡入或淡出')
        t,c=matches[0]
        return [(t.id,c.id if edge=='out' else '',c.id if edge=='in' else '',edge)]
    seams=[]
    for track in tracks:
        if track.locked:continue
        clips=sorted(track.clips,key=lambda c:(c.timeline_in_ms,c.id))
        for left,right in zip(clips,clips[1:]):
            if left.timeline_out_ms!=right.timeline_in_ms:continue
            if len(selected)>1:
                valid=left.id in selected and right.id in selected
            else:
                valid=abs(timeline.playhead_ms-left.timeline_out_ms)<=1
                if selected:valid=valid and bool({left.id,right.id}&selected)
                focused=timeline.selected_video_track_id if media=='video' else timeline.selected_audio_track_id
                if focused:valid=valid and track.id==focused
            if valid:seams.append((track.id,left.id,right.id,'seam'))
    if not seams:raise ValueError('请选择接缝或在目标轨剪辑点放置播放头')
    return seams


def apply_default(page,media,edge=None):
    if page.project is None:return
    try:resolved=targets(page,media,edge)
    except ValueError as exc:
        page.save_state.setText(tr(str(exc)));return
    default=int(page.project.studio_state.get('default_'+media+'_transition_ms',500 if media=='video' else 300))
    applied=[]
    def mutate(working):
        for tid,left,right,end in resolved:
            applied.append(set_transition(working,media,tid,left,right,end,default))
    if _push(page,mutate,tr('应用视频转场' if media=='video' else '应用音频转场')):
        page.timeline.selected_transition_id=applied[-1]['id']
        show_properties(page,applied[-1]['id'])
        bind_text(page.save_state,'已应用 {count} 个转场',count=len(applied))


def show_properties(page,transition_id):
    item=next((x for x in transition_records(page.project) if x['id']==transition_id),None) if page.project else None
    page.timeline.selected_transition_id=transition_id if item else ''
    box=getattr(page,'transition_properties',None)
    if box is None:return
    box.setVisible(item is not None)
    if item is None:return
    bind_text(page.transition_type,'交叉溶解' if item['media']=='video' else '恒定功率交叉淡化')
    bind_text(page.transition_end,'接缝' if item['edge']=='seam' else ('淡入' if item['edge']=='in' else '淡出'))
    page.transition_duration.blockSignals(True)
    page.transition_duration.setValue(item['duration_ms'])
    page.transition_duration.blockSignals(False)
    page._show_context_panel()
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
    page.timeline.update()


def change_duration(page):
    item=next((x for x in transition_records(page.project) if x['id']==page.timeline.selected_transition_id),None)
    if item:
        duration=page.transition_duration.value()
        _push(page,lambda p:set_transition(p,item['media'],item['track_id'],item.get('left_clip_id',''),item.get('right_clip_id',''),item['edge'],duration),tr('调整转场时长'))
        show_properties(page,item['id'])


def delete_selected(page):
    key=page.timeline.selected_transition_id
    if not key or not page.project:return False
    if not any(t['id']==key for t in transition_records(page.project)):
        page.timeline.selected_transition_id='';return False
    if _push(page,lambda p:p.studio_state.__setitem__(KEY,[t for t in transition_records(p) if t['id']!=key]),tr('删除转场')):
        show_properties(page,'')
    return True


def menu(page):
    from .studio_theme import create_studio_menu
    result=create_studio_menu(page)
    for media,name in (('video','视频'),('audio','音频')):
        sub=result.addMenu(tr(name))
        for edge,label in ((None,'应用默认转场'),('in','淡入'),('out','淡出')):
            sub.addAction(tr(label),lambda checked=False,m=media,e=edge:apply_default(page,m,e))
    return result


def create_inspector(page,parent):
    from PySide6.QtWidgets import QGroupBox,QFormLayout,QSpinBox,QLabel,QPushButton,QHBoxLayout,QWidget
    box=QGroupBox(tr('转场'));form=QFormLayout(box)
    page.transition_properties=box
    page.transition_type=QLabel();page.transition_end=QLabel()
    page.transition_duration=QSpinBox();page.transition_duration.setRange(1,10000);page.transition_duration.setSuffix(' ms')
    form.addRow(tr('类型'),page.transition_type);form.addRow(tr('作用端'),page.transition_end)
    form.addRow(tr('持续时间'),page.transition_duration)
    page.transition_duration.editingFinished.connect(lambda:change_duration(page))
    remove=QPushButton(tr('删除转场'));remove.clicked.connect(lambda:delete_selected(page));form.addRow(remove)
    box.hide()
    parent.addWidget(box)


def create_default_durations(page,parent):
    """Project defaults for newly applied transitions: a secondary, collapsed
    section at the end of the Video panel (2026-10-12: it used to sit above
    position/scale, the controls users adjust most often)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout,QSpinBox,QToolButton,QWidget,QVBoxLayout,QSizePolicy
    section=QWidget();section.setObjectName('videoDefaultsSection')
    outer=QVBoxLayout(section);outer.setContentsMargins(0,0,0,0);outer.setSpacing(4)
    header=QToolButton();header.setObjectName('videoDefaultsToggle')
    header.setCheckable(True);header.setChecked(False)
    header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    header.setArrowType(Qt.ArrowType.RightArrow)
    header.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    content=QWidget();layout=QFormLayout(content);layout.setContentsMargins(18,2,4,4)
    content.setVisible(False)
    outer.addWidget(header);outer.addWidget(content)
    page.default_transition_toggle=header;page.default_transition_content=content
    def refresh_summary():
        video=getattr(page,'default_video_transition_duration',None)
        audio=getattr(page,'default_audio_transition_duration',None)
        if video is not None and audio is not None:
            bind_text(header,'默认转场时长 · 视频 {video} ms · 音频 {audio} ms',video=video.value(),audio=audio.value())
    def toggled(checked):
        content.setVisible(bool(checked))
        header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
    header.toggled.connect(toggled)
    for media,label,value in (('video','视频',500),('audio','音频',300)):
        spin=QSpinBox();spin.setRange(1,10000);spin.setValue(value);spin.setSuffix(' ms')
        layout.addRow(tr(label),spin)
        def save_default(m=media,s=spin):
            if page.project:
                page.project.studio_state['default_'+m+'_transition_ms']=s.value();page._schedule_autosave()
        spin.editingFinished.connect(save_default)
        spin.valueChanged.connect(lambda _v:refresh_summary())
        setattr(page,'default_'+media+'_transition_duration',spin)
    refresh_summary()
    parent.addWidget(section)
