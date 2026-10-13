"""Loading defers full collections; the deferred one runs once the page is idle."""
import gc

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.playback_gc_budget import (
    PlaybackGcBudget, ProjectHeapPolicy, hold_full_collections, release_full_collections,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_load_defers_full_collections_then_collects_when_idle(app):
    before = gc.get_threshold()
    busy = [False]
    policy = ProjectHeapPolicy(busy=lambda: busy[0])
    try:
        policy.load_started()
        assert gc.get_threshold()[2] >= 1_000_000 and gc.get_threshold()[:2] == before[:2]
        policy.load_finished()
        assert gc.get_threshold() == before
        assert policy.settle_timer.isActive() and policy.settles == 0
        busy[0] = True
        policy.settle()  # pointer down or playing: wait, never collect mid-gesture
        assert policy.settles == 0 and policy.settle_timer.isActive()
        busy[0] = False
        policy.settle()
        assert policy.settles == 1 and gc.get_freeze_count() == 0  # nothing is frozen
    finally:
        policy.close()
    assert gc.get_threshold() == before


def test_failed_or_cancelled_load_restores_policy_without_collecting(app):
    before = gc.get_threshold()
    policy = ProjectHeapPolicy()
    try:
        policy.load_started()
        policy.load_started()  # a second open while loading keeps one hold
        policy.load_finished(settle=False)
        assert gc.get_threshold() == before and not policy.settle_timer.isActive()
    finally:
        policy.close()


def test_playback_and_loading_share_one_deferral(app):
    before = gc.get_threshold()
    budget = PlaybackGcBudget(memory_reader=lambda: 1000)
    policy = ProjectHeapPolicy()
    try:
        policy.load_started()
        budget.set_playing(True)
        policy.load_finished(settle=False)
        assert gc.get_threshold()[2] >= 1_000_000  # playback still defers
        budget.set_playing(False)
        assert gc.get_threshold() == before
    finally:
        budget.close()
        policy.close()
    assert hold_full_collections("probe") and release_full_collections("probe")
    assert gc.get_threshold() == before
