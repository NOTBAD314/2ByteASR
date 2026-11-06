import hashlib
import json
import threading
import time
from types import SimpleNamespace

from twobyteasr.media.relocation_identity import FINGERPRINT_FIELDS,fingerprint_at_source,verified_relocation


def test_batch_relocation_requires_original_full_metadata_identity():
    original={name:0 for name in FINGERPRINT_FIELDS}
    original.update(size=123456,mtime_ns=123456789,duration_ms=3000,video_codec='h264',audio_codec='aac')
    old='E:/known/recording.mp4'
    expected=hashlib.sha256(json.dumps(dict(original,path=old),sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
    asset=SimpleNamespace(canonical_source=old,fingerprint=expected)
    row=dict(path='F:/relocated/recording.mp4',status='available',identity=dict(original,source_path='F:/relocated/recording.mp4'))
    assert verified_relocation(asset,row)
    assert not verified_relocation(asset,dict(row,identity=dict(original,size=123455)))
    assert not verified_relocation(asset,dict(row,identity={'duration_ms':3000}))
    assert not verified_relocation(SimpleNamespace(canonical_source=old,fingerprint=''),row)


def test_gui_cache_lookup_is_nonblocking_coalesced_and_rejects_old_generation(tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.media.indexed_media import IndexedMediaCache
    app=QApplication.instance() or QApplication([])
    cache=IndexedMediaCache(tmp_path)
    entered=threading.Event();release=threading.Event();calls=[]
    def blocked():
        calls.append(threading.get_ident());entered.set();release.wait(2);return 'old'
    start=time.monotonic()
    for _ in range(50):assert cache._gui_read('probe','drive',blocked,None) is None
    assert time.monotonic()-start<.2 and entered.wait(1)
    assert len(calls)==1 and calls[0]!=threading.get_ident()
    cache.invalidate_source('drive');release.set()
    end=time.monotonic()+2
    while cache._gui_reads_pending and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert ('probe','drive') not in cache._gui_reads
    assert cache._gui_read('probe','drive',lambda:'new',None) is None
    end=time.monotonic()+2
    while ('probe','drive') not in cache._gui_reads and time.monotonic()<end:time.sleep(.005)
    assert cache._gui_read('probe','drive',lambda:'wrong',None)=='new'


def test_real_disposable_reader_slow_cancel_and_recovery(tmp_path,monkeypatch):
    from twobyteasr.media.media_availability import probe_sources,shutdown_probe_worker
    source=tmp_path/'drive.bin';source.write_bytes(b'fixture')
    shutdown_probe_worker();monkeypatch.setenv('TWOBYTEASR_TEST_MEDIA_DELAY','2')
    try:
        row=probe_sources([str(source)],timeout=.1)[str(source)]
        assert row['status']=='slow' and not row['verified_available']
        cancelled=threading.Event();threading.Timer(.15,cancelled.set).start()
        import pytest
        with pytest.raises(InterruptedError):probe_sources([str(source)],timeout=3,cancel_check=cancelled.is_set)
    finally:
        shutdown_probe_worker();monkeypatch.delenv('TWOBYTEASR_TEST_MEDIA_DELAY')
    recovered=probe_sources([str(source)],timeout=3)[str(source)]
    assert recovered['status']=='available'
    source.unlink()
    assert probe_sources([str(source)])[str(source)]['status']=='missing'
    shutdown_probe_worker()
