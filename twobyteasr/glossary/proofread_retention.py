"""Persist one review round separately from text edits and pending proposals."""
from copy import deepcopy
from uuid import uuid4

REVIEW_KEY = 'glossary_proofread_review'
ISSUE_FIELDS = ('kind', 'span', 'original', 'replacement', 'checked', 'default', 'reason',
                'options', 'evidence', 'lexical', 'cleanup', 'provenance', 'ignored',
                'reviewed', 'stale', 'context', 'anchor', 'proposal_id')


def review_state(project, *, create=False):
    value = (getattr(project, 'studio_state', None) or {}).get(REVIEW_KEY)
    if isinstance(value, dict) and value.get('version') == 1 and isinstance(value.get('rows'), dict):
        return value
    if not create:
        return {'version': 1, 'round_id': '', 'rows': {}}
    value = {'version': 1, 'round_id': uuid4().hex, 'rows': {}}
    project.studio_state[REVIEW_KEY] = value
    return value


def row_record(row):
    from .proofread_rules import text_version
    def plain(value):
        if isinstance(value,dict):return {key:plain(item) for key,item in value.items()}
        if isinstance(value,(list,tuple)):return [plain(item) for item in value]
        return value
    for issue in row['issues']:
        issue.setdefault('proposal_id', uuid4().hex)
    return dict(cue_id=row['cue_id'], layer='original', origin=row['origin'], base=row['base'],
                text_sha=text_version(row['base']),
                retained=bool(row.get('review_retained')), dismissed=bool(row.get('review_dismissed')),
                issues=[{key: plain(issue[key]) for key in ISSUE_FIELDS if key in issue}
                        for issue in row['issues']])


def restore_row(project, row):
    saved = review_state(project)['rows'].get(row['cue_id'])
    if not isinstance(saved, dict) or saved.get('layer') != 'original':
        return False
    row['origin'] = str(saved.get('origin', row['origin']))
    row['review_retained'] = bool(saved.get('retained'))
    row['review_dismissed'] = bool(saved.get('dismissed'))
    existing = {issue.get('proposal_id'): issue for issue in row['issues'] if issue.get('proposal_id')}
    row['issues'] = []
    for saved_issue in saved.get('issues', ()):
        if not isinstance(saved_issue, dict) or not {'kind', 'span', 'original', 'replacement'} <= saved_issue.keys():
            continue
        issue = existing.get(saved_issue.get('proposal_id'), {})
        hit = issue.get('hit')
        issue.clear()
        issue.update(checked=False, default=False, reason='', hit=hit, options=(), evidence='',
                     stale=False, reviewed=False)
        issue.update(deepcopy(saved_issue))
        for key in ('span', 'options', 'context', 'anchor'):
            if key in issue:
                issue[key] = tuple(issue[key])
        row['issues'].append(issue)
    return str(saved.get('base', row['base']))


def put_records(project, records):
    """Update only changed rows; unrelated rows and newer suggestions survive."""
    rows = review_state(project, create=True)['rows']
    for cue_id, value in records.items():
        if value is None:
            rows.pop(cue_id, None)
        else:
            rows[cue_id] = deepcopy(value)
