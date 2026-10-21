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
    assert "23.0 MB" in text and "主程序" in text
    assert "高级字幕渲染器" in text and "媒体工具" in text  # listed as kept
    assert "运行环境：沿用" in text and "模型：沿用" in text
    assert "修复：校对后能打开工作台" in text
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "下载并准备更新" in labels
    dialog.deleteLater()


def test_setup_fallback_states_size_and_reason(app):
    from twobyteasr.app.ui import UpdateOfferDialog

    plan = UpdatePlan("setup", (), 1_200_000_000, 1_200_000_000, "当前安装没有元件清单", ("moss",), ("moss",))
    dialog = UpdateOfferDialog(_check(plan))
    text = _texts(dialog)
    assert "完整安装包" in text and "1.12 GB" in text and "当前安装没有元件清单" in text
    assert "moss 的需求有变化" in text and "只有用到该模型时才需要下载" in text
    assert "下载安装包" in [b.text() for b in dialog.findChildren(QPushButton)]
    dialog.deleteLater()
