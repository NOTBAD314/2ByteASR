"""Opt-in real-window check: the three-step glossary submit sheet (2026-10-18).

Scenario ``glossary-submit`` (driver: scripts/verify_glossary_submit_headed.py, which
seeds example libraries into the isolated user data and writes their keys to
``seed.json``).  The hub catalog is a local fake, "只导出文件" writes into the
output folder and opening a web page is recorded instead of done, so nothing
leaves the computer.

* 线上词库 → 投稿我的词库 opens step 1: every personal library, the open one
  ticked, one without confirmed words disabled, a hub-installed one says so;
* step 2: one notice line per kind of finding (no line per rule), the
  conflicting rules start unticked, unconfirmed rows are not listed,
  「只看这几条」 filters the list;
* step 3 needs CC0; the exported file leaves out an unticked rule, the
  conflicting rules and every private field; no page is opened;
* the share button beside a library's title goes straight to step 2;
  the sheet still fits a small window.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QLabel
    from ..diagnostics.build_identity import load_build_identity
    from ..glossary import glossary_hub as hub
    from ..glossary import glossary_hub_ui as hub_ui

    app = QApplication.instance()
    output = Path(output)
    theme = os.environ.get('TWOBYTEASR_GLOSSARY_AUDIT_THEME', 'grape')
    seed = json.loads((output / 'seed.json').read_text('utf8'))
    keys, expected = seed['keys'], seed['expected']
    opened = []
    entry = {'id': 'genshin', 'game': '原神', 'title': '原神（至冬 7.x）', 'version': 1, 'rows': 3,
             'path': 'libraries/genshin.json', 'sha256': '0' * 64, 'size': 100, 'updated': '2026-10-17',
             'note': '示例目录：本次检查用的假目录'}
    catalog = hub.Catalog({'schema': 1, 'serial': 1, 'libraries': [entry]}, 'GitCode', time.time())
    hub.fetch_catalog = lambda **_kwargs: catalog
    hub_ui.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()))
    hub_ui._downloads_folder = lambda: output / 'Downloads'
    hub_ui._reveal = lambda _path: None

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'screenshots': [], 'theme': theme}
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})

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

        def shot(self, widget, name):
            QApplication.processEvents()
            path = output / f'{name}.png'
            widget.grab().save(str(path))
            self.result['screenshots'].append(str(path))

        def run(self):
            yield 1.0
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            window.showNormal()
            window.resize(1500, 950)
            window._manage_terms()
            yield 2.5
            library = window.term_library_page.library
            for index in range(library.game_list.count()):
                item = library.game_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole + 1) == keys['rock']:
                    library.game_list.setCurrentItem(item)
            yield .8
            self.check('current library is the example one', library.state.get('library_id') == keys['rock'],
                       library.state.get('game'))
            library.hub_button.click()
            yield 1.5
            self.shot(window, '0-hub-page')
            library.hub_panel.submit_button.click()
            yield .9
            sheet = library._hub_submit
            choices = {choice.library.key: choice for choice in sheet.library_choices}
            self.check('starts at step 1', sheet.step == 0)
            self.check('lists the example libraries', set(keys.values()) <= set(choices), list(choices))
            self.check('open library preselected', choices[keys['rock']].radio.isChecked())
            self.check('empty library disabled', not choices[keys['empty']].radio.isEnabled())
            hub_meta = [label.text() for label in choices[keys['genshin']].findChildren(QLabel)]
            self.check('hub-installed library says so', any('原神（至冬 7.x）' in text for text in hub_meta), hub_meta)
            self.shot(window, '1-choose')
            self.shot(sheet.sheet.frame, '1-choose-sheet')
            sheet.choose_next.click()
            yield .8
            codes = [group.code for group in sheet.groups]
            self.check('step 2 shown', sheet.step == 1)
            self.check('one notice line per kind', len(sheet.notices) == len(sheet.groups)
                       and codes.count('short_cjk') == 1, codes)
            short = next((group for group in sheet.groups if group.code == 'short_cjk'), None)
            self.check('short rules counted once', short is not None and short.count == expected['short'],
                       short.count if short else None)
            self.check('conflicting rules start unticked',
                       any(item.blocked for item in sheet.rows)
                       and all(not item.ticked for item in sheet.rows if item.blocked))
            self.check('unconfirmed row not listed', all(item.row['from'] != '候选词' for item in sheet.rows))
            self.check('rows listed', len(sheet.rows) == expected['rows'], len(sheet.rows))
            self.check('review next enabled', sheet.review_next.isEnabled())
            self.shot(window, '2-review')
            self.shot(sheet.sheet.frame, '2-review-sheet')
            _group, show, _bulk = next(notice for notice in sheet.notices if notice[0].code == 'short_cjk')
            show.click()
            yield .4
            visible = sum(1 for index in range(len(sheet.rows)) if not sheet.table.isRowHidden(index))
            self.check('只看这几条 filters the list', visible == expected['short'], visible)
            self.shot(sheet.sheet.frame, '2b-review-only-short')
            sheet.chips['all'].click()
            left_out = next(item for item in sheet.rows if item.pair == tuple(expected['left_out']))
            left_out.check.setCheckState(Qt.CheckState.Unchecked)
            yield .4
            sheet.review_next.click()
            yield .4
            self.check('step 3 shown', sheet.step == 2)
            self.check('send needs consent', not sheet.export_button.isEnabled())
            sheet.author.setText('示例署名')
            sheet.note.setPlainText('示例说明：本次检查用的示例词库')
            sheet.consent.setChecked(True)
            self.check('send enabled after consent', sheet.export_button.isEnabled())
            self.shot(window, '3-sign')
            self.shot(sheet.sheet.frame, '3-sign-sheet')
            sheet.export_button.click()
            yield .6
            files = list((output / 'Downloads').glob('2byteasr-glossary-*.json'))
            self.check('exported one file', len(files) == 1, [str(path) for path in files])
            if files:
                text = files[0].read_text('utf8')
                pairs = {(row['from'], row['to']) for row in json.loads(text)['mappings']}
                self.check('unticked rule stayed home', tuple(expected['left_out']) not in pairs)
                self.check('conflicting rules stayed home', not any(pair[0] == expected['conflict_from'] for pair in pairs))
                self.check('exported count', len(pairs) == expected['rows'] - 3, len(pairs))
                self.check('private fields stay home', '私人备注' not in text)
            self.check('no page opened', opened == [], opened)
            library.show_page('mine')
            yield .6
            library.share_button.click()
            yield .7
            sheet = library._hub_submit
            self.check('share button opens the review', sheet.step == 1 and sheet.library.key == keys['rock'])
            self.shot(window, '4-from-library')
            window.resize(1120, 740)
            yield .7
            self.shot(window, '5-small-window')
            frame = sheet.sheet.frame
            self.check('sheet fits the small window', frame.geometry().bottom() <= library.height(),
                       [frame.geometry().getRect(), library.height()])
            sheet.sheet.close()
            yield .3

        def finish(self):
            self.timer.stop()
            checks = self.result['checks']
            self.result['passed'] = bool(checks) and all(c['passed'] for c in checks) and 'error' not in self.result
            self.result['opened_urls'] = opened
            path = output / 'result.json'
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            def shutdown_done():
                self.result['gui_shutdown'] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            app.aboutToQuit.connect(shutdown_done)
            window.showNormal()
            window.close()

    window._glossary_submit_audit = Audit()
