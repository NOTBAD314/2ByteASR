"""Three actual component previews; the user explicitly chooses one direction."""
from PySide6.QtCore import Qt,Signal,QTimer,QSize
from PySide6.QtGui import QPixmap,QMovie,QPainter,QColor
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame,QPlainTextEdit,
    QScrollArea,QWidget,QSlider,QSplitter,QListWidget,QListWidgetItem,QTabWidget,QComboBox,QMenu,QToolButton)

from .i18n import bind_text

from .i18n import tr


def movie_frame_times(path):
    """GIF encoders coalesce hold frames; indexes are not a constant-rate clock."""
    from PIL import Image
    times=[];elapsed=0
    with Image.open(path) as source:
        for index in range(source.n_frames):
            source.seek(index);times.append(elapsed)
            elapsed+=max(1,int(source.info.get('duration',100)))
    return times


class FittedPicture(QLabel):
    clicked=Signal()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit();event.accept()
        else:super().mouseReleaseEvent(event)

    def __init__(self,path='',parent=None):
        super().__init__(parent);self.original=QPixmap(path);self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(120,90);self.background_mode=0
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(('#20262e','#e9e7df','#d2d4d1')[self.background_mode]))
        if self.background_mode==2:
            for y in range(0,self.height(),16):
                for x in range(0,self.width(),16):
                    if (x//16+y//16)%2:painter.fillRect(x,y,16,16,QColor('#b8bdb9'))
        painter.end();super().paintEvent(event)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not self.original.isNull():self.setPixmap(self.original.scaled(self.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))


class CandidateStrip(QListWidget):
    """A single compact horizontal filmstrip; overflow scrolls horizontally."""
    def __init__(self):
        super().__init__();self.setFlow(QListWidget.LeftToRight);self.setWrapping(False)
        self.setHorizontalScrollMode(QListWidget.ScrollPerPixel);self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSpacing(6);self.setFixedHeight(84)
    def resizeEvent(self,event):
        super().resizeEvent(event);self.fit_cards()
    def fit_cards(self):
        width=min(320,max(180,(self.viewport().width()-12*min(4,max(1,self.count()))-4)//min(4,max(1,self.count()))))
        for i in range(self.count()):self.item(i).setSizeHint(QSize(width,66))


class MotionPreviewDialog(QDialog):
    def __init__(self,concept,parent,motion=None):
        super().__init__(parent);bind_text(self, '{value0} · 完整动画', property='windowTitle', value0=concept['name']);self.resize(1000,650)
        motion=motion or concept['motion_preview']
        seconds=motion.get('duration_ms',6000)/1000
        layout=QVBoxLayout(self)
        self.description=bind_text(QLabel(), '字幕本体 · {seconds:g} 秒循环 · 中性底；全程保持统一放大比例', seconds=seconds)
        layout.addWidget(self.description)
        self.picture=FittedPicture(parent=self);layout.addWidget(self.picture,1)
        self.movie=None
        def load(full=False):
            from pathlib import Path
            if self.movie:self.movie.stop();self.movie.deleteLater()
            if motion.get('transparent_frames') and Path(motion['transparent_frames']).is_dir():
                from .candidate_preview_player import CandidatePreviewPlayer
                self.movie=CandidatePreviewPlayer(motion,context=full,parent=self)
            else:
                self.movie=QMovie((motion['context'] if full else motion)['gif']);self.movie.setParent(self)
                self.movie.setCacheMode(QMovie.CacheAll)
            self.movie.frameChanged.connect(self.refresh)
            if isinstance(self.movie,QMovie):self.movie.finished.connect(self.movie.start)
            self.movie.start()
        load()
        self.picture.setCursor(Qt.PointingHandCursor)
        bind_text(self.picture, '点击暂停 / 继续循环', property='toolTip')
        self.picture.clicked.connect(lambda:self.movie.setPaused(self.movie.state()==QMovie.Running))
        if motion.get('context'):
            context=QPushButton('查看视频叠加' if motion['context'].get('background')=='current-media' else '查看完整画面占比')
            context.setCheckable(True);layout.addWidget(context)
            def switch(checked):
                load(checked)
                (bind_text(self.description, '完整画面 · {value0:g} 秒循环 · 实际画面占比', value0=seconds) if checked else bind_text(self.description, '字幕本体 · {value0:g} 秒循环 · 中性底；全程保持统一放大比例', value0=seconds))
                (bind_text(context, '返回字幕本体') if checked else (bind_text(context, '查看视频叠加') if motion['context'].get('background') == 'current-media' else bind_text(context, '查看完整画面占比')))
            context.toggled.connect(switch)
        close=QPushButton('关闭预览');close.clicked.connect(self.accept);layout.addWidget(close)
    def refresh(self):
        self.picture.original=self.movie.currentPixmap()
        self.picture.setPixmap(self.picture.original.scaled(self.picture.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def done(self,value):
        self.movie.stop();super().done(value)


class SubjectPreviewDialog(QDialog):
    """Static subject inspection with pixel-preserving zoom and optional context."""
    def __init__(self,concept,path,parent=None):
        super().__init__(parent);bind_text(self, '{value0} · 字幕本体', property='windowTitle', value0=concept['name']);self.resize(1100,620)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('字幕本体 · 拖动缩放查看字面、冰层与边缘；预览底色不随作品导出'))
        scroll=QScrollArea();scroll.setWidgetResizable(False);scroll.setAlignment(Qt.AlignCenter);layout.addWidget(scroll,1)
        picture=QLabel();picture.setAlignment(Qt.AlignCenter);picture.setStyleSheet('background:#20262e');scroll.setWidget(picture)
        source=QPixmap(path)
        zoom=QSlider(Qt.Horizontal);zoom.setRange(25,200);zoom.setValue(100);layout.addWidget(zoom)
        def update(value):
            if source.isNull():return
            image=source.scaled(source.size()*value/100,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            picture.setPixmap(image);picture.resize(image.size())
        zoom.valueChanged.connect(update);update(100)
        if concept.get('motion_preview',{}).get('status')=='motion_ready':
            play=QPushButton('播放字幕本体完整动画');play.clicked.connect(lambda:MotionPreviewDialog(concept,self).exec());layout.addWidget(play)
        if concept.get('full_frame_preview'):
            context=QPushButton('查看视频叠加 / 完整画面占比');context.setCheckable(True);layout.addWidget(context)
            def switch(checked):
                nonlocal source
                source=QPixmap(concept['full_frame_preview'] if checked else path);update(zoom.value())
            context.toggled.connect(switch)
        close=QPushButton('关闭');close.clicked.connect(self.accept);layout.addWidget(close)


class ThemeConceptDialog(QDialog):
    retry_requested=Signal(str)
    recovery_requested=Signal(str,str)
    refine_requested=Signal(str)
    redo_requested=Signal(str)
    cancel_requested=Signal(str)

    def __init__(self,concepts,previews,parent=None):
        super().__init__(parent)
        self.selected_id='';self.task_states={};self.feedback={};self.movie=None;self.movies=[]
        self._preview_key=None;self.concepts=[];self.previews={};self.task_labels={};self._frame_times=[]
        bind_text(self, '字幕候选作品工作台', property='windowTitle');self.resize(1160,800);self.setMinimumSize(660,560)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,16,22,16);layout.setSpacing(9)
        self.overview=QLabel();self.overview.setObjectName('workOverview');layout.addWidget(self.overview)
        self.candidate_list=CandidateStrip();self.candidate_list.setObjectName('candidateList')
        self.candidate_list.setIconSize(QSize(86,42));self.candidate_list.setWordWrap(False)
        self.candidate_list.setTextElideMode(Qt.ElideRight);layout.addWidget(self.candidate_list)
        body=layout
        self.title=QLabel();self.title.setObjectName('workTitle');body.addWidget(self.title)
        self.picture=FittedPicture(parent=self);self.picture.setObjectName('subtitleSubjectPreview')
        self.picture.setStyleSheet('background:transparent;color:#e9e4db;padding:24px')
        body.addWidget(self.picture,1)
        self.preview_notice=QLabel();self.preview_notice.hide()
        transport=QHBoxLayout();body.addLayout(transport)
        self.play_button=QToolButton();self.play_button.setFixedSize(40,34);self.play_button.setIconSize(QSize(22,22));self.play_button.clicked.connect(self.toggle_play);transport.addWidget(self.play_button)
        self.picture.clicked.connect(self.toggle_play);self.picture.setCursor(Qt.PointingHandCursor)
        bind_text(self.picture, '点击播放 / 暂停；就绪后自动循环', property='toolTip')
        from .candidate_controls import SeekSlider
        self.scrubber=SeekSlider(Qt.Horizontal);self.scrubber.setMinimumWidth(60);self.scrubber.setRange(0,143);self.scrubber.valueChanged.connect(self.seek_frame);transport.addWidget(self.scrubber,1)
        self.scrubber.sliderPressed.connect(lambda:self.seek_frame(self.scrubber.value()))
        self.timecode=QLabel('0.00 / 0.00s');transport.addWidget(self.timecode)
        self.speed=QComboBox();self.speed.addItems(['1×','0.5×']);self.speed.currentIndexChanged.connect(self._speed);transport.addWidget(self.speed)
        self.segment=QComboBox();self.segment.addItems(['完整演示','仅入场','仅退场','阅读段']);self.segment.currentIndexChanged.connect(self._segment);transport.addWidget(self.segment)
        self.context=QToolButton();bind_text(self.context, '背景');self.context.setCheckable(True);self.context.toggled.connect(lambda _:self._show_selected());transport.addWidget(self.context)
        bind_text(self.context, '画面占比');bind_text(self.context, '切换字幕本体 / 完整画面', property='toolTip')
        self.background=QComboBox();self.background.addItems(['深色底','浅色底','棋盘底']);self.background.currentIndexChanged.connect(self._background);transport.addWidget(self.background)
        enlarge=QToolButton();bind_text(enlarge, '放大');enlarge.clicked.connect(self.enlarge);transport.addWidget(enlarge)
        body.addWidget(self.preview_notice)
        self.status=QLabel();self.status.setObjectName('workStatus');self.status.setWordWrap(True);self.status.setTextInteractionFlags(Qt.TextSelectableByMouse);body.addWidget(self.status)
        self.details_toggle=QToolButton();bind_text(self.details_toggle, '展开设计与过程');self.details_toggle.setCheckable(True);body.addWidget(self.details_toggle)
        self.tabs=QTabWidget();self.tabs.setMinimumHeight(86);self.tabs.setMaximumHeight(145);body.addWidget(self.tabs)
        self.tabs.hide();self.details_toggle.toggled.connect(self.tabs.setVisible)
        self.details={}
        for name in ('设计说明','动效','生成记录','源码与诊断'):
            field=QPlainTextEdit();field.setReadOnly(True);self.tabs.addTab(field,name);self.details[name]=field
        self.action_feedback=QLabel();self.action_feedback.setWordWrap(True);self.action_feedback.hide();layout.addWidget(self.action_feedback)
        footer=QHBoxLayout();footer.setContentsMargins(0,8,0,0);layout.addLayout(footer)
        self.more=QToolButton();bind_text(self.more, '更多操作');self.more.setPopupMode(QToolButton.InstantPopup);footer.addWidget(self.more)
        footer.addStretch(1)
        self.later=QPushButton('保留方案，稍后选择');self.later.clicked.connect(self.reject);footer.addWidget(self.later)
        self.primary=QPushButton();self.primary.setObjectName('studioPrimary');self.primary.setProperty('studioPrimary',True);self.primary.clicked.connect(self._primary);footer.addWidget(self.primary)
        self.candidate_list.currentRowChanged.connect(self._show_selected)
        self.status_timer=QTimer(self);self.status_timer.setInterval(1000);self.status_timer.timeout.connect(self.refresh_task_states);self.status_timer.start()
        self.refresh_theme_palette()
        self.update_concepts(concepts,previews)

    def current_concept(self):
        i=self.candidate_list.currentRow()
        return self.concepts[i] if 0<=i<len(self.concepts) else {}

    @staticmethod
    def badge(c,state=None):
        from .design_progress import candidate_status
        return {'queued':'排队中','running':'制作中','accepted':'已接收','repairing':'自动恢复中',
                'finishing':'保存中','failed':'已停止 · 未完成','cancelled':'已取消',
                'rejected':'未启动','ready':'就绪','render_pending':'待预览'}[candidate_status(c,state)]

    def update_concepts(self,concepts,previews):
        from PySide6.QtGui import QIcon
        selected=self.current_concept().get('id');scroll=self.candidate_list.horizontalScrollBar().value()
        self.concepts=concepts;self.previews=previews;self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for c in concepts:
            item=QListWidgetItem(f"{c['name']}\n{self.badge(c)}")
            item.setToolTip(c['name']+'\n'+str(c.get('composition','')))
            item.setData(Qt.UserRole,c['id']);item.setSizeHint(QSize(160,68))
            path=previews.get(c['id'],'')
            if path:
                icon=QIcon(path);icon.addPixmap(QPixmap(path),QIcon.Selected,QIcon.Off);item.setIcon(icon)
            self.candidate_list.addItem(item)
        idx=next((i for i,c in enumerate(concepts) if c['id']==selected),0)
        self.candidate_list.setCurrentRow(idx);self.candidate_list.blockSignals(False)
        self.candidate_list.fit_cards();self.candidate_list.horizontalScrollBar().setValue(scroll)
        ready=sum(self.badge(c)=='就绪' for c in concepts);busy=sum(bool(c.get('pending')) for c in concepts)
        bind_text(self.overview, '字幕视觉方向 · {value0} 候选 · {value1} 就绪{value2}', value0=len(concepts), value1=ready, value2=f' · {busy} 处理中' if busy else '')
        self._show_selected()

    def _show_selected(self,*_):
        import json
        from .candidate_attempt import primary_action
        c=self.current_concept()
        if not c:return
        self.title.setText(c['name'])
        self.task_labels={c['id']:self.status}
        motion=c.get('motion_preview',{});ready=motion.get('status')=='motion_ready'
        selected=motion.get('context',motion) if self.context.isChecked() else motion
        path=selected.get('gif') if ready else c.get('preview_picture') or self.previews.get(c['id'],'')
        key=(c['id'],path)
        if key!=self._preview_key:
            self._preview_key=key
            if self.movie:self.movie.stop();self.movie.deleteLater();self.movie=None
            self.picture.clear();self.picture.original=QPixmap()
            if ready and path:
                from pathlib import Path
                if motion.get('transparent_frames') and Path(motion['transparent_frames']).is_dir():
                    from .candidate_preview_player import CandidatePreviewPlayer
                    self.movie=CandidatePreviewPlayer(motion,context=self.context.isChecked(),parent=self)
                    self._frame_times=[i*1000/motion.get('fps',24) for i in range(motion['frame_count'])]
                else:
                    try:self._frame_times=movie_frame_times(path)
                    except (OSError,ValueError):self._frame_times=[]
                    self.movie=QMovie(path);self.movie.setParent(self);self.movie.setCacheMode(QMovie.CacheAll)
                self.movie.frameChanged.connect(self._frame)
                if isinstance(self.movie,QMovie):self.movie.finished.connect(self._loop_finished)
                self.scrubber.blockSignals(True)
                self.movie.jumpToFrame(0);self._speed()
                self.scrubber.setMaximum(max(1,self.movie.frameCount()-1));self.scrubber.blockSignals(False)
                transparent=c.get('full_frame_preview','') if self.context.isChecked() else c.get('preview_receipt',{}).get('transparent_picture','')
                poster=QPixmap(transparent or c.get('preview_picture') or self.previews.get(c['id'],''))
                if not poster.isNull():
                    self.picture.original=poster;self.picture.setPixmap(poster.scaled(self.picture.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            elif path:
                self.picture.original=QPixmap(path);self.picture.setPixmap(self.picture.original.scaled(self.picture.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            else:
                errors=c.get('technical_errors',[])
                reason=str(errors[0].get('constraint') or errors[0].get('actual') or '')[:150] if errors else '设计方向已保存，等待完整实现'
                (bind_text(self.picture, '正在处理此方向') if c.get('pending') else bind_text(self.picture, '预览尚未就绪\n{value0}', value0=reason))
            if self.movie:self._start_playback()
            self._sync_play_button()
        duration=motion.get('duration_ms',6000)
        (bind_text(self.preview_notice, '完整演示 {value0:g}s · 实际采用保持原字幕时长 · {value1}', value0=duration / 1000, value1=tr('适配作品大小') if not self.context.isChecked() else tr('真实画面占比')) if ready else (bind_text(self.preview_notice, '仅静态预览，动画未完成') if path else bind_text(self.preview_notice, '')))
        self.preview_notice.setVisible(bool(self.preview_notice.text()))
        self.play_button.setEnabled(bool(self.movie));self.scrubber.setEnabled(bool(self.movie));self.context.setEnabled(bool(motion.get('context')))
        self.background.setEnabled(bool(motion.get('transparent_frames')) and not (self.context.isChecked() and selected.get('background')=='current-media'))
        (bind_text(self.background, '背景仅用于观看，不进入透明导出', property='toolTip') if self.background.isEnabled() else bind_text(self.background, '旧预览未提供透明序列，保留原预渲染背景', property='toolTip'))
        self.details['设计说明'].setPlainText(str(c.get('composition','')))
        spec=c.get('authored_theme',{}).get('motionSpec',{})
        pixel_tracks={t.get('phase'):t.get('pixels',{}).get('mode') for t in spec.get('tracks',[]) if t.get('pixels')}
        entries={'alchemy':'字框像素簇从短距离显形归位','mineral':'带原字框纹理的格块落位、轻微回弹','sigil':'字框像素从符印锚点展开召唤'}
        exits={'alchemy':'原字框像素变暖、分簇上浮衰减','mineral':'原字框按空间顺序释放并重力下坠','sigil':'字框分组向符印锚点收回，法印最后熄灭'}
        motion_text=(f"入场：{entries.get(pixel_tracks.get('build'),'按原稿动作进入')}（{spec.get('buildMs',0):g} ms）\n"
            f"阅读：保持原稿字体、颜色、框形和布局\n退场：{exits.get(pixel_tracks.get('resolve'),'按原稿动作退出')}（{spec.get('resolveMs',0):g} ms）\n\n"
            '支持完整播放、入场/退场定位、慢放与拖动。完整动作参数见“源码与诊断”。')
        self.details['动效'].setPlainText(motion_text if spec else '尚未取得可运行的动作定义')
        if spec.get('timingProfile')=='readable-pixel':
            self.details['动效'].appendPlainText('正常句 >3秒：完整建立 / 能量熄灭与边缘崩解。\n1.8–3秒：320ms 入场、280ms 退场；更早进入阅读。\n短于1.8秒：最多110ms入退场、微量像素位移；≤260ms直接阅读。\n主文字在入场47%前归位；退场含45ms清场余量。')
        self.details['生成记录'].setPlainText(json.dumps({k:c.get(k) for k in ('latest_attempt','source_origin','ledger_path','automatic_completion','source_recovery','reference_research') if c.get(k)},ensure_ascii=False,indent=2))
        source=c.get('authored_theme',{})
        self.details['源码与诊断'].setPlainText(json.dumps(c.get('technical_errors',[]),ensure_ascii=False,indent=2)+'\n'+str(c.get('preview_integrity_error',''))+'\n\n'+json.dumps(source,ensure_ascii=False,indent=2))
        action,label,help_text=primary_action(c);self._action=action
        self.primary.setText(label);self.primary.setToolTip(help_text)
        self.primary.setMinimumWidth(self.primary.fontMetrics().horizontalAdvance(label)+38)
        self.primary.setObjectName('studioPrimary' if action=='adopt' else 'recovery-'+action)
        menu=QMenu(self.more)
        for mode,label,tip in [('preview','仅重建预览','零模型调用'),('implementation','仅补全实现正文','保留已有分节；至多一次请求'),('rebuild','从已有说明重新生成实现','保留旧版；至多一次请求')]:
            item=menu.addAction(label);item.setToolTip(tip);item.setEnabled(not c.get('pending') and (mode!='preview' or bool(source)))
            item.triggered.connect(lambda checked=False,m=mode:self._request(m))
        menu.addSeparator();item=menu.addAction('完整重做该方向…');item.triggered.connect(lambda:self.redo_requested.emit(self.current_concept()['id']))
        old=self.more.menu();self.more.setMenu(menu)
        if old:old.deleteLater()
        self.refresh_task_states()

    def _primary(self):
        c=self.current_concept()
        if self._action=='adopt':self.choose(c['id'])
        elif self._action=='cancel':
            self.show_action_feedback(c['id'],'正在停止本地任务；已收到内容保留。供应商端状态未知。')
            self.cancel_requested.emit(c['id'])
        else:self._request(self._action)

    def _request(self,mode):
        c=self.current_concept()
        self.show_action_feedback(c['id'],'正在检查请求并建立任务…')
        self.recovery_requested.emit(c['id'],mode)

    def show_action_feedback(self,key,message,*,busy=False):
        self.feedback[key]=str(message)
        if self.current_concept().get('id')==key:self.action_feedback.setText(message);self.action_feedback.setVisible(bool(message))
        if busy:
            bind_text(self.primary, '停止并保留');self._action='cancel'

    def set_task_states(self,states):
        self.task_states=states;self.refresh_task_states()

    def refresh_task_states(self):
        import time
        from .design_progress import status_text,compact_status,candidate_status,ACTIVE_STATES
        c=self.current_concept();state=self.task_states.get(c.get('id'),{})
        status=candidate_status(c,state);busy=status in ACTIVE_STATES
        menu=self.more.menu()
        if menu:
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(not busy and (action.text()!='仅重建预览' or bool(c.get('authored_theme'))))
        activity=dict(state.get('activity') or {})
        if state.get('stage') in {'technical_validation','rendering','ready','render_validation','render_pending'}:
            activity['production_state']=state.get('detail') or {'technical_validation':'源码检查中','rendering':'生成真实预览中','ready':'完整预览已就绪','render_validation':'预览检查失败','render_pending':'等待重建预览'}[state['stage']]
        if not activity:
            activity=dict(local_state=state.get('detail') or self.badge(c),status=state.get('status','idle'),production_state=self.badge(c))
            if c.get('authored_theme'):
                activity.update(body_summary='完整源码已保存',transport_summary='本次为本地预览；没有远端进度记录')
        summary=[self.badge(c,state)]
        if c.get('motion_preview',{}).get('status')=='motion_ready':summary.append('本地预览')
        if c.get('authored_theme'):summary.append('源已保存')
        progress_line=compact_status(activity,time.monotonic(),state=state) if state else ''
        self.status.setText('   ·   '.join(summary)+('\n'+progress_line if progress_line else ''))
        # Empty preview must update even when its (candidate, path) cache key
        # is unchanged. A stopped task never keeps the running placeholder.
        if not self.movie and self.picture.original.isNull():
            errors=c.get('technical_errors',[])
            reason=state.get('error') or (errors[0].get('constraint','') if errors else '')
            saved='完整源码已保存' if c.get('authored_theme') else '已有说明与收到的正文已保存'
            self.picture.setText((compact_status(activity,time.monotonic(),state=state)+'\n\n'+saved) if busy else self.badge(c,state)+'\n'+str(reason)[:300]+'\n'+saved)
        for i,peer in enumerate(self.concepts):
            item=self.candidate_list.item(i)
            if item:item.setText(peer['name']+'\n'+self.badge(peer,self.task_states.get(peer['id'])))
        statuses=[candidate_status(peer,self.task_states.get(peer['id'])) for peer in self.concepts]
        bind_text(self.overview, '字幕视觉方向 · {value0} 候选 · {value1} 就绪{value2}', value0=len(statuses), value1=statuses.count('ready'), value2=f' · {sum((s in ACTIVE_STATES for s in statuses))} 处理中' if any((s in ACTIVE_STATES for s in statuses)) else '')
        import json
        details=status_text(activity,time.monotonic())+'\n\n'+json.dumps({k:c.get(k) for k in ('latest_attempt','source_origin','ledger_path','automatic_completion','source_recovery','reference_research') if c.get(k)},ensure_ascii=False,indent=2)
        field=self.details['生成记录'];bar=field.verticalScrollBar()
        if field.toPlainText()!=details:
            position=bar.value();follow=position>=bar.maximum()-3
            field.setPlainText(details);bar.setValue(bar.maximum() if follow else position)
        self.action_feedback.setText(self.feedback.get(c.get('id'),''));self.action_feedback.setVisible(bool(self.action_feedback.text()))
        if busy:
            bind_text(self.primary, '停止并保留');self._action='cancel'
        else:
            from .candidate_attempt import primary_action
            effective=dict(c,pending=False)
            if status in {'failed','cancelled'}:effective['technical_status']='failed'
            self._action,label,tip=primary_action(effective)
            self.primary.setText(label);self.primary.setToolTip(tip)

    def refresh_theme_palette(self):
        from .studio_theme import build_studio_qss
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        from .candidate_controls import workbench_qss
        self._work_theme=theme_definition(theme_key())
        self.setStyleSheet(build_studio_qss(self._work_theme)+workbench_qss(self._work_theme))
        self._sync_play_button()

    def _sync_play_button(self):
        from .candidate_controls import playback_icon
        running=bool(self.movie and self.movie.state()==QMovie.Running)
        self.play_button.setText('')
        self.play_button.setIcon(playback_icon(running,self._work_theme.text))
        label='暂停' if running else '播放'
        self.play_button.setAccessibleName(label)
        bind_text(self.play_button, '{value0} · 自动循环；也可点击作品', property='toolTip', value0=label)

    def _frame_range(self):
        from bisect import bisect_left
        last=max(0,self.movie.frameCount()-1)
        if not self._frame_times:return 0,last
        c=self.current_concept();spec=c.get('authored_theme',{}).get('motionSpec',{})
        if self.segment.currentIndex()==1:
            return 0,min(last,max(0,bisect_left(self._frame_times,spec.get('buildMs',500))))
        if self.segment.currentIndex()==2:
            duration=c.get('motion_preview',{}).get('duration_ms',6000)
            return min(last,bisect_left(self._frame_times,duration-spec.get('resolveMs',500))),last
        if self.segment.currentIndex()==3:
            duration=c.get('motion_preview',{}).get('duration_ms',6000)
            return min(last,bisect_left(self._frame_times,spec.get('buildMs',500))),min(last,bisect_left(self._frame_times,duration-spec.get('resolveMs',500)))
        return 0,last

    def _frame(self,frame):
        if not self.movie:return
        first,last=self._frame_range()
        if self.movie.state()==QMovie.Running and (frame<first or frame>last):
            movie=self.movie
            QTimer.singleShot(0,lambda:self._restart_segment(movie))
            return
        self.picture.original=self.movie.currentPixmap()
        self.picture.setPixmap(self.picture.original.scaled(self.picture.contentsRect().size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        blocked=self.scrubber.blockSignals(True);self.scrubber.setValue(frame);self.scrubber.blockSignals(blocked)
        elapsed=self._frame_times[min(frame,len(self._frame_times)-1)] if self._frame_times else 0
        duration=self.current_concept().get('motion_preview',{}).get('duration_ms',6000)
        self.timecode.setText(f'{elapsed/1000:.2f} / {duration/1000:.2f}s')

    def _restart_segment(self,movie):
        if movie is self.movie and movie.state()==QMovie.Running:
            movie.jumpToFrame(self._frame_range()[0])

    def _loop_finished(self):
        if self.isVisible() and self.movie:self._start_playback(reset=True)

    def _start_playback(self,reset=False):
        if not self.movie:return
        first,last=self._frame_range()
        if reset or not first<=self.movie.currentFrameNumber()<=last:self.movie.jumpToFrame(first)
        if self.movie.state()==QMovie.NotRunning:self.movie.start()
        else:self.movie.setPaused(False)
        self._sync_play_button()

    def _speed(self,*_):
        if self.movie:self.movie.setSpeed(50 if self.speed.currentIndex() else 100)

    def _background(self,index):
        self.picture.background_mode=index;self.picture.update()

    def _segment(self,*_):
        if self.movie:self._start_playback(reset=True)

    def seek_frame(self,frame):
        if self.movie:
            self.movie.setPaused(True);self.movie.jumpToFrame(frame);self._sync_play_button()

    def toggle_play(self):
        if not self.movie:return
        if self.movie.state()==QMovie.Running:
            self.movie.setPaused(True);self._sync_play_button()
        else:self._start_playback()

    def choose(self,key):
        from .candidate_attempt import primary_action,revision
        c=next((c for c in self.concepts if c['id']==key),{})
        if primary_action(c)[0]!='adopt':
            self.show_action_feedback(key,'当前版本尚未完成源码与预览验证，不能采用');return
        self.selected_id=key;self.selected_revision=revision(c);self.accept()

    def enlarge(self):
        c=self.current_concept()
        if c.get('motion_preview',{}).get('status')=='motion_ready':self.play(c)
        elif self.previews.get(c.get('id')):SubjectPreviewDialog(c,self.previews[c['id']],self).exec()

    def play(self,concept):
        dialog=MotionPreviewDialog(concept,self);dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.show()

    def done(self,value):
        if self.movie:self.movie.stop()
        super().done(value)
