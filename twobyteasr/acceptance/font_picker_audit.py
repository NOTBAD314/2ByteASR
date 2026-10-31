"""Normal-window font glyphs, input boundary, popup latency and persistence."""
import copy,hashlib,json,os,sys,time,traceback
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QEvent,QObject,QPoint,QRect,QTimer,Qt,QSignalBlocker,QEventLoop
    from PySide6.QtGui import QFontDatabase,QInputMethodEvent
    from PySide6.QtTest import QTest,QSignalSpy
    from PySide6.QtWidgets import QApplication,QStyle,QStyleOptionComboBox
    from .blank_project_audit import _capture
    from ..caption_style.font_metadata import resolve_local_face,read_faces
    from ..caption_style.scoped_style import effective_layer_style,style_patch_command
    from ..projects.studio_project import save_project,load_project
    try:page=window.studio_page
    except RuntimeError:QTimer.singleShot(100,lambda:start(window,output));return
    output=Path(output);clock=time.perf_counter;baseline=bool(os.environ.get('STYLE_FONT_BEFORE'))
    from ..diagnostics.build_identity import load_build_identity
    result=dict(passed=False,baseline=baseline,pid=os.getpid(),executable=sys.executable,
        identity=load_build_identity().to_dict(),checks=[],font_timings=[],font_cases=[],performance=[])
    def receipt():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));receipt()
    def wait(predicate,seconds=90):
        until=clock()+seconds
        while clock()<until and not predicate():QTest.qWait(15)
        if not predicate():raise RuntimeError('Wait timed out')
    def settle():
        wait(lambda:not getattr(page,'_style_application_busy',False),120);QTest.qWait(180)
    def presents(p):return copy.deepcopy([(c.id,c.text,c.style_id,c.effect_id,c.appearance_override,c.transform)for c in p.cues])
    def row_geometry():
        c=page.style_preset;layout=c.parentWidget().layout().itemAt(0).layout()
        return dict(panel=page.context_panel.width(),preset=c.geometry().getRect(),layer=page.style_layer.geometry().getRect(),
            label_width=layout.itemAt(0).widget().width(),more_width=layout.itemAt(3).widget().width(),gap=layout.spacing(),
            full=c.currentText(),shown=c.displayed_text(),tooltip=c.toolTip())
    def shot(name):
        QTest.qWait(120);_capture(window,output/(name+'.png'))
        page.context_panel.grab().save(str(output/(name+'-panel.png')))
        page.style_font.grab().save(str(output/(name+'-font.png')))
    def popup_shot(name):
        QTest.qWait(80)
        page.style_font.view().window().grab().save(str(output/(name+'-popup.png')))
    class PaintProbe(QObject):
        def __init__(self):super().__init__(window);self.start=None;self.first=None
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Paint and self.start is not None and self.first is None:self.first=(clock()-self.start)*1000
            return False
    probe=PaintProbe()
    def glyphs_ready():
        combo=page.style_font
        if baseline:return True
        view=combo.view();viewport=view.viewport().rect();middle=viewport.center().x()
        first=view.indexAt(QPoint(middle,5)).row()
        if first<0:first=view.indexAt(QPoint(middle,12)).row()
        if first<0:first=0
        # Inspect the viewport's rows only. Scanning every visualRect in a
        # 1ms audit timer itself delayed font preparation and was not a UI cost.
        limit=min(combo.count(),first+combo.maxVisibleItems()+2)
        for row in range(first,limit):
            rect=combo.view().visualRect(combo.model().index(row,0))
            if rect.intersected(viewport).height()>=max(1,rect.height()//2):
                state=combo._last_font_rows.get(combo.itemText(row))
                if state is None or state.get('loading'):return False
        return True
    def wait_glyphs():
        if glyphs_ready():return
        loop=QEventLoop();poll=QTimer();poll.setInterval(1)
        poll.timeout.connect(lambda:loop.quit()if glyphs_ready()else None)
        deadline=QTimer();deadline.setSingleShot(True);deadline.timeout.connect(loop.quit)
        poll.start();deadline.start(15000)
        try:loop.exec()
        finally:poll.stop();deadline.stop()
        if not glyphs_ready():raise RuntimeError('Visible font glyphs did not finish')
    def open_timed(name):
        combo=page.style_font;combo.view().viewport().installEventFilter(probe)
        probe.start=clock();probe.first=None;misses=read_faces.cache_info().misses
        state=getattr(combo,'_last_font_preview',{})
        if state.get('sample_rect'):
            x,y,w,h=state['sample_rect'];point=QPoint(round(x+w/2),round(y+h/2))
        else:point=QPoint(max(4,combo.lineEdit().width()-20),combo.lineEdit().height()//2)
        QTest.mouseClick(combo.lineEdit(),Qt.MouseButton.LeftButton,pos=point)
        wait(lambda:combo.view().isVisible(),10);QTest.qWait(35)
        response=(clock()-probe.start)*1000
        wait_glyphs()
        result['font_timings'].append(dict(action=name,ready_ms=(clock()-probe.start)*1000,
            response_ms=response,
            first_paint_start_ms=probe.first,metadata_file_misses=read_faces.cache_info().misses-misses,
            items=combo.count(),popup=[combo.view().window().width(),combo.view().window().height()]))
        probe.start=None;combo.view().viewport().removeEventFilter(probe);receipt()
    def select_from_popup(family,query):
        combo=page.style_font;combo.showPopup();QTest.qWait(80)
        combo.lineEdit().selectAll();QTest.keyClicks(combo.lineEdit(),query);QTest.qWait(100)
        index=combo.findText(family)
        if index<0:raise RuntimeError('Font absent from filtered popup: '+family)
        before=QSignalSpy(combo.fontPicked)
        QTest.keyClick(combo.view(),Qt.Key.Key_Home)
        for _ in range(index):QTest.keyClick(combo.view(),Qt.Key.Key_Down)
        QTest.keyClick(combo.view(),Qt.Key.Key_Return);settle()
        return before.count()
    def case(label,expected_family):
        combo=page.style_font;combo.grab();face=resolve_local_face(expected_family)[0]
        state=copy.deepcopy(getattr(combo,'_last_font_preview',{}))
        style=effective_layer_style(page.project,page.project.cues[136],'original')
        prepared=page._prepared_caption('137')
        row=dict(label=label,requested=combo.currentText(),state=state,effective=dict(family=style.font_family,
            weight=style.font_weight,font_size=style.font_size,file=style.font_file),
            native_family=prepared.snapshot.font_family if prepared else None)
        result['font_cases'].append(row);receipt()
        if not baseline:
            check(label+'-real-face',bool(state.get('actual') and state['actual'].casefold()in {a.casefold()for a in face.aliases}),state)
            check(label+'-real-supported-example',state.get('sample_supported') and state.get('sample')=='示例ABC123',state.get('sample'))
            check(label+'-complete-example',state.get('sample_complete'),state)
            check(label+'-separate-preview-size',state.get('preview_pixels',99)<30 and style.font_size==61)
            check(label+'-name-uses-target',state.get('name_uses_target'),state)
        shot(label)
    def execute():
        try:
            wait(lambda:page.project is not None and page._readiness.ready and not page._readiness.active,150)
            for font in (Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts').glob('*'):
                if font.suffix.lower() in {'.ttf','.otf'}:QFontDatabase.addApplicationFont(str(font))
            QFontDatabase.addApplicationFont(str(Path(__file__).resolve().parents[2]/'assets/fonts/Cubic11.ttf'))
            # Test font files are installed before product imports; register
            # them in this private session before the lazy Qt inventory.
            from ..caption_style import font_system
            font_system._SYSTEM_FONT_INVENTORY=None
            if not page.video._paused:page._toggle_playback()
            page.volume_slider.setValue(0);p=page.project;cue=next(c for c in p.cues if c.id=='137')
            page.select_cue(cue.id);page._seek((cue.start_ms+1200)/1000);QTest.qWait(700)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.style_layer.setCurrentIndex(page.style_layer.findData('original'));page.style_apply_geometry.setChecked(False)
            if os.environ.get('STYLE_FONT_RESTART')=='1':
                page._prepare_caption_window(cue.start_ms+1200)
                wait(lambda:page._prepared_caption(cue.id)is not None,30)
                settle();case('restart-cubic-localized','俐方体11号')
                check('restart-persisted-family',effective_layer_style(p,cue,'original').font_family=='俐方体11号')
                check('restart-rendered-font-matches',page._prepared_caption(cue.id).snapshot.font_family=='Cubic 11')
                result['passed']=all(c['passed']for c in result['checks']);return
            index=page.style_preset.findData('user-ca40c9cf62d9')
            with QSignalBlocker(page.style_preset):page.style_preset.setCurrentIndex(index)
            page.style_preset.activated.emit(index);settle()
            page.style_font_size.setValue(61);page._commit_style_now();settle()
            page.upper_splitter.setSizes([320,1100,330]);QTest.qWait(150)
            result['preset_row']=row_geometry();result['device']=dict(dpr=window.devicePixelRatioF(),size=[window.width(),window.height()])
            if not baseline:
                check('preset-name-complete',page.style_preset.displayed_text()=='尼奈',result['preset_row'])
                check('preset-meaningful-width',page.style_preset.width()>page.style_layer.width()*1.5,result['preset_row'])
                check('scope-summary-below-preset',page.style_preset.geometry().bottom()<page.style_scope_summary.geometry().top(),
                    dict(preset=page.style_preset.geometry().getRect(),summary=page.style_scope_summary.geometry().getRect()))
                option=QStyleOptionComboBox();page.style_layer.initStyleOption(option)
                edit_rect=page.style_layer.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,
                    QStyle.SubControl.SC_ComboBoxEditField,page.style_layer)
                check('language-label-complete',edit_rect.width()>=page.style_layer.fontMetrics().horizontalAdvance(page.style_layer.currentText())+6,
                    dict(edit=edit_rect.getRect(),text=page.style_layer.currentText(),width=page.style_layer.width()))
                buttons=[page.style_bold,page.style_italic,page.style_underline]
                boxes=[QRect(b.mapTo(page.context_panel,QPoint()),b.size())for b in buttons]
                check('emphasis-spacing',all(b.left()-a.right()-1>=8 for a,b in zip(boxes,boxes[1:])),[r.getRect()for r in boxes])
                check('emphasis-complete',all(page.context_panel.rect().contains(r)and r.width()>=32 for r in boxes),[r.getRect()for r in boxes])
            shot('01-collapsed-maoken');case('02-maoken','猫啃什锦黑')
            combo=page.style_font;old=presents(p);undo=page.undo_stack.index();picked=QSignalSpy(combo.fontPicked)
            profiler=None
            if os.environ.get('STYLE_FONT_PROFILE')=='1':
                import cProfile
                profiler=cProfile.Profile();profiler.enable()
            open_timed('cold-open');popup_shot('03-cold-list');combo.hidePopup();QTest.qWait(50)
            open_timed('warm-open');popup_shot('04-warm-list')
            scroll=combo.view().verticalScrollBar()
            for fraction in (.2,.5,.8,0):
                t=clock();scroll.setValue(round(scroll.maximum()*fraction));QTest.qWait(20)
                response=(clock()-t)*1000;wait_glyphs()
                result['font_timings'].append(dict(action='scroll',fraction=fraction,response_ms=response,settled_ms=(clock()-t)*1000))
            combo.lineEdit().selectAll();t=clock();QTest.keyClicks(combo.lineEdit(),'Cubic');QTest.qWait(25)
            result['font_timings'].append(dict(action='search-Cubic',settled_ms=(clock()-t)*1000,items=combo.count()))
            popup_shot('05-search-cubic');combo.hidePopup();settle()
            if profiler is not None:profiler.disable();profiler.dump_stats(str(output/'font-picker.prof'))
            now=presents(p)
            check('browse-does-not-commit',picked.count()==0 and page.undo_stack.index()==undo and now==old,
                dict(signals=picked.count(),undo_before=undo,undo_after=page.undo_stack.index(),
                     changed_ids=[a[0]for a,b in zip(old,now)if a!=b],
                     changes=[dict(before=a,after=b)for a,b in zip(old,now)if a!=b],
                     commands=[page.undo_stack.command(i).text()for i in range(undo,page.undo_stack.index())]))
            if not baseline:check('cancel-restores-selected-name',combo.currentText()==effective_layer_style(p,cue,'original').font_family,combo.currentText())
            else:page._load_style_inspector()
            combo._recent_fonts=['猫啃什锦黑','MaokenAssortedSans','Arial','Cubic 11','Microsoft YaHei UI']
            combo.showPopup();QTest.qWait(180);popup_shot('06-three-faces');combo.hidePopup()
            for label,family,query in [('07-arial','Arial','Arial'),('08-cubic','Cubic 11','Cubic')]:
                count=select_from_popup(family,query)
                check(label+'-selected-once',count==1,dict(signals=count,current=combo.currentText()))
                wait(lambda:page._prepared_caption(cue.id)is not None,20);QTest.qWait(300);case(label,family)
            # A real persisted localized alias of the same Cubic font. Its
            # Chinese name has actual glyphs despite misleading OS/2 flags.
            style_patch_command(p,[cue.id],{'font_family':'俐方体11号','font_weight':0,'font_style_name':'','font_file':''},
                layer='original',changed=page._changed).redo();page._load_style_inspector();settle()
            wait(lambda:page._prepared_caption(cue.id)is not None,20);case('09-cubic-localized','俐方体11号')
            if not baseline:check('localized-alias-real-cubic-name',combo._last_font_preview.get('name_uses_target'))
            combo.showPopup();QTest.qWait(130);popup_shot('10-localized-row');combo.hidePopup()
            result['sample_popup_rows']=copy.deepcopy(getattr(combo,'_last_font_rows',{}))
            if not baseline:
                from ..caption_style.font_picker_preview import FontPreviewRequest
                label='中文名称（Arial）';arial=resolve_local_face('Arial')[0]
                stable=presents(p);index=page.undo_stack.index()
                combo.setEditText(label);combo.set_preview_face(label,filename=arial.file,face_index=arial.index)
                combo.grab();shot('11-missing-name-fixture')
                check('missing-name-fixture-readable',not combo._last_font_preview.get('name_uses_target')and
                    combo._last_font_preview.get('actual')=='Arial'and combo._last_font_preview.get('sample_supported'))
                result['coverage_fixture']=dict(label=label,state=copy.deepcopy(combo._last_font_preview),
                    note='Display-only Chinese test label for the actual Arial file; not an installed font name.')
                check('coverage-fixture-does-not-write',presents(p)==stable and page.undo_stack.index()==index)
                page._load_style_inspector();settle()
            if not baseline:
                from ..caption_style.font_picker_preview import _FACES,MAX_PREVIEW_FACES,MAX_COLLECTION_BYTES
                check('bounded-face-cache',len(_FACES)<=MAX_PREVIEW_FACES,
                    dict(faces=len(_FACES),collection_bytes=sum(x.collection_bytes for x in _FACES.values()),budget=MAX_COLLECTION_BYTES))
            saved=save_project(p,output/'saved-font.2byteproj');restored=load_project(saved)
            check('save-reopen-font-state',[(c.style_id,c.appearance_override,c.transform)for c in p.cues]==
                [(c.style_id,c.appearance_override,c.transform)for c in restored.cues])
            check('full-project-counts',len(p.cues)==1392 and len(p.generation_metadata.get('translations',{}))==1388)
            result['passed']=True if baseline else all(c['passed']for c in result['checks'])
        except BaseException:result['error']=traceback.format_exc()
        finally:
            receipt();QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.undo_stack.setClean();window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(250,execute)
