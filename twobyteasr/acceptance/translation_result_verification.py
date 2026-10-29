"""Read back paid results, export real SRTs and replay a reconstructed cache offline."""
from pathlib import Path
import argparse, hashlib, json, os, time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    root=Path(__file__).resolve().parents[2]
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('Fresh checkout/tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from ..test_isolation import install
    install()
    from ..projects.studio_project import load_project
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    from ..subtitle_rules import subtitle_translation as st
    original=load_project(args.original);reopened=load_project(args.run/'translated.2byteproj')
    receipt=json.loads((args.run/'result.json').read_text('utf8'))
    assert len(original.cues)==len(reopened.cues)==receipt['cue_count']
    def identity(c):return (c.id,c.text,c.start_ms,c.end_ms,c.speaker_id,c.style_id,c.effect_id,c.appearance_override,c.transform)
    assert [identity(c) for c in original.cues]==[identity(c) for c in reopened.cues]
    translations=receipt['translations']
    records=st.records_of(reopened)
    for cue in reopened.cues:
        assert records[cue.id]['text']==translations[cue.id]
    artifacts=export_language_layers(reopened,out/'exports','translation',speaker_mode='combined')
    rows={}
    for artifact in artifacts.artifacts:
        parsed,errors=parse_srt(artifact.path.read_text('utf8'));assert not errors
        rows[artifact.layer]=parsed
        assert len(parsed)==len(original.cues)
        assert [(c.start_ms,c.end_ms) for c in parsed]==[(c.start_ms,c.end_ms) for c in original.cues]
    from ..subtitle_rules.punctuation_style import project_mode,style_translation,math_enabled
    mode=project_mode(reopened)
    assert [r.text for r in rows['translation']]==[
        style_translation(translations[c.id],mode,math=math_enabled(reopened)) for c in original.cues]
    source=st.translation_source(original)
    context=receipt.get('game_context','洛克王国游戏实况，保留主播口语和角色称呼。')
    cache={}
    for cue in source.cues:
        window=st.context_texts(source,cue.id,3)
        key=st.cache_key(cue.text,window,target='en',model=receipt['model'],provider=receipt['provider'],
                         glossary_digest='',prompt_version=st.prompt_version_for(source.language,'en'),
                         extra=st._cache_extra(source,cue.id,context))
        cache[key]={'text':translations[cue.id]}
    class NoNetwork:
        model=receipt['model'];provider_id=receipt['provider']
        def structured_complete(self,*args,**kwargs):raise AssertionError('Unexpected cache miss; network forbidden')
    started=time.perf_counter()
    warm=st.translate(source,None,NoNetwork(),target='en',game_context=context,cache=cache,workers=4)
    elapsed=time.perf_counter()-started
    assert warm.requests==0 and len(warm.cache_hits)==len(original.cues) and not warm.failed
    result=dict(cue_count=len(original.cues),ids_text_timing_style_preserved=True,
                export_punctuation_mode=mode,
                persisted_translations_verified=True,srt_layers={k:len(v) for k,v in rows.items()},
                warm_cache_replay='reconstructed from actual paid translations, no network',
                warm_translate_seconds=elapsed,warm_requests=warm.requests,
                warm_cache_hits=len(warm.cache_hits),input_sha256=hashlib.sha256(args.original.read_bytes()).hexdigest())
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False));return 0
