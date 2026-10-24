"""Task-owned media identities and exact, committed recognition references.

Recognition cache identity is independent of project identity: identical input
may reuse computation, while each job still owns its own persistent project.
All persisted fields live in the existing generation_metadata extension point.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


class RecognitionResultMismatch(ValueError):
    """A result reference no longer names the committed recognition result."""


def digest_payload(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_job_id(value):
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("识别任务 ID 无效。")
    return value


def media_identity_for_task(media_path, context=None, *, selection=None):
    """Hash each source once per queue; stat checks catch later normal writes."""
    path = Path(media_path).resolve()
    canonical = os.path.normcase(str(path))
    if selection is None and context is not None:
        # The audio stream a home-page entry recognizes (2026-10-24): each
        # picked track of one file is its own input with its own caches.
        from .audio_stream_choice import active_choice, selection as stream_selection
        selection = stream_selection(active_choice(path, context))
    selected = dict(selection or {})
    key = canonical
    cache = getattr(context, "media_identities", None)
    lock = getattr(context, "media_identity_lock", None)

    def obtain():
        stat = path.stat()
        if cache is not None and key in cache:
            prior = cache[key]
            if (int(stat.st_size), int(stat.st_mtime_ns)) != (prior["size"], prior["mtime_ns"]):
                raise RuntimeError(f"识别过程中素材已改变：{path}")
            return dict(prior)
        sha = hashlib.sha256()
        token = getattr(context, "cancellation_token", None)
        with path.open("rb") as stream:
            while True:
                if token is not None:
                    token.raise_if_cancelled()
                chunk = stream.read(4 * 1024 * 1024)
                if not chunk:
                    break
                sha.update(chunk)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"计算素材身份时文件已改变：{path}")
        identity = {"path": canonical, "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns), "sha256": sha.hexdigest()}
        if cache is not None:
            cache[key] = dict(identity)
        return identity

    if lock is not None:
        with lock:
            identity = obtain()
    else:
        identity = obtain()
    identity["selection"] = selected
    identity["fingerprint"] = digest_payload({"sha256": identity["sha256"], "selection": selected})
    return identity


def recognition_project_path(media_path, job_id, *, media_index=1):
    from ..projects.studio_project import canonical_project_path
    canonical = canonical_project_path(media_path)
    job_id = validate_job_id(job_id)
    # Full job IDs prevent basename collisions and same-second overwrites.
    directory = canonical.parent.with_name(f"{canonical.parent.name}__{job_id}_{int(media_index)}")
    return directory / canonical.name


def cue_identity(project):
    return [{"id": str(c.id), "start_ms": int(c.start_ms), "end_ms": int(c.end_ms),
             "text": c.text, "speaker_id": c.speaker_id} for c in project.cues]


def input_graph_identity(project):
    """Persistent source/geometry/mapping only; no previews or runtime metadata."""
    data = project.to_dict()
    def pick(row, fields):
        return {key: row.get(key) for key in fields if key in row}
    media = pick(data.get("media") or {}, ("path", "fingerprint", "duration_ms", "width", "height"))
    assets = []
    for asset in data.get("media_pool") or []:
        item = pick(asset, ("asset_id", "canonical_source", "fingerprint", "duration_ms"))
        for kind, fields in (("video_metadata", ("has_video", "width", "height", "fps", "timebase", "rotation", "start_time_ms", "first_pts_ms", "source_start_ms")),
                             ("audio_metadata", ("has_audio", "sample_rate", "channels", "stream_index", "audio_stream_index", "timebase", "start_time_ms", "first_pts_ms", "source_start_ms"))):
            item[kind] = pick(asset.get(kind) or {}, fields)
        assets.append(item)
    result = {"media": media, "media_pool": assets}
    for kind in ("video_tracks", "audio_tracks"):
        tracks = []
        for track in data.get(kind) or []:
            item = pick(track, ("id", "enabled", "muted", "gain_db", "z_index"))
            item["clips"] = [pick(clip, ("id", "asset_id", "enabled", "audio_enabled", "source_in_ms", "source_out_ms", "timeline_in_ms", "timeline_out_ms", "playback_rate", "stream_index", "gain_db", "linked_video_clip_id", "link_group_id", "transform")) for clip in track.get("clips") or []]
            tracks.append(item)
        result[kind] = tracks
    result["av_track_groups"] = data.get("av_track_groups") or []
    sequence = data.get("edit_sequence") or {}
    result["sequence"] = pick(sequence, ("source_path", "source_duration_ms", "empty_timeline", "segments"))
    result["media_time_mapping"] = (data.get("studio_state") or {}).get("media_time_mapping") or {}
    return result


def stamp_result(project, path, *, job_id, media_identity):
    rows = cue_identity(project)
    identity = dict(media_identity or {})
    fingerprint = str(identity.get("fingerprint") or "")
    if not fingerprint:
        raise RecognitionResultMismatch("识别结果缺少本次输入指纹，已停止工程交付。")
    base = {"path": str(Path(path).resolve()), "project_id": project.project_id,
            "job_id": validate_job_id(job_id), "media_fingerprint": fingerprint,
            "cue_count": len(rows), "cue_digest": digest_payload(rows),
            "input_graph_digest": digest_payload(input_graph_identity(project)),
            "project_manual_edit_count": len(project.edit_history),
            "project_edit_history_digest": digest_payload(project.edit_history)}
    base["result_revision"] = digest_payload(base)
    project.generation_metadata["recognition_result"] = dict(base)
    project.generation_metadata["media_identity"] = identity
    for receipt in (project.studio_state.get('caption_timeline') or {}).get('instances', {}).values():
        for span in receipt.get('source_spans', ()):
            span.update(job_id=base['job_id'], result_revision=base['result_revision'])
    return base


def committed_result_reference(project, path):
    ref = dict(project.generation_metadata.get("recognition_result") or {})
    verify_result_reference(ref, project=project, project_path=path)
    from ..diagnostics.event_log import emit
    emit("recognition.project_written",result="completed",module="recognition",project_id=project.project_id,
         task_id=ref.get("job_id"),target_path=path,result_revision=ref.get("result_revision"),cue_count=len(project.cues))
    return ref


WORKING_SCOPE = "working"


def working_reference(reference):
    """``reference`` for reopening the delivered project after delivery.

    2026-10-10 (user report): the result page kept the delivery reference and
    demanded the delivered caption digest on every later Studio open, so any
    proofreading or Studio edit made the project "not this recognition".
    A working reference proves the same identity (path, project, job, the
    committed recognition stamp, media content) as strictly, but accepts the
    captions, cuts and manual revisions the user made since delivery."""
    if not reference:
        return ""
    if isinstance(reference, str):
        try:
            reference = json.loads(reference)
        except (ValueError, TypeError):
            return reference  # verification reports the broken reference
    if not isinstance(reference, dict):
        return reference
    return json.dumps(dict(reference, scope=WORKING_SCOPE), ensure_ascii=False)


def verify_result_reference(reference, *, project=None, project_path=None):
    """Return the exact loaded project or raise; never discover another path.

    A delivery reference names the exact committed result: captions, input
    graph and manual revision counter must equal what was delivered. A
    ``working_reference`` (scope "working") names the same project after the
    user edited it: every identity check stays, content may differ."""
    if isinstance(reference, str):
        try:
            reference = json.loads(reference)
        except (ValueError, TypeError) as exc:
            raise RecognitionResultMismatch("识别结果引用无效。") from exc
    if not isinstance(reference, dict):
        raise RecognitionResultMismatch("识别结果引用缺失。")
    working = reference.get("scope") == WORKING_SCOPE
    fields = ("path", "project_id", "job_id", "result_revision", "media_fingerprint", "cue_digest")
    if any(not reference.get(k) for k in fields) or "cue_count" not in reference:
        raise RecognitionResultMismatch("识别结果引用不完整，无法确认本次工程。")
    path = Path(reference["path"]).resolve()
    revision_payload = {k: reference[k] for k in ("path", "project_id", "job_id", "media_fingerprint", "cue_count", "cue_digest")}
    # Old saved projects remain readable without migration; new deliveries pin
    # their graph and manual edit counter in the same metadata extension.
    if reference.get("input_graph_digest"):
        fields += ("input_graph_digest", "project_manual_edit_count", "project_edit_history_digest")
        revision_payload.update(input_graph_digest=reference["input_graph_digest"],
                                project_manual_edit_count=reference.get("project_manual_edit_count"),
                                project_edit_history_digest=reference.get("project_edit_history_digest"))
    if digest_payload(revision_payload) != reference["result_revision"]:
        raise RecognitionResultMismatch("识别结果版本摘要损坏。")
    if project_path is not None and path != Path(project_path).resolve():
        raise RecognitionResultMismatch("打开的工程路径与本次识别结果不一致。")
    if project is None:
        from ..projects.studio_project import load_project
        project = load_project(path)
    stored = dict(project.generation_metadata.get("recognition_result") or {})
    if any(stored.get(k) != reference.get(k) for k in (*fields, "cue_count")):
        raise RecognitionResultMismatch("工程任务身份或结果版本与本次识别不一致。")
    if project.project_id != reference["project_id"]:
        raise RecognitionResultMismatch("工程 ID 与本次识别结果不一致。")
    rows = cue_identity(project)
    if not working and (len(rows) != reference["cue_count"] or digest_payload(rows) != reference["cue_digest"]):
        raise RecognitionResultMismatch("工程字幕数量或文本时间摘要与已保存结果不一致。")
    if dict(project.generation_metadata.get("media_identity") or {}).get("fingerprint") != reference["media_fingerprint"]:
        raise RecognitionResultMismatch("工程媒体指纹与本次识别输入不一致。")
    if reference.get("input_graph_digest") and not working:
        if digest_payload(input_graph_identity(project)) != reference["input_graph_digest"]:
            raise RecognitionResultMismatch("识别提交后工程素材、裁切或时间轴映射已改变，已停止打开过期结果。")
        if (len(project.edit_history) != reference.get("project_manual_edit_count")
                or digest_payload(project.edit_history) != reference.get("project_edit_history_digest")):
            raise RecognitionResultMismatch("识别提交后工程已有人工修订，已停止打开过期结果。")
    identity = dict(project.generation_metadata.get("media_identity") or {})
    sources = project.generation_metadata.get("input_source_identities") or {identity.get("path", ""):identity}
    for source, expected in sources.items():
        if not source or not isinstance(expected, dict) or not expected.get("sha256"):
            raise RecognitionResultMismatch("工程缺少已识别媒体的内容身份。")
        try:
            stat = Path(source).stat()
        except OSError as exc:
            raise RecognitionResultMismatch("本次识别的媒体已不可用，无法确认 Studio 输入。") from exc
        if (int(stat.st_size), int(stat.st_mtime_ns)) != (expected.get("size"), expected.get("mtime_ns")):
            raise RecognitionResultMismatch("识别完成后媒体文件已改变，已停止打开过期结果。")
    return project
