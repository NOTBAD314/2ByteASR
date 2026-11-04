from __future__ import annotations

import json
from pathlib import Path

from twobyteasr.diagnostics.build_identity import (
    _is_source_file,
    about_build_text,
    load_build_identity,
    source_snapshot_sha256,
    startup_identity_lines,
)


def test_source_snapshot_excludes_renderer_dependencies_and_outputs():
    assert _is_source_file("renderer/src/index.tsx") is True
    assert _is_source_file("renderer/service.mjs") is True
    assert _is_source_file("renderer/node_modules/react/index.js") is False
    assert _is_source_file("renderer/tmp/render.js") is False


def test_packaged_identity_loads_embedded_metadata(tmp_path: Path):
    metadata = tmp_path / "2byteasr_build.json"
    metadata.write_text(
        json.dumps(
            {
                "app_version": "0.2.0",
                "git_sha": "a" * 40,
                "git_dirty": True,
                "build_time": "2026-08-27T08:15:00Z",
                "build_channel": "p8a-r1",
                "source_sha256": "b" * 64,
                "source_file_count": 123,
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "dist" / "2ByteASR.exe"
    build = load_build_identity(
        metadata_path=metadata,
        packaged=True,
        executable_path=exe,
        project_root=tmp_path,
    )
    assert build.packaged is True
    assert build.git_sha == "a" * 40
    assert build.source_sha256 == "b" * 64
    assert build.source_file_count == 123
    about = about_build_text(build)
    assert "Runtime: packaged" in about
    assert f"Executable path: {exe.resolve()}" in about
    assert "Git SHA: " + "a" * 40 in about
    assert "Dirty state:" not in about


def test_source_snapshot_hash_covers_path_and_content(tmp_path: Path):
    first = tmp_path / "twobyteasr" / "a.py"
    second = tmp_path / "quick_start.py"
    first.parent.mkdir()
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("main = True\n", encoding="utf-8")
    before, count = source_snapshot_sha256(tmp_path, (second, first))
    assert count == 2
    first.write_text("value = 2\n", encoding="utf-8")
    after, _ = source_snapshot_sha256(tmp_path, (second, first))
    assert before != after


def test_startup_identity_contains_required_runtime_fields(tmp_path: Path):
    metadata = tmp_path / "2byteasr_build.json"
    metadata.write_text(
        json.dumps(
            {
                "app_version": "0.2.0",
                "git_sha": "c" * 40,
                "git_dirty": False,
                "build_time": "2026-08-27T08:15:00Z",
                "build_channel": "stable",
                "source_sha256": "d" * 64,
                "source_file_count": 99,
            }
        ),
        encoding="utf-8",
    )
    build = load_build_identity(
        metadata_path=metadata,
        packaged=True,
        executable_path=tmp_path / "2ByteASR.exe",
        project_root=tmp_path,
    )
    lines = startup_identity_lines(
        build,
        model_root=tmp_path / "models",
        project_root=tmp_path / "Projects",
    )
    keys = {line.partition("=")[0] for line in lines}
    assert {
        "APP_VERSION",
        "GIT_SHA",
        "BUILD_TIME",
        "BUILD_CHANNEL",
        "PACKAGED",
        "EXECUTABLE_PATH",
        "MODEL_ROOT",
        "PROJECT_ROOT",
        "SOURCE_SHA256",
        "PROCESS_ROLE",
        "PID",
        "PARENT_PID",
    } <= keys
