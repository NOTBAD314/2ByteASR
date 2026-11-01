"""MCP media operations delegated to the existing Studio services."""
from __future__ import annotations

import copy
import math
import tempfile
import uuid
from pathlib import Path

from . import mcp_common as common
from .mcp_bridge import BridgeError


def _path(value, *, file=True):
    path = Path(value).expanduser()
    if not path.is_absolute() or any(common.is_reparse_point(p) for p in (path, *path.parents)):
        raise BridgeError('out_of_scope', '路径必须为绝对路径，且不能经过链接目录')
    if file and not path.is_file():
        raise BridgeError('not_found', '指定文件不存在')
    return path.resolve()


def _output(settings, page, name, destination):
    saved = page.session.project_path
    if not saved:
        raise BridgeError('unsaved_project', '请先保存工程')
    stem = common.safe_file_stem(name or Path(saved).stem)
    if stem is None:
        raise BridgeError('bad_name', '名称不能包含路径、保留名或控制字符')
    if destination in ('', 'project_folder'):
        root = _path(str(Path(saved).parent), file=False)
        directory = root / common.EXPORT_FOLDER
    elif destination == 'authorized_folder':
        root = directory = _path(str(settings.get('export_dir') or ''), file=False)
        if not root.is_dir():
            raise BridgeError('not_permitted', '请在原生MCP设置中选择已存在的导出文件夹')
    else:
        raise BridgeError('bad_params', 'destination只能为project_folder或authorized_folder')
    target = directory / (stem + '.mp4')
    _check_output(root, target)
    return root, target


def _check_output(root, target):
    _path(str(target), file=False)
    if not root.is_dir() or not common.inside(root, target):
        raise BridgeError('out_of_scope', '导出位置不在允许目录内')
    if target.exists():
        raise BridgeError('output_exists', '成片已存在，请使用其他名称；不会覆盖')


def _check_pause_input(project, analysis):
    """A project revision alone does not detect a replaced source file."""
    from ..recognition.recognition_input import capture_recognition_snapshot
    expected = analysis.get('fingerprint')
    if not isinstance(expected, str) or not expected:
        raise BridgeError('invalid_job', '停顿结果缺少原生素材身份，请重新检测')
    try:
        current = capture_recognition_snapshot(project)['fingerprint']
    except (OSError, ValueError) as exc:
        raise BridgeError('input_changed', '检测使用的素材已不可用，请重新关联后检测；未执行剪切') from exc
    if current != expected:
        raise BridgeError('input_changed', '检测后素材或音频输入已变化，请重新检测；未执行剪切')


def _render(project, project_path, root, target, token, progress):
    from ..exports.export_timeline import write_export_ass
    from ..exports.studio_render import RenderJob, RenderSettings, run_render_job, validate_export_config
    from ..exports.video_export import capture_video_graph
    from ..rendering.advanced_renderer import AdvancedRendererBackend, project_requires_advanced
    from ..system.platform_media import ffmpeg_tool
    from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
    from ..timeline.studio_sequence_mapper import export_source_slices

    if token.is_cancelled:
        raise InterruptedError('成片导出已取消')
    _check_output(root, target)
    ffmpeg = Path(ffmpeg_tool())
    if not ffmpeg.is_file() or not ffmpeg.with_name('ffprobe' + ffmpeg.suffix).is_file():
        raise BridgeError('configuration_required', '成片导出缺少FFmpeg/FFprobe，请检查原生组件设置')
    duration = timeline_duration_ms(project)
    if duration <= 0:
        raise BridgeError('empty_timeline', '当前时间轴为空')
    settings = RenderSettings()
    settings.validate()
    graph = capture_video_graph(project)
    advanced = project_requires_advanced(project, start_ms=0, end_ms=duration)
    if advanced:
        AdvancedRendererBackend().require_available()
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_output(root, target)
    cache = target.parent / ('.mcp-video-' + uuid.uuid4().hex)
    cache.mkdir()
    ass = cache / 'subtitles.ass'
    snapshot = write_export_ass(project, ass, fps=settings.fps or None)
    sequence = sequence_of(project)
    slices = () if sequence.is_linear_source() else tuple(export_source_slices(sequence, None, duration))
    job = RenderJob(project.media.path, str(ass), str(target), settings,
                    duration_seconds=duration / 1000, edit_segments=slices, video_graph=graph,
                    export_project_data=snapshot.to_dict(), export_context={'project_path': project_path})
    validate_export_config(job)
    runner = (lambda *args, **kwargs: AdvancedRendererBackend().render(snapshot, *args, **kwargs)) if advanced else run_render_job
    result = Path(runner(ffmpeg, job, progress=progress,
                         cancelled=lambda: token.is_cancelled))
    if result.resolve() != target.resolve() or not result.is_file() or result.stat().st_size <= 0:
        raise BridgeError('export_failed', '原生渲染未返回有效成片')
    return {'output_path': str(result), 'size_bytes': result.stat().st_size,
            'format': 'mp4', 'overwritten': False, 'completion': dict(job.completion_metadata)}


class MediaOperations:
    def _create_media_target(self, media_path, name):
        from ..projects.studio_project import project_library_root, PROJECT_SUFFIX
        if self.bridge.settings.get('scope', 'current') != 'library':
            raise BridgeError('out_of_scope', '新建工程需要工程库范围，请在应用设置 → 外部 AI（MCP）中选择工程库；当前范围未改变')
        media = _path(media_path)
        stem = common.safe_file_stem(name or media.stem)
        if stem is None:
            raise BridgeError('bad_name', '工程名称不能包含路径或保留名')
        root = _path(str(project_library_root()), file=False)
        target = root / stem / (stem + PROJECT_SUFFIX)
        _path(str(target), file=False)
        if not common.inside(root, target):
            raise BridgeError('out_of_scope', '新工程目标不在工程库内，请检查应用设置 → 外部 AI（MCP）的范围及工程库目录')
        if target.parent.exists():
            raise BridgeError('output_exists', '同名工程目录已存在，请选择其他名称')
        return media, target

    def _require_open_scope(self, path):
        from ..projects.studio_project import project_library_root
        scope = self.bridge.settings.get('scope', 'current')
        if scope == 'library':
            root = _path(str(project_library_root()), file=False)
            if common.inside(root, path):
                return
        elif scope == 'current':
            page = self.bridge._page()
            current = getattr(getattr(page, 'session', None), 'project_path', None)
            if page is not None and page.project is not None and current and Path(current).resolve() == path.resolve():
                return
        raise BridgeError('out_of_scope', '当前MCP范围不允许打开此工程，请在应用设置 → 外部 AI（MCP）中检查范围；仅当前工程范围只能重开同一路径工程')

    def _clear_studio_probe_marker(self, job):
        if getattr(self.window, '_mcp_studio_probe_suppressed', None) == job['job_id']:
            del self.window._mcp_studio_probe_suppressed

    def finish_job(self, job, result, status='completed'):
        try:
            return super().finish_job(job, result, status=status)
        finally:
            self._clear_studio_probe_marker(job)

    def fail_job(self, job, exc):
        try:
            return super().fail_job(job, exc)
        finally:
            self._clear_studio_probe_marker(job)

    def _media_page(self):
        if not self.bridge.settings.get('enabled') or not self.bridge.settings.get('allow_edits'):
            raise BridgeError('not_permitted', '请检查应用设置 → 外部AI（MCP）的访问和修改开关')
        page = self.bridge._page()
        if page is not None:
            self._validate_media_page(page)
        self.require_idle()
        return page

    def _validate_media_page(self, page):
        if (getattr(page, '_manual_save_in_progress', False)
                or (page.project is not None and not page.undo_stack.isClean())
                or getattr(page, '_recovered_autosave_pending', False)):
            raise BridgeError('unsaved_changes', '当前工程有未保存修改，请先保存')

    def _prepare_media_page(self, kind, operation):
        """Use the native asynchronous Studio entry, never its pending property."""
        from PySide6.QtCore import QTimer
        page = self._media_page()
        if page is not None:
            return operation(page, None)
        pending = self.window.__dict__.get('_studio_entry_pending')
        if pending is not None and pending[0]:
            raise BridgeError('busy', '原生正在打开其他工程，请等待其完成')
        opener = getattr(self.window, 'open_studio_project', None)
        if not callable(opener):
            raise BridgeError('not_ready', '原生Studio导航入口尚未就绪')
        job = self.new_job(kind, {})
        self.window._mcp_studio_probe_suppressed = job['job_id']
        self.update_job(job, message='正在创建原生字幕编辑器，尚未创建或打开目标工程')
        waiting = {'active': True}
        owner = [None, None]
        def cancel():
            waiting['active'] = False
            session = self.window.__dict__.get('_studio_loading_session')
            if (owner[0] is not None and session is owner[0]
                    and getattr(session, 'generation', None) == owner[1]
                    and getattr(session, 'active', False)):
                self.window._cancel_studio_construction()
            self.finish_job(job, {'message': '已取消等待编辑器；未执行目标工程操作'}, status='cancelled')
        self.cancel_callbacks[job['job_id']] = cancel
        def ready(prepared):
            if not waiting['active'] or job.get('status') != 'running':
                return
            waiting['active'] = False
            try:
                self.require_access('allow_edits')
                self.require_idle(exclude_job_id=job['job_id'])
                if prepared is None or self.bridge._page() is not prepared or prepared.project is not None:
                    raise BridgeError('stale_project', '等待期间原生工程已变化，未执行目标工程操作')
                self._validate_media_page(prepared)
                operation(prepared, job)
            except Exception as exc:
                self.fail_job(job, exc)
        try:
            opener(None, source='mcp_production', on_ready=ready)
            session = self.window.__dict__.get('_studio_loading_session')
            owner[:] = [session, getattr(session, 'generation', None)]
        except Exception as exc:
            waiting['active'] = False
            self.fail_job(job, exc)
        def timeout():
            if waiting['active'] and job.get('status') == 'running':
                cancel()
                self.fail_job(job, BridgeError('studio_timeout', '原生编辑器准备超时，未执行目标工程操作'))
        def watch_navigation():
            if not waiting['active'] or job.get('status') != 'running':
                return
            session = self.window.__dict__.get('_studio_loading_session')
            pending = self.window.__dict__.get('_studio_entry_pending')
            superseded = (session is not owner[0] or getattr(session, 'generation', None) != owner[1]
                          or (pending is not None and pending[1].get('on_ready') is not ready))
            if superseded:
                waiting['active'] = False
                self.fail_job(job, BridgeError('stale_project', '等待期间用户切换了原生导航，未执行目标工程操作'))
                return
            QTimer.singleShot(50, watch_navigation)
        QTimer.singleShot(50, watch_navigation)
        QTimer.singleShot(180000, timeout)
        return self.public_job(job)

    def _open_media_project(self, page, path, job=None):
        from PySide6.QtCore import QTimer
        self._require_open_scope(path)
        job = job if job is not None else self.new_job('open_project', {})
        self.window._mcp_studio_probe_suppressed = job['job_id']
        initial_project = page.project
        initial_generation = getattr(page.session, 'generation', None)
        state = {'valid': True, 'committed': False}
        gate_owner = [None, None]
        def guard():
            allowed = (state['valid'] and job.get('status') == 'running' and not self._closed
                       and self.bridge.settings.get('enabled') and self.bridge.settings.get('allow_edits'))
            try:
                self._require_open_scope(path)
            except BridgeError:
                allowed = False
            native_target_assigned = (page.project is not initial_project and page.project is not None
                                      and getattr(page.session, 'project_path', None) is not None
                                      and Path(page.session.project_path).resolve() == path.resolve())
            if not state['committed'] and not native_target_assigned:
                allowed = allowed and page.project is initial_project
                allowed = allowed and getattr(page.session, 'generation', None) == initial_generation
                allowed = allowed and (page.project is None or page.undo_stack.isClean())
            if not allowed:
                state['valid'] = False
            return bool(allowed)
        handoff = None
        def done(committed):
            state['committed'] = bool(committed)
            if getattr(page, '_mcp_project_handoff', None) is handoff:
                del page._mcp_project_handoff
            if not committed and job.get('status') in ('running', 'cancelling'):
                self.fail_job(job, BridgeError('open_cancelled', '原生工程载入已中止，原工程及文件保留'))
        handoff = (str(path.resolve()), guard, done)
        page._mcp_project_handoff = handoff
        def cancel():
            state['valid'] = False
            gate = gate_owner[0]
            generation = gate_owner[1]
            if gate is None and getattr(page, '_mcp_project_handoff', None) is handoff:
                gate = getattr(page, '_readiness', None)
                generation = getattr(gate, 'generation', None)
            if (gate is not None and getattr(page, '_readiness', None) is gate
                    and getattr(gate, 'generation', None) == generation
                    and getattr(gate, 'active', False) and Path(gate.path).resolve() == path.resolve()):
                gate.cancel(navigate=False)
            if getattr(page, '_mcp_project_handoff', None) is handoff:
                del page._mcp_project_handoff
            self.finish_job(job, {'project_path': str(path), 'message': '已取消打开；工程文件保留'}, status='cancelled')
        self.cancel_callbacks[job['job_id']] = cancel
        def ready():
            try:
                if job.get('status') not in ('running', 'cancelling'):
                    return
                if not guard():
                    raise BridgeError('open_cancelled', 'MCP权限或当前工程已变化，未确认打开结果')
                self.require_access('allow_edits')
                if page.project is None or Path(page.session.project_path).resolve() != path.resolve():
                    raise BridgeError('wrong_project', '原生打开结果与请求工程不同')
                self.finish_job(job, self.snapshot(page, page.project))
            except Exception as exc:
                self.fail_job(job, exc)
        try:
            page.open_project(path, on_ready=ready)
        except Exception as exc:
            if getattr(page, '_mcp_project_handoff', None) is handoff:
                del page._mcp_project_handoff
            self.fail_job(job, exc)
        gate = getattr(page, '_readiness', None)
        gate_owner[:] = [gate, getattr(gate, 'generation', None)]
        if (job.get('status') == 'running' and gate is not None
                and getattr(gate, 'active', False) and Path(gate.path).resolve() == path.resolve()):
            self.cancel_callbacks[job['job_id']] = cancel
        elif job.get('status') == 'running':
            self.cancel_callbacks.pop(job['job_id'], None)
        def timeout():
            if job.get('status') == 'running':
                cancel()
                self.fail_job(job, BridgeError('open_timeout', '打开工程未完成，请检查原生界面'))
        QTimer.singleShot(120000, timeout)
        return self.public_job(job)

    def op_create_media_project(self, media_path, name='', socket=None):
        self.require_access('allow_edits')
        self._create_media_target(media_path, name)
        return self._prepare_media_page('create_media_project',
                    lambda page, job: self._create_media_project(page, media_path, name, job))

    def _create_media_project(self, page, media_path, name, job):
        media, target = self._create_media_target(media_path, name)
        initial_project = page.project
        initial_generation = getattr(page.session, 'generation', None)
        initial_identity = (media.stat().st_size, media.stat().st_mtime_ns)
        def work(token, progress):
            from ..media.media_service import GLOBAL_MEDIA_SERVICE
            from ..projects.studio_project import StudioMedia, SubtitleProject, hydrate_media_contract, save_project
            from ..timeline.studio_edit_sequence import identity_sequence, store_sequence
            if token.is_cancelled:
                raise InterruptedError('创建工程已取消')
            if target.parent.exists():
                raise BridgeError('output_exists', '同名工程目录已存在')
            if not GLOBAL_MEDIA_SERVICE.ffprobe_path.is_file():
                raise BridgeError('configuration_required', '创建工程缺少FFprobe，请检查原生组件设置')
            identity = GLOBAL_MEDIA_SERVICE.metadata(media)
            if identity.duration_ms <= 0:
                raise BridgeError('invalid_media', '原生媒体探测未取得有效时长，未创建空时间轴工程')
            if (media.stat().st_size, media.stat().st_mtime_ns) != initial_identity:
                raise BridgeError('input_changed', '创建期间素材已变化，未建立工程')
            project = SubtitleProject(media=StudioMedia(str(media), display_name=media.name,
                        duration_ms=identity.duration_ms, width=identity.width, height=identity.height,
                        fingerprint=identity.fingerprint))
            hydrate_media_contract(project, identity.to_dict(), source_path=media)
            # Match first-media ingestion in Studio: establish the editable
            # full-source sequence before validation materializes the V1 lane.
            store_sequence(project, identity_sequence(project.media))
            project.validate()
            if token.is_cancelled:
                raise InterruptedError('创建工程已取消')
            if self._create_media_target(media_path, name) != (media, target):
                raise BridgeError('out_of_scope', '创建期间工程库目录已变化，未建立工程')
            target.parent.parent.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(exist_ok=False)
            saved = save_project(project, target)
            if (media.stat().st_size, media.stat().st_mtime_ns) != initial_identity:
                raise BridgeError('input_changed', '创建期间素材已变化，新工程保留但不自动打开')
            return {'project': str(saved)}
        def apply(result, job):
            from .production import DEFERRED
            self.require_access('allow_edits')
            if (page.project is not initial_project or getattr(page.session, 'generation', None) != initial_generation
                    or (page.project is not None and not page.undo_stack.isClean())):
                raise BridgeError('unsaved_changes', '创建期间工程发生修改，新工程已保留但未切换')
            self._open_media_project(page, Path(result['project']), job=job)
            return DEFERRED
        return self.run_job('create_media_project', {}, work, apply, existing_job=job)

    def op_open_project(self, project_path, socket=None):
        from ..projects.studio_project import PROJECT_SUFFIX
        self.require_access('allow_edits')
        path = _path(project_path, file=False)
        self._require_open_scope(path)
        path = _path(project_path)
        if path.suffix.lower() != PROJECT_SUFFIX:
            raise BridgeError('bad_params', '只能打开原生.2byteproj工程')
        return self._prepare_media_page('open_project', lambda page, job: self._open_media_project(page, path, job=job))

    def op_save_project(self, project_id, revision, socket=None):
        from ..projects.studio_project import load_project, project_content_fingerprint
        page, project = self.require_project(project_id, revision)
        if not page.session.project_path:
            raise BridgeError('unsaved_project', '工程没有保存路径，请先在原生界面另存为')
        path = _path(str(page.session.project_path), file=False)
        errors = []
        page.project_controller.save(message_box_fn=lambda *args: errors.append(str(args[-1])))
        if errors or not path.is_file() or not page.undo_stack.isClean():
            raise BridgeError('save_failed', errors[0] if errors else '原生保存未完成，内存修改仍保留')
        saved = load_project(path)
        if saved.project_id != project.project_id or project_content_fingerprint(saved) != project_content_fingerprint(project):
            raise BridgeError('save_failed', '磁盘工程与当前内存工程不一致')
        return {**self.snapshot(page, project), 'saved': True, 'size_bytes': path.stat().st_size}

    def op_detect_speech_pauses(self, project_id, revision, mode='smart', minimum_s=1, padding_s=.2,
                                audio_track_id='', socket=None):
        from ..studio.studio_speech_cut import analyze_speech_pauses
        page, project = self.require_project(project_id, revision, permission=None)
        if mode not in ('smart', 'silence') or any(not math.isfinite(float(v)) for v in (minimum_s, padding_s)):
            raise BridgeError('bad_params', '检测模式或时间参数无效')
        if not .5 <= float(minimum_s) <= 3600 or not 0 <= float(padding_s) <= 60:
            raise BridgeError('bad_params', '停顿阈值须为0.5至3600秒，保护须为0至60秒')
        if audio_track_id and audio_track_id not in {t.id for t in project.audio_tracks}:
            raise BridgeError('bad_params', '指定音轨不存在')
        snap = self.snapshot(page, project)
        detached = copy.deepcopy(project)
        def work(token, progress):
            result = analyze_speech_pauses(detached, Path(tempfile.mkdtemp(prefix='2byte-mcp-pauses-')),
                         mode=mode, minimum_s=float(minimum_s), padding_s=float(padding_s),
                         audio_track_id=audio_track_id, request=token,
                         progress=lambda stage, done, total: progress({'stage': stage, 'done': done, 'total': total}))
            for index, row in enumerate(result['candidates']):
                row['candidate_id'] = str(index + 1)
            return result
        def apply(result, job):
            self.check_snapshot(snap)
            self.job_payloads[job['job_id']] = {'snapshot': snap, 'analysis': result, 'applied': False}
            return result
        return self.run_job('detect_speech_pauses', snap, work, apply)

    def op_apply_pause_cuts(self, project_id, revision, job_id, candidate_ids, socket=None):
        from ..timeline.studio_clip_edit import ripple_ranges_command
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        page, project = self.require_project(project_id, revision)
        job = self.get_owned_job(job_id, kind='detect_speech_pauses')
        data = self.job_payloads.get(job_id)
        if job.get('status') != 'completed' or not data or data['applied']:
            raise BridgeError('invalid_job', '检测任务未完成、已应用或不能恢复，请重新检测')
        self.check_snapshot(data['snapshot'])
        if not isinstance(candidate_ids, list) or not candidate_ids or any(not isinstance(v, str) for v in candidate_ids):
            raise BridgeError('bad_params', '请提供明确的候选ID列表')
        lookup = {c['candidate_id']: c for c in data['analysis']['candidates']}
        if len(set(candidate_ids)) != len(candidate_ids) or not set(candidate_ids) <= lookup.keys():
            raise BridgeError('bad_params', '候选ID重复或不属于指定检测任务')
        _check_pause_input(project, data['analysis'])
        ranges = [(lookup[i]['start_ms'], lookup[i]['end_ms']) for i in candidate_ids]
        before = timeline_duration_ms(project)
        command = ripple_ranges_command(project, ranges, page=page)
        page.undo_stack.push(command)
        after = timeline_duration_ms(project)
        data['applied'] = True
        return {**self.snapshot(page, project), 'candidate_ids': candidate_ids,
                'removed_ms': before - after, 'undoable': True}

    def op_export_video(self, project_id, revision, name='', destination='', socket=None):
        page, project = self.require_project(project_id, revision, permission='allow_export')
        root, target = _output(self.bridge.settings, page, name, destination)
        snap = self.snapshot(page, project)
        detached = copy.deepcopy(project)
        project_path = str(page.session.project_path)
        return self.run_job('export_video', snap,
                            lambda token, progress: _render(detached, project_path,
                                                          root, target, token, progress))
