"""Own library-created export scratch files without changing the temp volume."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile


@contextmanager
def renderer_temporary_environment(environment):
    # Keep the configured system/test temporary disk. Remotion and Chromium
    # create their own subdirectories here, rather than leaving unowned bundles
    # (including copied public fonts) alongside unrelated application temp files.
    parent = Path(tempfile.gettempdir()).resolve()
    root = Path(tempfile.mkdtemp(prefix='2byteasr-renderer-', dir=parent)).resolve()
    env = dict(environment)
    env.update(TEMP=str(root), TMP=str(root), TMPDIR=str(root))
    from ..exports.export_run_log import note_export
    note_export('renderer_temp_created', dict(path=str(root), volume=root.anchor,
        owner='one Node export process and its descendants'))
    try:
        yield env
    finally:
        total = 0
        try:
            try:
                for path in root.rglob('*'):
                    if path.is_file() and not path.is_symlink():
                        total += path.stat().st_size
            except OSError:
                pass  # Optional accounting must not prevent owned cleanup.
            # A cleanup path must still be our exact owned directory, never a
            # replaced junction into the source tree or another temp owner.
            if root.resolve() != root or root.parent != parent or not root.name.startswith('2byteasr-renderer-'):
                raise OSError('renderer temporary directory ownership changed')
            shutil.rmtree(root)
        except OSError as error:
            # Keep the original cancellation/render error and diagnose deferred
            # cleanup if Windows still has an external reader on a file.
            note_export('renderer_temp_cleanup_deferred', dict(path=str(root),
                bytes_before_cleanup=total, error_type=type(error).__name__))
        else:
            note_export('renderer_temp_released', dict(path=str(root), bytes=total))
