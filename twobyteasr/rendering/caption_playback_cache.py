"""Prepare immutable caption snapshots off the GUI thread for cue transitions."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import os
import threading
from PySide6.QtCore import QEvent, QObject, Qt, Signal


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
    interaction_transform: object = None


@dataclass(frozen=True)
class FailedCaption:
    error: str
    fallback: object = None


def materialize_caption_project(revision):
    """Called on a worker; JSON, font and recipe work never runs in playback GUI.

    The DTOs are already projected (rebuilding runtime indexes with the
    original edit/recognition metadata would project them a second time).
    Cues are the display cues the ASS export draws: adjusted originals plus
    ``<id>#tr`` translation companions."""
    return materialize_captions(revision)[0].project


# studio_state keys no caption reads: the view state written before each
# autosave (playhead, zoom, panel layout) and per-edit bookkeeping (manual
# text guard, review marks). A change there must not rebuild every caption.
VIEW_STATE_KEYS = frozenset({
    "last_selected_cue", "playhead_ms", "zoom", "scroll_ms", "follow_playhead",
    "timeline_snap_enabled", "timeline_tool", "timeline_track_heights", "layout",
    "manual_caption_text", "cue_statuses", "review_risks", "review_confirmations", "caption_global_link",
})
# Per-cue entries some captions read (word timings for word effects): a
# changed entry rebuilds its cue only.
CAPTION_TIMELINE_KEY = "caption_timeline"
TERM_OVERRIDES_KEY = "term_word_overrides"


@dataclass
class MaterializedCaptions:
    """A materialized caption project and what each source cue became."""
    revision: object
    project: object
    source: object          # same inputs, studio_state without the styled mark
    context: tuple
    translations: object
    entries: dict           # id(cue DTO) -> (DTO, [display cues])
    per_cue: tuple = ({}, {})   # caption receipts, term word overrides by cue id
    records: tuple = ({}, {}, {}, {})   # styles, speakers, recipes, effects by id


def _caption_context(revision):
    """(context, per-cue state, records by id).

    Equal contexts let unchanged cues be reused; styles, speakers, recipes
    and effects are compared per id, so a style edit rebuilds only the cues
    that use that style.
    """
    from ..projects.studio_revisions import FrozenMap
    state = revision.studio_state
    receipts, overrides = {}, {}
    if isinstance(state, FrozenMap):
        kept = []
        for key, value in state.items:
            if key in VIEW_STATE_KEYS:
                continue
            if key == CAPTION_TIMELINE_KEY and isinstance(value, FrozenMap):
                for name, item in value.items:
                    if name == "instances" and isinstance(item, FrozenMap):
                        receipts = dict(item.items)
                value = FrozenMap(tuple(item for item in value.items if item[0] != "instances"))
            elif key == TERM_OVERRIDES_KEY and isinstance(value, FrozenMap):
                overrides = dict(value.items)
                continue
            kept.append((key, value))
        state = tuple(kept)
    recipes, effects = revision.style_recipes, revision.effects
    records = ({style.id: style for style in revision.styles},
               {speaker.id: speaker for speaker in revision.speakers},
               dict(recipes.items) if isinstance(recipes, FrozenMap) else None,
               dict(effects.items) if isinstance(effects, FrozenMap) else None)
    context = (revision.project_id, revision.play_res_x, revision.play_res_y, state,
               None if records[2] is not None else recipes, None if records[3] is not None else effects,
               _glossary_marks_digest(revision))
    return context, (receipts, overrides), records


def _glossary_marks_digest(revision):
    """Which glossary terms the captions mark (2026-10-24 caption-marks port, Codex's emphasis).

    A changed library, or a term's 视觉强调 switch, must rebuild the captions; the cue DTOs
    themselves stay the same. ``snapshot_active`` is cached by the library files' mtimes."""
    from types import SimpleNamespace
    from ..projects.studio_revisions import FrozenMap, thaw_json
    from ..glossary.visual_emphasis import snapshot_active
    ids = tuple(getattr(revision, "glossary_ids", ()) or ())
    metadata = {}
    if not ids and isinstance(revision.generation_metadata, FrozenMap):
        recorded = dict(revision.generation_metadata.items).get("terminology_snapshot")
        if recorded is not None:
            metadata = {"terminology_snapshot": thaw_json(recorded)}
    try:
        return snapshot_active(SimpleNamespace(glossary_ids=ids, generation_metadata=metadata)).digest
    except Exception:  # noqa: BLE001 - no glossary data: nothing is marked
        return ""


def _context_change(previous, context):
    names = ("project", "play_res_x", "play_res_y")
    for name, old, new in zip(names, previous, context):
        if old != new:
            return name
    if previous[4:6] != context[4:6]:
        return "recipes_or_effects"
    if previous[6:] != context[6:]:
        return "glossary_marks"
    if previous[3] != context[3]:
        old_state, new_state = dict(previous[3] or ()), dict(context[3] or ())
        keys = sorted(key for key in set(old_state) | set(new_state) if old_state.get(key) != new_state.get(key))
        return "studio_state:" + ",".join(keys[:6])
    return "records"


def _changed_ids(old: dict | None, new: dict | None) -> set:
    if old is None or new is None:
        return set()
    return {key for key in set(old) | set(new)
            if old.get(key) is not new.get(key) and old.get(key) != new.get(key)}


def _recipe_keys(style_id: str) -> tuple:
    text = str(style_id or "")
    keys = [text]
    for token in ("-fill-", "-scope-", "-cue-", "-canvas-"):
        if token in text:
            keys.append(text.split(token, 1)[0])
    return tuple(keys)


def materialize_captions(revision, previous: MaterializedCaptions | None = None, *, full_builder=None, cancel_check=None):
    """``materialize_caption_project`` that rebuilds only changed source cues.

    2026-10-22 (report-eb10 stage 1): every edit rebuilt all display cues
    (2090 bilingual cues: 2-3.5 s of Python on the preparing thread, which
    kept the editor waiting for the GIL). Unchanged cue DTOs are shared
    between revisions. A cue keeps its display cues when its DTO, translation,
    caption receipt and word overrides are unchanged and so are the records it
    resolves through: its style, base preset and derived style, its speaker
    (and speaker style), the recipe for its style, and the default style.
    Anything else that differs (caption-relevant studio state) rebuilds
    everything, as does speaker-name layout, which looks at neighbouring
    captions.

    ``full_builder(revision)`` may produce the display cues of a full rebuild
    elsewhere (a worker process); None means build here.

    Returns ``(materialized, reused display cue ids, full-rebuild reason)``;
    the reason is "" for an incremental update.
    """
    from ..projects.studio_project import StudioCue, SubtitleStyle, StudioSpeaker
    from ..projects.studio_revisions import thaw_json
    from ..timeline.studio_edit_sequence import source_cue_id_of
    from ..caption_style.bilingual_layout import (
        COMPANION_SUFFIX, project_display_cues, translation_for_cue, translations_of, _check_preparation_cancelled)
    def display_for(project, items):
        if cancel_check is None:
            return project_display_cues(project, items)
        return project_display_cues(project, items, cancel_check=cancel_check)
    _check_preparation_cancelled(cancel_check)
    from ..caption_style.speaker_names import enabled as speaker_names_enabled
    cues = revision.timeline_cues if revision.timeline_cues is not None else revision.cues
    context, per_cue, records = _caption_context(revision)
    reason = ""
    if previous is None or not previous.entries:
        reason = "first"
    elif speaker_names_enabled(previous.source.studio_state):
        reason = "speaker_names"
    elif previous.context != context:
        reason = _context_change(previous.context, context)
    if not reason:
        styles, speakers, recipes, effects = records
        old_styles, old_speakers, old_recipes, old_effects = previous.records
        changed_styles = _changed_ids(old_styles, styles)
        changed_speakers = _changed_ids(old_speakers, speakers)
        changed_recipes = _changed_ids(old_recipes, recipes)
        changed_effects = _changed_ids(old_effects, effects)
        if "default" in changed_styles:
            reason = "default_style"
    if not reason:
        source = previous.source
        same_metadata = revision.generation_metadata == previous.revision.generation_metadata
        translations = previous.translations
        updates = {}
        if not same_metadata:
            metadata = thaw_json(revision.generation_metadata) or {}
            translations = translations_of(metadata)
            updates["generation_metadata"] = metadata
        if revision.studio_state is not previous.revision.studio_state:
            updates["studio_state"] = thaw_json(revision.studio_state) or {}
        if changed_styles:
            updates["styles"] = [SubtitleStyle(**asdict(style)) for style in revision.styles]
        if changed_speakers:
            updates["speakers"] = [StudioSpeaker(**speaker.to_dict()) for speaker in revision.speakers]
        if changed_recipes:
            updates["style_recipes"] = thaw_json(revision.style_recipes)
        if changed_effects:
            updates["effects"] = thaw_json(revision.effects)
        if updates:
            source = _replace_fields(source, **updates)
        (old_receipts, old_overrides), (receipts, overrides) = previous.per_cue, per_cue

        def entry_changed(table, old_table, key):
            new, old = table.get(key), old_table.get(key)
            return new is not old and new != old

        def records_changed(dto):
            if not (changed_styles or changed_speakers or changed_recipes):
                return False
            speaker = speakers.get(dto.speaker_id)
            old_speaker = old_speakers.get(dto.speaker_id)
            style_keys = {dto.base_preset_id, dto.style_id,
                          getattr(speaker, "style_id", ""), getattr(old_speaker, "style_id", "")}
            return (bool(changed_styles & style_keys) or dto.speaker_id in changed_speakers
                    or bool(changed_recipes.intersection(_recipe_keys(dto.style_id))))

        changed, frames_stale = [], set()
        for dto in cues:
            hit = previous.entries.get(id(dto))
            source_id = source_cue_id_of(dto.id)
            if (hit is None or hit[0] is not dto
                    or (not same_metadata and translation_for_cue(translations, dto.id)
                        != translation_for_cue(previous.translations, dto.id))
                    or entry_changed(receipts, old_receipts, dto.id)
                    or entry_changed(overrides, old_overrides, dto.id)
                    or entry_changed(overrides, old_overrides, source_id)
                    or records_changed(dto)):
                changed.append(dto)
            elif dto.effect_id in changed_effects:
                frames_stale.add(id(dto))   # same display cues, different motion
        built = [StudioCue(**cue.to_dict()) for cue in changed]
        groups = _group_display(display_for(source, built) if built else [],
                                [cue.id for cue in built], COMPANION_SUFFIX)
        if groups is not None:
            fresh = {id(dto): (dto, group) for dto, group in zip(changed, groups)}
            entries, reused = {}, set()
            for dto in cues:
                entry = fresh.get(id(dto))
                if entry is None:
                    entry = previous.entries[id(dto)]
                    if id(dto) not in frames_stale:
                        reused.update(cue.id for cue in entry[1])
                entries[id(dto)] = entry
            project = _caption_display_project(source, [cue for dto in cues for cue in entries[id(dto)][1]])
            return (MaterializedCaptions(revision, project, source, context, translations, entries, per_cue,
                                         records), reused, "")
        reason = "ungroupable"
    source = _caption_source_project(revision)
    display = full_builder(revision) if full_builder is not None else None
    _check_preparation_cancelled(cancel_check)
    if display is None:
        display = display_for(source, [StudioCue(**cue.to_dict()) for cue in cues])
    _check_preparation_cancelled(cancel_check)
    groups = None if speaker_names_enabled(source.studio_state) else _group_display(
        display, [cue.id for cue in cues], COMPANION_SUFFIX)
    entries = {} if groups is None else {id(dto): (dto, group) for dto, group in zip(cues, groups)}
    project = _caption_display_project(source, display)
    return (MaterializedCaptions(revision, project, source, context, translations_of(source.generation_metadata),
                                 entries, per_cue, records), set(), reason)


def _group_display(display, source_ids, suffix):
    """Split ``display_cues`` output back into one list per source cue, in order.

    None when a display cue cannot be traced to one source cue, or the output
    is not in source order (then only a full rebuild is safe)."""
    groups = {cue_id: [] for cue_id in source_ids}
    order = {cue_id: index for index, cue_id in enumerate(source_ids)}
    last = -1
    for cue in display:
        base = cue.id[:-len(suffix)] if cue.id.endswith(suffix) else cue.id
        if base not in groups:
            base = cue.id
        if base not in groups or order[base] < last:
            return None
        last = order[base]
        groups[base].append(cue)
    return [groups[cue_id] for cue_id in source_ids]


def _replace_fields(source, **changes):
    from dataclasses import replace as replace_fields
    return replace_fields(source, **changes)


def _caption_source_project(revision):
    from ..projects.studio_project import SubtitleProject, SubtitleStyle, StudioSpeaker, StudioMedia
    from ..projects.studio_revisions import thaw_json
    return SubtitleProject(project_id=revision.project_id,
        media=StudioMedia('', width=revision.play_res_x, height=revision.play_res_y),
        cues=[],
        styles=[SubtitleStyle(**asdict(style)) for style in revision.styles],
        speakers=[StudioSpeaker(**speaker.to_dict()) for speaker in revision.speakers],
        effects=thaw_json(revision.effects), style_recipes=thaw_json(revision.style_recipes),
        generation_metadata=thaw_json(revision.generation_metadata) or {},
        glossary_ids=list(getattr(revision, "glossary_ids", ())),
        studio_state=thaw_json(revision.studio_state) or {},
        render_settings={'play_res_x':revision.play_res_x, 'play_res_y':revision.play_res_y, '_cue_domain':'timeline'})


def _caption_display_project(source, display):
    from ..projects.studio_project import SubtitleProject
    from ..subtitle_rules.punctuation_style import mark_cues_styled
    project = SubtitleProject(project_id=source.project_id, media=source.media, cues=display,
        styles=source.styles, speakers=source.speakers, effects=source.effects,
        style_recipes=source.style_recipes, generation_metadata=source.generation_metadata,
        studio_state=dict(source.studio_state), render_settings=source.render_settings)
    mark_cues_styled(project)  # visual snapshots of these cues must not style them again
    return project


def basic_caption(project, cue_id, width, height, error):
    """Readable, ephemeral fallback; never rewrites the authored project."""
    from ..projects.studio_project import SubtitleProject, StudioCue, SubtitleStyle
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..caption_style.style_recipe import RecipeRoute, recipe_payload_for_style, route_recipe
    cue = next(c for c in project.cues if c.id == cue_id)
    payload=recipe_payload_for_style(project.style_recipes,cue.style_id)
    if payload and (payload.get('webTheme') or payload.get('engine')=='remotion' or route_recipe(payload).engine=='remotion'):return None
    basic = SubtitleProject(media=project.media, render_settings=dict(project.render_settings),
        styles=[SubtitleStyle('preview-fallback', '基础预览')],
        cues=[StudioCue(cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id,
                       'preview-fallback', transform=dict(cue.transform))])
    snapshot = build_visual_cue_snapshot(basic, cue.id, width=width, height=height)
    return PreparedCaption(snapshot, snapshot.stable_hash(), RecipeRoute('native', ()), preview_error=error)


class PlaybackCaptionCache(QObject):
    ready = Signal(object, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Only publication/retirement is serialized. Materialization and font
        # work stay outside this per-cache gate, on the existing worker.
        self._lock = threading.RLock()
        self._frames = OrderedDict()
        self._failures = OrderedDict()
        self._pending = None
        self._running = False
        self._thread = None
        self._closed = False
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self.prepared_count = 0
        self.rebuilt_cues = 0
        self.full_rebuilds = []
        self.worker_builds = 0
        self._materialized = None
        self._materialized_key = None
        if parent is not None:
            parent.destroyed.connect(self.close, Qt.ConnectionType.DirectConnection)
        self.destroyed.connect(self.close, Qt.ConnectionType.DirectConnection)

    def event(self, event):
        # Retire while the QObject still exists, before DeferredDelete destroys
        # the signal emitter. Parent destruction has the same gate above.
        if event.type() == QEvent.Type.DeferredDelete:
            self.close()
        return super().event(event)

    def _notify(self, *, key=None, cue_ids=(), error=None):
        with self._lock:
            if self._closed:
                return False
            try:
                if error is not None:
                    self.failed.emit(error)
                else:
                    self.ready.emit(key, tuple(cue_ids))
            except RuntimeError:
                self.close()
                return False
            return not self._closed

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

    def prepare(self, revision, cue_ids, width, height, *, merge=False):
        """Latest request wins; ``merge`` appends to a pending request instead."""
        group = revision_key(revision,width,height)
        with self._lock:
            if self._closed: return
            missing = tuple(cue_id for cue_id in cue_ids if (*group,cue_id) not in self._frames and (*group,cue_id) not in self._failures)
            if not missing: return
            pending = self._pending
            if merge and pending is not None and revision_key(pending[0], pending[2], pending[3]) == group:
                missing = tuple(dict.fromkeys((*pending[1], *missing)))
            self._pending = (revision, missing, width, height)
            self._wake.set()
            if self._running: return
            self._running = True
            worker = self._thread = threading.Thread(target=self._work, name='caption-prepare', daemon=True)
        worker.start()

    def _work(self):
        try:
            self._prepare_loop()
        finally:
            with self._lock:
                self._running = False

    def _prepare_loop(self):
        materialized = self._materialized
        current = self._materialized_key
        carried = set()
        while True:
            self._wake.wait()
            with self._lock:
                task = self._pending
                self._pending = None
                self._wake.clear()
                if self._closed:
                    return
                if task is None: continue
            revision, ids, width, height = task
            key = revision_key(revision,width,height)
            ready_ids = []
            try:
                if current != key:
                    materialized, reused, reason = materialize_captions(
                        revision, materialized, full_builder=self._full_builder(revision),
                        cancel_check=self._stop_event.is_set)
                    with self._lock:
                        if self._closed:
                            return
                    self.rebuilt_cues += len(materialized.project.cues) - len(reused)
                    if reason:
                        self.full_rebuilds.append(reason)
                        del self.full_rebuilds[:-64]
                        from ..diagnostics.editor_diagnostics import record
                        record('CAPTION_REBUILD', reason=reason, cues=len(materialized.project.cues))
                    carried = set()
                    with self._lock:
                        if self._closed:
                            return
                        # A caption whose display cue was reused looks the
                        # same in the new revision: keep its prepared frame.
                        if current is not None and current[3:] == key[3:]:
                            for cue_id in reused:
                                prepared = self._frames.get((*current, cue_id))
                                if prepared is not None and (*key, cue_id) not in self._frames:
                                    self._frames[(*key, cue_id)] = prepared
                                    carried.add(cue_id)
                        self._materialized, self._materialized_key = materialized, key
                    current = key
                project = materialized.project
                from ..caption_style.visual_snapshot import build_visual_cue_snapshot
                from ..caption_style.bilingual_layout import companion_id
                present = {cue.id for cue in project.cues}
                ids = tuple(dict.fromkeys(item for cue_id in ids for item in (
                    (cue_id, companion_id(cue_id)) if companion_id(cue_id) in present else (cue_id,))))
                for cue_id in ids:
                    with self._lock:
                        if self._closed: break
                        if (*key,cue_id) in self._frames:
                            if cue_id in carried:
                                # Carried over, never announced for this key.
                                carried.discard(cue_id)
                                ready_ids.append(cue_id)
                            continue
                    try:
                        snapshot = build_visual_cue_snapshot(project, cue_id, width=width, height=height, fps=30.)
                        from ..caption_style.style_recipe import route_recipe,RecipeRoute
                        cue = next(c for c in project.cues if c.id == cue_id)
                        # Resolved snapshots add layout/font measurement fields.
                        # Those are presentation data, not authored capabilities.
                        # Routing that enriched payload promoted plain ASS cues
                        # and the boundary worker drew a second text layer while
                        # the foreground owner correctly remained NATIVE.
                        from ..caption_style.style_resolution import recipe_for_cue
                        payload=recipe_for_cue(project.style_recipes,cue)
                        route = route_recipe(payload) if payload else RecipeRoute('native',())
                        web = None
                        theme = snapshot.style_recipe.get('webTheme')
                        if theme:
                            from .live_web_preview import prepare_web_configuration
                            from ..caption_style.speaker_labels import template_speaker
                            speaker = template_speaker(project, cue)
                            web = prepare_web_configuration(theme,snapshot.text,speaker,(cue.end_ms-cue.start_ms)/1000.,
                                snapshot.style_recipe.get('layout',{}).get('webPlacement'), translation=snapshot.translation)
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
                        with self._lock:
                            if self._closed:
                                return
                        try:
                            fallback = basic_caption(project, cue_id, width, height, error)
                        except Exception:
                            fallback = None
                        with self._lock:
                            if self._closed:
                                return
                            self._failures[(*key, cue_id)] = FailedCaption(error, fallback)
                            while len(self._failures)>96:self._failures.popitem(last=False)
                        ready_ids.append(cue_id)
                        if not self._notify(error=f'{cue_id}: {type(exc).__name__}: {exc}'):
                            return
                if ready_ids and not self._notify(key=key, cue_ids=ready_ids):
                    return
            except Exception as exc:
                from ..caption_style.bilingual_layout import CaptionPreparationCancelled
                if isinstance(exc, CaptionPreparationCancelled):
                    return
                if not self._notify(error=f'{type(exc).__name__}: {exc}'):
                    return

    # Full rebuilds of projects this large go to a worker process: in process
    # they hold the GIL for ~1 ms per cue (2-3.5 s on 2090 bilingual cues).
    DISPLAY_PROCESS_MIN_CUES = 300

    def _full_builder(self, revision):
        cues = revision.timeline_cues if revision.timeline_cues is not None else revision.cues
        if (len(cues) < self.DISPLAY_PROCESS_MIN_CUES
                or os.environ.get("TWOBYTEASR_CAPTION_DISPLAY_PROCESS", "1") == "0"):
            return None
        from .caption_display_actor import build_in_worker
        self.worker_builds += 1
        return lambda current: build_in_worker(current, cancel_check=self._stop_event.is_set)

    def close(self, *_):
        with self._lock:
            self._closed=True
            self._stop_event.set()
            self._pending=None
            self._frames.clear()
            self._failures.clear()
            # The materialized copy is a whole project; release it with the session.
            self._materialized=None
            self._materialized_key=None
            self._wake.set()

    def worker_thread(self):
        """Return the Python thread for asynchronous retirement, not the QObject."""
        with self._lock:
            return self._thread
