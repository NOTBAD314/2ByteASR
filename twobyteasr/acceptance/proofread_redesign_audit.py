"""Real-window check: AI 词库校对 redesign A (2026-10-23).

User (10-23): redesign the page (picked version A on the canvas), add
viewing captions by speaker so narration can be screened out, and join the
search and the batch replace (replacing needed Ctrl+H first).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=proofread-redesign``
(isolated data, from ``scripts/verify_proofread_redesign_headed.py``; source
or frozen). The scenario writes its own library 「原神」 and a 16-caption
project with three speakers (主播 / 旁白 / 队友) into the isolated folder,
opens the page the way the result page does, and in the runner's theme and
in 「grape」 checks the layout, hides 旁白, searches and replaces, and grabs
the window at each step (also narrow, and in other interface languages).
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

CUES = [("c12", 36600, 39000, "有一个倒计时", "S01"), ("c13", 39000, 42300, "三十天", "S01"),
        ("c14", 42300, 49000, "哎 真像那个格式化都被数据清除了", "S01"), ("c15", 49000, 52000, "风丹的水下藏着古老的秘密", "S02"),
        ("c16", 52100, 55000, "这个风丹的剧情还挺长的", "S01"), ("c17", 55000, 58400, "快快快 那边有宝箱", "S03"),
        ("c18", 58400, 61000, "我我我们先去找芙宁那吧", "S01"), ("c19", 61000, 64000, "欢迎来到风丹廷", "S02"),
        ("c20", 64000, 68000, "旅行者 你终于来了", "S02"), ("c21", 68800, 72000, "那维来特说的那个预言是真的吗", "S01"),
        ("c22", 72300, 75000, "欧庇克莱那边是不是监狱啊", "S01"), ("c23", 75000, 78400, "好 我们先去歌剧院", "S01"),
        ("c24", 78400, 82900, "风丹廷晚上好漂亮啊", "S01"), ("c25", 82900, 86100, "去风丹的路上有个宝箱", "S03"),
        ("c26", 86100, 89800, "六十个原石 还行吧", "S01"), ("c27", 89800, 93000, "所以风丹人是不是都不能哭", "S01")]
SPEAKERS = [("S01", "主播"), ("S02", "旁白"), ("S03", "队友")]
TERMS = [("风丹", "枫丹", "地点"), ("芙宁那", "芙宁娜", "角色"), ("那维来特", "那维莱特", "角色"),
         ("歌剧院", "歌剧院", "地点"), ("原石", "原石", "物品")]


def _project(output: Path) -> Path:
    import subtitle_core as legacy
    from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    for source, target, category in TERMS:
        legacy.add_learned_mapping("原神", target, target, category=category, origin="手动")
        if source != target:
            legacy.add_learned_mapping("原神", source, target, category=category, origin="手动")
    library = next(str(row["id"]) for row in legacy.glossary_catalog() if row["name"] == "原神")
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=95000),
                              cues=[StudioCue(cue_id, a, b, text, speaker_id=speaker) for cue_id, a, b, text, speaker in CUES],
                              speakers=[StudioSpeaker(identity, name) for identity, name in SPEAKERS])
    project.glossary_ids = [library]
    path = output / "projects" / "10月23日" / "10月23日.2byteproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    return save_project(project, path)


def start(window, output: Path):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], skipped=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(__import__('sys').executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait(test, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            settle(50)
            if test():
                return True
        return False

    def grab(name):
        try:
            window.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def click(widget, point=None):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         point if point is not None else widget.rect().center())
        settle(250)

    def listed(page):
        return [page._rows[index]["cue_id"] for index in page.list.visible]

    def layout(page, tag):
        """Narrower side column, nothing clipped, one-line captions, buttons fit."""
        side = page.left_panel
        body = side.findChild(QWidget, "proofreadLeftBody")
        viewport = body.parentWidget()
        cards = [w for w in body.findChildren(QWidget, "proofreadCard") if w.isVisible()]
        clipped = {card.findChild(QWidget).objectName() if card.findChild(QWidget) else 'card':
                   [card.minimumSizeHint().width(), viewport.width()] for card in cards
                   if card.minimumSizeHint().width() > viewport.width()}
        check(f'{tag}: the side column is at most 30% of the page and nothing in it is cut off',
              side.width() <= page.width() * 0.30 + 1 and not clipped, dict(side=side.width(), page=page.width(),
                                                                            clipped=clipped))
        plain = next((slot for slot, index in enumerate(page.list.visible)
                      if page._rows[index]["cue_id"] == "c13"), None)
        lst = page.list
        check(f'{tag}: a plain caption is one line high (number · time · play · speaker beside it)',
              plain is not None and lst.heights[plain] - lst._gap_before(plain) - lst._gap_after(plain)
              == lst.PAD + lst.LINE + lst.PAD, dict(slot=plain, height=lst.heights[plain] if plain is not None else None,
                                                     line=lst.LINE, pad=lst.PAD))
        short = {button.text(): [button.width(), button.sizeHint().width()]
                 for button in page.findChildren(QPushButton)
                 if button.isVisible() and button.text() and button.width() + 1 < button.sizeHint().width()}
        check(f'{tag}: no button is narrower than its text', not short, short)
        right = max((w.mapTo(page, w.rect().topRight()).x() for w in page.findChildren(QPushButton) if w.isVisible()),
                    default=0)
        check(f'{tag}: every button stays inside the page', right <= page.width(), [right, page.width()])
        libraries = page.library_list
        shown = min(4, libraries.count())
        whole = sum(libraries.sizeHintForRow(row) for row in range(shown)) + 2 * libraries.frameWidth()
        check(f'{tag}: the library list shows whole rows only (no half-cut row)', libraries.height() == whole,
              dict(height=libraries.height(), whole=whole, rows=shown, count=libraries.count()))
        summary = page.library_summary
        caption = summary.parentWidget().findChild(QWidget, "proofreadCaption")
        middle = lambda w: w.mapTo(page, w.rect().center()).y()
        check(f'{tag}: the library count sits on the 词库 title line', summary.isVisible() and caption is not None
              and abs(middle(summary) - middle(caption)) <= 4 and not page.library_note.isVisible(),
              dict(summary=summary.text(), note=page.library_note.text()))
        rows = [w for w in page.speaker_card.findChildren(QWidget, "proofreadSpeakerRow") if w.isVisible()]
        check(f'{tag}: one speaker row per speaker (none left over from an earlier opening)',
              len(rows) == len(page._speakers()), [len(rows), len(page._speakers())])
        result['metrics'][tag] = dict(window=[window.width(), window.height()], side=side.width(), page=page.width(),
                                      list=[lst.width(), lst.height()], visible=len(lst.visible),
                                      heights=lst.heights[:12])

    def flow(theme, page):
        page._reveal_speakers(None)   # the choice is kept per project; start from everyone shown
        page.filter_buttons["all"].click()
        settle(300)
        check(f'{theme}: the bar is there with 替换为 beside 查找', page.replace_bar.isVisible()
              and page.replace_input.isVisible() and page.search.isVisible()
              and page.replace_input.mapTo(page, page.replace_input.rect().topLeft()).y()
              == page.search.mapTo(page, page.search.rect().topLeft()).y())
        speakers = [(key, name, count) for key, name, _color, count in page._speakers()]
        check(f'{theme}: the speaker card lists 主播 / 旁白 / 队友 with their captions',
              page.speaker_card.isVisible() and speakers == [("S01", "主播", 11), ("S02", "旁白", 3), ("S03", "队友", 2)],
              speakers)
        layout(page, f'{theme}_open')
        grab(f'{theme}_01_open')
        # Hide narration with its eye.
        click(page._speaker_widgets["S02"]["eye"])
        check(f'{theme}: the eye hides 旁白 (list, counts, badge, note)',
              "c15" not in listed(page) and len(listed(page)) == 13 and page.speaker_badge.isVisible()
              and page.filter_buttons["all"].text().endswith("13 条") and page.hidden_note.isVisible(),
              dict(listed=listed(page), all=page.filter_buttons["all"].text(), note=page.hidden_note.text()))
        page.list.current = "c16"
        page.list.ensure_visible("c16")
        settle(300)
        page.list.repaint()
        bands = [rect for rect, action, _cue, _key in page.list._hit_boxes if action == "reveal"]
        check(f'{theme}: hidden captions leave a band with 显示', bool(bands) and page.list.gaps,
              dict(gaps=page.list.gaps))
        layout(page, f'{theme}_hidden')
        grab(f'{theme}_02_hidden')
        # Search and replace in one bar, without Ctrl+H.
        page.search.insert("风丹")
        settle(500)
        hits = len(page._hits)
        check(f'{theme}: searching lists the hits of the shown speakers', hits == 4 and page.hit_label.text() == "4 处",
              dict(hits=hits, label=page.hit_label.text()))
        QTest.keyClick(page.search, Qt.Key.Key_Return)
        settle(200)
        check(f'{theme}: Enter in 查找 frames the first hit', page.hit_label.text() == "第 1 / 4 处",
              page.hit_label.text())
        page.replace_input.insert("枫丹")
        settle(500)
        text = page.replace_count.text()
        check(f'{theme}: typing 替换为 shows the plan, names the hidden narration and enables both buttons',
              "将替换 4 处" in text and "隐藏的说话人里 2 处不改" in text and page.replace_one.isEnabled()
              and page.replace_go.isEnabled() and page.replace_go.text() == "全部替换 4 处", text)
        page.list.repaint()
        previews = [rect for rect, action, _cue, _start in page.list._hit_boxes if action == "find"]
        check(f'{theme}: each hit shows 枫丹 under it and can be clicked to exclude', bool(previews))
        grab(f'{theme}_03_find')
        steps = page._stack.index() if page._stack is not None else 0
        click(page.replace_one)
        check(f'{theme}: 替换 replaces only the framed hit and frames the next',
              page._by_id["c16"]["base"] == "这个枫丹的剧情还挺长的" and page.hit_label.text() == "第 1 / 3 处"
              and page._stack.index() == steps + 1, dict(text=page._by_id["c16"]["base"], label=page.hit_label.text()))
        grab(f'{theme}_04_replaced_one')
        page._undo()
        settle(300)
        check(f'{theme}: one undo brings it back', page._by_id["c16"]["base"] == "这个风丹的剧情还挺长的")
        QTest.keyClick(page.replace_input, Qt.Key.Key_Escape)
        settle(200)
        check(f'{theme}: Esc in 替换为 goes back to a plain search', page.replace_input.text() == ""
              and page.replace_bar.isVisible() and page.list.find.get("replace") is None)
        page.search.clear()
        settle(400)
        # The band's 显示 brings narration back.
        page.list.repaint()
        bands = [rect for rect, action, _cue, _key in page.list._hit_boxes if action == "reveal"]
        if bands:
            click(page.list, bands[0].center().toPoint())
        check(f'{theme}: the band\'s 显示 shows 旁白 again', not page._hidden_speakers and "c15" in listed(page),
              sorted(page._hidden_speakers))
        click(page._speaker_widgets["S02"]["eye"])   # hidden again for the next pictures

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            from ..projects.studio_project import load_project
            theme = os.environ.get('TWOBYTEASR_PROOFREAD_THEME', 'sand')
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            size = [int(v) for v in os.environ.get('TWOBYTEASR_PROOFREAD_SIZE', '1600x900').split('x')]
            window.resize(*size)
            path = _project(output)
            settle(800)
            for index, name in enumerate(dict.fromkeys([theme, 'grape'])):
                apply_theme(name, app)
                settle(800)
                window._show_glossary_proofread(str(path), load_project(path))
                page = window.glossary_proofread_page
                check(f'{name}: the page opens and matches locally', wait(lambda: not page.checks_running(), 60)
                      and page.list.isVisible(), page.status_label.text())
                settle(800)
                if index == 0:
                    suggested = [row["cue_id"] for row in page._rows if page._groups(row)]
                    check('the library 「原神」 proposes 风丹 / 芙宁那 / 那维来特', {"c16", "c18", "c21"} <= set(suggested),
                          suggested)
                flow(name, page)
                settle(400)
                grab(f'{name}_05_hidden_review')
                window.resize(1366, 760)
                settle(1200)
                layout(page, f'{name}_compact')
                grab(f'{name}_06_compact')
                window.resize(*size)
                settle(800)
                # Back to the result page, as the user would; reopened for the next theme.
                page._back()
                settle(600)
            # Other interface languages: longer button words.
            page = window.glossary_proofread_page
            for code in [c for c in os.environ.get('TWOBYTEASR_PROOFREAD_LANGS', '').split(',') if c]:
                index = window.language_combo.findData(code)
                if index < 0:
                    result['skipped'].append(f'language {code}')
                    continue
                window.language_combo.setCurrentIndex(index)
                settle(2500)
                window._show_glossary_proofread(str(path), load_project(path))
                wait(lambda: not page.checks_running(), 60)
                settle(800)
                layout(page, f'{code}')
                grab(f'{code}_07_open')
                window.resize(1366, 760)
                settle(1200)
                layout(page, f'{code}_compact')
                grab(f'{code}_08_compact')
                window.resize(*size)
                settle(800)
                page._back()
                settle(600)
            if os.environ.get('TWOBYTEASR_PROOFREAD_LANGS'):
                window.language_combo.setCurrentIndex(max(0, window.language_combo.findData('zh')))
                settle(1500)
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
