"""Actual Studio/E input to first correct Qt Paint, not function-return timing."""
import json,os,time,traceback,platform,math
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QTimer,Qt,QPoint,QEvent
    from PySide6.QtGui import QInputMethodEvent,QKeyEvent,QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.input_latency import InputLatencyTextEdit
    app=QApplication.instance();output=Path(output)
    baseline=os.environ.get('EDITOR_INTEGRITY_BASELINE')=='1'
    performance=os.environ.get('EDITOR_INTEGRITY_PERFORMANCE')=='1'
    result=dict(passed=False,baseline=baseline,checks={},measurements={},action_return_ms={},draft_change_ms={},dispatch_return_ms={},scope='Synthetic bilingual captions over 16s synthetic AV media; native Windows Qt normal MainWindow',machine=dict(system=platform.platform(),processor=platform.processor()))
    pending={};paint=InputLatencyTextEdit.paintEvent
    def painted(editor,event):
        paint(editor,event)
        if pending.get('editor') is editor and editor.toPlainText()==pending.get('expected'):
            pending['paint_ms']=(time.perf_counter()-pending['start'])*1000
            pending['paint_text']=editor.toPlainText();pending.pop('editor',None)
    InputLatencyTextEdit.paintEvent=painted
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value):
        result['checks'][name]=bool(value);save()
        if not value and not baseline:raise AssertionError(name)
    def wait(predicate,seconds=30):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            app.processEvents();time.sleep(.002)
        raise TimeoutError('editor integrity wait')
    def measure(name,editor,expected,action):
        pending.clear();pending.update(editor=editor,expected=expected,start=time.perf_counter())
        action();result['dispatch_return_ms'].setdefault(name,[]).append((time.perf_counter()-pending['start'])*1000)
        wait(lambda:'paint_ms' in pending,15)
        result['draft_change_ms'].setdefault(name,[]).append(pending.get('draft_ms'))
        result['measurements'].setdefault(name,[]).append(pending['paint_ms'])
        return pending['paint_ms']
    def commit_event(editor,text):
        event=QInputMethodEvent();event.setCommitString(text);QApplication.sendEvent(editor,event)
    def run():
        page=window.studio_page
        try:
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['EDITOR_INTEGRITY_PROJECT'],single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._readiness.ready,100)
            wait(lambda:page._readiness.loading.state=='ready' and not page._readiness.overlay.isVisible(),60)
            page.video.set_paused(True)
            if not baseline and not performance:
                before_video=len(page.project.video_tracks[0].clips);before_audio=len(page.project.audio_tracks[0].clips)
                check('cold loaded V1 is unlocked',not page.project.video_tracks[0].locked)
                clip=page.project.video_tracks[0].clips[0]
                page._commit_clip_edit(page.project.video_tracks[0].id,'split',clip_id=clip.id,time_ms=5000)
                check('cold first split changes linked AV together',len(page.project.video_tracks[0].clips)==before_video+1 and len(page.project.audio_tracks[0].clips)==before_audio+1)
                page.undo_stack.undo()
                check('linked split undo complete',len(page.project.video_tracks[0].clips)==before_video and len(page.project.audio_tracks[0].clips)==before_audio)
                page.undo_stack.redo();page.undo_stack.undo()
            result['performance_control_without_prior_AV_mutation']=performance
            result['cue_count']=len(page.project.cues);result['duration_ms']=page.project.media.duration_ms
            result['dpr']=page.devicePixelRatioF()
            editor=page.subtitle_edit_input;panel=page.subtitle_edit_card
            def draft_changed():
                if pending.get('editor') is editor and editor.toPlainText()==pending.get('expected') and 'draft_ms' not in pending:
                    pending['draft_ms']=(time.perf_counter()-pending['start'])*1000
            editor.document().contentsChanged.connect(draft_changed)

            base=page.project.cues[0].text
            measure('cold_open',editor,base,lambda:page._open_caption_editor('cue-0','original'))
            page._lock_caption_editor();QApplication.setActiveWindow(page.subtitle_edit_dock);editor.setFocus()
            QTest.qWait(150)
            resets=[];page.cue_model.modelReset.connect(lambda:resets.append(True))
            baseline_text=editor.toPlainText()
            from ..subtitle_rules.pronouns import pronoun_positions,toggle_pronoun
            def flipped(text):
                chars=list(text)
                for i in pronoun_positions(text):chars[i]=toggle_pronoun(chars[i])
                return ''.join(chars)
            for n in range(20):
                expected=flipped(editor.toPlainText())
                measure('shift_p',editor,expected,lambda:QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier))
                check('pronoun live override immediate',page._live_edit_text_overrides.get('cue-0')==expected)
                measure('typing',editor,expected+'字',lambda:commit_event(editor,'字'))
                QTest.qWait(5)
            panel.grab().save(str(output/'typed-card.png'))
            check('draft does not alter saved cue',page.project.cues[0].text==base)
            current=editor.toPlainText();QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_P,Qt.ShiftModifier,'P',True))
            check('auto-repeat does not flip again',editor.toPlainText()==current)
            page._cancel_canvas_inline_edit();check('cancel restores cue',page.project.cues[0].text==base)
            for n in range(int(os.environ.get('EDITOR_INTEGRITY_CYCLES','100'))):
                key=f'cue-{n%2}';cue=next(c for c in page.project.cues if c.id==key)
                measure('open' if n%2==0 else 'switch',editor,cue.text,lambda key=key:page._open_caption_editor(key,'original'))
                page._lock_caption_editor();QApplication.setActiveWindow(page.subtitle_edit_dock);editor.setFocus()
                before=cue.text;expected=flipped(before)
                if n%3==0:
                    QApplication.sendEvent(editor,QInputMethodEvent('ni',[]))
                    QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier)
                    check('preedit remains alive',getattr(editor,'_preediting',False))
                    commit_event(editor,'你');QTest.qWait(5)
                else:
                    measure('button_p',editor,expected,lambda:panel.pronoun_button.click())
                if n%2:
                    value=editor.toPlainText();index=page.undo_stack.index();started=time.perf_counter();page._caption_trigger_commit('audit')
                    result['action_return_ms'].setdefault('confirm',[]).append((time.perf_counter()-started)*1000)
                    check('one commit per confirmation',cue.text==value and page.undo_stack.index()==index+1)
                    page.undo_stack.undo();check('undo restores confirmed text',cue.text==before)
                    page.undo_stack.redo();check('redo restores confirmed text',cue.text==value)
                else:
                    started=time.perf_counter();page._cancel_canvas_inline_edit()
                    result['action_return_ms'].setdefault('cancel',[]).append((time.perf_counter()-started)*1000)
                    check('cancel remains isolated',cue.text==before)
                QTest.qWait(2)
            check('no typing model resets',not resets)
            if not baseline:
                page._open_caption_editor('cue-0','original');old=page._caption_draft;revision=old.revision
                page._open_caption_editor('cue-1','original');page._lock_caption_editor();editor.insertPlainText('新')
                new=page._caption_draft;text_now=editor.toPlainText();latest_revision=new.revision
                page._refresh_editor_suggestions(expected_draft=old,expected_revision=revision)
                check('late old target callback cannot alter current draft',page._caption_draft is new and editor.toPlainText()==text_now and new.revision==latest_revision)
                page._refresh_editor_suggestions(expected_draft=new,expected_revision=latest_revision-1)
                check('late old revision callback cannot replace newer text',editor.toPlainText()==text_now)
                page._cancel_canvas_inline_edit()
                page._refresh_editor_suggestions(expected_draft=old,expected_revision=revision)
                QTest.qWait(100)
                check('late callback after close cannot reopen editor',page._caption_draft is None and not page.subtitle_edit_dock.isVisible())
            # Candidate geometry is tested against the ENTIRE editor window.
            page._open_caption_editor('cue-0','original');page._lock_caption_editor()
            from ..subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption
            text=editor.toPlainText();start=text.index('营第')
            draft=page._caption_draft;draft.suggestions=(ReviewSuggestion(start,start+2,'营第',(SuggestionOption('营地'),),'model'),);draft.suggestion_text=text
            page._refresh_editor_suggestions();QTest.qWait(100)
            panel.place_bubble();QTest.qWait(30)
            dock=page.subtitle_edit_dock
            check('bubble entirely inside editor',dock.rect().contains(panel.bubble.geometry().translated(panel.pos())))
            panel.grab().save(str(output/'bubble-card.png'));dock.grab().save(str(output/'complete-editor.png'));page.grab().save(str(output/'workspace.png'))
            check('actual native editor visible',dock.isVisible() and panel.editor.isVisible())
            if not baseline:
                from PySide6.QtCore import QRectF
                shadow=panel.graphicsEffect().boundingRectFor(QRectF(panel.rect())).translated(panel.pos())
                check('complete shadow inside native editor',QRectF(dock.rect()).contains(shadow))
                check('close control does not cover text viewport',not panel.editor.geometry().intersects(panel.close_button.geometry()))

            if not baseline:
                old_button=panel.suggestions.candidate_button(0,0)
                old_generation=panel.suggestions._rows_generation
                page._open_caption_editor('cue-1','original');page._lock_caption_editor()
                next_text=editor.toPlainText();old_button.click()
                check('old candidate control cannot apply to a new binding',editor.toPlainText()==next_text and panel.suggestions._rows_generation!=old_generation)
                page._open_caption_editor('cue-0','original');page._lock_caption_editor()
                text=editor.toPlainText();at=text.index('营第')
                draft=page._caption_draft;draft.suggestions=(ReviewSuggestion(at,at+2,'营第',(SuggestionOption('很长的候选文字需要完整显示并允许访问'*4),SuggestionOption('营地')),'model'),);draft.suggestion_text=text
                page._refresh_editor_suggestions();QTest.qWait(100)
                for size in [(1440,900),(1120,760)]:
                    window.resize(*size);QTest.qWait(100);dock.fit_to_workspace();QTest.qWait(30)
                    previous=dock.pos();direction=panel.strip_above()
                    geometry=[dict(position=list(dock.pos().toTuple()),size=list(dock.size().toTuple()),lane=panel.lane.height(),above=direction)]
                    for n in range(8):
                        cursor=editor.textCursor();cursor.setPosition(n%max(1,len(text)));editor.setTextCursor(cursor)
                        panel.place_bubble();dock.fit_to_workspace()
                        geometry.append(dict(position=list(dock.pos().toTuple()),size=list(dock.size().toTuple()),lane=panel.lane.height(),above=panel.strip_above()))
                    result.setdefault('geometry',{})[str(size)]=geometry
                    check('long candidate complete in '+str(size),dock.rect().contains(panel.bubble.geometry().translated(panel.pos())))
                    check('cursor leaves orientation and anchor stable '+str(size),direction==panel.strip_above() and previous==dock.pos())
                    dock.grab().save(str(output/('long-candidate-'+str(size[0])+'.png')))
                from PySide6.QtGui import QFont,QFontInfo
                original_font=editor.font()
                for family in ['Microsoft YaHei UI','SimSun']:
                    font=QFont(original_font);font.setFamily(family);editor.setFont(font)
                    panel.resize_editor();dock.fit_to_workspace();QTest.qWait(30)
                    check('multiline and long candidate complete with '+family,dock.rect().contains(panel.bubble.geometry().translated(panel.pos())))
                    result.setdefault('fonts',[]).append(QFontInfo(editor.font()).family())
                editor.setFont(original_font);panel.resize_editor()
                for x,y in [(0.04,0.04),(.96,.04),(.04,.96),(.96,.96)]:
                    dock._anchor_fraction=y;dock._anchor_x_fraction=x
                    dock.fit_to_workspace();QTest.qWait(30)
                    check('whole component at synthetic corner '+str((x,y)),dock.screen().availableGeometry().contains(dock.geometry()) and dock.rect().contains(panel.bubble.geometry().translated(panel.pos())))
                page._toggle_fullscreen();QTest.qWait(100);dock.fit_to_workspace();QTest.qWait(50)
                check('fullscreen component complete',dock.screen().availableGeometry().contains(dock.geometry()) and dock.rect().contains(panel.bubble.geometry().translated(panel.pos())))
                dock.grab().save(str(output/'fullscreen-card.png'))
                page._toggle_fullscreen();QTest.qWait(100)
                native=output/'native-draft.png'
                page.video.controller.screenshot_to_file(str(native),mode='window',fast=True)
                wait(native.is_file,10)
                check('native caption frame captured',native.stat().st_size>100)

            if not baseline:
                page._cancel_canvas_inline_edit()
                translated=page.project.generation_metadata['translations']['cue-0']
                measure('translation_open',editor,translated,lambda:page._open_caption_editor('cue-0','translation'))
                page._cancel_canvas_inline_edit()
                page._open_caption_editor('cue-0','original');page._lock_caption_editor()
                editor.setPlainText('没有代称的句子')
                QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier)
                check('no pronoun command preserves text and open editor',editor.toPlainText()=='没有代称的句子' and page._caption_draft is not None)
                page._cancel_canvas_inline_edit()
            if not baseline:
                # Native video pixels, independent of the editor's own grab.
                # These checks run after latency sampling, not inside the key path.
                import hashlib
                from PIL import Image
                page._seek(.15)
                wait(lambda:abs(page.timeline.playhead_ms-150)<80,20)
                wait(lambda:float(page.video.controller.observed_property('time-pos',0) or 0)>=.1,20)
                wait(lambda:not getattr(page.video._playback_clock,'exact_seek_pending',False),20)
                page._open_caption_editor('cue-0','original');page._lock_caption_editor()
                def capture_signature(name):
                    path=output/(name+'.png')
                    page.video.controller.screenshot_to_file(str(path),mode='window',fast=True)
                    wait(path.is_file,10);QTest.qWait(25)
                    return hashlib.sha256(Image.open(path).convert('RGBA').tobytes()).hexdigest()
                base_pixels=None;stable=0
                for n in range(20):
                    QTest.qWait(80);current=capture_signature('preview-baseline-'+str(n))
                    stable=stable+1 if current==base_pixels else 0
                    base_pixels=current
                    if stable>=2:break
                check('native paused baseline is stable before editing',stable>=2)
                editor.setPlainText('即时草稿预览：她们现在在这里')
                changed=False
                for n in range(30):
                    QTest.qWait(50)
                    if capture_signature('preview-draft-'+str(n))!=base_pixels:changed=True;break
                check('native preview shows draft before confirmation',changed)
                page._cancel_canvas_inline_edit()
                # The selection handles normally return after cancel. Exclude
                # that separate assistance layer from the subtitle pixel proof.
                previous_inline=page.position_overlay._inline_editing
                page.position_overlay._inline_editing=True;page.position_overlay.hide()
                try:
                    restored=False
                    for n in range(30):
                        QTest.qWait(50)
                        if capture_signature('preview-cancel-'+str(n))==base_pixels:restored=True;break
                    check('native preview cancellation restores original pixels',restored)
                finally:
                    page.position_overlay._inline_editing=previous_inline
                    page._sync_canvas_selection()
            if not baseline:
                page._set_bilingual_mode(True)
                wait(lambda:page._prepared_caption('cue-0#tr') is not None,30)
                page._open_caption_editor('cue-0','translation');page._lock_caption_editor()
                translated_pixels=None;stable=0
                for n in range(20):
                    QTest.qWait(80);current=capture_signature('translation-baseline-'+str(n))
                    stable=stable+1 if current==translated_pixels else 0;translated_pixels=current
                    if stable>=2:break
                check('native bilingual baseline stable',stable>=2)
                editor.setPlainText('Live translation draft')
                changed=False
                for n in range(30):
                    QTest.qWait(50)
                    if capture_signature('translation-draft-'+str(n))!=translated_pixels:changed=True;break
                check('native translation uses current draft before confirm',changed)
                page._cancel_canvas_inline_edit()
                previous_inline=page.position_overlay._inline_editing
                page.position_overlay._inline_editing=True;page.position_overlay.hide()
                try:
                    restored=False
                    for n in range(30):
                        QTest.qWait(50)
                        if capture_signature('translation-cancel-'+str(n))==translated_pixels:restored=True;break
                    check('native translation cancel restores original pixels',restored)
                finally:
                    page.position_overlay._inline_editing=previous_inline
                    page._sync_canvas_selection()
                page.undo_stack.undo()
            if os.environ.get('EDITOR_INTEGRITY_REAL'):
                from ..projects.studio_project import load_project
                document=load_project(os.environ['EDITOR_INTEGRITY_REAL'])
                result['real_project']=dict(cues=len(document.cues),duration_ms=document.media.duration_ms,media_available=Path(document.media.path).is_file())
                if result['real_project']['media_available']:
                    old_id=page.project.project_id
                    page.undo_stack.setClean();page.project_dirty=False
                    page.project_controller.open_project_entry(os.environ['EDITOR_INTEGRITY_REAL'],single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
                    wait(lambda:page.project is not None and page.project.project_id!=old_id and page._readiness.ready,100)
                    wait(lambda:page._readiness.loading.state=='ready' and not page._readiness.overlay.isVisible(),60)
                    page.video.set_paused(True)
                    real=[cue for cue in page.project.cues if pronoun_positions(cue.text)][:5]
                    for cue in real:
                        page._seek((cue.start_ms+min(50,(cue.end_ms-cue.start_ms)//2))/1000)
                        wait(lambda cue=cue:abs(page.timeline.playhead_ms-cue.start_ms)<250,30)
                        before=cue.text
                        measure('real_open',editor,before,lambda cue=cue:page._open_caption_editor(cue.id,'original'))
                        page._lock_caption_editor();QApplication.setActiveWindow(page.subtitle_edit_dock);editor.setFocus()
                        measure('real_shift_p',editor,flipped(before),lambda:QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier))
                        page._cancel_canvas_inline_edit();check('real input remains unchanged on cancel',cue.text==before)
                    page.grab().save(str(output/'real-project-window.png'))
            summaries={} 
            for key,values in result['measurements'].items():
                ordered=sorted(values);summaries[key]=dict(n=len(values),median_ms=ordered[len(values)//2],p95_ms=ordered[max(0,math.ceil(len(values)*.95)-1)],max_ms=max(values))
            result['summary']=summaries
            result['target_met']={key:row['p95_ms']<=(200 if key in {'open','switch','translation_open','real_open'} else 100) for key,row in summaries.items() if key!='cold_open'}
            result['passed']=all(result['checks'].values()) or baseline
        except Exception as exc:
            result.update(error=str(exc),traceback=traceback.format_exc())
        finally:
            InputLatencyTextEdit.paintEvent=paint
            page._cancel_canvas_inline_edit();save()
            page.undo_stack.setClean();page.project_dirty=False
            window.close()
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
    QTimer.singleShot(1200,run)
