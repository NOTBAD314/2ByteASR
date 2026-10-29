"""Small, evidence-only completion summaries; never infer a successful stage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_COPY = {
    '摘要 · 查看全部': ('Summary · View all', '要約 · すべて表示'),
    '全部 · 返回摘要': ('Full · Back to summary', '全体 · 要約に戻る'),
    '已收起 · 展开摘要': ('Collapsed · Show summary', '折りたたみ · 要約を表示'),
    '收起': ('Collapse', '折りたたむ'),
    '展开': ('Expand', '展開'),
    '有效音频 {seconds} 秒': ('Audio processed: {seconds}s', '処理音声 {seconds} 秒'),
    '有效时长未记录': ('Processed duration unrecorded', '処理時間の記録なし'),
    '字幕工程已保存并载入': ('Subtitle project saved and loaded', '字幕プロジェクトを保存・読込済み'),
    '工程无法载入：{reason}': ('Project could not load: {reason}', 'プロジェクトを読み込めません：{reason}'),
    '工程保存状态待确认': ('Project save status unconfirmed', 'プロジェクトの保存状態は未確認'),
    '场景：{domain}（{source}）': ('Context: {domain} ({source})', '内容：{domain}（{source}）'),
    '场景：{domain}': ('Context: {domain}', '内容：{domain}'),
    '场景未记录（本任务）': ('Context unrecorded for this task', 'このタスクの内容設定は未記録'),
    '词库：{libraries}': ('Glossaries: {libraries}', '用語集：{libraries}'),
    ' · {count} 个有效词条': (' · {count} effective terms', ' · 有効用語 {count} 件'),
    '未记录启用词库': ('Enabled glossaries unrecorded', '有効な用語集の記録なし'),
    '素材：{name} · {duration}': ('Media: {name} · {duration}', '素材：{name} · {duration}'),
    '{count} 条字幕 · {saved}': ('{count} subtitles · {saved}', '字幕 {count} 件 · {saved}'),
    '识别产出 {count} 条字幕 · 工程当前 {current} 条 · {saved}': ('{count} subtitles recognized · {current} in the project now · {saved}', '認識時 {count} 件 · 現在のプロジェクト {current} 件 · {saved}'),
    '工程：{path}': ('Project: {path}', 'プロジェクト：{path}'),
    '工程位置未记录；可在更多操作中恢复已有结果': ('Project path unrecorded; recover results from More actions', 'プロジェクトの場所は未記録。「その他」で結果を復元できます'),
    '待审核：{count} 处疑似术语未召回{scope}': ('Review: {count} suspected terms had no candidate{scope}', '要確認：候補がない疑わしい用語 {count} 件{scope}'),
    '（{count} 条处理记录）': (' ({count} processing records)', '（処理記録 {count} 件）'),
    'AI建议被保护规则拒绝 {count} 处{reason}': ('Safety rules rejected {count} AI edits{reason}', '保護ルールでAI変更 {count} 件を却下{reason}'),
    '待审核：{count} 项；执行完成不等于质量检查通过': ('Review: {count} items; completed processing does not certify quality', '要確認 {count} 件。処理完了は品質確認完了を意味しません'),
    'AI校对': ('AI correction', 'AI校正'),
    'AI断句': ('AI grouping', 'AI文区切り'),
    '完成': ('completed', '完了'), '失败': ('failed', '失敗'), '取消': ('cancelled', '中止'),
    '未执行': ('not run', '未実行'), '状态待确认': ('status unconfirmed', '状態未確認'),
    '未记录': ('unrecorded', '記録なし'),
    '本地名称规范化 {local} 处{scan}；AI提出 {proposed} / 采纳 {accepted} / 拒绝 {rejected} 处': ('Local name normalization: {local}{scan}; AI proposed {proposed} / accepted {accepted} / rejected {rejected}', 'ローカル名称統一 {local} 件{scan}；AI提案 {proposed} / 採用 {accepted} / 却下 {rejected} 件'),
    '（扫描 {count} 条）': (' ({count} records scanned)', '（{count} 件を確認）'),
    '待审核 {count} 项 · {search}': ('{count} review items · {search}', '要確認 {count} 件 · {search}'),
    '用户选择': ('user selection', 'ユーザーの選択'),
    '启用词库元数据': ('enabled glossary metadata', '有効な用語集のメタデータ'),
    '多个领域词库': ('multiple glossary domains', '複数の用語集の分野'),
    '来源未知': ('source unknown', '出典不明'),
}


def completion_translate(source, language):
    from ..i18n import translate
    options = _COPY.get(source)
    return options[0 if language == 'en' else 1] if options and language in {'en', 'ja'} else translate(source, language)


@dataclass(frozen=True)
class CompletionSummary:
    task_lines: tuple[str, ...]
    log_lines: tuple[str, ...]
    local_replacements: int | None
    ai_proposed: int | None
    ai_accepted: int | None
    ai_rejected: int | None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _count(value):
    try:
        return max(0, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def completion_summary(report, outcome, *, media_path='', project_path='', project_loaded=False,
                       project_error='', language='zh', project_cues=None):
    """Use this task's immutable report and caller-verified delivery only.

    Missing counters stay unknown. A saved project and a completed request are
    independent of quality review, local name normalization and rejected edits.
    """
    translate = completion_translate

    def line(template, **values):
        return translate(template, language).format(**values)

    report = _dict(report)
    result = _dict(report.get('result'))
    settings = _dict(report.get('settings'))
    profile = _dict(settings.get('content_profile'))
    snapshot = _dict(profile.get('terminology_snapshot'))
    events = _rows(report.get('events'))
    polish = _dict(report.get('polishing_summary'))
    context = _dict(polish.get('term_context'))
    local = [row for row in events if row.get('event') == 'terminology_applied']
    local_counts = [_count(row.get('replacement_count')) for row in local]
    local_count = sum(local_counts) if local_counts and all(value is not None for value in local_counts) else None
    scan_count = max((_count(row.get('scanned_segment_count')) or 0 for row in local), default=0)
    finals = [row for row in events if row.get('event') == 'terminology_polish_final']
    final_details = {str(row.get('cue_id')): _dict(row.get('details')) for row in finals}
    proposed = _count(context.get('proposed_edits'))
    if proposed is None and final_details and all(isinstance(row.get('returned_edits'), list) for row in final_details.values()):
        proposed = sum(len(_rows(row['returned_edits'])) for row in final_details.values())
    accepted = _count(context.get('accepted_edits'))
    rejected = _count(context.get('rejected_edits'))
    if accepted is None and final_details and all(isinstance(row.get('accepted_edits'), list) for row in final_details.values()):
        accepted = sum(len(_rows(row['accepted_edits'])) for row in final_details.values())
    if rejected is None and final_details and all(isinstance(row.get('rejected_edits'), list) for row in final_details.values()):
        rejected = sum(len(_rows(row['rejected_edits'])) for row in final_details.values())

    name = str(_dict(report.get('media')).get('name') or Path(media_path).name or '')
    seconds = result.get('audio_seconds')
    duration = line('有效音频 {seconds} 秒', seconds=f'{float(seconds):.3f}') if isinstance(seconds, (int, float)) else translate('有效时长未记录', language)
    saved = translate('字幕工程已保存并载入', language) if project_loaded else line('工程无法载入：{reason}', reason=project_error) if project_error else translate('工程保存状态待确认', language)
    resolved = _dict(profile.get('resolved_context')) or _dict(settings.get('resolved_content_context'))
    domain = str(resolved.get('domain') or resolved.get('game') or profile.get('game') or '')
    source = str(resolved.get('domain_source') or resolved.get('source') or '')
    source = translate({'user_selected': '用户选择', 'enabled_glossary_metadata': '启用词库元数据',
        'mixed_enabled_glossaries': '多个领域词库', 'unknown': '来源未知'}.get(source, source), language)
    scene = line('场景：{domain}（{source}）', domain=domain, source=source) if domain and source else line('场景：{domain}', domain=domain) if domain else translate('场景未记录（本任务）', language)
    libraries = _rows(snapshot.get('libraries'))
    versions = ' / '.join(str(row.get('name') or row.get('id')) + (' · r' + str(row['revision']) if row.get('revision') is not None else '') for row in libraries if row.get('found') is not False)
    if not versions:
        versions = ' / '.join(str(value) for value in profile.get('enabled_glossary_ids', ()) or ()) or translate('未记录启用词库', language)
    terms = _count(snapshot.get('effective_terms'))
    glossary = line('词库：{libraries}', libraries=versions) + (line(' · {count} 个有效词条', count=terms) if terms is not None else '')
    task_lines = (line('素材：{name} · {duration}', name=name, duration=duration),
                  (line('识别产出 {count} 条字幕 · 工程当前 {current} 条 · {saved}', count=outcome.final_cues,
                        current=project_cues, saved=saved)
                   if project_cues is not None and project_cues != outcome.final_cues else
                   line('{count} 条字幕 · {saved}', count=outcome.final_cues, saved=saved)),
                  scene + ' · ' + glossary,
                  line('工程：{path}', path=project_path) if project_path else translate('工程位置未记录；可在更多操作中恢复已有结果', language))

    warnings = []
    gaps = _count(context.get('unresolved_recall_gaps'))
    if gaps:
        gap_cues = _count(context.get('recall_gap_cues'))
        warnings.append(line('待审核：{count} 处疑似术语未召回{scope}', count=gaps,
                             scope=line('（{count} 条处理记录）', count=gap_cues) if gap_cues is not None else ''))
    if rejected:
        reasons = []
        for row in finals:
            for edit in _rows(_dict(row.get('details')).get('rejected_edits')):
                source_word = str(edit.get('from') or edit.get('source') or edit.get('original') or edit.get('original_text') or '')
                target_word = str(edit.get('to') or edit.get('target') or edit.get('replacement') or edit.get('new_text') or '')
                reason = str(edit.get('rule_id') or edit.get('reason') or '')
                reasons.append((source_word + ' → ' + target_word + (' · ' + reason if reason else '')).strip(' →'))
        warnings.append(line('AI建议被保护规则拒绝 {count} 处{reason}', count=rejected,
                             reason='：' + reasons[0] if reasons and reasons[0] else ''))
    if project_error:
        warnings.insert(0, line('工程无法载入：{reason}', reason=project_error))
    if outcome.polish_status not in {'completed', 'disabled'}:
        warnings.append(translate(outcome.polish_label, language))
    if outcome.core_errors:
        warnings[:0] = list(outcome.core_errors[:2])
    if not warnings and outcome.review_issue_count:
        warnings.append(line('待审核：{count} 项；执行完成不等于质量检查通过', count=outcome.review_issue_count))
    warnings = list(dict.fromkeys(warnings))
    if len(warnings) > 2:
        warnings = [warnings[0], '；'.join(warnings[1:])]

    stages = _rows(report.get('stages'))
    def stage(parts, short_name):
        found = next((row for row in reversed(stages) if any(part in str(row.get('label') or '').lower() for part in parts)
                      and '筛选' not in str(row.get('label') or '')), None)
        if not found:
            return ''
        elapsed = found.get('elapsed_seconds')
        state = str(found.get('status') or 'unknown')
        status = translate({'completed': '完成', 'failed': '失败', 'cancelled': '取消', 'skipped': '未执行'}.get(state, '状态待确认'), language)
        return short_name + ' ' + (f'{float(elapsed):.3f}s ' if isinstance(elapsed, (int, float)) else '') + status
    local_stages = [stage(parts, name) for parts, name in ((('moss',), 'MOSS'), (('fireredasr2-aed',), 'FireRed'), (('qwen3-asr',), 'Qwen3'))]
    remote_stages = [stage(('文字校对', '文本校对', '文字校准', '受限校对', 'polish'), translate('AI校对', language)),
                     stage(('断句', 'group'), translate('AI断句', language))]
    timing_lines = []
    if any(local_stages):
        timing_lines.append(' · '.join(value for value in local_stages if value))
    if any(remote_stages):
        timing_lines.append(' · '.join(value for value in remote_stages if value))
    if not timing_lines:
        timing_lines.append(translate(outcome.polish_label, language) + ' · ' + translate(outcome.search_label, language))
    unknown = translate('未记录', language)
    counts_line = line('本地名称规范化 {local} 处{scan}；AI提出 {proposed} / 采纳 {accepted} / 拒绝 {rejected} 处',
        local=local_count if local_count is not None else unknown,
        scan=line('（扫描 {count} 条）', count=scan_count) if local else '',
        proposed=proposed if proposed is not None else unknown,
        accepted=accepted if accepted is not None else unknown,
        rejected=rejected if rejected is not None else unknown)
    # Always name the optional stage honestly, even when no request was made.
    quality_line = line('待审核 {count} 项 · {search}', count=outcome.review_issue_count,
                        search=translate(outcome.search_label, language))
    logs = tuple((warnings + timing_lines + [counts_line, quality_line])[:6])
    return CompletionSummary(tuple(task_lines), logs, local_count, proposed, accepted, rejected)
