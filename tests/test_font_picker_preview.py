from pathlib import Path
import pytest
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QFont,QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy,QTest
from twobyteasr.caption_style.font_picker_preview import FontPreviewRequest,preview_face,draw_font_preview,_FACES,MAX_PREVIEW_FACES
from twobyteasr.caption_style.studio_font_combo import LazyFontComboBox,FontPreviewEdit

APP=QApplication.instance()or QApplication([])
ROOT=Path(__file__).resolve().parents[1]


def request(family='Cubic 11'):
    return FontPreviewRequest(family,filename=str(ROOT/'assets/fonts/Cubic11.ttf'))


def paint(spec,name):
    image=QImage(360,36,QImage.Format_ARGB32_Premultiplied);image.fill(QColor('#222222'))
    painter=QPainter(image);font=QFont('Arial');font.setPixelSize(13)
    state=draw_font_preview(painter,QRectF(8,3,344,30),name,spec,font,QColor('white'));painter.end()
    return image,state


def test_file_face_draws_real_sample_without_platform_substitution():
    face,warning=preview_face(request(),18)
    assert face and face.raw.familyName()=='Cubic 11'
    assert face.covers('ABC123') and all(face.raw.glyphIndexesForString('ABC123'))
    image,state=paint(request(),'Cubic 11')
    assert state['actual']=='Cubic 11' and state['name_uses_target'] and state['sample']=='示例ABC123'
    assert not state['sample_uses_ui_prefix'] and state['sample_complete']
    assert state['sample_supported']


def test_existing_chinese_alias_uses_real_glyphs_even_when_os2_coverage_is_wrong():
    face,_=preview_face(request('俐方体11号'),18)
    assert face and face.covers('俐方体11号')
    _,state=paint(request('俐方体11号'),'俐方体11号')
    assert state['name_uses_target'] and state['actual']=='Cubic 11'
    assert state['sample']=='示例ABC123' and state['sample_supported']


def test_genuinely_unsupported_name_uses_ui_but_example_remains_target():
    from twobyteasr.caption_style.font_metadata import resolve_local_face
    face,_=resolve_local_face('Arial')
    if face.family!='Arial':pytest.skip('Arial is not installed')
    spec=FontPreviewRequest('中文名称',filename=face.file,face_index=face.index)
    _,state=paint(spec,'中文名称')
    assert not state['name_uses_target'] and state['actual']=='Arial'
    assert state['sample']=='示例ABC123' and state['sample_supported']
    assert state['sample_uses_ui_prefix'] and state['target_sample']=='ABC123'


def test_missing_face_never_paints_an_unlabelled_fallback_sample():
    _,state=paint(FontPreviewRequest('Not installed test face 87417'),'Not installed test face 87417')
    assert not state['actual'] and not state['sample'] and not state['name_uses_target']
    assert state['warning']


def test_raw_face_cache_is_bounded():
    for px in range(12,12+MAX_PREVIEW_FACES+10):assert preview_face(request(),px)[0]
    assert len(_FACES)<=MAX_PREVIEW_FACES


def test_open_search_cancel_never_commits_or_loses_the_selected_family():
    combo=LazyFontComboBox();combo.setEditable(True);combo.resize(280,32);combo.show()
    combo.setEditText('Cubic 11');combo.set_preview_face('Cubic 11',filename=request().filename)
    picked=QSignalSpy(combo.fontPicked)
    combo.showPopup();QTest.qWait(40)
    assert combo.view().isVisible()
    combo.lineEdit().selectAll();QTest.keyClicks(combo.lineEdit(),'cubic')
    assert combo.view().isVisible() and picked.count()==0
    combo.hidePopup()
    assert combo.currentText()=='Cubic 11' and picked.count()==0
    assert not combo._font_preview_timer.isActive()and not combo._pending_font_previews
    assert isinstance(combo.lineEdit(),FontPreviewEdit)
    combo.close();combo.deleteLater();APP.processEvents()


def test_formal_selection_emits_once_and_collapsed_preview_is_not_caption_size():
    combo=LazyFontComboBox();combo.setEditable(True);combo.resize(280,32);combo.show()
    picked=QSignalSpy(combo.fontPicked);combo.commit_family('Cubic 11')
    combo.set_preview_face('Cubic 11',filename=request().filename)
    combo.grab()
    assert picked.count()==1 and combo.currentText()=='Cubic 11'
    assert combo._last_font_preview['actual']=='Cubic 11'
    assert combo.lineEdit().font().pixelSize()!=61
    combo.close();combo.deleteLater();APP.processEvents()


def test_warm_picker_does_not_enumerate_font_inventory_again(monkeypatch):
    import twobyteasr.caption_style.studio_font_combo as module
    combo=LazyFontComboBox();combo.setEditable(True);combo.resize(280,32);combo.show()
    combo.showPopup();combo.hidePopup()
    monkeypatch.setattr(module,'system_font_inventory',lambda:(_ for _ in ()).throw(AssertionError('repeat inventory')))
    for _ in range(3):combo.showPopup();combo.hidePopup()
    combo.close();combo.deleteLater();APP.processEvents()
