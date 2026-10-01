"""Prepare immutable caption snapshots off the GUI thread for cue transitions."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import threading
from PySide6.QtCore import QObject, Signal


def revision_key(revision, width, height):
    return (revision.project_id, revision.mapping_revision, revision.visual_revision, int(width), int(height))


@dataclass(frozen=True)
class PreparedCaption:
    snapshot: object
    snapshot_hash: str
    route: object
    web: object = None
    pixel_content_key: str = ''
    preview_error: str = ''


@dataclass(frozen=True)
class FailedCaption:
    error: str
    fallback: object = None


def materialize_caption_project(revision):
    """Called on a worker; JSON, font and recipe work never runs in playback GUI."""
    from .studio_project import SubtitleProject, StudioCue, SubtitleStyle, StudioSpeaker, StudioMedia
    from .studio_revisions import thaw_json
    # The DTOs are already projected. Rebuilding runtime indexes with the
    # original edit/recognition metadata projects them a second time.
    cues = revision.timeline_cues if revision.timeline_cues is not None else revision.cues
    project = SubtitleProject(project_id=revision.project_id,
        media=StudioMedia('', width=revision.play_res_x, height=revision.play_res_y),
        cues=[StudioCue(**cue.to_dict()) for cue in cues],
        styles=[SubtitleStyle(**asdict(style)) for style in revision.styles],
        speakers=[StudioSpeaker(**speaker.to_dict()) for speaker in revision.speakers],
        effects=thaw_json(revision.effects), style_recipes=thaw_json(revision.style_recipes),
        generation_metadata=thaw_json(revision.generation_metadata) or {},
        studio_state=thaw_json(revision.studio_state) or {},
        render_settings={'play_res_x':revision.play_res_x, 'play_res_y':revision.play_res_y, '_cue_domain':'timeline'})
    return project


def basic_caption(project, cue_id, width, height, error):
    """Readable, ephemeral fallback; never rewrites the authored project."""
    from .studio_project import SubtitleProject, StudioCue, SubtitleStyle
    from .visual_snapshot import build_visual_cue_snapshot
    from .style_recipe import RecipeRoute, recipe_payload_for_style, route_recipe
    cue = next(c for c in project.cues if c.id == cue_id)
    payload=recipe_payload_for_style(project.style_recipes,cue.style_id)
    if payload and (payload.get('webTheme') or payload.get('engine')=='remotion' or route_recipe(payload).engine=='remotion'):return None
    basic = SubtitleProject(media=project.media, render_settings=dict(project.render_settings),
        styles=[SubtitleStyle('preview-fallback', '基础预览')],
        cues=[StudioCue(cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id, 'preview-fallback')])
    snapshot = build_visual_cue_snapshot(basic, cue.id, width=width, height=height)
    from .subtitle_stacking import project_stack_layout
    offset=project_stack_layout(project).offset_for(cue_id)
    if offset:snapshot=replace(snapshot,position_y=snapshot.position_y-offset)
    return PreparedCaption(snapshot, snapshot.stable_hash(), RecipeRoute('native', ()), preview_error=error)


class PlaybackCaptionCache(QObject):
    ready = Signal(object, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._frames = OrderedDict()
        self._failures = OrderedDict()
        self._pending = None
        self._running = False
        self._closed = False
        self._wake = threading.Event()
        self.prepared_count = 0
        self._materialized = None
        self._materialized_key = None

    def snapshot(self, revision, cue_id, width, height):
        prepared = self.prepared(revision,cue_id,width,height)
        return prepared.snapshot if prepared else None

    def prepared(self, revision, cue_id, width, height):
        key = (*revision_key(revision,width,height), cue_id)
        with self._lock:
            prepared = self._frames.get(key)
            failure = self._failures.get(key)
            return prepared or (failure.fallback if failure else None)

    def failure(self, revision, cue_id, width, height):
        with self._lock:return self._failures.get((*revision_key(revision,width,height),cue_id))

    def prepare(self, revision, cue_ids, width, height):
        group = revision_key(revision,width,height)
        with self._lock:
            if self._closed: return
            missing = tuple(cue_id for cue_id in cue_ids if (*group,cue_id) not in self._frames and (*group,cue_id) not in self._failures)
            if not missing: return
            self._pending = (revision, missing, width, height)
            self._wake.set()
            if self._running: return
            self._running = True
        threading.Thread(target=self._work, name='caption-prepare', daemon=True).start()

    def _work(self):
        project = self._materialized
        current = self._materialized_key
        while True:
            self._wake.wait()
            with self._lock:
                task = self._pending
                self._pending = None
                self._wake.clear()
                if self._closed:
                    self._running = False
                    return
                if task is None: continue
            revision, ids, width, height = task
            key = revision_key(revision,width,height)
            ready_ids = []
            try:
                if current != key:
                    project = materialize_caption_project(revision)
                    current = key
                    self._materialized, self._materialized_key = project, key
                from .visual_snapshot import build_visual_cue_snapshot
                for cue_id in ids:
                    with self._lock:
                        if self._closed: break
                        if (*key,cue_id) in self._frames: continue
                    try:
                        snapshot = build_visual_cue_snapshot(project, cue_id, width=width, height=height, fps=30.)
                        from .style_recipe import route_recipe,recipe_payload_for_style,RecipeRoute
                        cue = next(c for c in project.cues if c.id == cue_id)
                        # Resolved snapshots add layout/font measurement fields.
                        # Those are presentation data, not authored capabilities.
                        # Routing that enriched payload promoted plain ASS cues
                        # and the boundary worker drew a second text layer while
                        # the foreground owner correctly remained NATIVE.
                        payload=recipe_payload_for_style(project.style_recipes,cue.style_id)
                        route = route_recipe(payload) if payload else RecipeRoute('native',())
                        web = None
                        theme = snapshot.style_recipe.get('webTheme')
                        if theme:
                            from .live_web_preview import prepare_web_configuration
                            speaker = next((item.name or '' for item in project.speakers if item.id==cue.speaker_id), '')
                            web = prepare_web_configuration(theme,snapshot.text,speaker,(cue.end_ms-cue.start_ms)/1000.,
                                snapshot.style_recipe.get('layout',{}).get('webPlacement'))
                        # Repeated caption text can share first-frame pixels while
                        # keeping cue identity/revision guards on publication.
                        # A legacy persistent stage depends on absolute time.
                        pixel_key=(web.strip_key if web is not None and not str(theme.get('stageHtml','')).strip()
                            else snapshot.stable_hash() if web is not None
                            else replace(snapshot,cue_id='',start_ms=0,end_ms=0,appearance_generation=0).stable_hash())
                        prepared = PreparedCaption(snapshot,snapshot.stable_hash(),route,web,pixel_key)
                        with self._lock:
                            if self._closed: break
                            self._frames[(*key,cue_id)] = prepared
                            self.prepared_count += 1
                            while len(self._frames)>96: self._frames.popitem(last=False)
                        ready_ids.append(cue_id)
                    except Exception as exc:
                        error = f'{type(exc).__name__}: {exc}'
                        try:
                            fallback = basic_caption(project, cue_id, width, height, error)
                        except Exception:
                            fallback = None
                        with self._lock:
                            self._failures[(*key, cue_id)] = FailedCaption(error, fallback)
                            while len(self._failures)>96:self._failures.popitem(last=False)
                        ready_ids.append(cue_id)
                        try: self.failed.emit(f'{cue_id}: {type(exc).__name__}: {exc}')
                        except RuntimeError: pass
                if ready_ids and not self._closed: self.ready.emit(key, tuple(ready_ids))
            except Exception as exc:
                try: self.failed.emit(f'{type(exc).__name__}: {exc}')
                except RuntimeError: pass

    def close(self):
        with self._lock:
            self._closed=True
            self._pending=None
            self._frames.clear()
            self._failures.clear()
            self._wake.set()
