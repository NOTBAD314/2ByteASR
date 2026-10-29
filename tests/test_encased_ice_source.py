"""New authoring fields survive the real source parser and saved document."""
import json


def test_model_component_definition_survives_source_and_reopen():
    from twobyteasr.caption_design.source_artifact import frame, to_theme
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    definition = dict(version=7,geometry='facet',frost='snow',lettering='clear',
                      motion='lock',wiggle='strong',wiggleSeed=9301,fontSize=68)
    raw = frame(dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':definition})), 'new-source')
    theme, receipt = to_theme(raw,'new-source',{'name':'中文新句的冰封稿'})
    saved = WebThemeDocument.from_dict(theme).to_dict()
    reopened = WebThemeDocument.from_dict(json.loads(json.dumps(saved))).to_dict()
    assert reopened == saved
    assert receipt['component_definition'] == definition
    wiggle = next(t for t in reopened['motionSpec']['tracks'] if t['selector']=='.ice-wiggle')
    assert wiggle['wiggle']['seed'] == 9301 and wiggle['wiggle']['intensity'] == 1.6
    assert any(t.get('minCueMs')==1900 for t in reopened['motionSpec']['tracks'])
    assert '.ice-shell' in reopened['cueCss'] and '{{text}}' in reopened['cueHtml']


def test_legacy_component_definition_still_expands_unchanged():
    from twobyteasr.caption_design.caption_components import compose
    from twobyteasr.caption_design.caption_ice_legacy import compose as legacy
    assert compose({'version':6}) == legacy({'version':6})


def test_invalid_wiggle_is_rejected_instead_of_silently_removed():
    import pytest
    from twobyteasr.caption_design.caption_components import compose
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    source = compose({'version':7})
    next(t for t in source['motionSpec']['tracks'] if 'wiggle' in t)['wiggle']['seed'] = -1
    with pytest.raises(ValueError,match='seed'):
        WebThemeDocument.from_dict(dict(name='Invalid seed',**source))
