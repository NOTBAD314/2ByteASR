import os
from twobyteasr.system.process_snapshot import process_snapshot, descendant_pids


def test_census_includes_current_process_without_private_fields():
    rows = process_snapshot()
    assert os.getpid() in rows
    parent, threads = rows[os.getpid()]
    assert isinstance(parent, int) and isinstance(threads, int) and threads >= 1
    assert all(len(row) == 2 for row in rows.values())


def test_descendants_are_transitive_bounded_and_exclude_root_and_peers():
    rows = {1: (3, 5), 2: (1, 2), 3: (2, 1), 4: (99, 1), 5: (1, 3)}
    assert set(descendant_pids(1, rows)) == {2, 3, 5}
    assert descendant_pids(99, rows) == [4]
