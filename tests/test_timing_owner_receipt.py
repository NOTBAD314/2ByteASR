from types import SimpleNamespace

import moss_firered_pipeline as pipeline


def test_timing_owner_receipt_uses_actual_segment_owners():
    label, counts = pipeline._timing_owners([SimpleNamespace(final_timing_owner='Qwen3-ForcedAligner'),
                                             SimpleNamespace(final_timing_owner='Qwen3-ForcedAligner')])
    assert label == 'Qwen3-ForcedAligner'
    assert counts == {'Qwen3-ForcedAligner': 2}


def test_mixed_timing_owners_are_visible_and_deterministic():
    label, counts = pipeline._timing_owners([SimpleNamespace(final_timing_owner='Qwen3-ForcedAligner'),
                                             SimpleNamespace(final_timing_owner='API')])
    assert label == 'API + Qwen3-ForcedAligner'
    assert counts == {'API': 1, 'Qwen3-ForcedAligner': 1}
