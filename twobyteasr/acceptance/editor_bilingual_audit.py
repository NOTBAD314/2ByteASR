"""Normal Home-click recovery route and bound bilingual editing, opt-in only."""
import json,os,sys,time,traceback


def start(window,output):
    from PySide6.QtCore import QTimer,Qt,QRect,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox,QDialogButtonBox
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..design.theme_manager import apply_theme
    app=QApplication.instance();spec=json.loads((output/'input.json').read_text('utf8'))
    result=dict(passed=False,checks=[],screenshots=[],opens=[],pid=os.getpid(),executable=sys.executable,
        identity=load_build_identity().to_dict(),recovery_dialogs=0,gui_gaps_ms=[])
    state=dict(busy=False,condition=None,until=0.,deadline=0.,last=time.perf_counter())
    def write():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));write()
        if not value:raise AssertionError(name)
    def shot(name,target=None):
        if target is not None:
            target.grab().save(str(output/(name+'.png')))
        else:
            _capture(window,output/(name+'.png'))
        result['screenshots'].append(name);write()
    def ready():
        page=window.built_page('studio')
        return bool(page is not None and page.project is not None and page.isVisible()
            and getattr(page,'_readiness',None) is not None and page._readiness.ready)
    def on_home():return window.studio_recent_hero.isVisible()
    def steps():
        apply_theme(spec.get('theme','grape'),app);yield .25
        if spec.get('phase')=='restart':
            yield on_home
            QTest.mouseClick(window.studio_recent_hero,Qt.LeftButton);yield .2;yield ready;yield .2
            page=window.studio_page;prefs=page._studio_preferences()
            check('new process restores both E preferences',prefs.get('caption_pause_on_edit') is False
                and prefs.get('caption_default_layer')=='original')
            check('new process opens complete Austin',len(page.project.cues)==1392
                and len(page.project.generation_metadata.get('translations',{}))==1388)
            cue=page._cue_lookup['27'];page._seek((cue.start_ms+200)/1000);yield .12
            page.video.set_paused(False);yield .08
            page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);yield .06
            check('new process E uses original and keeps playing',not page.video._paused
                and page._caption_draft is not None and page._caption_draft.target.layer=='original')
            shot('restart-original-editor-float',page.subtitle_edit_dock)
            page._cancel_canvas_inline_edit();page.video.set_paused(True)
            return
        for index in range(spec.get('cycles',3)):
            yield on_home
            hero=window.studio_recent_hero
            row=(hero if hero.isVisible() and hero.entry.get('path')==str(output/'project.2byteproj') else
                next((r for r in window.studio_recent_list.rows if r.isVisible()
                    and r.entry.get('path')==str(output/'project.2byteproj')),None))
            check('real Austin Home entry visible '+str(index),row is not None)
            previous=window.built_page('studio')
            previous_epoch=getattr(getattr(previous,'_readiness',None),'generation',-1)
            started=time.perf_counter();QTest.mouseClick(row,Qt.LeftButton)
            yield .2
            yield ready
            yield .25
            page=window.studio_page
            counts=dict(cues=len(page.project.cues),translations=len(page.project.generation_metadata.get('translations',{})),
                speakers=len(page.project.speakers),seconds=time.perf_counter()-started,
                reused=page is previous and page._readiness.generation==previous_epoch)
            result['opens'].append(counts)
            check('Home click opens complete Austin '+str(index),counts['cues']==1392 and counts['translations']==1388,counts)
            page.video.set_paused(True);page._seek(83.8);yield .25
            if index==0:shot('austin-open-complete')
            if index<spec.get('cycles',3)-1:
                window._return_to_settings();yield on_home;yield .25
        page=window.studio_page
        page._seek(85.390);page.timeline.set_playhead(85390);yield .15
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);yield .12
        page.select_cue('25');yield .12
        gap=dict(title=page.subtitle_edit_title.text(),text=page.subtitle_edit_input.toPlainText(),
                 enabled=page.subtitle_edit_input.isEnabled(),bound=page._caption_draft is not None)
        result['gap_state']=gap;shot('gap-after-selection');shot('gap-after-selection-float',page.subtitle_edit_dock)
        if spec.get('open_only'):
            check('baseline gap state recorded',True,gap)
            page._cancel_canvas_inline_edit();return
        check('gap never shows unbound stale source text',not gap['bound'] and not gap['enabled'] and gap['text']=='',gap)
        page._cancel_canvas_inline_edit()
        # A manually edited test copy never writes back user result/report paths.
        page.project.report_path='';page.project.original_outputs={}
        cue=page._cue_lookup['27'];original=cue.text
        translation=str(page.project.generation_metadata['translations'][cue.id])
        page._seek((cue.start_ms+250)/1000);yield .2
        page.video.set_paused(False);yield .12
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);yield .12
        draft=page._caption_draft
        check('E pauses actual player by default',page.video._paused)
        check('generic E defaults to translated cue',draft is not None and draft.target.cue_id==cue.id
            and draft.target.layer=='translation' and page.subtitle_edit_input.toPlainText()==translation)
        check('translation title and language are bound','译文' in page.subtitle_edit_title.text()
            and bool(page.subtitle_edit_card.role.text()))
        shot('E-default-translation-paused')
        shot('E-default-translation-paused-float',page.subtitle_edit_dock)
        page.subtitle_edit_input.setPlainText(translation+' · 编辑验收')
        QTest.keyClick(page.subtitle_edit_input,Qt.Key_R,Qt.ShiftModifier);yield .2
        check('translation saves and closes without touching original',not page.subtitle_edit_dock.isVisible()
            and cue.text==original and page.project.generation_metadata['translations'][cue.id]==translation+' · 编辑验收')
        page.undo_stack.undo();yield .08
        check('one undo restores translation',page.project.generation_metadata['translations'][cue.id]==translation)
        page.undo_stack.redo();page.save();yield .1
        shot('translation-saved-editor-closed')
        # Exercise the real settings save route and its lazy Studio category.
        from ..app.application_settings import open_application_settings
        def choose_settings():
            dialog=getattr(window,'_application_settings_dialog',None)
            if dialog is None or not dialog.isVisible():QTimer.singleShot(30,choose_settings);return
            dialog.ensure_section('Studio 与维护')
            dialog.caption_pause_on_edit.setChecked(False)
            dialog.caption_default_layer.setCurrentIndex(dialog.caption_default_layer.findData('original'))
            def save_settings():
                # This settings surface is a Qt widget inside the modal host.
                # Widget.grab does not promote it to a native child HWND.
                dialog.grab().save(str(output/'settings-E-options.png'))
                result['screenshots'].append('settings-E-options')
                dialog.buttons.button(QDialogButtonBox.Save).click()
            QTimer.singleShot(150,save_settings)
        QTimer.singleShot(80,choose_settings)
        open_application_settings(window,initial_section='Studio 与维护')
        yield .15
        prefs=page._studio_preferences()
        check('settings persists both E choices',prefs.get('caption_pause_on_edit') is False
            and prefs.get('caption_default_layer')=='original',prefs)
        page._seek((cue.start_ms+250)/1000);yield .1
        page.video.set_paused(False);yield .08
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);yield .06
        check('optional E keeps playing and opens original',not page.video._paused
            and page._caption_draft is not None and page._caption_draft.target.layer=='original')
        editor=page.subtitle_edit_input;editor.setPlainText('他和她带他们弹吉他，其他人等她。')
        editor.moveCursor(__import__('PySide6.QtGui',fromlist=['QTextCursor']).QTextCursor.End)
        QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier);yield .08
        check('Shift P flips every eligible draft pronoun',editor.toPlainText()=='她和他带她们弹吉他，其他人等他。'
            and cue.text==original)
        shot('whole-draft-pronouns')
        shot('whole-draft-pronouns-float',page.subtitle_edit_dock)
        page._cancel_canvas_inline_edit();page.video.set_paused(True)
        check('cancel keeps original text',cue.text==original)
        page.save();yield .1
        window._return_to_settings();yield on_home;yield .2
        window.open_studio_project(str(output/'project.2byteproj'),mode='edit',source='bilingual_audit_reopen')
        yield ready;yield .2
        page=window.studio_page;cue=page._cue_lookup['27']
        check('save reopen keeps complete bilingual project',len(page.project.cues)==1392
            and len(page.project.generation_metadata.get('translations',{}))==1388
            and page.project.generation_metadata['translations'][cue.id]==translation+' · 编辑验收'
            and cue.text==original)
        page._seek((cue.start_ms+200)/1000);yield .12
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E);yield .08
        check('E preferences survive project reopen',page._caption_draft.target.layer=='original')
        page._cancel_canvas_inline_edit()
        # The two suggestion rows are an explicit offline navigation fixture,
        # not a claim about the Italian speech or an accepted ASR correction.
        page._open_caption_editor(cue.id,'original');yield .05
        from ..studio import caption_editor as module
        from ..subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption
        from types import SimpleNamespace
        old_review,old_view=module.review_suggestions,module.current_issue_view
        old_rows=page._review_suggestions_for
        try:
            module.review_suggestions=lambda *a,**k:[]
            module.current_issue_view=lambda *a,**k:SimpleNamespace(for_cue=lambda *a,**k:())
            page._review_suggestions_for=lambda *a:()
            value='我会利用4.7前瞻拍摄的机会';page.subtitle_edit_input.setPlainText(value)
            rows=tuple(ReviewSuggestion(at,at+len(word),word,(SuggestionOption(replacement),),'model')
                for at,word,replacement in ((0,'我',''),(value.index('4.7'),'4.7','四点七')))
            page._caption_draft.suggestions=rows;page._caption_draft.suggestion_text=value
            page._refresh_editor_suggestions();page.subtitle_edit_input.setFocus()
            QTest.keyClick(page.subtitle_edit_input,Qt.Key_W,Qt.ShiftModifier);yield .05
            check('W selects first upper candidate',page.caption_suggestion_text.selected==(0,0))
            QTest.keyClick(app.focusWidget(),Qt.Key_D,Qt.ShiftModifier);yield .04
            check('D cycles from first to second candidate',page.caption_suggestion_text.selected==(1,0))
            QTest.keyClick(app.focusWidget(),Qt.Key_D,Qt.ShiftModifier);yield .04
            check('D enters editable body',page.subtitle_edit_input.hasFocus())
            QTest.keyClick(app.focusWidget(),Qt.Key_A,Qt.ShiftModifier);yield .04
            check('A cycles from body back to second candidate',page.caption_suggestion_text.selected==(1,0))
            QTest.keyClick(app.focusWidget(),Qt.Key_A,Qt.ShiftModifier);yield .04
            check('A cycles from second to first candidate',page.caption_suggestion_text.selected==(0,0))
            QTest.keyClick(app.focusWidget(),Qt.Key_S,Qt.ShiftModifier);yield .04
            check('Shift S no longer navigates',page.caption_suggestion_text.selected==(0,0)
                and 'Shift+S' not in page.caption_editor_hint.text())
            view=page.caption_suggestion_text
            result['candidate_geometry']=dict(view=view.size().toTuple(),viewport=view.viewport().size().toTuple(),
                hint=view._layout.sizeHint().toTuple(),body=view._body.size().toTuple(),
                rows=[dict(rect=f.geometry().getRect(),hint=f.sizeHint().toTuple(),
                    buttons=[dict(rect=b.geometry().getRect(),hint=b.sizeHint().toTuple())
                        for b in f.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)]) for f in view._frames])
            buttons=[b for f in view._frames for b in f.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)]
            check('two candidate rows fit the visible viewport',all(view.viewport().rect().contains(
                QRect(b.mapTo(view.viewport(),QPoint()),b.size())) for b in buttons),result['candidate_geometry'])
            check('candidate viewport and body never overlap',view.geometry().bottom()<page.subtitle_edit_input.geometry().top(),
                dict(suggestions=view.geometry().getRect(),editor=page.subtitle_edit_input.geometry().getRect(),
                    window=page.subtitle_edit_dock.size().toTuple(),window_hint=page.subtitle_edit_dock.sizeHint().toTuple(),
                    panel=page.subtitle_edit_card.size().toTuple(),panel_hint=page.subtitle_edit_card.sizeHint().toTuple(),
                    hfw=page.subtitle_edit_dock.layout().totalHeightForWidth(page.subtitle_edit_dock.width())))
            check('complete shortcut groups put newline before commit',page.caption_editor_hint.text().index('Shift+Enter')
                <page.caption_editor_hint.text().index('Enter/Shift+R') and all(not g.wordWrap() for g in page.caption_editor_hint.groups))
            shot('offline-candidate-ring')
            shot('offline-candidate-ring-float',page.subtitle_edit_dock)
        finally:
            module.review_suggestions,module.current_issue_view=old_review,old_view
            page._review_suggestions_for=old_rows
        page._cancel_canvas_inline_edit()
        check('navigation fixture never changed the source',page._cue_lookup[cue.id].text==original)
        page.save();yield .1

    iterator=steps();timer=QTimer(window);timer.setInterval(12)
    def finish(error=None):
        timer.stop()
        if error:result['error']=error
        result['passed']=not error and all(c['passed'] for c in result['checks'])
        write()
        page=window.built_page('studio')
        if page is not None:
            page._cancel_canvas_inline_edit();page.undo_stack.setClean()
        window.close();QTimer.singleShot(500,app.quit)
    def tick():
        now=time.perf_counter();result['gui_gaps_ms'].append(round((now-state['last'])*1000,3));state['last']=now
        modal=app.activeModalWidget()
        if isinstance(modal,QMessageBox):
            button=next((b for b in modal.buttons() if b.text()=='打开正式保存'),None)
            if button is not None:
                result['recovery_dialogs']+=1;button.click();write()
        if state['busy']:return
        state['busy']=True
        try:
            if state['condition']:
                if state['condition']():state['condition']=None
                elif now>state['deadline']:raise TimeoutError('Normal Home/open workflow timed out')
                else:return
            if now<state['until']:return
            value=next(iterator)
            if callable(value):state.update(condition=value,deadline=now+120)
            else:state['until']=now+float(value or 0)
        except StopIteration:finish()
        except BaseException:
            try:shot('failure')
            except Exception:pass
            finish(traceback.format_exc())
        finally:state['busy']=False
    def shutdown():result['gui_shutdown']=True;write()
    app.aboutToQuit.connect(shutdown);timer.timeout.connect(tick);write();timer.start()
