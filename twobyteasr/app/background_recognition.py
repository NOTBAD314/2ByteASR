"""Application-owned queue state and immutable per-video deliveries.

The queue remains owned by MainWindow/PipelineWorker. This mixin holds paths and
references only; it never saves a project or retains editable project snapshots.
"""
from pathlib import Path


class BackgroundRecognitionMixin:
    def _begin_background_queue(self, job_id):
        self._background_job = job_id
        self._background_ready = {}
        self._background_terminal = set()
        self._background_failures = set()
        self._background_cancelled = set()
        self._background_total = len(set(map(str, self.media_paths)))
        self._background_current = ''
        self._background_stage = '准备中'
        self._background_fraction = ''
        self._background_running = True

    def _receive_background_event(self, event):
        if getattr(self, '_background_job', None) != event.job_id:
            return
        payload = event.payload or {}
        if event.kind == 'media_delivered':
            self._accept_background_delivery(payload.get('result') or {})
        elif event.kind == 'media_started':
            self._background_current = Path(event.media_path or payload.get('media_path', '')).name
            self._background_stage = '准备中'
            self._background_fraction = ''
        elif event.kind in {'media_failed', 'media_cancelled'}:
            media = str(event.media_path or payload.get('media_path', ''))
            self._background_terminal.add(media)
            (self._background_failures if event.kind == 'media_failed' else self._background_cancelled).add(media)
            self._background_stage = '失败' if event.kind == 'media_failed' else '已取消'
        elif event.kind in {'stage_started', 'stage_progress', 'asr_progress', 'asr_evidence_delta',
                           'cloud_batch_progress', 'studio_project_saving'}:
            self._background_stage = str(event.label or payload.get('stage_name') or self._background_stage)
            # Only real counters reported by this stage are displayed.
            self._background_fraction = ''
            for done, total in (('completed_batches', 'total_batches'), ('completed_chunks', 'total_chunks')):
                if payload.get(total) and done in payload:
                    self._background_fraction = f'{payload[done]} / {payload[total]}'
                    break

    def _accept_background_delivery(self, result):
        # Emitted only after service validates the atomic saved project, media
        # identity and usable timeline. No current-open-project lookup here.
        import json
        reference = result.get('result_ref_json', '')
        try:
            ref = json.loads(reference) if isinstance(reference, str) else dict(reference)
            path = str(Path(result['project_path']).resolve())
            if (ref['job_id'] != self._background_job or str(Path(ref['path']).resolve()) != path
                    or ref['project_id'] != result['project_id'] or not Path(path).is_file()):
                return False
        except (OSError, ValueError, TypeError, KeyError):
            return False
        if path in self._background_ready:
            return True
        self._background_ready[path] = reference
        self.__dict__.setdefault('_delivered_project_refs', {})[path] = reference
        studio = self.built_page('studio')
        if studio is not None:
            studio._refresh_visible_library()
        return True

    def _background_reference(self, item):
        from ..recognition.recognition_result import working_reference
        path = str(Path(item.project_path).resolve()) if item.project_path else ''
        accepted = getattr(self, '_delivered_project_refs', {}).get(path)
        return working_reference(accepted) if accepted and accepted == item.result_ref_json else item.result_ref_json

    def _finish_background_queue(self, *, result=None, error=''):
        if not hasattr(self, '_background_job'):
            return
        if result is not None:
            self._background_failures = {row.media_path for row in result.results if row.status == 'failed'}
            self._background_cancelled = {row.media_path for row in result.results if row.status == 'cancelled'}
        self._background_running = False
        self._background_stage = error or '后台任务已结束'
        self._background_fraction = ''
