import os
from pathlib import Path

import pytest

from twobyteasr import test_isolation


def test_guard_lists_resolved_paths_inside_isolation_root():
    lines = []
    paths = test_isolation.require_isolated_paths("pytest", emit=lines.append)
    root = test_isolation.isolation_root()
    assert lines and all(line.startswith("ISOLATION pytest ") for line in lines)
    for name in ("user_data_root", "settings_root", "project_library", "recognition_history_index",
                 "reports", "secrets", "startup_trace"):
        assert Path(paths[name]).resolve().is_relative_to(root), name


def test_guard_aborts_when_a_path_is_real_user_data(monkeypatch):
    # Pretend the isolated LocalAppData is the account's real one: every
    # product data path now counts as real user data and must abort.
    monkeypatch.setattr(test_isolation, "real_local_app_data", lambda: Path(os.environ["LOCALAPPDATA"]).resolve())
    with pytest.raises(SystemExit, match="ISOLATION ABORT"):
        test_isolation.require_isolated_paths("pytest", emit=lambda line: None)


def test_real_local_app_data_ignores_environment_overrides():
    real = test_isolation.real_local_app_data()
    if os.name != "nt":
        assert real is None
        return
    assert real is not None
    assert not real.is_relative_to(test_isolation.isolation_root())
