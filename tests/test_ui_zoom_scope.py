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


def test_model_card_subtree_pass_keeps_selected_user_scale(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    app = QApplication.instance() or QApplication([])
    from twobyteasr.app import ui_zoom
    from twobyteasr.local_models import model_workshop as workshop
    page = workshop.ModelWorkshopPage.__new__(workshop.ModelWorkshopPage)
    QWidget.__init__(page)
    page.resize(1920, 900)
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    header = workshop.model_list_header()
    card = workshop.ModelCard(next(m for m in workshop.MODELS if m.key == 'moss'))
    layout.addWidget(header)
    layout.addWidget(card)
    monkeypatch.setitem(ui_zoom._state, 'percent', 120)
    monkeypatch.setitem(ui_zoom._state, 'touched', True)
    ui_zoom.apply_to(page, 1.2)
    # Theme/resize work may reach a cached row through a global-factor pass.
    # Every descendant cell follows the selected user scale.
    ui_zoom.apply_to(card)
    app.processEvents()
    factor = ui_zoom.effective_factor(page)
    assert factor == 1.2
    assert ui_zoom.effective_factor(card) == factor
    assert card.language_row.minimumWidth() == round(workshop._workshop_language_width(card._wide_languages) * factor)
    assert card.action_host.minimumWidth() == round(workshop.WORKSHOP_ACTION_COLUMN * factor)
    assert card.metrics_host.width() == round(workshop.WORKSHOP_METRIC_COLUMN * factor) * 2 + round(workshop.WORKSHOP_METRIC_SPACING * factor)
    page.deleteLater()


def test_workshop_finishes_columns_after_native_style_restores_old_sizes(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from twobyteasr.local_models import model_workshop as workshop
    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(ui_zoom._state, 'percent', 120)
    monkeypatch.setitem(ui_zoom._state, 'touched', True)
    page = workshop.ModelWorkshopPage.__new__(workshop.ModelWorkshopPage)
    QWidget.__init__(page)
    page.resize(1920, 900)
    layout = QVBoxLayout(page)
    header = workshop.model_list_header()
    page.list_header = header
    card = workshop.ModelCard(next(m for m in workshop.MODELS if m.key == 'moss'))
    layout.addWidget(header)
    layout.addWidget(card)
    page._cards = {'moss': SimpleNamespace(_card=card)}
    ui_zoom.apply_to(page, 1.2)
    # The native style restores original constraints after the zoom pass.
    card.language_row.setFixedWidth(workshop._workshop_language_width(card._wide_languages))
    card.action_host.setFixedWidth(workshop.WORKSHOP_ACTION_COLUMN)
    page._queue_column_sync()
    app.processEvents()
    factor = ui_zoom.effective_factor(page)
    assert card.language_row.width() == round(workshop._workshop_language_width(card._wide_languages)*factor)
    assert card.action_host.width() == round(workshop.WORKSHOP_ACTION_COLUMN*factor)
    page.deleteLater()
