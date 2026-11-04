"""Owned real-project interaction measurements through the normal MainWindow."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import time


def start(window, output):
    from . import real_long_project_audit
    real_long_project_audit.start(window, output)
    audit = window._real_long_project_audit
    if os.environ.get('INTERACTIONS_OBSERVE') == '1':
        audit.check = lambda name, value: audit.checks.__setitem__(name, bool(value))
    audit.sequence = run(audit, window, output)


def run(a, window, output):
    from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.studio_edit_sequence import sequence_of
    from ..timeline.studio_media_pool import media_usage

    app = QApplication.instance()
    window.resize(1440, 900)
    yield .3
    a.set_phase('open')
    began = time.perf_counter()
    window.open_studio_project(str(a.project_path))
    yield a.wait(a.ready, 'real project ready', 110)
    a.page = p = window.built_page('studio')
    t = p.timeline
    p.video.set_paused(True)
    p.volume_slider.setValue(0)
    if os.environ.get('INTERACTIONS_VISIBLE')=='1':
        import ctypes
        from PySide6.QtGui import QCursor
        original_cursor=QCursor.pos()
        window.raise_();window.activateWindow()
        user=ctypes.windll.user32
        user.GetForegroundWindow.restype=ctypes.c_void_p
        user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
        user.SetForegroundWindow(int(window.winId()))
        yield a.wait(lambda:user.GetForegroundWindow()==int(window.winId()),'owned window foreground',20)
        a.result['foreground_verified']=True
        def restore_cursor():
            last=getattr(a,'last_cursor',None)
            if last is not None and QCursor.pos()==last:QCursor.setPos(original_cursor)
        app.aboutToQuit.connect(restore_cursor)
    a.result['open_ms'] = (time.perf_counter()-began)*1000
    a.result['project'] = dict(cues=len(p.project.cues),
        translations=len(p.project.generation_metadata.get('translations', {})),
        duration_ms=p.project.media.duration_ms, video_tracks=len(p.project.video_tracks),
        audio_tracks=len(p.project.audio_tracks), dpr=window.devicePixelRatioF(), size=[window.width(),window.height()])
    paints = a.result['timeline_measurements'] = []
    original_paint = t._paint_timeline
    def measured(event):
        at = time.perf_counter()
        original_paint(event)
        paints.append(dict(phase=a.phase, at=at, ms=(time.perf_counter()-at)*1000,
            start=t.visible_start_ms, span=t.visible_duration_ms, stats=dict(getattr(t,'_last_paint_stats',{}))))
    t._paint_timeline = measured
    yield .6
    part=os.environ.get('INTERACTIONS_PART','all')
    if part in ('all','timeline','proofread'):
        yield from timeline_suite(a,window,output)
    if part in ('all','proofread'):
        yield from review_suite(a,window,output)
    if part in ('all','source'):
        yield from source_suite(a,window,output)
    if part == 'colors':
        yield from colors_suite(a,window,output)
    t._paint_timeline=original_paint


def timeline_suite(a,window,output):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.studio_edit_sequence import sequence_of
    from ..timeline.studio_media_pool import media_usage
    app=QApplication.instance()
    p=a.page;t=p.timeline
    count=int(os.environ.get("INTERACTIONS_CYCLES","5"))
    a.set_phase('timeline-zoom')
    p.workspace_splitter.setSizes([350,520])
    t.set_group_expanded(True)
    t.vertical_scrollbar.setValue(t.vertical_scrollbar.maximum())
    a.result['timeline_viewport']=dict(workspace_sizes=p.workspace_splitter.sizes(),
        vertical=t.vertical_scrollbar.value(),maximum=t.vertical_scrollbar.maximum())
    for repeat in range(2):
        for span in (p.project.media.duration_ms, 3600000, 900000, 240000, 90000, 60000, 30000, 60000, 240000, 900000):
            a.action('zoom', lambda s=span:t.set_visible_window(1000000,s), span=span,repeat=repeat)
            yield .12
            if span==30000 and repeat==0:
                a.set_phase('text-threshold-evidence')
                _capture(window,output/'text-threshold.png')
                a.set_phase('timeline-zoom')
        for offset in range(12):
            a.action('horizontal-scroll',lambda n=offset:t.set_visible_window(1000000+n*8000,90000),repeat=repeat)
            yield .05
    _capture(window,output/'long-timeline.png')
    a.set_phase('seeks')
    for index in (10, 3480, 6700, 30, 3500, 6800):
        cue=p.project.cues[index]
        yield from a.seek(cue.start_ms+min(300,(cue.end_ms-cue.start_ms)//2),'seek-'+str(index))
        yield .12
    _capture(window,output/'long-captions.png')
    if os.environ.get('INTERACTIONS_COMPLEX')=='1':
        a.set_phase('complex-caption-seeks');a.apply_styles();yield .5
        for repeat in range(2):
            for cue_id in a.complex_ids:
                cue=p.session.runtime.cue_by_id[cue_id]
                target=cue.start_ms+min(300,(cue.end_ms-cue.start_ms)//2)
                yield from a.seek(target,'complex-'+str(repeat)+'-'+cue_id)
                yield .15
        _capture(window,output/'complex-captions.png')
        # A burst is submitted without awaiting obsolete requests.
        targets=[p.project.cues[i].start_ms+100 for i in (100,5900,700,4000,6800)]
        for target in targets:p._seek(target/1000)
        yield a.wait(lambda:a.seek_ready(targets[-1]),'latest of rapid seeks',25)
        a.check('rapid-seek-latest-position',abs(t.playhead_ms-targets[-1])<150)
        _capture(window,output/'rapid-seek-final.png')


def review_suite(a,window,output):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.studio_edit_sequence import sequence_of
    from ..timeline.studio_media_pool import media_usage
    app=QApplication.instance()
    p=a.page;t=p.timeline
    count=int(os.environ.get("INTERACTIONS_CYCLES","5"))
    a.set_phase('proofread')
    from ..app.ui_zoom import zoom_percent
    state=lambda: dict(span=t.visible_duration_ms,start=t.visible_start_ms,playhead=t.playhead_ms,
        preview_quality=p.video.preview_scale(),ui_zoom=zoom_percent(),
        sizes=p.workspace_splitter.sizes(),upper_sizes=p.upper_splitter.sizes())
    review_rows=a.result['proofread_cycles']=[]
    count=int(os.environ.get('INTERACTIONS_CYCLES','5'))
    for cycle in range(count):
        prior=state()
        a.action('open-proofread',window._open_studio_glossary_proofread,cycle=cycle)
        review=window.glossary_proofread_page
        yield a.wait(lambda:not review.checks_running(),'review checks done',90)
        for scope in ('translation','both','original'):
            combo=review.text_targets.mode
            index=combo.findData(scope)
            if index>=0:
                a.action('text-scope',lambda i=index:combo.setCurrentIndex(i),scope=scope,cycle=cycle)
                yield .15
        a.action('return-studio',lambda:QTest.mouseClick(review.back_button,Qt.LeftButton),cycle=cycle)
        yield .2
        after=state()
        review_rows.append(dict(cycle=cycle,before=prior,after=after))
        a.check('proofread-state-'+str(cycle),prior==after)
        for index in range(2):
            yield from button_feedback(a,p.cue_list_toggle_button,window,cycle,index)
    _capture(window,output/'proofread-return.png')


def button_feedback(a,button,window,cycle,repeat):
    from PySide6.QtCore import QObject,QEvent,QTimer,Qt,QPointF
    from PySide6.QtGui import QMouseEvent,QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import threading
    class Observer(QObject):
        def __init__(self):
            super().__init__(button);self.pending=None;self.records=[]
        def eventFilter(self,obj,event):
            row=self.pending
            if row is not None:
                if event.type() in (QEvent.Enter,QEvent.HoverEnter,QEvent.MouseButtonPress):
                    row.setdefault('received_at',time.perf_counter())
                elif event.type()==QEvent.Paint and 'paint_at' not in row:
                    row['paint_at']=time.perf_counter()
                    def done():
                        row['raster_delivery_at']=time.perf_counter()
                    QTimer.singleShot(0,done)
            return False
    observer=Observer();button.installEventFilter(observer)
    metrics=a.result.setdefault('button_feedback',[])
    visible=os.environ.get('INTERACTIONS_VISIBLE')=='1'
    away=window.rect().topLeft()+__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(12,12)
    if visible:
        a.last_cursor=window.mapToGlobal(away);QCursor.setPos(a.last_cursor)
    else:QTest.mouseMove(window,away)
    yield a.wait(lambda:not button.underMouse(),'pointer leaves owned button',2)
    yield .06
    from .button_feedback_probe import ButtonPixels
    probe=ButtonPixels(button,window) if visible else None
    normal=probe.sample() if probe is not None else button.grab().toImage()
    if probe is not None and normal is None:raise RuntimeError('Test window lost foreground ownership')
    def changed(row,reference):
        deadline=time.perf_counter()+1.2
        def ready():
            pixels=probe.sample()
            if pixels is not None and pixels!=reference:
                row.update(screen_changed_at=time.perf_counter(),visual_changed=True)
                return True
            if time.perf_counter()>deadline:
                row['visual_changed']=False
                return True
            return False
        return ready
    row=dict(kind='hover',cycle=cycle,repeat=repeat,sent_at=time.perf_counter())
    observer.pending=row
    if visible:
        a.last_cursor=button.mapToGlobal(button.rect().center());QCursor.setPos(a.last_cursor)
    else:QTest.mouseMove(button,button.rect().center())
    if probe is not None:
        yield changed(row,normal)
        hovered=probe.sample()
        row['under_mouse']=button.underMouse()
    else:
        yield a.wait(lambda:'raster_delivery_at' in row,'hover paint feedback',2)
        hovered=button.grab().toImage()
        row.update(visual_changed=hovered!=normal,under_mouse=button.underMouse())
    metrics.append(row)
    a.check(f'hover-visible-{cycle}-{repeat}',row['visual_changed'] and row['under_mouse'])
    row=dict(kind='press',cycle=cycle,repeat=repeat)
    observer.pending=row
    local=QPointF(button.rect().center());global_point=QPointF(button.mapToGlobal(local.toPoint()))
    event=QMouseEvent(QEvent.MouseButtonPress,local,global_point,Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    def post():
        row['sent_at']=time.perf_counter();QApplication.postEvent(button,event)
    thread=threading.Thread(target=post,name='owned-button-input');thread.start()
    # A pending hover paint can change pixels before the posted press arrives.
    # Acknowledge the actual input before interpreting its visual feedback.
    yield a.wait(lambda:'received_at' in row and button.isDown(),'press input delivered',2)
    if probe is not None:yield changed(row,hovered)
    else:
        yield a.wait(lambda:'raster_delivery_at' in row,'press paint feedback',2)
        row['visual_changed']=button.grab().toImage()!=hovered
    row['down']=button.isDown()
    metrics.append(row)
    a.check(f'press-visible-{cycle}-{repeat}',row['down'] and row['visual_changed'])
    QTest.mouseRelease(button,Qt.LeftButton,pos=button.rect().center());yield .06
    button.removeEventFilter(observer);observer.deleteLater()
    if probe is not None:probe.close()


def source_suite(a,window,output):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.studio_edit_sequence import sequence_of
    from ..timeline.studio_media_pool import media_usage
    app=QApplication.instance()
    p=a.page;t=p.timeline
    count=int(os.environ.get("INTERACTIONS_CYCLES","5"))
    a.set_phase('pool-source')
    p.context_drawer.setCurrentIndex(p.media_pool_tab_index)
    pool=p.media_pool_panel
    pool.show()
    fixtures=Path(os.environ['INTERACTIONS_FIXTURES'])
    def graph():
        return copy.deepcopy((p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups,
            sequence_of(p.project),t.playhead_ms))
    before=graph(); undo_index=p.undo_stack.index()
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(fixtures/'red.mp4')),QUrl.fromLocalFile(str(fixtures/'blue.mp4'))])
    view=pool.assets.viewport(); point=view.rect().center()
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    app.sendEvent(view,enter)
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    app.sendEvent(view,drop)
    a.result['pool_drop']=dict(enter_accepted=enter.isAccepted(),drop_accepted=drop.isAccepted())
    if not drop.isAccepted():
        # Native DND falls through to the accepting Studio parent.
        parent_point=view.mapTo(p,point)
        parent=QDropEvent(QPointF(parent_point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        p.dropEvent(parent)
    yield a.wait(lambda: any(Path(x.canonical_source).name=='blue.mp4' for x in p.project.media_pool),'pool imports ready',50)
    yield .4
    a.check('pool-import-preserves-timeline',graph()==before)
    a.check('pool-assets-unused',all(not media_usage(p.project).get(x.asset_id) for x in p.project.media_pool
        if Path(x.canonical_source).name in {'red.mp4','blue.mp4'}))
    _capture(window,output/'pool-import.png')
    if graph()!=before:
        while p.undo_stack.index()>undo_index:
            p.undo_stack.undo()
        pool.import_paths([fixtures/'red.mp4',fixtures/'blue.mp4'])
        yield a.wait(lambda:any(Path(x.canonical_source).name=='blue.mp4' for x in p.project.media_pool),'explicit pool-only recovery',30)
    m=p.source_monitor
    m.volume.setValue(0)
    assets=[x for x in p.project.media_pool if Path(x.canonical_source).name in {'red.mp4','blue.mp4'}]
    a.result['source_cycles']=[]
    for cycle in range(count):
        before=graph()
        p._set_major_panel_visible('cue_list',True)
        p.source_tabs.setCurrentIndex(1)
        m.open_asset(assets[cycle%len(assets)].asset_id)
        yield a.wait(lambda:m.controller is not None and not m.loading,'source loaded',25)
        m.clear_range();m.seek(2000);yield .5
        m.setFocus()
        a.action('source-in',lambda:QTest.keyClick(m,Qt.Key_I),cycle=cycle)
        m.seek(6000);yield .5
        a.action('source-out',lambda:QTest.mouseClick(m.point_buttons['out_ms'],Qt.LeftButton),cycle=cycle)
        a.check('source-io-'+str(cycle),m.range_ms()==(2000,6000))
        QTest.mouseClick(m.play_button,Qt.LeftButton);yield .45
        a.check('source-progress-'+str(cycle),m.position_ms>6000 and not m.paused)
        m.pause()
        a.check('source-isolated-'+str(cycle),graph()==before)
        a.result['source_cycles'].append(dict(cycle=cycle,source_hwnd=int(m.surface.winId()),
            main_hwnd=int(p.video.winId()),source_position=m.position_ms,range=m.range_ms()))
        import psutil
        process=psutil.Process()
        a.result['source_cycles'][-1]['resources']=dict(rss=process.memory_info().rss,
            threads=process.num_threads(),handles=process.num_handles(),widgets=len(app.allWidgets()),
            player_pid=getattr(getattr(m.controller,'_process',None),'pid',None))
        _capture(window,output/('source-'+str(cycle)+'.png'))
        m.close_source();yield .25
        resume_at=time.perf_counter();QTest.mouseClick(p.play_button,Qt.LeftButton)
        yield a.wait(lambda:not p.video._paused and t.playhead_ms>before[-1]+50,'sequence resumes after source',12)
        a.result['source_cycles'][-1]['sequence_resume_ms']=(time.perf_counter()-resume_at)*1000
        a.result['source_cycles'][-1]['sequence_state']=dict(paused=p.video._paused,position=t.playhead_ms,
            prior=before[-1],observed=p.video.controller.observed_properties())
        a.check('sequence-resumes-'+str(cycle),not p.video._paused and t.playhead_ms>before[-1])
        p.video.set_paused(True)

    # An explicit insertion owns the entire newly created AV graph and undo.
    p.source_tabs.setCurrentIndex(1);m.open_asset(assets[0].asset_id)
    yield a.wait(lambda:m.controller is not None and not m.loading,'insert source ready',25)
    m.clear_range();m.set_boundary('in_ms',2000);m.set_boundary('out_ms',6000)
    for mode in ('av','video','audio'):
        m.set_mode(mode);yield .15
        before=graph();index=p.undo_stack.index()
        a.action('explicit-source-insert',m.insert,mode=mode)
        yield .25
        a.check(mode+'-one-insert',p.undo_stack.index()==index+1)
        command=p.undo_stack.command(index)
        a.check(mode+'-four-second-selection',command.placement['end_ms']-command.placement['start_ms']==4000)
        if mode=='av':_capture(window,output/'explicit-av-composition.png')
        p.undo_stack.undo();yield .3
        after=graph()
        receipt=dict(mode=mode,parts_equal=[x==y for x,y in zip(before[:-1],after[:-1])],
            before_head=before[-1],after_head=after[-1],delta_ms=after[-1]-before[-1])
        a.result.setdefault('explicit_insert_undo',[]).append(receipt)
        a.check(mode+'-complete-undo',all(receipt['parts_equal']) and abs(receipt['delta_ms'])<=40)
    before=graph();m.time_edit.setFocus();m.time_edit.setText('')
    QTest.keyClicks(m.time_edit,'io')
    a.check('source-text-input-keeps-io-keys',m.time_edit.text()=='io' and graph()==before)
    m.time_edit.setText('00:00:03.000');m.setFocus();yield .1
    old=m.controller;old._process.terminate()
    yield a.wait(lambda:m.controller is None,'dead source detached',10)
    a.check('dead-source-transport-recovers',not m.loading)
    m.open_asset(assets[0].asset_id)
    yield a.wait(lambda:m.controller is not None and not m.loading,'source retry after exit',25)
    a.check('source-retry-new-instance',m.controller is not old)
    m.close_source();yield .1
    QTest.mouseClick(p.play_button,Qt.LeftButton)
    yield a.wait(lambda:not p.video._paused,'sequence playing before source entry',10)
    position=t.playhead_ms
    p.source_tabs.setCurrentIndex(1);m.open_asset(assets[0].asset_id)
    yield a.wait(lambda:m.controller is not None and not m.loading,'source alongside playing sequence',25)
    m.toggle_play();yield .4
    a.check('source-does-not-pause-playing-sequence',not p.video._paused and t.playhead_ms>position)
    m.close_source()
    a.check('closing-source-keeps-sequence-playing',not p.video._paused)
    p.video.set_paused(True)
    yield a.wait(lambda:not m._retired_surfaces,'source old output hosts retired',10)
    a.check('source-retired-hosts-drained',not m._retired_surfaces)


def colors_suite(a,window,output):
    import json
    from dataclasses import asdict
    from PySide6.QtCore import QTimer,QPoint,Qt
    from PySide6.QtGui import QColor,QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from ..caption_style.scoped_style import effective_layer_style,effective_layer_recipe
    from ..projects.studio_project import save_project,load_project
    from .blank_project_audit import _capture
    p=a.page
    p.context_drawer.setCurrentIndex(1)
    p._set_major_panel_visible('context',True)
    p.select_cue(p.project.cues[10].id)
    p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
    a.set_phase('appearance-colors')
    fields=(('primary_color','style_fill_color'),('outline_color','style_outline_color'),
        ('outline2_color','style_outline2_color'),('back_color','style_back_color'),
        ('shadow.color','style_shadow_color'),('glow.color','style_glow_color'))
    a.result['color_edits']=[]
    def control_color(field,attribute):
        value=QColor(getattr(p,attribute).text())
        if field=='shadow.color':value.setAlpha(round(p.style_shadow_opacity.value()*255/100))
        return value
    def snapshot(layer):
        cue=p.session.runtime.cue_by_id[p.selected_cue_id]
        style=effective_layer_style(p.project,cue,layer)
        recipe=effective_layer_recipe(p.project,cue,layer,style=style)
        return dict(style=asdict(style),recipe=recipe.to_dict() if hasattr(recipe,'to_dict') else recipe)
    def visible_appearance(state):
        value=copy.deepcopy(state)
        value['recipe'].pop('name',None)
        effects=value['recipe'].get('effects',{})
        if not (effects.get('glow') or {}).get('enabled',False):effects.pop('glow',None)
        return value
    if os.environ.get('INTERACTIONS_COLOR_RESTART'):
        old=Path(os.environ['INTERACTIONS_COLOR_RESTART'])
        expected=json.loads((old/'result.json').read_text('utf8'))
        for layer in ('original','translation'):
            final=next(row['state'] for row in reversed(expected['color_edits']) if row['layer']==layer)
            a.check(layer+'-fresh-process-colors',json.loads(json.dumps(snapshot(layer)))==final)
        _capture(window,output/'colors-fresh-process.png')
        return
    def edit(field,editor,value,cancel,tag):
        state={};a.timer.stop()
        index=p.undo_stack.index()
        def drive():
            d=QApplication.activeModalWidget()
            if d is None:
                QTimer.singleShot(30,drive);return
            try:
                state['type']=type(d).__name__
                if state['type']!='FillEditorDialog':raise AssertionError(state['type'])
                wheel=d.picker.wheel;sv=d.picker.sv_square
                center=sv.mapTo(wheel,sv.plane_rect().center().toPoint())
                state['center_error']=[center.x()-wheel.width()/2,center.y()-wheel.height()/2]
                state['modes']=len(d.mode_group.buttons())
                QTest.mouseClick(wheel,Qt.LeftButton,pos=QPoint(wheel.width()//2+round(wheel._outer()-wheel._band()/2),wheel.height()//2))
                d.picker.hex_edit.setFocus();QTest.keyClick(d.picker.hex_edit,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClicks(d.picker.hex_edit,value[-6:]);QTest.keyClick(d.picker.hex_edit,Qt.Key_Tab)
                d.picker.alpha_spin.setValue(round(QColor(value).alpha()*100/255))
                state['during_index']=p.undo_stack.index()
                def finish():
                    try:
                        d.grab().save(str(output/(tag+'-dialog.png')))
                        state['color']=d.picker.color().name(QColor.HexArgb)
                        state['preview']=asdict(d.preview._style) if getattr(d.preview,'_style',None) is not None else None
                        if field=='outline_color':
                            import numpy as np
                            from PySide6.QtGui import QImage
                            sample=d.preview.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
                            pixels=np.frombuffer(sample.bits(),dtype=np.uint8).reshape(sample.height(),sample.bytesPerLine())
                            rgb=pixels[:,:sample.width()*4].reshape(sample.height(),sample.width(),4)[:,:,:3].astype(np.int16)
                            state['preview_orange_pixels']=int(((rgb[:,:,0]-rgb[:,:,1]>20)&(rgb[:,:,1]-rgb[:,:,2]>20)).sum())
                    finally:
                        d.reject() if cancel else d.accept()
                QTimer.singleShot(120,finish)
            except Exception as exc:
                state['error']=str(exc);d.reject()
        QTimer.singleShot(80,drive)
        try:
            p._open_fill_editor() if field=='primary_color' else p._open_style_color_dialog(editor)
        finally:a.timer.start()
        if state.get('error'):raise AssertionError(state['error'])
        a.check(tag+'-new-dialog',state.get('type')=='FillEditorDialog')
        a.check(tag+'-center',all(abs(v)<=1 for v in state['center_error']))
        a.check(tag+'-capabilities',state['modes']==(3 if field=='primary_color' else 1))
        a.check(tag+'-no-history-during-drag',state['during_index']==index)
        return state
    for layer in ('original','translation'):
        p.style_layer.setCurrentIndex(p.style_layer.findData(layer));yield .2
        for number,(field,attribute) in enumerate(fields):
            editor=getattr(p,attribute)
            before=snapshot(layer);other=snapshot('translation' if layer=='original' else 'original')
            prior_colors={name:control_color(name,control) for name,control in fields}
            index=p.undo_stack.index();tag=layer+'-'+field.replace('.','-')
            edit(field,editor,'#55AAEE',True,tag+'-cancel')
            yield .1
            a.check(tag+'-cancel-keeps-state',p.undo_stack.index()==index and snapshot(layer)==before)
            desired=(('#44CC88','#CCFF8A33','#CC8C6CFF','#992E4A72','#A655AAEE','#A6EE55AA')
                if layer=='original' else ('#EE77FF','#CCFFBB33','#CC3377DD','#99264C38','#A63388DD','#A6FFAA55'))[number]
            receipt=edit(field,editor,desired,False,tag)
            yield .35
            if field=='outline_color':
                a.check(tag+'-preview-stroke-pixels',receipt.get('preview_orange_pixels',0)>20)
            a.check(tag+'-one-history',p.undo_stack.index()==index+1)
            a.result['last_color_actual']=dict(field=field,layer=layer,expected=desired,
                actual=control_color(field,attribute).name(QColor.HexArgb))
            a.check(tag+'-right-field',control_color(field,attribute)==QColor(desired))
            differences={name:dict(before=prior_colors[name].name(QColor.HexArgb),after=control_color(name,control).name(QColor.HexArgb))
                for name,control in fields if name!=field and control_color(name,control)!=prior_colors[name]}
            if differences:a.result['color_differences']={tag:differences}
            a.check(tag+'-other-colors-kept',all(control_color(name,control)==prior_colors[name]
                for name,control in fields if name!=field))
            a.check(tag+'-other-layer-kept',visible_appearance(snapshot('translation' if layer=='original' else 'original'))==visible_appearance(other))
            after=snapshot(layer)
            for name in ('font_family','font_size','spacing','outline_width','outline2_width','shadow','margin_v','position_x','position_y'):
                a.check(tag+'-keeps-'+name,after['style'].get(name)==before['style'].get(name))
            p.undo_stack.undo();yield .1
            a.check(tag+'-undo',snapshot(layer)==before)
            p.undo_stack.redo();yield .15
            a.check(tag+'-redo',snapshot(layer)==after)
            a.result['color_edits'].append(dict(layer=layer,field=field,color=desired,state=after,dialog=receipt))
    saved=output/'colors-saved.2byteproj'
    save_project(p.project,saved)
    reopened=load_project(saved)
    a.check('color-save-reopen-cue-appearance',reopened.cues==p.project.cues)
    # Enable the existing effects on this owned rendering copy so the movie
    # actually exercises both strokes, translucent backgrounds, shadow/glow.
    for layer in ('original','translation'):
        p.style_layer.setCurrentIndex(p.style_layer.findData(layer));yield .1
        p.style_outline2.setChecked(True);p.style_background.setChecked(True);p.style_glow.setChecked(True)
        yield .3
    render_saved=output/'colors-render-project.2byteproj'
    save_project(p.project,render_saved)
    cue=p.session.runtime.cue_by_id[p.selected_cue_id]
    target=cue.start_ms+min(500,(cue.end_ms-cue.start_ms)//2)
    yield from a.seek(target,'colors-visible-preview')
    _capture(window,output/'colors-final-main.png')
    from ..projects.project_range import set_range
    start=cue.start_ms;end=min(cue.end_ms,start+3000)
    set_range(p.project,start,end,undo_stack=p.undo_stack)
    p._open_render_dialog(skip_preflight=True);yield .6
    ui=p.export_workspace
    a.check('color-export-workspace',ui is not None)
    ui.directory.setText(str(output));ui.filename_prefix.setText('');ui.filename_suffix.setText('')
    ui.filename.setText('colors-verified');ui.audio.setCurrentIndex(ui.audio.findData('none'))
    index=ui.encoder.findData('libx264')
    if index>=0:ui.encoder.setCurrentIndex(index)
    destination=ui.export_target().full_path
    ui.export_button.click()
    yield a.wait(lambda:not ui._running,'color production export',180)
    a.check('color-export-file',destination.is_file() and destination.stat().st_size>1000)
    a.result['color_video']=dict(path=str(destination),start_ms=start,end_ms=end,
        fill_colors={'original':'#44CC88','translation':'#EE77FF'})
    p._close_export_workspace()


