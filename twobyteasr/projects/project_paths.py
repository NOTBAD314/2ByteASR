"""Bounded internal project locations; full titles belong in display metadata."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path


def legacy_stem(title):
    return ''.join('_' if c in '<>:"/\\|?*' or ord(c)<32 else c for c in str(title)).strip(' .') or 'Subtitle Project'


def internal_project_path(root, identity, *, kind='p'):
    # A 128-bit identity leaves room for atomic temporary files and sidecars.
    # Every caller's full job/media identity remains in the saved metadata.
    key=hashlib.sha256(str(identity).encode('utf8')).hexdigest()[:32]
    return Path(root)/f'{kind}-{key}'/'project.2byteproj'


def save_error_details(error, path):
    path=Path(path)
    return {'exception_type': type(error).__name__, 'errno':getattr(error,'errno',None),
            'winerror':getattr(error,'winerror',None), 'path':str(path),
            'path_utf16_units':len(str(path).encode('utf-16-le'))//2,
            'component_utf16_units':[len(p.encode('utf-16-le'))//2 for p in path.parts],
            'parent_exists':path.parent.is_dir(), 'error':str(error)}
