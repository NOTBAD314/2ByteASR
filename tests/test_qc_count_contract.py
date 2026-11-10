import os
import copy
from dataclasses import replace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain
from twobyteasr.subtitle_rules import current_issues as issues
from twobyteasr.subtitle_rules.studio_qc import (QCResult, QCIssue, QCCategory, QCSeverity,
                                               SubtitleQCEngine, ReadabilityRule)


def project():
    p = SubtitleProject(StudioMedia('', duration_ms=10000),
        cues=[StudioCue('a', 0, 1000, '短字幕'), StudioCue('b', 2000, 5000, '正常字幕')])
    p.validate()
    return p


def test_duplicate_rule_identity_stays_deduplicated_after_repeated_cold_and_warm_scans():
    p = project()
    row = QCIssue('actual_problem', QCSeverity.WARNING, QCCategory.TEXT, 'a', '问题', '原因')
    p._qc_result = QCResult({'a': (row, row, replace(row)), 'b': ()})
    for _ in range(4):
        issues.invalidate(p)
        view = issues.current_issue_view(p)
        assert view.counts() == {'priority': 1, 'critical': 0}
        assert len(view.for_cue('a')) == 1 and len(view.records) == 1
        assert issues.current_issue_view(p).records == view.records
    stats = p._qc_result.rule_statistics()[0]
    assert stats['hits'] == 3 and stats['unique_cues'] == 1


def test_worker_cache_is_bound_to_project_language_policy_and_rule_version():
    p = project()
    p._qc_result = QCResult({})
    prepared = issues.prepare_issue_cache(p)
    other = copy.deepcopy(p)
    other.project_id = 'other-project'
    assert not issues.adopt_issue_cache(other, p._qc_result, prepared)
    other.project_id = p.project_id
    other.generation_metadata['language'] = {'code': 'ja'}
    assert not issues.adopt_issue_cache(other, p._qc_result, prepared)
    assert not issues.adopt_issue_cache(p, p._qc_result, dict(prepared, version=-1))
    assert issues.adopt_issue_cache(p, p._qc_result, prepared)


def test_display_punctuation_does_not_create_hidden_readability_or_punctuation_tasks():
    p = project()
    p.cues[0].text = '短字幕！！'
    p.cues[0].end_ms = 250
    p._qc_result = SubtitleQCEngine().analyze(p)
    assert not any(row.issue_type == 'high_cps' for row in ReadabilityRule().evaluate(
        p.cues[0], SubtitleQCEngine().build_context(p)))
    view = issues.current_issue_view(p)
    assert not any(row.kind in {'abnormal_punctuation', 'duplicate_punctuation'} for row in view.for_cue('a'))
    p.studio_state['punctuation'] = {'mode': 'add'}
    # Even with the same raw QC object, the policy invalidates calibrated rows.
    assert any(row.kind == 'duplicate_punctuation' for row in issues.current_issue_view(p).for_cue('a'))


def test_style_only_transaction_keeps_qc_revision_and_content_bound_human_decisions():
    p = project()
    runtime = state_for(p)
    before = runtime.qc_revision
    with runtime.transaction(p, action_id='style', dirty=DirtyDomain.CUE_STYLE, affected_cue_ids=('a',)):
        p.cues[0].style_id = 'default'
    assert runtime.qc_revision == before
    row = QCIssue('actual_problem', QCSeverity.WARNING, QCCategory.TEXT, 'a', '问题', '原因')
    p._qc_result = QCResult({'a': (row,)})
    current = issues.current_issue_view(p).for_cue('a')[0]
    p.studio_state[issues.DECISIONS] = {current.issue_id: {'status': 'resolved', 'input_version': current.input_version}}
    issues.invalidate(p)
    assert issues.current_issue_view(p).counts() == {'priority': 0, 'critical': 0}
    p.cues[1].text = '另一条有变化'
    issues.invalidate(p, {'b'})
    assert issues.current_issue_view(p).counts() == {'priority': 0, 'critical': 0}
