"""Explicit detach records for externally associated models.

The files stay at their user-selected location. Discovery and ASR resolution
respect the same record, so a detached folder is not silently rediscovered.
"""
from __future__ import annotations
import json
import os
from pathlib import Path


def association_path() -> Path:
    from ..runtime_paths import user_data_root
    return user_data_root() / 'model-associations.json'


def _key(path: Path) -> str:
    from ..runtime_paths import scan_memo
    path = Path(path)
    return os.path.normcase(str(scan_memo(("resolve", str(path)), path.resolve)))


def _load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text('utf-8-sig'))
    except FileNotFoundError:
        return {'schema_version': 1, 'detached': {}}
    if not isinstance(payload, dict) or not isinstance(payload.get('detached'), dict):
        raise ValueError('模型关联记录格式无效；未覆盖原文件')
    return payload


def is_model_detached(folder: Path, *, record_path: Path | None = None) -> bool:
    from ..runtime_paths import scan_memo
    path = record_path or association_path()
    # Read once per registry scan (single_scan); always fresh outside one.
    return _key(folder) in scan_memo(("model_associations", str(path)), lambda: _load(path))['detached']


def detach_model(folder: Path, model_key: str, *, record_path: Path | None = None) -> None:
    path = record_path or association_path()
    payload = _load(path)
    payload['detached'][_key(folder)] = {'model_key': model_key, 'path': str(folder)}
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def restore_model_association(folder: Path, *, record_path: Path | None = None) -> None:
    path = record_path or association_path()
    payload = _load(path)
    if payload['detached'].pop(_key(folder), None) is not None:
        from ..storage.atomic_files import write_text_atomic
        write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))
