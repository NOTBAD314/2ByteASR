import gc
from PySide6.QtWidgets import QApplication
from twobyteasr.playback.playback_gc_budget import PlaybackGcBudget

APP = QApplication.instance() or QApplication([])


def test_defers_only_generation_two_and_restores_on_pause():
    before=gc.get_threshold(); memory=[1000]
    budget=PlaybackGcBudget(memory_reader=lambda:memory[0])
    try:
        budget.set_playing(True)
        assert gc.isenabled()
        assert gc.get_threshold()[:2] == before[:2]
        assert gc.get_threshold()[2] >= 1_000_000
        memory[0] += budget.SWEEP_GROWTH
        budget.set_playing(False)
        assert gc.get_threshold() == before
        assert budget.idle_collect.isActive()
        budget.set_playing(True)
        assert not budget.idle_collect.isActive()
    finally: budget.close()
    assert gc.get_threshold() == before


def test_short_play_pause_does_not_sweep_the_heap():
    # 2026-10-22: every pause swept a 1.4 GB heap (0.25-0.35 s GUI stall).
    before=gc.get_threshold(); memory=[1000]
    budget=PlaybackGcBudget(memory_reader=lambda:memory[0])
    try:
        for _ in range(5):
            budget.set_playing(True)
            memory[0] += 4 * 1024 * 1024
            budget.set_playing(False)
            assert gc.get_threshold() == before
            assert not budget.idle_collect.isActive()
    finally: budget.close()


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


def test_pause_does_not_repeat_a_full_collection_that_already_ran(monkeypatch):
    collections = [12]
    forced = []
    monkeypatch.setattr(gc, 'get_stats', lambda: [{}, {}, {'collections': collections[0]}])
    monkeypatch.setattr(gc, 'collect', lambda generation=2: forced.append(generation))
    before = gc.get_threshold()
    budget = PlaybackGcBudget(memory_reader=lambda: 1000)
    try:
        budget.set_playing(True)
        budget.set_playing(False)
        collections[0] += 1  # Normal automatic GC ran after its policy was restored.
        budget.idle_collect.stop()
        budget._collect_paused()
        assert forced == []
        assert gc.get_threshold() == before and gc.isenabled()
    finally:
        budget.close()


def test_open_editor_is_not_idle_for_an_extra_forced_collection(monkeypatch):
    forced = []
    monkeypatch.setattr(gc, 'collect', lambda generation=2: forced.append(generation))
    before = gc.get_threshold()
    budget = PlaybackGcBudget(memory_reader=lambda: 1000)
    budget.busy = lambda: True
    try:
        budget.set_playing(True)
        budget.set_playing(False)
        budget.idle_collect.stop()
        budget._collect_paused()
        assert forced == []
        # The fix must not suspend automatic collection while editing.
        assert gc.get_threshold() == before and gc.isenabled()
    finally:
        budget.close()


def _collector(memory):
    from twobyteasr.playback import playback_gc_budget as module
    collector = module.GuiThreadCollector(memory_reader=lambda: memory[0])
    assert collector.start()
    return module, collector


def test_gui_thread_collector_owns_automatic_collection_and_gives_it_back():
    before = gc.get_threshold()
    module, collector = _collector([1000])
    try:
        assert collector.active and not gc.isenabled()
        assert module.collection_enabled()
        # A playback hold still raises the full-collection threshold.
        budget = PlaybackGcBudget(memory_reader=lambda: 1000)
        budget.set_playing(True)
        assert budget.held and gc.get_threshold()[2] >= 1_000_000
        budget.close()
        assert gc.get_threshold() == before
    finally:
        collector.stop()
    assert gc.isenabled() and collector._observe not in gc.callbacks


def test_gui_thread_collector_follows_thresholds_and_bounds_full_collections(monkeypatch):
    memory = [100 * 1024 * 1024]
    module, collector = _collector(memory)
    calls = []
    counts = [(701, 0, 0)]
    monkeypatch.setattr(module.gc, 'get_count', lambda: counts[0])
    monkeypatch.setattr(module.gc, 'get_threshold', lambda: (700, 10, 10))
    monkeypatch.setattr(module.gc, 'collect', lambda generation=2: calls.append(generation))
    try:
        collector.tick()
        counts[0] = (5, 11, 0); collector.tick()
        counts[0] = (5, 0, 11); collector.tick()          # heap has not grown: no full pass
        counts[0] = (701, 0, 11); collector.tick()        # ...the young pass still runs
        memory[0] += 64 * 1024 * 1024; collector.tick()   # grown by 64 MiB: full pass
        counts[0] = (5, 5, 5); collector.tick()           # below every threshold
        assert calls == [0, 1, 0, 2]
    finally:
        monkeypatch.undo()
        collector.stop()


def test_cyclic_qt_garbage_from_a_worker_thread_is_destroyed_on_the_gui_thread():
    # Python's own automatic collection would destroy this QObject on the
    # worker thread (checked 2026-10-22: deleted_on == ['worker']).
    import threading
    from PySide6.QtCore import QObject, Qt

    module, collector = _collector([1000])
    deleted_on = []
    try:
        gc.collect()
        holder = []
        holder.append(holder)
        item = QObject()
        item.destroyed.connect(lambda *_: deleted_on.append(threading.current_thread().name),
                               Qt.ConnectionType.DirectConnection)
        holder.append(item)
        del item, holder

        def allocate():
            junk = []
            for index in range(200_000):
                junk.append([index])
                if len(junk) > 1000:
                    junk.clear()
        worker = threading.Thread(target=allocate, name='worker')
        worker.start(); worker.join()
        assert deleted_on == []
        gc.collect()  # what tick() does on the GUI thread
        assert deleted_on == [threading.current_thread().name]
    finally:
        collector.stop()
