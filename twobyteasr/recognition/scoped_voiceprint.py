"""Voiceprint comparison of anonymous API speaker labels; never identify a person by label.

Provider labels belong to one request: ``API_S01`` when the whole file was one
request, ``R002_S01`` when it was cut. MOSS Pro (2026-10-28) also splits one
person into several labels inside a single request, so labels of the same
request are compared too; only labels that speak at the same time are never
merged. Each label's own speech is embedded as two disjoint halves (alternate
captions), so a label must first agree with itself.

Strong groups are merged when a new recognition project is created (the merged
label stays in ``cue_cache`` and can be split back in 说话人管理); weaker groups
stay candidates for listening. Thresholds come from six real projects (plan
2026-10-28-moss-pro-voiceprint-merge). Vectors are held only in memory and the
subprocess temporary directory.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

VERSION = 'scoped-ecapa-review-v2'
_SCOPED = re.compile(r'^(?:R(\d+)|API)_([^\s]+)$')
# Cosine of the two whole-label voiceprints, the lowest of the four
# half-to-half pairs, and each label's own speech in seconds.
REVIEW = {'whole': .45, 'lowest': .40, 'seconds': 4.0}
AUTOMATIC = {'whole': .65, 'lowest': .60, 'seconds': 6.0}
MIN_SELF = .45            # a label's halves must agree before it is compared
AUTOMATIC_SELF = .55
HALF_SECONDS = 10.0
MIN_PIECE = .6
MAX_PIECE = 6.0
MAX_PIECES = 8            # per half: bounds the per-piece decode in 说话人管理
TRIM = .08                # the worker drops this much at both piece ends


def label_scope(label):
    """(request number, provider label) for an anonymous API label, else None."""
    match = _SCOPED.fullmatch(str(label or ''))
    return (int(match.group(1) or 1), match.group(2)) if match else None


def cue_signature(rows):
    import hashlib
    import json
    result = []
    for row in rows:
        label, a, b = _read(row)
        if isinstance(row, dict):
            key, text = row.get('id', row.get('cue_id', '')), row.get('text', '')
        else:
            key = getattr(row, 'id', getattr(row, 'cue_id', ''))
            text = getattr(row, 'text', '')
        result.append([str(key), round(a*1000), round(b*1000), label, str(text or '')])
    blob = json.dumps(result, ensure_ascii=False, separators=(',',':')).encode('utf8')
    return hashlib.sha256(blob).hexdigest()


def _read(row):
    if isinstance(row, dict):
        return str(row.get('speaker') or ''), float(row.get('start', 0)), float(row.get('end', 0))
    if hasattr(row, 'start_ms'):
        return str(row.speaker_id or ''), float(row.start_ms)/1000, float(row.end_ms)/1000
    return str(getattr(row, 'speaker', '') or ''), float(row.start), float(row.end)


def _spans(rows):
    spans = []
    for row in rows:
        try:
            label, a, b = _read(row)
        except (TypeError, ValueError, AttributeError):
            continue
        if label and math.isfinite(a) and math.isfinite(b) and 0 <= a < b:
            spans.append((a, b, label))
    return sorted(spans)


def sample_windows(rows):
    """Each scoped label's own speech as two disjoint halves (alternate captions).

    A caption that overlaps another label is left out: it may hold two voices.
    Every half keeps its longest pieces, up to ``HALF_SECONDS``.
    """
    spans = _spans(rows)
    mixed = set()
    for i, (a, b, label) in enumerate(spans):
        j = i+1
        while j < len(spans) and spans[j][0] < b:
            if spans[j][2] != label and min(b, spans[j][1])-spans[j][0] > .05:
                mixed.update((i, j))
            j += 1
    clean = defaultdict(list)
    for i, (a, b, label) in enumerate(spans):
        if i not in mixed and label_scope(label) and b-a >= MIN_PIECE:
            clean[label].append((a, min(b, a+MAX_PIECE)))
    if len(clean) > 64:
        raise ValueError('说话人标签过多，请分批试听并手动整理。')
    result = []
    for label in sorted(clean):
        for part in (0, 1):
            chosen, total = [], 0.
            for a, b in sorted(clean[label][part::2], key=lambda item: item[0]-item[1]):
                if total >= HALF_SECONDS or len(chosen) >= MAX_PIECES:
                    break
                chosen.append((a, b))
                total += b-a-2*TRIM
            for a, b in sorted(chosen):
                result.append({'id':f'OBS{len(result):04d}', 'label':label, 'part':part, 'start':a, 'end':b})
    return result


def _overlapping(left, right):
    a,b = sorted(left),sorted(right)
    i = j = 0
    while i < len(a) and j < len(b):
        x,y = a[i]; u,v = b[j]
        if min(y,v)-max(x,u) > .20:
            return True
        if y <= v:
            i += 1
        else:
            j += 1
    return False


def _passes(score, tier):
    return score.get('whole', -1) >= tier['whole'] and score.get('lowest', -1) >= tier['lowest']


def _complete_link(labels, allowed):
    """Merge groups only when every cross pair is allowed; best pairs first."""
    groups = [[label] for label in sorted(labels)]
    while True:
        choices = []
        for i,left in enumerate(groups):
            for j in range(i+1,len(groups)):
                cross = [allowed.get(tuple(sorted((a,b)))) for a in left for b in groups[j]]
                if all(cross):
                    choices.append((min(item['whole'] for item in cross), i, j))
        if not choices:
            break
        _, i, j = max(choices)
        groups[i] = sorted(groups[i] + groups[j])
        groups.pop(j)
    return [group for group in groups if len(group) > 1]


def proposals(rows, samples, embeddings):
    """Pair scores and complete-link groups; simultaneous speech is never grouped."""
    import numpy as np

    def vector(key):
        raw = embeddings.get('0|' + key)
        if raw is None:
            return None
        value = np.asarray(raw, dtype=float)
        if value.ndim != 1 or not len(value) or not np.isfinite(value).all():
            return None
        length = float(np.linalg.norm(value))
        return value/length if length > 1e-9 else None

    seconds = defaultdict(float)
    for sample in samples:
        seconds[sample['label']] += max(0., float(sample['end'])-float(sample['start'])-2*TRIM)
    spans = defaultdict(list)
    for a, b, label in _spans(rows):
        if label_scope(label):
            spans[label].append((a, b))
    voices, excluded, consistency = {}, {}, {}
    for label in sorted(spans):
        whole, *halves = (vector(label + suffix) for suffix in ('#w', '#0', '#1'))
        if (whole is None or any(item is None for item in halves) or len({len(whole), *map(len, halves)}) != 1
                or seconds[label] < REVIEW['seconds']):
            excluded[label] = 'insufficient_samples'
            continue
        consistency[label] = round(float(halves[0] @ halves[1]), 4)
        if consistency[label] < MIN_SELF:
            excluded[label] = 'inconsistent_samples'
            continue
        voices[label] = (whole, halves)
    pairs, conflicts = {}, []
    ordered = sorted(voices)
    for i, a in enumerate(ordered):
        for b in ordered[i+1:]:
            if len(voices[a][0]) != len(voices[b][0]):
                conflicts.append({'labels':[a,b], 'reason':'embedding_dimension'})
                continue
            if _overlapping(spans[a], spans[b]):
                conflicts.append({'labels':[a,b], 'reason':'overlap'})
                continue
            score = {'whole':round(float(voices[a][0] @ voices[b][0]), 4),
                     'lowest':round(min(float(x @ y) for x in voices[a][1] for y in voices[b][1]), 4)}
            if not _passes(score, REVIEW):
                continue
            strong = (_passes(score, AUTOMATIC) and min(seconds[a], seconds[b]) >= AUTOMATIC['seconds']
                      and min(consistency[a], consistency[b]) >= AUTOMATIC_SELF)
            pairs[(a,b)] = dict(score, same_request=label_scope(a)[0] == label_scope(b)[0],
                                tier='automatic' if strong else 'review')
    automatic = {key:value for key,value in pairs.items() if value['tier'] == 'automatic'}
    return {'version':VERSION, 'cue_signature':cue_signature(rows),
            'groups':_complete_link(ordered, pairs), 'automatic_groups':_complete_link(ordered, automatic),
            'excluded':excluded, 'conflicts':conflicts,
            'sample_counts':{label:sum(s['label'] == label for s in samples) for label in sorted(spans)},
            'sample_seconds':{label:round(value, 2) for label,value in sorted(seconds.items())},
            'self_consistency':consistency,
            'sample_intervals':[{'label':s['label'],'part':s['part'],'start':round(float(s['start']),3),
                                 'end':round(float(s['end']),3)} for s in samples],
            'pair_scores':[{'labels':list(pair), **score} for pair,score in sorted(pairs.items())],
            'thresholds':{'review':dict(REVIEW), 'automatic':dict(AUTOMATIC), 'self':MIN_SELF,
                          'automatic_self':AUTOMATIC_SELF},
            'meaning':'strong groups merged automatically on new projects; others are candidates for listening'}


def analyze_samples(rows, samples, parts, *, model_dir, main_python, worker_path, cancel_check=None):
    """Evaluate selected speech; the compact waveform and vectors are temporary."""
    import tempfile
    from pathlib import Path
    import numpy as np
    from ..model_integrity import verify_model_files
    from ..system.processes import run_speaker_embed_worker
    if len(samples) != len(parts) or len({item['label'] for item in samples}) < 2:
        return {'version':VERSION,'groups':[], 'automatic_groups':[], 'excluded':{}, 'conflicts':[],
                'sample_counts':{}, 'pair_scores':[], 'reason':'insufficient_samples'}
    packed, segments, length = [], [], 0
    for sample, part in zip(samples, parts):
        part = np.asarray(part, dtype=np.float32)
        if part.ndim != 1 or len(part) < int(16000*MIN_PIECE*.9) or not np.isfinite(part).all():
            raise ValueError('声纹样本不足或音频采样无效')
        span = {'start':length/16000, 'end':(length+len(part))/16000}
        # One decoded piece feeds its half and the label's whole voiceprint.
        segments += [dict(span, speaker=f"{sample['label']}#{sample['part']}"),
                     dict(span, speaker=f"{sample['label']}#w")]
        packed.append(part)
        length += len(part)
    pcm = np.concatenate(packed)
    if cancel_check and cancel_check():
        from .service import CancelledError
        raise CancelledError('声纹分析已取消')
    verify_model_files('speaker_embedding', Path(model_dir))
    with tempfile.TemporaryDirectory(prefix='2byte-voiceprint-') as folder:
        path = Path(folder)/'audio.npy'
        np.save(path, pcm, allow_pickle=False)
        manifest = {'audio_npy':str(path),'sample_rate':16000,'model_dir':str(model_dir),
                    'max_audio_seconds':2*HALF_SECONDS+MAX_PIECE,'chunk_overlap_seconds':0,
                    'audio_seconds':len(pcm)/16000,'threads':4,'batch_size':12,
                    'chunks':[{'offset':0,'duration':len(pcm)/16000,'segments':segments}]}
        vectors = run_speaker_embed_worker(worker_path=str(worker_path),main_python=str(main_python),
                                           manifest=manifest,cancel_check=cancel_check)
    return proposals(rows,samples,vectors)


def analyze_audio(rows, audio, *, model_dir, main_python, worker_path, cancel_check=None):
    """Compute candidates from the current frozen 16 kHz mono waveform."""
    import numpy as np
    pcm = np.asarray(audio, dtype=np.float32)
    if pcm.ndim != 1 or not len(pcm):
        raise ValueError('音频不是有效的 16 kHz 单声道采样')
    samples = sample_windows(rows)
    parts = [pcm[int(s['start']*16000):int(s['end']*16000)] for s in samples]
    return analyze_samples(rows,samples,parts,model_dir=model_dir,main_python=main_python,
                           worker_path=worker_path,cancel_check=cancel_check)


def decode_sample_windows(media_path, samples, *, ffmpeg, cancel_check=None):
    """Decode only selected pieces from the original single audio source."""
    import subprocess
    import time
    import numpy as np
    from ..system.processes import popen_hidden_subprocess, stop_process_tree
    from .service import CancelledError
    parts = []
    for sample in samples:
        if cancel_check and cancel_check():
            raise CancelledError('声纹分析已取消')
        command = [str(ffmpeg),'-v','error','-nostdin','-ss',f"{sample['start']:.6f}",
                   '-i',str(media_path),'-t',f"{sample['end']-sample['start']:.6f}",
                   '-vn','-ac','1','-ar','16000','-f','f32le','pipe:1']
        process = popen_hidden_subprocess(command,purpose='speaker sample decode',stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        deadline = time.monotonic()+60
        try:
            while True:
                try:
                    output,error = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_check and cancel_check():
                        raise CancelledError('声纹分析已取消')
                    if time.monotonic()>deadline:
                        raise RuntimeError('声纹音频采样超时')
            if process.returncode:
                raise RuntimeError('声纹音频采样失败：'+error.decode('utf8',errors='replace')[-300:])
            part = np.frombuffer(output,dtype='<f4').copy()
            if len(part)<int(16000*MIN_PIECE*.9):
                raise ValueError('声纹音频样本太短，请检查素材或轨道。')
            parts.append(part)
        finally:
            if process.poll() is None:
                stop_process_tree(process)
    return parts


def _decided(project, state, label):
    """A person chose this speaker's use, name, colour, visibility or host flag."""
    speaker = next((item for item in project.speakers if item.id == label), None)
    if speaker is None:
        return True
    entry = project.generation_metadata.get('speaker_names', {}).get('entries', {}).get(label) or {}
    return bool((state.get('roles') or {}).get(label) != 'unconfirmed' or speaker.is_host or speaker.hidden
                or speaker.color or (entry and ((entry.get('automatic') is False and speaker.name not in ('',label))
                                                or entry.get('name') != speaker.name))
                or (not entry and speaker.name not in ('',label)))


def reviewable_groups(project, groups):
    """Undecided labels of each group; one decided 主要 speaker leads its group.

    That speaker keeps its name and role and receives the others, so naming
    the host first does not stop the host's other labels from joining it.
    """
    state = project.generation_metadata.get('speaker_recovery') or {}
    roles = state.get('roles') or {}
    present = {speaker.id for speaker in project.speakers}
    result = []
    for group in groups or ():
        group = [label for label in group if label in present]
        decided = [label for label in group if _decided(project, state, label)]
        open_labels = [label for label in group if label not in decided]
        anchor = decided if len(decided) == 1 and roles.get(decided[0]) in ('main', 'unconfirmed') else []
        if open_labels and len(anchor + open_labels) > 1:
            result.append(anchor + open_labels)
    return result


def _members(report):
    return {str(key):[str(item) for item in value] for key,value in (report.get('members') or {}).items()}


def _check_groups(project, report, groups, tier):
    """Every original label pair inside a group must meet ``tier``; no simultaneous speech."""
    allowed = {tuple(sorted(item.get('labels') or ())):item for item in report.get('pair_scores') or ()
               if _passes(item, tier) and (tier is REVIEW or item.get('tier') == 'automatic')}
    members = _members(report)
    intervals = defaultdict(list)
    for cue in project.cues:
        intervals[cue.speaker_id].append((cue.start_ms/1000,cue.end_ms/1000))
    for group in groups:
        if len(group) < 2 or len(set(group)) != len(group):
            raise ValueError('声纹候选不完整或存在冲突，未应用。')
        for i,a in enumerate(group):
            for b in group[i+1:]:
                if any(tuple(sorted((x,y))) not in allowed for x in members.get(a,[a]) for y in members.get(b,[b])):
                    raise ValueError('声纹候选不完整或存在冲突，未应用。')
                if _overlapping(intervals[a],intervals[b]):
                    raise ValueError('重叠发言存在身份冲突，未应用。')


def _merge(project, report, groups, *, reviewed_by):
    """One project copy with each group folded into its first label."""
    import copy
    from dataclasses import asdict
    from ..projects.studio_project import SubtitleProject
    state = project.generation_metadata.get('speaker_recovery') or {}
    labels = [label for group in groups for label in group]
    roles = state.get('roles') or {}
    if len(labels) != len(set(labels)) or any(not label_scope(label) for label in labels):
        raise ValueError('说话人用途已变化，请重新分析。')
    # Per label, not per project: a role the user chose for another speaker
    # does not block voices nobody has decided yet. In a reviewed group the
    # first label may be the 主要 speaker a person already chose (the target).
    for group in groups:
        for index, label in enumerate(group):
            if (index == 0 and reviewed_by == 'user' and roles.get(label) in ('main', 'unconfirmed')
                    and label in {speaker.id for speaker in project.speakers}):
                continue
            if roles.get(label) != 'unconfirmed':
                raise ValueError('候选包含已人工确认用途的说话人，请使用手动合并。')
            if _decided(project, state, label):
                raise ValueError('候选包含人工设置的说话人，请使用手动合并。')
    tier = AUTOMATIC if reviewed_by == 'automatic' else REVIEW
    _check_groups(project, report, groups, tier)
    result = SubtitleProject.from_dict(project.to_dict())
    state = copy.deepcopy(state)
    saved = state.setdefault('cue_cache', {})
    display = state.setdefault('display_labels', {})
    organization = result.generation_metadata.setdefault('speaker_organization', {})
    originals = organization.setdefault('original_speakers', {})
    sources = {}
    for group in groups:
        target = group[0]
        for label in group[1:]:
            sources[label] = target
            state['roles'][label] = 'merge:' + target
    for speaker in result.speakers:
        if speaker.id in sources:
            originals[speaker.id] = asdict(speaker)
            display[speaker.id] = speaker.name or speaker.id
    for cue in result.cues:
        if cue.speaker_id in sources:
            label = cue.speaker_id
            saved.setdefault(label, []).append(asdict(cue))
            cue.speaker_id = sources[label]
    # Existing cache entries are retained but a cue may only appear once.
    for label in sources:
        saved[label] = list({row['id']:row for row in saved.get(label, []) if isinstance(row,dict) and row.get('id')}.values())
    result.speakers = [speaker for speaker in result.speakers if speaker.id not in sources]
    order = [item for item in result.studio_state.get('speaker_track_order', []) if item not in sources]
    if order or 'speaker_track_order' in result.studio_state:
        result.studio_state['speaker_track_order'] = order
    members = _members(report)
    for label, target in sources.items():
        members[target] = sorted(set(members.get(target, [target])) | set(members.pop(label, [label])))
    return result, state, display, members


def apply_reviewed(project, report):
    """Prepare one undoable project update after the user reviews proposals."""
    import copy
    from ..projects.speaker_names import ensure_speaker_names
    if (report.get('version') != VERSION or report.get('cue_signature') != cue_signature(project.cues)):
        raise ValueError('字幕或说话人已变化，请重新分析声纹。')
    groups = report.get('groups') or []
    if not groups:
        raise ValueError('没有可应用的声纹候选。')
    result, state, display, members = _merge(project, report, groups, reviewed_by='user')
    display.update(ensure_speaker_names(result))
    pending = [label for label,role in state['roles'].items() if role == 'unconfirmed']
    state.update(needs_confirmation=bool(pending), confirmed_by='user', unconfirmed_candidates=pending)
    state['voiceprint_review'] = {
        key:copy.deepcopy(report.get(key)) for key in
        ('version','groups','cue_signature','sample_counts','sample_intervals','pair_scores','conflicts','meaning')}
    state['voiceprint_review'].update(reviewed_by='user', members=members)
    result.generation_metadata['speaker_recovery'] = state
    result.validate()
    return result


def apply_automatic(project):
    """New recognition projects only: merge strong groups in place; True when merged.

    Captions, times and translations are untouched; only their speaker moves.
    The decision is per label, so caption text normalised after the
    comparison does not matter. Remaining candidates are re-stamped for
    说话人管理 against the merged captions.
    """
    import copy
    from ..projects.speaker_names import default_names, initialize_speaker_names
    state = project.generation_metadata.get('speaker_recovery') or {}
    processing = state.get('processing') or {}
    report = processing.get('voiceprint_review')
    if (not isinstance(report, dict) or report.get('version') != VERSION or state.get('confirmed_by')
            or not report.get('automatic_groups')):
        return False
    present = {speaker.id for speaker in project.speakers}
    groups = [list(group) for group in report['automatic_groups'] if set(group) <= present]
    if not groups:
        return False
    try:
        result, state, display, members = _merge(project, report, groups, reviewed_by='automatic')
    except ValueError as exc:
        processing['voiceprint_automatic_skipped'] = str(exc)
        return False
    # Nobody has named anyone yet: number the remaining voices S00, S01… again,
    # and give each merged label the next free number (reserved), so its card
    # and a later split never show a name another speaker already has.
    initialize_speaker_names(result)
    entries = result.generation_metadata['speaker_names']['entries']
    first = {}
    for cue in sorted(project.cues, key=lambda item: (item.start_ms, item.end_ms)):
        first.setdefault(cue.speaker_id, cue.start_ms)
    merged = sorted((label for group in groups for label in group[1:]), key=lambda label: (first.get(label, 0), label))
    originals = result.generation_metadata['speaker_organization']['original_speakers']
    for label, name in default_names(merged, [entry['name'] for entry in entries.values()]).items():
        entries[label] = dict(name=name, automatic=True, raw_label=label, scope=result.project_id,
                              backend=state.get('source', 'unknown'))
        display[label] = name
        if isinstance(originals.get(label), dict):
            originals[label]['name'] = name
    targets = {label:target for target,labels in members.items() for label in labels}
    remaining = []
    for group in report.get('groups') or ():
        mapped = sorted(set(targets.get(label, label) for label in group))
        if len(mapped) > 1 and set(mapped) <= {speaker.id for speaker in result.speakers}:
            remaining.append(mapped)
    review = copy.deepcopy(report)
    review.update(groups=remaining, members=members, cue_signature=cue_signature(result.cues))
    state['processing'] = dict(copy.deepcopy(processing), voiceprint_review=review)
    state['voiceprint_automatic'] = {'version':VERSION, 'groups':groups, 'reviewed_by':'automatic',
                                     'pair_scores':copy.deepcopy(report.get('pair_scores') or [])}
    several = len(result.speakers) > 1
    state['needs_confirmation'] = several
    state['unconfirmed_candidates'] = [label for label,role in state['roles'].items() if role == 'unconfirmed']
    result.generation_metadata['speaker_recovery'] = state
    result.generation_metadata.setdefault('speaker_organization', {})['needs_manual_host_selection'] = several
    project.cues, project.speakers = result.cues, result.speakers
    project.generation_metadata, project.studio_state = result.generation_metadata, result.studio_state
    return True
