"""Recover only the damaged derived cache; preserve project and media bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def media(tmp_path):
    ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    target=tmp_path/'sample.mp4'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=10:d=2',
        '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-preset','ultrafast',
        '-c:a','aac','-shortest',str(target)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return target,ffmpeg


def test_truncated_float_cache_is_rebuilt_instead_of_accepted(media,tmp_path):
    from twobyteasr.playback.waveform_cache import generate_waveform_cache,WaveformCache
    target,ffmpeg=media
    source_hash=hashlib.sha256(target.read_bytes()).hexdigest()
    root=tmp_path/'cache'
    unrelated=root/'unrelated'
    unrelated.mkdir(parents=True)
    marker=unrelated/'keep.bin'
    marker.write_bytes(b'keep unrelated cache')
    cache=generate_waveform_cache(target,ffmpeg,cache_root=root)
    metadata=json.loads((cache/'metadata.json').read_text('utf8'))
    broken=cache/metadata['levels'][0]['file']
    broken.write_bytes(b'\0')
    rebuilt=generate_waveform_cache(target,ffmpeg,cache_root=root)
    assert rebuilt==cache
    assert broken.stat().st_size>1
    reader=WaveformCache(cache)
    _,pairs=reader.read_window(0,1500,100)
    assert len(pairs)>0 and pairs.shape[1]==2
    assert marker.read_bytes()==b'keep unrelated cache'
    assert hashlib.sha256(target.read_bytes()).hexdigest()==source_hash


def test_large_invalid_cover_is_regenerated_and_failure_leaves_placeholder(media,tmp_path,monkeypatch):
    from PySide6.QtGui import QImage
    from twobyteasr.projects import studio_project_controller as module
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    target,_=media
    project=SubtitleProject(StudioMedia(str(target),duration_ms=2000))
    path=tmp_path/'project.2byteproj'
    save_project(project,path)
    before=path.read_bytes()
    cover=tmp_path/'preview/project-cover.jpg'
    cover.parent.mkdir(exist_ok=True)
    cover.write_bytes(b'broken jpeg'*300)
    result=module.StudioProjectController._ensure_project_cover(None,path,project)
    assert result==cover and not QImage(str(cover)).isNull()
    assert path.read_bytes()==before
    cover.write_bytes(b'broken again'*300)
    monkeypatch.setattr(module,'run_hidden_subprocess',lambda *a,**kw:SimpleNamespace(returncode=-22,stderr=b'controlled failure'))
    assert module.StudioProjectController._ensure_project_cover(None,path,project) is None
    assert path.read_bytes()==before and cover.read_bytes()==b'broken again'*300


def test_failed_cover_decode_queues_one_repair_for_that_version():
    from PySide6.QtGui import QImage
    from twobyteasr.studio.studio_hub import StudioHubMixin
    key=('fixture-cover.jpg',320,180)
    label=SimpleNamespace(_library_cover_record={'path':'fixture.2byteproj','cover_mtime_ns':3,'cover_size':9000})
    requests=[]
    page=SimpleNamespace(_library_cover_labels={key:[label]},_library_cover_queued={key},
        _queue_project_cover_backfill=lambda r:requests.append(r))
    StudioHubMixin._on_library_cover_ready(page,*key,QImage())
    page._library_cover_labels[key]=[label]
    StudioHubMixin._on_library_cover_ready(page,*key,QImage())
    assert len(requests)==1
