import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
from dataclasses import asdict
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import (StudioMedia, SubtitleProject, load_project, save_project,
                                      save_autosave_revision, recoverable_autosave)
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip
from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain


def project_fixture():
    project = SubtitleProject(media=StudioMedia(path="base.mp4", duration_ms=2000, width=160, height=90))
    project.validate()
    asset = add_media_asset(project, "overlay.mp4", duration_ms=2000)
    for _ in range(2):
        track = create_video_track(project)
        clip = add_video_clip(project, track.id, asset.asset_id)
        clip.playback_rate = 2.
        clip.timeline_out_ms = 1000
        clip.effects = {"blendMode": "screen", "chromaKey": {"enabled": True}}
    return project


def test_complete_snapshot_survives_mutation_and_roundtrip(tmp_path):
    project = project_fixture()
    store = StudioRevisionStore(project)
    revision = store.refresh_persistence(2)
    expected = revision.to_payload()
    project.video_tracks.pop()
    path, _ = save_autosave_revision(revision, tmp_path / "test.2byteproj", tmp_path, session_id="one")
    restored = load_project(path)
    assert len(restored.video_tracks) == 3
    assert sum(len(x.clips) for x in restored.video_tracks) == 3
    assert [asdict(t) for t in restored.video_tracks] == expected["video_tracks"]
    assert restored.video_tracks[1].clips[0].playback_rate == 2.
    assert restored.video_tracks[1].clips[0].effects["blendMode"] == "screen"


def test_reject_snapshot_inside_transaction_and_undo_preserves_graph(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = project_fixture()
    runtime = state_for(project)
    store = StudioRevisionStore(project)
    with runtime.transaction(project, action_id="test", dirty=DirtyDomain.PROJECT_METADATA):
        with pytest.raises(RuntimeError, match="事务"):
            store.refresh_persistence(2)
        with pytest.raises(RuntimeError, match="事务"):
            save_project(project, tmp_path / "forbidden.2byteproj")
    stack = QUndoStack()
    before = store.refresh_persistence(3).to_payload()["video_tracks"]
    command = media_graph_command(project, "add track", lambda p: create_video_track(p))
    stack.push(command)
    assert len(project.video_tracks) == 4
    stack.undo()
    assert store.refresh_persistence(4).to_payload()["video_tracks"] == before
    stack.redo()
    assert len(project.video_tracks) == 4


def test_late_writer_and_other_instance_cannot_overwrite_new_graph(tmp_path):
    project = project_fixture()
    official = save_project(project, tmp_path / "project.2byteproj")
    store = StudioRevisionStore(project)
    stale = store.refresh_persistence(1)
    create_video_track(project)
    latest = store.refresh_persistence(2)
    newer_path, _ = save_autosave_revision(latest, official, tmp_path, session_id="instance1")
    save_autosave_revision(stale, official, tmp_path, session_id="instance1")
    other_path, _ = save_autosave_revision(stale, official, tmp_path, session_id="instance2")
    assert newer_path != other_path
    assert len(load_project(newer_path).video_tracks) == 4
    assert len(load_project(other_path).video_tracks) == 3
    assert recoverable_autosave(official, tmp_path) is not None


def test_corrupt_and_interrupted_writes_leave_valid_recovery(tmp_path, monkeypatch):
    import twobyteasr.projects.studio_project as model
    project = project_fixture()
    official = save_project(project, tmp_path / "project.2byteproj")
    store = StudioRevisionStore(project)
    path, _ = save_autosave_revision(store.refresh_persistence(1), official, tmp_path, session_id="one")
    saved = path.read_bytes()
    real_replace = model.os.replace
    def killed_write(source, target):
        if target == path:
            raise OSError("injected crash before replace")
        return real_replace(source, target)
    monkeypatch.setattr(model.os, "replace", killed_write)
    with pytest.raises(OSError):
        save_autosave_revision(store.refresh_persistence(2), official, tmp_path, session_id="one")
    assert path.read_bytes() == saved
    monkeypatch.setattr(model.os, "replace", real_replace)
    damaged = json.loads(saved)
    damaged["video_tracks"].pop()
    path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match="校验"):
        load_project(path)
    assert recoverable_autosave(official, tmp_path) is None
    assert len(load_project(official).video_tracks) == 3


def test_killed_writer_keeps_previous_complete_autosave(tmp_path):
    import subprocess, sys, time
    from twobyteasr.system.processes import popen_hidden_subprocess
    project = project_fixture()
    official = save_project(project, tmp_path / "project.2byteproj")
    store = StudioRevisionStore(project)
    target, _ = save_autosave_revision(store.refresh_persistence(1), official, tmp_path, session_id="crash")
    before = target.read_bytes()
    marker = tmp_path / "ready"
    script = tmp_path / "kill_writer.py"
    script.write_text('''import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import twobyteasr.projects.studio_project as model
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.timeline.studio_media_pool import create_video_track
project = model.load_project(sys.argv[2])
create_video_track(project)
def before_replace(source, target):
    Path(sys.argv[4]).write_text("fsynced")
    time.sleep(60)
model.os.replace = before_replace
model.save_autosave_revision(StudioRevisionStore(project).refresh_persistence(2),
                            sys.argv[2], sys.argv[3], session_id="crash")
''', encoding="utf-8")
    process = popen_hidden_subprocess([sys.executable, str(script), str(Path(__file__).resolve().parents[1]),
                                       str(official), str(tmp_path), str(marker)],
                                      purpose="isolated autosave crash injection", stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        assert marker.exists(), process.communicate(timeout=1)[1]
        process.kill()
        process.wait(timeout=3)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stderr.close()
    assert target.read_bytes() == before
    restored = load_project(target)
    assert len(restored.video_tracks) == 3 and sum(len(t.clips) for t in restored.video_tracks) == 3
