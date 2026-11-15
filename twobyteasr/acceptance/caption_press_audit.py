"""Normal Studio entry: hit the rendered caption, drag and undo on owned media."""
def exercise(page, window, output, check, wait):
    import json
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..studio.canvas_visibility import visible_object_at
    from ..caption_style.caption_layer_transform import resolved_values
    controller=page._canvas_caption_press_controller()
    press=controller.press
    def observed_press(event):
        hit=visible_object_at(page,event.position())
        before=page.video._paused
        handled=press(event)
        (output/'press-observation.json').write_text(json.dumps(dict(hit=hit,before=before,after=page.video._paused,handled=handled,position=[event.position().x(),event.position().y()],selected=page.selected_cue_id,pending=bool(controller.pending))), 'utf8')
        return handled
    controller.press=observed_press

    def shot(name):
        window.grab().save(str(output/(name+'.png')))
        page.video.controller.screenshot_to_file(str(output/(name+'-native.png')))
    def point():
        scene=getattr(page,'_caption_scene',None)
        if scene is None:return None
        rows=scene.trace().get('cue_pixels',[])
        content=page.position_overlay._content_rect()
        for row in reversed(rows):
            if row.get('cue_id')!='a' or not row.get('bounds') or not row.get('viewport'):continue
            x,y,w,h=row['bounds'];vw,vh=row['viewport']
            p=QPointF(content.x()+(x+w/2)*content.width()/vw,content.y()+(y+h/2)*content.height()/vh)
            if visible_object_at(page,p)==('a','original'):return p.toPoint()
        return None
    def drag(start, delta, cancel=False):
        QTest.mousePress(page.video,Qt.LeftButton,Qt.NoModifier,start)
        for step in range(1,7):
            QTest.mouseMove(page.video,start+QPoint(round(delta.x()*step/6),round(delta.y()*step/6)),25)
            QApplication.processEvents()
            with (output/'drag-observation.jsonl').open('a',encoding='utf8') as f:
                overlay=page.position_overlay
                f.write(json.dumps(dict(step=step,pending=bool(controller.pending),started=controller.pending and controller.pending['started'],dragging=overlay._dragging,guard=overlay.interaction_guard(),paused=page.video._paused,position=[overlay.position_x,overlay.position_y],geometry=overlay.geometry_diagnostics,scene=page._caption_scene.trace().get('visible'))) + '\n')
        if cancel:QTest.keyClick(page.position_overlay,Qt.Key_Escape)
        QTest.mouseRelease(page.video,Qt.LeftButton,Qt.NoModifier,start+delta)
        QTest.qWait(250)
    page.video.set_paused(True);page._seek(.5);QTest.qWait(500)
    page.position_edit_button.setChecked(True)
    page.select_cue('b');page._sync_canvas_selection()
    wait(lambda:point() is not None)
    check('visible scene hit belongs to unselected caption',page.selected_cue_id=='b')
    shot('caption-before')
    cue=page._cue_lookup['a'];original=resolved_values(page.project,cue,'original').copy()
    undo=page.undo_stack.index()
    # Playing still shows a current scene. The actual canvas press must pause it.
    page.video.set_paused(False);QTest.qWait(100)
    wait(lambda:point() is not None)
    start=point();drag(start,QPoint(0,-45))
    check('canvas press pauses playback',page.video._paused)
    check('canvas press selects visible caption',page.selected_cue_id=='a')
    moved=resolved_values(page.project,cue,'original').copy()
    (output/'caption-transform.json').write_text(json.dumps(dict(before=original,after=moved),ensure_ascii=False,indent=2),'utf8')
    check('same gesture changes caption position',moved!=original)
    check('drag is one undo command',page.undo_stack.index()==undo+1)
    check('release retires gesture',page._canvas_caption_press.pending is None and not page.position_overlay._dragging)
    shot('caption-dragged')
    page.undo_stack.undo();QTest.qWait(300)
    check('undo restores exact transform',resolved_values(page.project,cue,'original')==original)
    page.undo_stack.redo();QTest.qWait(300)
    check('redo restores exact dragged transform',resolved_values(page.project,cue,'original')==moved)
    page.undo_stack.undo();QTest.qWait(300)
    page.select_cue('b');page._sync_canvas_selection();wait(lambda:point() is not None)
    undo=page.undo_stack.index();drag(point(),QPoint(0,-35),cancel=True)
    check('escape cancels without a command',page.undo_stack.index()==undo and resolved_values(page.project,cue,'original')==original)
    page.position_edit_button.setChecked(False);page.select_cue('b');page._sync_canvas_selection()
    wait(lambda:point() is not None);drag(point(),QPoint(0,-35))
    check('toggle off still selects but does not change transform',page.selected_cue_id=='a' and resolved_values(page.project,cue,'original')==original and page.undo_stack.index()==undo)
    page.position_edit_button.setChecked(True)
    check('toggle remains enabled',page.position_edit_button.isChecked())
    page.select_cue('b');page._sync_canvas_selection();wait(lambda:point() is not None)
    before=page.selected_cue_id
    QTest.mouseClick(page.video,Qt.LeftButton,Qt.ControlModifier,point())
    check('modified click preserves existing selection behavior',page.selected_cue_id==before)
    QTest.mouseClick(page.video,Qt.LeftButton,Qt.NoModifier,QPoint(4,4))
    check('empty picture does not select a caption',page.selected_cue_id==before)
    page.select_cue('a');page._seek(.5);QTest.qWait(300)
