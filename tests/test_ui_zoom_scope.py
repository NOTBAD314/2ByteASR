from PySide6.QtWidgets import QApplication,QDialog,QWidget
from twobyteasr.app import ui_zoom

def test_late_children_keep_the_page_reading_size_without_changing_other_pages(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setitem(ui_zoom._state,'percent',100);monkeypatch.setitem(ui_zoom._state,'touched',True)
    root=QWidget();page=QWidget(root);page.ui_zoom_factor=lambda factor:max(factor,2.)
    child=QWidget(page);ui_zoom.set_size(child,fixed_w=120)
    other=QWidget(root);ui_zoom.set_size(other,fixed_w=120)
    ui_zoom.apply_to(root)
    assert child.width()==240 and other.width()==120
    late=QWidget(page);ui_zoom.set_size(late,fixed_w=120);ui_zoom.apply_to(late)
    assert late.width()==child.width()==240
    ui_zoom.apply_to(root);assert late.width()==240
    root.deleteLater();app.processEvents()

def test_independent_dialog_uses_user_zoom_instead_of_owner_page_density(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setitem(ui_zoom._state,'percent',120);monkeypatch.setitem(ui_zoom._state,'touched',True)
    root=QWidget();page=QWidget(root);page.ui_zoom_factor=lambda factor:max(factor,2.)
    dialog=QDialog(page);child=QWidget(dialog);ui_zoom.set_size(child,fixed_w=100)
    assert child.width()==120 and ui_zoom.effective_factor(dialog)==1.2
    root.deleteLater();app.processEvents()
