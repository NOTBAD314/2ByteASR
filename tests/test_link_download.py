import json
import sys
import threading
import time
from pathlib import Path
import pytest
from twobyteasr.media import link_download as ld
from twobyteasr.media.link_tools import DownloadCancelled
from twobyteasr.media.link_queue import DownloadQueue
from twobyteasr.media.link_manifest import atomic_json


def test_subprocess_ignores_external_config_plugins_and_never_transcodes():
    args=ld.base_arguments(dict(ytdlp="managed.exe",node="node.exe",ffmpeg="ffmpeg.exe"))
    assert "--ignore-config" in args and "--no-plugin-dirs" in args
    assert "--no-playlist" in args and "--no-remote-components" in args
    assert "--recode-video" not in args and "--download-sections" not in args


def test_errors_are_classified_and_credentials_redacted():
    assert ld.classify_error("HTTP Error 429").category=="rate_limit"
    assert ld.classify_error("Sign in to confirm").category=="login"
    assert ld.classify_error("Connection timed out").category=="network"
    text=ld.redact("GET https://user:password@x.test/a?sig=secret Cookie: auth=private")
    assert "private" not in text and "secret" not in text and "password@" not in text


def test_switch_to_video_only_discards_previous_subtitle_selection(tmp_path):
    catalog=dict(video_id="BaW_jenozKc",url="https://www.youtube.com/watch?v=BaW_jenozKc",
                 title="Video",tracks=[dict(track_id="en")])
    task=ld.make_task(catalog,str(tmp_path),mode="video",track_ids=["en"],primary_track_id="en")
    assert task["track_ids"]==[] and task["primary_track_id"]==""


def test_silent_subprocess_cancel_reaps_child(tmp_path, monkeypatch):
    script=tmp_path/"silent.py"
    script.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(ld,"base_arguments",lambda tools:[sys.executable,str(script)])
    # Guard all mutable data used by run_ytdlp.
    import twobyteasr.runtime_paths as rp
    monkeypatch.setattr(rp,"get_runtime_paths",lambda: type("Paths",(),{"user_data_root":tmp_path})())
    cancel=threading.Event()
    threading.Timer(.25,cancel.set).start()
    start=time.monotonic()
    with pytest.raises(DownloadCancelled):
        ld.run_ytdlp(dict(ytdlp=sys.executable),[],cancel=cancel.is_set)
    assert time.monotonic()-start < 5
    assert not list((tmp_path/"cache/link-download").glob("request-*"))


def test_progress_coalesces_and_drops_signed_info_fields(tmp_path,monkeypatch):
    script=tmp_path/"events.py"
    script.write_text('import json\nprint("2BYTE_PROGRESS:"+json.dumps({"downloaded_bytes":10,"info_dict":{"url":"secret"}}))\nprint("done")\n')
    monkeypatch.setattr(ld,"base_arguments",lambda tools:[sys.executable,str(script)])
    import twobyteasr.runtime_paths as rp
    monkeypatch.setattr(rp,"get_runtime_paths",lambda: type("Paths",(),{"user_data_root":tmp_path})())
    events=[]
    output,_=ld.run_ytdlp(dict(ytdlp=sys.executable),[],notify=events.append)
    assert output.strip()=="done"
    assert events[0]["progress"]=={"downloaded_bytes":10}


class FakeEngine:
    def __init__(self):
        self.started=threading.Event()
        self.order=[]
        self.retry_modes=[]

    def download(self,task,*,cancel,notify,subtitles_only=False,**secrets):
        self.order.append(task["task_id"]);self.retry_modes.append(subtitles_only)
        self.started.set()
        for n in range(20):
            if cancel():
                raise DownloadCancelled()
            notify(dict(stage="downloading",progress={"downloaded_bytes":n}))
            time.sleep(.005)
        path=Path(task["directory"])/"download.2byte-download.json"
        atomic_json(path,dict(version=1,task_id=task["task_id"],video_id="BaW_jenozKc",media=None,subtitles=[]))
        return str(path)


def wait_until(predicate):
    deadline=time.monotonic()+4
    while not predicate():
        assert time.monotonic()<deadline
        time.sleep(.01)


def test_queue_serial_persistent_no_credentials_and_retry_scope(tmp_path):
    engine=FakeEngine()
    storage=tmp_path/"queue.json"
    queue=DownloadQueue(storage,engine)
    try:
        for n in ("one","two"):
            queue.add(dict(task_id=n,directory=str(tmp_path/n),state="queued",auto_import=True,target={"project_id":"a"}),
                      proxy="https://user:secret@example.com",cookie_file="private.txt")
        wait_until(lambda: all(t["state"]=="pending_import" for t in queue.snapshots()))
        assert engine.order==["one","two"]
        assert len(queue.events())<=2
        saved=storage.read_text()
        assert "secret" not in saved and "private.txt" not in saved
        queue.retry("one",subtitles_only=True)
        wait_until(lambda: len(engine.order)==3 and queue.snapshots()[0]["state"]=="pending_import")
        assert engine.retry_modes==[False,False,True]
    finally:
        queue.close()
    reopened=DownloadQueue(storage,FakeEngine())
    try:
        assert all(not t["auto_import"] and not t["target"] for t in reopened.snapshots())
    finally:
        reopened.close()


def test_queue_cancel_does_not_start_next_after_close(tmp_path):
    engine=FakeEngine()
    queue=DownloadQueue(tmp_path/"queue.json",engine)
    for n in ("one","two"):
        queue.add(dict(task_id=n,directory=str(tmp_path/n),state="queued"))
    assert engine.started.wait(2)
    queue.close()
    assert engine.order==["one"]
    assert not queue._thread.is_alive()
    assert queue.snapshots()[1]["state"]=="paused"


def test_cancel_during_final_verification_never_publishes_auto_import(tmp_path):
    queue=DownloadQueue(tmp_path/"queue.json",FakeEngine())
    def prepare(path):
        queue.cancel("one")
        return {"manifest":{}, "media_path":""}
    queue._prepare_bundle=prepare
    try:
        queue.add(dict(task_id="one",directory=str(tmp_path/"one"),state="queued",auto_import=True))
        wait_until(lambda:queue.snapshots()[0]["state"]=="cancelled")
        terminal=[e for e in queue.events() if e.get("terminal")]
        assert len(terminal)==1 and terminal[0]["state"]=="cancelled"
    finally:
        queue.close()


def test_actual_postprocessed_filename_and_partial_subtitle_failure(tmp_path,monkeypatch):
    from twobyteasr.media.link_catalog import subtitle_tracks
    cat=dict(video_id="BaW_jenozKc",url="https://www.youtube.com/watch?v=BaW_jenozKc",title="同名视频",
             formats=[dict(format_id="video")],
             tracks=subtitle_tracks(dict(id="BaW_jenozKc",subtitles={"en":[
                 dict(ext="json3",url="https://youtube.com/api/timedtext?lang=en&sig=expires")]})))
    task=ld.make_task(cat,str(tmp_path),video_format="video",track_ids=[cat["tracks"][0]["track_id"]],
                     primary_track_id=cat["tracks"][0]["track_id"])
    root=Path(task["directory"]);root.mkdir(parents=True)
    actual=root/"中文 日本語 renamed.mkv";actual.write_bytes(b"verified-video")
    def run(*args,**kwargs):
        return '2BYTE_FILE:'+json.dumps(str(actual))+'\n',[]
    monkeypatch.setattr(ld,"run_ytdlp",run)
    engine=ld.DownloadEngine(tools={"versions":{"yt_dlp":"test"}})
    calls=[]
    def analyze(*a,**k):
        calls.append(1);return cat
    engine.analyze=analyze
    engine._subtitle_bytes=lambda *a,**k: (_ for _ in ()).throw(ValueError("invalid subtitle"))
    manifest=Path(engine.download(task))
    data=json.loads(manifest.read_text(encoding="utf-8"))
    assert data["status"]=="partial"
    assert data["media"]["path"]==actual.name
    assert data["errors"][0]["category"]=="parse"
    assert len(calls)==2  # Re-extract before retrying expired subtitle endpoints.
    assert "expires" not in manifest.read_text()


@pytest.mark.parametrize("source",["manual","automatic"])
def test_same_language_download_uses_selected_source_endpoint(tmp_path,source):
    from twobyteasr.media.link_catalog import subtitle_tracks
    from twobyteasr.media.link_manifest import load_bundle
    entry=lambda kind:dict(ext="json3",url="https://youtube.com/api/timedtext?lang=en&kind="+kind)
    tracks=subtitle_tracks(dict(id="BaW_jenozKc",subtitles={"en":[entry("")]},
        automatic_captions={"en":[entry("asr")]}))
    selected=next(t for t in tracks if t["source"]==source)
    catalog=dict(video_id="BaW_jenozKc",url="https://www.youtube.com/watch?v=BaW_jenozKc",
                 title="Same language",tracks=tracks,formats=[])
    task=ld.make_task(catalog,str(tmp_path),mode="subtitles",track_ids=[selected["track_id"]],
                     primary_track_id=selected["track_id"])
    engine=ld.DownloadEngine(tools={"versions":{"yt_dlp":"offline"}})
    engine.analyze=lambda *a,**k:catalog
    def fetch(representation,**options):
        text="automatic words" if "kind=asr" in representation["url"] else "manual words"
        return json.dumps(dict(events=[dict(tStartMs=0,dDurationMs=1000,segs=[dict(utf8=text)])])).encode()
    engine._subtitle_bytes=fetch
    result=load_bundle(Path(engine.download(task)))
    assert len(result["manifest"]["subtitles"])==1
    assert result["captions"][selected["track_id"]]["captions"][0]["text"]==source+" words"
