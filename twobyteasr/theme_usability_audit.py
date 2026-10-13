"""Opt-in normal Studio gestures; shared by source and frozen acceptance."""
import copy,json
from PySide6.QtCore import Qt,QPoint,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox


def verify(page,out,phase,check,wait,pump):
    from .theme_application_ui import refresh_application_ui
    from .web_placement import cue_placement
    from .studio_design_target import design_cue
    path=out/'expected-placement.json'
    if phase=='reopen':
        expected=json.loads(path.read_text('utf8'))
        cue=design_cue(page.project,page.selected_cue_id)
        check('reopened complete-object scale and position match',cue_placement(page.project,cue)==expected)
        refresh_application_ui(page)
        check('reopened cue status says applied','已应用到当前字幕' in page.ai_application_status.text())
        verify_seeks(page,out,phase,check,wait,pump)
        return
    refresh_application_ui(page)
    check('primary apply action has clear label and width',page.ai_apply_button.text()=='重新应用到当前字幕'
          and page.ai_apply_button.width()>200 and page.ai_apply_button.height()>=40)
    page.undo_stack.undo();pump(.3);refresh_application_ui(page)
    check('auto apply can undo and status follows','尚未应用' in page.ai_application_status.text())
    page.undo_stack.redo();pump(.3);refresh_application_ui(page)
    check('redo restores applied status','已应用到当前字幕' in page.ai_application_status.text())
    page._scroll_ai_panel_into_view(page.ai_local_polish_button);pump(.2)
    old=page._ai_request_generation
    def accept_polish():
        dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QDialog)
                    and w.isVisible() and w.windowTitle()=='本地精修文字')
        button=dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        QTest.mouseClick(button,Qt.LeftButton)
    QTimer.singleShot(250,accept_polish)
    QTest.mouseClick(page.ai_local_polish_button,Qt.LeftButton)
    wait(lambda:page._ai_request_generation>old and page._theme_drafts().phase in {'APPLIED','FAILED'},90,'ordinary local text finishing dialog')
    check('local finishing validates and applies',page._theme_drafts().phase=='APPLIED')
    check('local revision preserves original and receipt',(page._theme_drafts().root/'local-revision/original.json').is_file()
          and (page._theme_drafts().root/'local-revision/receipt.json').is_file())
    page.video.set_paused(True);page._seek(1.0);pump(.6)
    page.ensure_active_subtitle_renderer(reason='usability-audit')
    overlay=page.position_overlay
    wait(lambda:overlay.isVisible() and overlay._measured_bounds is not None,30,'measured artwork scale handles')
    before=copy.deepcopy(cue_placement(page.project,design_cue(page.project,page.selected_cue_id)))
    rect=overlay._subtitle_rect()
    start=rect.bottomRight().toPoint();finish=start+QPoint(round(rect.width()*.18),round(rect.height()*.18))
    handle=overlay.window().windowHandle()
    # One QWindow event stream for press/move/release, as in a real gesture.
    QTest.mousePress(handle,Qt.LeftButton,Qt.NoModifier,overlay.mapTo(overlay.window(),start));pump(.05)
    for i in range(1,9):
        point=start+(finish-start)*i/8
        QTest.mouseMove(handle,overlay.mapTo(overlay.window(),point));pump(.025)
    QTest.mouseRelease(handle,Qt.LeftButton,Qt.NoModifier,overlay.mapTo(overlay.window(),finish));pump(.5)
    cue=design_cue(page.project,page.selected_cue_id);scaled=copy.deepcopy(cue_placement(page.project,cue))
    check('real corner drag scales the complete theme',scaled['scaleX']>before['scaleX']*1.2)
    check('corner scaling keeps aspect ratio',abs(scaled['scaleX']/before['scaleX']-scaled['scaleY']/before['scaleY'])<1e-5)
    check('scale does not overwrite source font size','font_size' not in cue.transform)
    page.undo_stack.undo();pump(.3)
    check('scale undo restores exact placement',cue_placement(page.project,design_cue(page.project,page.selected_cue_id))==before)
    page.undo_stack.redo();pump(.3)
    check('scale redo restores exact placement',cue_placement(page.project,design_cue(page.project,page.selected_cue_id))==scaled)
    wait(lambda:overlay.isVisible() and overlay._measured_bounds is not None,30,'scaled artwork measured again')
    start=overlay._subtitle_rect().center().toPoint();finish=start+QPoint(22,-18)
    QTest.mousePress(handle,Qt.LeftButton,Qt.AltModifier,overlay.mapTo(overlay.window(),start));pump(.05)
    QTest.mouseMove(handle,overlay.mapTo(overlay.window(),finish));pump(.1)
    QTest.mouseRelease(handle,Qt.LeftButton,Qt.AltModifier,overlay.mapTo(overlay.window(),finish));pump(.4)
    placed=cue_placement(page.project,design_cue(page.project,page.selected_cue_id))
    check('scaled object can move without losing scale',placed['x']>scaled['x'] and placed['y']<scaled['y']
          and placed['scaleX']==scaled['scaleX'])
    path.write_text(json.dumps(placed,ensure_ascii=False,indent=2),'utf8')
    page.grab().save(str(out/'scaled-studio-ui.png'))
    if page.video.controller:page.video.controller.screenshot_to_file(out/'scaled-native-canvas.png',mode='window')
    verify_seeks(page,out,phase,check,wait,pump)
    page._seek(1.75);pump(.4)  # Return to the shared editor/export audit sample.


def verify_seeks(page,out,phase,check,wait,pump):
    samples=[]
    for index,ms in enumerate([250,283,317,400,600,1100,317,250,600,283,1100]):
        page.video.set_paused(True);page._seek(ms/1000)
        wait(lambda:abs(getattr(page.advanced_cue_overlay,'_web_frame_context',{}).get('web_stage_ms',-999)-ms)<35,
            15,'current frame after forward/backward seek '+str(ms))
        samples.append(dict(request_ms=ms,frame=dict(page.advanced_cue_overlay._web_frame_context)))
        if page.video.controller:page.video.controller.screenshot_to_file(out/f'{phase}-seek-{index:02}-{ms}.png',mode='window')
    check('repeated early forward and backward seeks publish requested cue time',len(samples)==11)
    (out/(phase+'-seek-evidence.json')).write_text(json.dumps(samples,ensure_ascii=False,indent=2),'utf8')
    page._seek(1.75);pump(.3)
