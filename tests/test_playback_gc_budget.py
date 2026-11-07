import gc
from PySide6.QtWidgets import QApplication
from twobyteasr.playback.playback_gc_budget import PlaybackGcBudget

APP = QApplication.instance() or QApplication([])


def test_defers_only_generation_two_and_restores_on_pause():
    before=gc.get_threshold()
    budget=PlaybackGcBudget(memory_reader=lambda:1000)
    try:
        budget.set_playing(True)
        assert gc.isenabled()
        assert gc.get_threshold()[:2] == before[:2]
        assert gc.get_threshold()[2] >= 1_000_000
        budget.set_playing(False)
        assert gc.get_threshold() == before
        assert budget.idle_collect.isActive()
        budget.set_playing(True)
        assert not budget.idle_collect.isActive()
    finally: budget.close()
    assert gc.get_threshold() == before


def test_memory_growth_restores_normal_gc_while_still_playing():
    before=gc.get_threshold(); memory=[1000]
    budget=PlaybackGcBudget(memory_reader=lambda:memory[0])
    try:
        budget.set_playing(True)
        memory[0] += budget.MAX_PRIVATE_GROWTH+1
        budget.check_budget()
        assert budget.playing and not budget.held and budget.budget_exhausted
        assert gc.get_threshold() == before
        budget.set_playing(True)
        assert not budget.held  # No re-arming after the memory guard fired.
    finally: budget.close()


def test_close_restores_and_respects_an_external_policy_change():
    before=gc.get_threshold(); budget=PlaybackGcBudget(memory_reader=lambda:1000)
    try:
        budget.set_playing(True)
        gc.set_threshold(800,12,15)
        budget.close()
        assert gc.get_threshold() == (800,12,15)
    finally:
        budget.close(); gc.set_threshold(*before)


def test_unmeasurable_memory_and_pre_disabled_gc_are_not_overridden():
    before=gc.get_threshold(); budget=PlaybackGcBudget(memory_reader=lambda:None)
    budget.set_playing(True)
    assert not budget.held and gc.get_threshold() == before
    budget.close()
    gc.disable()
    try:
        budget=PlaybackGcBudget(memory_reader=lambda:1000); budget.set_playing(True)
        assert not budget.held and not gc.isenabled()
        budget.close()
    finally: gc.enable()
