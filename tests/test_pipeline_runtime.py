from contextlib import contextmanager
import threading
from types import SimpleNamespace

from twobyteasr.recognition.pipeline_runtime import finalize_cues, run_parallel_stages


class _ParallelLegacy:
    def __init__(self):
        self.items = []
        self.local = threading.local()

    @contextmanager
    def capture_review_items(self):
        bucket = []
        self.local.current = bucket
        try:
            yield bucket
        finally:
            self.local.current = None

    def extend_review_items(self, rows):
        self.items.extend(rows)


def test_parallel_stage_results_and_reviews_keep_declared_order():
    legacy = _ParallelLegacy()

    def stage(label):
        legacy.local.current.append(label)
        return label.upper()

    results = run_parallel_stages(
        legacy,
        {"first": lambda: stage("first"), "second": lambda: stage("second")},
        thread_name_prefix="test",
    )

    assert results == {"first": "FIRST", "second": "SECOND"}
    assert legacy.items == ["first", "second"]


class _FinalizeLegacy:
    def __init__(self):
        self.calls = []
        self.events = []

    def record_run_event(self, name, **payload):
        self.events.append((name, payload))

    def _same(self, name, cues, *_args, **_kwargs):
        self.calls.append(name)
        return cues

    def repair_overlong_cues_from_source(self, cues, *_args):
        return self._same("repair", cues)

    def normalize_cue_times(self, cues, *_args):
        return self._same("normalize", cues)

    def final_text_conservation_differences(self, *_args):
        self.calls.append("conservation")
        return []

    def validate_final_cues(self, cues, *_args, **_kwargs):
        return self._same("validate", cues)

    def apply_isolated_single_character_rules_safely(self, cues, **_kwargs):
        return self._same("single_character", cues)

    def merge_consecutive_short_repeated_cues(self, cues):
        return self._same("repeat_merge", cues)

    def snap_cue_starts_to_vad_onsets(self, cues, *_args):
        return self._same("vad_onset", cues)

    def extend_cue_tails_by_speaker(self, cues, *_args):
        return self._same("speaker_tail", cues)

    def bridge_short_display_gaps(self, cues, *_args):
        return self._same("display_gap", cues)

    def collect_review_items(self, *_args):
        self.calls.append("reviews")

    def relock_display_timing(self, cues, *_args, **_kwargs):
        self.calls.append("relock")


def test_finalize_cues_preserves_the_established_stage_order():
    legacy = _FinalizeLegacy()
    cues = [SimpleNamespace(cue_id=1, speaker='S01', text='原文字', start=0., end=1.)]
    assert finalize_cues(cues, [], [], [], 10.0, 60.0, legacy) is cues
    assert legacy.calls == [
        "repair",
        "normalize",
        "conservation",
        "validate",
        "single_character",
        "repeat_merge",
        "repair",
        "normalize",
        "vad_onset",
        "speaker_tail",
        "display_gap",
        "validate",
        "reviews",
        "relock",
    ]
    assert [p['phase'] for name,p in legacy.events if name=='display_boundary_phase'] == [
        'grouped_before_display', 'normalized_and_vad_onsets', 'speaker_reading_tail',
        'short_gap_bridge', 'validated_and_content_recovered', 'final_half_open_display']
    assert all(p['half_open'] for name,p in legacy.events if name=='display_boundary_phase')


def test_japanese_finalize_joins_flashing_lines_before_the_limit_repair():
    """2026-10-18 (日常 19): the joined line still goes through the 16-character / 5-second repair."""
    from twobyteasr.subtitle_rules.language_rules import language_scope

    class Legacy(_FinalizeLegacy):
        def repair_overlong_cues_from_source(self, cues, *_args):
            self.calls.append(("repair", [cue.text for cue in cues]))
            return cues

    legacy = Legacy()
    cues = [SimpleNamespace(cue_id=1, speaker='S08', text='いいから', start=373.540, end=373.915, timing_locked=False),
            SimpleNamespace(cue_id=2, speaker='S08', text='次は教えた通りに', start=374.249, end=375.458,
                            timing_locked=False)]
    with language_scope('ja'):
        result = finalize_cues(cues, [], [], [], 1420.0, 24000 / 1001, legacy)
    assert [cue.text for cue in result] == ['いいから次は教えた通りに']
    assert [call[1] for call in legacy.calls if isinstance(call, tuple)] == [
        ['いいから', '次は教えた通りに'], ['いいから次は教えた通りに']]
