"""Read-only recovery from saved projects; no player, recognition or user settings."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .srt_codec import normalize_srt_text
from .export_consistency import require_consistent_view
from .studio_subtitle_export import (
    SubtitleExportArtifact, SubtitleVerificationError, _atomic_text_write, _publish_new,
    _speaker_filename, compile_srt, verify_subtitle_artifact,
)
from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject


BUILD_ID = "subtitle-rescue-20261020.2"


class RescueInputError(ValueError):
    pass


class RescueExportError(RuntimeError):
    def __init__(self, directory, published, pending, cause):
        self.directory, self.published, self.pending, self.cause = directory, published, pending, cause
        super().__init__(f"救援未完整完成：{cause}\n已写入：{'、'.join(published) or '无'}"
                         f"\n未写入：{'、'.join(pending) or '无'}\n本次目录：{directory}")


def _strict_cues(rows):
    if not isinstance(rows, list):
        raise RescueInputError("缺少完整 cues 列表；不能从任务摘要恢复已编辑字幕。")
    seen = set()
    for index, cue in enumerate(rows, 1):
        if not isinstance(cue, dict) or not all(key in cue for key in ("id", "text", "start_ms", "end_ms")):
            raise RescueInputError(f"第 {index} 条缺少 ID、文字或毫秒时间；停止以免丢失字幕。")
        if not isinstance(cue["text"], str) or not isinstance(cue["id"], str) or not cue["id"].strip():
            raise RescueInputError(f"第 {index} 条的文字／ID 无效。")
        if cue["id"] in seen:
            raise RescueInputError(f"第 {index} 条的 cue ID 重复：{cue['id']}")
        seen.add(cue["id"])
        start, end = cue["start_ms"], cue["end_ms"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise RescueInputError(f"第 {index} 条（{cue['id']}）时间无效；不会猜测或改写时间戳。")


def read_rescue_input(source: Path):
    """Only schema-bearing projects or our explicitly timeline-domain export JSON."""
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise RescueInputError("文件不是可读取的 UTF-8 工程／JSON。请保留原文件并选择保存的工程或自动保存副本。") from exc
    if not isinstance(payload, dict):
        raise RescueInputError("需要完整工程对象；不接受时间域不明的裸字幕数组。")
    if payload.get("kind") == "2byteasr-subtitle-export" and payload.get("schema_version") == 1:
        _strict_cues(payload.get("cues"))
        cues = [StudioCue(row["id"], row["start_ms"], row["end_ms"],
                          row.get("original_text", row["text"]), row.get("speaker_id") or "S00")
                for row in payload["cues"]]
        if any(not isinstance(c.text, str) for c in cues):
            raise RescueInputError("导出 JSON 的 original_text 无效。")
        project = SubtitleProject(StudioMedia("", duration_ms=max((c.end_ms for c in cues), default=0)), cues=cues)
        project.speakers = [StudioSpeaker(s, s) for s in dict.fromkeys(c.speaker_id for c in cues)]
        project.render_settings["_cue_domain"] = "timeline"
        project.validate()
        return project, raw, "export_json_timeline", ["JSON 只代表当时导出的稿件；之后未保存在此文件的修改无法恢复。"]
    if "media" not in payload or "cues" not in payload or "project_id" not in payload:
        raise RescueInputError("这是任务记录或非完整工程，缺少已编辑字幕及时间轴；请选择 .2byteproj 工程、自动保存副本或字幕导出 JSON。")
    _strict_cues(payload["cues"])
    # Use exactly the same autosave integrity gate as load_project, without
    # a second file read or any recovery/save side effects.
    from ..projects.media_graph_integrity import validate_autosave_integrity, graph_counts
    integrity = validate_autosave_integrity(payload)
    project = SubtitleProject.from_dict(copy.deepcopy(payload))
    if integrity is not None:
        counts = graph_counts({key: [asdict(x) for x in getattr(project, key)]
                               for key in ("media_pool", "video_tracks", "audio_tracks", "av_track_groups")})
        if counts != integrity["counts"]:
            raise RescueInputError("自动保存媒体轨道校验失败；停止以免导出错误时间轴。")
    if len(project.cues) != len(payload["cues"]):
        raise RescueInputError("载入前后字幕条数不同；停止以免丢失字幕。")
    saved = {cue["id"]: cue for cue in payload["cues"]}
    if any(cue.id not in saved or (cue.start_ms, cue.end_ms, cue.text) !=
           (saved[cue.id]["start_ms"], saved[cue.id]["end_ms"], saved[cue.id]["text"]) for cue in project.cues):
        raise RescueInputError("载入前后字幕编号、文字或句级时间不同；停止以免改写保存内容。")
    domain = ("project_timeline" if project.render_settings.get("_cue_domain") == "timeline" else
              "captured_timeline" if project.generation_metadata.get("timeline_recognition") else "source_projected_to_timeline")
    return project, raw, domain, []


def rescue_subtitles(source: str | Path, output_parent: str | Path) -> Path:
    """Export all saved speakers (even hidden/empty), always into a fresh folder.

    Do not use original_text, ASR evidence or archived captions for a project's
    manuscript. project.cues is the latest saved edit; projected_cues is the
    existing, authoritative edit-clock mapping. No punctuation/language styling.
    """
    from ..timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    from .export_preferences import output_basename
    source = Path(source).resolve()
    project, raw, domain, notes = read_rescue_input(source)
    original_cues = copy.deepcopy(project.cues)
    view = sorted(copy.deepcopy(projected_cues(project, domain="timeline")),
                  key=lambda c: (c.start_ms, c.end_ms, c.id))
    _strict_cues([asdict(c) for c in view])
    # Recheck original saved owners, before loader normalization can hide a
    # malformed speaker/reference. Use the same selected source scope as the
    # mapped view; an unrelated source tail is preserved in input-copy.json.
    payload = json.loads(raw.decode("utf-8-sig"))
    saved = {cue["id"]: cue for cue in payload["cues"]}
    selected = {cue.id if cue.id in saved else source_cue_id_of(cue.id) for cue in view}
    require_consistent_view(payload, [cue for cue in payload["cues"] if cue["id"] in selected])
    consistency = require_consistent_view(project, view)
    notes.extend(issue.reason for issue in consistency.warnings)
    if project.cues != original_cues:
        raise RescueInputError("时间轴映射意外改变来源字幕；停止导出。")
    mapped_ids = {c.id if domain in {"project_timeline", "export_json_timeline"} else source_cue_id_of(c.id) for c in view}
    outside = [c.id for c in original_cues if c.id not in mapped_ids]
    if outside:
        notes.append(f"{len(outside)} 条来源字幕不在当前剪辑序列；未伪造时间放入 SRT，原文与原时间完整保存在 input-copy.json。")
    hidden = sorted(project.hidden_speaker_ids())
    if hidden:
        notes.append("救援包含被隐藏的说话人：" + "、".join(hidden))
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    stem = output_basename(source.stem) or "subtitles"
    folder_name = f"{stem}_字幕救援_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    for number in range(1, 10000):
        target = parent / (folder_name if number == 1 else f"{folder_name} ({number})")
        try:
            target.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("无法创建新的救援目录。")
    scopes = [("", view, f"{stem}_全部.srt")]
    speaker_ids = list(dict.fromkeys([s.id for s in project.speakers] + [c.speaker_id for c in view]))
    used = {scopes[0][2].casefold()}
    for speaker in speaker_ids:
        label = _speaker_filename(speaker)
        name, suffix = f"{stem}_{label}.srt", 2
        while name.casefold() in used:
            name = f"{stem}_{label}_{suffix}.srt"
            suffix += 1
        used.add(name.casefold())
        scopes.append((speaker, [c for c in view if c.speaker_id == speaker], name))
    manifest = {"build_id": BUILD_ID, "status": "verified", "input_name": source.name,
                "input_sha256": hashlib.sha256(raw).hexdigest(), "input_time_domain": domain,
                "output_time_domain": "current_timeline_ms", "source_cue_count": len(original_cues),
                "timeline_cue_count": len(view), "outside_current_timeline_ids": outside,
                "hidden_speakers_included": hidden, "notes": notes,
                "normalization": "CRLF / CR -> LF only; spaces and blank lines preserved",
                "consistency": consistency.to_dict(),
                "privacy": "本目录含字幕原文和工程副本，仅在本机；请自行决定是否提供。",
                "files": []}
    published: list[str] = []
    planned = [s[2] for s in scopes] + ["input-copy.json", "rescue-manifest.json"]
    try:
        with tempfile.TemporaryDirectory(prefix=".verify-", dir=target, ignore_cleanup_errors=True) as stage_name:
            stage = Path(stage_name)
            for speaker, cues, name in scopes:
                path = stage / name
                _atomic_text_write(path, compile_srt(cues))
                expected = copy.copy(project)
                expected.cues = cues
                check = verify_subtitle_artifact(SubtitleExportArtifact(path, "srt", speaker, len(cues)), expected)
                if not check.valid:
                    raise SubtitleVerificationError(target / name, speaker, check)
                result = asdict(check)
                result["path"] = name
                manifest["files"].append({"name": name, "speaker_id": speaker,
                    "cue_count": len(cues), "empty_track": not cues,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "verification": result,
                    "cues": [{"subtitle_number": index, "cue_id": c.id, "start_ms": c.start_ms,
                              "end_ms": c.end_ms, "speaker_id": c.speaker_id,
                              "text": c.text, "srt_text": normalize_srt_text(c.text)} for index, c in enumerate(cues, 1)]})
            (stage / "input-copy.json").write_bytes(raw)
            _atomic_text_write(stage / "rescue-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for name in planned:
                _publish_new(stage / name, target / name)
                published.append(name)
    except Exception as exc:
        pending = [name for name in planned if name not in published]
        failure = {"build_id": BUILD_ID, "status": "failed", "published": published, "not_published": pending,
                   "error": str(exc), "details": exc.details() if isinstance(exc, SubtitleVerificationError) else str(exc)}
        try:
            _atomic_text_write(target / "rescue-failure.json", json.dumps(failure, ensure_ascii=False, indent=2))
        except OSError:
            pass  # The raised receipt still lists every file if the disk is full.
        raise RescueExportError(target, published, pending, exc) from exc
    return target
