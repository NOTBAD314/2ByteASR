"""Native production permission and media identity regressions, in private data."""
import time
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.local_mcp import mcp_common
from twobyteasr.local_mcp.mcp_bridge import BridgeError, McpBridge
from twobyteasr.local_mcp.production import ACTIVE, ProductionCore
from twobyteasr.local_mcp.production_media import MediaOperations
from twobyteasr.local_mcp.production_recognition import RecognitionOperations
from twobyteasr.local_mcp.production_text import TextOperations
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, hydrate_media_contract
from twobyteasr.timeline.studio_edit_sequence import identity_sequence, store_sequence, timeline_duration_ms


class ReviewService(MediaOperations, RecognitionOperations, TextOperations, ProductionCore):
    pass


def wait_for(service, job):
    deadline = time.monotonic() + 8
    while service.jobs[job['job_id']]['status'] in ACTIVE:
        QApplication.instance().processEvents()
        time.sleep(.002)
        assert time.monotonic() < deadline, service.jobs[job['job_id']]
    QApplication.instance().processEvents()
    return service.jobs[job['job_id']]


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(tmp_path, application, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path / 'profile'))
    media_path = tmp_path / 'source.mp4'
    media_path.write_bytes(b'original source placeholder')
    project = SubtitleProject(media=StudioMedia(str(media_path), duration_ms=6000),
        cues=[StudioCue('a', 0, 900, '再再强调一遍')])
    hydrate_media_contract(project, dict(duration_ms=6000, width=64, height=64,
        has_video=True, has_audio=True, fingerprint='fixture-source'), source_path=media_path)
    store_sequence(project, identity_sequence(project.media))
    project.validate()
    page, window = QWidget(), QWidget()
    page.project = project
    page.session = SimpleNamespace(project=project, generation=1, project_path=tmp_path / 'review.2byteproj')
    page.undo_stack = QUndoStack(page)
    page._changed = lambda *_: None
    page.timeline = SimpleNamespace(playhead_ms=0, selected_video_track_id='V1',
        selected_video_clip_id='', selected_segment_id='', selected_segment_ids=set())
    window.built_page = lambda _name: page
    bridge = McpBridge(window)
    # These exact fields already existed before this PR: approval-based edits,
    # a general MCP data notice, and no independent glossary access.
    bridge.settings = dict(mcp_common.DEFAULTS, enabled=True, allow_edits=True,
                           allow_export=True, acknowledged=True)
    core = ReviewService(bridge, journal_path=tmp_path / 'jobs.json')
    yield core, page, bridge, media_path
    core.stop('review')
    deadline = time.monotonic() + 8
    while any(worker.isRunning() for worker in core._workers.values()):
        application.processEvents()
        time.sleep(.002)
        assert time.monotonic() < deadline
    application.processEvents()
    page.close()
    window.close()


def test_existing_edit_permission_allows_authorized_direct_edits(service):
    core, page, bridge, _media = service
    before = page.project.cues[0].text
    preview = core.op_cleanup_stutter(page.project.project_id, bridge.revision)
    job = wait_for(core, preview)
    assert job['status'] == 'completed' and job['result']['changes'], job
    adopted = core.op_cleanup_stutter(page.project.project_id, bridge.revision,
                                     action='apply', job_id=job['job_id'])
    print('legacy settings:', bridge.settings, 'direct result:', adopted)
    assert page.project.cues[0].text != before
    assert adopted['changed_cues'] == 1 and not bridge.plans
    page.undo_stack.undo()
    assert page.project.cues[0].text == before


def test_stutter_cleanup_cannot_read_glossaries_when_access_is_denied(service, monkeypatch):
    import subtitle_core as legacy
    core, page, bridge, _media = service
    page.project.glossary_ids = ['private-library']
    reads = []
    def load(*args, **kwargs):
        reads.append((args, kwargs))
        return {'games': {'private-library': {'library_id': 'private-library',
            'game': 'Private glossary', 'mappings': []}}}
    monkeypatch.setattr(legacy, 'load_learned_term_payload', load)
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    monkeypatch.setattr(legacy, 'resolve_glossary_identity', lambda value: value)
    assert bridge.settings['allow_glossary'] is False
    with pytest.raises(BridgeError) as exc:
        core.op_cleanup_stutter(page.project.project_id, bridge.revision)
    assert exc.value.code == 'not_permitted'
    assert not core.jobs
    assert reads == [], 'Denied glossary was read during stutter cleanup: ' + repr(reads)


@pytest.mark.parametrize('change', ['replace', 'remove'])
def test_pause_cuts_refuse_results_from_replaced_media(service, monkeypatch, change):
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.studio import studio_speech_cut
    from twobyteasr.timeline import studio_clip_edit
    core, page, bridge, media_path = service
    first_source = capture_recognition_snapshot(page.project)
    assert first_source['sources'], 'Fixture must include the actual media file identity'
    def analyze(detached, work, **kwargs):
        return {'candidates': [{'start_ms': 1000, 'end_ms': 2000}],
                'fingerprint': capture_recognition_snapshot(detached)['fingerprint']}
    monkeypatch.setattr(studio_speech_cut, 'analyze_speech_pauses', analyze)
    job = wait_for(core, core.op_detect_speech_pauses(page.project.project_id, bridge.revision,
                                                   mode='silence'))
    assert job['status'] == 'completed', job
    if change == 'replace':
        media_path.write_bytes(b'replaced source: formerly silent interval now contains speech')
        second_source = capture_recognition_snapshot(page.project)
        assert first_source['fingerprint'] != second_source['fingerprint']
    else:
        media_path.unlink()
    # Keep the production undo command/model mutation; omit UI refresh callbacks
    # because this fixture deliberately uses QWidget rather than a full Studio.
    native_command = studio_clip_edit.ripple_ranges_command
    def model_command(*args, **kwargs):
        command = native_command(*args, **kwargs)
        command.page = None
        return command
    monkeypatch.setattr(studio_clip_edit, 'ripple_ranges_command', model_command)
    duration = timeline_duration_ms(page.project)
    undo_count = page.undo_stack.count()
    try:
        result = core.op_apply_pause_cuts(page.project.project_id, bridge.revision,
                                         job['job_id'], ['1'])
    except BridgeError as exc:
        assert exc.code in {'stale', 'stale_project', 'input_changed'}
        assert timeline_duration_ms(page.project) == duration
        assert page.undo_stack.count() == undo_count
        assert not core.job_payloads[job['job_id']]['applied']
    else:
        pytest.fail('Cut result from replaced media was accepted: ' + repr(result)
                    + '; timeline before/after=' + repr((duration, timeline_duration_ms(page.project))))


def test_pause_cuts_with_current_input_still_apply_and_undo(service, monkeypatch):
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.studio import studio_speech_cut
    from twobyteasr.timeline import studio_clip_edit
    core, page, bridge, _media = service
    monkeypatch.setattr(studio_speech_cut, 'analyze_speech_pauses', lambda detached, *args, **kwargs: {
        'candidates': [{'start_ms': 1000, 'end_ms': 2000}],
        'fingerprint': capture_recognition_snapshot(detached)['fingerprint']})
    job = wait_for(core, core.op_detect_speech_pauses(page.project.project_id, bridge.revision, mode='silence'))
    native = studio_clip_edit.ripple_ranges_command
    def command(*args, **kwargs):
        value = native(*args, **kwargs)
        value.page = None
        return value
    monkeypatch.setattr(studio_clip_edit, 'ripple_ranges_command', command)
    result = core.op_apply_pause_cuts(page.project.project_id, bridge.revision, job['job_id'], ['1'])
    assert result['removed_ms'] == 1000 and timeline_duration_ms(page.project) == 5000
    assert page.undo_stack.count() == 1
    page.undo_stack.undo()
    assert timeline_duration_ms(page.project) == 6000


def test_pause_cuts_require_the_native_input_fingerprint(service):
    core, page, bridge, _media = service
    job = core.new_job('detect_speech_pauses', core.snapshot(page, page.project))
    core.finish_job(job, {})
    core.job_payloads[job['job_id']] = {'snapshot': core.snapshot(page, page.project), 'applied': False,
        'analysis': {'candidates': [{'candidate_id': '1', 'start_ms': 1000, 'end_ms': 2000}]}}
    with pytest.raises(BridgeError) as exc:
        core.op_apply_pause_cuts(page.project.project_id, bridge.revision, job['job_id'], ['1'])
    assert exc.value.code == 'invalid_job'
    assert timeline_duration_ms(page.project) == 6000 and page.undo_stack.count() == 0


def test_stutter_apply_rechecks_glossary_permission_before_reading(service, monkeypatch):
    from twobyteasr.local_mcp import production_text
    from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry
    core, page, bridge, _media = service
    page.project.glossary_ids = ['private-library']
    bridge.settings['allow_glossary'] = True
    reads = []
    snapshot = GlossarySnapshot((GlossaryLibrary('private-library', 'Private', '1', (TermEntry('专有词'),)),))
    def glossary(*args):
        reads.append(args)
        return snapshot
    monkeypatch.setattr(production_text, '_glossary', glossary)
    job = wait_for(core, core.op_cleanup_stutter(page.project.project_id, bridge.revision))
    assert job['status'] == 'completed' and job['result']['changes']
    before, count = page.project.cues[0].text, len(reads)
    bridge.settings['allow_glossary'] = False
    with pytest.raises(BridgeError) as exc:
        core.op_cleanup_stutter(page.project.project_id, bridge.revision, action='apply', job_id=job['job_id'])
    assert exc.value.code == 'not_permitted' and len(reads) == count
    assert page.project.cues[0].text == before and page.undo_stack.count() == 0
    bridge.settings['allow_glossary'] = True
    core.op_cleanup_stutter(page.project.project_id, bridge.revision, action='apply', job_id=job['job_id'])
    assert page.project.cues[0].text != before
    page.undo_stack.undo()
    assert page.project.cues[0].text == before


@pytest.mark.parametrize('kind', ['glossary_proofread', 'stutter_cleanup', 'recognition'])
def test_glossary_revocation_cancels_dependent_inflight_jobs(service, kind):
    import threading
    core, page, bridge, _media = service
    bridge.settings['allow_glossary'] = True
    entered = threading.Event()
    def work(token, progress):
        entered.set()
        while not token.is_cancelled:
            time.sleep(.002)
        token.raise_if_cancelled()
    job = core.run_job(kind, core.snapshot(page, page.project), work)
    assert entered.wait(2)
    previous = dict(bridge.settings)
    bridge.settings['allow_glossary'] = False
    core.permissions_changed(previous, bridge.settings)
    assert core.jobs[job['job_id']]['status'] == 'cancelling'
    assert wait_for(core, job)['status'] == 'cancelled'
    assert page.undo_stack.count() == 0


@pytest.mark.parametrize('attached', [False, True])
def test_recognition_cannot_use_saved_glossaries_without_permission(service, attached):
    core, page, bridge, _media = service
    page.project.glossary_ids = ['attached-library'] if attached else []
    core.window.legacy = SimpleNamespace(RUNTIME_SETTINGS={'glossary': {
        'enable_domain_terms': True, 'enabled_glossary_ids': [] if attached else ['global-library']}})
    with pytest.raises(BridgeError) as exc:
        core.op_start_recognition(page.project.project_id, bridge.revision)
    assert exc.value.code == 'not_permitted'
    assert not core.jobs
