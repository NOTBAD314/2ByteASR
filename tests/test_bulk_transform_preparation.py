"""Off-GUI planning preserves language geometry, one undo and stale-result safety."""
from copy import deepcopy
import threading
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.caption_style.scoped_transform import transform_plan
from twobyteasr.caption_style.bulk_transform_preparation import prepare_plan, queue_command


def wait_for_result(received):
    for _ in range(250):
        if received:
            return received[0]
        QTest.qWait(20)
    pytest.fail('bulk transform did not finish')


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
        responses = []
        assert queue_command(page, ['a','b'], 'linked', {'rotation':8.}, reference_id='a',
                             completed=responses.append, inspect_geometry=True)
        assert page._bulk_transform_busy and not responses
        command = wait_for_result(responses)
        assert called and called[0] != main_thread and released.is_set()
        assert command is not None and page.undo_stack.count()==0
        page.undo_stack.push(command)
        assert page.undo_stack.count()==1
        selected = [cue for cue in page.project.cues if cue.id in {'a', 'b'}]
        assert command.inspector_summary == bulk.summarize_geometry(page.project, selected, 'linked')
        from twobyteasr.projects.studio_revisions import RenderCueDTO
        assert page._revision_store._cues == tuple(RenderCueDTO.capture(cue) for cue in page.project.cues)
        page.undo_stack.undo()
        assert page.project.cues[0].transform == before
        assert page._revision_store._cues == tuple(RenderCueDTO.capture(cue) for cue in page.project.cues)
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


def test_prepared_bulk_geometry_rolls_back_values_and_render_generation(monkeypatch):
    from twobyteasr.caption_style.bulk_transform_preparation import BulkTransformCommand
    from twobyteasr.projects.studio_project import SubtitleStyle
    from twobyteasr.projects.studio_revisions import freeze_json
    from twobyteasr.projects.studio_runtime_state import state_for

    project = SubtitleProject(media=StudioMedia(""), cues=[StudioCue("a", 0, 1000, "Caption")],
                              styles=[SubtitleStyle("default", "Default")])
    project.validate()
    cue = project.cues[0]
    initial = cue.transform
    generation = cue.appearance_generation
    state = state_for(project)
    revision = state.revision
    command = BulkTransformCommand(
        project, {"a": (freeze_json(initial), freeze_json({"position_x": 900.0}))}, None)

    def reject_style(_style):
        raise ValueError("unusable style")

    monkeypatch.setattr(SubtitleStyle, "validate", reject_style)
    with pytest.raises(ValueError, match="unusable style"):
        command.redo()
    assert project.cues[0] is cue and cue.transform is initial
    assert cue.appearance_generation == generation and state.revision == revision


@pytest.mark.parametrize('replace_project', [False, True])
def test_large_exact_position_paints_before_commit_and_preserves_project(tmp_path, monkeypatch, replace_project):
    from PySide6.QtCore import QObject, QEvent
    from tests.test_motion_workflow_ui import make_page, close
    import twobyteasr.caption_style.bulk_transform_preparation as bulk
    app, page = make_page(tmp_path)
    initial = page.project
    before = deepcopy(initial.cues[0].transform)
    monkeypatch.setattr(bulk, 'BULK_THRESHOLD', 1)
    from twobyteasr.system import resident_worker
    monkeypatch.setattr(resident_worker, 'shared_worker', lambda: None)
    painted = []
    paint_ready = threading.Event()
    plan = bulk.prepare_plan

    def after_paint(*args, **kwargs):
        assert paint_ready.wait(4)
        return plan(*args, **kwargs)

    monkeypatch.setattr(bulk, 'prepare_plan', after_paint)
    class ObserveProgress(QObject):
        def eventFilter(self, watched, event):
            if watched.objectName() == 'studioBulkTransformProgress' and event.type() == QEvent.Paint:
                painted.append(True)
                assert initial.cues[0].transform == before and page.undo_stack.count() == 0
                if replace_project:
                    page.project = SubtitleProject(media=StudioMedia(''), cues=[StudioCue('new', 0, 1000, '新工程')])
                paint_ready.set()
            return False
    observer = ObserveProgress()
    app.installEventFilter(observer)
    try:
        responses = []
        assert queue_command(page, ['a', 'b'], 'original', {'position_x': 980.}, completed=responses.append)
        assert not responses
        command = wait_for_result(responses)
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
        responses = []
        assert queue_command(page, ['a'], 'original', {'font_size':61.}, reference_id='a',
                             completed=responses.append)
        command = wait_for_result(responses)
        assert command is None
        assert page.project.cues[0].id == 'new' and not page.project.cues[0].transform
        assert page.undo_stack.count()==0 and initial.cues[0].transform == {}
    finally:
        close(page)


def test_cancelled_geometry_plan_does_not_publish(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QProgressDialog
    from tests.test_motion_workflow_ui import make_page, close
    import twobyteasr.caption_style.bulk_transform_preparation as bulk

    app, page = make_page(tmp_path)
    started = threading.Event()
    release = threading.Event()
    planner = bulk.prepare_plan

    def wait_then_plan(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return planner(*args, **kwargs)

    monkeypatch.setattr(bulk, "prepare_plan", wait_then_plan)
    received = []
    try:
        assert queue_command(page, ["a"], "original", {"rotation": 8.0}, completed=received.append)
        for _ in range(20):
            if started.is_set():
                break
            QTest.qWait(10)
        progress = page.window().findChild(QProgressDialog, "studioBulkTransformProgress")
        assert progress is not None and started.is_set()
        progress.canceled.emit()
        release.set()
        assert wait_for_result(received) is None
        assert page.undo_stack.count() == 0
    finally:
        release.set()
        close(page)


def test_apply_all_button_prepares_without_blocking(tmp_path, monkeypatch):
    from tests.test_motion_workflow_ui import make_page, close
    from twobyteasr.caption_style import bulk_transform_preparation as bulk
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
    from twobyteasr.system import resident_worker

    _app, page = make_page(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original = bulk.prepare_plan

    def prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(bulk, "BULK_THRESHOLD", 1)
    monkeypatch.setattr(bulk, "prepare_plan", prepare)
    monkeypatch.setattr(resident_worker, "shared_worker", lambda: None)
    try:
        cue = page.project.cues[0]
        page.undo_stack.push(SetCueFieldsCommand(
            page.project, cue.id, {"transform": {"position_x": 750.0}}, "Set reference position", page._changed))
        page.select_cue(cue.id)
        before = tuple(deepcopy(c.transform) for c in page.project.cues)
        stack_index = page.undo_stack.index()
        page.caption_transform_panel.apply_to_all()
        assert entered.wait(1) and page._bulk_transform_busy
        assert page.undo_stack.index() == stack_index
        release.set()
        for _ in range(100):
            if not page._bulk_transform_busy:
                break
            QTest.qWait(20)
        assert not page._bulk_transform_busy
        assert page.undo_stack.index() == stack_index + 1
        page.undo_stack.undo()
        assert tuple(c.transform for c in page.project.cues) == before
    finally:
        release.set()
        close(page)
