import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import io

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_canvas import CoverSession, CoverView
from twobyteasr.cover.cover_psd import save_psd, load_local_psd, inspect_psd


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def document():
    stream=io.BytesIO(); Image.new('RGBA',(320,180),(20,110,65,140)).save(stream,format='PNG')
    doc=CoverDocument(width=640,height=360)
    doc.add_image(stream.getvalue(),'透明人物',(320,180),background=True)
    return doc


def test_new_background_unlocked_old_lock_retained(tmp_path):
    doc=document(); layer=doc.layers[0]
    assert not layer.locked
    layer.locked=True; doc.save(tmp_path/'old.2bytecover')
    assert CoverDocument.load(tmp_path/'old.2bytecover').layers[0].locked


@pytest.mark.parametrize('zoom',[.36])
@pytest.mark.parametrize('keep_aspect',[True,False])
@pytest.mark.parametrize('handle',[0,1,2,3,4,5,6,7])
def test_scale_option_all_handles_anchor_single_undo(app,zoom,handle,keep_aspect):
    doc=document(); layer=doc.layers[0]
    layer.x,layer.y,layer.width,layer.height=160,90,320,180
    layer.keep_aspect=keep_aspect
    session=CoverSession(doc); session.selected={layer.id}
    view=CoverView(session); view.resize(900,640); view.show(); view.set_zoom(zoom)
    app.processEvents()
    bounds=view.items_by_id[layer.id].sceneBoundingRect()
    point=view.mapFromScene(view.handle_points(bounds)[handle])
    assert view.hit_handle(point+QPoint(8,0)) is not None
    # Consecutive option cases share coordinates; move away first so Qt emits
    # a fresh hover event for the newly constructed offscreen viewport.
    QTest.mouseMove(view.viewport(),point+QPoint(-40,-40))
    QTest.mouseMove(view.viewport(),point); app.processEvents()
    assert view.cursor().shape()==view.handle_cursor(handle)
    QTest.mousePress(view.viewport(),Qt.LeftButton,pos=point)
    # Changing mode mid-drag must not alter the captured gesture semantics.
    session.document.layer(layer.id).keep_aspect=not keep_aspect
    delta=QPoint(-18 if handle in (0,2,7) else 18,-14 if handle in (0,1,4) else 14)
    QTest.mouseMove(view.viewport(),point+delta)
    QTest.mouseRelease(view.viewport(),Qt.LeftButton,pos=point+delta)
    actual=session.document.layer(layer.id)
    if keep_aspect: assert actual.width/actual.height==pytest.approx(320/180)
    elif handle in (5,7): assert actual.height==180
    elif handle in (4,6): assert actual.width==320
    else: assert actual.width/actual.height!=pytest.approx(320/180)
    if keep_aspect and handle in (4,6): assert actual.x+actual.width/2==pytest.approx(320)
    elif handle in (0,2,7): assert actual.x+actual.width==pytest.approx(480)
    else: assert actual.x==160
    if keep_aspect and handle in (5,7): assert actual.y+actual.height/2==pytest.approx(180)
    elif handle in (0,1,4): assert actual.y+actual.height==pytest.approx(270)
    else: assert actual.y==90
    assert session.undo.count()==1
    session.undo.undo(); assert session.document.layer(layer.id).width==320
    session.undo.redo(); assert session.document.layer(layer.id).width==actual.width
    view.close()


def test_real_psd_type_layers_original_assets_and_atomic_failure(tmp_path,app,monkeypatch):
    doc=document(); title=doc.add_text('中文标题\n仍可编辑'); title.style.update(size=36,stroke=2,shadow=False)
    path=tmp_path/'中文.psd'; save_psd(doc,path)
    assert path.read_bytes().startswith(b'8BPS\x00\x01')
    result=inspect_psd(path)['document']
    assert len(result['children'])==2
    assert '中文标题' in result['children'][1]['text']['text']
    assert result['children'][1]['text']['style']['font']['name']=='SourceHanSansSC-Heavy'
    assert load_local_psd(path).signature()==doc.signature()
    before=path.read_bytes()
    import twobyteasr.cover.cover_psd as module
    monkeypatch.setattr(module.os,'replace',lambda *args: (_ for _ in ()).throw(PermissionError('readonly')))
    with pytest.raises(PermissionError): save_psd(doc,path)
    assert path.read_bytes()==before


def test_psd_retains_visible_canvas_fill(tmp_path,app):
    doc=document();doc.background='#284c39'
    path=tmp_path/'fill.psd';save_psd(doc,path)
    layers=inspect_psd(path)['document']['children']
    assert layers[0]['name']=='画布底色'
    assert layers[0]['left']==0 and layers[0]['top']==0
    assert load_local_psd(path).background=='#284c39'
