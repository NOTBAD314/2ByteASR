"""Shared task lifecycle and explicit navigation for Studio subtitle work."""

from __future__ import annotations

from .studio_task_progress import SubtitleTask


class StudioSubtitleTaskMixin:
    def _new_subtitle_task(self, kind, cues):
        task = SubtitleTask(kind, tuple(cue.id for cue in cues))
        task.project = self.project
        self.__dict__.setdefault('_subtitle_tasks', {})[task.task_id] = task
        panel = self._subtitle_task_panel()
        panel.add_task(task)
        if not hasattr(self, '_subtitle_tasks_timer'):
            from PySide6.QtCore import QTimer
            self._subtitle_tasks_timer = QTimer(self)
            self._subtitle_tasks_timer.setInterval(500)
            self._subtitle_tasks_timer.timeout.connect(self._refresh_subtitle_task_entry)
            self._subtitle_tasks_timer.start()
        return task

    def _refresh_subtitle_task_entry(self):
        button = getattr(self, 'subtitle_tasks_button', None)
        if button is None:
            return
        tasks = list(getattr(self, '_subtitle_tasks', {}).values())
        for task in tasks:
            if task.ended is None and task.project is not self.project:
                self._cancel_subtitle_task(task.task_id)
                task.finish(cancelled=True)
        active = [task for task in tasks if task.ended is None and task.project is self.project]
        from ..i18n import tr
        text = tr('{count} 项进行中', count=len(active)) if active else tr('任务进度')
        if button.text() != text:
            button.setText(text)
        finished = [task for task in tasks if task.ended is not None and task.project is self.project]
        unseen = bool(finished) and max(task.ended for task in finished) > getattr(self, '_subtitle_tasks_seen', 0.)
        state = 'active' if active else ('done' if unseen else 'idle')
        progress = 0.
        if active:
            done = total = 0
            for task in active:
                counts = task.counts()
                done += counts['processed']
                total += counts['total']
            progress = done / total if total else 0.
        self._paint_subtitle_task_entry(button, state, progress)
        lines = [task.summary() for task in (active or tasks[-1:])]
        button.setToolTip('\n'.join(lines) if lines else '查看字幕任务进度与结果')

    def _paint_subtitle_task_entry(self, button, state, progress):
        from PySide6.QtCore import Qt
        key = (state, round(progress, 2))
        if getattr(self, '_subtitle_task_entry_key', None) == key:
            return
        self._subtitle_task_entry_key = key
        if button.property('taskState') != state:
            button.setProperty('taskState', state)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if state == 'active'
                                      else Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.style().unpolish(button)
            button.style().polish(button)
        if state == 'active':
            # The pill fills with the accent wash as ranges finish.
            from ..design.themed_icons import _active_theme
            theme = _active_theme(None)
            edge = min(0.999, max(0.001, progress))
            button.setStyleSheet(
                'QToolButton#studioSubtitleTasks { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, '
                f'stop:0 {theme.accent_soft}, stop:{edge:.3f} {theme.accent_soft}, '
                f'stop:{edge + 0.001:.3f} {theme.accent_tint}, stop:1 {theme.accent_tint}); }}')
        else:
            button.setStyleSheet('')
        # A crowded bar squeezes a button to its minimum: the pill claims
        # its full text; the idle / done circle is a fixed 32 px.
        if state == 'active':
            button.setMaximumWidth(16777215)
            button.setMinimumWidth(0)
            button.setMinimumWidth(button.sizeHint().width())
        else:
            button.setFixedWidth(32)
        button.updateGeometry()
        dot = getattr(self, 'subtitle_tasks_dot', None)
        if dot is not None:
            dot.setVisible(state == 'done')
            dot.move(22, 1)
            dot.raise_()

    def _subtitle_task_panel(self):
        panel = getattr(self, '_subtitle_tasks_dialog', None)
        if panel is None:
            from .studio_task_panel import SubtitleTaskPanel
            panel = SubtitleTaskPanel(self)
            panel.locate.connect(self._locate_subtitle_task_range)
            panel.retry.connect(self._retry_subtitle_task_range)
            panel.cancel.connect(self._cancel_subtitle_task)
            self._subtitle_tasks_dialog = panel
        return panel

    def show_subtitle_tasks(self):
        tasks = list(getattr(self, '_subtitle_tasks', {}).values())
        if self.project and not any(task.project is self.project for task in tasks):
            state = self.project.studio_state.get('ai_sentence_refine') or {}
            rows = state.get('range_results') or []
            if rows:
                from types import SimpleNamespace
                ids = list(dict.fromkeys(key for row in rows for key in row.get('cue_ids', ())))
                task = self._new_subtitle_task('AI 断句', [SimpleNamespace(id=key) for key in ids])
                task.started -= max(0., float(state.get('elapsed_seconds', 0)))
                for row in rows:
                    task.update(dict(row))
                task.finish(cancelled=state.get('last_status') == 'cancelled')
        import time
        self._subtitle_tasks_seen = time.monotonic()
        self._refresh_subtitle_task_entry()
        panel = self._subtitle_task_panel()
        panel.show()
        panel.raise_()
        panel.activateWindow()
        panel.refresh()

    def _subtitle_task_event(self, payload):
        task = getattr(self, '_subtitle_tasks', {}).get(payload.get('task_id'))
        if task is None or task.project is not self.project or task.cancelled:
            return
        task.update(payload.get('event', {}))

    def _cancel_subtitle_task(self, task_id):
        task = getattr(self, '_subtitle_tasks', {}).get(task_id)
        if task is None or task.ended:
            return
        task.cancelled = True
        task.phase = '正在安全取消'
        task.revision += 1
        cancel = getattr(task, 'cancel_action', None)
        if cancel:
            cancel()

    def _locate_subtitle_task_range(self, payload):
        task = getattr(self, '_subtitle_tasks', {}).get(payload['task_id'])
        if self.project is None or task is None or task.project is not self.project:
            return
        row = payload['record']
        existing = {cue.id for cue in self.project.cues}
        cue_id = next((key for key in row.get('output_ids', row.get('cue_ids', ())) if key in existing), '')
        if cue_id:
            self.select_cue(cue_id)
            self._seek(int(row.get('start_ms') or 0) / 1000.)
            if getattr(task, 'result', None) is not None:
                self._show_reasr_result(task.result)

    def _retry_subtitle_task_range(self, payload):
        task = getattr(self, '_subtitle_tasks', {}).get(payload['task_id'])
        if self.project is None or task is None or task.project is not self.project or task.ended is None:
            return
        ids = payload['record'].get('cue_ids', ())
        if task.kind == 'AI 断句':
            self.run_sentence_refine(whole_project=False, retry_ids=ids)
        elif task.kind == '单条重新识别' and ids:
            self._reasr_current(cue_id=ids[0])
        elif task.kind == '工程重新识别':
            self._subtitle_task_panel().hide()
            self._open_recognition_sheet()

    def _subtitle_task_current(self, task):
        return bool(self.project is not None and task and task.ended is None
                    and task.project is self.project and not task.cancelled)
