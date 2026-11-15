"""Application-owned queue presentation and immutable per-video deliveries.

The queue remains owned by MainWindow/PipelineWorker. This view holds paths and
references only; it never saves a project or retains editable project snapshots.
"""
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox
from ..i18n_widgets import bind_text


class BackgroundRecognitionMixin:
    def _ensure_background_queue(self):
        if hasattr(self, 'background_queue_bar'):
            return
        from ..design.soft_widgets import WrapLayout
        bar = self.background_queue_bar = QWidget(self)
        bar.setObjectName('backgroundRecognitionBar')
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(10, 5, 10, 5)
        self.background_queue_summary = QLabel(bar)
        self.background_queue_summary.setWordWrap(True)
        layout.addWidget(self.background_queue_summary)
        actions = WrapLayout(spacing=8, fill=False)
        layout.addLayout(actions)
        self.background_queue_projects = QComboBox(bar)
        self.background_queue_projects.setMinimumContentsLength(12)
        self.background_queue_projects.setMaximumWidth(320)
        actions.addWidget(self.background_queue_projects)
        for attr, label, callback in (
                ('background_queue_open', '开始校对', self._open_background_project),
                ('background_queue_library', '工程库', self._open_background_library),
                ('background_queue_detail', '后台任务', lambda: self._switch_page(1)),
                ('background_queue_results', '结果与重试', lambda: self._switch_page(2))):
            button = QPushButton(bar)
            bind_text(button, label)
            button.clicked.connect(callback)
            setattr(self, attr, button)
            actions.addWidget(button)
        self.content_layout.insertWidget(0, bar)
        bar.hide()

    def _begin_background_queue(self, job_id):
        self._ensure_background_queue()
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
        self.background_queue_projects.clear()
        self._refresh_background_queue()

    def _refresh_background_queue(self):
        if not hasattr(self, 'background_queue_bar'):
            return
        ready = len(getattr(self, '_background_ready', {}))
        total = getattr(self, '_background_total', 0)
        running = getattr(self, '_background_running', False)
        pieces = [f'已完成 {ready} / {total} 个视频']
        if running:
            pieces += [getattr(self, '_background_current', ''), getattr(self, '_background_stage', ''),
                       getattr(self, '_background_fraction', '')]
        else:
            pieces += [getattr(self, '_background_stage', '后台任务已结束')]
        failures = len(getattr(self, '_background_failures', ()))
        cancelled = len(getattr(self, '_background_cancelled', ()))
        if failures: pieces.append(f'失败 {failures}')
        if cancelled: pieces.append(f'取消 {cancelled}')
        text = ' · '.join(str(part) for part in pieces if part)
        if self.background_queue_summary.text() != text:
            self.background_queue_summary.setText(text)
        self.background_queue_open.setEnabled(bool(ready))
        self.background_queue_projects.setVisible(bool(ready))
        self.background_queue_results.setVisible(not running)
        self.background_queue_detail.setVisible(running)
        self.background_queue_bar.setVisible(bool(total))

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
        self._refresh_background_queue()

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
        self.background_queue_projects.addItem(Path(result['media_path']).name, path)
        studio = self.built_page('studio')
        if studio is not None:
            studio._refresh_visible_library()
        self._refresh_background_queue()
        return True

    def _background_reference(self, item):
        from ..recognition.recognition_result import working_reference
        path = str(Path(item.project_path).resolve()) if item.project_path else ''
        accepted = getattr(self, '_delivered_project_refs', {}).get(path)
        return working_reference(accepted) if accepted and accepted == item.result_ref_json else item.result_ref_json

    def _open_background_project(self):
        from ..recognition.recognition_result import working_reference
        path = self.background_queue_projects.currentData()
        reference = getattr(self, '_background_ready', {}).get(path)
        if path and reference:
            self.open_studio_project(path, source='background_delivery', expected_result_ref=working_reference(reference))

    def _open_background_library(self):
        studio = self.built_page('studio')
        if studio is None:
            self.open_studio_project(source='background_library')
        elif studio.show_project_hub():
            self._switch_page(studio)

    def _finish_background_queue(self, *, result=None, error=''):
        if not hasattr(self, 'background_queue_bar'):
            return
        if result is not None:
            self._background_failures = {row.media_path for row in result.results if row.status == 'failed'}
            self._background_cancelled = {row.media_path for row in result.results if row.status == 'cancelled'}
        self._background_running = False
        self._background_stage = error or '后台任务已结束'
        self._background_fraction = ''
        self._refresh_background_queue()
