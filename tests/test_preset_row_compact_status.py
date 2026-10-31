from PySide6.QtWidgets import QApplication
from twobyteasr.caption_style.studio_style_widgets import ElidedComboBox

APP=QApplication.instance()or QApplication([])


def test_modified_state_reserves_only_a_dot_and_preserves_full_value():
    combo=ElidedComboBox();combo.addItem('尼奈 · 已修改','ni')
    combo.set_display_label('尼奈',True);combo.resize(128,30);combo.show();APP.processEvents()
    assert combo.displayed_text()=='尼奈'
    assert combo.currentText()=='尼奈 · 已修改'and combo.property('presetModified')
    assert combo.display_text_source()=='尼奈'
    combo.grab();combo.deleteLater();APP.processEvents()


def test_long_name_elides_only_when_needed_and_current_index_cannot_keep_a_stale_name():
    combo=ElidedComboBox();long='这是一个确实无法放进窄选框的完整预设名称'
    combo.addItem(long+' · 已修改','long');combo.addItem('短名字','short')
    combo.set_display_label(long,True);combo.resize(128,30);combo.show();APP.processEvents()
    assert combo.displayed_text().endswith('…')
    combo.resize(700,30);APP.processEvents();assert combo.displayed_text()==long
    combo.setCurrentIndex(1);assert combo.displayed_text()=='短名字'
    combo.deleteLater();APP.processEvents()
