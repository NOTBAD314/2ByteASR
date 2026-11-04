"""Private caption snapshots and additive edits on the existing Studio undo stack."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, replace
from types import SimpleNamespace

from PySide6.QtGui import QUndoCommand

from ..projects.studio_project import StudioCue, StudioSpeaker, SubtitleStyle
from ..projects.studio_runtime_state import DirtyDomain as D, state_for
from .studio_commands import _commit_mutation


def _id(prefix):
    return prefix + '-' + uuid.uuid4().hex


def _remap(value, ids):
    if isinstance(value, dict):
        return {key: (_remap(item, ids) if key not in ('text', 'source_text', 'original_text',
                'original_source', 'original_translation') else item) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap(item, ids) for item in value]
    return ids.get(value, value) if isinstance(value, str) else value


def capture_captions(project, cue_ids, *, layer='original'):
    """Copy stored objects, not text or a live reference to the source project."""
    from ..subtitle_rules import subtitle_translation as st
    from .studio_caption_timeline import KEY
    from ..recognition.cue_word_alignment import cue_words
    wanted = set(cue_ids)
    cues = sorted((c for c in project.cues if c.id in wanted), key=lambda c: (c.start_ms, c.end_ms, c.id))
    records = (st._migrated_container(project.generation_metadata, project.cues)[0] or {}).get('records', {})
    if layer == 'translation':
        from ..caption_style.bilingual_layout import display_cues, settings_from_state
        values = project.generation_metadata.get('translations', {})
        cues = [c for c in cues if values.get(c.id)]
        cues = display_cues(cues, translations=values,
            settings=replace(settings_from_state(project.studio_state), mode='translation'),
            styles=project.styles, speakers=project.speakers, style_recipes=project.style_recipes,
            effects=project.effects)
    rows = []
    receipts = project.studio_state.get(KEY, {}).get('instances', {})
    sources = project.generation_metadata.get('subtitle_imports', {}).get('cues', {})
    tracks = project.generation_metadata.get('subtitle_imports', {}).get('tracks', {})
    for cue in cues:
        receipt = copy.deepcopy(receipts.get(cue.id, {}))
        words, reason = cue_words(project, cue) if layer == 'original' else ([], 'copied_translation')
        receipt.update(text=cue.text, words=[asdict(w) for w in words], word_alignment=reason,
                       word_base_words=[asdict(w) for w in words],
                       word_base_interval=[cue.start_ms, cue.end_ms], word_clock_offset_ms=0)
        rows.append(dict(cue=asdict(cue), receipt=receipt,
            record=copy.deepcopy(records.get(cue.id)) if layer == 'original' else None,
            source=copy.deepcopy(sources.get(cue.id)), track=copy.deepcopy(tracks.get(cue.speaker_id)),
            term_override=copy.deepcopy(project.studio_state.get('term_word_overrides', {}).get(cue.id))))
    return dict(version=1, layer=layer, project_id=project.project_id, target=st.container_target(project), rows=rows,
        speakers=[asdict(s) for s in project.speakers if any(c.speaker_id == s.id for c in cues)],
        styles=[asdict(s) for s in project.styles], recipes=copy.deepcopy(project.style_recipes))


class PasteCaptionsCommand(QUndoCommand):
    """Only inserted entities/associations are owned; unrelated cues stay live."""
    def __init__(self, project, payload, playhead_ms, *, changed=None):
        super().__init__('复制字幕')
        if payload.get('version') != 1 or not payload.get('rows'):
            raise ValueError('剪贴板没有可复制的字幕对象')
        self.project, self.changed = project, changed
        data = copy.deepcopy(payload)
        ids = {row['cue']['id']: _id('cue') for row in data['rows']}
        # A partial split group must not remain joined to its source group.
        for row in data['rows']:
            group = row['cue'].get('appearance_override', {}).get('translation_group', {}).get('id')
            if group:
                ids.setdefault(group, _id('translation-group'))
        delta = max(0, int(playhead_ms)) - min(int(row['cue']['start_ms']) for row in data['rows'])
        self.speakers, self.styles, self.recipes = [], [], {}
        self.tracks, self.sources, self.records, self.receipts, self.terms = {}, {}, {}, {}, {}
        self.cues = []
        speaker_map = {}
        current_speakers = {s.id for s in project.speakers}
        for row in data['rows']:
            sid = row['cue']['speaker_id']
            if sid in speaker_map:
                continue
            speaker = next((s for s in data.get('speakers', ()) if s['id'] == sid), {'id': sid, 'name': sid})
            if data['layer'] == 'translation' or sid not in current_speakers:
                speaker = copy.deepcopy(speaker)
                speaker['id'] = _id('translation-copy' if data['layer'] == 'translation' else 'speaker-copy')
                if data['layer'] == 'translation':
                    speaker['name'] += ' · 译文副本（' + data['target'] + '）'
                self.speakers.append(StudioSpeaker(**speaker))
            speaker_map[sid] = speaker['id']
        style_map = {}
        for row in data['rows']:
            for style_id in (row['cue']['style_id'], row['cue'].get('base_preset_id')):
                if not style_id or style_id in style_map:
                    continue
                style = next((s for s in data.get('styles', ()) if s['id'] == style_id), None)
                existing = next((s for s in project.styles if s.id == style_id), None)
                recipe = data.get('recipes', {}).get(style_id)
                if style and (existing is None or asdict(existing) != style
                              or project.style_recipes.get(style_id) != recipe):
                    new = _id('style-copy')
                    self.styles.append(SubtitleStyle(**dict(style, id=new)))
                    if recipe is not None:
                        self.recipes[new] = copy.deepcopy(recipe)
                    style_map[style_id] = new
                else:
                    style_map[style_id] = style_id
        for row in data['rows']:
            raw = row['cue']; old_id = raw['id']
            cue = StudioCue(**_remap(raw, ids)); cue.id = ids[old_id]
            cue.start_ms += delta; cue.end_ms += delta
            cue.speaker_id = speaker_map[raw['speaker_id']]
            cue.style_id = style_map.get(cue.style_id, cue.style_id)
            cue.base_preset_id = style_map.get(cue.base_preset_id, cue.base_preset_id)
            if data['layer'] == 'translation':
                cue.original_text = cue.text
                cue.evidence_refs = []
                cue.appearance_override.pop('translation_group', None)
                self.tracks[cue.speaker_id] = dict(role='translation', language=data['target'],
                    speaker=next(s.name for s in self.speakers if s.id == cue.speaker_id))
            elif row.get('track') and cue.speaker_id != raw['speaker_id']:
                self.tracks[cue.speaker_id] = copy.deepcopy(row['track'])
            cue.validate(); self.cues.append(cue)
            # source_cue_id(s) names immutable evidence in source_archive.
            # It must keep the original ID; only live translation associations
            # follow the newly authored objects.
            receipt = copy.deepcopy(row['receipt'])
            if 'translation_parent_ids' in receipt:
                receipt['translation_parent_ids'] = _remap(receipt['translation_parent_ids'], ids)
            if data.get('project_id') != project.project_id:
                cue.evidence_refs = []
                for key in ('source_cue_id', 'source_cue_ids', 'source_spans', 'evidence_refs', 'source_path'):
                    receipt.pop(key, None)
                for key in ('words', 'word_base_words'):
                    for word in receipt.get(key, ()):
                        word['evidence_ref'] = ''
            for key in ('words', 'word_base_words'):
                for word in receipt.get(key, ()):
                    word['start_ms'] += delta; word['end_ms'] += delta
            receipt['word_base_interval'] = [cue.start_ms, cue.end_ms]
            receipt['word_clock_offset_ms'] = 0
            if 'evidence_clock_offset_ms' in receipt:
                receipt['evidence_clock_offset_ms'] += delta
            self.receipts[cue.id] = receipt
            if row.get('source'):
                self.sources[cue.id] = _remap(row['source'], ids)
            if row.get('record'):
                self.records[cue.id] = _remap(row['record'], ids)
            if row.get('term_override'):
                term = _remap(row['term_override'], ids)
                for word in term.get('words', ()):
                    word['start_ms'] += delta; word['end_ms'] += delta
                self.terms[cue.id] = term
        self.ids = {c.id for c in self.cues}
        if len(self.ids) != len(self.cues) or self.ids & {c.id for c in project.cues}:
            raise ValueError('副本字幕 ID 冲突')
        self.selection_before = state_for(project).selected_cue_id
        self.metadata_presence = {k: k in project.generation_metadata for k in
                                  ('translations', 'translation_records', 'subtitle_imports')}
        self.state_presence = {k: k in project.studio_state for k in ('caption_timeline', 'term_word_overrides')}
        self.copied_selection = SimpleNamespace(cue_ids=self.ids, video_ids=set(), audio_ids=set(), count=len(self.ids))
        self.outcome = dict(applied=False, error=None)

    def _apply(self, forward):
        p = self.project
        def patch(mapping, values):
            for key, value in values.items():
                if forward:
                    mapping[key] = copy.deepcopy(value)
                else:
                    mapping.pop(key, None)
        def mutate():
            p.cues = [c for c in p.cues if c.id not in self.ids]
            if forward:
                p.cues.extend(copy.deepcopy(self.cues))
                p.cues.sort(key=lambda c: (c.start_ms, c.end_ms, c.id))
            for attr, additions in (('speakers', self.speakers), ('styles', self.styles)):
                keys = {s.id for s in additions}
                setattr(p, attr, [s for s in getattr(p, attr) if s.id not in keys] + (copy.deepcopy(additions) if forward else []))
            patch(p.style_recipes, self.recipes)
            if self.records:
                from ..subtitle_rules.subtitle_translation import _migrated_container
                container = p.generation_metadata.get('translation_records')
                if container is None:
                    container = _migrated_container(p.generation_metadata, p.cues)[0] or {'version': 1, 'records': {}}
                    p.generation_metadata['translation_records'] = container
                patch(container.setdefault('records', {}), self.records)
                patch(p.generation_metadata.setdefault('translations', {}),
                      {key: record['text'] for key, record in self.records.items() if record.get('text')})
            if self.tracks or self.sources:
                info = p.generation_metadata.setdefault('subtitle_imports', {'version': 1})
                patch(info.setdefault('tracks', {}), self.tracks)
                patch(info.setdefault('cues', {}), self.sources)
            patch(p.studio_state.setdefault('caption_timeline', {'version': 1}).setdefault('instances', {}), self.receipts)
            if self.terms:
                patch(p.studio_state.setdefault('term_word_overrides', {}), self.terms)
            if not forward:
                for key, existed in self.metadata_presence.items():
                    value = p.generation_metadata.get(key, {})
                    owned = ('records', 'tracks', 'cues', 'instances')
                    if not existed and not any(value.get(k) for k in owned) and (key != 'translations' or not value):
                        p.generation_metadata.pop(key, None)
                for key, existed in self.state_presence.items():
                    if not existed and not p.studio_state.get(key, {}).get('instances', p.studio_state.get(key, {})):
                        p.studio_state.pop(key, None)
            runtime = state_for(p)
            runtime.entity_epoch_sequence += 1
            for key in self.ids:
                if forward: runtime.entity_epochs[key] = runtime.entity_epoch_sequence
                else: runtime.entity_epochs.pop(key, None)
        before_cues, before_speakers = p.cues, p.speakers
        try:
            _commit_mutation(p, action_id=self.text(), cue_ids=self.ids, mutate=mutate, changed=self.changed,
                dirty=D.CUE_MODEL | D.CUE_CONTENT | D.CUE_TIMING | D.CUE_STYLE | D.PROJECT_METADATA |
                    D.TIMELINE_INDEX | D.TIMELINE_PIXELS | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.QC | D.AUTOSAVE,
                selection_after=self.cues[0].id if forward else self.selection_before,
                snapshot_cues=False, sync_caption_words=False,
                studio_state_keys=('caption_timeline', 'term_word_overrides'),
                generation_metadata_keys=('translations', 'translation_records', 'subtitle_imports'))
        except Exception:
            p.cues, p.speakers = before_cues, before_speakers
            state_for(p).reindex_cues(p)
            raise

    def redo(self):
        self.outcome.update(applied=False, error=None)
        try:
            self._apply(True)
            self.outcome['applied'] = True
        except Exception as exc:
            self.outcome['error'] = str(exc)
            self.setObsolete(True)

    def undo(self): self._apply(False)
