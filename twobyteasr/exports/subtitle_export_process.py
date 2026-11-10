"""Data-only request/reply on private inherited pipes of the owned worker.

The pickle stream is used only between this application and its own child.
No file, network response or external IPC is deserialized by this entry.
"""
import pickle
import sys
from pathlib import Path


class FileCancellation:
    def __init__(self, path):
        self.path = Path(path)

    def is_set(self):
        return self.path.is_file()


def main():
    request = pickle.load(sys.stdin.buffer)
    from .subtitle_export_task import SubtitleExportTask
    from .studio_subtitle_export import export_subtitle_artifacts, export_language_layers
    task = SubtitleExportTask(request['snapshot'], *request['parameters'],
        export_subtitle_artifacts, export_language_layers)
    task.work.task_id = request['task_id']
    task.cancel = FileCancellation(request['cancel_path'])
    task.work.cancel = task.cancel
    task._run()
    reply = dict(artifacts=task.artifacts, layered=task.layered,
        error=str(task.error) if task.error is not None else '', details=task.details,
        exception_type=task.exception_type, timings=task.work.timings,
        failed_stage=task.work.stage if task.error is not None else '',
        peak_bytes=task.work.peak_bytes, cue_count=task.cue_count)
    reply['validation_cache'] = dict(receipt_checks=task.work.receipt_checks, receipt_hits=task.work.receipt_hits)
    pickle.dump(reply, sys.stdout.buffer, protocol=5)
    sys.stdout.buffer.flush()
    return 0
