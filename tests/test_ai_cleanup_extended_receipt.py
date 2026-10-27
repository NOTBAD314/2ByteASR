"""The extended acceptance fingerprint includes display and motion state."""
import hashlib
import pytest
from twobyteasr.acceptance.ai_cleanup_extended_audit import content_hash, probe_schedule, observe_project_open_entry
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from scripts.verify_ai_cleanup_apply_headed import extended_completion_errors


def test_receipt_detects_translation_display_and_motion_differences():
    project = SubtitleProject(media=StudioMedia('fixture.mp4'), cues=[StudioCue('a', 0, 1000, 'Original')])
    original = content_hash(project)
    project.studio_state['bilingual'] = {'mode': 'bilingual'}
    bilingual = content_hash(project)
    assert bilingual != original
    project.style_recipes['default'] = {'motion': {'entrance': {'type': 'letter_stagger', 'duration_ms': 400}}}
    motion = content_hash(project)
    assert motion != bilingual
    project.cues[0].text = 'Edited'
    assert content_hash(project) != motion


def test_ai_probe_times_are_exact_frames_of_fixed_30fps_qa_media():
    rows = probe_schedule(30)
    assert [row['relative_frame'] for row in rows] == [3, 9]
    assert all(row['relative_ms']*row['source_fps']/1000 == row['relative_frame'] for row in rows)


@pytest.mark.parametrize('offset', [150, 350])
def test_nonrepresentable_probe_time_is_rejected_instead_of_relaxing_seek_tolerance(offset):
    with pytest.raises(ValueError, match='not representable'):
        probe_schedule(30, [offset])


def test_old_exe_cannot_report_extended_success_without_requested_receipts(tmp_path):
    expected = [dict(id='extra', project=str(tmp_path/'extra.2byteproj'), mode='original')]
    assert extended_completion_errors({'passed': True, 'gui_shutdown': True}, expected)


def test_real_reopen_receipt_requires_unique_ids_generation_and_saved_artifacts(tmp_path):
    project = tmp_path/'extra.2byteproj'
    project.write_text('{}')
    folder = tmp_path/'extra'; folder.mkdir()
    screenshot = folder/'actual-reopened-studio.png'; screenshot.write_bytes(b'fixture')
    expected = [dict(id='extra', project=str(project), mode='original')]
    row = dict(id='extra', saved_project=str(project), mode='original', partial=False, playing=False,
        before_generation=1, reopened_generation=2, real_gui_reopened=True, passed=True,
        open_project_entry_calls=[str(project)], old_project_object_id=10, reopened_project_object_id=20,
        saved_content_sha256='1'*64, reopened_content_sha256='1'*64,
        saved_sha256=hashlib.sha256(project.read_bytes()).hexdigest())
    assert not extended_completion_errors({'extended_cases': [row]}, expected)
    assert extended_completion_errors({'extended_cases': [row, row]}, expected)
    assert extended_completion_errors({'extended_cases': [dict(row, reopened_generation=1)]}, expected)
    assert extended_completion_errors({'extended_cases': [dict(row, real_gui_reopened=False)]}, expected)
    screenshot.unlink()
    assert extended_completion_errors({'extended_cases': [row]}, expected)


class SlotsController:
    __slots__ = ('received',)

    def __init__(self):
        self.received = []

    def open_project_entry(self, target, *, marker=None):
        self.received.append((target, marker))
        if marker == 'raise':
            raise ValueError('original entry error')
        return marker


def test_slots_entry_observer_records_only_target_and_preserves_other_instances(tmp_path):
    target, other = SlotsController(), SlotsController()
    original = SlotsController.open_project_entry
    with observe_project_open_entry(target) as calls:
        assert other.open_project_entry(tmp_path/'other.2byteproj', marker='other') == 'other'
        assert target.open_project_entry(tmp_path/'wanted.2byteproj', marker='wanted') == 'wanted'
        assert calls == [str((tmp_path/'wanted.2byteproj').resolve())]
    assert target.received == [(tmp_path/'wanted.2byteproj', 'wanted')]
    assert other.received == [(tmp_path/'other.2byteproj', 'other')]
    assert SlotsController.open_project_entry is original


def test_slots_entry_observer_restores_original_class_method_after_error(tmp_path):
    controller = SlotsController()
    original = SlotsController.open_project_entry
    with pytest.raises(ValueError, match='original entry error'):
        with observe_project_open_entry(controller) as calls:
            controller.open_project_entry(tmp_path/'failed.2byteproj', marker='raise')
    assert calls == [str((tmp_path/'failed.2byteproj').resolve())]
    assert SlotsController.open_project_entry is original


def test_slots_entry_observer_restores_on_abandoned_wait_generator(tmp_path):
    controller = SlotsController()
    original = SlotsController.open_project_entry
    def waiting():
        with observe_project_open_entry(controller) as calls:
            controller.open_project_entry(tmp_path/'opened.2byteproj')
            yield calls
    sequence = waiting()
    assert next(sequence) == [str((tmp_path/'opened.2byteproj').resolve())]
    assert SlotsController.open_project_entry is not original
    sequence.close()
    assert SlotsController.open_project_entry is original


def test_nested_slots_observers_restore_in_order(tmp_path):
    first, second = SlotsController(), SlotsController()
    original = SlotsController.open_project_entry
    with observe_project_open_entry(first) as first_calls:
        outer = SlotsController.open_project_entry
        with observe_project_open_entry(second) as second_calls:
            first.open_project_entry(tmp_path/'first.2byteproj')
            second.open_project_entry(tmp_path/'second.2byteproj')
        assert SlotsController.open_project_entry is outer
    assert first_calls == [str((tmp_path/'first.2byteproj').resolve())]
    assert second_calls == [str((tmp_path/'second.2byteproj').resolve())]
    assert SlotsController.open_project_entry is original
