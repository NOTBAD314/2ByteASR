"""Loading identity and one surface survive construction, cancellation and retry."""
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.studio.studio_loading import StudioLoadingSession

APP = QApplication.instance() or QApplication([])


def test_one_card_survives_construction_and_hydration(tmp_path):
    host = QWidget()
    host.resize(1000, 800)
    host.show()
    session = StudioLoadingSession(host)
    session.begin(str(tmp_path / 'first.2byteproj'))
    APP.processEvents()
    card, geometry, epoch = session.view.card, session.view.card.geometry(), session.generation
    session.mark('创建工作台界面')
    session.stage('读取工程')
    session.mark('读取工程')
    session.stage('恢复工作区')
    APP.processEvents()
    assert session.view.card is card
    assert session.view.card.geometry() == geometry
    assert session.generation == epoch
    assert session.completed == {'创建工作台界面', '读取工程'}
    host.close()


def test_only_latest_request_can_deliver_and_delivers_once(tmp_path):
    host = QWidget()
    session = StudioLoadingSession(host)
    a = session.begin(str(tmp_path / 'a.2byteproj'))
    b = session.begin(str(tmp_path / 'b.2byteproj'))
    assert not session.deliver(a)
    assert session.active and session.path.endswith('b.2byteproj')
    assert session.deliver(b)
    assert not session.deliver(b)
    assert session.deliveries == 1
    host.close()


def test_cancel_rejects_late_delivery_and_retry(tmp_path):
    host = QWidget()
    session = StudioLoadingSession(host)
    called = []
    epoch = session.begin(str(tmp_path / 'a.2byteproj'), on_retry=lambda: called.append('retry'))
    session.abort()
    assert not session.deliver(epoch)
    session.request_retry()
    assert not called and not session.view.isVisible()
    host.close()


def test_failure_keeps_card_and_requires_explicit_retry(tmp_path):
    host = QWidget()
    host.show()
    session = StudioLoadingSession(host)
    retried = []
    epoch = session.begin(str(tmp_path / 'a.2byteproj'), on_retry=lambda: retried.append(True))
    card = session.view.card
    session.mark('创建工作台界面')
    session.fail('读取工程', 'missing fixture')
    assert session.view.card is card and session.view.isVisible()
    assert session.view.steps_view.failed == '读取工程'
    assert not session.deliver(epoch) and session.view.retry.isVisible()
    assert 'missing fixture' in session.view.label.text()
    session.request_retry()
    assert retried == [True]
    host.close()


def test_hidden_workspace_uses_explicit_loading_session(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    from twobyteasr.studio import studio_readiness
    host = QWidget()
    page = QWidget(host)
    session = host._studio_loading_session = StudioLoadingSession(host)
    session.begin(str(tmp_path / 'a.2byteproj'))
    calls = []
    page._readiness = SimpleNamespace(begin=lambda path, **options: calls.append(path))
    controller = object.__new__(StudioProjectController)
    controller.page = page
    monkeypatch.setattr(StudioProjectController, 'open_project',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('sync load')))
    controller.open_project_entry(session.path, single_shot_fn=None)
    assert calls == [session.path]
    host.close()


def test_old_frame_or_pending_seek_is_not_first_screen_ready():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_readiness import player_surface_ready
    state = {'path': 'C:/test/a.mp4', 'time-pos': 12.0, 'video-frame-info': {'pts': 12.0}}
    clock = SimpleNamespace(exact_seek_pending=False, generation=0)
    video = SimpleNamespace(_startup_state='READY', _playback_clock=clock,
        _media_path='C:/test/a.mp4', _media_has_video=True,
        controller=SimpleNamespace(backend='qt-video-sink', source_epoch=0,
            applied_seek_state=lambda: {'generation': 0},
            surface=SimpleNamespace(frame=SimpleNamespace(isNull=lambda: False)), observed_properties=lambda: state))
    page = SimpleNamespace(video=video)
    assert player_surface_ready(page)
    state['path'] = 'C:/test/old.mp4'
    assert not player_surface_ready(page)
    state['path'] = video._media_path
    state['video-frame-info']['pts'] = 8.0
    assert not player_surface_ready(page)
    state['video-frame-info']['pts'] = 12.0
    clock.exact_seek_pending = True
    assert not player_surface_ready(page)


def test_mpv_picture_type_is_not_a_current_frame_witness():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_readiness import player_surface_ready
    state = {'path': 'C:/test/a.mp4', 'time-pos': 12.0,
             'video-frame-info': {'picture-type': 'P', 'estimated-smpte-timecode': '00:00:12:00'}}
    video = SimpleNamespace(_startup_state='READY', _media_path='C:/test/a.mp4', _media_has_video=True,
        controller=SimpleNamespace(backend='mpv', observed_properties=lambda: state))
    assert not player_surface_ready(SimpleNamespace(video=video))


def test_audio_and_gap_do_not_wait_for_video_frames():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_readiness import player_surface_ready
    state = {'path': 'C:/test/a.wav', 'time-pos': 0.0}
    video = SimpleNamespace(_startup_state='READY', _media_path='C:/test/a.wav',
        _media_has_video=False, controller=SimpleNamespace(observed_properties=lambda: state))
    assert player_surface_ready(SimpleNamespace(video=video))
    video._clock_only, video._startup_state = True, 'MEDIA_OPENING'
    assert player_surface_ready(SimpleNamespace(video=video))


def test_rejecting_dirty_open_keeps_previous_editor_and_undo(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_readiness import StudioReadiness
    host = QWidget()
    page = QWidget(host)
    session = StudioLoadingSession(host)
    session.begin(str(tmp_path / 'new.2byteproj'))
    old_project = object()
    page.project = old_project
    page.project_controller = SimpleNamespace(dirty_guard=SimpleNamespace(confirm=lambda _action: False))
    rejected = []
    host._reject_studio_loading = lambda: (rejected.append(True), session.abort())
    gate = SimpleNamespace(page=page, loading=session, active=False, ready=False, path='old', on_ready=lambda: None)
    StudioReadiness.begin(gate, tmp_path / 'new.2byteproj')
    assert page.project is old_project and rejected == [True]
    assert gate.on_ready is None and session.state == 'cancelled'
    host.close()


def test_same_file_request_joins_existing_reader(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_readiness import StudioReadiness, project_file_identity
    path = tmp_path / 'same.2byteproj'
    path.write_text('{}', encoding='utf-8')
    gate = SimpleNamespace(page=object(), active=True, path=str(path.resolve()),
                           requested_file_identity=project_file_identity(path), generation=19,
                           loading=SimpleNamespace(active=True, state='preparing', generation=19, path=str(path.resolve())))
    StudioReadiness.begin(gate, path)
    assert gate.generation == 19


def test_loading_surface_is_outside_page_stack_but_tracks_its_coverage(tmp_path):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QStackedWidget
    host = QWidget(); host.resize(1000, 800)
    pages = QStackedWidget(host); pages.setGeometry(12, 70, 976, 700)
    pages.addWidget(QWidget()); pages.addWidget(QWidget())
    session = StudioLoadingSession(host, host, coverage=pages)
    session.begin(str(tmp_path / 'a.2byteproj'))
    host.show(); APP.processEvents()
    assert session.view.parentWidget() is host
    assert pages.indexOf(session.view) == -1
    assert session.view.geometry() == QRect(pages.mapTo(host, QPoint()), pages.size())
    card = session.view.card
    pages.setCurrentIndex(1)
    pages.setGeometry(0, 0, 1000, 800); APP.processEvents()
    assert session.view.card is card and session.view.geometry() == host.rect()
    host.close()


def test_stack_loading_page_keeps_editor_hidden_until_the_owner_reveals_it(tmp_path):
    from PySide6.QtWidgets import QStackedWidget, QVBoxLayout
    host = QWidget()
    layout = QVBoxLayout(host)
    pages = QStackedWidget(host)
    layout.addWidget(pages)
    editor = QWidget()
    pages.addWidget(editor)
    session = StudioLoadingSession(pages, host, page_stack=True)
    pages.addWidget(session.view)
    session.on_reveal = lambda: pages.setCurrentWidget(editor)
    host.show()
    epoch = session.begin(str(tmp_path / 'ready.2byteproj'), present=False)
    pages.setCurrentWidget(session.view)
    session.present()
    APP.processEvents()
    assert session.view.isVisible() and not editor.isVisible()
    assert session.deliver(epoch)
    assert editor.isVisible() and not session.view.isVisible()
    assert not session.deliver(epoch) and session.deliveries == 1
    host.close()


def test_reveal_callback_cannot_retire_a_newer_request(tmp_path):
    host = QWidget()
    session = StudioLoadingSession(host)
    host.show()
    old = session.begin(str(tmp_path / 'a.2byteproj'))
    session.on_reveal = lambda: session.begin(str(tmp_path / 'b.2byteproj'))
    assert not session.deliver(old)
    assert session.active and session.path.endswith('b.2byteproj')
    assert session.view.isVisible() and session.deliveries == 0
    host.close()
