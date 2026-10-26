from types import SimpleNamespace
from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin

def owner(monkeypatch):
    import twobyteasr.rendering.caption_scene as scene_module
    monkeypatch.setattr(scene_module,'active_cues',lambda page,ms:())
    calls=[]
    page=SimpleNamespace(project=object(),isVisible=lambda:True,
        _caption_tick_time_ms=10,_caption_sample_ms=lambda *args:10,
        _caption_scene=SimpleNamespace(present=lambda cues,ms:(calls.append(ms) or True)),
        _revision_store=SimpleNamespace(render=SimpleNamespace(visual_revision=1,mapping_revision=1)))
    page._present_caption_scene=lambda:StudioAdvancedFlowMixin._present_caption_scene(page)
    return page,calls

def test_caption_sample_decorator_alone_never_retains_scene_submission(monkeypatch):
    page,calls=owner(monkeypatch)
    page._present_caption_scene();page._present_caption_scene()
    assert calls==[10,10]

def test_playhead_transaction_deduplicates_and_releases_after_return(monkeypatch):
    page,calls=owner(monkeypatch)
    page._apply_project_playhead_frame=lambda *args,**kw:(page._present_caption_scene(),page._present_caption_scene())
    StudioPlaybackFlowMixin._apply_project_playhead(page,10)
    assert calls==[10]
    assert page._caption_playhead_sample is None
    page._present_caption_scene()
    assert calls==[10,10]

def test_project_or_revision_change_rejects_old_transaction_result(monkeypatch):
    page,calls=owner(monkeypatch);page._caption_playhead_sample={}
    page._present_caption_scene();page._present_caption_scene()
    page.project=object();page._present_caption_scene()
    page._revision_store.render.visual_revision+=1;page._present_caption_scene()
    assert len(calls)==3

def test_exception_releases_transaction(monkeypatch):
    import pytest
    page,calls=owner(monkeypatch)
    def fail(*args,**kw):page._present_caption_scene();raise ValueError('abort')
    page._apply_project_playhead_frame=fail
    with pytest.raises(ValueError):StudioPlaybackFlowMixin._apply_project_playhead(page,10)
    assert page._caption_playhead_sample is None
