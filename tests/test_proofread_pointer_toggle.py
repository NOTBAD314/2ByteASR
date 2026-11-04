from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_proofread_retention import page, APP


def test_fast_second_click_is_one_revert_not_swallowed(page):
    w, p = page
    w.resize(1400, 850)
    w.show()
    APP.processEvents()
    def point():
        w.list.repaint()
        return next(rect.center().toPoint() for rect, action, key, index in w.list._hit_boxes
                    if action == 'check' and key == 'middle' and index == 0)
    original = p.cues[0].text
    QTest.mouseClick(w.list, Qt.LeftButton, pos=point())
    assert p.cues[0].text == '大骨龙和火龙来了'
    QTest.mouseDClick(w.list, Qt.LeftButton, pos=point())
    QTest.mouseRelease(w.list, Qt.LeftButton, pos=point())
    assert p.cues[0].text == original
    assert w._live_stack().count() == 2
    QTest.mouseClick(w.list, Qt.LeftButton, pos=point())
    assert p.cues[0].text == '大骨龙和火龙来了'
    assert w._live_stack().count() == 3
