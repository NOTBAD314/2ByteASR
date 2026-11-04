from PySide6.QtGui import QImage, QColor

from twobyteasr.rendering.caption_disk_cache import CaptionDiskCache
from twobyteasr.rendering.caption_scene import CaptionScene


def pixels():
    image=QImage(160,90,QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#b040d0'))
    return image


def test_disk_cache_reopens_pixels_and_evicts_without_invalidating_borrower(tmp_path):
    cache=CaptionDiskCache(tmp_path,max_entries=1)
    first=cache.key(('font-a',123,'text-a'));second=cache.key(('font-a',123,'text-b'))
    image=pixels();rows=[dict(cue_id='a',status='rendered',bounds=[0,0,160,90])]
    assert cache.get(first) is None
    cache.put(first,image,rows)
    reopened=CaptionDiskCache(tmp_path,max_entries=1)
    held,restored=reopened.get(first)
    assert bytes(held.constBits())==bytes(image.constBits()) and restored==rows
    reopened.put(second,image,[dict(cue_id='b',status='rendered')])
    assert reopened.stats()['entries']==1 and reopened.stats()['evictions']==1
    assert bytes(held.constBits())==bytes(image.constBits())
    assert reopened.get(first) is None and reopened.get(second) is not None


def test_bad_cache_and_too_large_entry_are_misses_without_disrupting_render(tmp_path):
    cache=CaptionDiskCache(tmp_path,max_bytes=1)
    key=cache.key('x');cache.put(key,pixels(),[])
    assert cache.get(key) is None and not list(tmp_path.iterdir())
    cache=CaptionDiskCache(tmp_path)
    cache.put(key,pixels(),[])
    (tmp_path/(key+'.json')).write_text('{broken','utf8')
    assert cache.get(key) is None and cache.stats()['errors']==1


def token(revision=1,generation=1,content='text-font-style-a',size=(640,360,False,None)):
    return ('project',1,revision,generation,('cue-a',),('content-v1',(('cue-a',content,('font.ttf',0,10,20),'None'),)),size,0,0,640,360)


def test_other_cue_edits_and_seek_keep_pixels_but_changed_dependencies_do_not():
    key=CaptionScene.frame_key(token())
    assert key==CaptionScene.frame_key(token(revision=2,generation=30))
    assert key!=CaptionScene.frame_key(token(content='text-font-style-b'))
    assert key!=CaptionScene.frame_key(token(size=(1280,720,False,None)))
    assert CaptionDiskCache.key(key)!=CaptionDiskCache.key((*key,'font-replaced'))


def test_range_preparation_covers_overlap_starts_and_ends():
    from types import SimpleNamespace as NS
    from twobyteasr.studio.caption_range_preparation import preparation_times
    cues=[NS(start_ms=0,end_ms=1000),NS(start_ms=500,end_ms=1500)]
    times=preparation_times(cues,0,1500)
    assert times==[80,580,1080]
    assert [tuple(i for i,c in enumerate(cues) if c.start_ms<=t<c.end_ms) for t in times]==[(0,),(0,1),(1,)]


def test_range_preparation_yields_before_seek_advances_playback_generation():
    from types import SimpleNamespace as NS
    from twobyteasr.studio.caption_range_preparation import CaptionRangePreparation
    project=object()
    page=NS(project=project,_revision_store=NS(render=NS(visual_revision=1)),
            _caption_seek_preparation=NS(pending={'phase':'prepare'}))
    task=NS(page=page,project=project,active=True,revision=1,index=0)
    # Video/cache access is absent: pending foreground work owns this turn.
    CaptionRangePreparation.tick(task)
    assert task.index==0 and task.active


def test_animated_frames_retain_mapping_revision_even_when_pixels_are_unchanged(monkeypatch):
    from fractions import Fraction
    from types import SimpleNamespace as NS
    import twobyteasr.timeline.caption_frame_time as timing
    monkeypatch.setattr(timing,'project_frame_rate',lambda project:Fraction(30))
    scene=NS(project=object(),frame_key=CaptionScene.frame_key)
    before=token();after=(before[0],2,*before[2:])
    prepared=[('cue-a',NS(snapshot_hash='same-content'))]
    assert CaptionScene.frame_key(before)==CaptionScene.frame_key(after)
    assert CaptionScene.animation_key(scene,before,prepared,1500)!=CaptionScene.animation_key(scene,after,prepared,1500)
