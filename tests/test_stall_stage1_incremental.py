"""Edits cost what they change, not the project size (2026-10-22, report-eb10 stage 1).

* Autosave snapshots reuse evidence rows already seen; formal saves and an
  idle check still notice a row changed in place.
* The autosave writer reuses the text of unchanged frozen values: same file
  and fingerprint as encoding the whole payload.
* Caption previews rebuild only changed cues and keep their prepared frames.
* A no-override ASS preview revision skips thawing and re-freezing recipes.
"""
import copy
import os
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import twobyteasr.projects.studio_project as persistence
from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project, project_content_fingerprint,
    save_autosave_revision,
)
from twobyteasr.projects.studio_revisions import StudioRevisionStore, preview_render_revision
from twobyteasr.projects.studio_runtime_state import DirtyDomain as D, StateDelta


def _app():
    return QApplication.instance() or QApplication([])


def _project(count=12):
    cues = [StudioCue(f"c{i}", i * 1000, i * 1000 + 800, f"line {i} “q” \\ é", speaker_id="S01",
                      evidence_refs=[f"seg:{i}"]) for i in range(count)]
    project = SubtitleProject(
        media=StudioMedia(path="", duration_ms=count * 1000),
        cues=cues, speakers=[StudioSpeaker(id="S01", name="One")],
        asr_evidence={f"seg:{i}": {"words": [{"text": "line", "start_ms": i * 1000, "end_ms": i * 1000 + 300,
                                             "p": 0.25}], "engines": {"moss": (1, 2.5, None, True)}}
                      for i in range(count)},
        generation_metadata={"translations": {f"c{i}": f"第{i}句" for i in range(count)},
                             "history": [{"z": 1, "a": []}]},
        studio_state={"bilingual": {"mode": "bilingual"}, "review_risks": [1], "last_opened": "x"},
    )
    project.validate()
    return project


_revision = [10]


def _commit(store, dirty, ids=()):
    _revision[0] += 1
    store.consume(StateDelta("t", dirty | D.AUTOSAVE, frozenset(ids), frozenset(), (), "", "", _revision[0]))


class _Plain:
    """Not a PersistenceRevision: takes the whole-payload writer."""

    def __init__(self, revision):
        self.revision, self.generation = revision, revision.generation

    def to_payload(self):
        return self.revision.to_payload()


# ------------------------------------------------------------------ evidence


def test_evidence_rows_are_reused_by_object_and_by_content():
    project = _project()
    store = StudioRevisionStore(project)
    first = store.refresh_persistence(1).asr_evidence
    assert store.refresh_persistence(2).asr_evidence is first
    # An equal copy (undo restores a deepcopy) keeps the frozen value.
    project.asr_evidence = copy.deepcopy(project.asr_evidence)
    assert store.refresh_persistence(3).asr_evidence is first
    project.asr_evidence["seg:3"] = {"words": [], "text": "replaced"}
    changed = store.refresh_persistence(4).asr_evidence
    assert changed is not first
    assert dict(changed.items)["seg:3"] != dict(first.items)["seg:3"]
    assert dict(changed.items)["seg:4"] is dict(first.items)["seg:4"]


def test_in_place_row_change_is_seen_by_deep_capture_and_idle_check():
    project = _project()
    store = StudioRevisionStore(project)
    first = store.refresh_persistence(1).asr_evidence
    project.asr_evidence["seg:2"]["words"][0]["text"] = "changed in place"
    # Autosave trusts a row object it has seen ...
    assert store.refresh_persistence(2).asr_evidence is first
    # ... a formal save compares every row,
    deep = StudioRevisionStore(project)
    deep.refresh_persistence(1)
    project.asr_evidence["seg:5"]["words"][0]["text"] = "also in place"
    assert dict(deep.refresh_persistence(2, deep=True).asr_evidence.items)["seg:5"] != \
        dict(first.items)["seg:5"]
    # ... and the idle check drops a stale row so the next autosave freezes it.
    assert store.evidence_rows_changed_in_place(["seg:1", "seg:2"]) == ["seg:2"]
    refreshed = store.refresh_persistence(3).asr_evidence
    assert dict(refreshed.items)["seg:2"] != dict(first.items)["seg:2"]
    assert store.evidence_rows_changed_in_place(["seg:2"]) == []


def test_idle_check_schedules_an_autosave_for_a_stale_row():
    from PySide6.QtWidgets import QWidget
    from twobyteasr.projects.evidence_idle_check import EvidenceIdleCheck
    app = _app()
    project = _project()

    class Page(QWidget):
        scheduled = 0

        class undo_stack:
            @staticmethod
            def isClean():
                return False

        def _schedule_autosave(self):
            Page.scheduled += 1

    page = Page()
    page._revision_store = StudioRevisionStore(project)
    page._revision_store.refresh_persistence(1)
    check = EvidenceIdleCheck(page)
    check.INTERVAL_MS = 0
    project.asr_evidence["seg:9"]["words"][0]["p"] = 0.75
    check.start()
    for _ in range(50):
        app.processEvents()
        if not check.running():
            break
    assert check.stale_found == 1 and Page.scheduled == 1


# ------------------------------------------------------------------ autosave text


def test_frozen_writer_matches_payload_writer_across_edits(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(persistence, "_utc_now", lambda: "2026-10-22T00:00:00+00:00")
    project = _project()
    store = StudioRevisionStore(project)
    checkpoint_bytes = None
    for step in range(4):
        if step == 1:
            project.cues[3].text = "edited"
            _commit(store, D.CUE_CONTENT, ["c3"])
        elif step == 2:
            project.cues.pop(5)
            project.asr_evidence["seg:7"] = {"words": [], "text": "new row"}
            del project.asr_evidence["seg:8"]
            _commit(store, D.CUE_MODEL)
        elif step == 3:
            project.studio_state["review_risks"] = [2, 3]
            project.generation_metadata["translations"]["c1"] = "新译文"
        revision = store.refresh_persistence(step + 1)
        old, _ = save_autosave_revision(_Plain(revision), tmp_path / "p.2byteproj", base=tmp_path / "old",
                                        session_id="s1")
        new, phases = save_autosave_revision(revision, tmp_path / "p.2byteproj", base=tmp_path / "new",
                                             session_id="s1")
        overlay = Path(new).with_name(Path(new).name + ".overlay")
        if step == 0:
            # The checkpoint is the old file plus a checkpoint id.
            expected, written = json.loads(Path(old).read_text("utf-8")), json.loads(Path(new).read_text("utf-8"))
            assert written["autosave"].pop("checkpoint_id") and written == expected
            checkpoint_bytes = Path(new).read_bytes()
            assert not overlay.exists()
        else:
            # Later autosaves only write the changes beside it.
            assert Path(new).read_bytes() == checkpoint_bytes and overlay.is_file()
            assert phases["overlay_chars"] < len(checkpoint_bytes)
        assert asdict(load_project(new)) == asdict(load_project(old))
        side_old = persistence.autosave_fingerprint_sidecar(Path(old))
        side_new = persistence.autosave_fingerprint_sidecar(Path(new))
        assert side_new["content_fingerprint"] == side_old["content_fingerprint"]
        assert side_new["content_fingerprint"] == project_content_fingerprint(load_project(new))
        assert side_new["generation"] == step + 1
        if step:
            assert phases["pieces_reused"] > 0


def _autosaved(tmp_path, project, store, generation):
    target, _ = save_autosave_revision(store.refresh_persistence(generation), tmp_path / "p.2byteproj",
                                       base=tmp_path / "data", session_id="s9")
    return Path(target), Path(target).with_name(Path(target).name + ".overlay")


def test_large_change_writes_a_new_checkpoint(tmp_path):
    project = _project()
    store = StudioRevisionStore(project)
    target, overlay = _autosaved(tmp_path, project, store, 1)
    project.cues[0].text = "small"
    _commit(store, D.CUE_CONTENT, ["c0"])
    _autosaved(tmp_path, project, store, 2)
    assert overlay.is_file()
    first = target.read_bytes()
    # Above the 4 MB overlay floor (and an eighth of this small project).
    project.asr_evidence = {key: dict(row, text="x" * 400_000) for key, row in project.asr_evidence.items()}
    _autosaved(tmp_path, project, store, 3)
    assert target.read_bytes() != first and not overlay.exists()
    assert load_project(target).asr_evidence["seg:3"]["text"] == "x" * 400_000


def test_recovery_uses_the_overlay_time_and_content(tmp_path):
    import os
    project = _project()
    official = persistence.save_project(project, tmp_path / "p.2byteproj")
    store = StudioRevisionStore(project)
    target, overlay = _autosaved(tmp_path, project, store, 1)
    project.cues[1].text = "edited after the formal save"
    _commit(store, D.CUE_CONTENT, ["c1"])
    _autosaved(tmp_path, project, store, 2)
    # The formal save lands between checkpoint and overlay.
    base = Path(official).stat().st_mtime_ns
    os.utime(target, ns=(base - 10_000_000, base - 10_000_000))
    os.utime(overlay, ns=(base + 10_000_000, base + 10_000_000))
    sidecar = target.with_name(target.stem + ".fingerprint.json")
    os.utime(sidecar, ns=(base + 20_000_000, base + 20_000_000))
    assert persistence.recoverable_autosave(official, tmp_path / "data") == target
    assert load_project(target).cues[1].text == "edited after the formal save"
    # A sidecar older than the overlay is stale.
    os.utime(sidecar, ns=(base, base))
    assert persistence.autosave_fingerprint_sidecar(target) == {}


def test_stale_overlay_is_ignored_and_discard_removes_everything(tmp_path):
    import json
    project = _project()
    store = StudioRevisionStore(project)
    target, overlay = _autosaved(tmp_path, project, store, 1)
    project.cues[2].text = "overlay text"
    _commit(store, D.CUE_CONTENT, ["c2"])
    _autosaved(tmp_path, project, store, 2)
    assert load_project(target).cues[2].text == "overlay text"
    data = json.loads(overlay.read_text("utf-8"))
    data["base"]["checkpoint_id"] = "someone else"
    overlay.write_text(json.dumps(data), encoding="utf-8")
    assert load_project(target).cues[2].text != "overlay text"
    persistence.discard_autosave(target)
    assert not target.exists() and not overlay.exists()
    assert not target.with_name(target.stem + ".fingerprint.json").exists()


def test_frozen_writer_respects_a_newer_generation_on_disk(tmp_path):
    project = _project()
    store = StudioRevisionStore(project)
    newer = store.refresh_persistence(5)
    target, _ = save_autosave_revision(newer, tmp_path / "p.2byteproj", session_id="s2")
    before = Path(target).read_bytes()
    project.cues[0].text = "older capture"
    _commit(store, D.CUE_CONTENT, ["c0"])
    same, phases = save_autosave_revision(store.refresh_persistence(4), tmp_path / "p.2byteproj", session_id="s2")
    assert same == target and Path(target).read_bytes() == before
    assert phases["persist_ms"] == 0.0


# ------------------------------------------------------------------ captions


def _rows(materialized):
    return [asdict(cue) for cue in materialized.project.cues]


@pytest.mark.parametrize("change,dirty,ids", [
    (lambda p: setattr(p.cues[2], "text", "edited text"), D.CUE_CONTENT, ["c2"]),
    (lambda p: setattr(p.cues[4], "end_ms", p.cues[4].end_ms - 100), D.CUE_TIMING, ["c4"]),
    (lambda p: p.generation_metadata["translations"].__setitem__("c6", "改过的译文"), D.CUE_CONTENT, ["c6"]),
    (lambda p: p.cues.pop(7), D.CUE_MODEL, []),
    (lambda p: p.studio_state.update(playhead_ms=999, zoom=2.0), D.CUE_CONTENT, ["c8"]),
    (lambda p: setattr(p.styles[0], "font_size", p.styles[0].font_size + 4), D.CUE_STYLE, []),
])
def test_incremental_captions_equal_a_full_rebuild(change, dirty, ids):
    from twobyteasr.rendering.caption_playback_cache import materialize_captions
    project = _project()
    store = StudioRevisionStore(project)
    previous, _, _ = materialize_captions(store.render)
    change(project)
    _commit(store, dirty, ids)
    updated, reused, reason = materialize_captions(store.render, previous)
    full, _, _ = materialize_captions(store.render)
    assert _rows(updated) == _rows(full)
    assert updated.project.studio_state == full.project.studio_state
    assert updated.project.generation_metadata == full.project.generation_metadata
    if dirty == D.CUE_STYLE:
        assert not reused
    else:
        # Only the edited cue (and its translation companion) is rebuilt.
        assert len(reused) >= len(full.project.cues) - 2


def test_manual_text_guard_does_not_rebuild_but_receipts_rebuild_their_cue():
    from twobyteasr.rendering.caption_playback_cache import materialize_captions
    project = _project()
    project.studio_state["caption_timeline"] = {"version": 1, "instances": {
        f"c{i}": {"text": f"line {i}", "words": [{"text": "line", "start_ms": i * 1000, "end_ms": i * 1000 + 300}]}
        for i in range(12)}}
    store = StudioRevisionStore(project)
    previous, _, _ = materialize_captions(store.render)
    # A user text edit also records the manual text guard (no caption reads it).
    project.cues[2].text = "user edit"
    project.studio_state.setdefault("manual_caption_text", {})["c2"] = "user edit"
    _commit(store, D.CUE_CONTENT, ["c2"])
    updated, reused, reason = materialize_captions(store.render, previous)
    assert reason == "" and len(reused) >= len(updated.project.cues) - 2
    # A word re-timing changes one receipt: only that cue is rebuilt.
    project.studio_state["caption_timeline"]["instances"]["c5"]["words"][0]["end_ms"] += 50
    _commit(store, D.CUE_CONTENT, ["c5"])
    again, reused, reason = materialize_captions(store.render, updated)
    assert reason == ""
    assert "c5" not in reused and "c4" in reused
    assert _rows(again) == _rows(materialize_captions(store.render)[0])
    # Anything else in the caption timeline still rebuilds everything.
    project.studio_state["caption_timeline"]["version"] = 2
    _commit(store, D.CUE_CONTENT, ["c6"])
    _final, reused, reason = materialize_captions(store.render, again)
    assert reason == "studio_state:caption_timeline" and not reused


def test_style_recipe_and_effect_edits_rebuild_only_their_cues():
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    from twobyteasr.projects.studio_project import SubtitleStyle
    from twobyteasr.rendering.caption_playback_cache import materialize_captions
    project = _project()
    project.styles.append(SubtitleStyle("alt", "Alt", font_size=40))
    for cue in project.cues[3:5]:
        cue.style_id = "alt"
    project.style_recipes["alt"] = StyleRecipe(name="Alt", typography={"fontSize": 40}).to_dict()
    project.cues[6].effect_id = "fade"
    project.validate()
    store = StudioRevisionStore(project)
    current, _, _ = materialize_captions(store.render)

    def step(change, expect_rebuilt, expect_reason=""):
        nonlocal current
        change()
        _commit(store, D.CUE_STYLE)
        updated, reused, reason = materialize_captions(store.render, current)
        assert reason == expect_reason
        assert _rows(updated) == _rows(materialize_captions(store.render)[0])
        rebuilt = {cue.id for cue in updated.project.cues} - set(reused)
        assert rebuilt == expect_rebuilt
        current = updated

    alt = {"c3", "c3#tr", "c4", "c4#tr"}
    step(lambda: setattr(project.styles[-1], "font_size", 52), alt)
    step(lambda: project.style_recipes["alt"]["typography"].__setitem__("fontSize", 52), alt)
    # Same display cues, different motion: only the prepared frames go.
    step(lambda: project.effects["fade"]["entry"].__setitem__("duration", 400), {"c6", "c6#tr"})
    # The default style is everyone's fallback.
    everyone = {cue.id for cue in current.project.cues}
    step(lambda: setattr(project.styles[0], "font_size", project.styles[0].font_size + 1), everyone,
         "default_style")


def test_speaker_names_layout_always_rebuilds():
    from twobyteasr.caption_style.speaker_names import KEY
    from twobyteasr.rendering.caption_playback_cache import materialize_captions
    project = _project()
    project.studio_state[KEY] = True
    store = StudioRevisionStore(project)
    previous, _, _ = materialize_captions(store.render)
    project.cues[1].text = "named"
    _commit(store, D.CUE_CONTENT, ["c1"])
    updated, reused, reason = materialize_captions(store.render, previous)
    assert not reused
    assert _rows(updated) == _rows(materialize_captions(store.render)[0])


def test_split_or_delete_keeps_unchanged_cue_dtos():
    project = _project()
    store = StudioRevisionStore(project)
    before = {dto.id: dto for dto in store.render.cues}
    project.cues.insert(3, StudioCue("new", 3500, 3700, "inserted", speaker_id="S01"))
    project.cues.pop(8)
    _commit(store, D.CUE_MODEL)
    after = {dto.id: dto for dto in store.render.cues}
    assert all(after[key] is before[key] for key in after if key in before)
    assert "new" in after and "c7" not in after


def test_cache_keeps_prepared_frames_of_unchanged_cues():
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache, revision_key
    app = _app()
    project = _project()
    store = StudioRevisionStore(project)
    cache = PlaybackCaptionCache()
    ready = []
    cache.ready.connect(lambda key, ids: ready.append((key, ids)))

    def prepare(ids):
        ready.clear()
        cache.prepare(store.render, ids, 1280, 720)
        for _ in range(400):
            app.processEvents()
            if ready:
                break
            __import__("time").sleep(0.01)
        return ready[-1]

    first_key, _ids = prepare(("c0", "c1"))
    frame = cache.prepared(store.render, "c1", 1280, 720)
    assert frame is not None
    project.cues[0].text = "edited"
    _commit(store, D.CUE_CONTENT, ["c0"])
    key, ids = prepare(("c0", "c1"))
    assert key == revision_key(store.render, 1280, 720) != first_key
    assert {"c0", "c1"} <= set(ids)       # the carried frame is announced too
    assert cache.prepared(store.render, "c1", 1280, 720) is frame
    assert cache.prepared(store.render, "c0", 1280, 720).snapshot.text != frame.snapshot.text
    cache.close()


# ------------------------------------------------------------------ ASS preview


def test_preview_revision_without_overrides_only_drops_hidden_cues():
    project = _project()
    revision = StudioRevisionStore(project).render
    hidden = {"c1", "c4"}
    fast = preview_render_revision(revision, hidden_cue_ids=hidden)
    slow = preview_render_revision(revision, text_overrides={"zz-none": "x"}, hidden_cue_ids=hidden)
    assert [cue.id for cue in fast.cues] == [cue.id for cue in slow.cues]
    assert fast.style_recipes == slow.style_recipes and fast.styles == slow.styles
    assert fast.preview_key and fast.preview_key != slow.preview_key
    assert preview_render_revision(revision).preview_key == ""
    assert preview_render_revision(revision).cues is revision.cues


# ------------------------------------------------------------------ formal save and open


def _old_formal_text(revision):
    """The 0.8.2 writer: from_dict, persist_sequence, asdict, json.dumps(indent=2)."""
    import json
    from twobyteasr.timeline.studio_edit_sequence import persist_sequence
    detached = SubtitleProject.from_dict(revision.to_payload())
    persist_sequence(detached)
    payload = asdict(detached)
    payload["studio_state"].pop("review_risks", None)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_formal_save_writes_the_same_bytes_and_reuses_row_text(tmp_path):
    project = _project()
    project.asr_evidence["tuple-row"] = {"pair": (1, 2), 3: "int key"}   # not plain JSON
    project.edit_history = [{"a": 1}, "not a mapping"]
    store = StudioRevisionStore(project)
    target = tmp_path / "formal.2byteproj"
    for step in range(3):
        if step == 1:
            project.cues[2].text = "formal edit"
            _commit(store, D.CUE_CONTENT, ["c2"])
        elif step == 2:
            project.asr_evidence["seg:4"] = {"words": [], "text": "replaced"}
            project.studio_state["review_risks"] = [1]
        revision = store.refresh_persistence(step + 1, deep=True)
        persistence.save_project_revision(revision, target)
        assert target.read_text("utf-8") == _old_formal_text(revision)
    cache = persistence._FORMAL_TEXT_CACHES[str(target)]
    assert cache.reused > 0


def test_owned_load_equals_a_copying_load(tmp_path):
    import json
    project = _project()
    path = persistence.save_project(project, tmp_path / "p.2byteproj")
    loaded = load_project(path)
    copied = SubtitleProject.from_dict(json.loads(path.read_text("utf-8")))
    assert asdict(loaded) == asdict(copied)


def test_frozen_blob_thaws_like_a_frozen_tree():
    from twobyteasr.projects.studio_revisions import FrozenBlob, freeze_json, thaw_json
    for value in ({"a": [1, {"b": None}], "c": "é"}, {"t": (1, (2, 3))}, {1: "x", "2": [()]}, [1.5, True]):
        blob = FrozenBlob.capture(value)
        assert thaw_json(blob) == thaw_json(freeze_json(value))
    assert FrozenBlob.capture({"a": [1]}).plain is None     # checked when thawed, not on the GUI thread
    with pytest.raises(TypeError):
        thaw_json(FrozenBlob.capture({"a": {1, 2}}))


def test_builtin_effects_are_validated_once_and_copied():
    from twobyteasr.caption_style import effect_dsl
    first = effect_dsl.builtin_effects()
    first["fade"]["entry"]["duration"] = 9999
    assert effect_dsl.builtin_effects()["fade"]["entry"]["duration"] != 9999
    assert effect_dsl.builtin_effects() == effect_dsl._validated_builtin_effects()


def test_process_tree_from_one_snapshot():
    from twobyteasr.diagnostics import process_diagnostics as pd

    class FakePsutil:
        Error = Exception

        @staticmethod
        def _ppid_map():
            return {1: 0, 2: 1, 3: 2, 4: 1, 5: 9, 0: 0}

        class Process:
            def __init__(self, pid):
                self.pid = pid

    tree = pd._process_tree(FakePsutil)
    assert sorted(p.pid for p in pd._descendants(FakePsutil, tree, 1)) == [2, 3, 4]
    assert pd._descendants(FakePsutil, tree, 5) == []


# ------------------------------------------------------------------ stage 2: undo keeps changes only


def test_speaker_commands_store_only_changed_cues():
    from twobyteasr.timeline.studio_commands import AssignSpeakerCommand, SetSpeakerCommand
    project = _project()
    project.speakers.append(StudioSpeaker(id="S02", name="Two"))
    project.validate()
    original = [asdict(cue) for cue in project.cues]
    assign = AssignSpeakerCommand(project, ["c1", "c2"], "S02")
    assert set(assign._before_cues) == set(assign._after_cues) == {"c1", "c2"}
    assign.redo()
    assert [cue.speaker_id for cue in project.cues[:4]] == ["S01", "S02", "S02", "S01"]
    untouched = project.cues[5]
    rename = SetSpeakerCommand(project, "S02", {"name": "Renamed"})
    assert rename._before_cues == rename._after_cues == {}
    rename.redo()
    assert project.cues[5] is untouched          # unchanged cues are not replaced
    rename.undo()
    assign.undo()
    assert [asdict(cue) for cue in project.cues] == original
    assert [s.name for s in project.speakers] == ["One", "Two"]
    assert [cue.speaker_id for cue in assign.after_cues[:3]] == ["S01", "S02", "S02"]
    # An unchanged cue removed outside the undo stack cannot be restored silently.
    project.cues.pop(7)
    with pytest.raises(ValueError):
        assign.redo()


# ------------------------------------------------------------------ stage 3: full rebuilds in a worker process


def test_large_full_rebuilds_run_in_a_worker_process(monkeypatch):
    from twobyteasr.rendering.caption_playback_cache import (PlaybackCaptionCache, materialize_captions,
                                                             revision_key)
    app = _app()
    project = _project(30)
    store = StudioRevisionStore(project)
    cache = PlaybackCaptionCache()
    monkeypatch.setattr(cache, "DISPLAY_PROCESS_MIN_CUES", 10)
    ready = []
    cache.ready.connect(lambda key, ids: ready.append(key))
    try:
        cache.prepare(store.render, ("c0", "c1"), 1280, 720)
        deadline = __import__("time").monotonic() + 90
        while not ready and __import__("time").monotonic() < deadline:
            app.processEvents()
            __import__("time").sleep(0.02)
        assert ready and ready[-1] == revision_key(store.render, 1280, 720)
        from twobyteasr.system.resident_worker import shared_worker
        worker = shared_worker()
        assert cache.worker_builds == 1 and worker.calls >= 1 and not worker.failures
        local = materialize_captions(store.render)[0]
        assert _rows(cache._materialized) == _rows(local)
    finally:
        cache.close()


def test_resident_worker_runs_jobs_and_refuses_others():
    from twobyteasr.system.resident_worker import ResidentWorker
    worker = ResidentWorker("test-worker")
    try:
        assert worker.call("twobyteasr.projects.frozen_json_text:dump", {"b": 1, "a": [2]}) == '{"a":[2],"b":1}'
        assert worker.call("os:getcwd", None) is None and "not a 2ByteASR job" in worker.failures[-1]
        assert worker.call("twobyteasr.projects.frozen_json_text:no_such", None) is None
        assert worker.running
    finally:
        worker.close()
    assert not worker.running and worker.call("twobyteasr.projects.frozen_json_text:dump", 1) is None


def test_small_projects_and_the_switch_stay_in_process(monkeypatch):
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache
    project = _project(12)
    revision = StudioRevisionStore(project).render
    cache = PlaybackCaptionCache()
    assert cache._full_builder(revision) is None
    monkeypatch.setattr(cache, "DISPLAY_PROCESS_MIN_CUES", 1)
    monkeypatch.setenv("TWOBYTEASR_CAPTION_DISPLAY_PROCESS", "0")
    assert cache._full_builder(revision) is None
    from twobyteasr.system.resident_worker import shared_worker
    monkeypatch.setenv("TWOBYTEASR_RESIDENT_WORKER", "0")
    assert shared_worker() is None
    cache.close()


def test_first_save_encodes_rows_in_the_worker():
    from twobyteasr.projects.frozen_json_text import FrozenTextCache, dump, pretty
    from twobyteasr.projects.studio_revisions import FrozenBlob, thaw_json
    blobs = [FrozenBlob.capture({"i": i, "w": [{"t": "字", "s": i * 10}], "tuple": (i,)}) for i in range(40)]
    for encoder in (dump, pretty):
        cache = FrozenTextCache(encoder)
        assert cache.prefetch(blobs, minimum=10) == 40
        assert all(cache.known(blob) for blob in blobs)
        assert [cache.frozen(blob) for blob in blobs] == [encoder(thaw_json(blob)) for blob in blobs]
        assert cache.prefetch(blobs, minimum=10) == 0      # nothing missing any more
    assert FrozenTextCache().prefetch(blobs[:5], minimum=10) == 0
