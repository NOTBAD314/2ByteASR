"""Actual MainWindow controls and clock; all fixtures/profile are isolated."""
def run(window,page,output,check):
    import json,os,time
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..design.theme_manager import request_theme
    from ..projects.studio_project import studio_settings_path
    app=QApplication.instance();t=page.timeline;button=page.selection_center_toggle
    def wait(predicate,seconds=15):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:
            app.processEvents();QTest.qWait(10)
        if not predicate():raise TimeoutError('center audit wait')
    def centered():
        return abs(t._time_to_x(t.playhead_ms)-(t.TRACK_HEADER_WIDTH+t._content_right())/2)<1.5
    phase=os.environ.get('TWOBYTEASR_CENTER_PHASE','initial')
    expected=phase!='restart-off'
    check('center preference restored '+phase,button.isCheckable() and button.isChecked()==expected and t.center_playhead_mode==expected)
    page.cue_controller.cancel_selection();app.processEvents()
    check('center available without selected cue',button.isEnabled() and not page.selected_cue_id)
    if phase!='initial':
        button.setChecked(True)
        check('center restart can enable without selection',button.isChecked() and centered())
        return
    before=(t.playhead_ms,t.visible_duration_ms,page.undo_stack.count())
    QTest.mouseClick(button,Qt.LeftButton);QTest.mouseClick(button,Qt.LeftButton)
    check('center toggle preserves time zoom undo selection',before==(t.playhead_ms,t.visible_duration_ms,page.undo_stack.count()) and not page.selected_cue_id)
    check('center actual checked control',button.isChecked() and button.accessibleName()=='播放头持续居中')
    page.select_cue('b');before=page.selected_cue_id
    t.set_visible_window(0,6000);page._seek(2.0)
    wait(lambda:abs(t.playhead_ms-2000)<90 and not page.video._playback_clock.exact_seek_pending)
    check('center seek keeps zoom and target',centered() and t.visible_duration_ms==6000 and page.selected_cue_id==before)
    samples=[];page.video.set_paused(False)
    wait(lambda:not page.video._paused)
    start=t.playhead_ms
    for _ in range(30):
        QTest.qWait(50);app.processEvents()
        samples.append(dict(time=t.playhead_ms,left=t.visible_start_ms,centered=centered()))
    page.video.set_paused(True);wait(lambda:page.video._paused)
    (output/'center-samples.json').write_text(json.dumps(samples,indent=2),'utf8')
    check('center real playback advances',samples[-1]['time']-start>900)
    check('center each observed frame stays centered',all(s['centered'] for s in samples))
    check('center continuous viewport movement',len({s['left'] for s in samples})>20)
    check('center playback retains selection and zoom',page.selected_cue_id==before and t.visible_duration_ms==6000)
    t._horizontal_scrolled(1000);held=t.visible_start_ms
    QTest.qWait(150)
    check('center manual browse is held',not t.center_playhead(t.playhead_ms) and t.visible_start_ms==held and button.isChecked())
    page.video.set_paused(False);wait(lambda:not t._manual_view_hold and centered())
    page.video.set_paused(True);wait(lambda:page.video._paused)
    check('center resumes on actual play',centered())
    for flag in ('_scrub_drag','_pan_drag','_clip_drag','_range_drag'):
        old=getattr(t,flag);setattr(t,flag,True)
        try:
            held=t.visible_start_ms
            check('center pointer owns view '+flag,not t.center_playhead(9000,force=True) and t.visible_start_ms==held)
        finally:setattr(t,flag,old)
    for at in (0,12000):
        t.set_playhead(at);t.center_playhead(at,force=True)
        check('center bounds '+str(at),centered() and t._bounded_time_ms(-1)==0 and t._bounded_time_ms(13000)==12000)
    for theme in ('sand','midnight'):
        request_theme(theme);QTest.qWait(150)
        button.setChecked(True);app.processEvents()
        window.grab().save(str(output/('center-'+theme+'-on.png')))
        button.grab().save(str(output/('button-'+theme+'-on.png')))
        button.setChecked(False);app.processEvents()
        button.grab().save(str(output/('button-'+theme+'-off.png')))
        check('center unchecked uses ordinary range '+theme,not t.center_playhead_mode and t.visible_start_ms>=0)
    payload=json.loads(studio_settings_path().read_text('utf8'))
    check('center off saved to isolated profile',payload['studio_preferences']['playhead_centered'] is False)
