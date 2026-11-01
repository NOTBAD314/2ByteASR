"""MCP adapter to the existing Studio recognition worker."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .mcp_bridge import BridgeError


def _native_failure(message):
    from .production import error_info, safe_message
    text = safe_message(message or '原生识别没有成功交付，请检查运行日志。')
    info = error_info(RuntimeError(text))
    if any(term in text.lower() for term in ('缺少运行依赖', 'no module named', '未安装', '缺少模型', '缺少 api 密钥')):
        info['code'] = 'configuration_required'
    return BridgeError(info['code'], text)


class RecognitionOperations:
    def op_start_recognition(self, project_id: str, revision: int):
        page, project = self.require_project(project_id, revision)
        window = self.window
        saved = getattr(getattr(window, 'legacy', None), 'RUNTIME_SETTINGS', {}) or {}
        glossary = saved.get('glossary') or {}
        if (glossary.get('enable_domain_terms') and
                (project.glossary_ids or glossary.get('enabled_glossary_ids'))):
            self.bridge._require_glossary()
        if getattr(window, '_run_in_progress', False):
            raise BridgeError('busy', '已有原生识别任务正在运行。')
        if getattr(window, '_asr_config_dirty', False):
            raise BridgeError('configuration_required', '识别设置有未保存修改，请先在软件中保存或撤销。')
        if getattr(window, '_ai_has_draft', False):
            settings = getattr(getattr(window, 'legacy', None), 'RUNTIME_SETTINGS', {}) or {}
            switches = settings.get('switches') or {}
            if switches.get('enable_ai_polish', True) or switches.get('use_ai_grouping', True):
                raise BridgeError('configuration_required', '已启用的文字 AI 设置有未保存修改，请先在软件中保存或撤销。')
        path = Path(str(getattr(page.session, 'project_path', '') or ''))
        media = Path(str(getattr(project.media, 'path', '') or ''))
        if not path.is_file() or not media.is_file():
            raise BridgeError('not_ready', '请先保存工程并重新关联有效媒体文件。')
        start = getattr(window, '_handle_studio_recognition_request', None)
        if not callable(start) or not callable(getattr(window, '_cancel_run', None)):
            raise BridgeError('unsupported', '当前宿主缺少原生识别入口。')
        snapshot = self.snapshot(page, project)
        job = self.new_job('recognition', snapshot)
        job_id = job['job_id']
        if not hasattr(self, 'recognition_handoffs'):
            self.recognition_handoffs = {}
        handoff = {'valid': True}
        self.recognition_handoffs[job_id] = handoff
        def handoff_guard():
            return (handoff['valid'] and self.jobs.get(job_id) is job and
                    job.get('status') not in ('cancelling', 'cancelled', 'failed', 'interrupted') and
                    not self._closed and bool(self.bridge.settings.get('enabled')) and
                    bool(self.bridge.settings.get('allow_edits')))
        def drop_handoff():
            if self.recognition_handoffs.get(job_id) is handoff:
                self.recognition_handoffs.pop(job_id, None)
        def handoff_done(committed):
            allowed = handoff_guard()
            drop_handoff()
            if committed and allowed:
                self.finish_job(job, job.get('result') or {})
            elif job.get('status') == 'cancelling':
                self.finish_job(job, job.get('result') or {}, status='cancelled')
            else:
                self.fail_job(job, BridgeError('handoff_refused', '识别结果已保存，但工程交接已取消或不再有效。'))
        prior = getattr(window, 'worker', None)
        page._recognition_replace_baseline_ids = {cue.id for cue in project.cues}
        page._recognition_autosave_generation = int(getattr(page, '_autosave_generation', 0) or 0)
        page._recognition_undo_count = int(page.undo_stack.count())
        start_error = None
        try:
            start('start_final', str(media.resolve()), str(path.resolve()), noninteractive=True,
                  handoff_guard=handoff_guard, handoff_done=handoff_done)
        except Exception as exc:
            start_error = exc
        worker = getattr(window, 'worker', None)
        native_id = str(getattr(window, '_active_job_id', '') or '')
        if worker is None or worker is prior or not native_id:
            reason = str(getattr(window, '_run_block_reason', '') or '原生预检未启动识别，请检查软件中的提示。')
            code = str(getattr(window, '_run_block_code', '') or 'not_ready')
            drop_handoff()
            self.fail_job(job, start_error or BridgeError(code, reason))
            return self.public_job(job)
        if any(not hasattr(worker, name) for name in ('event_received', 'result_ready', 'unexpected_error', 'finished', 'isRunning')):
            if getattr(window, 'worker', None) is worker and getattr(window, '_active_job_id', '') == native_id:
                window._cancel_run()
            drop_handoff()
            self.fail_job(job, BridgeError('unsupported', '原生识别 worker 信号不兼容，已请求取消。'))
            return self.public_job(job)
        native_snapshot = (getattr(window, '_studio_recognition_context', None) or {}).get('snapshot', {})
        if native_snapshot.get('project_id') != project_id:
            window._cancel_run()
            drop_handoff()
            self.fail_job(job, BridgeError('result_mismatch', '原生识别工程身份不一致，已请求取消。'))
            return self.public_job(job)
        self.update_job(job, result={'native_job_id': native_id},
                        message='原生启动过程返回异常，正在跟踪已启动的任务。' if start_error else '')
        terminal = {'done': False}
        bindings = []
        def owned():
            return not terminal['done']
        def fail(code, message):
            if owned():
                terminal['done'] = True
                drop_handoff()
                self.fail_job(job, BridgeError(code, message))
        def event_received(event):
            if owned() and str(getattr(event, 'job_id', '')) == native_id:
                self.update_job(job, progress={'stage': str(getattr(event, 'label', '') or ''),
                    'done': int(getattr(event, 'stage_index', 0) or 0),
                    'total': int(getattr(event, 'stage_total', 0) or 0)})
        def result_ready(result):
            if not owned() or str(getattr(result, 'job_id', '')) != native_id:
                return
            rows = tuple(getattr(result, 'results', ()) or ())
            if not rows or any(os.path.normcase(os.path.abspath(str(r.media_path))) !=
                    os.path.normcase(str(media.resolve())) for r in rows):
                fail('result_mismatch', '原生结果媒体路径与本次任务不一致。')
                return
            successful = [r for r in rows if r.status in ('success', 'degraded_success')]
            problems = [r for r in rows if r.status not in ('success', 'degraded_success')]
            if len(successful) > 1 or any(r.status not in ('failed', 'cancelled', 'skipped') for r in problems):
                fail('result_mismatch', '原生返回多个结果工程或未知状态，请在软件中检查。')
                return
            if not successful:
                if job.get('status') == 'cancelling' or all(r.status == 'cancelled' for r in rows):
                    terminal['done'] = True
                    drop_handoff()
                    self.finish_job(job, {'native_job_id': native_id}, status='cancelled')
                else:
                    details = [str(r.error) for r in rows if getattr(r, 'error', '')]
                    failure = _native_failure('；'.join(details))
                    fail(failure.code, str(failure))
                return
            row = successful[0]
            if str(getattr(row, 'job_id', '')) != native_id:
                fail('result_mismatch', '原生结果不属于本次任务。')
                return
            if job.get('status') == 'cancelling' or row.status == 'cancelled':
                terminal['done'] = True
                drop_handoff()
                self.finish_job(job, {'native_job_id': native_id}, status='cancelled')
                return
            if row.status not in ('success', 'degraded_success'):
                fail('recognition_failed', '原生识别没有成功交付，请检查运行日志。')
                return
            if os.path.normcase(os.path.abspath(str(row.media_path))) != os.path.normcase(str(media.resolve())):
                fail('result_mismatch', '识别结果媒体路径不匹配。')
                return
            try:
                from ..recognition.recognition_result import verify_result_reference
                result_project = verify_result_reference(row.result_ref_json, project_path=row.project_path)
                ref = json.loads(row.result_ref_json)
                timeline = result_project.generation_metadata.get('timeline_recognition') or {}
                if (ref['job_id'] != native_id or timeline.get('source_project_id') != project_id or
                    os.path.normcase(os.path.abspath(timeline.get('source_project_path') or '')) != os.path.normcase(str(path.resolve())) or
                    timeline.get('fingerprint') != ref['media_fingerprint'] or
                    (native_snapshot.get('project_revision') and timeline.get('source_project_revision') != native_snapshot['project_revision'])):
                    raise ValueError('identity mismatch')
            except (OSError, ValueError, TypeError, KeyError):
                fail('verify_failed', '原生结果身份或工程凭据校验失败。')
                return
            terminal['done'] = True
            from .production import safe_message
            self.update_job(job, message='识别结果已验证，正在等待工程交接。', result={'native_job_id': native_id, 'outcome': row.status,
                'project_id': result_project.project_id, 'project_path': str(Path(row.project_path).resolve()),
                'result_reference': ref, 'cue_count': len(result_project.cues),
                'partial_failures': [{'status': r.status, 'message': safe_message(r.error)} for r in problems]})
        def unexpected_error(message):
            failure = _native_failure(message)
            fail(failure.code, str(failure))
        def finished():
            if owned():
                if job.get('status') == 'cancelling':
                    terminal['done'] = True
                    drop_handoff()
                    self.finish_job(job, {'native_job_id': native_id}, status='cancelled')
                else:
                    fail('missing_result', '识别结束但未收到可验证结果。')
            for signal, callback in bindings:
                try:
                    signal.disconnect(callback)
                except (RuntimeError, TypeError):
                    pass
        def cancel():
            handoff['valid'] = False
            if owned() and getattr(window, 'worker', None) is worker and getattr(window, '_active_job_id', '') == native_id:
                window._cancel_run()
        self.cancel_callbacks[job_id] = cancel
        bindings.extend(((worker.event_received, event_received), (worker.result_ready, result_ready),
                         (worker.unexpected_error, unexpected_error), (worker.finished, finished)))
        for signal, callback in bindings:
            signal.connect(callback)
        from PySide6.QtCore import QTimer
        def recover_early():
            if owned() and not worker.isRunning():
                tasks = tuple(getattr(window, '_completion_tasks', ()) or ())
                rows = tuple(item for item, _project in tasks if str(getattr(item, 'job_id', '')) == native_id)
                if rows:
                    from ..recognition.service import QueueResult
                    result_ready(QueueResult(rows, 0.0, job_id=native_id))
                if owned():
                    finished()
        QTimer.singleShot(0, recover_early)
        return self.public_job(job)
