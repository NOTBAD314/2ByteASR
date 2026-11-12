"""The loading mascot keeps its authored motion while dropping invisible pixels."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint,QPointF,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication

@pytest.mark.parametrize('ratio',[1.0,1.25,1.75,2.0])
@pytest.mark.parametrize('moment',[0.0,1.3,2.5])
def test_cropped_layers_match_uncropped_frame(monkeypatch,ratio,moment):
    from twobyteasr.design import bunny_mascot as module
    app=QApplication.instance() or QApplication([])
    original=module.BunnyMascot(height=270);cropped=module.BunnyMascot(height=270)
    assert cropped.rig
    original.rig = module.load_rig()
    # Independent reference: the original untrimmed full PNG layers, scaled
    # synchronously only in this pixel regression. Production uses worker QImages.
    def reference_layers():
        factor = original.scale * ratio
        original._scaled = {name: image.scaled(round(image.width()*factor),round(image.height()*factor),
            Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            for name,image in original.rig[1].items()}
        for image in original._scaled.values():image.setDevicePixelRatio(ratio)
        original._scaled_offsets = {name:QPointF() for name in original._scaled}
        return original._scaled
    original._layers = reference_layers
    import time
    from PySide6.QtTest import QTest
    key = cropped._assets.request(270,ratio)
    deadline = time.monotonic()+5
    while key not in cropped._assets.cache and time.monotonic()<deadline:
        time.sleep(.005);QTest.qWait(5)
    assert key in cropped._assets.cache
    monkeypatch.setattr(module.time,'perf_counter',lambda:moment)
    def capture(widget):
        widget.devicePixelRatioF=lambda:ratio
        widget.reduced_motion=False;widget._started=0;widget._next_blink=99;widget._talk_until=10
        image=QImage(round(widget.width()*ratio),round(widget.height()*ratio),QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio);image.fill(0)
        painter=QPainter(image);widget.render(painter,QPoint());painter.end()
        return np.frombuffer(image.bits(),np.uint8).copy()
    before,after=capture(original),capture(cropped)
    difference=np.abs(before.astype(np.int16)-after.astype(np.int16))
    # Border interpolation can round by one channel value after a rotated
    # crop. There must be no moved/missing features or clipping of the glare.
    assert np.mean(difference)<.05
    assert np.mean(difference>8)<.0005
    old_pixels=sum(p.width()*p.height() for p in original._scaled.values())
    new_pixels=sum(p.width()*p.height() for p in cropped._scaled.values())
    assert new_pixels<old_pixels*.12
    original.close();cropped.close()


def test_cover_backfill_uses_summary_not_full_document(tmp_path,monkeypatch):
    import threading
    from types import SimpleNamespace
    from twobyteasr.studio import studio_media_flow as flow
    path=tmp_path/'p.2byteproj';path.write_text('{}');st=path.stat();done=threading.Event();seen=[]
    monkeypatch.setattr(flow,'load_project',lambda *a:pytest.fail('cover loaded the full project'))
    host=SimpleNamespace(_ensure_project_cover=lambda path,project:seen.append(project.media.path) or '',
                         cover_ready_signal=SimpleNamespace(emit=lambda *a:done.set()))
    flow.StudioMediaFlowMixin._queue_project_cover_backfill(host,dict(path=str(path),source_media='media.mp4',duration_ms=1000,
        _file_version=(st.st_size,st.st_mtime_ns)))
    assert done.wait(2) and seen==['media.mp4']


def test_cover_job_does_not_overwrite_new_custom_cover(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.projects import studio_project_controller as controller
    path=tmp_path/'p.2byteproj';path.write_text('{}')
    media=tmp_path/'video.mp4';media.write_bytes(b'fixture')
    cover=tmp_path/'preview/project-cover.jpg'
    def encode(command,**kwargs):
        from pathlib import Path
        Path(command[-1]).write_bytes(b'generated'*200)
        cover.write_bytes(b'user-custom'*200)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(controller,'run_hidden_subprocess',encode)
    result=controller.StudioProjectController._ensure_project_cover(None,path,
        SimpleNamespace(media=SimpleNamespace(path=str(media),duration_ms=1000)))
    assert result is None and cover.read_bytes()==b'user-custom'*200
    assert not list(cover.parent.glob('.project-cover-*'))
