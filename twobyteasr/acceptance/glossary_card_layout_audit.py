"""Opt-in normal Windows window checks for the six-by-four term grid."""
from pathlib import Path
import json
import os
import traceback


def start(window, output):
    from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolTip
    from ..design.theme_manager import apply_theme
    from ..glossary.glossary_term_cards import card_parts
    from . import blank_project_audit

    out = Path(output)
    app = QApplication.instance()
    legacy = window.legacy
    result = dict(passed=False, checks=[], layouts=[], pid=os.getpid(),
                  dpr=window.devicePixelRatioF(), platform=app.platformName(),
                  scope="normal MainWindow, synthetic isolated library, Qt input and actual QWidget screenshots")

    def check(name, value, detail=None):
        result["checks"].append(dict(name=name, passed=bool(value), detail=detail))
        if not value:
            raise AssertionError(f"{name}: {detail}")

    def save():
        (out / "layout-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")

    def settle():
        app.processEvents()
        QTest.qWait(120)

    def run():
        try:
            window.resize(1440, 960)
            apply_theme("grape")
            window._manage_terms()
            settle()
            page = window._term_library_dialog
            page.sidebar_new_button.click()
            page.game_input.setText("词卡布局验收")
            page.add_game_button.click()
            settle()
            key = page._library_key()
            words = "仪式镐 倾泻 光合 光合治愈 光合球 冰点 分光水晶 力增 力量增效 卡洛西亚 卡瓦重 蓄势 可可牛牧节 可可果球 吓退 听析 命定花种 咕噜球 咕波螺 噩梦枷锁 圣凯布米龙 地刺 地武队 夜枭 失重漂浮 失重球 奇异血脉 威廉古堡 小浣蛋 尤里克 巨人裂谷 布灵 布灵布灵 幸运惊喜盒 幽铃 异色 彩虹独角兽 影袭 愿不到 愿力 愿力冲击 折射 抽枝 持续高温 挂速冻 摇铃魔偶 新月狼灵 新月鹭 星光对决 星星眼 星陨流光 智辉章脑 暗夜拾光 暗夜领主".split()
            categories = ("地点", "游戏术语", "其他", "技能", "物品", "角色")
            mistakes = {"倾泻": ["倾斜", "清线"], "冰点": ["兵点"], "力增": ["力争", "力针", "历增"],
                        "卡瓦重": ["他二重"], "蓄势": ["盛式", "蝶式"], "地武队": ["地五队", "地无队", "地舞队"],
                        "吓退": ["下推", "下退"], "夜枭": ["夜宵"]}
            long_word = "巨人裂谷深处的超长术语名称与完整技能说明示例"
            words.insert(8, long_word)
            mistakes[long_word] = [f"完整误识别词{i}" for i in range(1, 13)]
            words.extend(f"验收词条{i:02d}" for i in range(1, 37))
            for position, word in enumerate(words):
                category = categories[position % len(categories)]
                legacy.add_learned_mapping(key, word, word, category=category, origin="手动")
                for heard in mistakes.get(word, []):
                    legacy.add_learned_mapping(key, heard, word, category=category, origin="手动")
            for name in ("绝区零", "原神", "明日方舟", "瓦罗兰特", "鸣潮"):
                page.sidebar_new_button.click()
                page.game_input.setText(name)
                page.add_game_button.click()
            item = next(page.game_list.item(i) for i in range(page.game_list.count())
                        if page.game_list.item(i).data(Qt.ItemDataRole.UserRole) == "词卡布局验收")
            page.game_list.setCurrentItem(item)
            page._notify_library_changed()
            page.refresh_current_game()
            settle()
            view = page.listing

            def index_for(word):
                return next(page._term_model.index(i, 0) for i in range(page._term_model.rowCount())
                            if page._term_model.data_for_row(i)["target"] == word)

            for width, height in ((1440, 960), (1280, 900), (1920, 1080), (1440, 960)):
                window.resize(width, height)
                view.verticalScrollBar().setValue(0)
                settle()
                rects = [view.visualRect(page._term_model.index(i, 0)) for i in range(25)]
                metrics = view.card_delegate.metrics(rects[0])
                detail = dict(requested=[width, height], window=list(window.size().toTuple()),
                              viewport=list(view.viewport().size().toTuple()), grid=list(view.gridSize().toTuple()),
                              card=list(rects[0].size().toTuple()), columns=view.columns(),
                              word_font_px=metrics.px(15), category_font_px=metrics.px(11),
                              detail_font_px=metrics.px(12), status_size=metrics.px(18),
                              right_gap=view.viewport().width() - rects[5].right(),
                              bottom_gap=view.viewport().height() - rects[23].bottom())
                result["layouts"].append(detail)
                check(f"six_columns_{width}_{height}", len({r.top() for r in rects[:6]}) == 1 and view.columns() == 6, detail)
                check(f"24_equal_cards_{width}_{height}", len({r.size().toTuple() for r in rects[:24]}) == 1
                      and all(view.viewport().visibleRegion().contains(r) for r in rects[:24]), detail)
                check(f"fills_viewport_{width}_{height}", detail["right_gap"] <= view.GAP + 6
                      and detail["bottom_gap"] <= view.GAP + 4 and rects[24].top() >= view.viewport().height() - 4, detail)
                window.grab().save(str(out / f"layout-{width}x{height}.png"))
            compact, large = result["layouts"][1:3]
            check("type_labels_status_grow_with_card", all(large[key] >= compact[key] * 1.5
                  for key in ("word_font_px", "category_font_px", "detail_font_px", "status_size")), [compact, large])
            check("no_explanatory_text_or_reference_aliases", all(not card_parts(page._term_model.data_for_row(i))["note"]
                  for i in range(page._term_model.rowCount())))
            view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
            settle()
            last = page._term_model.index(page._term_model.rowCount() - 1, 0)
            check("scroll_reaches_last_card", view.viewport().rect().contains(view.visualRect(last)))
            window.grab().save(str(out / "scroll-bottom.png"))

            page.search.setText("倾斜")
            settle()
            check("search_by_misrecognition", page._term_model.rowCount() == 1 and page._term_model.data_for_row(0)["target"] == "倾泻")
            check("filter_removes_scrollbar", not view.verticalScrollBar().isVisible())
            page.search.clear()
            page.status_buttons["confirmed"].click()
            settle()
            check("confirmed_status_filter", page.filter_status.currentData() == "confirmed" and page._term_model.rowCount() == len(words))
            page.filter_category.setCurrentIndex(page.filter_category.findData("角色"))
            settle()
            check("category_filter", page._term_model.rowCount() > 0 and all(page._term_model.data_for_row(i)["category"] == "角色"
                  for i in range(page._term_model.rowCount())))
            page.filter_category.setCurrentIndex(0)
            page.status_buttons["hidden"].click()
            settle()
            check("empty_status_filter", page._term_model.rowCount() == 0)
            page.status_buttons[""].click()
            settle()

            index = index_for("倾泻")
            view.scrollTo(index)
            settle()
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, view.visualRect(index).center())
            settle()
            check("click_opens_editor_with_all_mappings", page._edit_sheet is not None and page._edit_sheet.isVisible()
                  and set(page.edit_alias.text().split("、")) == {"倾斜", "清线"})
            window.grab().save(str(out / "click-edit.png"))
            QTest.keyClick(page.edit_canonical, Qt.Key.Key_Escape)
            settle()
            check("escape_closes_editor", page._edit_sheet is None)

            before = view.gridSize()
            for row, modifiers in ((0, Qt.KeyboardModifier.ControlModifier), (1, Qt.KeyboardModifier.ControlModifier)):
                QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifiers, view.visualRect(page._term_model.index(row, 0)).center())
            settle()
            check("ctrl_multiselect_without_reflow", len(view.selectionModel().selectedRows()) == 2 and page.selection_bar.isVisible() and view.gridSize() == before)
            page.clear_selection.click()
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, view.visualRect(page._term_model.index(0, 0)).center())
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, view.visualRect(page._term_model.index(3, 0)).center())
            settle()
            check("shift_range_selection", len(view.selectionModel().selectedRows()) >= 4)
            window.grab().save(str(out / "multiselect.png"))
            page.clear_selection.click()

            index = index_for(long_word)
            view.scrollTo(index)
            settle()
            pos = view.visualRect(index).center()
            event = QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos))
            app.sendEvent(view.viewport(), event)
            settle()
            check("hover_full_word_and_all_misrecognitions", long_word in QToolTip.text()
                  and all(heard in QToolTip.text() for heard in mistakes[long_word]))
            for widget in app.topLevelWidgets():
                if widget.isVisible() and widget.metaObject().className() == "QTipLabel":
                    widget.grab().save(str(out / "full-tooltip.png"))
            QToolTip.hideText()
            apply_theme("warm")
            view.verticalScrollBar().setValue(0)
            settle()
            window.grab().save(str(out / "layout-warm.png"))

            # Exercise the relocated painted buttons against real isolated
            # reference storage as well as the confirmed-card editing above.
            item = next(page.game_list.item(i) for i in range(page.game_list.count())
                        if page.game_list.item(i).data(Qt.ItemDataRole.UserRole) == "绝区零")
            page.game_list.setCurrentItem(item)
            page.status_buttons["reference"].click()
            settle()
            check("reference_filter_has_cards", page._term_model.rowCount() > 1)
            index = page._term_model.index(0, 0)
            row = page._term_model.data_for_row(0)
            reference_name = row["target"]
            check("reference_only_keeps_name_category_status_action", not card_parts(row)["note"]
                  and not card_parts(row)["chips"] and card_parts(row)["action"] == "收下")
            window.grab().save(str(out / "reference-cards.png"))
            button = view.card_delegate.button_rect(view.visualRect(index), index)
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button.center())
            settle()
            check("painted_keep_confirms_reference", any(r["from"] == reference_name and r["to"] == reference_name
                  for r in legacy.learned_mappings_for_game(page._library_key())))

            index = page._term_model.index(0, 0)
            hidden_name = page._term_model.data_for_row(0)["target"]
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, view.visualRect(index).center())
            page.hide_selected_references()
            page.status_buttons["hidden"].click()
            settle()
            index = index_for(hidden_name)
            check("hidden_filter_preserves_restore_action", card_parts(page._term_model.data_for_row(index.row()))["action"] == "恢复")
            window.grab().save(str(out / "hidden-cards.png"))
            button = view.card_delegate.button_rect(view.visualRect(index), index)
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button.center())
            settle()
            check("painted_restore_returns_to_reference", any(r["target"] == hidden_name and r["status"] == "reference"
                  for r in page._unified_term_rows()))
            check("zero_provider_calls", blank_project_audit._provider_calls == 0)
            result["passed"] = True
        except Exception:
            result["error"] = traceback.format_exc()
            window.grab().save(str(out / "layout-failure.png"))
        window.result_exit_code = 0 if result["passed"] else 1
        save()

        def stopped():
            result["gui_shutdown"] = True
            save()
        app.aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(900, run)
