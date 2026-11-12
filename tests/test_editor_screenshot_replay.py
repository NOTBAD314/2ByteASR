"""Opt-in local replay. Project contents stay outside the repository test files.

Set TWOBYTEASR_SCREENSHOT_PROJECT to your own read-only input or a local tmp
copy. No project data is copied, serialized or committed by this module.
"""
from pathlib import Path
from hashlib import sha256
import os
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope='module')
def project():
    value=os.environ.get('TWOBYTEASR_SCREENSHOT_PROJECT')
    if not value:pytest.skip('Provide a local screenshot project path explicitly')
    path=Path(value);before=sha256(path.read_bytes()).hexdigest()
    app=QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.projects.project_open_preparation import prepare
    p=load_project(path);prepare(p)
    yield p
    assert sha256(path.read_bytes()).hexdigest()==before


def cue_for(project,text):
    return next(c for c in project.cues if c.text.replace('\n','').replace(' ','')==text)


def suggestions(project,cue):
    from twobyteasr.subtitle_rules.studio_qc import review_candidates
    from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
    from twobyteasr.recognition.asr_source_evidence import annotate_suggestions
    candidates=review_candidates(project,cue)
    return annotate_suggestions(project,cue,review_suggestions(cue.text,[(c.text,c.sources) for c in candidates[1:] if not c.context_only],pronouns=False))


@pytest.mark.parametrize('text',['怎么说上罗隐','对对对','他这里会打打雪仗我们走吧','第一个连水友可以吧','好好好','行行行行','可以试试'])
def test_quoted_screenshot_problem_does_not_offer_projected_or_cross_speaker_change(project,text):
    assert suggestions(project,cue_for(project,text))==()


def test_quoted_spelling_fix_remains_without_dropping_normal_prefix(project):
    cue=cue_for(project,'这里他这个炮米花算是解掉了');rows=suggestions(project,cue)
    assert [(r.original,[o.text for o in r.options]) for r in rows]==[('炮',['爆'])]


def test_quoted_blue_continuation_keeps_green_interjection_and_own_slot(project):
    from twobyteasr.subtitle_rules.display_continuity import continuity_successors
    from twobyteasr.caption_style.collision_layout import project_layout_schedule
    left=next(c for c in project.cues if c.text.endswith('把他的BUFF'))
    right=cue_for(project,'换你身上然后把');green=cue_for(project,'我们我们是99级')
    assert left.speaker_id==right.speaker_id and left.speaker_id!=green.speaker_id
    assert continuity_successors(project.cues)[left.id]==right.id
    assert left.end_ms==right.start_ms
    assert green.start_ms<right.start_ms<green.end_ms
    plan=project_layout_schedule(project)
    assert plan[left.id][0][2]==plan[right.id][0][2]


def test_normal_overlapping_replies_have_no_asr_or_repetition_check_task(project):
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.subtitle_rules.current_issues import current_issue_view,invalidate
    project._qc_result=SubtitleQCEngine().analyze(project);invalidate(project)
    view=current_issue_view(project)
    for text in ['第一个连水友可以吧','好好好','行行行行','可以试试']:
        cue=cue_for(project,text)
        assert not [r for r in view.for_cue(cue.id) if r.kind in {'model_disagreement','local_model_correction','repeated_character','overlap'}]
