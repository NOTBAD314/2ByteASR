"""User-facing material regressions, independent of renderer implementation."""
from scripts.author_balatro_material import definitions,build_theme
from scripts.author_balatro_candidates import candidates
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,accept_authored_set


def test_paper_print_gets_continuous_time_and_never_metal_sweep():
    theme=build_theme(definitions()[0]);spec=theme['motionSpec']
    ink=next(t for t in spec['tracks'] if t['selector']=='.a-ink' and t['phase']=='build')
    assert 450<=min(spec['buildMs'],3000*.2)*(ink['end']-ink['start'])<=580
    assert not any('clipPath' in t['to'] for t in spec['tracks'])
    assert all(x not in theme['cueHtml'] for x in ('type-scan','foil-shimmer','crt-local'))
    assert not any(t.get('repeat',0) for t in spec['tracks'])


def test_metal_has_slow_distinct_lobes_without_periodic_replay():
    theme=build_theme(definitions()[1]);tracks=theme['motionSpec']['tracks']
    assert all(t.get('repeat',0)==0 and not t.get('yoyo',False) for t in tracks)
    assert not any('clipPath' in t['to'] for t in tracks)
    light=[t for t in tracks if t['phase']=='breathe' and 'backgroundPositionX' in t['to']]
    assert len(light)>=2 and len({(t['start'],t['end']) for t in light})==len(light)
    assert all((t['end']-t['start'])*(3000-600-420)>1200 for t in light)
    assert 'crt-local' not in theme['cueHtml'] and 'type-scan' not in theme['cueHtml']


def test_crt_keeps_text_stationary_and_closes_to_center():
    theme=build_theme(definitions()[2]);tracks=theme['motionSpec']['tracks']
    main=[t for t in tracks if t['selector'] in ('.c-screen-type','.c-phosphor')]
    assert not any(set(t['to']) & {'x','xPercent','clipPath'} for t in main)
    collapse=next(t for t in tracks if t['phase']=='resolve' and t['selector']=='.c-powerline' and 'clipPath' in t['to'])
    assert collapse['to']['clipPath']=='inset(0% 49.8% 0% 49.8%)'
    screen_off=next(t for t in tracks if t['phase']=='resolve' and t['selector']=='.c-glass' and t['to'].get('opacity')==0)
    assert screen_off['end']<=collapse['start']
    assert theme['cueHtml'].count('data-semantic-text="true"')==1


def test_normal_creative_adapter_accepts_three_material_specific_sources(tmp_path):
    rows=candidates()
    materials=[('paper',['.a-paper-fibres','.a-ink']),('metal',['.b-rim-specular','.b-gold']),('crt',['.c-glass','.c-phosphor'])]
    for row,definition,(material,selectors) in zip(rows,definitions(),materials):
        row['generated_source']=build_theme(definition)
        row['art_direction_contract']['vocabulary']=[material,definition[1]]
        row['design_spec']['vocabulary']=[material]
        row['MaterialContract']={'material':material,'selectors':selectors}
    ledger=ThemeLedger(tmp_path,'Balatro 纸牌、金币、显像管各自的材质')
    result=accept_authored_set({'candidates':rows},ledger,'test','offline')
    assert len(result.concepts)==3
    assert [r['signature_elements'][0] for r in result.concepts]==['paper','metal','crt']
