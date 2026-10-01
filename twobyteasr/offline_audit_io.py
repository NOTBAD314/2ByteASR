"""Test-only diagnostic sinks for zero-capability Windows AppContainer audits.

That OS token denies opening the NUL device. Temporary files replace only
subprocess DEVNULL descriptors; media IO, IPC, rendering and networking remain
real. The hook runs in frozen worker entry points as well as the GUI process.
"""
import os


def install():
    if os.environ.get('TWOBYTEASR_COVER_OFFLINE_AUDIT') != '1':
        return
    from .windows_ipc import in_app_container
    if not in_app_container():
        return
    from pathlib import Path
    import subprocess
    import tempfile
    root = Path(os.environ.get('TWOBYTEASR_TEST_ROOT', '')).resolve()
    allowed = (Path(os.environ.get('TWOBYTEASR_INVOKER_CWD') or Path.cwd())/'tmp').resolve()
    if not root.is_relative_to(allowed):
        raise ValueError('Offline diagnostic sinks require a private audit directory')
    folder = root/'diagnostic-sinks'
    folder.mkdir(parents=True, exist_ok=True)

    def private_sink(self):
        if not hasattr(self, '_devnull'):
            # Duplicate only the fd: Popen closes it after handle inheritance.
            # O_TEMPORARY keeps the sink private and removes it when children exit.
            with tempfile.TemporaryFile(dir=folder) as stream:
                self._devnull = os.dup(stream.fileno())
        return self._devnull

    subprocess.Popen._get_devnull = private_sink
