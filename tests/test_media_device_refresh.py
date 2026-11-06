from types import SimpleNamespace
from twobyteasr.studio.studio_media_availability import StudioMediaAvailability


def test_device_notification_invalidates_negative_ttl_and_rejects_the_old_reply():
    starts=[];applied=[]
    project=SimpleNamespace(_media_availability={'external.mp4':dict(status='offline',failures=3,next_probe_monotonic=999)})
    owner=SimpleNamespace(_probe_generation=7,page=SimpleNamespace(project=project),
        _device_probe_timer=SimpleNamespace(start=starts.append),apply=lambda *args:applied.append(args))
    StudioMediaAvailability.device_changed(owner)
    assert owner._probe_generation==8 and starts==[1000]
    assert project._media_availability['external.mp4']['next_probe_monotonic']==0
    StudioMediaAvailability._apply_checked(owner,project,(7,('external.mp4',)),{'external.mp4':{'status':'missing'}})
    assert not applied
    StudioMediaAvailability._apply_checked(owner,project,(8,('external.mp4',)),{'external.mp4':{'status':'available'}})
    assert len(applied)==1


def test_explicit_same_name_relink_needs_confirmation_when_identity_is_unknown(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    asset=SimpleNamespace(asset_id='a',canonical_source='old/clip.mp4',fingerprint='different',
        duration_ms=3000,video_metadata={'width':640},audio_metadata={'has_audio':True})
    project=SimpleNamespace(media_pool=[asset],video_tracks=[],audio_tracks=[])
    page=SimpleNamespace(project=project)
    owner=SimpleNamespace(page=page,relink_generation=1,cancel_relink=lambda:None)
    questions=[]
    def question(*args):questions.append(args);return QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox,'question',question)
    StudioMediaAvailability.apply_relink(owner,project,'a','old/clip.mp4',1,
        dict(status='available',path='new/clip.mp4',identity=dict(duration_ms=3000,has_video=True,has_audio=True)))
    assert len(questions)==1 and '身份' in questions[0][2]
    assert asset.canonical_source=='old/clip.mp4'
