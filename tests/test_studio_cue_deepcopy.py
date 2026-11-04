"""StudioCue deep copies stay exact and independent (fast path, 2026-10-10).

Undo snapshots and edit working copies deep-copy every cue several times per
edit. The field-aware copy must give the same values and types as the generic
``copy.deepcopy`` and never share a mutable container with the original.
"""
import copy
import enum

from twobyteasr.projects.studio_project import StudioCue


class _Level(enum.IntEnum):
    HIGH = 2


class _Tagged(dict):
    pass


def _cue():
    cue = StudioCue("c1", 0, 1200, "你好", speaker_id="S02", evidence_refs=["seg:1", "seg:2"],
                    appearance_override={"fill": {"stops": [[0, "#fff"], [1, "#000"]]}, "size": 1.5, "on": True},
                    transform={"x": 0.25, "anchor": (0.5, 1.0)})
    cue.appearance_override["level"] = _Level.HIGH
    cue.transform["tagged"] = _Tagged(k=[1])
    cue.runtime_note = {"seen": [1, 2]}
    return cue


def test_copy_matches_generic_values_and_types():
    cue = _cue()
    fast = copy.deepcopy(cue)
    assert fast == cue and fast is not cue
    assert type(fast.appearance_override["level"]) is _Level
    assert type(fast.transform["tagged"]) is _Tagged
    assert fast.transform["anchor"] == (0.5, 1.0) and type(fast.transform["anchor"]) is tuple
    assert fast.runtime_note == {"seen": [1, 2]}


def test_copy_shares_no_mutable_container():
    cue = _cue()
    fast = copy.deepcopy(cue)
    fast.evidence_refs.append("seg:3")
    fast.appearance_override["fill"]["stops"][0][1] = "#f00"
    fast.transform["tagged"]["k"].append(2)
    fast.runtime_note["seen"].append(3)
    assert cue.evidence_refs == ["seg:1", "seg:2"]
    assert cue.appearance_override["fill"]["stops"][0][1] == "#fff"
    assert cue.transform["tagged"]["k"] == [1]
    assert cue.runtime_note == {"seen": [1, 2]}


def test_list_of_cues_copies_each_cue_once():
    cues = [_cue(), _cue()]
    shared = cues[0]
    copied = copy.deepcopy([shared, shared, cues[1]])
    assert copied[0] is copied[1] and copied[0] is not shared
    assert copied[2] == cues[1]
