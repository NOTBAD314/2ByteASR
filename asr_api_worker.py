"""Owned API request process. Credentials arrive only through stdin, never argv/disk.

Source-checkout launcher for ``twobyteasr.cloud_api_worker``; the packaged app
runs the same body as ``2ByteASR.exe --asr-api-worker``.
"""
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    if root.name == 'workers':
        root = root.parent
    # Append, never prepend: site-packages of the running interpreter must win
    # over loose files beside an installed app.
    if str(root) not in sys.path:
        sys.path.append(str(root))
    from twobyteasr.cloud_api_worker import main as worker_main
    return worker_main()


if __name__ == '__main__':
    raise SystemExit(main())
