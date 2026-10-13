"""Opt-in normal-window brand verification, also embedded in the frozen EXE."""
import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, QSettings, Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QAbstractButton, QDialog
    from .build_identity import load_build_identity
    from .theme_manager import theme_key, apply_theme
    from .ui_theme import DEFAULT_THEME_KEY, theme_definition

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pixel_source': 'grab of visible native Qt window in the actual application process'}
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(80)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})
            if not value:
                raise AssertionError(name)

        def tick(self):
            if time.monotonic() < self.wait_until:
                return
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def brand(self, phase):
            b, cn = window.brand, window.header_subtitle
            self.check(phase + ': full brand visible', b.isVisible() and cn.isVisible() and window.header_mascot.isVisible())
            self.check(phase + ': Chinese name', cn.text() == '兔白字幕')
            self.check(phase + ': heavy readable type', cn.font().pixelSize() == 27 and cn.font().weight() >= 800)
            self.check(phase + ': title', '兔白字幕' in window.windowTitle())
            self.check(phase + ': no divider', not any(f.frameShape() == QFrame.Shape.VLine for f in window.header_content.findChildren(QFrame)))
            gap = cn.x() - b.geometry().right() - 1
            self.check(phase + ': adjacent names', 8 <= gap <= 16, gap)
            self.check(phase + ': Chinese fits', cn.width() >= cn.fontMetrics().horizontalAdvance(cn.text()))
            self.check(phase + ': aligned centers', abs(cn.geometry().center().y()-b.geometry().center().y()) <= 2)
            buttons = [window.update_button, window.subtitle_studio_button, window.model_workshop_button,
                       window.app_settings_button, window.language_combo]
            for button in buttons:
                if button.isVisible():
                    self.check(phase + ': navigation fits ' + button.objectName(),
                               button.x() > cn.geometry().right() and button.geometry().right() < window.header_content.width())
            visible_text = [w.text() for w in window.findChildren(QLabel) if w.isVisible()]
            visible_text += [w.text() for w in window.findChildren(QAbstractButton) if w.isVisible()]
            self.check(phase + ': no old visible brand', all('优兔泊' not in t and '智能游戏字幕工作台' not in t for t in visible_text))

        def run(self):
            app = QApplication.instance()
            expected = os.environ.get('TWOBYTEASR_BRAND_EXPECT_THEME', 'grape')
            window.showNormal()
            window.resize(1440, 900)
            yield .6
            self.check('stored choice or empty default', theme_key() == expected, theme_key())
            self.check('actual palette matches preference', app.palette().color(QPalette.ColorRole.Window).name() == theme_definition(expected).app_background)
            self.check('factory default grape', DEFAULT_THEME_KEY == 'grape')
            self.brand('initial')
            window.settings_scroll.verticalScrollBar().setValue(0)
            yield .3
            window.grab().save(str(output/'desktop-brand.png'))
            # All fixtures live under the guarded QA root, never the user's library.
            from .studio_project_flow import studio_settings_path
            from PySide6.QtGui import QImage, QColor
            settings_path = studio_settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            records = []
            for name, color in [('封面 A', '#4ba8b8'), ('封面 B', '#cb8355')]:
                folder = output / name
                (folder/'preview').mkdir(parents=True)
                project = folder / (name + '.2byteproj')
                project.write_text('{}', 'utf-8')
                image = QImage(640, 360, QImage.Format.Format_RGB32)
                image.fill(QColor(color))
                image.save(str(folder/'preview'/'custom.png'))
                records.append({'path': str(project), 'name': name, 'cover_path': 'preview/custom.png'})
            def recent(items):
                settings_path.write_text(json.dumps({'recent_projects': items}, ensure_ascii=False), 'utf-8')
            recent(records)
            yield 1.8
            card = window.studio_entry_card
            self.check('Home resolves recent relative cover', card._cover.pixelColor(10, 10).name() == '#4ba8b8',
                       {'key': card._cover_key, 'pixel': card._cover.pixelColor(10,10).name(), 'visible': card.isVisible(), 'timer': card._refresh_timer.isActive(), 'label': window.studio_entry_recent.text()})
            card.grab().save(str(output/'home-cover-a.png'))
            recent(list(reversed(records)))
            yield 1.8
            self.check('Home follows newest project without restart', window.studio_entry_recent.text() == '最近：封面 B' and card._cover.pixelColor(10, 10).name() == '#cb8355')
            canonical = output/'封面 B'/'preview'/'project-cover.jpg'
            image.fill(QColor('#77a75a')); image.save(str(canonical))
            yield 1.8
            self.check('Home picks asynchronously generated canonical thumbnail', card._cover_key[0] == str(canonical))
            key = card._cover_key
            image.fill(QColor('#755aaa')); image.save(str(canonical))
            yield 1.8
            self.check('Same-path thumbnail replacement invalidates cache', card._cover_key != key and abs(card._cover.pixelColor(10, 10).blue()-170) < 4)
            card.grab().save(str(output/'home-cover-b-updated.png'))
            recent([{'path': str(output/'missing.2byteproj')}, records[0]])
            yield 1.8
            self.check('Moved recent project falls back to latest available', window.studio_entry_recent.text() == '最近：封面 A')
            recent([])
            yield 1.8
            self.check('Empty library clears stale thumbnail', card._cover.isNull() and window.studio_entry_recent.text() == '最近：暂无工程')
            for theme in ('warm', 'grape'):
                apply_theme(theme, app)
                yield .5
                self.brand(theme)
            for language in ('en', 'ja', 'zh'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                yield .4
                self.brand(language)
            window.resize(950, 720)
            yield .5
            self.brand('narrow')
            window.grab().save(str(output/'desktop-narrow.png'))
            window.language_combo.setCurrentIndex(window.language_combo.findData('en'))
            yield .3
            self.brand('narrow language switch')
            self.check('compact actions remain icons after translation', not window.subtitle_studio_button.text())
            window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))
            window.resize(1440, 900)
            yield .4

            def inspect_settings():
                try:
                    dialog = next(w for w in app.allWidgets() if w.isVisible() and hasattr(w, 'theme_combo'))
                    dialog.navigation.setCurrentRow(2)
                    self.check('appearance selector agrees with palette', dialog.theme_combo.currentData() == 'grape')
                    self.check('appearance name says deep grape', '深葡萄紫' in dialog.theme_combo.currentText())
                    dialog.grab().save(str(output/'appearance.png'))
                    QDialog.done(dialog, QDialog.DialogCode.Rejected)
                except Exception:
                    self.result['error'] = traceback.format_exc()
                    for d in app.topLevelWidgets():
                        if isinstance(d, QDialog):
                            QDialog.done(d, QDialog.DialogCode.Rejected)
            QTimer.singleShot(600, inspect_settings)
            QTest.mouseClick(window.app_settings_button, Qt.MouseButton.LeftButton)
            yield .3
            self.check('settings dialog actually inspected', any(c['name'] == 'appearance selector agrees with palette' for c in self.result['checks']))
            QTest.mouseClick(window.subtitle_studio_button, Qt.MouseButton.LeftButton)
            yield 2
            self.check('Studio page entered', window.pages.currentWidget() is window.studio_page)
            self.check('Hidden Home stops thumbnail polling', not card._refresh_timer.isActive())
            # Studio has its own chrome; the home header is intentionally hidden.
            self.check('Studio uses same name', window.studio_page.filename.text() == '兔白字幕')
            self.check('Studio window title retains name', '兔白字幕' in window.windowTitle())
            window.grab().save(str(output/'studio-entry.png'))
            window._return_to_settings()
            yield .5
            self.brand('return home')
            self.check('Returning Home resumes thumbnail polling', card._refresh_timer.isActive())

        def finish(self):
            self.timer.stop()
            self.result['passed'] = 'error' not in self.result
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            window.result_exit_code = 0 if self.result['passed'] else 1
            QTimer.singleShot(100, window.close)

    window._product_brand_audit = Audit()
