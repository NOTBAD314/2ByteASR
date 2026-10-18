"""Studio actions and inspector for saved video/audio transitions."""
from __future__ import annotations
from .i18n import tr, bind_text
from .studio_transitions import (set_transition, transition_records, KEY, DEFAULT_LOOK_KEY,
                                           LOOK_DIRECTIONS, VIDEO_LOOKS, normalize_look, default_look)

# Card name, card hint. Generic editing techniques; names are our own.
LOOK_TEXT = {
    'cross_dissolve': ('交叉溶解', '前一段淡出、后一段淡入的叠化'),
    'push': ('推移模糊', '两段画面一起滑过去，带动态模糊'),
    'whip': ('甩镜', '像镜头猛甩一下，拖影很重'),
    'zoom_blur': ('缩放模糊', '冲向镜头，再从放大状态收回'),
    'flash': ('闪白', '亮到全白（或压到全黑），再显出下一段'),
    'glitch': ('色散故障', '红蓝错开、横条错位的故障切换'),
    'stretch': ('拉伸', '沿一个方向拉长，切到下一段再收回'),
}
DIRECTION_TEXT = {'left': ('←', '向左'), 'right': ('→', '向右'), 'up': ('↑', '向上'), 'down': ('↓', '向下'),
                  'white': ('白', '闪白'), 'black': ('黑', '闪黑'),
                  'horizontal': ('横向', '横向拉伸'), 'vertical': ('纵向', '纵向拉伸')}


def look_name(look):
    return LOOK_TEXT[(normalize_look(look) or {}).get('id', 'cross_dissolve')][0]


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


def apply_default(page,media,edge=None,look=None):
    """Apply at the default duration. Video seams get ``look`` when given,
    otherwise the project's default look; clip ends always fade."""
    if page.project is None:return
    try:resolved=targets(page,media,edge)
    except ValueError as exc:
        page.save_state.setText(tr(str(exc)));return
    default=int(page.project.studio_state.get('default_'+media+'_transition_ms',500 if media=='video' else 300))
    chosen=normalize_look(look) if look is not None else default_look(page.project)
    applied=[]
    def mutate(working):
        for tid,left,right,end in resolved:
            applied.append(set_transition(working,media,tid,left,right,end,default,look=chosen))
    if _push(page,mutate,tr('应用视频转场' if media=='video' else '应用音频转场')):
        page.timeline.selected_transition_id=applied[-1]['id']
        show_properties(page,applied[-1]['id'])
        bind_text(page.save_state,'已应用 {count} 个转场',count=len(applied))


def _selected(page):
    key=getattr(page.timeline,'selected_transition_id','') if page.project else ''
    return next((x for x in transition_records(page.project) if x['id']==key),None) if key else None


def _update_selected(page,label,**changes):
    """One undo step for the selected transition's duration or look."""
    item=_selected(page)
    if item is None:return False
    duration=changes.get('duration',item['duration_ms'])
    def mutate(project):
        if 'look' in changes:
            set_transition(project,item['media'],item['track_id'],item.get('left_clip_id',''),
                           item.get('right_clip_id',''),item['edge'],duration,look=changes['look'])
        else:
            set_transition(project,item['media'],item['track_id'],item.get('left_clip_id',''),
                           item.get('right_clip_id',''),item['edge'],duration)
    pushed=_push(page,mutate,tr(label))
    show_properties(page,item['id'])
    return pushed


def show_properties(page,transition_id):
    item=next((x for x in transition_records(page.project) if x['id']==transition_id),None) if page.project else None
    page.timeline.selected_transition_id=transition_id if item else ''
    if not _fill_properties(page,item):return
    page._show_context_panel()
    page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
    page.timeline.update()


def refresh_properties(page):
    """After undo/redo: show the selected transition's restored values
    without switching panels; hide the box if it no longer exists."""
    box=getattr(page,'transition_properties',None)
    if box is None or not box.isVisible():return
    item=_selected(page) if page.project else None
    if item is None:page.timeline.selected_transition_id=''
    _fill_properties(page,item)
    page.timeline.update()


def _fill_properties(page,item):
    box=getattr(page,'transition_properties',None)
    if box is None:return False
    box.setVisible(item is not None)
    if item is None:return False
    seam_video=item['media']=='video' and item['edge']=='seam'
    look=normalize_look(item.get('look')) if seam_video else None
    if seam_video:
        bind_text(page.transition_type,look_name(look))
    else:
        bind_text(page.transition_type,'交叉溶解' if item['media']=='video' else '恒定功率交叉淡化')
    bind_text(page.transition_end,'接缝' if item['edge']=='seam' else ('淡入' if item['edge']=='in' else '淡出'))
    page.transition_duration.blockSignals(True)
    page.transition_duration.setValue(item['duration_ms'])
    page.transition_duration.blockSignals(False)
    _sync_look_controls(page,seam_video,look)
    return True


def _sync_look_controls(page,seam_video,look):
    host=getattr(page,'transition_look_host',None)
    if host is None:return
    host.setVisible(seam_video)
    current=(look or {}).get('id','cross_dissolve')
    for key,tile in page.transition_look_tiles.items():
        tile.set_selected(seam_video and key==current)
    choices=LOOK_DIRECTIONS.get(current,()) if seam_video else ()
    page.transition_direction_row.setVisible(bool(choices))
    for key,button in page.transition_direction_buttons.items():
        button.setVisible(key in choices)
        button.blockSignals(True);button.setChecked(key==(look or {}).get('direction'));button.blockSignals(False)
    page.transition_strength_row.setVisible(seam_video and look is not None)
    value=round(100*(look or {}).get('intensity',1.))
    page.transition_strength.blockSignals(True);page.transition_strength.setValue(value);page.transition_strength.blockSignals(False)
    page.transition_strength_value.setText(f'{value}%')
    default=default_look(page.project) if page.project else None
    page.transition_make_default.setVisible(seam_video)
    page.transition_make_default.setEnabled(seam_video and default!=look)


def change_duration(page):
    item=_selected(page)
    if item and page.transition_duration.value()!=item['duration_ms']:
        _update_selected(page,'调整转场时长',duration=page.transition_duration.value())


def change_look(page,look_id):
    """Pick another look; keep direction/strength where they still apply."""
    item=_selected(page)
    if item is None or item['media']!='video' or item['edge']!='seam':return
    previous=normalize_look(item.get('look')) or {}
    if look_id==previous.get('id','cross_dissolve'):
        _sync_look_controls(page,True,normalize_look(item.get('look')));return
    look=normalize_look(dict(id=look_id,direction=previous.get('direction'),intensity=previous.get('intensity',1.)))
    _update_selected(page,'更改转场效果',look=look)


def change_direction(page,direction):
    item=_selected(page)
    look=normalize_look((item or {}).get('look'))
    if look and look.get('direction')!=direction:
        _update_selected(page,'更改转场效果',look=dict(look,direction=direction))


def change_strength(page):
    item=_selected(page)
    look=normalize_look((item or {}).get('look'))
    value=page.transition_strength.value()/100
    if look and abs(look['intensity']-value)>1e-6:
        _update_selected(page,'调整转场强度',look=dict(look,intensity=value))


def set_default_look(page,look):
    """Ctrl+D default for new video seams: a project setting, like the
    default durations (saved with the project, not an undo step)."""
    if page.project is None:return
    look=normalize_look(look)
    if look is None:page.project.studio_state.pop(DEFAULT_LOOK_KEY,None)
    else:page.project.studio_state[DEFAULT_LOOK_KEY]=look
    page._schedule_autosave()
    bind_text(page.save_state,'已设为默认转场：{name}',name=tr(look_name(look)))
    refresh_defaults(page)
    item=_selected(page)
    if item is not None:show_properties(page,item['id'])


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
        if media=='video':
            looks=sub.addMenu(tr('应用转场效果'))
            for key in VIDEO_LOOKS:
                looks.addAction(tr(LOOK_TEXT[key][0]),
                                lambda checked=False,k=key:apply_default(page,'video',look=dict(id=k) if k!='cross_dissolve' else {}))
    return result


def _look_tile_class():
    from PySide6.QtCore import Qt,QElapsedTimer,QTimer
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QPushButton,QVBoxLayout,QLabel

    class TransitionLookTile(QPushButton):
        """A card that plays its look between two stand-in pictures."""
        PREVIEW=(96,54)
        CYCLE_MS=1600

        def __init__(self,key,parent=None):
            super().__init__(parent)
            self.key=key
            self.setObjectName('transitionLookTile')
            self.setCheckable(True)
            self.setCursor(Qt.PointingHandCursor)
            self.setFixedSize(*TILE_SIZE)
            name,hint=LOOK_TEXT[key]
            bind_text(self,hint,property='toolTip')
            bind_text(self,name,property='accessibleName')
            box=QVBoxLayout(self);box.setContentsMargins(5,5,5,4);box.setSpacing(3)
            self.preview=QLabel(self);self.preview.setFixedSize(*self.PREVIEW)
            self.preview.setAttribute(Qt.WA_TransparentForMouseEvents)
            box.addWidget(self.preview,0,Qt.AlignHCenter)
            self.caption=QLabel(self);self.caption.setObjectName('transitionLookLabel')
            self.caption.setAlignment(Qt.AlignCenter);self.caption.setAttribute(Qt.WA_TransparentForMouseEvents)
            bind_text(self.caption,name)
            box.addWidget(self.caption)
            self.clock=QElapsedTimer();self.timer=QTimer(self);self.timer.setInterval(33)
            self.timer.timeout.connect(self.draw_frame)
            self._built=False

        def frame_at(self,progress):
            from .transition_looks import compose_pair,sample_frames
            ratio=max(1.,self.devicePixelRatioF())
            size=(round(self.PREVIEW[0]*ratio),round(self.PREVIEW[1]*ratio))
            cache=TransitionLookTile.__dict__.get('_frames') or {}
            if size not in cache:
                cache[size]=sample_frames(*size);TransitionLookTile._frames=cache
            frames=cache[size]
            look=normalize_look(dict(id=self.key))
            image=compose_pair(look,progress,frames[0],frames[1],size,transition_id='card-'+self.key)
            image.setDevicePixelRatio(ratio)
            return image

        def draw_frame(self):
            if self.clock.isValid():
                # Hold each picture briefly, then play the seam.
                t=(self.clock.elapsed()%self.CYCLE_MS)/self.CYCLE_MS
                progress=min(1.,max(0.,(t-.2)/.6))
            else:
                progress=POSTER_PROGRESS.get(self.key,.42)
            self.preview.setPixmap(QPixmap.fromImage(self.frame_at(progress)))

        def showEvent(self,event):
            super().showEvent(event)
            if not self._built:
                self._built=True;self.draw_frame()
            if self.isChecked():self._play()

        def set_selected(self,selected):
            self.setChecked(selected)
            if selected and self.isVisible():self._play()
            elif not self.underMouse():self._still()

        def _play(self):
            self.clock.start();self.timer.start()

        def _still(self):
            self.timer.stop();self.clock.invalidate();self.draw_frame()

        def enterEvent(self,event):
            self._play();super().enterEvent(event)

        def leaveEvent(self,event):
            if not self.isChecked():self._still()
            super().leaveEvent(event)

        def hideEvent(self,event):
            self.timer.stop();super().hideEvent(event)

    return TransitionLookTile


TILE_SIZE=(106,84)
# Still frame per card: the moment that best shows the motion.
POSTER_PROGRESS={'cross_dissolve':.5,'push':.4,'whip':.42,'zoom_blur':.38,'flash':.3,'glitch':.47,'stretch':.4}
# App-wide button rules cap heights; pin the card box like the motion tiles.
STYLE='''
QPushButton#transitionLookTile { border: 1px solid palette(mid); border-radius: 8px; padding: 0; background: transparent;
    min-height: %dpx; max-height: %dpx; min-width: %dpx; max-width: %dpx; }''' % (TILE_SIZE[1]-4,TILE_SIZE[1]-4,TILE_SIZE[0]-4,TILE_SIZE[0]-4)+'''
QPushButton#transitionLookTile:hover { border-color: palette(highlight); }
QPushButton#transitionLookTile:checked { border: 2px solid palette(highlight); }
QLabel#transitionLookLabel { font-size: 12px; font-weight: 600; background: transparent; border: 0; }
QPushButton#transitionSegment { border: 1px solid palette(mid); border-radius: 6px; padding: 1px 7px;
    min-height: 20px; max-height: 22px; min-width: 18px; font-size: 11px; background: transparent; }
QPushButton#transitionSegment:hover { border-color: palette(highlight); }
QPushButton#transitionSegment:checked { background: palette(highlight); color: palette(highlighted-text);
    border-color: palette(highlight); }
'''


def create_inspector(page,parent):
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtWidgets import (QGroupBox,QFormLayout,QSpinBox,QLabel,QPushButton,QHBoxLayout,QWidget,
                                   QVBoxLayout,QSlider,QButtonGroup)
    from .motion_inspector_ui import FlowLayout
    box=QGroupBox(tr('转场'));box.setObjectName('videoInspectorSection')
    box.setStyleSheet(STYLE)
    outer=QVBoxLayout(box);outer.setContentsMargins(10,6,10,8);outer.setSpacing(7)
    page.transition_properties=box
    # Look cards, direction and strength: video seams only.
    host=QWidget();looks=QVBoxLayout(host);looks.setContentsMargins(0,0,0,0);looks.setSpacing(6)
    grid_host=QWidget();grid=FlowLayout(grid_host,spacing=6)
    tile_class=_look_tile_class()
    page.transition_look_tiles={}
    for key in VIDEO_LOOKS:
        tile=tile_class(key,grid_host)
        tile.clicked.connect(lambda checked=False,k=key:change_look(page,k))
        grid.addWidget(tile)
        page.transition_look_tiles[key]=tile
    looks.addWidget(grid_host)
    direction_row=QWidget();row=QHBoxLayout(direction_row);row.setContentsMargins(0,0,0,0);row.setSpacing(4)
    row.addWidget(bind_text(QLabel(),'方向'))
    group=QButtonGroup(direction_row);group.setExclusive(True)
    page.transition_direction_buttons={}
    for key,(symbol,hint) in DIRECTION_TEXT.items():
        button=QPushButton();button.setObjectName('transitionSegment');button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor);button.setFocusPolicy(Qt.TabFocus)
        bind_text(button,symbol);bind_text(button,hint,property='toolTip')
        button.clicked.connect(lambda checked=False,k=key:change_direction(page,k))
        group.addButton(button);row.addWidget(button)
        page.transition_direction_buttons[key]=button
    row.addStretch(1)
    page.transition_direction_row=direction_row
    looks.addWidget(direction_row)
    strength_row=QWidget();row=QHBoxLayout(strength_row);row.setContentsMargins(0,0,0,0);row.setSpacing(6)
    row.addWidget(bind_text(QLabel(),'强度'))
    page.transition_strength=QSlider(Qt.Horizontal);page.transition_strength.setRange(50,150)
    page.transition_strength.setSingleStep(5);page.transition_strength.setPageStep(25)
    page.transition_strength_value=QLabel('100%');page.transition_strength_value.setMinimumWidth(38)
    commit=QTimer(page.transition_strength);commit.setSingleShot(True);commit.setInterval(250)
    commit.timeout.connect(lambda:change_strength(page))
    def strength_moved(value):
        page.transition_strength_value.setText(f'{value}%')
        if not page.transition_strength.isSliderDown():commit.start()
    page.transition_strength.valueChanged.connect(strength_moved)
    page.transition_strength.sliderReleased.connect(commit.start)
    row.addWidget(page.transition_strength,1);row.addWidget(page.transition_strength_value)
    page.transition_strength_row=strength_row
    looks.addWidget(strength_row)
    page.transition_look_host=host
    outer.addWidget(host)
    form=QFormLayout();form.setContentsMargins(0,0,0,0)
    page.transition_type=QLabel();page.transition_end=QLabel()
    page.transition_duration=QSpinBox();page.transition_duration.setRange(1,10000);page.transition_duration.setSuffix(' ms')
    form.addRow(tr('类型'),page.transition_type);form.addRow(tr('作用端'),page.transition_end)
    form.addRow(tr('持续时间'),page.transition_duration)
    page.transition_duration.editingFinished.connect(lambda:change_duration(page))
    outer.addLayout(form)
    buttons=QHBoxLayout();buttons.setContentsMargins(0,0,0,0)
    page.transition_make_default=bind_text(QPushButton(),'设为默认')
    bind_text(page.transition_make_default,'以后「应用默认转场」都用这个效果',property='toolTip')
    page.transition_make_default.clicked.connect(lambda:set_default_look(page,(_selected(page) or {}).get('look')))
    remove=QPushButton(tr('删除转场'));remove.clicked.connect(lambda:delete_selected(page))
    buttons.addWidget(page.transition_make_default);buttons.addWidget(remove)
    outer.addLayout(buttons)
    stack=getattr(page,'undo_stack',None)
    if stack is not None:
        stack.indexChanged.connect(lambda _index:refresh_properties(page))
    box.hide()
    parent.addWidget(box)


def refresh_defaults(page):
    """Show the project's default look in the defaults section."""
    combo=getattr(page,'default_video_transition_look',None)
    if combo is None:return
    current=(default_look(page.project) if page.project else None) or {}
    index=combo.findData(current.get('id','cross_dissolve'))
    combo.blockSignals(True);combo.setCurrentIndex(max(0,index));combo.blockSignals(False)
    summary=getattr(page,'_refresh_transition_defaults_summary',None)
    if summary:summary()


def create_default_durations(page,parent):
    """Project defaults for newly applied transitions: a secondary, collapsed
    section at the end of the Video panel (2026-10-12: it used to sit above
    position/scale, the controls users adjust most often)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout,QSpinBox,QToolButton,QWidget,QVBoxLayout,QSizePolicy
    from .studio_theme import StudioComboBox
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
    combo=StudioComboBox()
    for key in VIDEO_LOOKS:
        combo.addItem(tr(LOOK_TEXT[key][0]),key)
    page.default_video_transition_look=combo
    def refresh_summary():
        video=getattr(page,'default_video_transition_duration',None)
        audio=getattr(page,'default_audio_transition_duration',None)
        if video is not None and audio is not None:
            bind_text(header,'默认转场 · 视频 {look} {video} ms · 音频 {audio} ms',
                      look=tr(LOOK_TEXT[combo.currentData() or 'cross_dissolve'][0]),video=video.value(),audio=audio.value())
    page._refresh_transition_defaults_summary=refresh_summary
    def toggled(checked):
        content.setVisible(bool(checked))
        header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
    header.toggled.connect(toggled)
    layout.addRow(tr('视频效果'),combo)
    combo.activated.connect(lambda _index:set_default_look(page,dict(id=combo.currentData())))
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
