"""Freezing studio_state reuses unchanged caption receipts, with equal results.

One Q/W edit used to re-freeze every caption receipt (and its word list) for
the render revision and again for each autosave capture.
"""
from __future__ import annotations

import copy
import random

from twobyteasr.studio_caption_timeline import KEY
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_revisions import StudioRevisionStore, freeze_json


def _project(count=300):
    project = SubtitleProject(
        media=StudioMedia(path="D:/missing.mp4", duration_ms=count * 2000 + 5000),
        speakers=[StudioSpeaker(id="S01", name="主播")],
        cues=[StudioCue(f"c{i}", i * 2000, i * 2000 + 1500, f"第{i}句字幕", speaker_id="S01")
              for i in range(count)])
    project.studio_state = {
        KEY: {"version": 1, "instances": {
            f"c{i}": {"text": f"第{i}句字幕", "word_alignment": "exact_token_text",
                      "words": [{"text": c, "start_ms": i * 2000 + k * 100, "end_ms": i * 2000 + k * 100 + 90,
                                 "char_start": k, "char_end": k + 1} for k, c in enumerate(f"第{i}句字幕")],
                      "word_base_interval": [i * 2000, i * 2000 + 1500], "word_clock_offset_ms": 0}
            for i in range(count)}},
        "manual_caption_text": {"c3": "第3句字幕"},
        "term_word_overrides": {},
        7: "non-string key",
    }
    return project


def test_shared_freeze_equals_full_freeze_across_edits():
    project = _project()
    store = StudioRevisionStore(project)
    assert store._frozen_studio_state() == freeze_json(project.studio_state)
    rng = random.Random(20261011)
    instances = project.studio_state[KEY]["instances"]
    for _round in range(25):
        name = f"c{rng.randrange(300)}"
        receipt = instances[name]
        choice = rng.randrange(4)
        if choice == 0:
            for word in receipt["words"]:
                word["start_ms"] += 40
                word["end_ms"] += 40
        elif choice == 1:
            receipt["text"] = receipt["text"] + "啊"
        elif choice == 2:
            instances[f"new{_round}"] = copy.deepcopy(receipt)
        else:
            instances.pop(name)
            project.studio_state["manual_caption_text"][name] = "改"
        assert store._frozen_studio_state() == freeze_json(project.studio_state)
    # A persistence capture freezes the same content.
    assert store._capture_persistence(5).studio_state == freeze_json(project.studio_state)


def test_unchanged_receipts_are_reused_not_refrozen():
    project = _project(50)
    store = StudioRevisionStore(project)
    before = dict(store._frozen_studio_state().items)[KEY]
    project.studio_state[KEY]["instances"]["c10"]["text"] = "改过的字幕"
    after = dict(store._frozen_studio_state().items)[KEY]
    old = dict(dict(before.items)["instances"].items)
    new = dict(dict(after.items)["instances"].items)
    assert new["c11"] is old["c11"]
    assert new["c10"] is not old["c10"] and dict(new["c10"].items)["text"] == "改过的字幕"
