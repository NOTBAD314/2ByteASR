"""Lossless MOSS candidate inventory and offline, user-confirmed track recovery.

This service never runs an ASR model or a provider. The original MOSS rows and
existing edited cues are retained in the project's extensible metadata.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import asdict
from pathlib import Path


def candidate_statistics(rows):
    from .speaker_organization import utterance_counts
    counts=utterance_counts(rows)
    result = []
    for label in sorted({str(row.get("speaker") or "S00") for row in rows}):
        selected = [row for row in rows if str(row.get("speaker") or "S00") == label]
        intervals = sorted((float(row["start"]), float(row["end"])) for row in selected)
        # Persistence is a review signal, never proof of a human identity.
        result.append({
            "label": label, "segments": len(selected),
            "utterances": counts.get(label,0),
            "seconds": round(sum(end - start for start, end in intervals), 3),
            "first": intervals[0][0], "last": max(end for _, end in intervals),
            "intervals": intervals,
            "sustained": counts.get(label,0)>10,
            "needs_identity_review": counts.get(label,0)<=10,
        })
    return result


def selected_display_mapping(snapshot, roles, project=None):
    """Presentation only. Raw MOSS labels and cached speaker fields never change."""
    from .speaker_names import default_names
    labels = [row['label'] for row in sorted(candidate_statistics(snapshot['raw_segments']), key=lambda row: row['first'])]
    mapping = dict(snapshot.get('display_labels', {}))
    if project is not None:
        mapping.update({s.id:s.name for s in project.speakers})
    mapping.update(default_names([label for label in labels if label not in mapping], mapping.values(), preserve_canonical=False))
    snapshot['display_labels'] = mapping
    return {label:mapping[label] for label in labels if roles.get(label)=='main'}


def recovery_preview(project, snapshot, roles):
    """Exact local cue count, without constructing or mutating a project."""
    saved = snapshot.get("cue_cache", {})
    counts = {}
    for label, role in roles.items():
        target = ('GAME_BACKGROUND' if role == 'game' or (role == 'unconfirmed' and not anonymous_snapshot(snapshot)) else
                  role[6:] if isinstance(role,str) and role.startswith('merge:') else label)
        if role not in {'main','game','unconfirmed'} and not (target != label and roles.get(target)=='main'):
            continue
        current = [cue for cue in project.cues if cue.speaker_id == label]
        if saved.get(label):
            amount = len(saved[label])
        elif current:
            amount = len(current)
        else:
            amount = 0 if snapshot.get('allow_raw_recovery') is False else sum(min(len(str(row.get("text") or "")), max(1, math.ceil(
                (round(row["end"] * 1000) - round(row["start"] * 1000)) / 5000)))
                for row in snapshot["raw_segments"] if str(row.get("speaker") or "S00") == label
                and str(row.get("text") or "").strip())
        counts[target] = counts.get(target,0)+amount
    return counts


def anonymous_snapshot(snapshot):
    return snapshot.get('source') in {'nemotron','native','filetrans'} or snapshot.get('processing',{}).get('mode') in {'nemotron','native','filetrans'} or any(
        row.get('speaker_evidence',{}).get('source')=='nemotron' for row in snapshot.get('raw_segments',[]))


def candidate_snapshot(rows, retained=(), expected=0, *, source=None):
    raw = copy.deepcopy(list(rows))
    for row in raw:
        start, end = float(row["start"]), float(row["end"])
        if not math.isfinite(start + end) or start < 0 or end <= start:
            raise ValueError("MOSS 候选时间区间无效")
    labels = {item["label"] for item in candidate_statistics(raw)}
    retained = set(retained) & labels
    from .speaker_organization import utterance_counts
    counts=utterance_counts(raw)
    sustained = {item["label"] for item in candidate_statistics(raw) if item["sustained"]}
    pending = len(labels)>1 or bool(sustained - retained) or (expected > 0 and len(retained) != expected)
    anonymous = source in {'moss','nemotron','native','filetrans'} or any(
        row.get('speaker_evidence',{}).get('source')=='nemotron' for row in raw)
    return {
        "version": 1, "raw_segments": raw, "source": source or 'moss',
        "roles": {label:('unconfirmed' if anonymous else 'main' if counts.get(label,0)>10 else 'game') for label in labels},
        "reasons": {item['label']:'语音样本不足，身份待复核；原文保留可恢复'
                    for item in candidate_statistics(raw) if len(labels)>1 and item['needs_identity_review']},
        "auto_policy": "background-utterance-v2", "utterance_counts":counts, "main_threshold":10,
        "expected_speakers": int(expected), "needs_confirmation": pending or anonymous,
        "confirmed_by": "", "retained_at_recognition": sorted(retained),
        "timing_owner": "MOSS_DEGRADED", "cue_cache": {},
    }


def load_candidate_snapshot(project, cache_directory=None):
    """Read old project evidence through its report; never write source caches."""
    existing = project.generation_metadata.get("speaker_recovery")
    if isinstance(existing, dict) and existing.get("raw_segments"):
        state = copy.deepcopy(existing)
        if not state.get('confirmed_by') and state.get('auto_policy')=='fragment-review-v1':
            stats = candidate_statistics(state['raw_segments'])
            for item in stats:
                if len(stats)>1 and item['needs_identity_review']:
                    state['roles'][item['label']]='ignore'
                    state.setdefault('reasons',{})[item['label']]='语音样本不足，身份待复核；原文保留可恢复'
        return state
    report = {}
    if project.report_path and Path(project.report_path).is_file():
        report = json.loads(Path(project.report_path).read_text(encoding="utf-8-sig"))
    directory = cache_directory or report.get("cache", {}).get("directory")
    if not directory:
        raise ValueError("工程未保存原始 MOSS 候选，且任务报告没有缓存路径。请选择本素材的 MOSS 缓存目录。")
    source = Path(directory) / "moss.json"
    blob = source.read_bytes()
    payload = json.loads(blob.decode("utf-8-sig"))
    identity = payload.get("identity", {})
    source_path = os.path.normcase(os.path.abspath(str(identity.get("path") or "")))
    media_path = os.path.normcase(os.path.abspath(project.media.path))
    if source_path != media_path:
        raise ValueError("MOSS 缓存不属于当前媒体，未应用。")
    media = Path(project.media.path)
    if media.is_file():
        stat = media.stat()
        if identity.get("size") != stat.st_size or identity.get("mtime_ns") != stat.st_mtime_ns:
            raise ValueError("媒体已变化，MOSS 缓存身份不匹配，未应用。")
    rows = payload.get("data", {}).get("segments", [])
    if not rows:
        raise ValueError("缓存中没有 MOSS 段。")
    expected = report.get("settings", {}).get("content_profile", {}).get("expected_speakers", 0)
    snapshot = candidate_snapshot(rows, {cue.speaker_id for cue in project.cues}, int(expected or 0))
    snapshot.update(source_path=str(source), source_sha256=hashlib.sha256(blob).hexdigest())
    vad_path=Path(directory)/'firered_vad.json'
    if vad_path.is_file():
        try:
            vad=json.loads(vad_path.read_text(encoding='utf-8-sig'))
            if vad.get('identity')==identity and isinstance(vad.get('data'),list):
                snapshot['vad_intervals']=copy.deepcopy(vad['data'])
        except (OSError,ValueError):
            pass  # VAD is optional evidence, never a reason to reject a manual label.
    return snapshot


def apply_automatic_candidate_policy(project):
    """Only on newly generated projects; archive exact final cues before hiding."""
    state=project.generation_metadata.get('speaker_recovery',{})
    if state.get('confirmed_by') or state.get('auto_policy') != 'fragment-review-v1': return
    saved=state.setdefault('cue_cache',{})
    for label in {cue.speaker_id for cue in project.cues}:
        saved[label]=[asdict(cue) for cue in project.cues if cue.speaker_id==label]
    ignored={key for key,value in state.get('roles',{}).items() if value=='ignore'}
    state['ignored_cue_count']=sum(c.speaker_id in ignored for c in project.cues)
    project.cues=[c for c in project.cues if c.speaker_id not in ignored]
    active={c.speaker_id for c in project.cues}
    project.speakers=[s for s in project.speakers if s.id in active]


def representative_interval(snapshot, label):
    rows = [row for row in snapshot["raw_segments"] if str(row.get("speaker") or "S00") == label]
    if not rows:
        raise ValueError("该标签没有原始语音段。")
    # Prefer a long clean turn over a turn overlapped by another label.
    def score(row):
        overlap = sum(max(0, min(row["end"], other["end"]) - max(row["start"], other["start"]))
                      for other in snapshot["raw_segments"] if other.get("speaker") != label)
        return (row["end"] - row["start"] - overlap, row["end"] - row["start"])
    row = max(rows, key=score)
    start = max(0, round(row["start"] * 1000) - 150)
    duration = min(4000, max(2000, round((row["end"] - row["start"]) * 1000) + 300))
    return start, start + duration


def rebuild_selected_speakers(project, snapshot, roles):
    """Prepare an atomic update of the current project; edited cues are reused.

    New labels use MOSS's existing natural sentence boundaries, with a local
    proportional split only above five seconds. No speculative text correction.
    Every newly restored cue remains explicitly pending human timing/text review.
    """
    from .studio_project import StudioCue, StudioSpeaker, SubtitleProject

    state = copy.deepcopy(snapshot)
    # Revalidate persisted evidence too: manual authority cannot recover corrupt data.
    candidate_snapshot(state["raw_segments"])
    labels = {item["label"] for item in candidate_statistics(state["raw_segments"])}
    def merge_target(role):
        return role[6:] if isinstance(role,str) and role.startswith('merge:') else ''
    if set(roles) != labels or any(role not in {"main", "game", "ignore", "unconfirmed"}
            and not (merge_target(role) in labels and roles[merge_target(role)] == 'main') for role in roles.values()):
        raise ValueError("请为全部原始标签选择有效用途。")
    selected = {label for label, role in roles.items() if role == "main"}
    anonymous=anonymous_snapshot(state)
    pending={label for label,role in roles.items() if role=='unconfirmed'} if anonymous else set()
    background = {label for label,role in roles.items() if role=='game' or (role=='unconfirmed' and not anonymous)}
    restored = selected | background | pending | {label for label, role in roles.items() if merge_target(role)}
    if not restored:
        raise ValueError("至少保留一个主要或背景标签。")
    unresolved = [item["label"] for item in candidate_statistics(state["raw_segments"])
                  if roles[item["label"]] == "unconfirmed"]
    # An explicit label selection is final authority, including when an unrelated
    # candidate or the old expected-count hint is still unresolved. Never run the
    # Stage 5 span/count, host_priority, FireRed or confidence gates on this path.
    result = SubtitleProject.from_dict(project.to_dict())
    saved = state.setdefault("cue_cache", {})
    current_cues = {cue.id:cue for cue in project.cues}
    known_ids = {row['id'] for rows in saved.values() for row in rows}
    for label, rows in saved.items():
        saved[label] = [dict(asdict(current_cues[row['id']]),speaker_id=label)
                        if row['id'] in current_cues else row for row in rows]
    for cue in project.cues:
        if cue.id not in known_ids:
            saved.setdefault(cue.speaker_id,[]).append(asdict(cue))
    cues = []
    current = {speaker.id: speaker for speaker in project.speakers}
    added = []
    used_ids = {cue.id for cue in project.cues}
    for label in sorted(restored):
        if saved.get(label):
            cues.extend(StudioCue(**copy.deepcopy(row)) for row in saved[label])
            continue
        added.append(label)
        if state.get('allow_raw_recovery') is False:
            raise ValueError(f'{label} 没有最终字幕缓存；未从 MOSS 原文覆盖 API 文字。')
        for index, row in enumerate(state["raw_segments"]):
            if str(row.get("speaker") or "S00") != label or not str(row.get("text") or "").strip():
                continue
            text = str(row["text"])
            start, end = round(row["start"] * 1000), round(row["end"] * 1000)
            parts = min(len(text), max(1, math.ceil((end-start)/5000)))
            for part in range(parts):
                lo, hi = len(text)*part//parts, len(text)*(part+1)//parts
                cue_id = f"moss-{label}-{index}-{part}"
                while cue_id in used_ids:
                    cue_id += "-r"
                used_ids.add(cue_id)
                a, b = start+(end-start)*lo//len(text), start+(end-start)*hi//len(text)
                ref = f"moss-raw:{index}:{part}"
                result.asr_evidence[ref] = {
                    "speaker_id": label, "raw_moss_label": label, "text": text[lo:hi], "moss_text": text,
                    "start_ms": a, "end_ms": b, "moss_start": row["start"], "moss_end": row["end"],
                    "acoustic_start_ms": start, "acoustic_end_ms": end,
                    "display_split_estimated": parts > 1,
                    "confidence": 0.5, "final_timing_owner": "MOSS_DEGRADED",
                    "review_required": True, "source": "user-selected MOSS cache",
                }
                cues.append(StudioCue(cue_id, a, b, text[lo:hi], speaker_id=label,
                                      evidence_refs=[ref], style_id=result.styles[0].id))
        saved[label] = [asdict(cue) for cue in cues if cue.speaker_id == label]
    for cue in cues:
        cue.speaker_id = merge_target(roles.get(cue.speaker_id,'')) or cue.speaker_id
    missing = selected - {cue.speaker_id for cue in cues}
    if missing:
        raise ValueError("已选标签没有可恢复的有效原文：" + "、".join(sorted(missing)))
    result.cues = sorted({cue.id:cue for cue in cues}.values(), key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    result.speakers = [copy.deepcopy(current.get(label)) or StudioSpeaker(label, name=label, style_id=result.styles[0].id)
                       for label in sorted(selected|background|pending)]
    for speaker in result.speakers:
        speaker.hidden = False
        speaker.is_host = speaker.id in selected if anonymous else speaker.is_host or speaker.id in selected
    from .speaker_names import ensure_speaker_names
    mapping = ensure_speaker_names(result)
    for cue in result.cues:
        for ref in cue.evidence_refs:
            if isinstance(result.asr_evidence.get(ref), dict):
                result.asr_evidence[ref].setdefault("raw_moss_label", cue.speaker_id)
    state.update(roles=dict(roles), needs_confirmation=bool(pending), confirmed_by="user",
                 unconfirmed_candidates=unresolved, display_labels=mapping,
                 newly_restored=added,
                 ignored_cue_count=sum(len(rows) for label,rows in saved.items() if roles.get(label)=='ignore'),
                 merged_cue_count=sum(len(rows) for label,rows in saved.items() if merge_target(roles.get(label,''))),
                 reconstruction="exact cached cues; missing legacy MOSS cues use natural boundaries; no model requests")
    result.generation_metadata["speaker_recovery"] = state
    result.studio_state["speaker_track_order"] = list(mapping)
    if background:
        from .speaker_organization import organize
        result=organize(result,background,'background')
    # Identity-only decisions never alter authored text, segmentation or timing.
    result.validate()
    return result
