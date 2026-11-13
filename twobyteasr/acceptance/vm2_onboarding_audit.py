"""Normal-window evidence for required first use and full glossary names."""
import json, os, sys, time, traceback
from unittest.mock import patch


def start(window, output):
    from pathlib import Path
    from PySide6.QtCore import QTimer, Qt, QPoint, QRect
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance()
    checks = []
    result = dict(passed=False, checks=checks, dpr=window.devicePixelRatioF())

    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        (output / 'progress.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        if not value:
            raise AssertionError(name)

    def settle(seconds=.2):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def wait(predicate, seconds=25):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            settle(.03)
        check('wait for ready content', predicate())

    def shot(widget, name):
        check('screenshot ' + name, widget.grab().save(str(output / (name + '.png'))))

    def run():
        try:
            from ..app import onboarding, ui
            from ..app.quick_setup import QuickSetupDialog
            from ..app.home_tour import GuidedTour, start_home_tour
            from ..design.theme_manager import apply_theme
            from ..glossary import multilingual_terms as m
            from ..glossary.glossary_term_cards import TermCardDelegate, card_parts
            from ..i18n import translate
            check('normal Windows platform', app.platformName() == 'windows')
            check('owned private profile', Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve().is_relative_to(output))
            window.showNormal()
            window.resize(1440, 900)
            window._return_to_settings()
            settle(.5)

            for theme in ('warm', 'grape'):
                apply_theme(theme, app)
                for language in ('zh', 'en', 'ja'):
                    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                    dialog = QuickSetupDialog(window, plan_keys=['cloud', 'light'], size_of=lambda _b: 1., required=True)
                    dialog.show()
                    settle(.65)
                    check('recommended card is preselected ' + theme + language, dialog.choice is not None)
                    check('required controls ' + theme + language, dialog.later_button.isHidden() and dialog.tour_check.isHidden() and dialog.tour_check.isChecked())
                    check('first-use note visible ' + theme + language, dialog.required_note.isVisible())
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    settle(.7)
                    check('Escape cannot bypass confirmation ' + theme + language, dialog.isVisible() and dialog.result() == 0)
                    dialog.close()
                    settle(.7)
                    check('window close cannot bypass confirmation ' + theme + language, dialog.isVisible())
                    check('required explanation fits ' + theme + language, dialog.rect().contains(dialog.required_note.geometry()))
                    shot(dialog, 'required-picker-' + theme + '-' + language)
                    dialog.select('light')
                    dialog.go_button.click()
                    wait(lambda: not dialog.isVisible())
                    check('explicit selection accepted ' + theme + language, dialog.result() == QDialog.DialogCode.Accepted and dialog.backends is not None and dialog.tour)
                    dialog.deleteLater()
                window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))

            # Exercise the production entry and real picker; only the detailed
            # configuration and download side effects are replaced by fixtures.
            original_skip = os.environ.pop('TWOBYTEASR_SKIP_FIRST_RUN_WIZARD', None)
            onboarding.save_state(dict(fresh=True, guide=True, tour_done=False, first_task_done=False))
            inspect_errors = []
            picker_count = []

            def inspect_picker():
                # SpringDialog.exec uses a guarded nonmodal window and its own
                # event loop; QApplication.activeModalWidget is intentionally empty.
                dialog = next((w for w in app.topLevelWidgets() if isinstance(w, QuickSetupDialog) and w.isVisible()), None)
                if not isinstance(dialog, QuickSetupDialog):
                    QTimer.singleShot(50, inspect_picker)
                    return
                try:
                    picker_count.append(True)
                    check('production first-use picker required', dialog.required and dialog.isVisible())
                    if len(picker_count) == 1:
                        dialog._choose_custom()
                        QTimer.singleShot(450, inspect_picker)
                    else:
                        check('cancelled detailed setup returns to chooser', len(picker_count) == 2)
                        check('cancel did not stamp setup complete', not onboarding.load_state().get('setup_offered'))
                        dialog.select('cloud')
                        dialog.go_button.click()
                except Exception:
                    inspect_errors.append(traceback.format_exc())
                    dialog.accept()

            with patch.object(ui, '_open_guided_setup', return_value=False), patch.object(ui, '_apply_setup_choice', return_value=None):
                QTimer.singleShot(250, inspect_picker)
                ui._offer_first_run_setup(window)
            if original_skip is not None:
                os.environ['TWOBYTEASR_SKIP_FIRST_RUN_WIZARD'] = original_skip
            check('production picker automation completed', not inspect_errors and len(picker_count) == 2, inspect_errors)
            check('confirmed setup persists', onboarding.load_state().get('setup_offered') and window._first_run_required)
            wait(lambda: window.findChild(GuidedTour) is not None and window.findChild(GuidedTour).mode != 'closed')
            tour = window.findChild(GuidedTour)
            check('production picker starts required tutorial', tour.required and tour.skip.isHidden() and tour.chip_end.isHidden())
            wait(lambda: tour.mode == 'shown' and tour.bubble.isVisible())
            QTest.keyClick(window, Qt.Key.Key_Escape)
            settle(.4)
            check('required tutorial survives Escape', tour.mode != 'closed' and not onboarding.load_state().get('tour_done'))
            shot(window, 'required-tutorial-start')
            shot(tour, 'required-tutorial-overlay')
            window._first_run_downloads = None  # this audit never requests models
            tour.close_tour(False)  # simulate the app stopping with unfinished teaching
            settle(.25)
            check('unfinished tutorial remains required', onboarding.first_run_required(onboarding.load_state()))
            # Returning at the next launch skips the already-confirmed picker.
            with patch.object(ui, '_open_quick_setup', side_effect=AssertionError('picker repeated')):
                old_skip = os.environ.pop('TWOBYTEASR_SKIP_FIRST_RUN_WIZARD', None)
                ui._offer_first_run_setup(window)
                if old_skip is not None:
                    os.environ['TWOBYTEASR_SKIP_FIRST_RUN_WIZARD'] = old_skip
            wait(lambda: any(t.mode != 'closed' for t in window.findChildren(GuidedTour)))
            tour = next(t for t in window.findChildren(GuidedTour) if t.mode != 'closed')
            check('unfinished tutorial starts again', tour.required)
            # The existing full teaching sequence and assets are retained. New
            # completion state is checked by its real finished signal boundary.
            check('full tutorial sequence retained', len(tour.steps) >= 10, len(tour.steps))
            with patch.object(window, '_start_first_run_downloads', return_value=None):
                tour.close_tour(True)
                settle(.4)
            check('finished tutorial clears required state', onboarding.load_state().get('tour_done') and not window._first_run_required and not onboarding.first_run_required())
            for state in (dict(fresh=False), dict(fresh=True, first_task_done=True), onboarding.load_state()):
                check('existing or completed users exempt', not onboarding.first_run_required(state))
            manual = start_home_tour(window)
            settle(.2)
            check('manual tutorial still skippable', not manual.required and not manual.skip.isHidden())
            manual._user_close()
            check('manual tutorial closes normally', manual.mode == 'closed')

            # Populate only an owned throwaway library via production storage.
            window._return_to_settings()
            library = window.legacy.create_learned_content('首次使用卡片验收', create_new=True)
            words = ['倾泻', '彩虹独角兽', '彩虹独角兽长名字', '普通术语']
            concepts = [m.concept(w, 'zh-Hans', category='game_term') for w in words]
            m.mutate(window.legacy, library, lambda dest, entry: dest.extend(concepts))
            window._manage_terms()
            settle(.4)
            page = window.term_library_page._ensure_library()
            page.add_game_item('首次使用卡片验收', select=True, library_id=library)
            wait(lambda: page._library_key() == library and page._term_model.rowCount() == 4)
            page.term_display_language.setCurrentIndex(page.term_display_language.findData('en'))
            for theme in ('warm', 'grape'):
                apply_theme(theme, app)
                for width in (1440, 1180, 1600):
                    window.resize(width, 900)
                    settle(.25)
                    view = page.listing
                    delegate = view.itemDelegate()
                    check('card delegate production instance', isinstance(delegate, TermCardDelegate))
                    for row in range(page._term_model.rowCount()):
                        index = page._term_model.index(row, 0)
                        rect = view.visualRect(index)
                        parts = card_parts(page._term_model.data_for_row(row))
                        tag = delegate.category_rect(rect, index, view.font())
                        check('category remains inside card', rect.contains(tag), dict(rect=rect.getRect(),tag=tag.getRect()))
                        check('category label full width', tag.width() >= delegate._tag_width(view.font(), parts), dict(word=parts['word'],tag=tag.width(),needed=delegate._tag_width(view.font(),parts)))
                        top = delegate.content_rects(rect, parts)[0]
                        available = tag.left() - 8 - top.left() if tag.top() < top.bottom() else top.width()
                        font = delegate.word_font(view.font(), available, parts['word'])
                        check('whole name fits before eliding', QFontMetrics(font).horizontalAdvance(parts['word']) <= available, dict(word=parts['word'],available=available))
                    check('short alias placeholder retained', page.term_alias_editor.placeholderText() == translate('常被听成（可不填）'))
                    check('full alias guidance on hover', page.term_alias_editor.toolTip() == translate('常被听成（可不填，多个用顿号）'))
                    from PySide6.QtWidgets import QLabel, QPushButton
                    outside = []
                    for child in page.term_toolbar.findChildren(QLabel) + page.term_toolbar.findChildren(QPushButton):
                        if not child.isVisible():
                            continue
                        position = child.mapTo(page.term_toolbar, QPoint())
                        if not page.term_toolbar.rect().contains(QRect(position, child.size())):
                            outside.append(child.objectName() or child.text())
                    check('resized toolbar keeps controls within its bounds', not outside, outside)
                    shot(window, 'cards-' + theme + '-' + str(width))
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot(app.activeModalWidget() or window, 'failure')
            except Exception:
                pass
        finally:
            from ..diagnostics.build_identity import load_build_identity
            result.update(pid=os.getpid(), executable=sys.executable, identity=load_build_identity().to_dict())
            def stopped():
                result['gui_shutdown'] = True
                (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
            app.aboutToQuit.connect(stopped)
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
            app.exit(0 if result['passed'] else 1)
    QTimer.singleShot(600, run)
