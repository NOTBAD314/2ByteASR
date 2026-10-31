"""Prepare a large layer transform off the GUI; publish one owned undo command."""
from dataclasses import replace
import threading

from ..projects.studio_revisions import FrozenMap

BULK_THRESHOLD = 128


def _geometry_revision(revision):
    """Keep recognition blobs and word plans out of the IPC/geometry payload."""
    metadata = revision.generation_metadata
    if isinstance(metadata, FrozenMap):
        metadata = FrozenMap(tuple(item for item in metadata.items if item[0]=='translations'))
    state = revision.studio_state
    if isinstance(state, FrozenMap):
        state = FrozenMap(tuple(item for item in state.items
                         if item[0] in {'bilingual', 'bilingual_mode', 'caption_group_transform'}))
    return replace(revision, generation_metadata=metadata, studio_state=state, word_animations=None)


def prepare_plan(revision, cue_ids, language, changes, *, mode='absolute', reference_id=None, reset=False):
    """The synchronous planner on detached immutable presentation inputs."""
    from .scoped_transform import transform_plan
    from ..rendering.caption_playback_cache import _caption_source_project
    from ..projects.studio_project import StudioCue
    narrow = _geometry_revision(revision)
    project = _caption_source_project(narrow)
    project.cues = [StudioCue(**cue.to_dict()) for cue in revision.cues]
    return transform_plan(project, cue_ids, language, changes, mode=mode, reference_id=reference_id, reset=reset)


def prepare_plan_job(payload):
    revision, ids, language, changes, options = payload
    return {'transforms': prepare_plan(revision, ids, language, changes, **options) or {}}


def prepare_command(page, cue_ids, language, changes, *, mode='absolute', reference_id=None, reset=False):
    """A modal progress loop pumps Qt while a bounded worker computes geometry.

    No QWidget is read on the worker. There is one job per page, no queue;
    a replaced project, changed visual revision or save path rejects its result.
    """
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid
    from ..i18n import tr
    from ..projects.studio_save import _CloseGuard, _SaveProgress
    from .caption_layer_transform import presentation_command
    app = QApplication.instance()
    if app is None:
        raise RuntimeError('批量变换需要运行中的界面')
    if getattr(page, '_bulk_transform_busy', False):
        return None
    project = page.project
    # Algebraically exact position-only edits need no detached snapshot,
    # process transfer or glyph layout. Large edits still paint progress before
    # publishing the single undo command; publication itself is not free.
    from .scoped_transform import position_only_plan
    from .caption_layer_transform import target_ids
    wanted = target_ids(project, cue_ids)
    targets = [cue for cue in project.cues if cue.id in wanted]
    quick = position_only_plan(project, targets, 'linked' if language == 'group' else language,
                               changes, mode=mode, reset=reset)
    if quick is not None and len(targets) < BULK_THRESHOLD:
        return presentation_command(project, targets, quick, changed=page._changed)
    revision = (page._revision_store.render if quick is not None else
                _geometry_revision(page._revision_store.authoring_render()))
    path = page.session.project_path
    page._bulk_transform_busy = True
    finished = threading.Event()
    result = {}
    ids, patch = tuple(cue_ids), dict(changes)
    def work():
        try:
            if quick is not None:
                result['transforms'] = quick
                return
            options = dict(mode=mode, reference_id=reference_id, reset=reset)
            answer = None
            if len(ids) >= BULK_THRESHOLD:
                from ..system.resident_worker import shared_worker
                resident = shared_worker()
                if resident is not None:
                    answer = resident.call('twobyteasr.caption_style.bulk_transform_preparation:prepare_plan_job',
                                           (revision, ids, language, patch, options))
            result['transforms'] = (answer['transforms'] if answer is not None else
                prepare_plan(revision, ids, language, patch, **options))
        except Exception as exc:
            result['error'] = exc
        finally:
            finished.set()
    worker = threading.Thread(target=work, name='caption-bulk-transform', daemon=True)
    class Progress(_SaveProgress):
        started = False
        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.started:
                self.started = True
                worker.start()
    loop = QEventLoop()
    progress = Progress(tr('正在计算 {count} 条字幕的位置与缩放…', count=len(ids)), '', 0, 0, page.window())
    progress.setObjectName('studioBulkTransformProgress')
    progress.setWindowTitle(tr('批量更新字幕'))
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.setMinimumWidth(360)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setWindowFlag(Qt.WindowCloseButtonHint, False)
    from ..design.studio_theme import apply_secondary_surface_theme
    apply_secondary_surface_theme(progress)
    guard = _CloseGuard(page, page.window())
    app.installEventFilter(guard)
    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(lambda: loop.quit() if finished.is_set() else None)
    try:
        progress.show()
        timer.start()
        if page.window().isMinimized():
            progress.started = True
            worker.start()
        loop.exec()
    finally:
        timer.stop()
        app.removeEventFilter(guard)
        progress.hide()
        progress.deleteLater()
        page._bulk_transform_busy = False
    if 'error' in result:
        raise result['error']
    if (not isValid(page) or page.project is not project or page.session.project_path != path
            or page._revision_store.render.visual_revision != revision.visual_revision
            or page._revision_store.render.mapping_revision != revision.mapping_revision):
        if isValid(page):
            page._show_studio_hint(tr('工程已变化，这次批量修改未提交，请重新操作'))
        return None
    transforms = result.get('transforms') or {}
    targets = [cue for cue in project.cues if cue.id in transforms]
    return presentation_command(project, targets, transforms, changed=page._changed)
