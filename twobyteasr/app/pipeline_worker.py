"""Background thread that runs one recognition queue for the main window.

``PipelineWorker`` calls ``recognition.service.run_media_queue`` and tees the
pipeline's stdout/stderr into the progress page through ``SignalTextStream``.
Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports both names.
Tests that fake the queue patch ``run_media_queue`` on this module.
"""
from __future__ import annotations

import sys
import threading
from contextlib import redirect_stderr, redirect_stdout

from PySide6.QtCore import QThread, Signal

from ..recognition.service import run_media_queue


class SignalTextStream:
    """Tee text written by the pipeline to both the GUI and the original console."""

    def __init__(self, signal, level: str, fallback=None):
        self.signal = signal
        self.level = level
        self.fallback = fallback
        self._buffer = ""
        self._lock = threading.RLock()

    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return False

    def writable(self):
        return True

    def write(self, value):
        text = str(value or "")
        if not text:
            return 0
        with self._lock:
            if self.fallback is not None:
                try:
                    self.fallback.write(text)
                except Exception:
                    pass
            self._buffer += text.replace("\r\n", "\n").replace("\r", "\n")
            lines = self._buffer.split("\n")
            self._buffer = lines.pop()
            for line in lines:
                if line.strip():
                    self.signal.emit(line, self.level)
        return len(text)

    def flush(self):
        with self._lock:
            if self._buffer.strip():
                self.signal.emit(self._buffer, self.level)
            self._buffer = ""
            if self.fallback is not None:
                try:
                    self.fallback.flush()
                except Exception:
                    pass


class PipelineWorker(QThread):
    event_received = Signal(object)
    console_received = Signal(str, str)
    result_ready = Signal(object)
    unexpected_error = Signal(str)

    def __init__(self, media_paths, options, token, legacy, pipeline, startup_self_test):
        super().__init__()
        self.media_paths = list(media_paths)
        self.options = options
        self.token = token
        self.legacy = legacy
        self.pipeline = pipeline
        self.startup_self_test = startup_self_test

    def run(self):
        stdout_stream = SignalTextStream(self.console_received, "stdout", sys.stdout)
        stderr_stream = SignalTextStream(self.console_received, "stderr", sys.stderr)
        try:
            with redirect_stdout(stdout_stream), redirect_stderr(stderr_stream):
                startup_self_test = self.startup_self_test
                if startup_self_test is None:
                    print("[后台自测] 首次开始任务，正在检查字幕护栏……")
                    startup_self_test = self.legacy.run_startup_self_test()
                    print(
                        f"[后台自测通过] {startup_self_test['id']}："
                        f"{startup_self_test['checks']} 项关键护栏正常"
                    )
                result = run_media_queue(
                    self.media_paths,
                    self.options,
                    event_sink=self.event_received.emit,
                    cancel_token=self.token,
                    _legacy=self.legacy,
                    _pipeline=self.pipeline,
                    _startup_self_test=startup_self_test,
                )
            self.result_ready.emit(result)
        except BaseException as exc:
            self.unexpected_error.emit(" ".join(str(exc).split()) or exc.__class__.__name__)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()
