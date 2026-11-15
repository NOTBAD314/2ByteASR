"""Merging Ultra readiness must not regress incremental list discovery."""
import threading
import time
from types import SimpleNamespace


def test_alignment_proof_is_published_by_worker_before_unrelated_slow_model(tmp_path,monkeypatch):
    from twobyteasr.local_models import model_status_cache as cache,model_registry,alignment_readiness
    partial_seen=threading.Event();release=threading.Event();finished=threading.Event()
    inspection_threads=[];results=[];final_results=[]
    base=SimpleNamespace(health=SimpleNamespace(value='INSTALLED'))
    def inspect(registry,*,keys=None):
        inspection_threads.append(threading.get_ident())
        return {k:dict(state='installed',ready=True,reason='fixture proof') for k in keys}
    monkeypatch.setattr(alignment_readiness,'inspect',inspect)
    def scan(*,install_root,on_progress,workers):
        assert workers==2
        partial=model_registry.ModelRegistry(install_root,tmp_path,records={'qwen_ultra_aligner':base},pending_keys=frozenset({'mfa_aligner','mfa_aligner_ja'}))
        on_progress(partial)
        assert release.wait(3)
        return model_registry.ModelRegistry(install_root,tmp_path,records={**partial.records,'mfa_aligner':base,'mfa_aligner_ja':base})
    monkeypatch.setattr(model_registry,'scan_model_registry',scan)
    def receive(registry):
        results.append(registry)
        if registry.pending_keys:partial_seen.set()
    def final(registry):
        final_results.append(registry)
        finished.set()
    cache.request_registry(tmp_path,final,progress_callback=receive)
    try:
        assert partial_seen.wait(3)
        partial=results[0]
        assert partial.alignment_readiness['qwen_aligner']['ready']
        assert partial.alignment_readiness['mfa_aligner']['state']=='checking'
        assert not final_results
        assert inspection_threads and all(t!=threading.get_ident() for t in inspection_threads)
        release.set()
        assert finished.wait(3)
        assert len(final_results)==1 and not final_results[0].pending_keys
        assert final_results[0].alignment_readiness['mfa_aligner']['ready']
        assert partial.alignment_readiness['mfa_aligner']['state']=='checking'
    finally:release.set()
