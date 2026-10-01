"""Actual browser pixels: surfaces, backgrounds, type material, and font proof."""
from pathlib import Path
import argparse,copy,json,os,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'examples/web-themes/balatro-object-motion-20260911'
TMP=ROOT/'tmp/balatro-object-motion';TMP.mkdir(parents=True,exist_ok=True)
os.environ.update(LOCALAPPDATA=str(TMP/'local'),APPDATA=str(TMP/'roaming'))

def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--themes',type=Path,default=OUT)
    OUT=parser.parse_args().themes.resolve()
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import theme_archive_html
    from PIL import Image
    import numpy as np
    service=RendererService();summary={}
    bg=Image.open(ROOT/'tmp/caption-audit-20260910/visual/game.png').convert('RGBA')
    try:
        for ident in 'ABC':
            folder=OUT/ident;theme=json.loads((folder/'theme.json').read_text('utf8'))
            static=copy.deepcopy(theme);static.pop('motionSpec')
            # Hide only caption copy, retaining the object's own edition labels.
            static['cueCss']+=' .lettering{visibility:hidden}'
            service.live_set(theme_archive_html(static,sample_text='啊感觉他就是你看',auto_replay=False),width=1920,height=1080)
            (folder/'surface.png').write_bytes(service.live_pause(cue_ms=1500,stage_ms=1500))
            surface=Image.open(folder/'surface.png').convert('RGBA')
            Image.alpha_composite(bg,surface).convert('RGB').save(folder/'surface-game.png')
            service.live_set(theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False),width=1920,height=1080)
            for label,ms in [('entrance',180),('hero',1500),('hold-later',1873),('exit',2840),('end',3000)]:
                (folder/f'{label}.png').write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms))
                rgba=Image.open(folder/f'{label}.png').convert('RGBA')
                if label!='end':Image.alpha_composite(bg,rgba).convert('RGB').save(folder/f'{label}-game.png')
            hero=Image.open(folder/'hero.png').convert('RGBA')
            for label,color in [('light','#eee5d7'),('dark','#131615')]:
                Image.alpha_composite(Image.new('RGBA',(1920,1080),color),hero).convert('RGB').save(folder/f'hero-{label}.png')
            bbox=hero.getchannel('A').getbbox();crop=(max(0,bbox[0]-8),max(0,bbox[1]-8),min(1920,bbox[2]+8),min(1080,bbox[3]+8))
            Image.open(folder/'hero-game.png').crop(crop).save(folder/'detail-1to1.png')
            sheet=Image.new('RGB',(1920,1080),'#171a16')
            for i,label in enumerate(('surface-game','entrance-game','hero-game','hold-later-game','exit-game')):
                piece=Image.open(folder/f'{label}.png').crop((280,740,1650,1060));piece.thumbnail((960,300))
                sheet.paste(piece,((i%2)*960,(i//2)*350+20))
            sheet.save(folder/'review-sheet.png')
            service.live_pause(cue_ms=1500,stage_ms=1500)
            d=service._live_request({'type':'live_diagnostics','selectors':['.lettering','.ink','.object','.b-dollar','.b-die','.b-coin']},timeout=8)['diagnostics']
            (folder/'material-diagnostics.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
            row=next(r for r in d['roots'] if r['selector']=='.ink');rect=row['rect'];x,y,w,h=rect
            assert 'Cubic 11' in row['fontFamily'],row
            roi=(int(x+6),int(y+6),int(x+w-6),int(y+h-6))
            left=np.array(hero.crop(roi)).astype(int);right=np.array(Image.open(folder/'hold-later.png').convert('RGBA').crop(roi)).astype(int)
            summary[ident]={'bbox':bbox,'text_rect':rect,'text_material_changed_pixels':int(np.count_nonzero(np.abs(left[:,:,:3]-right[:,:,:3]).max(axis=2)>4)),
                'computed_font_family':row['fontFamily'],'computed_font_size':row['fontSize'],
                'interior_alpha_min':int(left[:,:,3].min()),'hard_end_clear':Image.open(folder/'end.png').getbbox() is None,
                'script_errors':d['script_errors'],'fonts':[{k:v for k,v in r.items() if k in ('text','fontFamily','fontSize','fontWeight','fontLoaded')} for r in d.get('text_runs',[])],
                'timelines':d['timelines'],'motion_map':d['motion_map']}
            print(ident,json.dumps({k:v for k,v in summary[ident].items() if k not in ('fonts','motion_map')},ensure_ascii=True),flush=True)
    finally:service.shutdown()
    (OUT/'material-review.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
