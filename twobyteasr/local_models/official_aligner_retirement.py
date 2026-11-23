"""Remove the superseded official Qwen3 aligner once Ultra is the verified route.

2026-11-22 (user): the Qwen3 对齐 entry runs Ultra, yet the old official weights
(models/Qwen3-ForcedAligner-0.6B, about 1.8 GB) stayed in users' model folders.
Ultra only borrowed them for the rare utterance that conflicts with its ASR
parent; without them such an item stays unaligned, exactly as on a fresh Ultra
install. Install and repair scripts already download Ultra for this key, so the
folder does not come back.

Only the files the dependency lock lists for ``qwen_aligner`` are deleted, and
only from an app-managed model folder (``plan_model_removal``); a custom folder
(``2BYTEASR_QWEN3_ALIGNER_DIR`` or an external location) is left alone, and so
is every unknown file.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MODEL_KEY = 'qwen_aligner'
RECORD = 'migrations/qwen-official-aligner-retired.json'
KEEP_ENV = 'TWOBYTEASR_KEEP_OFFICIAL_ALIGNER'


def retirement_blocker(settings, *, readiness=None) -> str:
    """Why the old weights must stay; '' when they can go."""
    models = (settings or {}).get('models') or {}
    if os.environ.get(KEEP_ENV, '').strip() == '1':
        return 'kept_by_environment'
    if os.environ.get('2BYTEASR_QWEN3_ALIGNER_DIR', '').strip():
        return 'custom_directory'
    if models.get('qwen_alignment_profile') != 'ultra-v5':
        # Settings that never moved to Ultra still run the official weights.
        return 'official_profile_in_use'
    if readiness is None:
        from ..recognition.qwen_upgrade import current_readiness
        readiness = current_readiness()
    if not readiness:
        return 'ultra_not_verified'
    return ''


def _write_record(record: dict) -> None:
    from ..runtime_paths import user_data_root
    from ..storage.atomic_files import write_text_atomic
    target = user_data_root() / RECORD
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, json.dumps(record, ensure_ascii=False, indent=2))


def retire_official_aligner(settings, *, install_root=None, busy_check=lambda: False,
                            readiness=None) -> dict:
    blocker = retirement_blocker(settings, readiness=readiness)
    if blocker:
        return dict(status='kept', reason=blocker)
    from ..recognition.alignment_backend import official_compat_directory
    if busy_check():
        return dict(status='kept', reason='busy')
    compat_directory = official_compat_directory()
    from ..runtime_paths import detect_install_root
    from .model_removal import execute_removal, plan_model_removal
    try:
        plan = plan_model_removal(Path(install_root or detect_install_root()), MODEL_KEY)
    except (OSError, ValueError, KeyError) as exc:
        return dict(status='kept', reason='no_owned_plan', error=str(exc)[:300])
    if plan.mode != 'delete' or plan.external:
        return dict(status='kept', reason='not_app_managed', directory=str(plan.root))
    if compat_directory and Path(compat_directory).absolute() != plan.root:
        return dict(status='kept', reason='different_compat_directory', directory=compat_directory)
    if not plan.paths:
        return dict(status='absent', directory=str(plan.root))
    result = execute_removal(plan, busy_check=busy_check)
    record = dict(status='removed' if not result.failures else 'partial', model=MODEL_KEY,
                  directory=str(plan.root), removed=result.removed, failures=result.failures,
                  retained=result.retained, freed_bytes=result.logical_bytes, at=time.time())
    try:
        _write_record(record)
    except OSError as exc:
        record['record_error'] = str(exc)
    if result.removed:
        from .model_state_events import notify
        notify([MODEL_KEY], 'removed')
    return record
