"""Real window, data, preview and persistence checks for explicit Studio actions."""
import copy
import json
import os
from pathlib import Path
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QEvent,QObject,QPoint,Qt,QTimer
    from PySide6.QtGui import QColor,QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from .blank_project_audit import _capture,_provider_calls
    from .studio_acceptance_audit import require
    from ..caption_style.scoped_style import effective_layer_style
    from ..caption_style.caption_layer_transform import resolved_values
    from ..caption_style.style_presets import StylePresetStore
    from ..timeline.selection_scope import SelectionScope
    from ..projects.studio_project import save_project,load_project

    output=Path(output);clock=time.perf_counter
    baseline=bool(os.environ.get('INTERACTION_BASELINE_SOURCE'))
    try:
        page=window.studio_page
    except RuntimeError:
        QTimer.singleShot(100,lambda:start(window,output))
        return
    result=dict(checks=[],samples=[],passed=False,baseline=baseline,pid=os.getpid())
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name,passed,detail=None):
        result['checks'].append(dict(name=name,passed=bool(passed),detail=detail));receipt()
        if not baseline:require(passed,name)
    def wait(predicate,seconds=90):
        end=clock()+seconds
        while not predicate() and clock()<end:QTest.qWait(20)
        require(predicate(),'wait timed out')
    def shot(name):
        QTest.qWait(180)
        _capture(window,output/(name+'.png'))
        page.subtitle_edit_card.grab().save(str(output/(name+'-editor.png')))
    class PaintProbe(QObject):
        def __init__(self):
            super().__init__(window);self.start=None;self.first=None
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Paint and self.start is not None and self.first is None:
                self.first=(clock()-self.start)*1000
            return False
    probe=PaintProbe()
    def timed(name,control,action):
        control.installEventFilter(probe);probe.start=clock();probe.first=None
        gaps=[];last=[clock()];pulse=QTimer(window);pulse.setInterval(16)
        def beat():
            now=clock();gaps.append((now-last[0])*1000);last[0]=now
        pulse.timeout.connect(beat);pulse.start()
        try:
            action()
            wait(lambda:not getattr(page,'_style_application_busy',False),120)
            done=(clock()-probe.start)*1000
            QTest.qWait(160)
        finally:pulse.stop();pulse.deleteLater()
        result['samples'].append(dict(name=name,data_ms=round(done,3),first_control_paint_ms=probe.first,
            max_gui_gap_ms=max(gaps,default=0),background=getattr(page,'_last_style_application_metrics',None)))
        probe.start=None;control.removeEventFilter(probe);receipt()
    def click_scope(kind,timing=None):
        index=page.style_scope.findData(kind);button=page.style_scope._buttons[index]
        action=lambda:QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=QPoint(button.width()-3,button.height()//2))
        if timing:timed(timing,button,action)
        else:action()
    def choose():
        combo=page.style_preset
        index=combo.findData('user-c969b5795c64')
        require(index>=0,'actual 大饭包2 preset loaded')
        combo.setCurrentIndex(index)
        combo.showPopup();QTest.qWait(30)
        rect=combo.view().visualRect(combo.model().index(index,0))
        QTest.mouseClick(combo.view().viewport(),Qt.MouseButton.LeftButton,pos=rect.center())
    def color(dialog,accept):
        dialog.picker.hex_edit.setFocus()
        dialog.picker.hex_edit.selectAll();QTest.keyClicks(dialog.picker.hex_edit,'#0066FF')
        QTest.keyClick(dialog.picker.hex_edit,Qt.Key.Key_Tab)
        check('picker_hex_is_blue',dialog.selectedColor()==QColor('#0066FF'))
        button=dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel)
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    def pick(accept=True):
        def handle():
            dialog=QApplication.activeModalWidget()
            if dialog is None:QTimer.singleShot(20,handle);return
            color(dialog,accept)
        QTimer.singleShot(20,handle)
        page._open_style_color_dialog(page.style_outline_color)
    def text_editor(cue,layer='original'):
        if layer=='translation':page.timeline.select_translation(cue.id)
        else:
            page.select_cue(cue.id);page.timeline.set_subtitle_layer('original');page.timeline.explicit_subtitle_id=cue.id
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key.Key_E)
        wait(lambda:getattr(page,'_canvas_editor',None) is not None,10)
        return page.subtitle_edit_input
    def execute():
        try:
            wait(lambda:page.project is not None and page._readiness.ready,120)
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('INTERACTION_THEME','warm'))
            window.resize(1600,950);window.show();QApplication.setActiveWindow(window)
            page.video.set_paused(True)
            p=page.project
            result['project']=dict(id=p.project_id,cues=len(p.cues),translations=len(p.generation_metadata.get('translations',{})),
                speakers=len(p.speakers),dpr=window.devicePixelRatioF(),theme=os.environ.get('INTERACTION_THEME','warm'))
            wait(lambda:hasattr(p,'_qc_result'),120)
            page._activate_filter('all')
            # Match the reported S00 lane; imported long projects retain their
            # stable native labels and use the first available lane instead.
            cue=next((c for c in p.cues if c.speaker_id=='S00' and c.start_ms>10000),p.cues[0])
            page.select_cue(cue.id);page._seek((cue.start_ms+150)/1000)
            page.timeline.set_visible_window(max(0,cue.start_ms-3000),24000)
            page.cue_controller.apply_selection_scope(SelectionScope.explicit([cue.id],cue.id))
            page.context_drawer.setCurrentIndex(1)
            page.style_scope.setCurrentIndex(page.style_scope.findData('selected'))
            # Many original cues already use this exact preset. Controlled
            # width differences in this disposable copy make scope writes
            # observable without replacing the real text, timing or media.
            for i,c in enumerate(p.cues):c.appearance_override['outline_width']=float(1+i%4)
            result['controlled_fixture']='outline_width varied 1..4 on copied real cues only'
            page._changed();QTest.qWait(250);page.undo_stack.clear()
            def translation_faces(project):
                keys=('font_family','font_size','outline_color','outline_width','primary_color','bold','italic','spacing')
                return {c.id:tuple(getattr(effective_layer_style(project,c,'translation'),key) for key in keys)
                        for c in project.cues if project.generation_metadata.get('translations',{}).get(c.id)}
            old_translation=translation_faces(p)
            timed('preset_selected_one',page.style_preset,choose)
            patch=StylePresetStore().load_patch('user-c969b5795c64')
            preset_color=QColor(patch['outline_color'])
            speaker_ids={c.id for c in p.cues if c.speaker_id==cue.speaker_id}
            timed('scope_speaker',page.style_scope,lambda:click_scope('speaker'))
            changed={c.id for c in p.cues if effective_layer_style(p,c,'original').font_family==patch['font_family']
                     and effective_layer_style(p,c,'original').outline_width==patch['outline_width']}
            check('preset_first_speaker_updates_whole_lane',speaker_ids<=changed,dict(expected=len(speaker_ids),matched=len(changed)))
            pick()
            click_scope('all','scope_all_blue')
            styles=[effective_layer_style(p,c,'original') for c in p.cues]
            check('all_blue_data',all(QColor(s.outline_color)==QColor('#0066FF') for s in styles))
            swatch=page.style_outline_swatch.findChild(page._style_color_button_type())
            check('blue_panel_swatch',swatch._color==QColor('#0066FF'),page.style_outline_color.text())
            check('blue_preview_sample',QColor(page.style_preview._style.outline_color)==QColor('#0066FF'))
            before=copy.deepcopy([(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues])
            count=page.undo_stack.count();pick(accept=False)
            check('cancel_color_restores_actual_blue',before==[(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues] and page.undo_stack.count()==count)
            pose=resolved_values(p,cue,'original');count=page.undo_stack.count()
            timed('include_saved_pose',page.style_apply_geometry,lambda:QTest.mouseClick(page.style_apply_geometry,Qt.MouseButton.LeftButton))
            check('geometry_toggle_applies_saved_pose',resolved_values(p,cue,'original')['position_y']==patch['position_y'],
                  dict(before=pose['position_y'],after=resolved_values(p,cue,'original')['position_y'],preset=patch['position_y']))
            after=copy.deepcopy([(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues])
            page.undo_stack.undo();page.undo_stack.redo()
            check('undo_redo_restores_complete_batch',after==[(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues])
            if not baseline:
                check('completion_status_is_terminal',not page.save_state.text().startswith('正在应用样式'))
                count=page.undo_stack.count();click_scope('all')
                check('identical_scope_click_has_no_undo',page.undo_stack.count()==count)
            shot('01-blue-and-saved-pose')
            # Both source and associated translation E use the same bound card.
            translations=p.generation_metadata.get('translations',{})
            if not baseline:
                for layer in ('original','translation'):
                    if layer=='translation' and not translations.get(cue.id):continue
                    old=translations[cue.id] if layer=='translation' else cue.text
                    editor=text_editor(cue,layer);editor.setPlainText(old+' TEST')
                    check(layer+'_bound_target',page._caption_draft.target.layer==layer)
                    QTest.keyClick(editor,Qt.Key.Key_Enter)
                    check(layer+'_enter_closed',page._canvas_editor is None)
                    value=p.generation_metadata.get('translations',{}).get(cue.id) if layer=='translation' else cue.text
                    check(layer+'_correct_data',value==old+' TEST')
                    page.undo_stack.undo()
                editor=text_editor(cue)
                QApplication.sendEvent(editor,QInputMethodEvent('ni',[]))
                QTest.keyClick(editor,Qt.Key.Key_Escape);check('ime_first_escape_only_composition',page._caption_draft is not None and not editor._preediting)
                QTest.keyClick(editor,Qt.Key.Key_Escape);check('ime_second_escape_closes',page._caption_draft is None)
                editor=text_editor(cue)
                QApplication.sendEvent(editor,QInputMethodEvent('zhong',[]))
                QTest.keyClick(editor,Qt.Key.Key_Return)
                check('ime_enter_only_composition',page._caption_draft is not None and not editor._preediting)
                commit=QInputMethodEvent();commit.setCommitString('中')
                QApplication.sendEvent(editor,commit)
                QTest.keyClick(editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
                check('ime_commit_then_shift_enter_newline','中' in editor.toPlainText() and '\n' in editor.toPlainText())
                QTest.keyClick(editor,Qt.Key.Key_Escape)
                for i in range(12):
                    editor=text_editor(cue);editor.setPlainText(cue.text+' discarded')
                    button=page.caption_cancel_button if i%2 else page.caption_close_button
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                    check('repeat_exit_'+str(i),page._canvas_editor is None and not page.position_overlay._inline_editing)
                editor=text_editor(cue)
                shot('02-editor-actions')
                QTest.mouseClick(page.caption_confirm_button,Qt.MouseButton.LeftButton)
                check('mouse_confirm_closed',page._caption_draft is None)
                editor=text_editor(cue);editor.setPlainText(cue.text+' error')
                controller_type=type(page.cue_controller);original_writer=controller_type.set_text
                def failure(*args,**kwargs):raise ValueError('isolated write validation failure')
                try:
                    controller_type.set_text=failure
                    QTest.mouseClick(page.caption_confirm_button,Qt.MouseButton.LeftButton)
                    check('commit_error_is_visible_and_cancellable',page._caption_draft is not None and page.caption_editor_error.isVisible())
                    shot('03-editor-error')
                    QTest.mouseClick(page.caption_close_button,Qt.MouseButton.LeftButton)
                    check('error_close_releases_editor',page._caption_draft is None and page._canvas_editor is None)
                finally:controller_type.set_text=original_writer
                # A normal time-axis click and a new E establish post-close use.
                next_target=page.cue_model.cue_at(page.cue_model.rowCount()-1)
                page.select_cue(next_target.id)
                check('post_exit_selection_works',page.selected_cue_id==next_target.id)
                page._seek(cue.start_ms/1000)
                check('post_exit_seek_has_no_editor_blocker',page._canvas_editor is None and not page.position_overlay._inline_editing)
                page.select_cue(cue.id)
                before=[(c.id,c.style_id,copy.deepcopy(c.appearance_override),copy.deepcopy(c.transform))for c in p.cues]
                click_scope('all')
                check('new_selection_does_not_replay_old_preset',before==[(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues])
            saved=save_project(p,output/'saved.2byteproj')
            restored=load_project(saved)
            check('save_reopen_styles_and_geometry',[(c.id,c.style_id,c.appearance_override,c.transform)for c in restored.cues]==[(c.id,c.style_id,c.appearance_override,c.transform)for c in p.cues])
            check('unmodified_other_text_layer',old_translation==translation_faces(p))
            # Close/reopen while an uncommitted editor owns focus, then reject
            # its delayed callbacks against the next project generation.
            if not baseline:
                text_editor(cue).setPlainText('must never persist')
                page._close_project_session('interaction-audit')
                page.open_project(saved)
                wait(lambda:page.project is not None and page._readiness.ready,120)
                check('project_switch_retires_editor',page._caption_draft is None and page._canvas_editor is None)
            check('no_provider_requests',not _provider_calls)
            result['passed']=True
        except BaseException:
            result['error']=traceback.format_exc()
        finally:
            receipt()
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.undo_stack.setClean()
            window.result_exit_code=0 if result['passed'] else 1
            window.close()
    QTimer.singleShot(200,execute)
