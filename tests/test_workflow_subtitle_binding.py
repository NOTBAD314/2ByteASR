from pathlib import Path
from twobyteasr.playback.studio_mpv import MpvController, _MpvCommandActor

def controller(tmp_path):
    exe = tmp_path/'mpv.exe'
    exe.touch()
    c = MpvController(executable=exe)
    c.sent = []
    c._send = lambda command: c.sent.append(command) or {}
    c.get_property = lambda name, default=None: {'path':c.current_path,'track-list':[], 'sid':1}.get(name, default)
    c.queued = []
    c._post = lambda fn, **kwargs: c.queued.append(fn) or True
    c.current_path = str((tmp_path/'B.mp4').resolve())
    return c

def deliver(c, event):
    _MpvCommandActor._handle_event(type('Actor',(),{'controller':c})(), {'event':event})
    while c.queued:
        c.queued.pop(0)()

def test_subtitle_waits_for_actual_file_loaded(tmp_path):
    c = controller(tmp_path)
    c.load(c.current_path)
    ass = str(tmp_path/'B.ass')
    c.set_subtitle_file(ass)
    assert not any(cmd[0]=='sub-add' for cmd in c.sent)
    deliver(c,'file-loaded')
    assert [cmd[1] for cmd in c.sent if cmd[0]=='sub-add'] == [str(Path(ass).resolve())]

def test_old_file_loaded_cannot_attach_old_project_after_clear(tmp_path):
    c = controller(tmp_path)
    c.load(c.current_path)
    c.set_subtitle_file(tmp_path/'A.ass')
    _MpvCommandActor._handle_event(type('Actor',(),{'controller':c})(), {'event':'file-loaded'})
    c.clear_media()
    c.current_path = str((tmp_path/'C.mp4').resolve())
    c.load(c.current_path)
    c.set_subtitle_file(tmp_path/'C.ass')
    while c.queued:
        c.queued.pop(0)()
    assert not any(cmd[0]=='sub-add' for cmd in c.sent)
    deliver(c,'file-loaded')
    assert [Path(cmd[1]).name for cmd in c.sent if cmd[0]=='sub-add']==['C.ass']

def test_queued_old_subtitle_cannot_follow_new_load(tmp_path):
    c=controller(tmp_path)
    c.load(c.current_path)
    c.post_subtitle_file(tmp_path/'A.ass')
    old=c.queued.pop()
    c.post_clear_media();c.post_load_at(c.current_path,1.,generation=4)
    while c.queued:c.queued.pop(0)()
    old()
    assert c._desired_subtitle_path==''
    c.post_subtitle_file(tmp_path/'B.ass')
    while c.queued:c.queued.pop(0)()
    deliver(c,'file-loaded')
    assert [Path(cmd[1]).name for cmd in c.sent if cmd[0]=='sub-add']==['B.ass']

def test_same_project_proxy_rebind_keeps_latest_queued_subtitle(tmp_path):
    c=controller(tmp_path)
    c.load(c.current_path)
    c.post_subtitle_file(tmp_path/'latest.ass')
    c.current_path=str((tmp_path/'proxy.mp4').resolve())
    c.post_load_at(c.current_path,1.,generation=5)
    while c.queued:c.queued.pop(0)()
    deliver(c,'file-loaded')
    assert [Path(cmd[1]).name for cmd in c.sent if cmd[0]=='sub-add']==['latest.ass']

def test_same_media_reload_does_not_remove_unloaded_cached_sid(tmp_path):
    from twobyteasr.playback.studio_mpv import MpvCommandError
    c=controller(tmp_path);c._subtitle_media_ready=True
    c._studio_subtitle_sid=1  # A prior file-loaded callback completed during reload.
    def send(command):
        c.sent.append(command)
        if command[0]=='sub-remove':raise MpvCommandError(command,'invalid parameter')
        return {}
    c._send=send  # Current track-list is empty: mpv already unloaded that id.
    c.set_subtitle_file(tmp_path/'new.ass')
    assert [Path(cmd[1]).name for cmd in c.sent if cmd[0]=='sub-add']==['new.ass']
