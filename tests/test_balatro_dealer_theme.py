from twobyteasr.caption_design.web_theme import builtin_web_themes,sanitize_html,theme_archive_html

def test_svg_viewbox_survives_safe_import():
    output=sanitize_html('<svg viewBox="0 0 64 72"><path d="M0 0L1 1"/></svg>',section='cue')
    assert 'viewBox="0 0 64 72"' in output

def test_balatro_has_transparent_stage_and_separate_text_column():
    theme=builtin_web_themes()['balatro-joker'].to_dict()
    assert 'transparent' in theme['stageCss']
    assert 'vignette' not in theme['stageCss'] and 'infinite' not in theme['stageCss']
    assert 'grid-template-columns' in theme['cueCss']
    assert 'min(.44s,calc(var(--wt-dur) * .34))' in theme['cueCss']
    for name in ('chips-stack','mult-flame','joker-bell','foil-shimmer','card-slider','balatro-plate'):
        assert name in theme['cueHtml'] and '.'+name in theme['cueCss']
    assert 'viewBox=' in theme['cueHtml']
