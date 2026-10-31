"""Prepare additive subtitle imports; external labels never become track identity."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from .studio_project import StudioCue, StudioSpeaker, parse_ass_dialogue_line, parse_subtitle_timecode_ms
from ..exports.srt_codec import SIDECAR_FORMAT, sidecar_path

IMPORT_KEY = "subtitle_imports"


def normalize_speaker(value: str) -> str:
    value = str(value or "").strip()
    match = re.fullmatch(r"s(\d+)", value, re.I)
    return f"S{int(match[1]):02d}" if match else value


def normalize_language(value: str) -> str:
    """Keep script and region distinctions (recognition normalization loses them)."""
    from ..subtitle_rules.language_rules import TASK_LANGUAGES
    parts = str(value or "").replace("_", "-").split("-")
    if parts[0].lower() not in TASK_LANGUAGES or any(
        not re.fullmatch(r"[a-zA-Z0-9]{2,8}", part) for part in parts[1:]
    ):
        return ""
    return "-".join([parts[0].lower(), *(
        part.title() if len(part) == 4 else part.upper() if len(part) == 2 else part
        for part in parts[1:])])


def language_label(language: str) -> str:
    from ..subtitle_rules.european_text import LABELS
    names = {"zh": "中文", "zh-Hans": "简体中文", "zh-Hant": "繁体中文",
             "ja": "日语", "en": "英语", "ko": "韩语", **LABELS}
    if not language:
        return tr("未指定语言")
    if language in names:
        return tr(names[language])
    base, _, region = language.partition("-")
    return f"{tr(names.get(base, base))}（{region}）"


def filename_metadata(path: Path) -> tuple[str, str]:
    """Only terminal exporter fields, never arbitrary words or subtitle dialogue."""
    stem = path.stem
    stem = re.sub(r"\.translation(?=\.[a-zA-Z]{2}(?:[-_][a-zA-Z0-9]+)*$)", "", stem, flags=re.I)
    # Layer writer inserts a collision counter before the language suffix.
    stem = re.sub(r" \(\d+\)(?=\.[a-zA-Z]{2}(?:[-_][a-zA-Z0-9]+)*$)", "", stem)
    match = re.search(r"(?:^|[._ -])(s\d+)(?:[._ -]?([a-z]{2}(?:[-_][a-z0-9]{2,8})*))?$", stem, re.I)
    if match:
        language = normalize_language(match[2] or "")
        if not match[2] or language:
            return normalize_speaker(match[1]), language
    # Our language-layer exports use .<language>, not words containing 'it'.
    suffix = stem.rsplit(".", 1)
    if len(suffix) == 2:
        return "", normalize_language(suffix[1])
    return "", ""


@dataclass
class ImportRow:
    number: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str = ""
    language: str = ""
    source_track: str = ""
    source_cue: str = ""
    role: str = "independent"
    association: dict = field(default_factory=dict)


@dataclass
class ParsedSubtitles:
    path: Path
    rows: list[ImportRow]
    sha256: str
    export_id: str = ""
    warnings: list[str] = field(default_factory=list)


_TIME = r"\d{1,}:[0-5]\d:[0-5]\d[,.]\d{1,3}"
_HEADER = re.compile(rf"(?m)^(?:[ \t]*(\d+)[ \t]*\n)?[ \t]*({_TIME})[ \t]*-->[ \t]*({_TIME})[^\n]*\n")


def _srt_rows(text: str) -> list[ImportRow]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    headers = list(_HEADER.finditer(text))
    if not headers or text[:headers[0].start()].strip():
        raise ValueError("没有读取到有效 SRT 字幕标头")
    rows = []
    for index, match in enumerate(headers):
        body = text[match.end():headers[index + 1].start() if index + 1 < len(headers) else len(text)]
        # Remove framing only, preserving body indentation, line breaks and blanks.
        body = body.removesuffix("\n\n") if index + 1 < len(headers) else body.removesuffix("\n")
        start, end = (parse_subtitle_timecode_ms(match[n]) for n in (2, 3))
        if start is None or end is None or end <= start:
            raise ValueError(f"第 {index + 1} 条字幕时间无效")
        if "-->" in body and re.search(r"(?m)^\S*\d.*-->.*$", body):
            raise ValueError(f"第 {index + 1} 条后有无法解析的时间标头")
        rows.append(ImportRow(int(match[1] or index + 1), start, end, body))
    return rows


def _legacy_companion(result: ParsedSubtitles) -> None:
    """Older optional JSON exports have no digest: match every time and body."""
    path = result.path
    candidates = [path.with_suffix(".json")]
    if "." in path.stem:
        base = path.stem.rsplit(".", 1)[0]
        if base.endswith(".translation"):
            base = base.removesuffix(".translation")
        candidates.append(path.with_name(base + ".json"))
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            raw = candidate.read_bytes()
            metadata = json.loads(raw.decode("utf-8-sig"))
            if metadata.get("kind") != "2byteasr-subtitle-export" or metadata.get("schema_version") != 1:
                continue
            entries = metadata["cues"]
            variations = [("original", entries, [r["text"] for r in entries], metadata.get("original_language", ""))]
            translated = [r for r in entries if r.get("translation", {}).get("text", "").strip()]
            variations.append(("translation", translated, [r["translation"]["text"] for r in translated], metadata.get("translation_target", "")))
            for first in (True, False):
                texts = []
                for row in entries:
                    parts = [row.get("translation", {}).get("text", ""), row["text"]]
                    texts.append("\n".join(part for part in (parts if first else reversed(parts)) if part))
                variations.append(("bilingual", entries, texts, ""))
            matches = []
            actual = [(r.start_ms, r.end_ms, r.text) for r in result.rows]
            for role, rows, texts, lang in variations:
                if actual == [(r["start_ms"], r["end_ms"], text) for r, text in zip(rows, texts)]:
                    key = (role, normalize_language(lang))
                    if key not in [item[0] for item in matches]:
                        matches.append((key, rows))
            # With no translations the bilingual rendering equals original.
            if not translated:
                matches = [m for m in matches if m[0][0] == "original"]
            if len(matches) != 1:
                result.warnings.append(f"{path.name}：旧 JSON 与字幕不能唯一完整匹配，保留为独立文件轨道")
                continue
            (role, lang), rows = matches[0]
            for row, entry in zip(result.rows, rows):
                sid = normalize_speaker(entry.get("speaker_name") or entry.get("speaker_id", ""))
                if row.speaker and row.speaker != sid or row.language and lang and row.language != lang:
                    result.warnings.append(f"{path.name}：文件名与完整匹配的 JSON 冲突，采用 JSON 元数据")
                row.speaker, row.language, row.role = sid, lang, role
                row.source_track, row.source_cue = str(entry.get("speaker_id", "")), str(entry.get("id", ""))
            result.export_id = "legacy-json-" + hashlib.sha256(raw).hexdigest()
            return
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            result.warnings.append(f"{path.name}：旧 JSON 无法校验，保留为独立文件轨道")


def read_subtitles(path: Path) -> ParsedSubtitles:
    path = Path(path).resolve()
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "gb18030")
    speaker, language = filename_metadata(path)
    rows = []
    if path.suffix.lower() == ".srt":
        rows = _srt_rows(text)
    elif path.suffix.lower() == ".ass":
        for number, line in enumerate(text.splitlines(), 1):
            if not line.startswith("Dialogue:"):
                continue
            parsed = parse_ass_dialogue_line(line)
            if parsed is None:
                raise ValueError(f"第 {number} 行 ASS 对话无效")
            start, end, _style, actor, body = parsed
            rows.append(ImportRow(number, start, end, body, normalize_speaker(actor)))
    else:
        raise ValueError("只支持 SRT / ASS 字幕文件")
    if not rows:
        raise ValueError("没有读取到有效字幕")
    result = ParsedSubtitles(path, rows, hashlib.sha256(raw).hexdigest())
    for row in rows:
        if row.speaker and speaker and row.speaker != speaker:
            result.warnings.append(f"{path.name}：ASS Actor {row.speaker} 优先于文件名 {speaker}")
        row.speaker = row.speaker or speaker
        row.language = language
    companion = sidecar_path(path)
    if companion.is_file():
        try:
            metadata = json.loads(companion.read_text("utf-8"))
            entries = metadata["rows"]
            if (metadata.get("format") != SIDECAR_FORMAT or metadata.get("version") != 1
                    or metadata.get("sha256") != result.sha256 or len(entries) != len(rows)):
                raise ValueError("元数据版本、文件校验或条数不匹配")
            resolved = []
            for row, entry in zip(rows, entries):
                if (entry["number"], entry["start_ms"], entry["end_ms"]) != (row.number, row.start_ms, row.end_ms):
                    raise ValueError("元数据条目与字幕时间不匹配")
                sid = normalize_speaker(entry.get("speaker", ""))
                lang = normalize_language(entry.get("language", ""))
                association = entry.get("association", {})
                if not isinstance(association, dict) or not all(isinstance(association.get(k), str) for k in ("export_id", "cue_id")):
                    association = {}
                resolved.append((sid, lang, str(entry.get("track_id", "")), str(entry.get("cue_id", "")),
                                 str(entry.get("role", "independent")), association))
            for row, (sid, lang, track, cue, role, association) in zip(rows, resolved):
                if (row.speaker and sid and row.speaker != sid) or (row.language and lang and row.language != lang):
                    result.warnings.append(f"{path.name}：文件名/Actor 与已校验元数据冲突，采用配套元数据")
                row.speaker, row.language = sid, lang
                row.source_track, row.source_cue, row.role = track, cue, role
                row.association = association
            result.export_id = str(metadata.get("export_id", ""))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            result.warnings.append(f"{path.name}：配套元数据无效，按文件名导入独立轨道（{exc}）")
    if not result.export_id:
        _legacy_companion(result)
    result.warnings = list(dict.fromkeys(result.warnings))
    return result


@dataclass
class SubtitleImportPlan:
    cues: list[StudioCue] = field(default_factory=list)
    speakers: list[StudioSpeaker] = field(default_factory=list)
    tracks: dict = field(default_factory=dict)
    instances: dict = field(default_factory=dict)
    cue_sources: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    replace_track_id: str = ""
    replacement_name: str = ""


def prepare_import(project, paths, *, replace_track_id: str = "") -> SubtitleImportPlan:
    """Parse all files before touching the project. Each file has a new scope."""
    plan = SubtitleImportPlan(replace_track_id=replace_track_id)
    paths = list(dict.fromkeys(Path(path).resolve() for path in paths))
    names = {speaker.name.casefold() for speaker in project.speakers if speaker.id != replace_track_id}
    for path in paths:
        try:
            parsed = read_subtitles(path)
            for row in parsed.rows:
                if row.start_ms < 0 or row.end_ms <= row.start_ms:
                    raise ValueError(f"第 {row.number} 条字幕时间无效")
            instance = uuid.uuid4().hex
            groups = {}
            for row in parsed.rows:
                groups.setdefault((row.source_track, row.speaker, row.language, row.role), []).append(row)
            if replace_track_id and (len(paths) != 1 or len(groups) != 1):
                raise ValueError("替换指定轨道需要一个文件且只包含一个说话人/语言轨道")
            for (_source_track, sid, lang, role), rows in groups.items():
                track_id = replace_track_id or "subtitle-" + uuid.uuid4().hex
                name = f"{sid or path.stem} · {language_label(lang)}"
                original, counter = name, 2
                while name.casefold() in names:
                    name = f"{original}（{counter}）"
                    counter += 1
                names.add(name.casefold())
                if not replace_track_id:
                    plan.speakers.append(StudioSpeaker(track_id, name))
                else:
                    plan.replacement_name = name
                plan.tracks[track_id] = dict(instance_id=instance, speaker=sid, language=lang,
                                             source_track=_source_track, role=role)
                for row in rows:
                    cue_id = "subtitle-cue-" + uuid.uuid4().hex
                    cue = StudioCue(cue_id, row.start_ms, row.end_ms, row.text, speaker_id=track_id, original_text=row.text)
                    cue.validate()
                    plan.cues.append(cue)
                    plan.cue_sources[cue_id] = dict(instance_id=instance, file_number=row.number,
                        source_cue=row.source_cue, export_id=parsed.export_id, role=row.role,
                        association=row.association or (dict(export_id=parsed.export_id, cue_id=row.source_cue)
                            if parsed.export_id and row.source_cue else {}))
            plan.instances[instance] = dict(path=str(path), filename=path.name, sha256=parsed.sha256,
                                           export_id=parsed.export_id)
            plan.warnings.extend(parsed.warnings)
        except (OSError, ValueError, UnicodeError) as exc:
            plan.failures.append(f"{path.name}：{exc}")
    if replace_track_id and not any(s.id == replace_track_id for s in project.speakers):
        raise ValueError("指定的字幕轨道已不存在")
    return plan


def imported_track(project, track_id: str) -> dict:
    return project.generation_metadata.get(IMPORT_KEY, {}).get("tracks", {}).get(track_id, {})
