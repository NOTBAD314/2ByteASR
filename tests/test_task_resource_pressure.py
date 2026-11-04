from twobyteasr.system import task_resources as resources
from twobyteasr.storage.runtime_cache import RuntimeCacheManager


def state(gib,foreground=False):
    return dict(available_bytes=int(gib*1024**3),total_bytes=64*1024**3,
                process_tree_rss_bytes=8*1024**3,foreground=foreground)


def test_budgets_respond_to_available_memory_and_foreground(monkeypatch):
    for name in ('TWOBYTEASR_AI_REQUESTS','TWOBYTEASR_SHARD_WORKERS','TWOBYTEASR_CACHE_MIB'):
        monkeypatch.delenv(name,raising=False)
    large=resources.task_budget(state(24));small=resources.task_budget(state(1))
    foreground=resources.task_budget(state(24,True))
    assert large.ai_requests>small.ai_requests and large.shard_workers>foreground.shard_workers
    assert large.reclaimable_cache_bytes>small.reclaimable_cache_bytes
    assert foreground.reclaimable_cache_bytes==large.reclaimable_cache_bytes//2
    monkeypatch.setenv('TWOBYTEASR_CACHE_MIB','128')
    assert resources.task_budget(state(24)).reclaimable_cache_bytes==128*1024**2


def test_cache_reclaims_rebuildable_results_and_preserves_pinned_data():
    budget=[50]
    cache=RuntimeCacheManager(memory_budget_provider=lambda:budget[0])
    cache.put_memory('edited','keep',size_bytes=10,project_pinned=True)
    for number in range(4):cache.put_memory(str(number),number,size_bytes=10)
    assert cache.snapshot()['memory_entries']==5
    budget[0]=20
    assert cache.get_memory('edited')=='keep'
    assert cache.get_memory('0') is None and cache.get_memory('3')==3
    assert cache.snapshot()['memory_bytes']==20


def test_gui_cache_read_never_enumerates_processes(monkeypatch):
    monkeypatch.setattr(resources,'_LIVE_VALUE',resources.task_budget(state(24)))
    monkeypatch.setattr(resources,'memory_snapshot',lambda:(_ for _ in ()).throw(AssertionError('GUI process scan')))
    assert resources.cached_cache_budget(1,share=.5)==512*1024**2
