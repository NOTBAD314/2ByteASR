"""Actual headless-browser pixels for a freely authored bilingual theme."""
import argparse,hashlib,json,os,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.caption_design.web_theme import builtin_web_themes
    from twobyteasr.rendering.live_web_preview import prepare_web_configuration
    from twobyteasr.rendering.renderer_service import GLOBAL_RENDERER_SERVICE as renderer
    theme=builtin_web_themes()['doom95'].to_dict()
    theme['cueHtml']=theme['cueHtml'].replace('<i class="blood b1">','<div class="translation">{{translation}}</div><i class="blood b1">')
    theme['cueCss']+='\n.translation{font-size:32px;color:#30ff70;text-align:center;padding:8px;}'
    config=prepare_web_configuration(theme,'通過最後一關','隊長',3,translation='Victory')
    cases=[]
    try:
        renderer.live_set(config.html,width=960,height=540)
        for name,speaker,translation in [('initial','隊長','Victory'),('updated','領航員','Mission complete'),('hidden','','Mission complete')]:
            renderer.live_text(text='通過最後一關',speaker=speaker,translation=translation,duration_ms=3000)
            png=renderer.live_frame(cue_ms=600,stage_ms=600)
            (out/(name+'.png')).write_bytes(png)
            cases.append(dict(name=name,sha256=hashlib.sha256(png).hexdigest(),bytes=len(png)))
    finally:renderer.shutdown()
    result=dict(passed=len({c['sha256'] for c in cases})==3,cases=cases,
        scope='actual browser; live name/translation/hide at identical project time; no AI provider request')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
