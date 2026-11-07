"""Completed audio tails are terminal tiles, not endlessly refreshing partials."""
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.waveform_cache import WaveformLevel
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.waveform_tiles import build_envelope

APP = QApplication.instance() or QApplication([])


class Cache:
    def __init__(self,count,*,incomplete=False,origin=0):
        self.metadata=SimpleNamespace(incomplete=incomplete,sample_timeline_origin_ms=origin)
        self.level=WaveformLevel(0,count,16.,'lod0.f32')
        self.pairs=np.tile(np.array([[-.5,.5]],dtype=np.float32),(count,1))
    def read_window(self,*args):
        return self.level,self.pairs


def test_finished_short_audio_tail_is_complete_in_worker_and_sync_path():
    cache=Cache(10)
    assert build_envelope(cache,0,1600,100,100)[2] is True
    page=SimpleNamespace(_trace_waveform_lod=lambda *args:None)
    assert WaveformTimeline._build_waveform_envelope(page,cache,0,1600,100,100,60)[2] is True


def test_finished_empty_window_is_cached_as_terminal_silence():
    result=build_envelope(Cache(0),2000,3000,100,100)
    assert result is not None and result[0].isEmpty() and result[2] is True


def test_progressive_uncovered_tail_remains_incomplete():
    assert build_envelope(Cache(10,incomplete=True),0,1600,100,100)[2] is False


def test_expired_partial_is_drawn_while_refresh_is_queued():
    cache=Cache(10,incomplete=True)
    path=QPainterPath();path.addRect(0,-1,100,2)
    key=(cache,0,0.,1024.,1.)
    page=SimpleNamespace(WAVEFORM_TILE_PX=1024,_waveform_tile_cache=OrderedDict(),
        _waveform_partial_tiles={key:(cache,path,{'buckets':10},0.)},
        _paint_geometry_cache={},_waveform_tile_jobs={})
    pieces=WaveformTimeline._waveform_envelope_tiles(page,cache,0,1024,0,1024,QRectF(0,0,1024,100),0,1024)
    assert len(pieces)==1 and not pieces[0][0].isEmpty()
    assert key in page._waveform_tile_jobs
