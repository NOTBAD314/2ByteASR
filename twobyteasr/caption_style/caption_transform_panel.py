"""Numeric original/translation transforms using Studio's existing scrub fields."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget
from ..studio.studio_widgets import ScrubDoubleSpinBox
from ..design.studio_theme import StudioComboBox
from ..design.soft_widgets import FoldCard, SegmentedControl, UnitField, WrapLayout
from ..design.themed_icons import install_themed_icon
from ..i18n import bind_text, tr
from .caption_layer_transform import resolved_values, displayed_layer,GeometryBatch
from .scoped_transform import transform_command,edit_values
from ..studio.presentation_scope import capture_scope,report_scope


class CaptionTransformPanel(FoldCard):
    # 2026-10-24 (user): captions move where video clips move. This card is
    # the 视频 tab's 运动 card for a selected caption (the tab shows it instead
    # of the clip cards); it left the 样式 tab. Same parts as the clip card:
    # 原文 | 译文, the small canvas with a dot, X / Y boxes with the unit
    # inside, the link icon at the end of 缩放 and a small 重设变换.
    def __init__(self, page):
        super().__init__(tr('位置与变换'), expanded=True)
        self.setProperty('summaryWhenOpen', True)
        self.set_expanded(True, notify=False)
        self.setObjectName('captionTransformCard')
        self.page=page
        self._updating=False
        self._needs_refresh=False
        self._selection=None
        self.gesture=None
        self.pending={}
        self.controls={}
        self.mixed=set()
        body=self.body_layout

        def field_row(title,*widgets):
            row=QHBoxLayout();row.setSpacing(6)
            label=QLabel(tr(title));label.setObjectName('softLabel')
            row.addWidget(label)
            for widget,stretch in widgets:row.addWidget(widget,stretch)
            return row

        # Only a problem is spelled out here (no translation yet, a locked
        # track); the selection itself is named in the tab's chip.
        self.target=QLabel();self.target.setWordWrap(True);self.target.setObjectName('softMeta')
        self.target.hide()
        body.addWidget(self.target)
        self.language=StudioComboBox()
        for title,value in [('原文','original'),('译文','translation'),('双语','linked')]:self.language.addItem(tr(title),value)
        self.language_segments=SegmentedControl(self.language,emit_activated=False)
        body.addLayout(field_row('语言层',(self.language_segments,1)))
        fields=[('位置','position_x','position_y',-400,500,'%'),
                ('缩放','scale_x','scale_y',1,2000,'%'),
                ('旋转','rotation',None,-360,360,'°'),
                ('锚点','anchor_x','anchor_y',0,100,'%')]
        boxes={}
        for label,x,y,low,high,suffix in fields:
            for column,key in enumerate((x,y),1):
                if key is None:continue
                control=ScrubDoubleSpinBox();control.setObjectName('caption_'+key)
                control.setRange(low,high);control.setDecimals(2);control.setSuffix(suffix)
                control.setKeyboardTracking(False)
                control.setAccessibleName(tr(label)+(' X' if column==1 and y else ' Y' if y else ''))
                control.valueChanged.connect(lambda value,key=key:self.edit(key,value))
                control.editingFinished.connect(lambda key=key:self.finish_field(key))
                control.scrubStarted.connect(self.begin_gesture)
                control.scrubFinished.connect(self.end_gesture)
                axis=('X' if column==1 else 'Y') if y else ''
                boxes[key]=UnitField(control,axis=axis,sample='-360.00' if key=='rotation' else '100.00')
                self.controls[key]=control
        from ..studio.video_inspector_widgets import VideoPositionPad
        self.pad=VideoPositionPad(self.controls['position_x'],self.controls['position_y'],self.end_gesture,
                                  aspect=self._canvas_aspect,on_press=self.begin_gesture,
                                  tooltip='拖动圆点改变字幕位置',name='字幕位置')
        body.addWidget(self.pad)
        hint=QLabel(tr('拖动小画面里的圆点改字幕位置；也可以在画面里直接拖动、缩放字幕。'))
        hint.setObjectName('softMeta');hint.setWordWrap(True)
        body.addWidget(hint)
        self.link=QToolButton();self.link.setCheckable(True);self.link.setChecked(True)
        self.link.setObjectName('captionScaleLink')
        self.link.setAccessibleName(tr('等比缩放'))
        bind_text(self.link,'等比缩放：锁定时修改 X/Y 任一值，另一值同步',property='toolTip')
        install_themed_icon(self.link,'fa5s.link','accent')
        self.link.toggled.connect(lambda value:install_themed_icon(self.link,'fa5s.link' if value else 'fa5s.unlink',
                                                                  'accent' if value else 'secondary'))
        self.link.toggled.connect(lambda value:self.apply({'scale_link':value}))
        link_room=QWidget();link_room.setFixedWidth(34)
        body.addLayout(field_row('位置',(boxes['position_x'],1),(boxes['position_y'],1),(link_room,0)))
        body.addLayout(field_row('缩放',(boxes['scale_x'],1),(boxes['scale_y'],1),(self.link,0)))
        # 旋转 and 锚点 share a line and wrap under each other in long
        # languages, as in the clip card.
        rotation_group,anchor_group=QWidget(),QWidget()
        rotation_row=field_row('旋转',(boxes['rotation'],1));rotation_row.setContentsMargins(0,0,0,0)
        rotation_group.setLayout(rotation_row)
        anchor_row=field_row('锚点',(boxes['anchor_x'],1),(boxes['anchor_y'],1));anchor_row.setContentsMargins(0,0,0,0)
        anchor_group.setLayout(anchor_row)
        rotation_line=WrapLayout(spacing=10,fill=True,by_minimum=True)
        rotation_line.addWidget(rotation_group);rotation_line.addWidget(anchor_group)
        body.addLayout(rotation_line)
        self.reset=QPushButton(tr('重设变换'));self.reset.setObjectName('studioButton')
        self.reset.setProperty('softRole','ghost');self.reset.setProperty('softSize','sm')
        self.reset.setProperty('flexibleWidth',True)
        self.reset.clicked.connect(lambda:self.apply({},reset=True))
        actions=QHBoxLayout();actions.addStretch(1);actions.addWidget(self.reset)
        body.addLayout(actions)
        note=QLabel(tr('位置以工程画布为准；锚点相对本行文字。只修改输入的属性，动效保留基础位置。'))
        note.setObjectName('softMeta');note.setWordWrap(True);body.addWidget(note)
        # Codex 10-23: one switch links position/scale edits across the whole
        # project; one button applies the current values to every caption.
        self.global_link=QCheckBox(tr('全局联动位置与缩放'))
        self.global_link.setObjectName('captionGlobalLink')
        self.global_link.setToolTip(tr('开启后，后续位置与缩放修改作用于全工程所有原文和译文，保留双语间距与说话人避让。'))
        self.global_link.toggled.connect(self.link_changed)
        body.addWidget(self.global_link)
        self.apply_all=QPushButton(tr('将当前位置与缩放套用至全部字幕'))
        self.apply_all.setObjectName('captionApplyAllGeometry')
        self.apply_all.clicked.connect(self.apply_to_all)
        self.apply_all.setProperty('softRole','ghost');self.apply_all.setProperty('softSize','sm')
        body.addWidget(self.apply_all)
        self.language.currentIndexChanged.connect(self.language_changed)
        self.refresh()

    def _canvas_aspect(self):
        project=self.page.project
        if not project:return 16/9
        width=float(project.render_settings.get('play_res_x',1920) or 1920)
        height=float(project.render_settings.get('play_res_y',1080) or 1080)
        return width/height if width and height else 16/9

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh:
            QTimer.singleShot(0, self, self._refresh_if_needed)

    def _refresh_if_needed(self):
        if self._needs_refresh and self.isVisible() and not getattr(self.page, '_close_requested', False):
            self.refresh()

    def targets(self):
        page=self.page
        self._scope_snapshot=capture_scope(page)
        if page.project is None:return []
        ids=set(self._scope_snapshot.cue_ids)
        lookup=getattr(page,'_cue_lookup',{})
        return [lookup[key] for key in ids if key in lookup] if lookup else [cue for cue in page.project.cues if cue.id in ids]

    def link_changed(self,enabled):
        if self._updating or not self.page.project:return
        self.end_gesture(cancel=True)
        if enabled:
            for selector,value in ((self.page.style_scope,'all'),(self.page.style_layer,'group'),(self.language,'linked')):
                with QSignalBlocker(selector):selector.setCurrentIndex(selector.findData(value))
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        from .caption_group_transform import LINK_KEY
        _commit_mutation(self.page.project,action_id='字幕全局联动开关',
            dirty=DirtyDomain.AUTOSAVE,cue_ids=(),
            mutate=lambda:self.page.project.studio_state.__setitem__(LINK_KEY,bool(enabled)),changed=self.page._changed)
        self.refresh()

    def apply_to_all(self):
        self.end_gesture(cancel=True)
        self.page.style_scope.setCurrentIndex(self.page.style_scope.findData('all'))
        targets=self.targets()
        if not targets:return
        cue=next((c for c in targets if c.id==self.page.selected_cue_id),targets[0])
        layer='original' if self._scope_snapshot.layer=='group' else self._scope_snapshot.layer
        value=resolved_values(self.page.project,cue,layer)
        if value is None:return
        changes={key:value[key] for key in ('position_x','position_y','scale_x','scale_y')}
        command=transform_command(self.page.project,[c.id for c in targets],self._scope_snapshot.layer,changes,
            reference_id=cue.id,changed=self.page._changed)
        if command is not None:self.page.undo_stack.push(command)
        report_scope(self.page,self._scope_snapshot,applied=len(targets) if command is not None else 0)
        self.refresh()

    def begin_gesture(self):
        if self.gesture is not None:return
        targets=self.targets()
        if not targets:return
        locked=getattr(self.page.timeline,'locked_speakers',set())
        affected=self.page.project.cues if self.global_link.isChecked() else targets
        if locked and any(c.speaker_id in locked for c in affected):
            self.target.setText(tr('工程有锁定的字幕轨，请先解锁再套用全部'));return
        from .caption_group_transform import values,anchor
        from ..rendering.caption_scene import active_cues
        self.gesture=object();self.pending={}
        self._gesture_project=self.page.project
        self._gesture_revision=self.page._revision_store.render.visual_revision
        self._gesture_ids=tuple(c.id for c in targets)
        self._gesture_known_ids={cue.id for cue in self.page.project.cues}
        self._gesture_selected=self.page.selected_cue_id
        self._gesture_language='linked' if self._scope_snapshot.layer=='group' else self._scope_snapshot.layer
        self._gesture_scope=self._scope_snapshot
        self._gesture_mode='absolute'
        self._gesture_reference_language='original' if self._gesture_language=='linked' else self._gesture_language
        self._gesture_global=self.global_link.isChecked() and self._scope_snapshot.scope=='all' and self._scope_snapshot.layer=='group'
        self._gesture_reference=next((c for c in targets if c.id==self.page.selected_cue_id),targets[0])
        self._gesture_current=resolved_values(self.page.project,self._gesture_reference,self._gesture_reference_language)
        self._gesture_pivot=anchor(self.page.project,self._gesture_reference)
        self._gesture_shared=values(self.page.project)
        self._gesture_visible={}
        for cue in active_cues(self.page,self.page._caption_sample_ms()):
            if not self._gesture_global and not self._gesture_owns(cue.id):continue
            for language in ('original','translation') if self._gesture_global or self._gesture_language=='linked' else (self._gesture_language,):
                value=resolved_values(self.page.project,cue,language)
                if value is not None:self._gesture_visible[(cue.id,language)]=(value,anchor(self.page.project,cue))
        self.page.timeline.set_caption_transform_active(True)

    def _gesture_owns(self,cue_id):
        if cue_id in self._gesture_ids:return True
        if cue_id in self._gesture_known_ids:return False
        from ..timeline.studio_edit_sequence import source_cue_id_of
        return source_cue_id_of(cue_id) in self._gesture_ids

    def end_gesture(self,*,cancel=False):
        if self.gesture is None:return
        changes=self.pending;self.pending={};self.gesture=None
        scope=capture_scope(self.page)
        cancel=cancel or self.page.project is not self._gesture_project or scope.scope!=self._gesture_scope.scope or scope.layer!=self._gesture_scope.layer
        cancel=cancel or self.page._revision_store.render.visual_revision!=self._gesture_revision
        cancel=cancel or scope.cue_ids!=self._gesture_scope.cue_ids
        if cancel:
            if getattr(self.page,'_caption_layer_canvas',False):self.page._caption_transform_retired=True
            self.page._caption_layer_canvas=False
            self.page.position_overlay._dragging=False
        try:
            if not cancel and changes and self.page.project is self._gesture_project:
                self._commit(changes,self._gesture_ids,self._gesture_language,self._gesture_global,
                             self._gesture_reference)
        finally:
            if not getattr(self.page,'_style_deferred_geometry_preview',False):self.page._caption_transform_preview={}
            self.page._caption_transform_preview_serial=getattr(self.page,'_caption_transform_preview_serial',0)+1
            self._gesture_project=None;self._gesture_reference=None
            self._gesture_known_ids=set();self._gesture_visible={};self._gesture_ids=()
            self.page.timeline.set_caption_transform_active(False)
            self.page._present_caption_scene()
            bulk=getattr(getattr(self.page,'style_controller',None),'_bulk_application',None)
            if bulk is not None:bulk.resume_after_gesture()

    def refresh_gesture_targets(self,cues):
        if self.gesture is None or not self.pending or not self._gesture_global:return
        wanted={cue.id for cue in cues}
        current={key[0] for key in self._gesture_visible}
        if wanted==current:return
        from .caption_group_transform import anchor
        self._gesture_visible={}
        for cue in cues:
            for language in ('original','translation'):
                value=resolved_values(self.page.project,cue,language)
                if value is not None:self._gesture_visible[(cue.id,language)]=(value,anchor(self.page.project,cue))
        self._preview({},present=False)

    def _preview(self,changes,*,present=True):
        from .caption_group_transform import shared_after
        from .bilingual_layout import companion_id
        self.pending.update(changes)
        preview={}
        global_geometry=self._gesture_global and bool({'position_x','position_y','scale_x','scale_y'} & self.pending.keys())
        after=shared_after(self.page.project,self._gesture_reference,self._gesture_reference_language,self.pending,
            current=self._gesture_current,pivot=self._gesture_pivot) if global_geometry else None
        for (cue_id,language),(before,pivot) in self._gesture_visible.items():
            if not global_geometry and (not self._gesture_owns(cue_id) or self._gesture_language!='linked' and language!=self._gesture_language):continue
            value=dict(before)
            if after:
                shared=self._gesture_shared
                for axis,point in zip(('x','y'),pivot):
                    key='position_'+axis
                    value[key]=point+(before[key]-shared['d'+axis]-point)/shared['s'+axis]*after['s'+axis]+after['d'+axis]
                    value['scale_'+axis]*=after['s'+axis]/shared['s'+axis]
            else:
                owner=self._gesture_visible.get((cue_id,self._gesture_reference_language),(before,None))[0]
                value=edit_values(before,self.pending,reference=self._gesture_current,owner=owner,
                    mode=self._gesture_mode,linked=self._gesture_language=='linked')
            from .bilingual_layout import settings_from_state
            shown_mode=settings_from_state(self.page.project.studio_state).mode
            if shown_mode=='original' and language=='translation':continue
            if shown_mode=='translation' and language=='original':continue
            preview[companion_id(cue_id) if language=='translation' and shown_mode=='bilingual' else cue_id]=value
        self.page._caption_transform_preview=preview
        self.page._caption_transform_preview_serial=getattr(self.page,'_caption_transform_preview_serial',0)+1
        if present:self.page._present_caption_scene()

    def _commit(self,changes,ids,language,global_mode,reference,*,reset=False):
        bulk=getattr(getattr(self.page,'style_controller',None),'_bulk_application',None)
        if getattr(self.page,'_style_application_busy',False) and bulk is not None:
            mode=getattr(self,'_gesture_mode','absolute') if self._gesture_project is not None else 'absolute'
            if bulk.defer_geometry(ids,language,changes,mode=mode,reference_id=reference.id,reset=reset,global_mode=global_mode):
                return True
        if global_mode and reset:
            from .caption_group_transform import reset_group_command
            command=reset_group_command(self.page.project,self.page._changed)
        elif global_mode and {'position_x','position_y','scale_x','scale_y'} & changes.keys():
            from .caption_group_transform import GroupTransformCommand,shared_after
            command=GroupTransformCommand(self.page.project,
                shared_after(self.page.project,reference,language,changes,reset=reset),self.page._changed)
        else:
            mode=getattr(self,'_gesture_mode','absolute') if self._gesture_project is not None else 'absolute'
            from .bulk_transform_preparation import BULK_THRESHOLD,prepare_command
            if len(ids)>=BULK_THRESHOLD:
                command=prepare_command(self.page,ids,language,changes,reset=reset,
                    reference_id=reference.id,mode=mode)
            else:
                command=transform_command(self.page.project,ids,language,changes,reset=reset,changed=self.page._changed,
                    reference_id=reference.id,mode=mode)
        if command is not None:self.page.undo_stack.push(command)
        report_scope(self.page,getattr(self,'_gesture_scope',None) if self._gesture_project is not None else self._scope_snapshot,
                     applied=len(ids) if command is not None else 0)

    def language_changed(self,*_):
        if self._updating:return
        self.end_gesture(cancel=True)
        selector=getattr(self.page,'style_layer',None)
        value='group' if self.language.currentData()=='linked' else self.language.currentData()
        if selector is not None:
            with QSignalBlocker(selector):selector.setCurrentIndex(selector.findData(value))
        self.page.timeline.selected_lane='translation' if self.language.currentData()=='translation' else ''
        self._updating=True
        try:self.page._load_style_inspector()
        finally:self._updating=False
        self._selection=None
        self.refresh()
        geometry=getattr(self.page,'_selection_geometry',None)
        if geometry is not None:
            geometry.key=None
            cue=getattr(self.page,'_cue_lookup',{}).get(self.page.selected_cue_id)
            if cue is not None:geometry.sync(cue,self.page.project.style_recipes.get(cue.style_id,{}))
        self.page.ensure_active_subtitle_renderer(reason='caption_language_selection')

    def refresh(self):
        if self._updating:return
        if (not self.isVisible() and self.gesture is None
                and len(capture_scope(self.page).cue_ids) > 32):
            # The Video tab's mixed-value form has no visible consumer while
            # another tab is open. Keep selection/overlay ownership current,
            # then hydrate the form from the latest state when it is shown.
            self._needs_refresh=True
            sync_tab=getattr(self.page,'_sync_video_tab_selection',None)
            if callable(sync_tab):sync_tab()
            if not self.isVisible():
                self._scope_snapshot=capture_scope(self.page)
                language='linked' if self._scope_snapshot.layer=='group' else self._scope_snapshot.layer
                with QSignalBlocker(self.language):self.language.setCurrentIndex(self.language.findData(language))
                if self.page.project:self.sync_overlay()
                return
        self._needs_refresh=False
        if self.gesture is not None:
            if (self.page.project is not self._gesture_project or self.page.selected_cue_id!=self._gesture_selected
                    or self.page._revision_store.render.visual_revision!=self._gesture_revision):
                self.end_gesture(cancel=True)
            else:return
        self._updating=True
        try:
            targets=self.targets()
            language='linked' if self._scope_snapshot.layer=='group' else self._scope_snapshot.layer
            selection=(id(self.page.project),self.page.selected_cue_id,tuple(c.id for c in targets),self._scope_snapshot.scope,language)
            if selection!=self._selection:
                self._selection=selection
                with QSignalBlocker(self.language):self.language.setCurrentIndex(self.language.findData(language))
                self.language_segments.sync()  # set with signals blocked
            language=self.language.currentData()
            from .caption_group_transform import LINK_KEY
            with QSignalBlocker(self.global_link):
                self.global_link.setChecked(bool(self.page.project and self.page.project.studio_state.get(LINK_KEY,False)))
            cache=GeometryBatch(self.page.project) if self.page.project else None
            values=[cache.values(c,'original' if language=='linked' else language) for c in targets]
            available=[value for value in values if value is not None]
            locked=bool(targets and any(c.speaker_id in getattr(self.page.timeline,'locked_speakers',set()) for c in targets))
            if self.global_link.isChecked() and self.page.project:
                locked=locked or any(c.speaker_id in getattr(self.page.timeline,'locked_speakers',set()) for c in self.page.project.cues)
            editable=bool(available) and not locked
            message=''
            if self.global_link.isChecked() and self.page.project:
                message=tr('全工程原文与译文 · {count} 条字幕',count=len(self.page.project.cues))
            if targets and not available:message=tr('所选字幕尚无译文')
            if not targets:message=tr('当前范围没有可编辑字幕')
            if not targets and self._scope_snapshot.missing_layer_ids:message=tr('当前范围没有可编辑译文')
            if self._scope_snapshot.locked_ids:
                message=tr('将跳过 {count} 条锁定字幕',count=len(self._scope_snapshot.locked_ids)) if targets else tr('所选字幕轨已锁定，请在时间轴解锁')
            if locked:message=tr('所选字幕轨已锁定，请在时间轴解锁')
            self.target.setText(message);self.target.setVisible(bool(message))
            self.mixed.clear()
            width,height=(float(self.page.project.render_settings.get(k,d)) if self.page.project else d
                          for k,d in (('play_res_x',1920),('play_res_y',1080)))
            for key,control in self.controls.items():
                control.setEnabled(editable)
                with QSignalBlocker(control):
                    raw=available[0][key] if available else (100 if key.startswith('scale_') else 0)
                    factor=100/width if key=='position_x' else 100/height if key=='position_y' else 100 if key.startswith('anchor_') else 1
                    control.setValue(raw*factor)
                    if not available or any(abs(value[key]-raw)>.001 for value in available[1:]):
                        self.mixed.add(key);control.lineEdit().setText('—')
                        control.setToolTip(tr('不同字幕的值不同；输入后只更新此项。'))
            with QSignalBlocker(self.link):self.link.setChecked(available[0]['scale_link'] if available else True)
            linked=self.link.isChecked()
            install_themed_icon(self.link,'fa5s.link' if linked else 'fa5s.unlink','accent' if linked else 'secondary')
            self.link.setEnabled(editable);self.reset.setEnabled(editable)
            self.reset.setText(tr('重设全部位置与缩放' if self.global_link.isChecked() else '重设变换'))
            self.apply_all.setEnabled(editable)
            self.pad.update()
            self._refresh_summary()
            self.sync_overlay()
        finally:self._updating=False
        # The 视频 tab shows this card for a caption selection, the clip
        # cards otherwise; the chip names the selected caption.
        sync_tab=getattr(self.page,'_sync_video_tab_selection',None)
        if callable(sync_tab):sync_tab()

    def _refresh_summary(self):
        def number(key):
            return '—' if key in self.mixed else f'{round(self.controls[key].value(),1):g}'
        scale=(number('scale_x') if number('scale_x')==number('scale_y')
               else f"{number('scale_x')}×{number('scale_y')}")
        self.set_summary(f"{number('position_x')}%, {number('position_y')}% · {scale}% · {number('rotation')}°"
                         if self.controls['position_x'].isEnabled() else '')

    def finish_field(self,key):
        if key in self.mixed and self.controls[key].lineEdit().text().strip()!='—':
            self.edit(key,self.controls[key].value())
        self.end_gesture()

    def edit(self,key,value):
        if self._updating or not self.page.project:return
        width=float(self.page.project.render_settings.get('play_res_x',1920))
        height=float(self.page.project.render_settings.get('play_res_y',1080))
        factor=width/100 if key=='position_x' else height/100 if key=='position_y' else .01 if key.startswith('anchor_') else 1
        control=self.controls.get(key)
        if self.gesture is None and control is not None and (control.hasFocus() or control.lineEdit().hasFocus()):self.begin_gesture()
        self.apply({key:float(value)*factor})

    def apply(self,changes,*,reset=False):
        if self._updating:return
        if self.gesture is not None and not reset:
            if self.page.project is self._gesture_project:self._preview(changes)
            return
        targets=self.targets()
        affected=self.page.project.cues if self.global_link.isChecked() and self.page.project else targets
        if not targets or any(c.speaker_id in getattr(self.page.timeline,'locked_speakers',set()) for c in affected):
            report_scope(self.page,self._scope_snapshot,applied=0)
            self.refresh();return
        reference=next((c for c in targets if c.id==self.page.selected_cue_id),targets[0])
        language='linked' if self._scope_snapshot.layer=='group' else self._scope_snapshot.layer
        self._gesture_project=None
        pending=self._commit(changes,[c.id for c in targets],language,self.global_link.isChecked() and self._scope_snapshot.scope=='all' and language=='linked',reference,reset=reset)
        if not pending:self.refresh()

    def sync_overlay(self):
        targets=self.targets()
        overlay=getattr(self.page,'position_overlay',None)
        if not targets or overlay is None or overlay._dragging:return
        cue=next((c for c in targets if c.id==self.page.selected_cue_id),targets[0])
        shown=displayed_layer(self.page.project,cue,self.language.currentData())
        values=resolved_values(self.page.project,cue,self.language.currentData())
        if shown is None or values is None:return
        from .resolved_caption_style import resolve_caption_style
        width=int(self.page.project.render_settings.get('play_res_x',1920));height=int(self.page.project.render_settings.get('play_res_y',1080))
        style=resolve_caption_style(self.page.project.styles,self.page.project.speakers,shown,self.page.project.style_recipes,width).style
        overlay.set_text(shown.text)
        overlay.set_video_position(round(values['position_x']),round(values['position_y']),width,height)
        overlay.set_font_spec(style.font_family,style.font_size,style.spacing,style.alignment,
            scale_x=style.scale_x,scale_y=style.scale_y,outline_width=style.outline_width,shadow=style.shadow,
            bold=style.bold,italic=style.italic,underline=style.underline,strokes=style.stroke_layers())
        geometry=getattr(self.page,'_selection_geometry',None)
        if geometry is None:
            from ..studio.selection_geometry import SelectionGeometryController
            geometry=self.page._selection_geometry=SelectionGeometryController(self.page)
        geometry.sync(cue,self.page.project.style_recipes.get(cue.style_id,{}))
