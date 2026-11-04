"""Actual decoder EOF(0) with no PCM must not strand an FLV preview."""
from pathlib import Path
import subprocess
import time
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudioFormat
from twobyteasr.playback.audio_engine import _AudioEngineWorker,_PcmRingDevice,AudioOutputSpec,studio_ffmpeg_path


def test_empty_indexed_copy_falls_back_to_original_once(tmp_path):
    app=QApplication.instance() or QApplication([])
    ffmpeg=studio_ffmpeg_path()
    source=tmp_path/'original.flv';short=tmp_path/'bad-seek-copy.mka'
    for path,seconds,fmt in [(source,4,'flv'),(short,.25,'matroska')]:
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i',f'sine=frequency=440:sample_rate=48000:duration={seconds}',
                        '-c:a','aac','-f',fmt,str(path)],check=True,capture_output=True)
    worker=_AudioEngineWorker(ffmpeg)
    worker._output_spec=AudioOutputSpec(48000,2,QAudioFormat.SampleFormat.Float,4,'f32le')
    worker.device=_PcmRingDevice(sample_format=worker._output_spec.sample_format)
    worker._ensure_sink=lambda:True
    worker._emit=lambda *_:None
    worker._trace_decoder=lambda *a,**k:None
    request=dict(source_path=str(source),source_ms=1500,source_out_ms=3500,clip_rate=1,transport_rate=1,
                 audible=True,paused=True,volume=1,transport_generation=(1,1),
                 decode_source=dict(path=str(short),offset_ms=0))
    try:
        worker.synchronize(request)
        worker._feeder.join(4)
        assert worker._decoder_eof and not worker.device.has_produced_pcm()
        assert worker.process.wait(4)==0  # this successful exit was the sticky case
        worker.synchronize(request)
        until=time.monotonic()+4
        while not worker.device.has_produced_pcm() and time.monotonic()<until:time.sleep(.01)
        assert worker._decode_input_path==str(source)
        assert worker.device.has_produced_pcm()
        assert worker.device.producer_rms>0.01
        generation=worker._source_generation
        for _ in range(4):worker.synchronize(request)
        assert worker._source_generation==generation  # no repeat recovery
        assert str(short) in worker._rejected_seek_copies
    finally:
        worker._stop_decoder()
        worker.device.close()
