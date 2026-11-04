"""Read-only explanation of the same snapshots used by normal text tasks."""
from __future__ import annotations

from types import SimpleNamespace

from .terminology import TermResolver


def diagnose_sentence(text, browsed, enabled, *, expected_canonical='', scene=None,
                      task_snapshot=None, pending=False):
    """Keep library preview distinct from actual batch eligibility.

    An optional user supplied target lets us distinguish a missing canonical
    entry from a missing alias association without inventing a nickname relation.
    """
    preview = TermResolver(browsed).resolve(text, scene=scene, context_text=text)
    actual = TermResolver(enabled).resolve(text, scene=scene, context_text=text)
    skipped_keys = {item.source.casefold() for resolution in (preview, actual)
                    for item in resolution.skipped if item.reason != 'already_canonical'}
    conflicts = [item for item in (*preview.conflicts, *actual.conflicts) if item.key in skipped_keys]
    reasons = []
    if pending:
        reasons.append(('unsubmitted_draft', '编辑内容尚未保存；本批快照只读取已提交词条'))
    missing = [library for library in browsed.libraries if not library.found]
    if missing:
        reasons.append(('library_missing', '当前浏览的词库不存在'))
    enabled_ids = {library.id for library in enabled.libraries}
    if not any(library.id in enabled_ids for library in browsed.libraries):
        reasons.append(('library_not_enabled', '当前浏览词库未用于本批，或术语增强已关闭'))
    expected = str(expected_canonical or '').strip()
    terms = [term for library in browsed.libraries for term in library.terms]
    expected_terms = [term for term in terms if term.canonical == expected] if expected else []
    if expected and not expected_terms:
        if any(expected == value for library in browsed.libraries for value in library.reference_terms):
            reasons.append(('reference_only', '规范词仅在参考资料中，尚未确认加入本地词库'))
        else:
            reasons.append(('term_missing', f'规范词 {expected} 不存在；不会猜测或改成相近拼写'))
    elif expected_terms and not any(term.confirmed for term in expected_terms):
        reasons.append(('reference_only', '规范词尚未确认，不能作为确定替换'))
    elif expected_terms and not any(hit.canonical == expected for hit in preview.hits):
        matched_alias = any(alias and alias.casefold() in text.casefold()
                            for term in expected_terms for alias in term.aliases)
        if not matched_alias:
            reasons.append(('alias_unlinked', f'输入中的别名未关联到 {expected}'))
        elif not conflicts:
            reasons.append(('context_filtered', '别名存在，但当前句子语境或词边界不适用'))
    if conflicts:
        reasons.append(('ambiguous', '别名有歧义：' + '；'.join(
            dict.fromkeys(f'{item.key}：{item.reason}' for item in conflicts))))
    for item in getattr(actual, 'skipped', ()):
        reason = item.reason
        if reason in {'alias_context_topic_conflict', 'alias_domain_conflict'}:
            reasons.append(('context_filtered', f"别名 {item.source} 未替换：" +
                ('当前句子在讨论动画/影视等普通话题' if reason == 'alias_context_topic_conflict' else '当前明确领域不适用该别名')))
    if task_snapshot is not None and task_snapshot.digest != enabled.digest:
        reasons.append(('snapshot_changed', '已有任务使用的冻结快照不同；新任务将读取当前版本，已有任务不会静默改写'))
    candidates = []
    if not actual.hits:
        from .terminology_retrieval import retrieve_candidates
        candidates = retrieve_candidates(enabled, [SimpleNamespace(
            segment_id=0, text=text, moss_text='', firered_text='', qwen_asr_text='',
            firered_llm_text='', alternate_text='')])
        if candidates:
            reasons.append(('review_candidates', '只有待复核候选；近音/拼写相似不直接替换：' +
                '、'.join(row['canonical'] for row in candidates[:5])))
        elif not expected and not reasons:
            reasons.append(('no_candidate', '输入没有已关联别名或可召回词条；可指定期望规范词检查缺项'))
    return {'input': text, 'preview': preview, 'actual': actual, 'reasons': reasons,
            'browsed': browsed.summary(), 'enabled': enabled.summary(),
            'candidate_count': len(candidates)}


def diagnostic_text(result):
    def versions(summary):
        return '、'.join(f"{row['name']} · revision {row['revision']}"
                        for row in summary['libraries']) or '无'
    actual, preview = result['actual'], result['preview']
    rows = [f"本批实际词库：{versions(result['enabled'])}",
            f"本批结果：{actual.text}（替换 {len(actual.hits)} 处）"]
    if actual.hits:
        rows.append('实际匹配：' + '；'.join(f'{hit.source} → {hit.canonical}' for hit in actual.hits))
    if result['browsed']['snapshot_digest'] == result['enabled']['snapshot_digest']:
        rows.append('当前浏览与本批为同一词库快照，预览和实际替换一致。')
    else:
        rows.extend([f"当前浏览预览：{versions(result['browsed'])}",
                     f"{preview.text}（替换 {len(preview.hits)} 处；预览不代表本批启用）"])
    rows.extend(f'原因：{message}' for _code, message in result['reasons'])
    return '\n'.join(rows)
