"""Off-GUI planning preserves language geometry, one undo and stale-result safety."""
from copy import deepcopy
import threading
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.caption_style.scoped_transform import transform_plan
from twobyteasr.caption_style.bulk_transform_preparation import prepare_plan, prepare_command


@pytest.mark.parametrize('language,fields', [('original',{'position_x':980.,'position_y':900.}),
    ('translation',{'position_y':880.}),('linked',{'position_x':1030.})])
def test_position_fast_path_matches_glyph_planner_with_independent_layer_offsets(monkeypatch,language,fields):
    import twobyteasr.caption_style.scoped_transform as planner
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',0,2000,"l'altro è già qui"),StudioCue('b',2000,5000,'同时间不同语言')],
        generation_metadata={'translations':{'a':'对应译文'}},studio_state={'bilingual':{'mode':'bilingual','layout':'ink_v1','order':'translation_first'}})
    p.cues[0].transform={'position_x':700.,'language_layers':{'original':{'position_x':820.},'translation':{'position_x':930.,'position_y':720.}}}
    quick=planner.position_only_plan
    actual=planner.transform_plan(p,['a','b'],language,fields)
    monkeypatch.setattr(planner,'position_only_plan',lambda *args,**kwargs:None)
    assert actual==planner.transform_plan(p,['a','b'],language,fields)
    # Group transforms and non-outer anchors keep their measured fallback.
    p.studio_state['caption_group_transform']={'dx':12.,'dy':8.,'sx':1.15,'sy':1.}
    expected=planner.transform_plan(p,['a','b'],language,fields)
    monkeypatch.setattr(planner,'position_only_plan',quick)
    assert planner.transform_plan(p,['a','b'],language,fields)==expected


@pytest.mark.parametrize('language', ['original', 'translation', 'linked'])
@pytest.mark.parametrize('mode', ['absolute', 'delta', 'ratio'])
@pytest.mark.parametrize('fields', [{'position_x':980., 'position_y':920.}, {'scale_x':135.}, {'rotation':12.}])
def test_detached_plan_equals_existing_layer_transaction(language, mode, fields):
    app = QApplication.instance() or QApplication([])
    p = SubtitleProject(media=StudioMedia(''), cues=[StudioCue(str(i), i*500, i*500+900,
        f'Una frase numero {i}') for i in range(5)],
        generation_metadata={'translations': {str(i): f'第{i}条译文' for i in range(4)},
                             'recognition_result': {'unrelated': [1]*10000}},
        studio_state={'bilingual': {'mode':'bilingual','layout':'ink_v1'}, 'playhead_ms': 400})
    p.cues[1].transform = {'position_x':740., 'language_layers': {'translation': {'position_y':800.,'scale_x':110.}}}
    p.cues[2].appearance_override = {'original': {'font_size':47.}, 'translation': {'style': {'font_size':60.}}}
    p.validate()
    before = deepcopy(p.to_dict())
    ids = ['0','1','2','4']
    expected = transform_plan(p,ids,language,fields,reference_id='1',mode=mode)
    actual = prepare_plan(StudioRevisionStore(p).render,ids,language,fields,reference_id='1',mode=mode)
    assert actual == expected
    assert p.to_dict() == before


def test_progress_keeps_gui_alive_and_publishes_one_undo(tmp_path, monkeypatch):
    from tests.test_motion_workflow_ui import make_page, close
    import twobyteasr.caption_style.bulk_transform_preparation as bulk
    app, page = make_page(tmp_path)
    main_thread = threading.get_ident()
    called = []
    original = bulk.prepare_plan
    released = threading.Event()
    def slow(*args, **kwargs):
        called.append(threading.get_ident())
        assert released.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(bulk,'prepare_plan',slow)
    QTimer.singleShot(80, released.set)
    try:
        before = deepcopy(page.project.cues[0].transform)
        command = prepare_command(page,['a','b'],'linked',{'rotation':8.},reference_id='a')
        assert called and called[0] != main_thread and released.is_set()
        assert command is not None and page.undo_stack.count()==0
        page.undo_stack.push(command)
        assert page.undo_stack.count()==1
        page.undo_stack.undo()
        assert page.project.cues[0].transform == before
        assert not page._bulk_transform_busy
    finally:
        close(page)


def test_independent_captions_keep_authoring_ids_when_source_ass_is_empty():
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    app = QApplication.instance() or QApplication([])
    p = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('a',0,1000,'原文')],
        generation_metadata={'translations':{'a':'Traduzione'}},
        studio_state={'bilingual':{'mode':'bilingual','layout':'ink_v1'}})
    ensure_independent_captions(p)
    store = StudioRevisionStore(p)
    assert store.render.cues == ()
    revision = store.authoring_render()
    assert [c.id for c in revision.cues] == ['a'] and revision.timeline_cues is None
    assert prepare_plan(revision,['a'],'linked',{'position_x':900.},reference_id='a') == transform_plan(
        p,['a'],'linked',{'position_x':900.},reference_id='a')


@pytest.mark.parametrize('replace_project', [False, True])
def test_large_exact_position_paints_before_commit_without_full_snapshot(tmp_path, monkeypatch, replace_project):
    from PySide6.QtCore import QObject, QEvent
    from tests.test_motion_workflow_ui import make_page, close
    import twobyteasr.caption_style.bulk_transform_preparation as bulk
    app, page = make_page(tmp_path)
    initial = page.project
    before = deepcopy(initial.cues[0].transform)
    monkeypatch.setattr(bulk, 'BULK_THRESHOLD', 1)
    def unnecessary(*args, **kwargs):
        pytest.fail('exact position must not build a full snapshot or measure text')
    monkeypatch.setattr(StudioRevisionStore, 'authoring_render', unnecessary)
    monkeypatch.setattr(bulk, 'prepare_plan', unnecessary)
    painted = []
    class ObserveProgress(QObject):
        def eventFilter(self, watched, event):
            if watched.objectName() == 'studioBulkTransformProgress' and event.type() == QEvent.Paint:
                painted.append(True)
                assert initial.cues[0].transform == before and page.undo_stack.count() == 0
                if replace_project:
                    page.project = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('new', 0, 1000, '新工程')])
            return False
    observer = ObserveProgress()
    app.installEventFilter(observer)
    try:
        command = prepare_command(page, ['a', 'b'], 'original', {'position_x': 980.})
        assert painted and not page._bulk_transform_busy
        if replace_project:
            assert command is None and page.project.cues[0].id == 'new'
            assert initial.cues[0].transform == before
        else:
            assert command is not None and page.undo_stack.count() == 0
            page.undo_stack.push(command)
            assert page.undo_stack.count() == 1
            page.undo_stack.undo()
            assert initial.cues[0].transform == before
    finally:
        app.removeEventFilter(observer)
        close(page)


def test_changed_project_rejects_worker_result(tmp_path, monkeypatch):
    from tests.test_motion_workflow_ui import make_page, close
    import twobyteasr.caption_style.bulk_transform_preparation as bulk
    app, page = make_page(tmp_path)
    initial = page.project
    released = threading.Event()
    original = bulk.prepare_plan
    def slow(*args, **kwargs):
        assert released.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(bulk,'prepare_plan',slow)
    def replace_project():
        page.project = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('new',0,1000,'新工程')])
        released.set()
    QTimer.singleShot(80, replace_project)
    try:
        command = prepare_command(page,['a'],'original',{'font_size':61.},reference_id='a')
        assert command is None
        assert page.project.cues[0].id == 'new' and not page.project.cues[0].transform
        assert page.undo_stack.count()==0 and initial.cues[0].transform == {}
    finally:
        close(page)
