"""Prepare a large layer transform off the GUI; publish one owned undo command."""
from dataclasses import replace
import threading
from time import perf_counter
import weakref

from PySide6.QtGui import QUndoCommand

from ..projects.studio_revisions import FrozenMap, freeze_json, thaw_json

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


def _geometry_project(revision):
    from ..rendering.caption_playback_cache import _caption_source_project
    from ..projects.studio_project import StudioCue

    narrow = _geometry_revision(revision)
    project = _caption_source_project(narrow)
    project.cues = [StudioCue(**cue.to_dict()) for cue in revision.cues]
    return project


def prepare_plan(revision, cue_ids, language, changes, *, mode='absolute', reference_id=None, reset=False):
    """The synchronous planner on detached immutable presentation inputs."""
    from .scoped_transform import transform_plan

    project = _geometry_project(revision)
    return transform_plan(project, cue_ids, language, changes, mode=mode, reference_id=reference_id, reset=reset)


def summarize_geometry(project, cues, language):
    from .caption_layer_transform import GEOMETRY, GeometryBatch

    batch = GeometryBatch(project)
    first = None
    mixed = set()
    for cue in cues:
        value = batch.values(cue, 'original' if language == 'linked' else language)
        if value is None:
            continue
        if first is None:
            first = value
            continue
        mixed.update(key for key in GEOMETRY - mixed if abs(value[key] - first[key]) > .001)
        if mixed == GEOMETRY:
            break
    return first, mixed


def prepare_summary_job(payload):
    revision, cue_ids, language = payload
    project = _geometry_project(revision)
    lookup = {cue.id: cue for cue in project.cues}
    return summarize_geometry(project, (lookup[key] for key in cue_ids if key in lookup), language)


def queue_geometry_summary(panel, revision, cue_ids, language, completed):
    """Measure a large inspector selection without owning the GUI thread."""
    from PySide6.QtCore import QTimer
    from shiboken6 import isValid

    payload = (_geometry_revision(revision), cue_ids, language)
    cancelled = threading.Event()
    finished = threading.Event()
    answer = None

    def is_cancelled():
        return cancelled.is_set() or not isValid(panel)

    def prepare():
        nonlocal answer
        try:
            from ..system.resident_worker import shared_worker

            worker = shared_worker()
            if worker is not None and not is_cancelled():
                answer = worker.call(
                    "twobyteasr.caption_style.bulk_transform_preparation:prepare_summary_job",
                    payload, cancel_check=is_cancelled,
                )
            if answer is None and not is_cancelled():
                answer = prepare_summary_job(payload)
        except Exception:
            answer = None
        finally:
            finished.set()

    timer = QTimer(panel)
    timer.setInterval(35)

    def collect():
        if not finished.is_set() and not cancelled.is_set():
            return
        timer.stop()
        timer.deleteLater()
        if not cancelled.is_set() and isValid(panel):
            completed(answer)

    timer.timeout.connect(collect)
    timer.start()
    threading.Thread(target=prepare, name="caption-transform-summary", daemon=True).start()
    return cancelled.set


def prepare_plan_job(payload):
    revision, ids, language, changes, options = payload
    options = dict(options)
    inspect_geometry = options.pop('inspect_geometry', False)
    transformed = prepare_plan(revision, ids, language, changes, **options) or {}
    result = {
        'entries': {cue.id: (cue.transform, after)
                    for cue in revision.cues if cue.id in transformed
                    if (after := freeze_json(transformed[cue.id])) != cue.transform}
    }
    if inspect_geometry and result['entries']:
        project = _geometry_project(revision)
        lookup = {cue.id: cue for cue in project.cues}
        for cue_id, value in transformed.items():
            lookup[cue_id].transform = value
        result['inspector'] = summarize_geometry(project, (lookup[key] for key in ids if key in lookup), language)
    return result


class BulkTransformCommand(QUndoCommand):
    """Apply the detached geometry delta without rebuilding shared presets."""

    def __init__(self, project, entries, changed, *, page=None):
        super().__init__('调整字幕变换')
        self.project = project
        self.entries = entries
        self.changed = changed
        self._page = weakref.ref(page) if page is not None else None
        self._initial_publication = True

    def _apply(self, side):
        from ..projects.studio_runtime_state import DirtyDomain
        from ..timeline.studio_commands import _commit_mutation

        geometry = {key: thaw_json(pair[side]) or {} for key, pair in self.entries.items()}

        page = self._page() if self._page is not None else None
        if page is not None:
            from shiboken6 import isValid

            if not isValid(page) or page.project is not self.project:
                page = None
        if page is not None:
            prior = getattr(page, '_style_publication_owned', False)
            page._style_publication_owned = True
        try:
            _commit_mutation(self.project, action_id="bulk_caption_transform", cue_ids=self.entries,
                             dirty=(DirtyDomain.CUE_STYLE | DirtyDomain.TIMELINE_PIXELS |
                                    DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW |
                                    DirtyDomain.TRANSFORM | DirtyDomain.AUTOSAVE),
                             prepared_geometry=geometry, changed=self.changed, snapshot_cues=False, sync_caption_words=False)
        finally:
            if page is not None:
                page._style_publication_owned = prior
        # The first publisher supplies its prepared summary. Later undo/redo
        # refresh the transform card for the current selection.
        if page is not None and not self._initial_publication:
            page.caption_transform_panel.refresh()
        self._initial_publication = False

    def redo(self):
        self._apply(1)

    def undo(self):
        self._apply(0)


def queue_command(page, cue_ids, language, changes, *, completed, discarded=None,
                  mode='absolute', reference_id=None, reset=False, inspect_geometry=False):
    """Plan against an immutable revision and publish through the GUI event loop."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QProgressDialog
    from shiboken6 import isValid
    from ..i18n import tr
    from ..design.studio_theme import apply_secondary_surface_theme

    if getattr(page, '_bulk_transform_busy', False):
        page._show_studio_hint(tr('正在准备上一项字幕变换'))
        return False
    if discarded is None:
        discarded = lambda: completed(None)
    project = page.project
    path = page.session.project_path
    submitted = perf_counter()
    revision = _geometry_revision(page._revision_store.authoring_render())
    ids = tuple(cue_ids)
    payload = (revision, ids, language, dict(changes),
               dict(mode=mode, reference_id=reference_id, reset=reset, inspect_geometry=inspect_geometry))
    page._bulk_transform_busy = True
    finished = threading.Event()
    cancelled = threading.Event()
    result = {}

    def prepare():
        try:
            from ..system.resident_worker import shared_worker
            resident = shared_worker() if len(ids) >= BULK_THRESHOLD else None
            if cancelled.is_set():
                return
            answer = resident.call('twobyteasr.caption_style.bulk_transform_preparation:prepare_plan_job',
                                   payload, cancel_check=cancelled.is_set) if resident else None
            if not cancelled.is_set():
                if not isinstance(answer, dict) or "entries" not in answer:
                    answer = prepare_plan_job(payload)
                result.update(answer)
        except Exception as error:
            result['error'] = error
        finally:
            finished.set()

    progress = QProgressDialog(tr('正在计算 {count} 条字幕的位置与缩放…', count=len(ids)),
                               tr('取消'), 0, 0, page.window())
    progress.setObjectName('studioBulkTransformProgress')
    progress.setWindowTitle(tr('批量更新字幕'))
    progress.setWindowModality(Qt.WindowModality.NonModal)
    progress.setMinimumDuration(0)
    progress.setMinimumWidth(360)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    apply_secondary_surface_theme(progress)
    progress.canceled.connect(cancelled.set)
    timer = QTimer(page)
    timer.setInterval(16)

    def collect():
        if not finished.is_set():
            return
        timer.stop()
        timer.deleteLater()
        if isValid(progress):
            progress.hide()
            progress.deleteLater()
        if not isValid(page):
            return
        page._bulk_transform_busy = False
        current = page._revision_store.render if page._revision_store is not None else None
        if cancelled.is_set():
            discarded()
        elif (page.project is not project or page.session.project_path != path or current is None
              or current.visual_revision != revision.visual_revision
              or current.mapping_revision != revision.mapping_revision):
            page._show_studio_hint(tr('工程已变化，这次批量修改未提交，请重新操作'))
            discarded()
        elif result.get('error'):
            page._show_studio_hint(tr('批量更新字幕失败'))
            discarded()
        else:
            entries = result.get('entries') or {}
            locked = (page.timeline.locked_speakers or project.studio_state.get('locked_speakers')
                      or project.studio_state.get('locked_cue_ids')
                      or any(getattr(cue, 'locked', False) for cue in project.cues if cue.id in entries))
            if locked and entries:
                from ..studio.presentation_scope import capture_scope

                scope = capture_scope(page, layer=language, ids=entries)
                if scope.locked_ids:
                    page._show_studio_hint(tr('字幕已锁定，这次批量修改未提交'))
                    discarded()
                    return
            published = perf_counter()
            command = BulkTransformCommand(project, entries, page._changed, page=page) if entries else None
            if command is not None:
                command.inspector_summary = result.get('inspector')
            completed(command)
            page._last_bulk_transform_metrics = dict(
                requested=len(ids), applied=len(entries),
                prepare_ms=(published - submitted) * 1000,
                publish_ms=(perf_counter() - published) * 1000)

    timer.timeout.connect(collect)
    progress.show()
    timer.start()
    threading.Thread(target=prepare, name='caption-bulk-transform', daemon=True).start()
    return True
