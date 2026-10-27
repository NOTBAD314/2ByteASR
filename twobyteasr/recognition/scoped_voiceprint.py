"""Reviewable cross-request voiceprint proposals; never identify a person by label.

The thresholds select candidates for listening, not automatic identity truth.
Vectors are held only in memory and the subprocess temporary directory.
"""
from __future__ import annotations

import math
import re
import heapq
from collections import defaultdict

VERSION = 'scoped-ecapa-review-v1'
_SCOPED = re.compile(r'^R(\d+)_([^\s]+)$')
MIN_MEDIAN = .53
MIN_LOWER_QUARTILE = .48
MIN_WITHIN_MEDIAN = .50


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


def sample_windows(rows, *, count=3):
    """Choose separated mid-cue speech, avoiding another labeled speaker."""
    spans = []
    for row in rows:
        try:
            label, a, b = _read(row)
        except (TypeError, ValueError, AttributeError):
            continue
        if label and math.isfinite(a) and math.isfinite(b) and 0 <= a < b:
            spans.append((label, a, b))
    candidates, possible = defaultdict(list), []
    for label, a, b in spans:
        if not _SCOPED.fullmatch(label) or b-a < 2.8:
            continue
        mid = (a+b)/2
        left, right = mid-1.3, mid+1.3
        possible.append((left, right, label))
    # Every window is the same length, so its right edge is monotone too.
    # A sweep avoids comparing every caption with every other caption.
    ordered = sorted(spans, key=lambda item:item[1])
    active, counts, cursor = [], defaultdict(int), 0
    for left, right, label in sorted(possible):
        while cursor < len(ordered) and ordered[cursor][1] < right:
            other, start, end = ordered[cursor]
            heapq.heappush(active, (end, cursor, other))
            counts[other] += 1
            cursor += 1
        while active and active[0][0] <= left:
            _, _, other = heapq.heappop(active)
            counts[other] -= 1
            if not counts[other]:
                del counts[other]
        if any(other != label for other in counts):
            continue
        candidates[label].append((left, right))
    if len(candidates) > 64:
        raise ValueError('说话人标签过多，请分批试听并手动整理。')
    result = []
    for label in sorted(candidates):
        options = sorted(candidates[label])
        positions = [min(len(options)-1, i*len(options)//max(1,count-1)) for i in range(count)]
        chosen = []
        for position in positions:
            left,right = options[position]
            if any(min(right,y) > max(left,x) for x,y in chosen):
                continue
            chosen.append((left,right))
            result.append({'id':f'OBS{len(result):04d}', 'label':label,
                           'start':left, 'end':right})
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


def proposals(rows, samples, embeddings):
    """Complete-link candidate groups with scope and overlap conflicts barred."""
    import numpy as np
    grouped, windows = defaultdict(list), defaultdict(list)
    for sample in samples:
        raw = embeddings.get('0|' + sample['id'])
        if raw is None:
            continue
        vector = np.asarray(raw, dtype=float)
        if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all():
            continue
        length = float(np.linalg.norm(vector))
        if length > 1e-9:
            grouped[sample['label']].append(vector/length)
            windows[sample['label']].append((float(sample['start']),float(sample['end'])))
    spans = defaultdict(list)
    for row in rows:
        try:
            label,a,b = _read(row)
        except (TypeError, ValueError, AttributeError):
            continue
        if _SCOPED.fullmatch(label) and math.isfinite(a) and math.isfinite(b) and a < b:
            spans[label].append((a,b))
    labels = sorted(spans)
    reliable, excluded = {}, {}
    for label in labels:
        vectors = grouped[label]
        intervals = sorted(windows[label])
        if (len(vectors) < 2 or len({len(v) for v in vectors}) != 1
                or any(x[1] > y[0] for x,y in zip(intervals,intervals[1:]))):
            excluded[label] = 'insufficient_samples'
            continue
        within = [float(x@y) for i,x in enumerate(vectors) for y in vectors[i+1:]]
        if float(np.median(within)) < MIN_WITHIN_MEDIAN:
            excluded[label] = 'inconsistent_samples'
        else:
            reliable[label] = vectors
    pairs, conflicts = {}, []
    for i,a in enumerate(sorted(reliable)):
        for b in sorted(reliable)[i+1:]:
            if len(reliable[a][0]) != len(reliable[b][0]):
                conflicts.append({'labels':[a,b], 'reason':'embedding_dimension'})
                continue
            same_request = _SCOPED.fullmatch(a).group(1) == _SCOPED.fullmatch(b).group(1)
            overlapping = _overlapping(spans[a],spans[b])
            if same_request or overlapping:
                conflicts.append({'labels':[a,b], 'reason':'same_request' if same_request else 'overlap'})
                continue
            values = [float(x@y) for x in reliable[a] for y in reliable[b]]
            median, lower = float(np.median(values)), float(np.quantile(values,.25))
            if median >= MIN_MEDIAN and lower >= MIN_LOWER_QUARTILE:
                pairs[(a,b)] = {'median':round(median,4), 'lower_quartile':round(lower,4)}
    groups = [[label] for label in sorted(reliable)]
    while True:
        choices = []
        for i,left in enumerate(groups):
            for j in range(i+1,len(groups)):
                right = groups[j]
                cross = [pairs.get(tuple(sorted((a,b)))) for a in left for b in right]
                if all(cross):
                    choices.append((min(item['median'] for item in cross), i, j))
        if not choices:
            break
        _, i, j = max(choices)
        groups[i] = sorted(groups[i] + groups[j])
        groups.pop(j)
    return {'version':VERSION, 'cue_signature':cue_signature(rows), 'groups':[g for g in groups if len(g)>1], 'excluded':excluded,
            'conflicts':conflicts, 'sample_counts':{key:len(value) for key,value in grouped.items()},
            'sample_intervals':[{'label':s['label'],'start':round(float(s['start']),3),
                                 'end':round(float(s['end']),3)} for s in samples if '0|'+s['id'] in embeddings],
            'pair_scores':[{'labels':list(pair), **score} for pair,score in sorted(pairs.items())],
            'meaning':'candidate for listening; not automatic identity confirmation'}


def analyze_samples(rows, samples, parts, *, model_dir, main_python, worker_path, cancel_check=None):
    """Evaluate bounded samples; the compact waveform and vectors are temporary."""
    import tempfile
    from pathlib import Path
    import numpy as np
    from ..model_integrity import verify_model_files
    from ..system.processes import run_speaker_embed_worker
    if len(samples) != len(parts) or len({item['label'] for item in samples}) < 2:
        return {'version':VERSION,'groups':[], 'excluded':{}, 'conflicts':[], 'sample_counts':{},
                'pair_scores':[], 'reason':'insufficient_samples'}
    packed, segments, length = [], [], 0
    for sample, part in zip(samples, parts):
        part = np.asarray(part, dtype=np.float32)
        if part.ndim != 1 or len(part) < 16000*2 or not np.isfinite(part).all():
            raise ValueError('声纹样本不足或音频采样无效')
        segments.append({'speaker':sample['id'], 'start':length/16000, 'end':(length+len(part))/16000})
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
                    'max_audio_seconds':2.6,'chunk_overlap_seconds':0,'audio_seconds':len(pcm)/16000,
                    'threads':4,'batch_size':12,'chunks':[{'offset':0,'duration':len(pcm)/16000,
                    'segments':segments}]}
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
    """Decode only selected windows from the original single audio source."""
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
            if len(part)<16000*2:
                raise ValueError('声纹音频样本太短，请检查素材或轨道。')
            parts.append(part)
        finally:
            if process.poll() is None:
                stop_process_tree(process)
    return parts


def apply_reviewed(project, report):
    """Prepare one undoable project update after the user reviews proposals."""
    import copy
    from dataclasses import asdict
    from ..projects.speaker_names import ensure_speaker_names
    from ..projects.studio_project import SubtitleProject
    if (report.get('version') != VERSION or report.get('cue_signature') != cue_signature(project.cues)):
        raise ValueError('字幕或说话人已变化，请重新分析声纹。')
    state = project.generation_metadata.get('speaker_recovery') or {}
    if state.get('confirmed_by'):
        raise ValueError('已有人工确认的身份，请使用现有说话人管理操作，避免覆盖。')
    groups = report.get('groups') or []
    labels = [label for group in groups for label in group]
    roles = state.get('roles') or {}
    if (len(labels) != len(set(labels)) or any(roles.get(label) != 'unconfirmed' for label in labels)
            or any(not _SCOPED.fullmatch(label) for label in labels)):
        raise ValueError('说话人用途已变化，请重新分析。')
    entries = project.generation_metadata.get('speaker_names', {}).get('entries', {})
    identities = {speaker.id:speaker for speaker in project.speakers}
    for label in labels:
        speaker = identities.get(label)
        entry = entries.get(label) or {}
        if (speaker is None or speaker.is_host or speaker.hidden or speaker.color
                or (entry and ((entry.get('automatic') is False and speaker.name not in ('',label))
                               or entry.get('name') != speaker.name))
                or (not entry and speaker.name not in ('',label))):
            raise ValueError('候选包含人工设置的说话人，请使用手动合并。')
    allowed = {tuple(sorted(item.get('labels') or ())) for item in report.get('pair_scores') or ()
               if item.get('median',0) >= MIN_MEDIAN and item.get('lower_quartile',0) >= MIN_LOWER_QUARTILE}
    intervals = defaultdict(list)
    for cue in project.cues:
        intervals[cue.speaker_id].append((cue.start_ms/1000,cue.end_ms/1000))
    for group in groups:
        if len(group)<2 or any(tuple(sorted((a,b))) not in allowed
                               for i,a in enumerate(group) for b in group[i+1:]):
            raise ValueError('声纹候选不完整或存在冲突，未应用。')
        for i,a in enumerate(group):
            for b in group[i+1:]:
                if _SCOPED.fullmatch(a).group(1) == _SCOPED.fullmatch(b).group(1):
                    raise ValueError('同一请求中的不同标签不能直接合并。')
                if _overlapping(intervals[a],intervals[b]):
                    raise ValueError('重叠发言存在身份冲突，未应用。')
    if not groups:
        raise ValueError('没有可应用的声纹候选。')
    result = SubtitleProject.from_dict(project.to_dict())
    state = copy.deepcopy(state)
    saved = state.setdefault('cue_cache', {})
    display = state.setdefault('display_labels', {})
    organization = result.generation_metadata.setdefault('speaker_organization', {})
    identities = organization.setdefault('original_speakers', {})
    sources = {}
    for group in groups:
        target = group[0]
        for label in group[1:]:
            sources[label] = target
            state['roles'][label] = 'merge:' + target
    for speaker in result.speakers:
        if speaker.id in sources:
            identities[speaker.id] = asdict(speaker)
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
    result.studio_state['speaker_track_order'] = order
    display.update(ensure_speaker_names(result))
    pending = [label for label,role in state['roles'].items() if role == 'unconfirmed']
    state.update(needs_confirmation=bool(pending), confirmed_by='user', unconfirmed_candidates=pending)
    state['voiceprint_review'] = {
        key:copy.deepcopy(report.get(key)) for key in
        ('version','groups','cue_signature','sample_counts','sample_intervals','pair_scores','conflicts','meaning')}
    state['voiceprint_review']['reviewed_by'] = 'user'
    result.generation_metadata['speaker_recovery'] = state
    result.validate()
    return result
