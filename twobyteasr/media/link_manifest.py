"""Portable download receipts and bounded, same-directory subtitle discovery."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

from .link_catalog import digest
from .link_reconstruction import reconstruct
from .link_subtitles import Caption, PARSER_VERSION, ParsedSubtitles, parse_subtitles, srt_bytes, subtitle_format, words_vtt_bytes
from ..storage.atomic_files import write_text_atomic

MANIFEST_NAME = "download.2byte-download.json"
MANIFEST_VERSION = 1


def atomic_json(path: Path, data) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def resolve_relative(root: Path, value: str) -> Path:
    relative = Path(value)
    result = (root / relative).resolve()
    if relative.is_absolute() or not result.is_relative_to(root.resolve()):
        raise ValueError("下载清单包含目录外的路径。")
    return result


def file_receipt(root: Path, path: Path) -> dict:
    path = path.resolve()
    return dict(path=path.relative_to(root.resolve()).as_posix(),
                bytes=path.stat().st_size, sha256=sha256(path))


def preserve_subtitle(root: Path, track: dict, raw: bytes, expected_format: str, *,
                      mode="smart", keep_sound=True) -> dict:
    """Content-addressed originals are immutable, including failed parse inputs."""
    from .link_catalog import public_track
    content_hash = hashlib.sha256(raw).hexdigest()
    raw_dir = root / "originals"
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Detect the actual representation BEFORE giving the preserved file an extension.
    text = raw[:256].decode("utf-8-sig", errors="replace").lstrip()
    actual = subtitle_format(text)
    if actual == "srt" and "-->" not in raw[:2048].decode("utf-8-sig", errors="replace"):
        actual = "bin"
    name = f"{track['track_id']}.{content_hash[:16]}"
    original = raw_dir / f"{name}.{actual}"
    if not original.exists():
        with original.open("xb") as stream:
            stream.write(raw)
    elif sha256(original) != content_hash:
        raise ValueError("原始字幕校验不一致；未覆盖已有文件。")
    parsed = parse_subtitles(raw, expected_format=expected_format, source=track.get("source", "unknown"))
    parsed = reconstruct(parsed, language=track.get("language", ""), source=track.get("source", ""),
                         mode="smart" if mode == "ai" else mode, keep_sound=keep_sound)
    variant = f"{name}.v{PARSER_VERSION}.{mode}{'' if keep_sound else '-speech'}"
    normalized = root / "subtitles" / f"{variant}.json"
    srt = normalized.with_name(f"{variant}.srt")
    words = normalized.with_name(f"{variant}.words.vtt")
    atomic_json(normalized, parsed.to_dict())
    srt.write_bytes(srt_bytes(parsed))
    words.write_bytes(words_vtt_bytes(parsed))
    # Real conversion, with a second parser check; never relabel VTT as SRT.
    if parse_subtitles(srt.read_bytes()).format != "srt":
        raise ValueError("SRT 转换验证失败。")
    return dict(track=public_track(track), actual_format=parsed.format,
                original=file_receipt(root, original), normalized=file_receipt(root, normalized),
                srt=file_receipt(root, srt), words_vtt=file_receipt(root, words), tidy=parsed.tidy,
                parser_version=PARSER_VERSION, processing_mode=mode, keep_sound=keep_sound,
                timing_basis="media_elapsed_ms", input_events=parsed.input_events,
                cue_count=len(parsed.captions), display_repeats=parsed.display_repeats,
                warnings=parsed.warnings)


def read_normalized(path):
    data = json.loads(path.read_bytes())
    data["captions"] = [Caption(**row) for row in data["captions"]]
    return ParsedSubtitles(**data)


def reprocess_subtitles(path, task_id, mode, *, cancel=None, notify=None):
    """Rebuild derived files using previously verified originals without a network request."""
    from .link_reconstruction import MODES
    from .link_tools import check_cancel

    root = path.parent
    data = load_manifest(path, verify_derived=False)
    if mode not in MODES or data["task_id"] != task_id or not data.get("subtitles"):
        raise ValueError("没有可重新处理的字幕原稿。")
    updated = []
    primary = data.get("primary_track_id") or data["subtitles"][0]["track"]["track_id"]
    for receipt in data["subtitles"]:
        check_cancel(cancel)
        original = resolve_relative(root, receipt["original"]["path"])
        if notify:
            notify(dict(stage="organizing"))
        replacement = preserve_subtitle(root, receipt["track"], original.read_bytes(),
            receipt["actual_format"], mode=mode, keep_sound=receipt.get("keep_sound", True))
        if mode == "ai" and receipt["track"]["track_id"] == primary:
            if notify:
                notify(dict(stage="ai_refining"))
            refine_saved_subtitle(root, replacement, cancel=cancel)
        updated.append(replacement)
    check_cancel(cancel)
    data["subtitles"] = updated
    atomic_json(path, data)
    return path


def refine_saved_subtitle(root, receipt, *, cancel=None, progress=None):
    from .link_ai import refine_downloaded
    from ..storage.settings import load_runtime_settings
    loaded = load_runtime_settings()
    settings = loaded[0] if isinstance(loaded, tuple) else loaded
    group = settings.get("models", {}).get("group", {})
    model = {key: group.get(key) for key in ("service", "model", "thinking", "temperature")}
    identity = digest([receipt["original"]["sha256"], receipt["parser_version"], receipt["keep_sound"], model])[:20]
    previous = receipt.get("ai", {})
    if previous.get("identity") == identity and previous.get("status") == "completed":
        return
    fallback = receipt.get("smart_normalized") or receipt["normalized"]
    parsed = read_normalized(resolve_relative(root, fallback["path"]))
    final, state = refine_downloaded(parsed, receipt["track"].get("language", ""), settings,
                                   cancel=cancel, on_progress=progress)
    receipt["ai"] = dict(state, identity=identity)
    receipt.setdefault("smart_normalized", fallback)
    receipt.setdefault("smart_srt", receipt["srt"])
    receipt.setdefault("smart_words_vtt", receipt["words_vtt"])
    if not state["applied"]:
        receipt.update(normalized=fallback, srt=receipt["smart_srt"], words_vtt=receipt["smart_words_vtt"],
                       cue_count=len(parsed.captions))
        return
    source = resolve_relative(root, fallback["path"])
    target = source.with_name(source.stem + f".{identity}.json")
    final.tidy = dict(final.tidy, mode="ai", **state)
    atomic_json(target, final.to_dict())
    target_srt = target.with_suffix(".srt")
    target_vtt = target.with_suffix(".words.vtt")
    target_srt.write_bytes(srt_bytes(final))
    target_vtt.write_bytes(words_vtt_bytes(final))
    receipt.update(normalized=file_receipt(root, target), srt=file_receipt(root, target_srt),
                   words_vtt=file_receipt(root, target_vtt), cue_count=len(final.captions))


def load_manifest(path: Path, *, verify_media=False, verify_derived=True) -> dict:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("下载清单过大。")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("version") != MANIFEST_VERSION or not data.get("task_id") or not data.get("video_id"):
        raise ValueError("下载清单版本或身份无效。")
    media = data.get("media")
    if media:
        target = resolve_relative(path.parent, media["path"])
        if not target.is_file() or target.stat().st_size != media["bytes"]:
            raise ValueError("下载清单对应的视频已丢失或被替换。")
        if verify_media and sha256(target) != media["sha256"]:
            raise ValueError("视频校验失败，不能自动绑定字幕。")
    ids = set()
    for sub in data.get("subtitles", []):
        identity = sub["track"]["track_id"]
        if identity in ids or sub["track"]["video_id"] != data["video_id"]:
            raise ValueError("字幕身份重复或不属于该视频。")
        ids.add(identity)
        for kind in (("original", "normalized") if verify_derived else ("original",)):
            receipt = sub[kind]
            target = resolve_relative(path.parent, receipt["path"])
            if (not target.is_file() or target.stat().st_size != receipt["bytes"]
                    or sha256(target) != receipt["sha256"]):
                raise ValueError("配套字幕已被修改，需重新选择；当前工程未改变。")
    return data


def load_bundle(path: Path, *, verify_media=False) -> dict:
    data = load_manifest(path, verify_media=verify_media)
    captions = {}
    for sub in data.get("subtitles", []):
        if sub.get("parser_version") == PARSER_VERSION and sub.get("processing_mode"):
            normalized = resolve_relative(path.parent, sub["normalized"]["path"])
            captions[sub["track"]["track_id"]] = json.loads(normalized.read_bytes())
            continue
        # Parse immutable original again using current parser; normalized file is a receipt.
        original = resolve_relative(path.parent, sub["original"]["path"])
        parsed = parse_subtitles(original.read_bytes(), expected_format=sub["actual_format"],
                                 source=sub["track"].get("source", "unknown"))
        # The primary keeps YouTube's rows when a translation is paired with it,
        # so the two still line up row by row (2026-10-26).
        paired = (sub["track"]["track_id"] == data.get("primary_track_id")
                  and bool(data.get("translation_track_id")))
        from .link_tidy import tidy_captions
        captions[sub["track"]["track_id"]] = tidy_captions(
            parsed, language=sub["track"].get("language", ""), source=sub["track"].get("source", ""),
            regroup=not paired).to_dict()
    return dict(manifest=data, manifest_path=str(path.resolve()), captions=captions,
                media_path=str(resolve_relative(path.parent, data["media"]["path"])) if data.get("media") else "")


def discover_companions(media: Path) -> dict:
    """Run in ingest's worker. Exact receipts first, bounded names second."""
    media = media.resolve()
    result = dict(automatic="", candidates=[], error="")
    files = []
    # Avoid a recursive search or enumerating a user's entire large directory.
    for i, entry in enumerate(media.parent.iterdir()):
        if i >= 2048:
            result["error"] = "同目录文件过多，请从链接下载窗口选择任务清单。"
            break
        if entry.is_file():
            files.append(entry)
    manifests = [p for p in files if p.name.endswith(".2byte-download.json")]
    for manifest in manifests[:64]:
        try:
            data = load_manifest(manifest)
            if data.get("media") and resolve_relative(manifest.parent, data["media"]["path"]) == media:
                # Hash only exact path candidates, not all downloads.
                if sha256(media) == data["media"]["sha256"]:
                    result["candidates"].append(str(manifest))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["error"] = str(exc)
    if result["candidates"]:
        if len(result["candidates"]) == 1:
            result["automatic"] = result["candidates"][0]
        return result
    # Same stem (language/source suffix allowed), no fuzzy title or duration identity.
    pattern = re.compile(re.escape(media.stem) + r"(?:[.](?:[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*|manual|auto|orig))*$", re.I)
    result["candidates"] = [str(p) for p in files if p.suffix.lower() in {".json3", ".vtt", ".srt"}
                            and pattern.fullmatch(p.stem)]
    # Unmanaged multiple representations are ambiguous, so offer one choice.
    if len(result["candidates"]) == 1:
        result["automatic"] = result["candidates"][0]
    return result


def local_subtitle_bundle(media: Path, subtitle: Path) -> dict:
    """A user's explicit sidecar selection; unknown source, no invented platform ID."""
    parsed = parse_subtitles(subtitle.read_bytes())
    identity = digest([str(media.resolve()), sha256(subtitle)])[:24]
    track = dict(track_id=identity, platform="local", video_id=identity, language="",
                 original_language="", source="unknown", raw_id="", formats=[parsed.format])
    return dict(manifest=dict(version=1, task_id="local-"+identity, platform="local",
                video_id=identity, source_url="", primary_track_id=identity, translation_track_id="",
                subtitles=[dict(track=track, actual_format=parsed.format)],
                timing_basis="media_elapsed_ms"), manifest_path=str(subtitle.resolve()),
                media_path=str(media.resolve()), captions={identity: parsed.to_dict()})


def relocate_project_downloads(project, project_path: Path) -> int:
    """Recover a moved task folder using exact saved identity + SHA, never titles.

    Only two relative locations are inspected: beside the project or its parent
    (our task/project layout). Existing valid paths and edited captions stay intact.
    """
    moved = {}
    for asset in project.media_pool:
        source = asset.video_metadata.get("link_source") or {}
        name = str(source.get("manifest_name") or "")
        expected_hash = source.get("media_sha256")
        if not name or Path(name).name != name or not expected_hash or Path(asset.canonical_source).is_file():
            continue
        candidates = []
        for parent in (project_path.resolve().parent, project_path.resolve().parent.parent):
            manifest = parent/name
            if not manifest.is_file():
                continue
            try:
                data = load_manifest(manifest, verify_media=True)
                if (data.get("platform"),data["video_id"],data["task_id"]) != (
                        source.get("platform"),source.get("video_id"),source.get("task_id")):
                    continue
                if (data.get("media") or {}).get("sha256") != expected_hash:
                    continue
                candidates.append(str(resolve_relative(parent,data["media"]["path"])))
            except (OSError,ValueError,KeyError,TypeError):
                continue
        if len(set(candidates)) == 1:
            moved[asset.canonical_source] = candidates[0]
            asset.canonical_source = candidates[0]
            asset.offline = False
            asset.relink_state = "relinked"
    if not moved:
        return 0
    from ..timeline.studio_edit_sequence import sequence_of,replace_runtime_sequence
    sequence = sequence_of(project)
    sequence.source_path = moved.get(sequence.source_path,sequence.source_path)
    for segment in sequence.segments:
        segment.source_path = moved.get(segment.source_path,segment.source_path)
    project.media.path = moved.get(project.media.path,project.media.path)
    for receipt in project.studio_state.get("caption_timeline",{}).get("instances",{}).values():
        if receipt.get("source_path") in moved:
            receipt["source_path"] = moved[receipt["source_path"]]
        for span in receipt.get("source_spans",[]):
            for item in span.get("instances",[]):
                if item.get("source_path") in moved:
                    item["source_path"] = moved[item["source_path"]]
    replace_runtime_sequence(project,sequence)
    return len(moved)
