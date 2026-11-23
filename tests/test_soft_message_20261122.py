"""No Windows pop-ups for 交给兔白 (2026-11-22): rounded notices and a frameless 兔白 window."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.design.main_ui_dialogs import SpringDialog
from twobyteasr.design.soft_message import SoftMessage, soft_information, soft_question


def _app():
    return QApplication.instance() or QApplication([])


def _answer(click):
    """Click a button of the next SoftMessage once it is up."""
    def later():
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, SoftMessage) and w.isVisible())
        click(dialog)
    QTimer.singleShot(50, later)


def test_soft_message_is_frameless_and_answers():
    _app()
    parent = QWidget()
    parent.show()
    message = SoftMessage(parent, "标题", "内容", accept_text="好", reject_text="不要")
    assert message.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert message.accept_button.text() == "好" and message.reject_button.text() == "不要"
    _answer(lambda dialog: dialog.accept_button.click())
    assert soft_question(parent, "还原？", "会丢掉修改", accept_text="仍要还原", reject_text="先不还原") is True
    _answer(lambda dialog: dialog.reject_button.click())
    assert soft_question(parent, "还原？", "会丢掉修改") is False
    _answer(lambda dialog: dialog.accept_button.click())
    soft_information(parent, "现在不能交给兔白", "识别还在运行")
    parent.close()


def test_destructive_question_does_not_confirm_on_enter():
    _app()
    parent = QWidget()
    message = SoftMessage(parent, "还原", "丢掉修改", accept_text="仍要还原", reject_text="先不还原", destructive=True)
    assert message.reject_button.isDefault() and not message.accept_button.isDefault()


def test_repair_window_has_no_windows_frame_and_notices_are_soft(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app import completion_ai_repair_ui as rui
    _app()

    class Window(QWidget):
        _run_in_progress = True

        def built_page(self, name):
            return None

    window = Window()
    controller = rui.RepairController(window)
    controller.plan = SimpleNamespace(categories=[], project_path="x.2byteproj", fixable=0, manual=0,
                                      category=lambda key: None, estimate=lambda chosen: SimpleNamespace(
        cost_text=lambda: "", time_text=lambda: "", audio_seconds=0))
    dialog = rui.RepairDialog(controller, window)
    assert isinstance(dialog, SpringDialog)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.close_button.isVisibleTo(dialog)
    seen = []
    monkeypatch.setattr(rui, "soft_information", lambda parent, title, text, **kw: seen.append((title, text)))
    assert controller.start({"timing"}) is False
    assert seen and "兔白" in seen[0][0]
    controller.state = "running"
    dialog.show()
    dialog._close_clicked()                 # closing while running only hides it
    assert dialog.isHidden() and controller.state == "running"
    controller.state = "idle"
    dialog.deleteLater()


def test_repair_window_design_b_counts_and_chips(tmp_path, monkeypatch):
    """Design B (2026-11-22): three numbers, kinds as chips behind a disclosure, done chips per kind."""
    from tests.test_completion_ai_repair import _plan, _project
    from twobyteasr.app import completion_ai_repair as repair
    from twobyteasr.app import completion_ai_repair_ui as rui
    from twobyteasr.projects.studio_project import save_project
    _app()
    p, report = _project()
    path = save_project(p, tmp_path / "task.2byteproj")
    monkeypatch.setattr(repair, "text_ai_ready", lambda settings, stage="polish": True)
    monkeypatch.setattr(repair, "speech_backend", lambda settings: ("local", "本机测试模型"))

    class Window(QWidget):
        def built_page(self, name):
            return None

    window = Window()
    controller = rui.RepairController(window)
    controller.plan = _plan(path, report)
    dialog = rui.RepairDialog(controller, window)
    plan = controller.plan
    automatic = {item.key for item in plan.categories if item.automatic}
    assert set(dialog.cards) == automatic and dialog.chosen == automatic
    local = sum(item.count for item in plan.categories if item.automatic and item.key in repair.LOCAL)
    assert dialog.tiles[0].value.text().startswith(str(local))
    assert dialog.tiles[2].value.text().startswith(str(plan.manual))
    assert dialog.chips_host.isHidden()
    dialog._toggle_adjust()
    assert not dialog.chips_host.isHidden()
    key = next(iter(automatic - repair.LOCAL))
    dialog.cards[key].click()
    assert key not in dialog.chosen and dialog.cards[key].property("chosen") is False
    controller.state, controller.selected = "running", set(dialog.chosen)
    controller.progress = {k: (0, 1, "") for k in dialog.chosen}
    dialog.refresh()
    assert dialog.bunny.progress is not None and not dialog.steps.isHidden() and dialog.tiles_row.isHidden()
    controller.state = "idle"
    dialog.deleteLater()
