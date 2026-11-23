"""Exercise cumulative delivery controls through the real Studio and Home windows."""
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QToolButton

from ..app.application_settings_ui import ApplicationSettingsDialog
from ..design.transitions import capture_page
from ..projects.save_changes_dialog import SaveChangesDialog
from ..projects.studio_project import StudioSpeaker, load_project
from ..studio.speaker_name_style import SpeakerNameStyleDialog
from ..studio.studio_speaker_manager import SpeakerManagerDialog
from ..timeline.studio_commands import SetCueFieldsCommand


def run(window, page, output, check, wait):
    app = QApplication.instance()

    def modal(dialog_type, open_dialog, act, *, close=True):
        problems = []
        handled = []

        def respond():
            dialog = next((widget for widget in app.topLevelWidgets()
                           if isinstance(widget, dialog_type) and widget.isVisible()), None)
            if dialog is None:
                return
            timer.stop()
            try:
                act(dialog)
                handled.append(True)
            except Exception as error:
                problems.append(error)
            finally:
                if close or problems:
                    dialog.reject()

        timer = QTimer(window)
        timer.timeout.connect(respond)
        timer.start(30)
        try:
            open_dialog()
        finally:
            timer.stop()
            timer.deleteLater()
        if problems:
            raise problems[0]
        check(f'{dialog_type.__name__} was opened and operated', bool(handled))

    def settings(dialog):
        old_index = dialog.pages.currentIndex()
        target = (old_index + 1) % dialog.navigation.count()
        item = dialog.navigation.item(target)
        dialog.navigation.scrollToItem(item)
        QTest.mouseClick(dialog.navigation.viewport(), Qt.LeftButton,
                         pos=dialog.navigation.visualItemRect(item).center())
        check('settings navigation changes to the requested page', dialog.pages.currentIndex() == target)
        picture = capture_page(dialog.pages)
        check('translucent settings capture retains visible page pixels', picture is not None)
        image = picture.toImage()
        colors = [image.pixelColor(x * image.width() // 10, y * image.height() // 10)
                  for x in range(1, 10) for y in range(1, 10)]
        check('settings capture is neither empty nor all black',
              sum(c.alpha() > 0 and c.value() > 24 for c in colors) >= len(colors) // 2)
        picture.save(str(output / 'settings-page.png'))

    modal(ApplicationSettingsDialog, window._open_application_settings, settings)
    QTest.qWait(350)
    page._seek(0.6)
    page.timeline.setFocus()
    QTest.keyClick(page.timeline, Qt.Key_E)
    wait(lambda: page._caption_draft is not None and page.subtitle_edit_input.hasFocus(), 5)
    editor = page.subtitle_edit_input
    check('E focuses the current subtitle immediately', page._caption_draft.target.cue_id == 'a')
    QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
    check('Ctrl+A selects the whole subtitle without another click',
          editor.textCursor().selectedText() == editor.toPlainText())
    QTest.keyClick(editor, Qt.Key_Home)
    QTest.keyClick(editor, Qt.Key_Right)
    check('right arrow moves the subtitle caret', editor.textCursor().position() == 1)
    page.subtitle_edit_dock.grab().save(str(output / 'caption-edit-focus.png'))
    page._cancel_canvas_inline_edit()

    menu = page.cue_ai_button.menu()
    menu.popup(page.cue_ai_button.mapToGlobal(page.cue_ai_button.rect().bottomLeft()))
    try:
        QTest.qWait(60)
        check('lively marks is available in the real subtitle AI menu',
              page.ai_lively_marks_action in menu.actions() and page.ai_lively_marks_action.isEnabled())
        menu.grab().save(str(output / 'subtitle-ai-menu.png'))
    finally:
        menu.close()

    cue = page.project.cues[0]
    if not page.project.speakers:
        page.project.speakers.append(StudioSpeaker(cue.speaker_id, '驗收說話人'))
        page.cue_controller.model_changed()

    def edit_speaker(manager):
        def choose(dialog):
            swatch = dialog.swatches[0]
            QTest.mouseClick(swatch, Qt.LeftButton)
            check('speaker color is selected in the name style dialog',
                  dialog.changes().get('name_color') == str(swatch.property('swatch')).upper())
            dialog.grab().save(str(output / 'speaker-name-style.png'))
            buttons = dialog.findChild(QDialogButtonBox)
            QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.LeftButton)

        modal(SpeakerNameStyleDialog, manager.name_style_button.click, choose, close=False)

    modal(SpeakerManagerDialog, page._open_speaker_manager, edit_speaker)
    check('speaker style changes the project', any(s.name_color for s in page.project.speakers))
    page.undo_stack.undo()
    check('speaker style rolls back in one step', not any(s.name_color for s in page.project.speakers))

    project_path = Path(page.project_path)
    cue = page.project.cues[0]
    text = '本機驗收保存字幕'
    page.undo_stack.push(SetCueFieldsCommand(
        page.project, cue.id, {'text': text}, '保存驗收', page.cue_controller.model_changed))
    check('modified subtitle triggers the save guard', page.project_controller.dirty_guard.is_dirty())

    def save(dialog):
        dialog.grab().save(str(output / 'leave-save-prompt.png'))
        QTest.mouseClick(dialog.save_button, Qt.LeftButton)

    button = next((b for b in page.findChildren(QToolButton) if b.isVisible()
                   and '兔白字幕工程库' in b.toolTip()), None)
    open_library = (lambda: QTest.mouseClick(button, Qt.LeftButton)) if button else page._request_return_library
    modal(SaveChangesDialog, open_library, save, close=False)
    wait(lambda: page._project_view_state == 'hub', 20)
    check('save and leave automatically returns to the library', load_project(project_path).cues[0].text == text)

    window._switch_page(window.settings_scroll)
    media = output / 'fixture.mp4'
    window.import_media([str(media)], replace=True)
    wait(window.media_studio_button.isVisible, 10)
    window.grab().save(str(output / 'home-media-entry.png'))
    QTest.mouseClick(window.media_studio_button, Qt.LeftButton)
    wait(lambda: page.project is not None and page._readiness.ready
         and Path(str(page.project.media.path)) == media, 35)
    check('home media button opens a new project with the selected video',
          Path(page.project_path) != project_path and window.pages.currentWidget() is page)
    window.grab().save(str(output / 'home-media-in-studio.png'))
    page.save()
    wait(lambda: not page.project_controller.dirty_guard.is_dirty(), 20)


def render_templates(output, check):
    from PIL import Image
    from ..caption_design.caption_components import compose
    from ..caption_design.web_theme import WebThemeDocument
    from ..caption_style.style_recipe import StyleRecipe
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    from ..rendering.advanced_renderer import compile_composition_data
    from ..rendering.renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob

    sample = '這一波操作直接把我看傻了'
    marks = [
        {'start': 2, 'end': 4, 'strike': True},
        {'start': 4, 'end': 6, 'highlight': True},
        {'start': 8, 'end': 11, 'bold': True},
    ]
    jobs = []
    for name, composition in (
        ('vhs-signal', {'version': 12, 'template': 'vhs-signal'}),
        ('hud-lock', {'version': 12, 'template': 'hud-lock'}),
        ('glass', {'version': 11, 'kit': 'glass'}),
    ):
        theme = WebThemeDocument.from_dict({'name': name, **compose(composition)}).to_dict()
        project = SubtitleProject(
            media=StudioMedia(str(output / 'fixture.mp4'), duration_ms=4000, width=960, height=540),
            cues=[StudioCue(name, 0, 4000, sample, style_id='default',
                            appearance_override={'text_marks': marks})],
            styles=[SubtitleStyle('default', '驗收樣式', font_family='Source Han Sans SC Heavy', font_size=66)],
            style_recipes={'default': StyleRecipe(name=name, engine='remotion', web_theme=theme).to_dict()},
        )
        props = compile_composition_data(project, width=960, height=540, fps=30,
                                         start_seconds=0, duration_seconds=4)
        check(f'{name} receives inline marks while keeping the subtitle text',
              props['cues'][0]['text'].startswith(sample) and len(props['cues'][0]['text']) > len(sample))
        for frame in (8, 42):
            jobs.append(RendererJob(str(output / f'{name}-{frame}.png'), props, frame,
                                    job_kind='diagnostic', cue_id=name, project_id='vm2-cumulative'))
    result = GLOBAL_RENDERER_SERVICE.render(jobs, render_type='still', resolution=(960, 540),
                                           batch_group='vm2-cumulative', timeout=150)
    check('production renderer completed the two dynamic templates and one kit',
          result.status.upper() in {'OK', 'DONE'})
    for job in jobs:
        result.require_job(job)
        with Image.open(job.output) as image:
            alpha = image.convert('RGBA').getchannel('A')
            check(f'{Path(job.output).stem} produced visible subtitle pixels',
                  image.size == (960, 540) and sum(alpha.histogram()[32:]) > 100)
    from PIL import ImageChops
    for name in ('vhs-signal', 'hud-lock'):
        with Image.open(output / f'{name}-8.png') as early, Image.open(output / f'{name}-42.png') as hold:
            change = ImageChops.difference(early.convert('RGB'), hold.convert('RGB'))
            check(f'{name} animates between entrance and hold', change.getbbox() is not None)
