"""Atomic, scoped import of a verified download into the existing media/caption model."""
from __future__ import annotations
import copy
import heapq
from dataclasses import asdict
from pathlib import Path

from PySide6.QtGui import QUndoCommand

from .studio_project import StudioCue, StudioSpeaker
from .studio_runtime_state import DirtyDomain, state_for
from .subtitle_consistency import validate_project, SubtitleConsistencyError
from ..media.link_catalog import digest, language_matches
from ..timeline.clip_time_mapper import source_to_project
from ..timeline.studio_caption_timeline import KEY, ensure_independent_captions
from ..timeline.studio_edit_sequence import sequence_of, replace_runtime_sequence

FIELDS = ("media", "media_pool", "video_tracks", "audio_tracks", "av_track_groups", "cues",
          "speakers", "asr_evidence", "generation_metadata", "studio_state", "render_settings")


def target_matches(page, target: dict) -> bool:
    """Generation is required as well as project id: close/reopen is a new session."""
    from PySide6.QtCore import QObject
    from shiboken6 import isValid
    if isinstance(page, QObject) and not isValid(page):
        return False
    project = getattr(page, "project", None)
    session = getattr(page, "session", None)
    return bool(project is not None and session is not None
                and project.project_id == target.get("project_id")
                and session.generation == target.get("generation")
                and not getattr(page, "_shutdown_started", False)
                and not getattr(page, "_close_requested", False))


def _snapshot(project):
    return dict(values={key: copy.deepcopy(getattr(project, key)) for key in FIELDS},
                sequence=copy.deepcopy(sequence_of(project)))


def interval_pairs(primary: list[dict], translation: list[dict]) -> tuple[dict[int, list[int]], list[int]]:
    """Accept only unambiguous interval ownership; never zip row numbers.

    Several translation rows fully inside one source sentence may be joined.
    One translation spanning multiple source sentences is preserved for review.
    """
    owners, candidates = {}, {}
    ordered = sorted(enumerate(primary), key=lambda pair: pair[1]["start_ms"])
    active, endings, cursor = {}, [], 0
    for j, secondary in sorted(enumerate(translation), key=lambda pair: pair[1]["start_ms"]):
        while cursor < len(ordered) and ordered[cursor][1]["start_ms"] < secondary["end_ms"]:
            i, row = ordered[cursor]
            active[i] = row
            heapq.heappush(endings, (row["end_ms"], i))
            cursor += 1
        while endings and endings[0][0] <= secondary["start_ms"]:
            _, i = heapq.heappop(endings)
            active.pop(i, None)
        overlaps = []
        for i, row in active.items():  # insertion order is increasing start time
            if row["start_ms"] >= secondary["end_ms"]:
                break
            amount = min(row["end_ms"], secondary["end_ms"])-max(row["start_ms"], secondary["start_ms"])
            if amount >= 50:
                overlaps.append((i, amount))
                if len(overlaps) > 1:
                    break
        if len(overlaps) != 1:
            continue
        i, amount = overlaps[0]
        shorter = min(primary[i]["end_ms"]-primary[i]["start_ms"], secondary["end_ms"]-secondary["start_ms"])
        if amount / max(1, shorter) < .8:
            continue
        owners[j] = i
        candidates.setdefault(i, []).append(j)
    return candidates, [j for j in range(len(translation)) if j not in owners]


def _belongs(receipt: dict, clip_id: str, track_id: str) -> bool:
    return any(span.get("track_id") == track_id and any(item.get("clip_id") == clip_id
               for item in span.get("instances", [])) for span in receipt.get("source_spans", []))


def prepare_import(project, bundle, media_result=None, *, position_ms=0, clip_id="",
                   replace_source=False, confirmed_media=False):
    """All file/network work has finished. Build and validate a private candidate."""
    working = copy.deepcopy(project)
    ensure_independent_captions(working)
    manifest = bundle["manifest"]
    platform, video_id = manifest["platform"], manifest["video_id"]
    state = working.studio_state.setdefault("link_imports", {"version": 1, "tasks": {}, "scopes": {}})
    prior = state["tasks"].get(manifest["task_id"], {})
    all_clips = {c.id: c for t in working.video_tracks for c in t.clips}
    pools = {a.asset_id: a for a in working.media_pool}
    selected_clip_id = clip_id or prior.get("clip_id", "")
    clip = all_clips.get(selected_clip_id)
    if selected_clip_id and clip is None:
        raise ValueError("目标素材片段已被删除，请重新选择导入位置。")
    if clip:
        asset = pools[clip.asset_id]
        source = asset.video_metadata.get("link_source") or {}
        if (source.get("platform"), source.get("video_id")) != (platform, video_id) and not confirmed_media:
            raise ValueError("当前素材缺少同一视频的明确身份，请主动选择并确认对应素材。")
    else:
        # A retry or a later drag can recover only an unambiguous identified instance.
        # A download that brings its own media joins only the same file: an
        # audio-only or other-quality copy of a video already here (2026-10-26)
        # is new media, not a second import onto the old clip.
        media_sha = (manifest.get("media") or {}).get("sha256", "")
        matching = [c for c in all_clips.values() if
            (pools[c.asset_id].video_metadata.get("link_source") or {}).get("video_id") == video_id
            and (pools[c.asset_id].video_metadata.get("link_source") or {}).get("platform") == platform
            and (media_result is None
                 or (pools[c.asset_id].video_metadata.get("link_source") or {}).get("media_sha256", "") == media_sha)]
        if len(matching) > 1:
            raise ValueError("工程中有多个相同视频的片段，请指定本次字幕对应的素材实例。")
        if matching:
            clip = matching[0]
    if clip is None and media_result is not None:
        from ..studio.studio_media_drop import MediaDropCommand
        before_ids = set(all_clips)
        command = MediaDropCommand(working, [media_result], position_ms)
        command.redo()
        clip = next(c for t in working.video_tracks for c in t.clips if c.id not in before_ids)
    if clip is None:
        raise ValueError("仅字幕任务需要选择对应媒体片段；不会仅凭时长自动绑定。")
    asset = next(a for a in working.media_pool if a.asset_id == clip.asset_id)
    # Metadata is an existing extension point, no project/schema version change.
    asset.video_metadata["link_source"] = dict(platform=platform, video_id=video_id,
        task_id=manifest["task_id"], source_url=manifest.get("source_url", ""),
        manifest_name=Path(bundle["manifest_path"]).name,
        media_sha256=(manifest.get("media") or {}).get("sha256", ""))
    track_id = manifest.get("primary_track_id", "")
    captions = bundle["captions"].get(track_id, {}).get("captions", [])
    track = next((s["track"] for s in manifest.get("subtitles", []) if s["track"]["track_id"] == track_id), {})
    scope_key = digest([platform, video_id, track_id, clip.id])
    if captions and scope_key in state["scopes"] and not replace_source:
        return None, dict(status="already_imported", cue_count=0, clip_id=clip.id)
    receipts = working.studio_state.setdefault(KEY, dict(version=1, source_archive=[], instances={}))["instances"]
    if replace_source:
        owned = {cue.id for cue in working.cues if _belongs(receipts.get(cue.id, {}), clip.id, track_id)}
        from ..timeline.studio_caption_timeline import locked_caption_speakers
        locked = locked_caption_speakers(project)
        if any(cue.id in owned and cue.speaker_id in locked for cue in project.cues):
            raise ValueError("目标字幕轨已锁定；请解锁后再替换该来源。")
        working.cues = [cue for cue in working.cues if cue.id not in owned]
        for key in owned:
            receipts.pop(key, None)
    result = dict(status="imported", cue_count=0, clip_id=clip.id, translated=0,
                  translation_unmatched=0, warnings=[], task_id=manifest["task_id"])
    audio_language = manifest.get("audio_language", "")
    if track and audio_language and not language_matches(audio_language, track.get("language", "")):
        result["warnings"].append("字幕语言与所选音轨语言不同；已保留语言标记，请确认配音与原声关系。")
    source_archive = working.studio_state[KEY].setdefault("source_archive", [])
    archived = {row["id"] for row in source_archive}
    imported = {}
    word_count = 0
    for index, row in enumerate(captions):
        a, b = max(int(row["start_ms"]), clip.source_in_ms), min(int(row["end_ms"]), clip.source_out_ms)
        if b <= a:
            continue
        start, end = source_to_project(clip, a), source_to_project(clip, b)
        if start is None or end is None or end <= start:
            raise ValueError("字幕与素材的时间映射无效；未修改工程。")
        revision = digest(row)[:8]
        source_id = f"link-{track_id}-{revision}-{index}"
        cue_id = f"{source_id}@{clip.id}"
        ref = source_id
        cue = StudioCue(id=cue_id, start_ms=start, end_ms=end, text=row["text"], original_text=row["text"],
                        speaker_id="S00", evidence_refs=[ref])
        # Download display timing is not an acoustic observation. Segment starts
        # remain indivisible anchors, never populate measured-word fields.
        working.asr_evidence[ref] = dict(text=row["text"], start_ms=row["start_ms"], end_ms=row["end_ms"],
            words=[], segment_anchors=copy.deepcopy(row.get("anchors", [])),
            final_timing_owner="downloaded_subtitle", timing_precision=row.get("precision", "sentence"),
            link_source=dict(track=copy.deepcopy(track), task_id=manifest["task_id"],
                             events=row.get("events", []), parser_version=bundle["captions"][track_id]["parser_version"]))
        anchors = []
        for anchor in row.get("anchors", []):
            mapped = source_to_project(clip, anchor["start_ms"])
            if mapped is not None and start <= mapped < end:
                value = dict(anchor, start_ms=mapped, source_start_ms=anchor["start_ms"])
                if "end_ms" in anchor:
                    value["source_end_ms"] = anchor["end_ms"]
                    mapped_end = source_to_project(clip, anchor["end_ms"])
                    if mapped_end is not None and mapped < mapped_end <= end:
                        value["end_ms"] = mapped_end
                    else:
                        value.pop("end_ms", None)
                        value["precision"] = "segment_start"
                anchors.append(value)
        # YouTube automatic captions carry each word's start: those become the
        # caption's word timing (2026-10-26); other captions keep sentence timing.
        from ..timeline.link_timing import SENTENCE_TIMING, onset_words, single_word
        from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS
        words = onset_words(row["text"], anchors, start, end, ref)
        if not words and not anchors and (track or {}).get("source") == "automatic":
            words = single_word(row["text"], start, end, ref)
        alignment = DOWNLOADED_WORD_ONSETS if words else SENTENCE_TIMING
        if words:
            word_count += 1
        span = dict(source_cue_id=source_id, source_start_ms=a, source_end_ms=b, source_text=row["text"],
            evidence_refs=[ref], task_fingerprint=scope_key, job_id=manifest["task_id"], track_id=track_id,
            instances=[dict(clip_id=clip.id, source_path=asset.canonical_source,
                            task_start_ms=start, task_end_ms=end)])
        receipts[cue_id] = dict(source_cue_id=source_id, source_start_ms=a, source_end_ms=b,
            translation_parent_ids=[cue_id],
            source_path=asset.canonical_source, text=row["text"], evidence_refs=[ref],
            source_spans=[span], words=words, word_alignment=alignment,
            word_base_interval=[start, end], word_base_words=copy.deepcopy(words), word_base_alignment=alignment,
            segment_anchors=anchors, anchor_base_interval=[start, end], anchor_base_text=row["text"],
            clip_id=clip.id, timing_precision=row.get("precision", "sentence"),
            link_follow=dict(clip_id=clip.id, asset_id=clip.asset_id, source_interval=[a,b],
                             timeline_interval=[start,end]))
        if source_id not in archived:
            source_archive.append(asdict(StudioCue(id=source_id, start_ms=row["start_ms"], end_ms=row["end_ms"],
                text=row["text"], evidence_refs=[ref])))
            archived.add(source_id)
        working.cues.append(cue)
        imported[index] = cue
    if imported and not any(s.id == "S00" for s in working.speakers):
        working.speakers.append(StudioSpeaker(id="S00", name="未知说话人"))
    result["cue_count"] = len(imported)
    if imported and not project.cues:
        from ..subtitle_rules.language_rules import normalize_language, TASK_LANGUAGES
        language = normalize_language(track.get("language", ""))
        if language in TASK_LANGUAGES:
            working.generation_metadata["language"] = dict(code=language, decided_by="downloaded_caption_track")
    result["timing_counts"] = {"sentence": sum(not row.get("anchors") for row in captions),
                              "segment_start": sum(bool(row.get("anchors")) for row in captions),
                              "word_onsets": word_count}
    result["timing_note"] = ("词级时间来自字幕自带的每词开始时间（词尾取下一个词的开始）。" if word_count else
                            "片段起点锚点，未伪造词尾；需要字级时间可使用重新对齐。"
                            if result["timing_counts"]["segment_start"] else "句级时间；需要更细时间可使用重新对齐。")
    translation_id = manifest.get("translation_track_id", "")
    translations = bundle["captions"].get(translation_id, {}).get("captions", [])
    if translations and imported:
        from ..subtitle_rules.subtitle_translation import import_downloaded_translations
        pairs, unmatched = interval_pairs(captions, translations)
        secondary_track = next(s["track"] for s in manifest["subtitles"] if s["track"]["track_id"] == translation_id)
        if (secondary_track.get("source") == "translated" and secondary_track.get("original_language")
                and track.get("language") and not language_matches(secondary_track["original_language"], track["language"])):
            pairs, unmatched = {}, list(range(len(translations)))
            result["warnings"].append("译文的原语言与所选原文不一致；已保留文件，未自动配对。")
        accepted = {imported[i].id: dict(text="\n".join(translations[j]["text"] for j in indices),
                     source_indices=indices, source_intervals=[[translations[j]["start_ms"], translations[j]["end_ms"]] for j in indices])
                    for i, indices in pairs.items() if i in imported}
        import_downloaded_translations(working, accepted, target=secondary_track["language"], track=secondary_track)
        result["translated"], result["translation_unmatched"] = len(accepted), len(unmatched)
        state.setdefault("unmatched_translations", {})[scope_key] = dict(track=secondary_track,
            rows=[translations[j] for j in unmatched], reason="ambiguous_time_overlap")
        if unmatched:
            result["warnings"].append(f"{len(unmatched)} 条译文跨越多个原文或时间不对应，已保留原稿，待人工关联。")
        if accepted and not project.cues:
            from ..caption_style.bilingual_layout import BilingualSettings, compact_defaults
            working.studio_state["bilingual"] = dict(BilingualSettings(mode="bilingual").to_dict(), **compact_defaults())
            working.studio_state["bilingual_mode"] = True
    working.cues.sort(key=lambda c: (c.start_ms, c.id))
    if captions:
        state["scopes"][scope_key] = dict(track_id=track_id, clip_id=clip.id, task_id=manifest["task_id"],
            cue_ids=[cue.id for cue in imported.values()])
    state["tasks"][manifest["task_id"]] = dict(clip_id=clip.id, video_id=video_id,
        manifest_name=Path(bundle["manifest_path"]).name, result=copy.deepcopy(result),
        # Extra selected languages remain preserved, not silently made separate speakers.
        available_tracks=[s["track"] for s in manifest.get("subtitles", [])])
    working.validate()
    validation = validate_project(working, stage="link_import")
    if not validation.ok:
        raise SubtitleConsistencyError(validation)
    return _snapshot(working), result


class LinkImportCommand(QUndoCommand):
    def __init__(self, project, bundle, media_result=None, **options):
        super().__init__("导入下载视频与字幕")
        self.project = project
        self.before = _snapshot(project)
        self.after, self.result = prepare_import(project, bundle, media_result, **options)
        if self.after is None:
            self.setObsolete(True)

    def _apply(self, data):
        if data is None:
            return
        dirty = (DirtyDomain.MEDIA_POOL | DirtyDomain.VIDEO_TRACKS | DirtyDomain.AUDIO_TRACKS
                 | DirtyDomain.SEQUENCE_STRUCTURE | DirtyDomain.TIMELINE_INDEX | DirtyDomain.TIMELINE_PIXELS
                 | DirtyDomain.MEDIA_TIMING | DirtyDomain.VIDEO_COMPOSITION | DirtyDomain.AUTOSAVE
                 | DirtyDomain.PROJECT_METADATA | DirtyDomain.CUE_MODEL | DirtyDomain.CUE_CONTENT
                 | DirtyDomain.CUE_TIMING | DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW)
        with state_for(self.project).transaction(self.project, action_id="link_import", dirty=dirty):
            for key, value in data["values"].items():
                setattr(self.project, key, copy.deepcopy(value))
            replace_runtime_sequence(self.project, copy.deepcopy(data["sequence"]))

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class MediaCompanionCommand(LinkImportCommand):
    """One drop transaction includes all verified sidecars, or none of the changes."""
    def __init__(self, project, results, position_ms, track_id=""):
        QUndoCommand.__init__(self, "拖入媒体与配套字幕")
        self.project = project
        self.before = _snapshot(project)
        working = copy.deepcopy(project)
        from ..studio.studio_media_drop import MediaDropCommand
        old_ids = {c.id for t in working.video_tracks for c in t.clips}
        MediaDropCommand(working, results, position_ms, track_id).redo()
        new_clips = [c for t in working.video_tracks for c in t.clips if c.id not in old_ids]
        assets = {a.asset_id: a for a in working.media_pool}
        self.result = dict(cue_count=0, warnings=[])
        for result in results:
            if not result.subtitle_bundle:
                if result.subtitle_error:
                    self.result["warnings"].append(result.subtitle_error)
                continue
            clip = next(c for c in new_clips if Path(assets[c.asset_id].canonical_source).resolve() == Path(result.source_path).resolve())
            command = LinkImportCommand(working, result.subtitle_bundle, clip_id=clip.id, confirmed_media=True)
            command.redo()
            self.result["cue_count"] += command.result["cue_count"]
            self.result["warnings"].extend(command.result.get("warnings", []))
            new_clips.remove(clip)
        self.after = _snapshot(working)
