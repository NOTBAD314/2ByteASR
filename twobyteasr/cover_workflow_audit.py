"""Opt-in normal-entry cover workflow acceptance. All outputs are isolated."""
import copy,hashlib,json,os,time,traceback
from pathlib import Path
from PySide6.QtCore import QPoint,QPointF,QTimer,Qt,QEvent,QMimeData,QUrl
from PySide6.QtGui import QImage,QInputMethodEvent,QCursor,QMouseEvent,QWheelEvent,QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox,QComboBox,QFileDialog,QLineEdit,QMessageBox,QPushButton,QInputDialog
from .studio_acceptance_audit import require


def start(window,out):
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
    def run():
        from .build_identity import load_build_identity
        from .cover_psd import psd_metadata
        from .cover_render import CoverRenderer,export_image
        from .cover_samples import demo_character
        from .cover_templates_ui import TemplatePicker
        import psutil
        report=dict(passed=False,checks={},build=load_build_identity().to_dict(),metrics=[],resources=[])
        begun=time.perf_counter();page=window.studio_page;work=None;local=None;timers=[]
        def pump(seconds=.05):
            until=time.monotonic()+seconds
            while time.monotonic()<until:QApplication.processEvents();time.sleep(.004)
        def wait(predicate,timeout=75):
            until=time.monotonic()+timeout
            while not predicate() and time.monotonic()<until:pump(.025)
            require(predicate(),'Timed out: '+str(predicate))
        def check(name,value):
            report['checks'][name]=bool(value)
            (out/'cover-workflow-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            require(value,name)
        def idle():
            return work and not (work._loading or work._placing or work.busy or work.pane.pending or work.pane.queue)
        def web_idle():
            until=time.monotonic()+75;quiet=None
            while time.monotonic()<until:
                pump(.02)
                if idle():
                    quiet=quiet or time.monotonic()
                    if time.monotonic()-quiet>.2:break
                else:quiet=None
            require(idle() and quiet is not None,'Editor did not settle: '+work.status.text())
            require(not work.pane.faulted,work.status.text())
        def query(expression,document=None):
            result=[];work.pane.query(expression,result.append,document=work.document_id if document is None else document)
            wait(lambda:bool(result));return result[0]
        def file_dialog(path=None):
            timer=QTimer(window);timers.append(timer);timer.setInterval(150);state={'dialog':None}
            def choose():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QFileDialog):
                    if path is None:dialog.reject();timer.stop();return
                    if state['dialog'] is not dialog:state['dialog']=dialog;dialog.setDirectory(str(Path(path).parent))
                    else:
                        field=dialog.findChild(QLineEdit,'fileNameEdit')
                        if field:field.setText(Path(path).name)
                        dialog.accept()
                        if not dialog.isVisible():timer.stop()
            timer.timeout.connect(choose);timer.start()
        def click_action(editor,key):
            widget=editor.toolbar.widgetForAction(editor.cover_actions[key])
            if widget is None:widget=editor.tools.widgetForAction(editor.cover_actions[key])
            QTest.mouseClick(widget,Qt.LeftButton);pump()
        def drag(view,start,end):
            move(view,start)
            QTest.mousePress(view.viewport(),Qt.LeftButton,pos=start)
            for step in range(1,9):
                move(view,start+(end-start)*step/8,Qt.LeftButton)
            QTest.mouseRelease(view.viewport(),Qt.LeftButton,pos=end);pump(.035)
        def move(view,point,buttons=Qt.NoButton):
            target=view.viewport()
            QApplication.sendEvent(target,QMouseEvent(QEvent.MouseMove,QPointF(point),QPointF(target.mapToGlobal(point)),Qt.NoButton,buttons,Qt.NoModifier))
        watchdog=QTimer(window);timers.append(watchdog);watchdog.setInterval(10000)
        def snapshot():
            modal=QApplication.activeModalWidget()
            if modal:modal.grab().save(str(out/'live-modal.jpg'))
            (out/'live-state.json').write_text(json.dumps(dict(modal=str(modal),status=work.status.text() if work else '',elapsed=time.perf_counter()-begun),ensure_ascii=False),encoding='utf8')
        watchdog.timeout.connect(snapshot);watchdog.start()
        try:
            wait(lambda:page.project is not None and getattr(page.project,'media',None) is not None)
            page.video.set_paused(True);pump(.2)
            before=copy.deepcopy(page.project.to_dict());position=page.timeline.playhead_ms
            history=(page.undo_stack.index(),page.undo_stack.count())
            open_started=time.perf_counter();QTest.mouseClick(page.make_cover_button,Qt.LeftButton)
            wait(lambda:page.cover_controller.editor is not None)
            work=page.cover_controller.editor;web_idle()
            report['open_editor_seconds']=time.perf_counter()-open_started
            report['frame_receipt']=page.cover_controller.last_receipt
            report['dpi']=work.devicePixelRatioF()
            check('requested_dpi',abs(report['dpi']-float(os.environ['TWOBYTEASR_COVER_DPI'])/100)<.01)
            check('studio_frame_is_original_pixels',work.original.width==page.cover_controller.last_receipt['width'])
            check('new_background_unlocked',not work.original.layer(work.original.background_id).locked)
            check('embedded_real_photopea_ready',work.pane.is_ready and work.pane.web.isVisible())
            if os.environ.get('TWOBYTEASR_COVER_RECOVERY')=='1':
                check('restart_recovery_banner',work.recovery.isVisible())
                QTest.mouseClick(next(b for b in work.recovery.findChildren(QPushButton) if b.text()=='恢复草稿'),Qt.LeftButton);web_idle()
                check('restart_draft_not_manual_save',work.dirty and not work.filename)
                value=query('(function(){var a=[];for(var i=0;i<app.activeDocument.layers.length;i++){var l=app.activeDocument.layers[i];if(l.kind==LayerKind.TEXT)a.push(l.textItem.contents);}return a;})()')
                check('restart_editable_chinese',any('中文改稿' in x for x in value))
                work.export_document(out/'restored.png');web_idle();check('restart_export_valid',QImage(str(out/'restored.png')).width()>0)
                entry=work.library.entries()[0];work.dirty=False;work.apply_template(entry,True);web_idle()
                work.export_document(out/'template-without-source.png');web_idle()
                check('template_self_contained_after_restart',QImage(str(out/'template-without-source.png')).width()>0)
                work.resize(900,600);pump(.5);web_idle();work.grab().save(str(out/'recovery.jpg'))
                report['small_browser_zoom']=work.pane.web.zoomFactor()
                report['metrics']=work.metrics+work.pane.metrics;report['passed']=True
                return
            # Local compatibility editor: actual pointer events across all handles.
            work.open_local();local=work.local_editor;local.move(20,20);local.raise_();local.activateWindow();pump(.3)
            person=out/'透明示例人物.png';person.write_bytes(demo_character())
            local.add_images([str(person)]);wait(lambda:not local.busy)
            overlay=local.selected_layer();check('transparent_person_independent',overlay.kind=='image' and overlay.id!=local.session.document.background_id)
            base_id=local.session.document.background_id
            base_item=next(local.layers.item(i) for i in range(local.layers.count()) if local.layers.item(i).data(Qt.UserRole)==base_id)
            QTest.mouseClick(local.layers.viewport(),Qt.LeftButton,pos=local.layers.visualItemRect(base_item).center());local.view.fit_canvas();pump(.1)
            base=local.session.document.layer(base_id);old_x=base.x
            point=local.view.mapFromScene(QPointF(base.x+base.width*.2,base.y+base.height*.2));drag(local.view,point,point+QPoint(24,16))
            check('full_size_base_direct_move',local.session.document.layer(base_id).x!=old_x);local.undo()
            rect=local.view.items_by_id[base_id].sceneBoundingRect();corner=local.view.mapFromScene(rect.bottomRight());width=rect.width()
            drag(local.view,corner,corner-QPoint(22,14));check('full_size_base_direct_scale',local.session.document.layer(base_id).width!=width);local.undo()
            local.view.setFocus();pump(.05);undo_index=local.session.undo.index()
            QTest.mousePress(local.view.viewport(),Qt.LeftButton,pos=corner);move(local.view,corner-QPoint(16,12),Qt.LeftButton)
            local.layers.setFocus();pump(.05);QTest.mouseRelease(local.view.viewport(),Qt.LeftButton,pos=corner-QPoint(16,12))
            check('focus_loss_finishes_one_drag',local.view.resize_drag is None and local.session.undo.index()==undo_index+1);local.undo()
            before_wheel=local.session.document.signature();zoom=local.view.transform().m11();point=QPoint(200,200)
            QApplication.sendEvent(local.view.viewport(),QWheelEvent(QPointF(point),QPointF(local.view.viewport().mapToGlobal(point)),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False))
            check('wheel_only_changes_view',local.session.document.signature()==before_wheel and local.view.transform().m11()>zoom)
            local.view.fit_canvas()
            local.grab().save(str(out/'local-full-frame.jpg'))
            for key in (local.session.document.background_id,overlay.id):
                item=next(local.layers.item(i) for i in range(local.layers.count()) if local.layers.item(i).data(Qt.UserRole)==key)
                QTest.mouseClick(local.layers.viewport(),Qt.LeftButton,pos=local.layers.visualItemRect(item).center());pump(.03)
                layer=local.session.document.layer(key);layer.locked=False
                for zoom in (.25,.5,1):
                    for handle in range(8):
                        layer=local.session.document.layer(key);layer.x=160;layer.y=90;layer.width=320;layer.height=180;layer.keep_aspect=True
                        local.view.sync_document();local.view.set_zoom(zoom);local.view.centerOn(320,180);pump(.03)
                        bounds=local.view.items_by_id[key].sceneBoundingRect();p=local.view.mapFromScene(local.view.handle_points(bounds)[handle])
                        move(local.view,p+QPoint(25,25))
                        move(local.view,p)
                        report['last_handle']=dict(handle=handle,point=[p.x(),p.y()],viewport=[local.view.viewport().width(),local.view.viewport().height()],
                            hit=local.view.hit_handle(p),hover=local.view.hover_handle,tracking=local.view.viewport().hasMouseTracking(),actual_cursor=local.view.cursor().shape().value,expected_cursor=local.view.handle_cursor(handle).value,selected=list(local.session.selected),enabled=local.view.isEnabled(),
                            cursor_global=[QCursor.pos().x(),QCursor.pos().y()],target_global=[local.view.viewport().mapToGlobal(p).x(),local.view.viewport().mapToGlobal(p).y()],widget_at=str(QApplication.widgetAt(local.view.viewport().mapToGlobal(p))),viewport_object=str(local.view.viewport()),active=str(QApplication.activeWindow()),modal=str(QApplication.activeModalWidget()))
                        check(f'{key[:8]}-{zoom}-{handle}-cursor',local.view.cursor().shape()==local.view.handle_cursor(handle))
                        count=local.session.undo.index();dx=-16 if handle in (0,2,7) else 16;dy=-12 if handle in (0,1,4) else 12
                        drag(local.view,p,p+QPoint(dx,dy));changed=local.session.document.layer(key)
                        ok=(changed.height==180 if handle in (5,7) else changed.width==320 if handle in (4,6) else abs(changed.width/changed.height-320/180)<.0001)
                        check(f'{key[:8]}-{zoom}-{handle}-axis',ok and local.session.undo.index()==count+1)
                        local.undo();check(f'{key[:8]}-{zoom}-{handle}-undo',local.session.document.layer(key).width==320)
                        local.redo()
                    local.grab().save(str(out/f'local-{key[:8]}-{round(zoom*100)}.jpg'))
            check('canvas_unchanged_by_background_drag',(local.session.document.width,local.session.document.height)==(work.original.width,work.original.height))
            local.toggle_lock();locked=copy.deepcopy(local.selected_layer());p=local.view.mapFromScene(local.view.items_by_id[locked.id].sceneBoundingRect().center())
            drag(local.view,p,p+QPoint(30,20));check('locked_layer_does_not_move',local.session.document.layer(locked.id).x==locked.x)
            local.toggle_lock();local.fit_selected('center');check('recover_to_canvas',local.selected_layer().x>=0)
            click_action(local,'text')
            for i,line in enumerate(['真实中文标题','第二行仍可编辑']):
                if i:QTest.keyClick(local.text_edit,Qt.Key_Return)
                event=QInputMethodEvent();event.setCommitString(line);QApplication.sendEvent(local.text_edit,event);pump()
            local.flush_text();check('qt_ime_chinese',local.selected_layer().text=='真实中文标题\n第二行仍可编辑')
            file_dialog(out/'local-editable.psd');click_action(local,'save');wait(lambda:not local.busy and (out/'local-editable.psd').is_file())
            check('local_psd_editable_text',any((x.get('text') or {}).get('text','').startswith('真实中文标题') for x in psd_metadata(out/'local-editable.psd')['layers']))
            local.export_document(out/'local-export.png');wait(lambda:not local.busy)
            expected=CoverRenderer().render(local.session.document)
            check('local_export_matches_composition',QImage(str(out/'local-export.png')).convertToFormat(expected.format())==expected)
            local.resize(900,600);pump(.2);local.grab().save(str(out/'local-small.jpg'))
            check('small_window_core_save',local.toolbar.widgetForAction(local.cover_actions['save']).isVisible())
            item=next(local.layers.item(i) for i in range(local.layers.count()) if local.layers.item(i).data(Qt.UserRole)==overlay.id)
            QTest.mouseClick(local.layers.viewport(),Qt.LeftButton,pos=local.layers.visualItemRect(item).center());local.view.set_zoom(.5)
            rect=local.view.items_by_id[overlay.id].sceneBoundingRect();local.view.centerOn(rect.center());pump(.05)
            point=local.view.mapFromScene(local.view.handle_points(rect)[5]);old_width=local.selected_layer().width
            drag(local.view,point,point+QPoint(18,0));check('resize_window_keeps_transform',local.selected_layer().width>old_width);local.undo()
            local.session.saved_signature=local.session.document.signature();local.close();pump(.2);local=None
            # Native Photopea PSD and template lifecycle through the application controls.
            entries=work.library.entries();check('two_distinct_bundled_templates',len(entries)>=2 and len({(e['width'],e['height']) for e in entries})>=2)
            for index,entry in enumerate(entries[:2]):
                work.dirty=False
                timer=QTimer(window);timers.append(timer);timer.setInterval(100)
                def pick(entry=entry,timer=timer):
                    dialog=QApplication.activeModalWidget()
                    if isinstance(dialog,TemplatePicker):
                        for row in range(dialog.cards.count()):
                            if dialog.cards.item(row).data(Qt.UserRole)['id']==entry['id']:
                                dialog.cards.setCurrentRow(row);QTest.mouseClick(next(b for b in dialog.findChildren(QPushButton) if b.text()=='使用模板'),Qt.LeftButton);timer.stop();return
                timer.timeout.connect(pick);timer.start();click_action(work,'templates');web_idle()
                check(f'template-{index}-new-document',work.template_id==entry['id'] and work.filename=='')
                work.quick.setFocus();QTest.keyClick(work.quick,Qt.Key_A,Qt.ControlModifier)
                event=QInputMethodEvent();event.setCommitString('中文改稿 '+str(index+1));QApplication.sendEvent(work.quick,event);QTest.keyClick(work.quick,Qt.Key_Return);web_idle()
                value=query('(function(){var d=app.activeDocument,a=[];for(var i=0;i<d.layers.length;i++){var l=d.layers[i];if(l.kind==LayerKind.TEXT)a.push(l.textItem.contents);}return a;})()')
                check(f'template-{index}-title-edit',any('中文改稿' in text for text in value))
                if index==0:
                    from .cover_workbench import FIND_LAYER
                    previous_ids={x['id'] for x in work.layer_info}
                    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(out/'透明示例人物.png'))]*2)
                    drop_target=work.pane.web.focusProxy() or work.pane.web
                    enter=QDragEnterEvent(QPoint(200,200),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    QApplication.sendEvent(drop_target,enter)
                    dropped=QDropEvent(QPointF(200,200),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    QApplication.sendEvent(drop_target,dropped);pump(.1);web_idle()
                    new_ids=[x['id'] for x in work.layer_info if x['id'] not in previous_ids]
                    check('native_multi_file_drop',enter.isAccepted() and dropped.isAccepted() and len(new_ids)==2)
                    work.pane.command(FIND_LAYER+'var ids='+json.dumps(new_ids)+';for(var i=0;i<ids.length;i++)findLayer(app.activeDocument.layers,ids[i]).remove();',lambda _:work.refresh_layers(),document=work.document_id);web_idle()
                    person_layer=next(x for x in work.layer_info if '示例角色' in x['name'])
                    done=[]
                    work.pane.command(FIND_LAYER+'app.activeDocument.activeLayer=findLayer(app.activeDocument.layers,'+str(person_layer['id'])+');',done.append,document=work.document_id);web_idle()
                    frame=next(f for f in work.pane.page.mainFrame().children() if f.url().host()=='www.photopea.com')
                    rects=[];frame.runJavaScript('JSON.stringify(Array.from(document.querySelectorAll("canvas")).map(c=>({w:c.width,h:c.height,r:c.getBoundingClientRect().toJSON()})))',rects.append);wait(lambda:bool(rects))
                    report['native_canvases']=json.loads(rects[0])
                    canvas=max((c['r'] for c in report['native_canvases']),key=lambda r:r['width']*r['height'])
                    focus=work.pane.web.focusProxy() or work.pane.web
                    bounds_query='(function(){'+FIND_LAYER+'var d=app.activeDocument,l=findLayer(d.layers,'+str(person_layer['id'])+');var b=l.bounds;return {id:l.id,bounds:[b[0].value,b[1].value,b[2].value,b[3].value],width:d.width,height:d.height};})()'
                    report['native_transforms']=[]
                    for native_handle in ('right','top','corner'):
                        before_native=query(bounds_query);b=before_native['bounds']
                        scale=min((canvas['width']-16)/before_native['width'],(canvas['height']-16)/before_native['height'])
                        ox=canvas['x']+(canvas['width']-before_native['width']*scale)/2
                        oy=canvas['y']+(canvas['height']-before_native['height']*scale)/2
                        def pixel(x,y):return QPoint(round(ox+x*scale),round(oy+y*scale))
                        center=pixel((b[0]+b[2])/2,(b[1]+b[3])/2)
                        QTest.mouseClick(focus,Qt.LeftButton,pos=center);pump(.1)
                        QTest.keyClick(focus,Qt.Key_T,Qt.ControlModifier);pump(.3)
                        deferred=[]
                        if native_handle=='right':
                            work.pane.export(work.document_id,'psd',deferred.append);pump(.15)
                            check('native_transform_pending_keeps_input',work.pane.web.isEnabled() and not deferred)
                        work.grab().save(str(out/f'native-{native_handle}-before.jpg'))
                        origin=pixel(b[2],(b[1]+b[3])/2) if native_handle=='right' else pixel((b[0]+b[2])/2,b[1]) if native_handle=='top' else pixel(b[2],b[3])
                        delta=QPoint(-22,0) if native_handle=='right' else QPoint(0,22) if native_handle=='top' else QPoint(-22,-22)
                        QTest.mousePress(focus,Qt.LeftButton,pos=origin)
                        for step in range(1,9):
                            p=origin+delta*step/8
                            QApplication.sendEvent(focus,QMouseEvent(QEvent.MouseMove,QPointF(p),QPointF(focus.mapToGlobal(p)),Qt.NoButton,Qt.LeftButton,Qt.NoModifier));pump(.025)
                        QTest.mouseRelease(focus,Qt.LeftButton,pos=origin+delta);pump(.1);QTest.keyClick(focus,Qt.Key_Return);pump(.3)
                        web_idle()
                        if native_handle=='right':check('native_transform_then_save_returns_psd',bool(deferred) and deferred[0].startswith(b'8BPS'))
                        after_native=query(bounds_query)
                        report['native_transforms'].append(dict(handle=native_handle,before=before_native,after=after_native))
                        check('photopea-native-'+native_handle,after_native['bounds']!=before_native['bounds'])
                        work.grab().save(str(out/f'native-{native_handle}-after.jpg'))
                        QTest.keyClick(focus,Qt.Key_Z,Qt.ControlModifier);pump(.2)
                        check('photopea-native-'+native_handle+'-undo',query(bounds_query)['bounds']==before_native['bounds'])
                        QTest.keyClick(focus,Qt.Key_Z,Qt.ControlModifier|Qt.ShiftModifier);pump(.2)
                        check('photopea-native-'+native_handle+'-redo',query(bounds_query)['bounds']==after_native['bounds'])
                    title_id=work.slots['title']
                    title_bounds=query('(function(){'+FIND_LAYER+'var l=findLayer(app.activeDocument.layers,'+str(title_id)+'),b=l.bounds;return [b[0].value,b[1].value,b[2].value,b[3].value];})()')
                    title_point=pixel(title_bounds[0]+55,title_bounds[1]+70)
                    QTest.mouseClick(focus,Qt.LeftButton,pos=title_point);QTest.keyClick(focus,Qt.Key_T);pump(.15)
                    QTest.mouseClick(focus,Qt.LeftButton,pos=title_point);pump(.2);QTest.keyClick(focus,Qt.Key_A,Qt.ControlModifier)
                    event=QInputMethodEvent();event.setCommitString('中文改稿一');QApplication.sendEvent(focus,event);pump(.2)
                    QTest.keyClick(focus,Qt.Key_Return,Qt.ControlModifier);pump(.25)
                    title_native=query('(function(){'+FIND_LAYER+'return findLayer(app.activeDocument.layers,'+str(title_id)+').textItem.contents;})()')
                    check('photopea_native_ime_chinese',title_native=='中文改稿一')
                psd=out/f'example-{index+1}.psd';file_dialog(psd);click_action(work,'save');web_idle();wait(psd.is_file)
                metadata=psd_metadata(psd);check(f'template-{index}-editable-psd',sum(bool(l.get('text')) for l in metadata['layers'])>=3)
                output=out/f'example-{index+1}.png';file_dialog(output);click_action(work,'export');web_idle();wait(output.is_file)
                pixels=QImage(str(output));check(f'template-{index}-visible-background',pixels.pixelColor(pixels.width()//2,5).alpha()==255)
                check(f'template-{index}-master-not-overwritten',hashlib.sha256(work.library.asset(entry,'psd').read_bytes()).hexdigest()!=hashlib.sha256(psd.read_bytes()).hexdigest())
                work.grab().save(str(out/f'photopea-{index+1}.jpg'))
            template_form=QTimer(window);timers.append(template_form);template_form.setInterval(60)
            def fill_template():
                dialog=QApplication.activeModalWidget()
                if dialog and dialog.windowTitle() in ('当前封面保存为模板','更新模板母版'):
                    dialog.findChild(QLineEdit).setText('验收 · 自定义模板')
                    for box,name in zip(dialog.findChildren(QComboBox),('当前冻结帧','主标题','副标题')):
                        box.setCurrentIndex(box.findText(name))
                    QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save),Qt.LeftButton);template_form.stop()
            template_form.timeout.connect(fill_template);template_form.start();work.save_template_dialog();web_idle()
            custom=work.library.get(work.template_id)
            check('save_template_ui_stable_roles',len(custom['slots'])==3 and work.library.asset(custom,'psd').is_file())
            picker=TemplatePicker(work.library,work.settings,work);picker.show();pump(.1)
            picker.search.setText('自定义');check('template_search',picker.cards.count()==1);picker.cards.setCurrentRow(0)
            QTest.mouseClick(next(b for b in picker.findChildren(QPushButton) if b.text()=='收藏 / 取消'),Qt.LeftButton)
            picker.filter.setCurrentIndex(1);check('template_favorite',picker.cards.count()==1)
            picker.grab().save(str(out/'template-library.jpg'));picker.close();pump(.1)
            old_master=work.library.asset(custom,'psd')
            template_form.start();work.save_template_dialog(update=True);web_idle()
            custom=work.library.get(work.template_id)
            check('template_explicit_update_versioned',work.library.asset(custom,'psd')!=old_master and old_master.is_file())
            update_cancel=QTimer(window);timers.append(update_cancel);update_cancel.setInterval(50)
            def cancel_template():
                dialog=QApplication.activeModalWidget()
                if dialog and dialog.windowTitle()=='更新模板母版':dialog.reject();update_cancel.stop()
            update_cancel.timeout.connect(cancel_template);update_cancel.start();work.save_template_dialog(update=True);web_idle()
            check('template_update_cancel_preserves_master',work.library.get(work.template_id)['psd']==custom['psd'])
            picker=TemplatePicker(work.library,work.settings,work);picker.show();picker.search.setText('自定义');picker.cards.setCurrentRow(0)
            previous_templates={e['id'] for e in work.library.entries()}
            QTest.mouseClick(next(b for b in picker.findChildren(QPushButton) if b.text()=='复制'),Qt.LeftButton)
            duplicate=next(e for e in work.library.entries() if e['id'] not in previous_templates)
            check('template_duplicate_independent',duplicate['psd']!=custom['psd'] and work.library.asset(duplicate,'psd').read_bytes()==work.library.asset(custom,'psd').read_bytes())
            def select_copy():
                picker.search.clear()
                for row in range(picker.cards.count()):
                    if picker.cards.item(row).data(Qt.UserRole)['id']==duplicate['id']:picker.cards.setCurrentRow(row);return
            select_copy()
            rename=QTimer(window);timers.append(rename);rename.setInterval(50)
            def rename_copy():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QInputDialog):dialog.setTextValue('验收 · 重命名模板');dialog.accept();rename.stop()
            rename.timeout.connect(rename_copy);rename.start();QTest.mouseClick(next(b for b in picker.findChildren(QPushButton) if b.text()=='重命名'),Qt.LeftButton)
            check('template_rename',work.library.get(duplicate['id'])['name']=='验收 · 重命名模板')
            select_copy();remove=QTimer(window);timers.append(remove);remove.setInterval(50)
            def delete_copy():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QMessageBox):QTest.mouseClick(dialog.button(QMessageBox.Yes),Qt.LeftButton);remove.stop()
            remove.timeout.connect(delete_copy);remove.start();QTest.mouseClick(next(b for b in picker.findChildren(QPushButton) if b.text()=='删除'),Qt.LeftButton)
            check('template_delete_only_selected',duplicate['id'] not in {e['id'] for e in work.library.entries()} and custom['id'] in {e['id'] for e in work.library.entries()})
            picker.close();pump(.1)
            saved_file=work.filename;saved_bytes=Path(saved_file).read_bytes()
            file_dialog(None);work.save_dialog(save_as=True);check('save_as_cancel_keeps_target',work.filename==saved_file and Path(saved_file).read_bytes()==saved_bytes)
            work.mark_dirty();work.save_document(out/'missing-folder'/'fail.psd');web_idle()
            check('write_failure_stays_dirty',work.dirty and work.filename==saved_file and Path(saved_file).read_bytes()==saved_bytes)
            work.save_document(out/'retry.psd');web_idle();check('write_retry_valid',not work.dirty and (out/'retry.psd').read_bytes().startswith(b'8BPS'))
            received=[];work.pane.export('unrelated-document-id','psd',received.append);web_idle()
            check('wrong_document_refused',not received and not work.pane.faulted and work.filename==str(out/'retry.psd'))
            work.mark_dirty();target=out/'correlated.psd';work.save_document(target)
            work.pane.run_js("window.dispatchEvent(new MessageEvent('message',{origin:'https://www.photopea.com',source:window,data:'done'}));window.dispatchEvent(new MessageEvent('message',{origin:'https://invalid.example',source:frame.contentWindow,data:new ArrayBuffer(32)}));")
            check('unmatched_done_cannot_save',not target.exists() and work.dirty)
            # A second toolbar save during this operation is rejected without
            # replacing the pending document or its target.
            click_action(work,'save');web_idle()
            check('repeated_save_keeps_target',work.filename==str(target) and not work.dirty and psd_metadata(target)['layers'])
            work.open_document(target,confirmed=True);web_idle()
            value=query('(function(){var a=[];for(var i=0;i<app.activeDocument.layers.length;i++){var l=app.activeDocument.layers[i];if(l.kind==LayerKind.TEXT)a.push(l.textItem.contents);}return a;})()')
            check('native_psd_roundtrip_editable_chinese',any('中文改稿' in x for x in value))
            check('native_psd_roundtrip_independent_images',sum(not bool(x.get('text')) for x in psd_metadata(target)['layers'])>=2)
            reload_id=work.document_id;reload_pane=work.pane
            cancel=QTimer(window);timers.append(cancel);cancel.setInterval(50)
            def cancel_reload():
                dialog=QApplication.activeModalWidget()
                if isinstance(dialog,QMessageBox):dialog.done(QMessageBox.Cancel);cancel.stop()
            cancel.timeout.connect(cancel_reload);cancel.start();work.reload()
            check('reload_cancel_preserves_document',work.pane is reload_pane and work.document_id==reload_id)
            draft_started=time.time();work.mark_dirty()
            if os.environ.get('TWOBYTEASR_COVER_STUDIO_REGRESSION')=='1':
                wait(lambda:work.library.draft() and work.library.draft()['time']>draft_started,25);web_idle()
                check('automatic_idle_draft_saved',work._draft_revision==work.revision)
            else:work.save_draft();web_idle()
            check('draft_not_manual_save',work.dirty and work.library.draft() is not None)
            master_hashes={e['id']:hashlib.sha256(work.library.asset(e,'psd').read_bytes()).hexdigest() for e in entries[:2]}
            work.restore_draft();web_idle();check('draft_restore_unsaved',work.dirty and work.filename=='')
            check('draft_does_not_change_masters',all(hashlib.sha256(work.library.asset(e,'psd').read_bytes()).hexdigest()==master_hashes[e['id']] for e in entries[:2]))
            from .cover_workbench import CoverWorkbench
            from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
            class Offline(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self,info):
                    if info.requestUrl().scheme()=='https':info.block(True)
            offline=CoverWorkbench(work.original,work);blocker=Offline(offline.pane.profile)
            offline.pane.profile.setUrlRequestInterceptor(blocker);offline.pane.timeout.start(1800);offline.show()
            wait(lambda:offline.pane.faulted,10)
            check('offline_load_has_explicit_failure',not offline.pane.is_ready and '超时' in offline.status.text())
            offline.grab().save(str(out/'offline-failure.jpg'))
            offline.open_local();fallback=offline.local_editor;pump(.15)
            check('offline_local_fallback_has_frame',fallback.isVisible() and bool(fallback.session.document.background_id))
            fallback.session.saved_signature=fallback.session.document.signature();fallback.close();pump(.1)
            offline.dirty=False;offline.close();pump(.1)
            report['metrics']=work.metrics+work.pane.metrics
            work.resize(900,600);pump(.5);web_idle();work.grab().save(str(out/'photopea-small.jpg'))
            report['small_viewports']=[]
            for frame in [work.pane.page.mainFrame()]+work.pane.page.mainFrame().children():
                geometry=[];frame.runJavaScript('JSON.stringify({url:location.origin,width:innerWidth,height:innerHeight,x:scrollX,y:scrollY,dpr:devicePixelRatio,scrollWidth:document.documentElement.scrollWidth,body:document.body.getBoundingClientRect().toJSON()})',geometry.append)
                wait(lambda:bool(geometry));report['small_viewports'].append(json.loads(geometry[0]))
            check('small_iframe_not_scrolled_offscreen',all(abs(v['x'])<1 for v in report['small_viewports']))
            check('photopea_small_core_actions',all(work.toolbar.widgetForAction(work.actions[key]).isVisible() and work.toolbar.widgetForAction(work.actions[key]).geometry().right()<work.toolbar.width() for key in ('templates','save','export')))
            proc=psutil.Process();report['resources'].append(dict(rss=proc.memory_info().rss,children=[dict(name=p.name(),rss=p.memory_info().rss) for p in proc.children(recursive=True)]))
            work.dirty=False;work.close();pump(.2);work=None
            check('studio_project_preserved',page.project.to_dict()==before)
            check('studio_playhead_preserved',page.timeline.playhead_ms==position)
            check('studio_history_preserved',(page.undo_stack.index(),page.undo_stack.count())==history)
            if os.environ.get('TWOBYTEASR_COVER_STUDIO_REGRESSION')=='1':
                frames=out/'frames';frames.mkdir();page.frame_capture.settings.setValue('frame_export/directory',str(frames))
                page.frame_capture.settings.setValue('frame_export/subtitles',True);page._seek(8.25);page.frame_capture.last=None
                QTest.mouseClick(page.save_frame_button,Qt.LeftButton);wait(lambda:not page.frame_capture.busy,120)
                receipt=page.frame_capture.last;report['return_frame']=receipt
                check('studio_return_original_resolution_frame',receipt and receipt['width']==page.project.media.width and abs(receipt['milliseconds']-8250)<70)
                page._toggle_playback();pump(1.3);page.video.set_paused(True);check('studio_return_playback',page.timeline.playhead_ms>8500)
                from .project_range import set_range
                set_range(page.project,7500,10000);QTest.mouseClick(page.studio_render_button,Qt.LeftButton);wait(lambda:page.export_workspace is not None)
                ui=page.export_workspace;pump(.3);(out/'video').mkdir();ui.directory.setText(str(out/'video'));ui.filename.setText('cover-return-range')
                ui.filename_prefix.clear();ui.filename_suffix.clear();ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
                if ui.encoder.findData('libx264')<0:ui.encoder.addItem('Software x264','libx264')
                ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'));export_start=time.perf_counter();QTest.mouseClick(ui.export_button,Qt.LeftButton)
                wait(lambda:ui._last_job is not None);wait(lambda:not ui._running,160)
                check('studio_return_io_range_export',ui.pages.currentWidget()==ui.success_page)
                report['video_export']=dict(path=ui._last_job.output_path,seconds=time.perf_counter()-export_start,metadata=ui._last_job.completion_metadata)
                window.grab().save(str(out/'studio-return.jpg'))
                page.undo_stack.setClean()
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
            if local:local.grab().save(str(out/'local-failure.jpg'))
            if work:
                report['photopea_events']=work.pane.events[-20:];report['status']=work.status.text();work.grab().save(str(out/'failure.jpg'))
        finally:
            report['seconds']=time.perf_counter()-begun
            (out/'cover-workflow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            for timer in timers:timer.stop()
            if local:local.session.saved_signature=local.session.document.signature();local.close()
            if work:work.dirty=False;work._closing=True;work.close()
            QTimer.singleShot(300,window.close)
    QTimer.singleShot(1200,run)
