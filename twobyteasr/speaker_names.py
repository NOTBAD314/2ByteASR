"""Persistent presentation labels, independent of project-local identity keys."""
from __future__ import annotations

import re

from .i18n import tr

_AUTO = re.compile(r'(?:S\d+|(?:NEMO|MOSS|ECAPA|SPEAKER)[_ -]?\d+|说话人\s*\d+|\d+)', re.I)
_STANDARD = re.compile(r'S\d{2,}')
_SEMANTIC = {'UNASSIGNED':'待确认', 'SUBTITLES':'统一字幕', 'GAME_BACKGROUND':'游戏背景声'}


def default_names(labels, reserved=(), *, preserve_canonical=True):
    """Allocate without identifying two raw labels by their numerical suffix."""
    labels = list(dict.fromkeys(map(str, labels)))
    used = {str(name).casefold() for name in reserved}
    result = {}
    for label in labels:
        if label in _SEMANTIC:
            result[label] = _SEMANTIC[label]
            used.add(result[label].casefold())
            continue
        if preserve_canonical and _STANDARD.fullmatch(label) and label.casefold() not in used:
            result[label] = label
            used.add(label.casefold())
    for label in labels:
        if label in result:
            continue
        index = 0
        while f'S{index:02d}'.casefold() in used:
            index += 1
        result[label] = f'S{index:02d}'
        used.add(result[label].casefold())
    return result


def initialize_speaker_names(project):
    labels = list(dict.fromkeys(c.speaker_id for c in sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms))))
    labels += [s.id for s in project.speakers if s.id not in labels]
    names = default_names(labels, preserve_canonical=False)
    entries = {}
    recovery = project.generation_metadata.get('speaker_recovery', {})
    for speaker in project.speakers:
        speaker.name = names[speaker.id]
        entries[speaker.id] = dict(name=speaker.name, automatic=True, raw_label=speaker.id,
            scope=project.project_id, backend=recovery.get('source', 'unknown'))
    project.generation_metadata['speaker_names'] = dict(version=1, entries=entries)


def ensure_speaker_names(project):
    """Migrate only provably automatic names; never rewrite IDs or cue ownership.

    Entries for removed identities remain reserved, so restoring or dragging
    cues cannot renumber other speakers. Identity scope is project/task local;
    identical backend labels in another recording prove no correspondence.
    """
    state = project.generation_metadata.setdefault('speaker_names', {'version': 1, 'entries': {}})
    entries = state.setdefault('entries', {})
    recovery = project.generation_metadata.get('speaker_recovery', {})
    previous = recovery.get('display_labels', {})
    speakers = {s.id: s for s in project.speakers}
    ordered = list(dict.fromkeys(c.speaker_id for c in sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms))))
    ordered += [s.id for s in project.speakers if s.id not in ordered]
    used = {str(e.get('name')) for e in entries.values()}
    # Existing canonical IDs and human labels have priority over a legacy
    # recovery alias that happens to have the same text.
    priority_names = {s.name for s in project.speakers if s.name and (
        s.name == s.id and _STANDARD.fullmatch(s.id) or
        s.name != s.id and s.name != previous.get(s.id))}
    used.update(priority_names)
    pending = []
    for identity in ordered:
        speaker = speakers.get(identity)
        if speaker is None:
            continue
        if identity in _SEMANTIC and speaker.name in {'', identity}:
            speaker.name = _SEMANTIC[identity]
        entry = entries.get(identity)
        if entry:
            # An explicit rename wins over the allocator's remembered name.
            if speaker.name and speaker.name != entry['name'] and not (
                entry.get('automatic') and speaker.name == identity):
                entry.update(name=speaker.name, automatic=False)
            speaker.name = entry['name']
        else:
            automatic = not speaker.name or (speaker.name == identity and bool(_AUTO.fullmatch(identity))) or (
                previous.get(identity) == speaker.name and bool(_STANDARD.fullmatch(speaker.name)))
            if automatic and (not _STANDARD.fullmatch(speaker.name or '') or (
                speaker.name in used and speaker.name != identity)):
                pending.append(identity)
                continue
            entries[identity] = dict(name=speaker.name, automatic=automatic, raw_label=identity,
                scope=project.project_id, backend=recovery.get('source', 'legacy'))
        used.add(speaker.name)
    for identity in pending:
        speaker = speakers[identity]
        name = default_names([identity], used)[identity]
        entries[identity] = dict(name=name, automatic=True, raw_label=identity,
            scope=project.project_id, backend=recovery.get('source', 'legacy'))
        speaker.name = name
        used.add(name)
    return {s.id: s.name for s in project.speakers}


def display_speaker_name(project, speaker):
    from .i18n import tr
    entry = project.generation_metadata.get('speaker_names', {}).get('entries', {}).get(speaker.id, {})
    name = speaker.name or speaker.id
    if entry.get('automatic'):
        if speaker.id in _SEMANTIC and name == _SEMANTIC[speaker.id]:
            return tr(name)
        match = re.fullmatch(r'说话人\s*(\d+)', name)
        if match:
            return tr('说话人 {number}', number=match[1])
    return name
