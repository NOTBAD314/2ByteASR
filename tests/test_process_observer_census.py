from types import SimpleNamespace
from twobyteasr.diagnostics import process_diagnostics as observer

def test_windows_observer_reuses_bounded_native_census(monkeypatch):
    from twobyteasr.system import process_snapshot
    monkeypatch.setattr(observer,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_snapshot,'process_snapshot',lambda:{10:(0,2),11:(10,3),12:(11,4),13:(13,1)})
    def forbidden():raise AssertionError('GIL-holding psutil census was called')
    assert observer._process_tree(SimpleNamespace(_ppid_map=forbidden))=={0:[10],10:[11],11:[12]}
