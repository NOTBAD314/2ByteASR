"""Opt-in normal-window checks for the approved A caption editor; offline only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QFont, QInputMethodEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..studio import caption_editor as captions
    from ..subtitle_rules.current_issues import invalidate
    from ..subtitle_rules.review_suggestions import ReviewSuggestion, SuggestionOption

    # Normal startup constructs Studio incrementally. Do not request its
    # property while the existing ready callback still owns construction.
    try:
        window.studio_page
    except RuntimeError:
        QTimer.singleShot(100, window, lambda: start(window, output))
        return

    output=Path(output)
    result=dict(passed=False,checks=[],screenshots=[],pid=os.getpid(),executable=sys.executable,
                identity=load_build_identity().to_dict(),entry='frozen' if getattr(sys,'frozen',False) else 'source')
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));receipt();require(value,name)
    def wait(predicate,seconds=90):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:QTest.qWait(20)
        require(predicate(),'caption editor wait timed out')
    def shift(widget,key):QTest.keyClick(widget,key,Qt.KeyboardModifier.ShiftModifier)

    def execute():
        page=None
        try:
            page=window.studio_page
            wait(lambda:page.project is not None and page._readiness.ready,120)
            apply_theme(os.environ.get('CAPTION_EDITOR_A_THEME','warm'))
            width,height=(int(x) for x in os.environ.get('TWOBYTEASR_STARTUP_SIZE','1600x950').split('x'))
            window.resize(width,height);window.show();QApplication.setActiveWindow(window)
            page.video.set_paused(True)
            p=page.project
            wait(lambda:hasattr(p,'_qc_result'),120)
            result['project']=dict(cues=len(p.cues),translations=len(p.generation_metadata.get('translations',{})),
                project_id=p.project_id,theme=os.environ.get('CAPTION_EDITOR_A_THEME','warm'),
                dpr=window.devicePixelRatioF(),logical_window=[window.width(),window.height()])
            check('real_media_is_present',Path(p.media.path).is_file())
            page._activate_filter('all')
            cue=next((c for c in p.cues if c.start_ms>10_000),p.cues[0])
            cue_id=cue.id;original=cue.text
            page._seek((cue.start_ms+80)/1000)
            QTest.qWait(600)
            def opened(layer='original'):
                if layer=='translation':page.timeline.select_translation(cue_id)
                else:
                    page.select_cue(cue_id);page.timeline.set_subtitle_layer('original');page.timeline.explicit_subtitle_id=cue_id
                page._remember_canvas_edit_target(cue_id,layer)
                page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key.Key_E)
                wait(lambda:page._caption_draft is not None,10)
                QTest.qWait(40)
                return page.subtitle_edit_input
            def geometry(name):
                card=page.subtitle_edit_card;host=page.video_overlay_host
                a=card.mapTo(window,QPoint());b=host.mapTo(window,QPoint())
                values=dict(card=[a.x(),a.y(),card.width(),card.height()],video_host=[b.x(),b.y(),host.width(),host.height()],
                    card_native=bool(card.internalWinId()),font_px=page.subtitle_edit_input.font().pixelSize(),font_weight=int(page.subtitle_edit_input.font().weight()))
                check(name+'_outside_video',a.y()>=b.y()+host.height(),values)
                check(name+'_bounded_by_window',a.x()>=0 and a.x()+card.width()<=window.width()+2 and a.y()+card.height()<=window.height()+2,values)
                check(name+'_bold_normal_editing_text',values['font_px']==18 and values['font_weight']>=int(QFont.Weight.DemiBold))
            def shot(name):
                QTest.qWait(250)
                _capture(window,output/(name+'.png'))
                page.subtitle_edit_card.grab().save(str(output/(name+'-editor.png')))
                result['screenshots'].append(name+'.png');receipt()

            editor=opened()
            result['caption_module']=captions.__file__
            if os.environ.get('CAPTION_EDITOR_A_BASELINE') == '1':
                check('baseline_old_editor_opens',page._caption_draft is not None)
                shot('baseline-editor')
                QTest.mouseClick(page.caption_close_button,Qt.MouseButton.LeftButton)
                check('baseline_old_editor_closes',page._caption_draft is None)
                result['passed']=True
                return
            geometry('normal')
            check('not_parented_to_native_video',not page.video_overlay_host.isAncestorOf(page.subtitle_edit_card))
            check('normal_reference_is_absent',not page.caption_reference.isVisible() and not page.caption_reference_button.isVisible())
            shot('01-normal')
            try:
                frame=output/'native-video.png'
                page.video.controller.screenshot_to_file(str(frame),mode='window')
                wait(frame.is_file,8)
                from PIL import Image,ImageStat
                image=Image.open(frame).convert('RGB')
                check('actual_mpv_frame_has_content',image.width>100 and max(ImageStat.Stat(image).var)>5,
                      dict(size=image.size,pixel_source='mpv screenshot-to-file window; separate from PrintWindow UI image'))
            except Exception:
                result['native_frame_error']=traceback.format_exc();raise
            editor.moveCursor(QTextCursor.MoveOperation.Start)
            cursor=editor.textCursor();old_pos=cursor.position()
            shift(editor,Qt.Key.Key_D);right=editor.textCursor().position();shift(editor,Qt.Key.Key_A)
            check('shift_ad_moves_cursor_without_selection',right>old_pos and editor.textCursor().position()==old_pos and not editor.textCursor().hasSelection())
            value=original+' A_EDIT'
            editor.setPlainText(value)
            before=time.perf_counter();shift(editor,Qt.Key.Key_R)
            result['confirm_dispatch_ms']=(time.perf_counter()-before)*1000
            check('shift_r_in_text_commits_and_closes',page._caption_draft is None and not page.subtitle_edit_card.isVisible() and p.cues[[c.id for c in p.cues].index(cue_id)].text==value)
            page.undo_stack.undo();check('one_undo_restores_original',page._cue_lookup[cue_id].text==original)
            page.undo_stack.redo();check('redo_restores_edit',page._cue_lookup[cue_id].text==value)
            page.undo_stack.undo()
            for i in range(5):
                editor=opened();editor.setPlainText(original+' discarded')
                button=page.caption_cancel_button if i%2 else page.caption_close_button
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                check('mouse_exit_'+str(i),page._caption_draft is None and page._cue_lookup[cue_id].text==original)
            editor=opened()
            QApplication.sendEvent(editor,QInputMethodEvent('ni',[]));shift(editor,Qt.Key.Key_R)
            check('ime_shift_r_does_not_commit_caption',page._caption_draft is not None)
            QTest.mouseClick(page.caption_close_button,Qt.MouseButton.LeftButton)
            check('mouse_close_after_composition_works',page._caption_draft is None)

            translations=p.generation_metadata.get('translations',{})
            translated=next((c for c in p.cues if translations.get(c.id)),None)
            if translated is not None:
                cue_id,original=translated.id,translated.text
                editor=opened('translation')
                check('associated_translation_reference_is_collapsed',page.caption_reference_button.isVisible() and not page.caption_reference.isVisible())
                QTest.mouseClick(page.caption_reference_button,Qt.MouseButton.LeftButton)
                check('associated_source_is_read_only',page.caption_reference.isVisible() and translated.text in page.caption_reference.text())
                geometry('translation');shot('02-translation')
                page._cancel_canvas_inline_edit()

            # Explicit offline candidates on this copied project; not original ASR errors.
            fixture='她说在营第等一下，其他人还在路上，吉它也留在那里。'
            page.cue_controller.set_text(cue_id,fixture,command_text='离线编辑器验收夹具')
            old_view,old_rules=captions.current_issue_view,captions.review_suggestions
            old_review=page._review_suggestions_for
            try:
                from types import SimpleNamespace
                captions.current_issue_view=lambda *args:SimpleNamespace(for_cue=lambda *args,**kwargs:())
                captions.review_suggestions=lambda *args,**kwargs:[]
                page._review_suggestions_for=lambda *args:()
                editor=opened()
                def row(word,*values):
                    at=fixture.index(word)
                    return ReviewSuggestion(at,at+len(word),word,tuple(SuggestionOption(v) for v in values),'model')
                draft=page._caption_draft
                draft.suggestions=(row('营第','营地','营区'),row('吉它','吉他'))
                draft.suggestion_text=fixture;page._refresh_editor_suggestions()
                shift(editor,Qt.Key.Key_W)
                check('shift_w_enters_first_candidate',page.caption_suggestion_text.owns_focus() and page.caption_suggestion_text.selected==(0,0))
                shift(QApplication.focusWidget(),Qt.Key.Key_D)
                check('candidate_shift_d_moves_right',page.caption_suggestion_text.selected==(0,1))
                shift(QApplication.focusWidget(),Qt.Key.Key_S)
                check('candidate_shift_s_moves_down',page.caption_suggestion_text.selected==(1,0))
                geometry('candidates');shot('03-candidates')
                shift(QApplication.focusWidget(),Qt.Key.Key_R)
                check('candidate_shift_r_only_stages_current_word',page._caption_draft is not None and editor.toPlainText()==fixture.replace('吉它','吉他') and page._cue_lookup[cue_id].text==fixture)
                check('handled_row_remains_focused',page.caption_suggestion_text.owns_focus() and page.caption_suggestion_text.selected==(-1,-1))
                shift(QApplication.focusWidget(),Qt.Key.Key_S)
                check('last_row_shift_s_returns_to_draft',editor.hasFocus())
                shift(editor,Qt.Key.Key_R)
                check('draft_shift_r_confirms_after_candidate',page._caption_draft is None and page._cue_lookup[cue_id].text==fixture.replace('吉它','吉他'))
            finally:
                captions.current_issue_view,captions.review_suggestions=old_view,old_rules
                page._review_suggestions_for=old_review
            page.undo_stack.undo();page.undo_stack.undo()
            check('fixture_undo_restores_real_source',page._cue_lookup[cue_id].text==original)

            editor=opened();editor.setPlainText(original+' retry')
            writer_type=type(page.cue_controller);writer=writer_type.set_text
            def failure(*args,**kwargs):raise ValueError('isolated write validation failure')
            try:
                writer_type.set_text=failure;shift(editor,Qt.Key.Key_R)
                check('failure_retains_text_and_chinese_reason',page._caption_draft is not None and editor.toPlainText()==original+' retry' and '输入内容已保留' in page.caption_editor_error.text())
                check('technical_detail_is_collapsed',not page.subtitle_edit_card.error_detail.isVisible())
                geometry('failure');shot('04-failure')
            finally:writer_type.set_text=writer
            shift(editor,Qt.Key.Key_R)
            check('retry_without_changing_text_succeeds',page._caption_draft is None and page._cue_lookup[cue_id].text==original+' retry')
            page.undo_stack.undo()

            editor=opened();editor.setPlainText(original+' SAVED_A')
            shift(editor,Qt.Key.Key_R)
            QTest.mouseClick(page.save_button,Qt.MouseButton.LeftButton)
            saved=Path(page.project_path)
            wait(lambda:page.undo_stack.isClean(),90)
            disk=load_project(saved)
            check('normal_save_persists_confirmed_text',next(c.text for c in disk.cues if c.id==cue_id)==original+' SAVED_A')
            generation=page.session.generation
            editor=opened();editor.setPlainText('未确认草稿不得留到重开')
            page._close_project_session('caption-editor-a-audit')
            page.open_project(saved)
            wait(lambda:page.project is not None and page.session.generation>generation and page._readiness.ready,120)
            check('reopen_preserves_text_and_discards_unconfirmed_draft',page._caption_draft is None and page._cue_lookup[cue_id].text==original+' SAVED_A')
            result['project_after']=dict(cues=len(page.project.cues),translations=len(page.project.generation_metadata.get('translations',{})))
            check('full_cue_counts_preserved',result['project_after']['cues']==result['project']['cues'] and result['project_after']['translations']==result['project']['translations'])
            from .blank_project_audit import _provider_calls
            check('no_provider_requests',_provider_calls==0)
            result['passed']=True
        except BaseException:
            result['error']=traceback.format_exc()
        finally:
            receipt()
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            if page is not None:page.undo_stack.setClean()
            window.result_exit_code=0 if result['passed'] else 1
            window.close()
    QTimer.singleShot(200,execute)
