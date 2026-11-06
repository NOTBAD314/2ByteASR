from types import SimpleNamespace
from twobyteasr.media.media_availability import apply_availability,media_available,record_probe,probe_due,availability_identity


def project(offline=False):
    return SimpleNamespace(media_pool=[SimpleNamespace(canonical_source='drive/clip.mp4',offline=offline,relink_state='offline' if offline else 'linked')])


def test_slow_device_does_not_turn_verified_media_into_missing():
    p=project();apply_availability(p,{'drive/clip.mp4':dict(status='available',signature=[10,20])})
    apply_availability(p,{'drive/clip.mp4':dict(status='slow',verified_available=True,signature=[10,20])})
    assert not p.media_pool[0].offline and media_available(p,'drive/clip.mp4')


def test_unknown_slow_path_is_not_claimed_available_or_confirmed_missing():
    p=project();apply_availability(p,{'drive/clip.mp4':dict(status='slow',verified_available=False)})
    assert not p.media_pool[0].offline and not media_available(p,'drive/clip.mp4')


def test_confirmed_missing_and_recovery_change_only_current_referenced_path():
    p=project();apply_availability(p,{'unrelated':dict(status='missing'),'drive/clip.mp4':dict(status='missing')})
    assert p.media_pool[0].offline and not media_available(p,'drive/clip.mp4')
    apply_availability(p,{'drive/clip.mp4':dict(status='available',signature=[10,20])})
    assert not p.media_pool[0].offline and p.media_pool[0].relink_state=='linked'


def test_negative_cache_expires_and_backs_off_without_becoming_missing():
    previous={}
    for now,delay in [(0,3),(3,10),(13,30),(43,30)]:
        previous=record_probe(dict(status='slow'),previous,started=now,now=now)
        assert not probe_due(previous,now+delay-.01)
        assert probe_due(previous,now+delay)
    recovered=record_probe(dict(status='available',signature=[1,2]),previous,started=73,now=73)
    assert recovered['failures']==0 and recovered['probe_count']==5
    assert not probe_due(recovered,87.9) and probe_due(recovered,88)


def test_probe_timestamp_does_not_invalidate_decoder_identity():
    a=dict(status='available',signature=[1,2],identity={'duration_ms':3000})
    assert availability_identity(a)==availability_identity(record_probe(a,{},started=1,now=2))
    assert availability_identity(a)!=availability_identity(dict(a,signature=[2,3]))


def test_gui_cached_metadata_never_stats_the_drive(monkeypatch,tmp_path):
    from twobyteasr.media.media_service import MediaService,MediaMetadataSnapshot
    service=MediaService(cache_root=tmp_path)
    path=str(tmp_path/'external.mp4')
    snapshot=MediaMetadataSnapshot(path,100,200,3000,True,True)
    service._known_metadata[service._path_key(path)]=snapshot
    def forbidden(*args,**kwargs):raise AssertionError('GUI filesystem access')
    monkeypatch.setattr('os.stat',forbidden)
    assert service.cached_metadata(path) is snapshot
    service.invalidate_metadata(path,[100,200]);assert service.cached_metadata(path) is snapshot
    service.invalidate_metadata(path,[100,201]);assert service.cached_metadata(path) is None
