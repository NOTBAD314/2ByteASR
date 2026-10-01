"""Render authored source in actual Chromium; export videos only after review."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import theme_archive_html
    from PIL import Image
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'examples/web-themes/balatro-20260911');a=p.parse_args()
    background=Image.open(ROOT/'tmp/caption-audit-20260910/visual/game.png').convert('RGBA')
    positive=Image.open(ROOT/'tmp/caption-audit-20260910/visual/A-game-1500.png').convert('RGB')
    service=RendererService();summary={}
    try:
        for ident in 'ABC':
            out=a.output/ident;theme=json.loads((out/'theme.json').read_text('utf8'))
            html=theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False)
            service.live_set(html,width=1920,height=1080)
            for name,ms in [('entrance',140),('hero',1500),('exit',2850),('end',3000)]:
                path=out/(name+'.png');path.write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms))
                rgba=Image.open(path).convert('RGBA');bounds=rgba.getchannel('A').getbbox()
                if name!='end':
                    Image.alpha_composite(background,rgba).convert('RGB').save(out/(name+'-game.png'))
                if name=='hero' and bounds:
                    rgba.crop((max(0,bounds[0]-15),max(0,bounds[1]-15),min(1920,bounds[2]+15),min(1080,bounds[3]+15))).save(out/'detail-1to1.png')
                    game=Image.open(out/'hero-game.png').convert('RGB')
                    compare=Image.new('RGB',(1920,2160));compare.paste(positive,(0,0));compare.paste(game,(0,1080));compare.save(out/'positive-comparison.png')
            service.live_pause(cue_ms=1500,stage_ms=1500)
            diag=service._live_request({'type':'live_diagnostics','selectors':['.lettering','.chips-stack','.mult-flame','.foil-shimmer','.card-slider','.joker-mark']},timeout=8)['diagnostics']
            (out/'diagnostics.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2),encoding='utf8')
            summary[ident]={'script_errors':diag['script_errors'],'timelines':diag['timelines'],'bounds':Image.open(out/'hero.png').getbbox(),'end_clear':Image.open(out/'end.png').getbbox() is None}
            props=dict(schemaVersion=1,width=1920,height=1080,fps=30,durationInFrames=90,cues=[dict(id='balatro',text='啊感觉他就是你看',startMs=0,endMs=3000,styleId='theme',visual=dict(webTheme=theme))],recipes=dict(theme=dict(webTheme=theme)))
            (out/'export-props.json').write_text(json.dumps(props,ensure_ascii=False),encoding='utf8')
            print(ident,summary[ident],flush=True)
    finally:service.shutdown()
    (a.output/'render-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
