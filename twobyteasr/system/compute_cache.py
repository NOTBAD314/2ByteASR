"""JIT caches belong to the writable application cache, never a model/runtime."""
from __future__ import annotations
import os
from pathlib import Path


def environment(base=None):
    from ..runtime_paths import user_data_root
    result=dict(os.environ if base is None else base)
    if not result.get('NUMBA_CACHE_DIR'):
        folder=Path(user_data_root())/'cache'/'compute'/'numba'
        folder.mkdir(parents=True,exist_ok=True)
        result['NUMBA_CACHE_DIR']=str(folder)
    return result
