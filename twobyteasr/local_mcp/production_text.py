"""Independent Studio text actions exposed by the local MCP bridge."""
from __future__ import annotations

import copy
from dataclasses import asdict

from .mcp_bridge import BridgeError


def _cues(project, cue_ids):
    cues = {str(c.id): c for c in project.cues}
    if cue_ids is None:
        return list(project.cues)
    if (not isinstance(cue_ids, list) or not cue_ids or
            any(not isinstance(i, str) or not i for i in cue_ids) or
            len(set(cue_ids)) != len(cue_ids)):
        raise BridgeError('bad_params', 'cue_ids 必须是不重复的字幕 ID 列表，或省略以选择全部。')
    if not set(cue_ids) <= cues.keys():
        raise BridgeError('unknown_cue', '字幕 ID 不属于当前工程。')
    return [cues[i] for i in cue_ids]


def _locked(page, project, cue):
    from ..studio.studio_text_tools import cue_locked
    from ..timeline.studio_caption_timeline import locked_caption_speakers
    return (cue_locked(cue, (project.studio_state or {}).get('locked_cue_ids', ())) or
            cue.speaker_id in locked_caption_speakers(project, page))


def _error_category(message):
    value = str(message).lower()
    if any(x in value for x in ('401', '403', 'unauthorized', 'authentication', 'invalid api key')):
        return 'authentication_failed'
    if any(x in value for x in ('429', 'rate limit', 'too many requests')):
        return 'rate_limited'
    if any(x in value for x in ('quota', 'insufficient balance', '余额')):
        return 'quota_exhausted'
    if any(x in value for x in ('timeout', 'timed out', '超时')):
        return 'timeout'
    if any(x in value for x in ('json', 'parse', 'format', '格式')):
        return 'invalid_response'
    return 'provider_error'


def _settings(stage):
    from ..storage.settings import load_runtime_settings
    from ..providers.llm_config import text_ai_key_missing, effective_ai_identity
    loaded = load_runtime_settings()
    settings = loaded[0] if isinstance(loaded, tuple) else loaded
    if text_ai_key_missing(settings, stage):
        raise BridgeError('configuration_required', '请在软件的 AI 服务设置中配置文字服务和 API 密钥。')
    try:
        identity = effective_ai_identity(settings, stage)
    except (ValueError, KeyError, TypeError) as exc:
        raise BridgeError('configuration_required', '请在软件的 AI 服务设置中检查服务和模型配置。') from exc
    if not identity.get('provider') or not identity.get('model'):
        raise BridgeError('configuration_required', '请在软件的 AI 服务设置中选择文字服务和模型。')
    return settings


def _glossary(project, library_ids):
    from ..glossary.terminology import GlossarySnapshot, snapshot_glossaries
    ids = list(project.glossary_ids or ()) if library_ids is None else library_ids
    if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise BridgeError('bad_params', 'library_ids 必须是不重复的词库 ID 列表。')
    if not ids:
        return GlossarySnapshot()
    import subtitle_core as legacy
    legacy.load_learned_term_payload(strict=True)
    snapshot = snapshot_glossaries(legacy, ids)
    if any(not lib.found for lib in snapshot.libraries):
        raise BridgeError('unknown_library', '所选词库不存在。')
    return snapshot


def _protected(snapshot, project):
    terms = {s for lib in snapshot.libraries for term in lib.terms
             for s in (term.canonical, *term.aliases) if s}
    from ..subtitle_rules.chinese_script import convert_text, glossary_script
    script = glossary_script(project)
    if script:
        terms |= {convert_text(s, script) for s in terms}
    return tuple(sorted(terms))


def _changes(project, hits):
    from ..studio.studio_text_tools import occurrence_conflicts, values_from_occurrences
    chosen = [hit for hit in hits if hit.default_selected and hit.source in ('stutter', 'local_confirmed', 'ai_accepted')]
    values = {}
    for cue in project.cues:
        selected = [h for h in chosen if h.cue_id == cue.id]
        if not selected or occurrence_conflicts(selected):
            continue
        after = values_from_occurrences(project, selected).get(cue.id)
        if after and after.strip() and after != cue.text:
            values[cue.id] = {'before': cue.text, 'after': after}
    return values


def _glossary_changes(project, snapshot, hits):
    import subtitle_core as legacy
    from ..glossary.glossary_proofread import TermIndex, _issue, issue_groups, rewrite_text
    from ..studio.studio_text_tools import occurrence_conflicts
    from ..subtitle_rules.chinese_script import glossary_script
    terms = TermIndex.from_snapshot(snapshot, legacy, script=glossary_script(project))
    kinds = {'local_confirmed': 'term', 'local_review': 'near', 'ai_accepted': 'ai',
             'ai_review': 'ai_review', 'stutter': 'stutter', 'merge_suspect': 'merge'}
    by_cue = {}
    for hit in hits:
        issue = _issue(kinds.get(hit.source, 'ai_review'), hit.span, hit.original, hit.replacement,
                       checked=False, reason=hit.reason, hit=hit, evidence=hit.evidence)
        issue['default'] = bool(hit.default_selected)
        by_cue.setdefault(hit.cue_id, []).append(issue)
    changes = {}
    for cue in project.cues:
        issues = by_cue.get(cue.id, [])
        selected = []
        for group in issue_groups({'cue_id': cue.id, 'base': cue.text, 'issues': issues}, terms):
            members = [issues[i] for i in group['parts']]
            if (not group['options'] and not group['pending'] and
                    all(x['default'] and x['kind'] in {'term', 'ai', 'stutter'} for x in members)):
                selected.extend(members)
        if occurrence_conflicts([x['hit'] for x in selected]):
            continue
        after = rewrite_text(cue.text, selected, adopted=True)
        if after.strip() and after != cue.text:
            changes[cue.id] = {'before': cue.text, 'after': after}
    return changes


class TextOperations:
    def _text_snapshot_fresh(self, snapshot):
        try:
            self.check_snapshot(snapshot)
            return True
        except BridgeError:
            return False

    def _text_apply(self, project_id, revision, kind, job_id):
        page, project = self.require_project(project_id, revision)
        if kind == 'glossary_proofread':
            self.bridge._require_glossary()
        job = self.get_owned_job(job_id, kind=kind)
        payload = self.job_payloads.get(job_id)
        if not payload or job.get('status') != 'completed' or payload.get('applied'):
            raise BridgeError('job_not_ready', '该任务没有可采用的结果，或结果已采用。')
        self.check_snapshot(payload['snapshot'])
        if payload.get('applicable') is False:
            raise BridgeError('job_not_ready', '原生 AI 没有成功完成可采用的结果。')
        if 'glossary_digest' in payload:
            if payload['library_ids']:
                self.bridge._require_glossary()
            if _glossary(project, payload['library_ids']).digest != payload['glossary_digest']:
                raise BridgeError('stale', '词库已改变，请重新生成建议。')
        if kind == 'sentence_refine':
            from ..subtitle_rules.sentence_refine import build_replacement_cues
            from ..timeline.studio_commands import SpliceCuesCommand
            outcome = payload['outcome']
            if outcome.llm_status not in ('completed', 'partial'):
                raise BridgeError('job_not_ready', '断句未成功，原字幕已保留。')
            actions = {a.cue_id: a for a in outcome.actions}
            used = {c.id for c in project.cues}
            replacements, skipped = [], []
            for i, cue in enumerate(project.cues):
                action = actions.get(cue.id)
                if action is None:
                    continue
                if _locked(page, project, cue):
                    raise BridgeError('stale', '字幕或轨道已锁定，请重新生成建议。')
                replacement = build_replacement_cues(cue, action, project=project, used_ids=used)
                if replacement:
                    replacements.append((i, replacement))
                elif action.action != 'keep':
                    skipped.append(cue.id)
            if replacements:
                page.undo_stack.beginMacro('AI 断句优化')
                try:
                    for i, replacement in reversed(replacements):
                        page.undo_stack.push(SpliceCuesCommand(project, i, 1, replacement, 'AI 断句', page._changed))
                finally:
                    page.undo_stack.endMacro()
            result = {'changed_cues': len(replacements), 'skipped_cue_ids': skipped,
                      'failed_cue_ids': list(outcome.failed_cue_ids)}
        else:
            from ..timeline.studio_commands import BatchReplaceTextCommand, MutationOrigin
            changes = payload['changes']
            by_id = {c.id: c for c in project.cues}
            for cid, change in changes.items():
                cue = by_id.get(cid)
                if cue is None or cue.text != change['before'] or _locked(page, project, cue):
                    raise BridgeError('stale', '字幕原文或锁定状态已改变，请重新生成建议。')
            if changes:
                page.undo_stack.push(BatchReplaceTextCommand(project, {k: v['after'] for k,v in changes.items()},
                    needle='MCP 字幕整理', changed=getattr(page, '_changed', None), origin=MutationOrigin.LLM,
                    glossary_ids=list(project.glossary_ids or ()),
                    review_receipt={'kind': kind, 'audio_video_changed': False}))
            result = {'changed_cues': len(changes), 'audio_video_changed': False}
        payload['applied'] = True
        return result

    def op_start_glossary_proofread(self, project_id: str, revision: int, cue_ids=None, library_ids=None,
                                 action: str = 'preview', job_id: str = ''):
        if action == 'apply':
            if cue_ids is not None or library_ids is not None or not job_id:
                raise BridgeError('bad_params', '采用结果时只提供 job_id。')
            return self._text_apply(project_id, revision, 'glossary_proofread', job_id)
        if action != 'preview' or job_id:
            raise BridgeError('bad_params', 'action 必须为 preview，或指定 job_id 采用已有结果。')
        self.bridge._require_glossary()
        page, project = self.require_project(project_id, revision)
        cues = [c for c in _cues(project, cue_ids) if not _locked(page, project, c)]
        if not cues:
            raise BridgeError('no_cues', '所选范围没有可编辑字幕。')
        snapshot = self.snapshot(page, project)
        frozen = copy.deepcopy(project)
        glossary = _glossary(project, library_ids)
        settings = _settings('polish')
        ids = [c.id for c in cues]
        def work(token, progress):
            from ..glossary.studio_glossary_service import preview_glossary_correction
            return preview_glossary_correction(frozen, ids, glossary, settings, cancel_token=token,
                                               progress=lambda done, total: progress({'done': done, 'total': total}))
        def complete(preview, job):
            changes = _glossary_changes(frozen, glossary, preview.hits)
            receipt = preview.receipt
            self.job_payloads[job['job_id']] = {'snapshot': snapshot, 'changes': changes, 'applied': False,
                'applicable': bool(receipt.get('successful_cues')),
                'library_ids': [lib.id for lib in glossary.libraries], 'glossary_digest': glossary.digest}
            failures = bool(receipt.get('request_errors') or receipt.get('fallback_cues') or receipt.get('failed_cues'))
            successes = int(receipt.get('successful_cues') or 0)
            return {'changes': changes, 'suggestion_count': len(preview.hits), 'reviewed_cue_ids': ids,
                'api_status': ('partial' if successes else 'failed') if failures else 'completed',
                'api_completed': not failures, 'applicable': bool(changes) and bool(successes),
                'no_change': not failures and not changes,
                'successful_cues': receipt.get('successful_cues'), 'fallback_cues': receipt.get('fallback_cues'),
                'failed_cues': [row.get('cue_id') for row in receipt.get('failed_cues', ())],
                'request_error_count': len(receipt.get('request_errors', ())),
                'error_categories': sorted({_error_category(x) for x in receipt.get('request_errors', ())}),
                'snapshot_fresh': self._text_snapshot_fresh(snapshot)}
        return self.run_job('glossary_proofread', snapshot, work, apply=complete, check_before_apply=False,
                            summarize_cancelled=complete)

    def op_start_sentence_refine(self, project_id: str, revision: int, cue_ids=None,
                              action: str = 'preview', job_id: str = ''):
        if action == 'apply':
            if cue_ids is not None or not job_id:
                raise BridgeError('bad_params', '采用结果时只提供 job_id。')
            return self._text_apply(project_id, revision, 'sentence_refine', job_id)
        if action != 'preview' or job_id:
            raise BridgeError('bad_params', 'action 必须为 preview，或指定 job_id 采用已有结果。')
        page, project = self.require_project(project_id, revision)
        cues = [c for c in _cues(project, cue_ids) if not _locked(page, project, c)]
        if not cues:
            raise BridgeError('no_cues', '所选范围没有可编辑字幕。')
        snapshot = self.snapshot(page, project)
        frozen, cues = copy.deepcopy(project), copy.deepcopy(cues)
        settings = _settings('group')
        def work(token, progress):
            from ..subtitle_rules.sentence_refine import refine_cues_with_llm
            return refine_cues_with_llm(cues, project=frozen, runtime_settings=settings,
                                        cancel_check=lambda: token.is_cancelled, operation_kind='group')
        def complete(outcome, job):
            self.job_payloads[job['job_id']] = {'snapshot': snapshot, 'outcome': outcome, 'applied': False}
            return {'status': outcome.llm_status, 'api_status': outcome.llm_status,
                    'api_completed': outcome.llm_status == 'completed',
                    'applicable': outcome.llm_status in ('completed', 'partial') and any(a.action != 'keep' for a in outcome.actions),
                    'no_change': outcome.llm_status == 'completed' and all(a.action == 'keep' for a in outcome.actions), 'actions': [asdict(a) for a in outcome.actions],
                    'rejected': outcome.rejected, 'failed_cue_ids': list(outcome.failed_cue_ids),
                    'request_count': None if outcome.llm_status == 'cancelled' else len(outcome.requests),
                    'recorded_request_count': len(outcome.requests),
                    'error_category': _error_category(outcome.llm_error) if outcome.llm_error else None, 'snapshot_fresh': self._text_snapshot_fresh(snapshot)}
        return self.run_job('sentence_refine', snapshot, work, apply=complete, check_before_apply=False,
                            summarize_cancelled=complete)

    def op_cleanup_stutter(self, project_id: str, revision: int, cue_ids=None,
                        action: str = 'preview', job_id: str = ''):
        if action == 'apply':
            if cue_ids is not None or not job_id:
                raise BridgeError('bad_params', '采用结果时只提供 job_id。')
            return self._text_apply(project_id, revision, 'stutter_cleanup', job_id)
        if action != 'preview' or job_id:
            raise BridgeError('bad_params', 'action 必须为 preview，或指定 job_id 采用已有结果。')
        page, project = self.require_project(project_id, revision)
        if project.glossary_ids:
            self.bridge._require_glossary()
        cues = [c for c in _cues(project, cue_ids) if not _locked(page, project, c)]
        snapshot = self.snapshot(page, project)
        frozen, ids = copy.deepcopy(project), [c.id for c in cues]
        glossary = _glossary(project, None)
        protected = _protected(glossary, project)
        def work(token, progress):
            from ..subtitle_rules.stutter_cleanup import stutter_occurrences
            hits = []
            for cue in frozen.cues:
                token.raise_if_cancelled()
                if cue.id in ids:
                    hits.extend(stutter_occurrences(frozen, cue, protected))
            return hits
        def complete(hits, job):
            changes = _changes(frozen, hits)
            self.job_payloads[job['job_id']] = {'snapshot': snapshot, 'changes': changes, 'applied': False,
                'library_ids': [lib.id for lib in glossary.libraries], 'glossary_digest': glossary.digest}
            return {'changes': changes, 'suggestion_count': len(hits), 'audio_video_changed': False,
                    'snapshot_fresh': self._text_snapshot_fresh(snapshot)}
        return self.run_job('stutter_cleanup', snapshot, work, apply=complete, check_before_apply=False,
                            summarize_cancelled=complete)

    def op_get_review_summary(self, project_id: str, revision: int):
        import hashlib
        import json
        page, project = self.require_project(project_id, revision, permission=None, idle=False)
        identity = self.snapshot(page, project)
        identity.update(unsaved=not page.undo_stack.isClean(), source='native_glossary_workspace')
        review = getattr(self.window, 'glossary_proofread_page', None)
        if review is None:
            # A completed independent review remains useful without opening a page.
            candidates = [j for j in self.jobs.values()
                if j.get('kind') == 'glossary_proofread' and j.get('status') == 'completed'
                and j.get('project_id') == identity['project_id']
                and j.get('project_fingerprint') == identity['project_fingerprint']
                and j.get('project_path') == identity['project_path']]
            if candidates:
                job = max(candidates, key=lambda item: item.get('created_at', 0))
                result = job.get('result') or {}
                return {**identity, 'source': 'mcp_glossary_proofread_job', 'status': 'preview_ready',
                    'job_id': job['job_id'], 'counts': None,
                    'suggestion_count': result.get('suggestion_count'),
                    'reviewed_cue_ids': result.get('reviewed_cue_ids'),
                    'api_status': result.get('api_status'), 'api_completed': result.get('api_completed')}
            return {**identity, 'status': 'not_opened', 'counts': None}
        live, owner = review._live_project()
        from pathlib import Path
        current_path = getattr(page.session, 'project_path', None)
        bound_path = getattr(review, '_project_path', None)
        if (live is not project or owner is not page or not current_path or not bound_path or
                Path(bound_path).resolve() != Path(current_path).resolve()):
            return {**identity, 'status': 'not_opened', 'counts': None}
        if getattr(getattr(review, 'list', None), '_editing', ''):
            return {**identity, 'status': 'editing', 'counts': None}
        if review.checks_running() or getattr(review, '_rematch_ids', None):
            return {**identity, 'status': 'checking', 'counts': None}
        if not self.bridge.settings.get('allow_glossary', False):
            return {**identity, 'status': 'permission_limited', 'counts': None,
                    'note': '未允许查看词库，词库相关复核摘要不可用。'}
        rows = copy.deepcopy(review._rows)
        if {row['cue_id']: row['base'] for row in rows} != {cue.id: cue.text for cue in project.cues}:
            return {**identity, 'status': 'stale', 'counts': None}
        selected = list(review._selected_ids())
        glossary = getattr(review, '_snapshot', None)
        if glossary is None:
            return {**identity, 'status': 'not_ready', 'counts': None}
        if _glossary(project, selected).digest != glossary.digest:
            return {**identity, 'status': 'stale', 'counts': None}
        groups = [group for row in rows for group in review._groups(row)]
        # Native _row_state marks retained suggestions; work on detached rows only.
        states = [review._row_state(row) for row in rows]
        counts = {'captions': len(rows), 'proposals': len(groups),
            'adopted': sum(g['state'] == 'adopted' for g in groups),
            'remaining_proposals': sum(g['state'] != 'adopted' and not g['reviewed'] for g in groups),
            'suggested_captions': sum(bool(s[0]) for s in states),
            'pending_captions': sum(bool(s[1]) for s in states),
            'suspects': sum(i['kind'] == 'suspect' and not i['stale'] for row in rows for i in row['issues'])}
        bound = {'project_id': project_id, 'project_fingerprint': identity['project_fingerprint'],
                 'counts': counts, 'library_ids': selected, 'glossary_digest': glossary.digest}
        signature = hashlib.sha256(json.dumps(bound, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {**identity, 'status': 'ready', 'counts': counts, 'library_ids': selected,
                'glossary_digest': glossary.digest, 'signature': signature,
                'count_scope': 'all_captions_not_current_search_filter'}
