"""Finite worker/PNG/production parity and authored readability evidence."""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
from io import BytesIO


def reference_theme():
    return dict(name='纸页渲染校准',palette=dict(primary='#E8DDC4',text='#FFF5DE'),
        appearance=dict(fontFamily='Source Han Sans SC Heavy',fontWeight=900,fontSize=70,
                        color='#FFF5DE',strokeColor='#2D322A',strokeWidth=3,bold=False),
        stageHtml='',stageCss='',
        cueHtml='<div class="position"><div class="paper"><div class="fold" aria-hidden="true"></div><div class="ink" data-semantic-text="true">{{text}}</div></div></div>',
        cueCss='.position{position:absolute;left:5%;right:5%;bottom:9%;display:flex;justify-content:center}'
            '.paper{position:relative;max-width:100%;padding:1.2vh 2.4vh;background:#65725A;border:0.28vh solid #E8DDC4;box-shadow:0.6vh 0.6vh 0 #252D26}'
            '.ink{position:relative;z-index:2;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);color:#FFF5DE;line-height:1.15;text-align:center;-webkit-text-stroke:0.25vh #2D322A;paint-order:stroke fill}'
            '.fold{position:absolute;right:-0.3vh;top:-0.3vh;width:1.7vh;height:1.7vh;background:linear-gradient(45deg,#A19A81 49%,#E8DDC4 50%);z-index:1}',
        motionSpec=dict(version=1,runtime='gsap',buildMs=320,resolveMs=180,tracks=[
            dict(selector='.paper',phase='build',start=0,end=1,ease='power2.out',**{'from':dict(y=30,opacity=0),'to':dict(y=0,opacity=1)}),
            dict(selector='.fold',phase='breathe',start=.1,end=.6,ease='sine.inOut',**{'from':dict(opacity=.65),'to':dict(opacity=1)}),
            dict(selector='.paper',phase='resolve',start=0,end=1,ease='power2.in',**{'from':dict(y=0,opacity=1),'to':dict(y=20,opacity=0)})]))


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--payload',type=Path)
    parser.add_argument('--production',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp directory required')
    out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.structured_output import response_object
    from PIL import Image,ImageDraw
    import numpy as np
    themes={'reference':reference_theme()}
    if args.payload:
        payload=response_object(args.payload.read_text('utf8'))
        themes={row['id']:row['generated_source'] for row in payload['candidates']}
    service=RendererService();results={};panels=[]
    try:
        for name,raw in themes.items():
            folder=out/name;folder.mkdir()
            theme=WebThemeDocument.from_dict(raw).to_dict()
            (folder/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
            text='这次终于找到出口了'
            html=theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False)
            (folder/'worker.html').write_text(html,'utf8')
            service.live_set(html,width=1920,height=1080)
            rows=[]
            for ms in (0,100,320,1500,2900):
                png=service.live_pause(cue_ms=ms,stage_ms=ms)
                path=folder/f'worker-{ms}.png';path.write_bytes(png)
                d=service._live_request({'type':'live_diagnostics','selectors':['.paper','.ink']},timeout=5)['diagnostics']
                im=Image.open(BytesIO(png)).convert('RGBA');bbox=im.getchannel('A').getbbox()
                rows.append(dict(ms=ms,path=str(path),alpha_bounds=bbox,diagnostics=d))
                if ms in (100,1500,2900):
                    background=Image.new('RGBA',im.size,'#293E44')
                    draw=ImageDraw.Draw(background)
                    for x in range(0,1920,120):draw.rectangle((x,500,x+65,1080),fill='#46624D')
                    composite=Image.alpha_composite(background,im)
                    composite.save(folder/f'composite-{ms}.png')
                    composite.thumbnail((640,360));panels.append((f'{name} {ms}ms',composite))
            cases=[]
            for duration,caption in ((50,'短句'),(100,'短句'),(500,'短句'),(3000,'第一行明确换行\n第二行继续说明'),
                (3000,'这一段很长的中文字幕应完整显示并保留原来的字形与清楚的轮廓')):
                service.live_text(text=caption,duration_ms=duration)
                for ms in ((0,duration-1) if duration<=100 else (duration*.5,)):
                    png=service.live_pause(cue_ms=ms,stage_ms=ms)
                    path=folder/f'case-{duration}-{len(caption)}-{int(ms)}.png';path.write_bytes(png)
                    d=service._live_request({'type':'live_diagnostics'},timeout=5)['diagnostics']
                    runs=d.get('semantic_text_runs',[])
                    cases.append(dict(duration_ms=duration,ms=ms,text=caption,path=str(path),diagnostics=d,
                        readable=bool(runs) and all(r['opacity']>=.5 and r['rect'][2]>0 for r in runs)))
            parity=[]
            if args.production:
                from twobyteasr.advanced_renderer import compile_composition_data
                from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,SubtitleStyle
                from twobyteasr.style_recipe import StyleRecipe
                project=SubtitleProject(media=StudioMedia('synthetic.mp4',width=1920,height=1080,duration_ms=3000),
                    styles=[SubtitleStyle('default','Render comparison')],cues=[StudioCue('c',0,3000,text)])
                project.style_recipes['default']=StyleRecipe('reference',engine='remotion',web_theme=theme).to_dict()
                project.validate()
                props=compile_composition_data(project,width=1920,height=1080,fps=30,start_seconds=0,duration_seconds=3)
                for ms in (100,1500,2900):
                    frame=round(ms*30/1000);path=folder/f'production-{frame}.png'
                    job=RendererJob(str(path),props,frame,job_kind='production')
                    service.render([job],timeout=120).require_job(job)
                    left=np.array(Image.open(folder/f'worker-{ms}.png').convert('RGBA')).astype(float)
                    right=np.array(Image.open(path).convert('RGBA')).astype(float)
                    for pixels in (left,right):pixels[:,:,:3]*=pixels[:,:,3:]/255
                    mask=np.maximum(left[:,:,3],right[:,:,3])>8
                    mae=float(np.abs(left-right)[mask].mean()) if mask.any() else 0
                    parity.append(dict(ms=ms,mae=mae,passed=mae<2))
            results[name]=dict(frames=rows,cases=cases,production_parity=parity)
    finally:
        service.shutdown()
        (out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    sheet=Image.new('RGB',(640*3,390*((len(panels)+2)//3)),'#111820');draw=ImageDraw.Draw(sheet)
    for i,(label,im) in enumerate(panels):
        x=(i%3)*640;y=(i//3)*390;sheet.paste(im,(x,y+30));draw.text((x+12,y+8),label,fill='white')
    sheet.save(out/'contact.png')
    print(json.dumps(dict(output=str(out),themes={name:dict(short_readable=all(c['readable'] for c in r['cases']),
        parity=r['production_parity']) for name,r in results.items()}),ensure_ascii=False))


if __name__=='__main__':main()
