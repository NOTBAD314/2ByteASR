import time
from collections import OrderedDict
from types import SimpleNamespace
from PySide6.QtGui import QImage, QColor
from twobyteasr.rendering.caption_scene import WebSceneCache


def test_seek_discards_queued_old_frames_but_retains_visible_peers():
    cache=WebSceneCache(lambda: None)
    cache.pending=OrderedDict([('old',None),('speaker-a',None),('speaker-b',None)])
    cache.retain(('speaker-a','speaker-b'))
    assert tuple(cache.pending)==('speaker-a','speaker-b')
    cache.retain(())
    assert not cache.pending
    cache.close()


def test_one_cue_binds_text_once_while_frames_follow_project_time(tmp_path,monkeypatch):
    from twobyteasr.rendering import renderer_service
    image=QImage(2,2,QImage.Format_ARGB32);image.fill(QColor('red'))
    path=tmp_path/'pixel.png';image.save(str(path));png=path.read_bytes()
    calls=[]
    class Service:
        def __init__(self,*args):pass
        def live_set(self,*args,**kwargs):calls.append(('set',None))
        def live_text(self,**kwargs):calls.append(('text',kwargs['text']))
        def live_frame(self,**kwargs):calls.append(('frame',kwargs['cue_ms']));return png
        def close(self):pass
    monkeypatch.setattr(renderer_service,'LiveRendererSession',Service)
    cache=WebSceneCache(lambda: None)
    web=SimpleNamespace(theme_key='theme',strip_key='cue-a',html='<p>text</p>',text='正文',speaker='玩家',duration=1,placement={})
    cache.retain(('a',))
    try:
        for at in (0,50,125):
            cache.get('a',web,at,1000+at,2,2)
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and ('a' not in cache.images or cache.images['a'][1]!=at):time.sleep(.005)
            assert cache.images['a'][1]==at
        assert calls==[('set',None),('text','正文'),('frame',0),('frame',50),('frame',125)]
    finally:cache.close()
