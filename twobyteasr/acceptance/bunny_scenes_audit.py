"""Exercise Bunny's scene prompts on the actual Windows application pages."""
import json
import os
import threading
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def run():
        checks = []
        try:
            audit(window, output, checks)
            result = dict(passed=True, checks=checks, checks_passed=len(checks))
        except Exception:
            result = dict(passed=False, checks=checks, error=traceback.format_exc())
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().exit(0 if result['passed'] else 1)

    QTimer.singleShot(500, run)


def audit(window, output, checks):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from ..app.bunny_chat import show_bunny
    from ..app.bunny_errands import SEAT, _say
    from ..app.sample_project import ensure_sample_project, tutorial_ai_preview
    from ..design.bunny_button_fx import WobbleEffect
    from ..design.theme_manager import apply_theme, save_theme_key

    def check(name, condition):
        checks.append(dict(name=name, passed=bool(condition)))
        if not condition:
            raise AssertionError(name)

    def wait(name, condition, seconds=12):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(30)
        check(name, condition())

    def shot(name):
        check(name + ' screenshot saved', window.grab().save(str(output / (name + '.png'))))

    def says(text):
        bubble = puck.carrier.bubble
        return bubble is not None and bubble.isVisible() and _say(text) in bubble.text

    theme = os.environ.get('TWOBYTEASR_BUNNY_THEME', 'sand')
    save_theme_key(theme)
    apply_theme(theme, QApplication.instance())
    window.resize(1440, 900)
    window.show()
    QTest.qWait(1200)
    chat = show_bunny(window)
    check('the resident rabbit is folded on the visible main window', chat is not None and chat.collapsed)
    errands, puck = chat.errands, chat.puck
    errands.interrupt()
    errands.input_at = time.monotonic() + 120
    choose = errands._suggestion('home')
    check('Home points to the actual media picker', choose is not None and choose[0] is window.choose_media_button)

    if os.environ.get('TWOBYTEASR_BUNNY_ENTRY_AUDIT') == '1':
        from ..app import ui_zoom

        original_zoom = ui_zoom.zoom_percent()
        ui_zoom.set_zoom_percent(120)
        window.settle_for_picture()
        check('the two Home wordmark labels cannot select text',
              all(label.textInteractionFlags() == Qt.TextInteractionFlag.NoTextInteraction
                  for label in (window.header_subtitle, window.brand)))
        check('the Home brand shows an arrow cursor',
              window.header_subtitle.parentWidget().parentWidget().cursor().shape() == Qt.CursorShape.ArrowCursor)
        window.model_workshop_button.click()
        workshop = window.workshop_page
        wait('the model workshop opens through its Home button',
             lambda: window.pages.currentWidget() is workshop and workshop._ui_built, 20)
        workshop.return_requested.emit()
        wait('the workshop returns to Home', lambda: window.pages.currentWidget() is window.settings_scroll)
        wait('the return transition finishes', lambda: window.__dict__.get('_page_cover_ahead') is None)
        QTest.qWait(700)
        controls = (window.app_header, window.model_workshop_button, window.bottom_bar)
        positions = [widget.geometry().getRect() for widget in controls]
        shot('entry-home-return')
        QTest.qWait(1000)
        check('the Home controls stay put at 120 percent after returning',
              positions == [widget.geometry().getRect() for widget in controls])

        ui_zoom.set_zoom_percent(original_zoom)

        voice = chat.voice
        old_enabled, original_pcm = voice.enabled, voice.play_pcm
        received = []

        def observe_pcm(pcm):
            queued = original_pcm(pcm)
            received.append((pcm, queued))
            return queued

        voice.play_pcm = observe_pcm
        try:
            voice.set_enabled(True)
            chat.sfx._last.pop('cheer', None)
            chat.mascot.stop_move()
            check('the visible rabbit starts cheering', chat.mascot.play('cheer'))
            issued = [item for item in received if item[0]]
            check('the visible rabbit cheer submits stereo PCM through MascotVoice',
                  bool(issued and len(issued[-1][0]) % 4 == 0 and len(set(issued[-1][0])) > 8))
            endpoint = dict(native_sink_accepted=bool(issued[-1][1]), pcm_bytes=len(issued[-1][0]))
            (output / 'entry-audio-endpoint.json').write_text(json.dumps(endpoint, indent=2), 'utf8')
            chat.voice_button.click()
            check('the chat voice control switches off', not voice.enabled)
            received.clear()
            chat.sfx._last.pop('cheer', None)
            chat.mascot.stop_move()
            check('the visible rabbit starts cheering', chat.mascot.play('cheer'))
            check('turning off the rabbit voice prevents new action audio', not received)
        finally:
            voice.play_pcm = original_pcm
            voice.set_enabled(old_enabled)

    window._switch_page(window.pages.widget(1))
    window.progress_percent.setText('20%')
    window.progress_bar.setRange(0, 100)
    window.progress_bar.setValue(20)
    window.progress_stage.setText('准备字幕')
    window.stage_elapsed.setText('01:00')
    wait('recognition scene uses the real progress page', lambda: getattr(errands, '_context', '') == 'progress')
    check('rabbit does not treat safe cancel as a toy', window.cancel_run_button not in errands._buttons())
    ride = dict(errands.candidates()).get('ride_bar')
    check('the real recognition bar is a ride target', ride is not None and ride[0] is window.progress_bar)
    check('rabbit starts the recognition bar animation', errands.start('ride_bar', ride))
    try:
        wait('rabbit sits on the real progress bar', lambda: chat.mascot.current_move == 'sit', 8)
    except AssertionError as error:
        raise AssertionError(f'{error}: {errands.name=}, {puck.mode=}, {puck.pos=}, '
                             f'{chat.mascot.current_move=}, {errands._rect(window.progress_bar)=}') from error
    seat = puck.window_point(SEAT)
    shot('01-recognition-ride')
    window.progress_percent.setText('65%')
    window.progress_bar.setValue(65)
    wait('rabbit moves along as the recognition progress advances',
         lambda: puck.window_point(SEAT).x() > seat.x() + 80, 6)
    errands.interrupt()

    window._switch_page(window.pages.widget(2))
    window.result_title.setText('字幕已生成')
    window.result_ai_card.setEnabled(True)
    wait('completion has its own scene', lambda: getattr(errands, '_context', '') == 'result')
    wait('completion announces the result', lambda: says('字幕已生成'))
    target = errands._suggestion('result')
    check('completion recommends the real AI proofreading card', target is not None and target[0] is window.result_ai_card)
    shot('02-recognition-result')

    sample = ensure_sample_project()
    check('the demo project is isolated', sample.resolve().is_relative_to(output.resolve()))
    if os.environ.get('TWOBYTEASR_BUNNY_ENTRY_AUDIT') == '1':
        cover = sample.parent / 'preview/project-cover.jpg'
        cover.parent.mkdir(parents=True, exist_ok=True)
        stripes = QImage(640, 360, QImage.Format.Format_RGB32)
        stripes.fill(QColor('#3050a0'))
        painter = QPainter(stripes)
        for x in range(0, stripes.width(), 32):
            painter.fillRect(x, 0, 6, stripes.height(), QColor('#ffffff'))
        painter.end()
        if not stripes.save(str(cover)):
            raise AssertionError('could not create the isolated loading cover')
    window.open_studio_project(sample, source='bunny_scene_audit')
    if os.environ.get('TWOBYTEASR_BUNNY_ENTRY_AUDIT') == '1':
        def loading_view():
            session = window.__dict__.get('_studio_loading_session')
            view = session.view if session is not None and session.active else None
            return view if view is not None and view.isVisible() and not view.library_mode else None

        wait('the opening project shows its real loading view', loading_view)
        view = loading_view()
        backdrop = view._ambient_pixmap()
        check('the photographed loading cover has a full-resolution opaque blur',
              backdrop is not None and backdrop.size() == view.size()
              and backdrop.toImage().pixelColor(0, 0).alpha() == 255)
        back_image = backdrop.toImage()
        columns = [back_image.pixelColor(x, back_image.height() // 2).red()
                   for x in range(back_image.width() // 4, 3 * back_image.width() // 4)]
        check('the background blends the sharp source stripes',
              max(columns) - min(columns) < 45 and max(columns) > 40)
        check('project loading screenshot saved', view.grab().save(str(output / 'entry-project-loading.png')))
    wait('Studio opens the demo project',
         lambda: (page := window.built_page('studio')) is not None and page._readiness.ready, 35)
    studio = window.built_page('studio')
    wait('Studio finishes its loading transition',
         lambda: window.pages.currentWidget() is studio and not window._studio_loading_session.active, 35)
    window._show_glossary_proofread(studio.project_path, studio.project, studio=studio)
    review = window.glossary_proofread_page
    wait('the real proofreading page opens', lambda: getattr(errands, '_context', '') == 'proofread')
    wait('proofread introduces AI proofreading', lambda: says('AI 词库校对'))
    wait('automatic local checks settle', lambda: not review.checks_running(), 35)
    review._set_busy(True)
    try:
        QTest.qWait(550)
        check('local matching never exposes the AI bar', not review.ai_progress_bar.isVisible())
        check('local matching never reports AI started', not says('AI 开始校对'))
    finally:
        review._set_busy(False)

    release_worker = threading.Event()

    def stand_in(*args, **kwargs):
        if not release_worker.wait(15):
            raise TimeoutError('audit did not release the offline AI response')
        return tutorial_ai_preview(*args, **kwargs)

    review.ai_stand_in = stand_in
    review.ai_button.click()
    try:
        wait('the actual AI worker shows a dedicated batch bar', lambda: review.ai_progress_bar.isVisible())
        wait('rabbit announces the AI job', lambda: says('AI 开始校对'))
        review._worker.progress.emit(3, 8)
        wait('the real batch callback updates progress', lambda: review.ai_progress_bar.value() == 3)
        check('rabbit reads the batch ratio', errands._bar_percent('proofread') == 38)
        ride = dict(errands.candidates()).get('ride_bar')
        check('rabbit uses the actual AI batch bar', ride is not None and ride[0] is review.ai_progress_bar)
        shot('03-proofreading-ai-progress')
    finally:
        release_worker.set()
    wait('offline AI completion closes the dedicated batch bar', lambda: not review.ai_progress_bar.isVisible())
    wait('rabbit announces the accepted AI result', lambda: says('校对好了'))
    shot('04-proofreading-ai-complete')
    review.ai_stand_in = None

    window._switch_page(studio)
    studio._open_render_dialog(skip_preflight=True)
    export = studio.export_workspace
    wait('the real Studio export workspace has its own scene',
         lambda: export is not None and getattr(errands, '_context', '') == 'export', 15)
    check('rabbit suggests the real video export control', errands._suggestion('export')[0] is export.export_button)
    export._running = True
    export.pages.setCurrentWidget(export.exporting_page)
    export.progress.setValue(42)
    wait('rabbit announces video rendering', lambda: says('开始导出'))
    check('rabbit reads the real rendering bar', errands._bar_percent('export') == 42)
    shot('05-video-export-progress')
    export._show_success(str(output / 'demo.mp4'))
    wait('rabbit announces video delivery', lambda: says('视频导出好啦'))
    check('rabbit suggests the real output-folder control', errands._suggestion('export')[0] is export.open_folder_button)
    shot('06-video-export-complete')
    studio._close_export_workspace()

    card = QWidget(window)
    card.setStyleSheet('QWidget { background: #2050a0; } '
                       'QPushButton { background: #c03060; border: none; border-radius: 16px; color: white; }')
    card.setGeometry(10, 50, 300, 160)
    button = QPushButton('开始', card)
    button.setGeometry(60, 50, 180, 48)
    card.show()
    card.raise_()
    effect = WobbleEffect(button, 20)
    button.setGraphicsEffect(effect)
    effect.x = 0.6
    effect.update()
    QTest.qWait(120)
    picture = card.grab()
    image, scale = picture.toImage(), picture.devicePixelRatio()
    corner = QColor(image.pixel(round(62 * scale), round(52 * scale)))
    middle = QColor(image.pixel(round(150 * scale), round(74 * scale)))
    check('moving button keeps its foreground', middle.red() > 150 and middle.blue() < 140)
    check('moving button corner shows the parent background', corner.blue() > 130 and corner.red() < 90)
    check('rounded button pixel evidence saved', picture.save(str(output / '07-rounded-button.png')))
    card.deleteLater()
    chat.close_chat()
