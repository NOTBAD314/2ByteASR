"""Speaker evidence and optional provider receipts survive alternate-primary conversion."""
import copy

import pytest


@pytest.mark.parametrize('with_provider', [False, True])
def test_alternate_primary_copies_speaker_evidence_without_a_local_import(with_provider):
    import moss_firered_pipeline as pipeline
    import subtitle_core as legacy
    row = dict(start=0.0, end=1.2, text='你好世界', speaker='S01',
               speaker_evidence=dict(source='provider', details=dict(labels=['S01'])))
    if with_provider:
        row['provider_source'] = dict(provider='loopback', details=dict(labels=['primary']))
    before = copy.deepcopy(row)
    segment, = pipeline.build_alternate_primary_segments([row], [], legacy, 'api')
    assert segment.caption_arbitration['speaker_evidence'] == before['speaker_evidence']
    segment.caption_arbitration['speaker_evidence']['details']['labels'].append('changed')
    if with_provider:
        assert segment.caption_arbitration['provider_source'] == before['provider_source']
        segment.caption_arbitration['provider_source']['details']['labels'].append('changed')
    assert row == before
