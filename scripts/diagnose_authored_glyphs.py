"""Local raster ablation of a preserved author response; no provider calls."""
import argparse,copy,hashlib,json,os,sys
from io import BytesIO
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('fresh repository tmp directory required')
    out.mkdir(parents=True);os.environ['LOCALAPPDATA']=str(out/'local');os.environ['APPDATA']=str(out/'roaming')
    from PIL import Image,ImageDraw
    import numpy as np
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import theme_archive_html
    raw=args.source.read_bytes();data=json.loads(raw);result=dict(source=str(args.source),sha256=hashlib.sha256(raw).hexdigest(),cases=[])
    service=RendererService(root/'renderer');thumbs=[]
    try:
        for candidate in data['candidates']:
            theme=candidate['generated_source'];theme=theme.get('webTheme',theme)
            for variant,css in [('legacy-paint-order','[data-caption-text],.wt-w{paint-order:normal!important}'),('host-default',''),
                                ('no-stroke','[data-caption-text],.wt-w{-webkit-text-stroke-width:0!important}')]:
                html=theme_archive_html(theme,sample_text='这次终于找到出口了',duration_seconds=3,auto_replay=False)
                html=html.replace('</head>','<style>'+css+'</style></head>')
                service.live_set(html,width=1920,height=1080)
                png=service.live_frame(cue_ms=1500,stage_ms=1500,timeout=25)
                path=out/(candidate['id']+'-'+variant+'.png');path.write_bytes(png)
                diagnostic=service._live_request({'type':'live_diagnostics'},timeout=15)['diagnostics']
                im=Image.open(BytesIO(png)).convert('RGBA');pixels=np.asarray(im)
                white=(pixels[:,:,:3].min(axis=2)>235)&(pixels[:,:,3]>220)
                bbox=im.getchannel('A').getbbox()
                result['cases'].append(dict(id=candidate['id'],variant=variant,white_fill_pixels=int(white.sum()),
                    alpha_nonzero=int((pixels[:,:,3]>0).sum()),alpha_bbox=bbox,computed=diagnostic['semantic_text_runs']))
                crop=im.crop(bbox);crop.thumbnail((760,160));tile=Image.new('RGB',(800,190),'#181820');tile.paste(crop,(10,25),crop)
                ImageDraw.Draw(tile).text((10,5),f"{candidate['id']} {variant} white pixels={int(white.sum())}",fill='white');thumbs.append(tile)
    finally:service.shutdown()
    sheet=Image.new('RGB',(800*3,190*3),'#181820')
    for index,im in enumerate(thumbs):sheet.paste(im,(index%3*800,index//3*190))
    sheet.save(out/'contact.png');(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([{k:r[k] for k in ('id','variant','white_fill_pixels','alpha_nonzero')} for r in result['cases']]))


if __name__=='__main__':main()
