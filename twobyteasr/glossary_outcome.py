"""Shared evidence-based outcomes for collection and its preview/task state."""

def resumable_checkpoint(resume,game,now=None,ttl_seconds=86400,force_refresh=False):
    """Source-scoped 24h freshness; failures never carry domain cooldowns.

    Keep candidate/history data reviewable, but expired source cursors must be
    revalidated. Changing provider does not invalidate fresh successful HTTP.
    """
    import copy,time
    from datetime import datetime
    if not isinstance(resume,dict) or str(resume.get('game','')).strip().casefold()!=str(game).strip().casefold():
        return {},dict(reason='new_task_or_game_mismatch',expired_sources=[])
    result=copy.deepcopy(resume);now=time.time() if now is None else now
    latest={str(r.get('url','')):r for r in result.get('source_results',[])}
    expired=[]
    for url in result.get('done_urls',[]):
        row=latest.get(url,{})
        try:
            stamp=row.get('fetched_at','')
            age=now-(stamp if isinstance(stamp,(int,float)) else datetime.fromisoformat(stamp).timestamp())
        except (ValueError,TypeError):age=ttl_seconds+1
        if force_refresh or not row.get('read') or not 0<=age<=ttl_seconds:expired.append(url)
    result['done_urls']=[url for url in result.get('done_urls',[]) if url not in expired]
    for url in expired:result.get('category_cursors',{}).pop(url,None)
    stale_evidence=set(expired)|{latest[url].get('evidence_url') for url in expired if url in latest}
    for candidate in result.get('candidates',[]):
        if any(s.get('url') in stale_evidence for s in candidate.get('sources',[])):
            candidate['verification']='sourced'
    # Do not report obsolete successful receipts as currently verified.
    for row in result.get('source_results',[]):
        if row.get('url') in expired:row.update(read=False,error='refresh_required' if force_refresh else 'cache_expired_revalidation_required')
    return result,dict(reason='resume',expired_sources=expired,success_ttl_seconds=ttl_seconds,
        force_refresh=force_refresh,failure_cooldown='task-local; not reused by a new run')

def collection_outcome(candidates, sources, pending=(), *, changed=True):
    # A URL or HTTP 200 alone is not a verified catalogue. Empty, successfully
    # parsed catalogues are valid only when enumeration explicitly completed.
    latest = {str(row.get('url', '')): row for row in sources}
    valid = [row for row in latest.values() if row.get('read') and
             (row.get('catalog_member_count', 0) or row.get('enumeration_complete'))]
    failed = [row for row in latest.values() if row.get('error') or not row.get('read')]
    # Resource keys and names have different denominators: several language
    # keys (or sources) can describe the same glossary name.
    source_entries = sum(int(row.get('catalog_member_count', 0)) for row in valid)
    def field(term, name):
        return term.get(name, '') if isinstance(term, dict) else getattr(term, name, '')
    verified = len({str(field(term, 'term')).strip().casefold() for term in candidates
                    if field(term, 'verification') in {'catalog_verified', 'page_verified'}
                    and str(field(term, 'term')).strip()}) if valid else 0
    remaining = bool(pending or failed)
    if candidates and valid:
        status = 'partial' if remaining else ('new_candidates' if changed else 'no_changes')
    elif valid:
        status = 'partial' if remaining else 'no_changes'
    elif any(any(word in str(row.get('error', '')) for word in
                 ('blocked', 'throttled', 'cooldown', '403', '429')) for row in failed):
        status = 'blocked'
    elif failed:
        status = 'failed'
    else:
        status = 'no_verified_content'
    labels = {
        'new_candidates': '已取得可核对候选；仅覆盖本次来源范围',
        'no_changes': '本次成功核对的来源范围内没有新增；不代表全游戏已覆盖',
        'partial': '部分来源已核对，仍有未完成来源，可继续补齐',
        'blocked': '来源访问受阻，未取得可核对内容；可查看原因后继续',
        'failed': '来源请求或解析失败，未取得可核对内容',
        'no_verified_content': '未获得可核对内容，不能判断现有词库是否覆盖',
    }
    return dict(status=status, message=labels[status], verified_names=verified,
                verified_source_entries=source_entries,
                verified_sources=len(valid), failed_sources=len(failed),
                scope='本次成功解析的明确来源；全游戏分母未知')


def empty_result_message(result):
    outcome = result.get('outcome') or {}
    if outcome.get('message'):
        return outcome['message']
    # Historical empty results did not retain sufficient proof of coverage.
    return '未获得可添加的已核对候选；请查看来源回执，不能据此判断现有词库已覆盖。'
