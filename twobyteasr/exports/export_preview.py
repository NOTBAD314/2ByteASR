"""Bounded loopback transport for sampled, actual FFmpeg output frames."""
import socket
import threading


class ExportPreview:
    def __init__(self, callback, start=0):
        self.callback, self.start = callback, start
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.server.settimeout(.25)
        self.url = f'tcp://127.0.0.1:{self.server.getsockname()[1]}'
        self.closed = threading.Event()
        self.connection = None
        self.thread = threading.Thread(target=self._read, daemon=True, name='export-frame-preview')
        self.thread.start()

    def _read(self):
        import av
        from PySide6.QtGui import QImage
        try:
            while not self.closed.is_set():
                try:
                    self.connection, _ = self.server.accept()
                    break
                except socket.timeout:
                    continue
            if self.connection is None:
                return
            with self.connection.makefile('rb') as stream, av.open(stream, format='nut') as container:
                for frame in container.decode(video=0):
                    if self.closed.is_set():
                        break
                    pixels = frame.to_ndarray(format='bgra')
                    image = QImage(pixels.data, frame.width, frame.height, pixels.strides[0], QImage.Format.Format_ARGB32).copy()
                    self.callback(image, (self.start + float(frame.pts*frame.time_base))*1000, '已烧录字幕')
        except (OSError, ValueError, av.error.FFmpegError):
            pass

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


def run_streaming_with_preview(command, job, runner, **kwargs):
    """Sample the final composite in static/animated export using the same transport."""
    if not job.preview_callback:
        return runner(command, **kwargs)
    preview = ExportPreview(job.preview_callback, job.start_seconds or 0)
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
