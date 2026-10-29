"""Keep Provider delivery constraints aligned with the finite motion runtime."""
import copy

import jsonschema
import pytest

from twobyteasr.caption_design.theme_motion import validate_motion_spec


def motion(selector='.paper-text'):
    return {'version': 1, 'runtime': 'gsap', 'buildMs': 320, 'resolveMs': 180,
            'tracks': [{'selector': selector, 'phase': 'build', 'start': 0, 'end': 1,
                        'ease': 'power2.out', 'from': {'opacity': 0}, 'to': {'opacity': 1}}]}


def test_actual_provider_compound_selector_has_precise_syntax_error():
    with pytest.raises(ValueError) as caught:
        validate_motion_spec(motion('.paper-text.main'))
    message = str(caught.value)
    assert 'motionSpec.tracks[0].selector' in message
    assert '语法' in message and '.a.b' in message
    assert '宿主' not in message


def test_host_selector_keeps_separate_ownership_error():
    with pytest.raises(ValueError, match=r'motionSpec\.tracks\[0\]\.selector.*宿主'):
        validate_motion_spec(motion('.wt-cue'))


@pytest.mark.parametrize('selector', ['.paper-text', '.paper-text > .ink', '.paper-text .ink:nth-child(2)'])
def test_motion_schema_accepts_runtime_supported_class_chains(selector):
    from twobyteasr.caption_design.theme_motion import MOTION_OUTPUT_SCHEMA
    value = motion(selector)
    jsonschema.validate(value, MOTION_OUTPUT_SCHEMA)
    validate_motion_spec(value)


@pytest.mark.parametrize('selector', ['.paper-text.main', '.a,.b', '#root', '.wt-cue', '.subtitle-placement .ink'])
def test_motion_schema_rejects_unsupported_selector_before_provider_delivery(selector):
    from twobyteasr.caption_design.theme_motion import MOTION_OUTPUT_SCHEMA
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(motion(selector), MOTION_OUTPUT_SCHEMA)


def test_motion_schema_shares_numeric_bounds_and_complete_track_shape():
    from twobyteasr.caption_design.theme_motion import MOTION_OUTPUT_SCHEMA, NUMERIC
    from twobyteasr.caption_design.caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
    shared = AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['properties']['generated_source']['properties']['motionSpec']
    assert shared is MOTION_OUTPUT_SCHEMA
    track = shared['properties']['tracks']['items']
    assert set(track['required']) == {'selector', 'phase', 'from', 'to'}
    states = track['properties']['from']['properties']
    for prop, (low, high) in NUMERIC.items():
        assert states[prop] == {'type': 'number', 'minimum': low, 'maximum': high}
    value = motion()
    value['tracks'][0].update({'from': {'rotationY': 0}, 'to': {'rotationY': 180}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, shared)
    value['tracks'][0]['to']['rotationY'] = 60
    jsonschema.validate(value, shared)


def test_motion_delivery_explains_supported_syntax_without_rewriting_author():
    from twobyteasr.caption_design.caption_material_direction import MOTION_DELIVERY
    assert '.a.b' in MOTION_DELIVERY and '不支持' in MOTION_DELIVERY
    assert '独立class' in MOTION_DELIVERY
    assert 'rotationX/rotationY' in MOTION_DELIVERY and '-80..80' in MOTION_DELIVERY
    value = motion('.paper-text.main')
    original = copy.deepcopy(value)
    with pytest.raises(ValueError):
        validate_motion_spec(value)
    assert value == original
