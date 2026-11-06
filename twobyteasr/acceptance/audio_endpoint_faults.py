"""Owned-profile process-boundary faults; never enabled in ordinary launches."""
import os
from pathlib import Path
import sys
import time


def mode():
    value=os.environ.get('TWOBYTEASR_TEST_AUDIO_FAULT','')
    root=os.environ.get('TWOBYTEASR_TEST_ROOT','')
    output=os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR','')
    if not value or not root or not output:return ''
    if Path(output).resolve()!=Path(root).resolve():return ''
    return value


def before_connect():
    value=mode()
    if value=='exit':
        sys.stderr.write('Controlled endpoint failure before IPC handshake\n');sys.stderr.flush()
        raise SystemExit(1)
    if value=='delay':time.sleep(3.)


def configure_devices():
    if mode()=='no-device':
        from PySide6.QtMultimedia import QAudioDevice,QMediaDevices
        QMediaDevices.defaultAudioOutput=staticmethod(QAudioDevice)
