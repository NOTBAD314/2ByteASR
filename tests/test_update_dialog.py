"""The update offer shows versions, notes and the real download size."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton

from twobyteasr.app.updater import ComponentAction, UpdatePlan


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _check(plan):
    manifest = SimpleNamespace(note_for=lambda language: "修复：校对后能打开工作台")
    return SimpleNamespace(manifest=manifest, plan=plan, latest_version="0.6.6", current_version="0.6.5")


def _texts(dialog):
    return "\n".join(w.text() for w in dialog.findChildren(QLabel)) + "\n" + \
        "\n".join(w.toPlainText() for w in dialog.findChildren(QPlainTextEdit))


def test_component_offer_lists_only_changed_parts(app):
    from twobyteasr.app.ui import UpdateOfferDialog

    plan = UpdatePlan("components", (
        ComponentAction("app", "changed", 23 * 1024 * 1024, 23 * 1024 * 1024, 48_000_000),
        ComponentAction("renderer", "reuse", 0, 0, 587_000_000),
        ComponentAction("tools", "reuse", 0, 0, 421_000_000),
    ), 23 * 1024 * 1024, 1_000_000_000, "", (), ())
    dialog = UpdateOfferDialog(_check(plan))
    text = _texts(dialog)
    assert "0.6.6" in text and "0.6.5" in text
    assert "23.0 MB" in text
    # 2026-11-12 (user): the kept parts and "nothing to download" lines are gone.
    assert "沿用" not in text and "高级字幕渲染器" not in text
    assert "修复" in text and "校对后能打开工作台" in text  # 2026-11-11: title and line of one card
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "下载并准备更新" in labels
    dialog.deleteLater()


@pytest.mark.parametrize("label, page", [
    ("打开 GitHub 发布页", "https://github.com/NOTBAD314/2ByteASR/releases"),
    ("打开 GitCode 发布页", "https://gitcode.com/Notbad314/2ByteASR/releases"),
    ("关闭", None),
])
def test_check_failed_box_offers_github_and_gitcode(app, monkeypatch, label, page):
    # 2026-10-22: on a mainland line github.com timed out while GitCode had the release.
    from PySide6.QtWidgets import QMessageBox, QWidget
    from twobyteasr.app import ui

    seen, opened = {}, []

    def press(box):
        seen["buttons"] = [b.text() for b in box.buttons()]
        seen["text"] = box.informativeText()
        next(b for b in box.buttons() if b.text() == label).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", press)
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    host = QWidget()
    ui.MainWindow._update_check_failed(host, "github.com：Read timed out")
    assert seen["buttons"] == ["打开 GitHub 发布页", "打开 GitCode 发布页", "关闭"]
    assert "github.com：Read timed out" in seen["text"] and "GitCode" in seen["text"]
    assert opened == ([page] if page else [])
    host.deleteLater()


def test_setup_fallback_states_size_and_reason(app):
    from twobyteasr.app.ui import UpdateOfferDialog

    plan = UpdatePlan("setup", (), 1_200_000_000, 1_200_000_000, "当前安装没有元件清单", ("moss",), ("moss",))
    dialog = UpdateOfferDialog(_check(plan))
    text = _texts(dialog)
    assert "完整安装包" in text and "1.12 GB" in text and "当前安装没有元件清单" in text
    assert "moss 的需求有变化" in text and "只有用到该模型时才需要下载" in text
    assert "下载安装包" in [b.text() for b in dialog.findChildren(QPushButton)]
    dialog.deleteLater()


def test_notes_become_cards_only_when_the_lines_fit():
    # 2026-11-11: the notes are free text; the layout must hold for any count.
    from twobyteasr.app.update_dialog import card_cells, highlight_plan, note_items, split_highlight

    items = note_items("· 字幕固定避让，结束释放空位。\n\n- 14 字内优先一条\n  • 第三条：说明\n第四条\n第五条")
    assert items == ["字幕固定避让，结束释放空位。", "14 字内优先一条", "第三条：说明", "第四条", "第五条"]
    assert split_highlight(items[0]) == ("字幕固定避让", "结束释放空位。")
    assert split_highlight("没有逗号的一整句。") == ("没有逗号的一整句", "")
    cards, rest, as_cards = highlight_plan(items)
    assert as_cards and len(cards) == 4 and rest == ["第五条"]
    assert highlight_plan(["短", "长" * 61]) == ([], ["短", "长" * 61], False)
    assert highlight_plan([]) == ([], [], False)
    assert card_cells(1) == [(0, 0, 2)]
    assert card_cells(3) == [(0, 0, 2), (1, 0, 1), (1, 1, 1)]
    assert [cell[:2] for cell in card_cells(4)] == [(0, 0), (0, 1), (1, 0), (1, 1)]


@pytest.mark.parametrize("count, cards, more", [(1, 1, False), (3, 3, False), (4, 4, False), (6, 4, True)])
def test_offer_layout_follows_the_number_of_notes(app, count, cards, more):
    from twobyteasr.app.update_dialog import UpdateOfferDialog

    notes = "\n".join(f"· 第{index}项，说明文字" for index in range(count))
    plan = UpdatePlan("components", (ComponentAction("app", "changed", 1, 1, 1),), 1, 10, "", (), ())
    check = SimpleNamespace(manifest=SimpleNamespace(note_for=lambda language: notes), plan=plan,
                            latest_version="0.9.8", current_version="0.9.7")
    dialog = UpdateOfferDialog(check)
    assert len(dialog.highlight_cards) == cards
    line = getattr(dialog, "more_line", None)
    assert (line is not None) == more
    if more:
        # One line ending with 查看完整说明, which opens the release page.
        assert "第4项" in line.text() and "第5项" in line.text() and "查看完整说明" in line.text()
        line.linkActivated.emit("page")
        assert dialog.choice == "page"
    assert "第0项" in _texts(dialog)
    dialog.deleteLater()
