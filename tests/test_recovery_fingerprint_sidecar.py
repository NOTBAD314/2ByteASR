"""autosave 指纹边车 + recovery 快路径（2026-09-18 进入提速）。"""

import json
import os
import time
from pathlib import Path

import pytest

from twobyteasr.projects.studio_project import (
    SubtitleProject,
    StudioCue,
    StudioMedia,
    autosave_fingerprint_sidecar,
    load_project,
    project_content_fingerprint,
    recoverable_autosave,
    save_autosave,
    save_project,
)


def _project(tmp_path: Path, name: str = "p", text: str = "字幕内容") -> tuple[SubtitleProject, Path]:
    path = tmp_path / f"{name}.2byteproj"
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "m.mp4")),
        cues=[StudioCue(id="1", start_ms=0, end_ms=900, text=text)],
    )
    save_project(project, path)
    return project, path


def test_save_autosave_writes_fresh_fingerprint_sidecar(tmp_path):
    project, path = _project(tmp_path)
    target = save_autosave(project, path)
    sidecar_path = target.with_name(f"{target.stem}.fingerprint.json")
    assert sidecar_path.is_file()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == project.project_id
    assert payload["content_fingerprint"] == project_content_fingerprint(project)


def test_sidecar_stale_when_older_than_candidate(tmp_path):
    project, path = _project(tmp_path)
    target = save_autosave(project, path)
    sidecar_path = target.with_name(f"{target.stem}.fingerprint.json")
    old = time.time() - 3600
    os.utime(sidecar_path, (old, old))
    assert autosave_fingerprint_sidecar(target) == {}
    # 新鲜则可读
    os.utime(sidecar_path, None)
    assert autosave_fingerprint_sidecar(target).get("content_fingerprint")


def test_recoverable_autosave_accepts_loaded_official_and_sidecar_identity(tmp_path):
    project, path = _project(tmp_path)
    assert recoverable_autosave(path, official=project) is None  # 无更新候选

    time.sleep(0.02)
    save_autosave(project, path)  # 内容一致但 mtime 更新 → 候选存在
    candidate = recoverable_autosave(path, official=project)
    assert candidate is not None
    sidecar = autosave_fingerprint_sidecar(candidate)
    assert sidecar.get("content_fingerprint") == project_content_fingerprint(project)


def test_sidecar_fingerprint_matches_roundtrip_loaded_official(tmp_path):
    """边车指纹必须与"重新加载的官方"指纹一致，快路径才成立。"""
    project, path = _project(tmp_path)
    time.sleep(0.02)
    save_autosave(project, path)
    reloaded = load_project(path)
    sidecar = autosave_fingerprint_sidecar(save_autosave(project, path))
    assert sidecar.get("content_fingerprint") == project_content_fingerprint(reloaded)


def test_recoverable_autosave_without_sidecar_still_validates_by_load(tmp_path):
    """旧版 autosave（无边车）走全量解析校验路径。"""
    project, path = _project(tmp_path)
    time.sleep(0.02)
    target = save_autosave(project, path)
    target.with_name(f"{target.stem}.fingerprint.json").unlink()
    candidate = recoverable_autosave(path, official=project)
    assert candidate == target
