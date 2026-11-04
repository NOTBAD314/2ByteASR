"""Actual source widgets -> immutable MIME -> timeline drop -> normal command.

Uses Qt mouse/drag events on the actual Windows window. The drag executor is
controlled to deliver target events without relying on the input desktop;
this does not claim physical Windows pointer/OLE transport validation.
"""
def run(audit):
    import copy
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..studio import studio_source_monitor as module
    from ..timeline.studio_media_pool import create_video_track
    from ..timeline.studio_media_commands import media_graph_command
    from ..timeline.source_selection import source_boundary
    p=audit.page;t=p.timeline;m=p.source_monitor
    window=p.window();window.showMaximized()
    m.time_edit.clearFocus()
    yield .15
    m.pause();m.clear_range();m.seek(2520)
    yield from audit.wait(lambda:abs(m.position_ms-2520)<80,10,'source point input position ready')
    m.content_scroll.ensureWidgetVisible(m.point_buttons['in_ms']);yield .1
    expected=source_boundary(m.asset,m.position_ms)
    button=m.point_buttons['in_ms'];seen=[]
    button.clicked.connect(lambda:seen.append(True))
    QTest.mouseClick(button,Qt.LeftButton,pos=QPoint(7,button.height()//2));yield .1
    audit.check('whole point frame background sets once',m.range_ms()[0]==expected and len(seen)==1)
    m.seek(9000);yield from audit.wait(lambda:abs(m.position_ms-9000)<80,10,'source out input position ready')
    button=m.point_buttons['out_ms'];expected=source_boundary(m.asset,m.position_ms)
    pos=m.out_edit.mapTo(button,m.out_edit.rect().center())
    audit.check('timecode does not intercept single click',button.childAt(pos) is None)
    QTest.mouseClick(button,Qt.LeftButton,pos=pos);yield .1
    audit.check('whole point timecode sets current position',m.range_ms()[1]==expected)
    button=m.point_buttons['in_ms'];pos=m.in_edit.mapTo(button,m.in_edit.rect().center())
    QTest.mouseDClick(button,Qt.LeftButton,pos=pos)
    QTest.keyClick(m.in_edit,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(m.in_edit,'00:00:04.000')
    QTest.keyClick(m.in_edit,Qt.Key_Return);yield .1
    audit.check('double click edits timecode and locks it again',m.range_ms()[0]==4000 and m.in_edit.isReadOnly())
    QTest.mouseDClick(button,Qt.LeftButton,pos=pos)
    QTest.keyClick(m.in_edit,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(m.in_edit,'00:00:07.000')
    QTest.keyClick(m.in_edit,Qt.Key_Escape);yield .1
    audit.check('Escape keeps previous range',m.range_ms()[0]==4000 and m.in_edit.isReadOnly())
    audit.capture('whole-point-controls')
    made={}
    def add_target(project):made['video']=create_video_track(project).id
    p.undo_stack.push(media_graph_command(p.project,'验收拖放目标',add_target))
    t.set_visible_window(0,90000);yield .3
    before_cues=copy.deepcopy(p.project.cues)
    target={};captures=[];original_drag=module.QDrag
    expected_range=m.range_ms();expected_duration=expected_range[1]-expected_range[0]
    class RoutedDrag:
        def __init__(self,widget):self.widget=widget
        def setMimeData(self,mime):self.mime=mime
        def exec(self,_action):
            selection=module.selection_from_mime(p.project,self.mime);captures.append(selection)
            if target.get('cancel'):return Qt.IgnoreAction
            row=(t._audio_track_rects() if target.get('audio') else t._video_track_rects())[target['track']]
            point=QPoint(round(t._time_to_x(target['time'])),round(row.center().y()))
            target['actual_start']=max(0,int(t._x_to_time(point.x())))
            for event in (QDragEnterEvent(point,Qt.CopyAction,self.mime,Qt.LeftButton,Qt.NoModifier),
                          QDragMoveEvent(point,Qt.CopyAction,self.mime,Qt.LeftButton,Qt.NoModifier)):
                QApplication.sendEvent(t,event)
            if not target.get('invalid'):audit.capture('selected-range-drop-preview')
            event=QDropEvent(QPointF(point),Qt.CopyAction,self.mime,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(t,event)
            return event.dropAction() if event.isAccepted() else Qt.IgnoreAction
    def grab(widget):
        origin=QPoint(8,max(2,widget.height()//2))
        QTest.mousePress(widget,Qt.LeftButton,pos=origin)
        pos=QPointF(origin+QPoint(QApplication.startDragDistance()+8,0))
        QApplication.sendEvent(widget,QMouseEvent(QEvent.MouseMove,pos,QPointF(widget.mapToGlobal(pos.toPoint())),
            Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
        QTest.mouseRelease(widget,Qt.LeftButton,pos=pos.toPoint())
    module.QDrag=RoutedDrag
    try:
        m.set_mode('av');target.update(track=made['video'],time=60000)
        m.content_scroll.ensureWidgetVisible(m.selection_handle);yield .1
        before=p.undo_stack.index();grab(m.selection_handle);yield .3
        audit.check('selection title starts drag and one command',len(captures)==1 and p.undo_stack.index()==before+1)
        clips=[c for tr in p.project.video_tracks for c in tr.clips if tr.id==made['video']]
        first=clips[0]
        audit.result['measurements']['first_drop']={'actual':[first.timeline_in_ms,first.timeline_out_ms,first.source_in_ms,first.source_out_ms],
            'pixel_time':target['actual_start'],'source_range':expected_range}
        audit.check('drop uses target track time and source range',
            (first.timeline_in_ms,first.timeline_out_ms,first.source_in_ms,first.source_out_ms)==
            (target['actual_start'],target['actual_start']+expected_duration,*expected_range))
        group=next(g for g in p.project.av_track_groups if g.video_track_id==made['video'])
        audio=next(tr for tr in p.project.audio_tracks if tr.id==group.audio_track_id)
        audit.check('AV drag keeps linked selected audio stream',len(audio.clips)==1 and
            audio.clips[0].linked_video_clip_id==first.id and audio.clips[0].stream_index==1)
        m.set_mode('video');target['time']=70000
        grab(m.selection_card);yield .3
        audit.check('selection card background also starts drag',len(captures)==2 and captures[-1].mode=='video')
        clips=[c for tr in p.project.video_tracks for c in tr.clips if tr.id==made['video']]
        audit.check('second drag has its own target time',any(c.timeline_in_ms==target['actual_start'] and
                    c.timeline_out_ms==target['actual_start']+expected_duration for c in clips))
        m.set_mode('audio');target.update(audio=True,track=group.audio_track_id,time=80000)
        grab(m.selection_handle);yield .3
        audio=next(tr for tr in p.project.audio_tracks if tr.id==group.audio_track_id)
        audio_start=target['actual_start']
        audit.check('audio drag reaches audio track and time',any(c.timeline_in_ms==audio_start and
                    c.timeline_out_ms==audio_start+expected_duration and not c.linked_video_clip_id for c in audio.clips))
        graph=copy.deepcopy((p.project.video_tracks,p.project.audio_tracks))
        p.undo_stack.undo();yield .1
        audit.check('drag is one undo step',not any(c.timeline_in_ms==audio_start for tr in p.project.audio_tracks for c in tr.clips))
        p.undo_stack.redo();yield .1
        audit.check('redo restores drop exactly',(p.project.video_tracks,p.project.audio_tracks)==graph)
        before=p.undo_stack.index();target['cancel']=True;grab(m.selection_handle)
        audit.check('cancelled drag makes no command',p.undo_stack.index()==before)
        target.pop('cancel');target['invalid']=True
        m.set_mode('video');grab(m.selection_handle)
        audit.check('wrong track drop leaves graph unchanged',p.undo_stack.index()==before and (p.project.video_tracks,p.project.audio_tracks)==graph)
        target.update(audio=False,track=made['video'],time=85000)
        track=next(tr for tr in p.project.video_tracks if tr.id==made['video']);track.locked=True
        grab(m.selection_handle)
        audit.check('locked track rejects drop',p.undo_stack.index()==before)
        track.locked=False
        audit.check('existing captions preserved',p.project.cues==before_cues)
    finally:
        module.QDrag=original_drag
    audit.capture('range-dropped-on-tracks')
