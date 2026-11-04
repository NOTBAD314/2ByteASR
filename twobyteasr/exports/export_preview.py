"""Bounded loopback transport for sampled, actual FFmpeg output frames."""
import socket
import threading


class ExportPreview:
    def __init__(self, callback, start=0, *, job=None, warning=None):
        from .export_run_log import current_export_log
        self.callback, self.start = callback, start
        self.job, self.warning, self.logger = job, warning, current_export_log()
        self.failure = None
        self.last_received_ms = self.last_delivered_ms = None
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.server.settimeout(.25)
        self.url = f'tcp://127.0.0.1:{self.server.getsockname()[1]}'
        self.closed = threading.Event()
        self.connection = None
        self.thread = threading.Thread(target=self._read, daemon=True, name='export-frame-preview')
        self.thread.start()

    def _warn(self, error):
        if self.failure is not None or self.closed.is_set():
            return
        import traceback
        self.failure = dict(observer='export_preview', exception_type=type(error).__name__,
            reason=str(error), last_received_ms=self.last_received_ms, last_delivered_ms=self.last_delivered_ms,
            traceback=''.join(traceback.format_exception(type(error),error,error.__traceback__)))
        if self.job is not None:
            self.job.export_context['preview_warning'] = self.failure
            self.job.completion_metadata.setdefault('completion_warnings', []).append(self.failure)
        try:
            if self.logger is not None:
                self.logger.note('preview_failed_export_continues',self.failure)
        except Exception as reporting_error:
            if self.job is not None:
                self.job.export_context['preview_diagnostics_error'] = str(reporting_error)
        try:
            if self.warning:
                self.warning('导出预览已停止，成片继续编码；预览错误已保存在诊断信息中。')
        except Exception as reporting_error:
            if self.job is not None:
                self.job.export_context['preview_notice_error'] = str(reporting_error)

    def _drain(self):
        # The preview is a nonessential observer, but FFmpeg still writes this
        # TCP output. Keep consuming bytes after decode failure so the main
        # video output cannot deadlock on a full socket receive buffer.
        try:
            while not self.closed.is_set() and self.connection.recv(65536):
                pass
        except OSError as error:
            self._warn(error)

    def _read(self):
        try:
            while not self.closed.is_set():
                try:
                    self.connection, _ = self.server.accept()
                    break
                except socket.timeout:
                    continue
            if self.connection is None:
                return
        except OSError as error:
            self._warn(error)
            return
        try:
            import av
            from PySide6.QtGui import QImage
            with self.connection.makefile('rb') as stream, av.open(stream, format='nut') as container:
                for frame in container.decode(video=0):
                    if self.closed.is_set():
                        break
                    if self.failure is not None:
                        continue
                    try:
                        milliseconds=(self.start+float(frame.pts*frame.time_base))*1000
                        self.last_received_ms=milliseconds
                        pixels = frame.to_ndarray(format='bgra')
                        image = QImage(pixels.data, frame.width, frame.height, pixels.strides[0], QImage.Format.Format_ARGB32).copy()
                        self.callback(image, milliseconds, '已烧录字幕')
                        self.last_delivered_ms=milliseconds
                    except Exception as error:
                        self._warn(error)
        except Exception as error:
            self._warn(error)
            self._drain()

    def close(self):
        self.closed.set()
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
        self.server.close()
        self.thread.join(timeout=2)


def run_streaming_with_preview(command, job, runner, *, warning=None, **kwargs):
    """Sample the final composite in static/animated export using the same transport."""
    if not job.preview_callback:
        return runner(command, **kwargs)
    preview = ExportPreview(job.preview_callback, job.start_seconds or 0, job=job, warning=warning)
    try:
        command = list(command)
        graph_at = command.index('-filter_complex') + 1
        map_at = command.index('-map') + 1
        original = command[map_at]
        command[graph_at] += (f';{original}split=2[finalpreviewbase][previewfull];'
            '[previewfull]fps=2:round=up:start_time=0:eof_action=pass,scale=640:-2[exportpreview]')
        command[map_at] = '[finalpreviewbase]'
        if job.duration_seconds:
            command += ['-t', f'{job.duration_seconds:.9f}']
        command += ['-map','[exportpreview]','-an','-c:v','rawvideo','-pix_fmt','bgra',
                    '-threads','1','-f','nut',preview.url]
        return runner(command, **kwargs)
    finally:
        preview.close()
