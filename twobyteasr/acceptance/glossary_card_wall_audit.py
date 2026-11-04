"""Frozen normal-window acceptance for the user-selected grouped term cards."""
from pathlib import Path
import json,os,traceback

def start(window, output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    out=Path(output);win=window;legacy=window.legacy;app=QApplication.instance()
    GAME="卡片界面验收";themes=("grape","plum","warm");width=1440
    result=dict(passed=False,checks=[],pid=os.getpid(),identity=load_build_identity().to_dict())
    def write():
        (out/"card-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),"utf8")
    def check(name,ok,detail=""):
        result["checks"].append(dict(name=name,passed=bool(ok),detail=str(detail)))
        if not ok:raise AssertionError(name+": "+str(detail))
    def run():
        try:
            win.resize(1440,900)
            rows = [("倾泻", "倾泻", "技能"), ("倾斜", "倾泻", "技能"), ("清线", "倾泻", "技能"), ("光合", "光合", "技能"),
                    ("光金", "光合", "技能"), ("冰点", "冰点", "技能"), ("兵点", "冰点", "技能"), ("迪莫", "迪莫", "角色"),
                    ("低魔", "迪莫", "角色"), ("火花", "火花", "角色"), ("水蓝蓝", "水蓝蓝", "角色"), ("喵喵", "喵喵", "角色"),
                    ("圣羽翼王", "圣羽翼王", "Boss"), ("圣雨翼王", "圣羽翼王", "Boss"), ("冰龙王", "冰龙王", "Boss"),
                    ("魔法学院", "魔法学院", "地点"), ("星辰岛", "星辰岛", "地点"), ("洛克贝", "洛克贝", "物品"),
                    ("仪式镐", "仪式镐", "物品"), ("光合球", "光合球", "物品"), ("克劳德", "克劳德", "人物"),
                    ("拉布朗", "拉布朗", "人物"), ("努力值", "努力值", "其他"), ("暗影系", "暗影系", "其他"),
                    ("恶魔叮", "恶魔叮", "角色"), ("雪影娃娃", "雪影娃娃", "角色"), ("治愈之光", "治愈之光", "技能"),
                    ("种子炸弹", "种子炸弹", "技能"), ("寒冰护盾", "寒冰护盾", "技能"), ("寒兵护盾", "寒冰护盾", "技能")]

            win._manage_terms()
            app.processEvents()
            page = win._term_library_dialog
            page.sidebar_new_button.click()
            page.game_input.setText(GAME)
            page.add_game_button.click()
            app.processEvents()
            key = page._library_key()
            for source, target, category in rows:
                legacy.add_learned_mapping(key, source, target, category=category, origin="手动")
            for name in ("绝区零", "原神", "鸣潮", "明日方舟：终末地"):
                page.sidebar_new_button.click()
                page.game_input.setText(name)
                page.add_game_button.click()
                app.processEvents()
            item = next(page.game_list.item(i) for i in range(page.game_list.count())
                        if page.game_list.item(i).data(Qt.ItemDataRole.UserRole) == GAME)
            page.game_list.setCurrentItem(item)
            page._notify_library_changed()
            page.refresh_current_game()
            app.processEvents()
            QTest.qWait(300)

            for theme in themes:
                apply_theme(theme)
                app.processEvents()
                QTest.qWait(250)
                win.grab().save(str(out / f"page-{theme}-{width}.png"))
            check("cards_shown", page._term_model.rowCount() >= 20, page._term_model.rowCount())
            check("columns_at_width", page.listing.columns() >= 4, page.listing.columns())
            check("guide_visible_first_time", page.term_guide.isVisible())

            # click the second card: in-place edit box over the card
            index = page._term_model.index(1, 0)
            rect = page.listing.visualRect(index)
            QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
            app.processEvents()
            QTest.qWait(200)
            sheet = getattr(page, "_edit_sheet", None)
            card_top_left = page.listing.viewport().mapTo(page, rect.topLeft())
            check("edit_sheet_opens", sheet is not None and sheet.isVisible())
            if sheet is not None:
                check("edit_sheet_on_card", abs(sheet.y() - card_top_left.y()) <= 4 or sheet.geometry().contains(card_top_left),
                      (sheet.geometry().getRect(), card_top_left.toTuple()))
                win.grab().save(str(out / f"edit-{themes[-1]}.png"))
                QTest.keyClick(page.edit_canonical, Qt.Key.Key_Escape)
                app.processEvents()
                QTest.qWait(100)
                check("escape_closes", getattr(page, "_edit_sheet", None) is None)

            # ctrl-click two cards: the selection bar
            for row in (2, 5):
                r = page.listing.visualRect(page._term_model.index(row, 0))
                QTest.mouseClick(page.listing.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, r.center())
            app.processEvents()
            check("ctrl_click_selects", page.selection_bar.isVisible() and "2" in page.selection_label.text(), page.selection_label.text())
            win.grab().save(str(out / f"select-{themes[-1]}.png"))
            page.clear_selection.click()

            # status segment
            page.status_buttons["confirmed"].click()
            app.processEvents()
            check("segment_drives_filter", page.filter_status.currentData() == "confirmed")
            grouped=[page._term_model.data_for_row(i) for i in range(page._term_model.rowCount())
                     if page._term_model.data_for_row(i).get('target')=='倾泻']
            check('one_card_for_three_mappings',len(grouped)==1 and len(grouped[0].get('members',[]))==3)
            page.status_buttons[""].click()
            app.processEvents()

            # guide dismiss is remembered
            page.term_guide_close.click()
            page.refresh_current_game()
            check("guide_dismissed", not page.term_guide.isVisible())

            # try panel
            page.term_try_toggle.click()
            page.term_try_input.setText("这波兵点接倾斜")
            page.try_sentence()
            app.processEvents()
            win.grab().save(str(out / f"try-{themes[-1]}.png"))
            check("try_panel_visible", page.term_try_panel.isVisible())

            page.status_buttons['confirmed'].click()
            app.processEvents()
            row=next(i for i in range(page._term_model.rowCount()) if page._term_model.data_for_row(i).get('target')=='倾泻')
            index=page._term_model.index(row,0)
            page.listing.scrollTo(index);app.processEvents()
            QTest.mouseClick(page.listing.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,page.listing.visualRect(index).center())
            app.processEvents()
            check('grouped_edit_lists_all_aliases',set(page.edit_alias.text().split('、'))=={'倾斜','清线'})
            page.edit_alias.setText('倾斜、清线、青谢')
            QTest.mouseClick(page.edit_save_button,Qt.MouseButton.LeftButton)
            app.processEvents()
            stored=legacy.learned_mappings_for_game(key)
            check('grouped_edit_saved_all_aliases',{'倾泻','倾斜','清线','青谢'}=={r['from'] for r in stored if r['to']=='倾泻'})
            check('grouped_edit_preserved_category',all(r['category']=='技能' for r in stored if r['to']=='倾泻'))
            win.grab().save(str(out/'grouped-edited.png'))


            from . import blank_project_audit
            check("zero_provider_calls",blank_project_audit._provider_calls==0)
            result["passed"]=True
        except Exception:
            result["error"]=traceback.format_exc()
            win.grab().save(str(out/"card-failure.png"))
        window.result_exit_code=0 if result["passed"] else 1
        write()
        def stopped():
            result["gui_shutdown"]=True
            write()
        app.aboutToQuit.connect(stopped)
        win.close()
    QTimer.singleShot(900,run)
