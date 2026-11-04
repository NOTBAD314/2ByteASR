"""Regression tests for the 2026-08-10 P1/P2 fixes:

- MOSS legacy parallel settings cannot reactivate independent contexts;
- glossary.txt tolerates GBK/GB18030 encodings (Windows 记事本);
- game_profiles.json is cached per process and invalidated by mtime;
- dead Tk entry points no longer exist.
"""

import time

import pytest

import subtitle_core
import moss_firered_pipeline


def test_moss_parallel_worker_count_requires_free_vram(monkeypatch):
    jobs = [{"chunk_id": 1}, {"chunk_id": 2}, {"chunk_id": 3}]

    class _Legacy:
        MOSS_PARALLEL_WORKERS = 2
        MOSS_PARALLEL_MIN_VRAM_GB = 14.0

    monkeypatch.setattr(moss_firered_pipeline, "_cuda_total_memory_gb", lambda: 24.0)
    # 总显存足够但空闲不足 → 单路，避免 OOM 后整批回退
    monkeypatch.setattr(moss_firered_pipeline, "_cuda_free_memory_gb", lambda: 10.0)
    assert moss_firered_pipeline._moss_parallel_worker_count(jobs, _Legacy()) == 1
    # 空闲显存足够仍为整段单上下文
    monkeypatch.setattr(moss_firered_pipeline, "_cuda_free_memory_gb", lambda: 20.0)
    assert moss_firered_pipeline._moss_parallel_worker_count(jobs, _Legacy()) == 1


def test_load_glossary_tolerates_gbk_encoding(monkeypatch, tmp_path):
    glossary = tmp_path / "glossary.txt"
    # “原神” 的 GBK 字节：非 UTF-8，旧代码会 UnicodeDecodeError
    glossary.write_bytes("纳西妲\n".encode("gbk"))
    monkeypatch.setattr(subtitle_core, "GLOSSARY_PATH", str(glossary))
    terms = subtitle_core.load_glossary()
    assert terms == ["纳西妲"]


def test_load_game_profiles_is_cached_until_mtime_changes(monkeypatch, tmp_path):
    profiles = tmp_path / "game_profiles.json"
    profiles.write_text('{"profiles": {"A": {"identity": "a"}}}', encoding="utf-8")
    monkeypatch.setattr(subtitle_core, "GAME_PROFILES_PATH", str(profiles))
    monkeypatch.setattr(subtitle_core, "_GAME_PROFILES_CACHE", {"mtime_ns": 0, "profiles": {}})

    assert subtitle_core.load_game_profiles() == {"A": {"identity": "a"}}
    # 缓存生效：mtime 不变时返回同一缓存对象，未重新解析
    assert subtitle_core.load_game_profiles() is subtitle_core.load_game_profiles()

    # mtime 变化 → 重新读取
    time.sleep(0.02)
    profiles.write_text('{"profiles": {"B": {"identity": "b"}}}', encoding="utf-8")
    assert subtitle_core.load_game_profiles() == {"B": {"identity": "b"}}


def test_dead_tk_entry_points_removed():
    for name in (
        "choose_media_files",
        "choose_runtime_content_profile",
        "filter_overwrite_media",
        "show_completion_message",
        "build_hf_endpoints",
    ):
        assert not hasattr(subtitle_core, name), f"{name} 应已删除"
    assert "tkinter" not in open(subtitle_core.__file__, encoding="utf-8-sig").read()
