"""A second owned dialog must receive input while the earlier guard is alive."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from twobyteasr.design.main_ui_dialogs import SpringDialog

APP = QApplication.instance() or QApplication([])


def test_nested_sibling_exec_keeps_latest_dialog_operable():
    owner = QWidget()
    owner.show()
    outer = SpringDialog(owner)
    outer.ENTRY_ANIMATED = outer.EXIT_ANIMATED = False
    child = SpringDialog(owner)
    child.ENTRY_ANIMATED = child.EXIT_ANIMATED = False
    layout = QVBoxLayout(child)
    close = QPushButton('关闭', child)
    layout.addWidget(close)
    clicks, ticks = [], []
    close.clicked.connect(lambda: (clicks.append(True), child.accept()))
    heartbeat = QTimer(child)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start(5)

    def nested():
        QTimer.singleShot(30, lambda: QTest.mouseClick(close, Qt.LeftButton))
        QTimer.singleShot(150, child.reject)
        child.exec()
        outer.accept()

    QTimer.singleShot(20, nested)
    outer.exec()
    try:
        assert ticks, 'The event loop must keep running during diagnosis'
        assert clicks == [True], 'The older input guard swallowed the newer close button'
        assert not getattr(APP, '_spring_dialog_guards', [])
    finally:
        heartbeat.stop()
        owner.close()
        owner.deleteLater()
        APP.processEvents()


def test_async_settings_sibling_can_close_inside_older_exec():
    owner=QWidget();owner.show()
    outer=SpringDialog(owner);outer.ENTRY_ANIMATED=outer.EXIT_ANIMATED=False
    settings=SpringDialog(owner);settings.ENTRY_ANIMATED=settings.EXIT_ANIMATED=False
    layout=QVBoxLayout(settings);close=QPushButton('取消',settings);layout.addWidget(close)
    hits=[]
    close.clicked.connect(lambda:(hits.append(True),settings.reject(),outer.accept()))
    def opened():
        settings.show()
        QTimer.singleShot(30,lambda:QTest.mouseClick(close,Qt.LeftButton))
        QTimer.singleShot(150,lambda:(settings.reject(),outer.reject()))
    QTimer.singleShot(20,opened)
    outer.exec()
    assert hits==[True]
    assert not getattr(APP,'_spring_visible_dialogs',[])
    owner.close();owner.deleteLater();APP.processEvents()
