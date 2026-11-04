"""Read-only export diagnostics with canonical owners and effective scope."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from ..glossary.translation_terms import digest

EMPTY_CONFIRMATIONS = 'intentional_empty_sources'


@dataclass(frozen=True)
class ExportIssue:
    code: str
    label: str
    reason: str
    blocking: bool = True
    cue_id: str = ''
    view_id: str = ''
    start_ms: int = 0
    end_ms: int = 0
    track_id: str = ''
    speaker: str = ''
    layer: str = 'original'
    text: str = ''
    manuscript: str = ''
    translation: str = ''
    input_version: str = ''
    stage: str = '字幕预检'
    provenance: str = ''

    def to_dict(self):
        return asdict(self)


class ExportPreflightError(ValueError):
    def __init__(self, issues):
        self.issues = tuple(issues)
        blocking = [issue for issue in self.issues if issue.blocking]
        first = (blocking or list(self.issues))[0]
        super().__init__(f"{len(blocking)} 项问题需处理：{clock(first.start_ms)} · {first.speaker or first.track_id} · {first.label}。可打开问题列表定位字幕。")

    def details(self):
        import json
        return json.dumps([i.to_dict() for i in self.issues], ensure_ascii=False, indent=2)


def clock(ms):
    seconds, millis = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}'


def owner_for(project, view_id):
    from ..timeline.studio_edit_sequence import source_cue_id_of
    canonical = {cue.id: cue for cue in project.cues}
    return canonical.get(view_id) or canonical.get(source_cue_id_of(view_id))


def empty_version(project, cue):
    from ..subtitle_rules.subtitle_translation import records_of, container_target
    from ..subtitle_rules.language_rules import project_language
    record = records_of(project).get(cue.id, {})
    return digest([cue.id, cue.text, cue.original_text, cue.start_ms, cue.end_ms, cue.speaker_id,
        project_language(project), container_target(project), {k: record.get(k) for k in ('text', 'source_sha', 'target', 'origin')},
        project.generation_metadata.get('subtitle_imports', {}).get('cues', {}).get(cue.id, {})])


def export_issues(project, cues=None, *, start_ms=None, end_ms=None, validate_structure=True):
    from ..timeline.studio_edit_sequence import projected_cues, source_cue_id_of
    from ..caption_style.bilingual_layout import settings_from_state
    from ..subtitle_rules.subtitle_translation import records_of
    views = list(projected_cues(project, domain='timeline') if cues is None else cues)
    hidden = project.hidden_speaker_ids()
    visibility = project.studio_state.get('subtitle_track_visibility', {})
    views = [cue for cue in views if cue.speaker_id not in hidden and visibility.get(cue.speaker_id, True)
             and (start_ms is None or cue.end_ms > start_ms) and (end_ms is None or cue.start_ms < end_ms)]
    speakers = {s.id: s.name for s in project.speakers}
    tracks = project.generation_metadata.get('subtitle_imports', {}).get('tracks', {})
    records = records_of(project)
    decisions = project.studio_state.get(EMPTY_CONFIRMATIONS, {})
    mode = settings_from_state(project.studio_state).mode
    from ..subtitle_rules.language_rules import project_language
    source_language = project_language(project).split('-')[0]
    output, seen = [], set()
    canonical = {cue.id: cue for cue in project.cues}
    for view in views:
        # First check exact ownership: range-* is a real range-recognition ID,
        # while #segment denotes an export/editor projection of that owner.
        cue = canonical.get(view.id) or canonical.get(source_cue_id_of(view.id))
        if cue is None or cue.id in seen:
            continue
        seen.add(cue.id)
        role = tracks.get(cue.speaker_id, {}).get('role')
        track_language = str(tracks.get(cue.speaker_id, {}).get('language') or '').split('-')[0]
        independent_translation = role == 'independent' and source_language and track_language and track_language != source_language
        if (mode == 'translation' or role == 'translation' or independent_translation or view.id.endswith('#tr')
                or str(cue.text).strip() or not str(cue.original_text).strip()):
            continue
        version = empty_version(project, cue)
        confirmation = decisions.get(cue.id, {}) if isinstance(decisions, dict) else {}
        if isinstance(confirmation, dict) and confirmation.get('input_version') == version:
            continue
        provenance = '当前工程中的实际字幕ID；尚无首次清空写入证据'
        range_ids = (project.generation_metadata.get('timeline_recognition', {}).get('range') or {}).get('cue_ids', ())
        if cue.id in range_ids:
            provenance += '；工程收据标记为区间识别结果'
        if view.id != cue.id:
            provenance += '；已保留剪辑实例→实际字幕映射'
        manual = project.studio_state.get('manual_caption_text', {})
        if cue.id in manual and manual[cue.id] == '':
            provenance += '；工程含人工空文编辑收据，仍需核对意图'
        output.append(ExportIssue('empty_source', '原文为空，原稿非空',
            '当前文本为空不能单凭原稿判断丢失。请查看原稿，恢复、编辑，或确认这次有意清空。',
            cue_id=cue.id, view_id=view.id, start_ms=view.start_ms, end_ms=view.end_ms,
            track_id=cue.speaker_id, speaker=speakers.get(cue.speaker_id, cue.speaker_id),
            text=cue.text, manuscript=cue.original_text, translation=str(records.get(cue.id, {}).get('text') or ''),
            input_version=version, provenance=provenance))
    if validate_structure:
        from ..projects.subtitle_consistency import validate_export_view
        result = validate_export_view(project, views, stage='export')
        by_view = {view.id: view for view in views}
        for row in result.errors:
            cue = canonical.get(row.cue_id) or canonical.get(source_cue_id_of(row.cue_id))
            view = by_view.get(row.cue_id, cue)
            output.append(ExportIssue(row.code, '字幕数据需要检查', row.reason,
                cue_id=cue.id if cue else '', view_id=row.cue_id,
                start_ms=getattr(view, 'start_ms', 0), end_ms=getattr(view, 'end_ms', 0),
                track_id=getattr(cue, 'speaker_id', ''), speaker=speakers.get(getattr(cue, 'speaker_id', ''), ''),
                text=getattr(cue, 'text', ''), manuscript=getattr(cue, 'original_text', '')))
    unique = {}
    for row in output:
        unique.setdefault((row.code, row.cue_id or row.view_id), row)
    return tuple(unique.values())


def issues_from_error(project, error):
    if isinstance(error, ExportPreflightError):
        return error.issues
    result = getattr(error, 'result', None)
    if result is not None:
        canonical = {cue.id: cue for cue in project.cues}
        return tuple(ExportIssue(row.code, '字幕数据需要检查', row.reason,
            cue_id=row.cue_id, view_id=row.cue_id, start_ms=getattr(canonical.get(row.cue_id), 'start_ms', 0),
            text=getattr(canonical.get(row.cue_id), 'text', ''), stage=row.stage) for row in result.errors)
    return (ExportIssue('task_failure', '导出任务无法继续', str(error), stage='准备导出窗口'),)
