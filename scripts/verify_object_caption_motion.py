"""Object-language frames, six cue lengths, exact seeks and glyph geometry."""
from pathlib import Path
import argparse,copy,json,os,sys,time
from io import BytesIO
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--themes',type=Path,default=ROOT/'examples/web-themes/balatro-object-motion-20260911')
    p.add_argument('--output',type=Path,default=ROOT/'tmp/balatro-object-motion/object-check');p.add_argument('--only',default='ABC')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import theme_archive_html
    from PIL import Image
    import numpy as np
    service=RendererService();summary={};bg=Image.open(ROOT/'tmp/caption-audit-20260910/visual/game.png').convert('RGBA')
    text='啊感觉他就是你看'
    def frame(ms):return Image.open(BytesIO(service.live_pause(cue_ms=ms,stage_ms=ms))).convert('RGBA')
    def diag(selectors=()):return service._live_request({'type':'live_diagnostics','selectors':list(selectors)},timeout=8)['diagnostics']
    def premult(im):
        ar=np.array(im).astype(float);ar[:,:,:3]*=ar[:,:,3:]/255;return ar
    try:
        for ident in a.only:
            folder=out/ident;folder.mkdir(exist_ok=True);theme=json.loads((a.themes/ident/'theme.json').read_text('utf8'))
            row={'checks':{},'durations':[]};summary[ident]=row;checks=row['checks']
            for duration in (100,300,500,1500,3000,6000):
                service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=duration/1000,auto_replay=False),width=1920,height=1080)
                build=min(theme['motionSpec']['buildMs'],duration*.2);resolve=min(theme['motionSpec']['resolveMs'],duration*.15)
                keys={'zero':0,'entry10':build*.1,'entry30':build*.3,'entry60':build*.6,'build-end':build,
                      'hold':(build+duration-resolve)/2,'resolve-start':duration-resolve,'exit-mid':duration-resolve/2,'near-end':duration*.99,'EOF':duration}
                samples={name:frame(ms) for name,ms in keys.items()}
                d=diag(('.ink','.lettering','.object'));main_runs=d['semantic_text_runs']
                details={'duration_ms':duration,'build_ms':build,'resolve_ms':resolve,'reading_ms':duration-build-resolve,'seek':[]}
                checks[f'{duration}-reading-budget']=duration-build-resolve>=duration*.65-.0001
                checks[f'{duration}-EOF']=not bool(np.array(samples['EOF'])[:,:,3].any())
                checks[f'{duration}-zero']=not bool(np.array(samples['zero'])[:,:,3].any())
                for name in ('resolve-start','hold','build-end','entry60','entry30','entry10','zero','near-end','EOF'):
                    actual=frame(keys[name]);old=premult(samples[name]);diff=np.abs(old-premult(actual))
                    alpha_max=int(diff[:,:,3].max());changed=int(np.count_nonzero(diff.max(axis=2)>1))
                    passed=float(diff.max())<=16 and float(diff.mean())<.001 and alpha_max<=1 and changed<1920*1080*.001
                    details['seek'].append(dict(key=name,ms=keys[name],max=float(diff.max()),mean=float(diff.mean()),alpha_max=alpha_max,pixels_over_one=changed,passed=passed))
                checks[f'{duration}-reverse']=all(r['passed'] for r in details['seek'])
                service.live_pause(cue_ms=keys['hold'],stage_ms=keys['hold']);d=diag(('.ink',))
                run=next(r for r in d['roots'] if r['selector']=='.ink')
                checks[f'{duration}-Cubic']='Cubic 11' in run['fontFamily']
                checks[f'{duration}-visible']=bool(d['semantic_text_runs']) and all(r['opacity']>.99 for r in d['semantic_text_runs'])
                details['motion_map']=d['motion_map'];details['font']=run['fontFamily'];details['text_rect']=run['rect']
                checks[f'{duration}-bounded']=all(t.get('repeat',0)==0 or (t['end']-t['start'])/(t['repeat']+1)>=.12-1e-9 for t in d['motion_map'])
                checks[f'{duration}-single-clock']=len(d['timelines'])==1 and d['timelines'][0]['paused'] and not d['animations'] and not d['script_errors']
                row['durations'].append(details)
                if duration in (1500,3000,6000):
                    panel=Image.new('RGB',(1680,1030),'#171a16')
                    for index,name in enumerate(('entry10','entry30','entry60','build-end','hold','exit-mid')):
                        image=Image.alpha_composite(bg,samples[name]).convert('RGB')
                        image.save(folder/f'{duration}-{name}.png')
                        crop=image.crop((260,680,1675,1065));crop.thumbnail((820,300));panel.paste(crop,((index%2)*840,(index//2)*340))
                    panel.save(folder/f'{duration}-motion-sheet.png')
                if duration==3000:
                    # Primary-ink opacity is monotone through a full 510ms print
                    # interval. Preserve actual sampled values, not just a label.
                    row['entry_opacity']=[]
                    for ms in (90,140,190,240,290,340,390,440,490,540,600):
                        service.live_pause(cue_ms=ms,stage_ms=ms);r=diag()['semantic_text_runs'][0]
                        row['entry_opacity'].append({'ms':ms,'opacity':r['opacity'],'rect':r['rect']})
            # Body remains a complete animated object without semantic copy.
            empty=copy.deepcopy(theme);empty['cueCss']+=' .lettering{visibility:hidden}'
            service.live_set(theme_archive_html(empty,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
            for name,ms in {'empty-entry10':60,'empty-entry30':180,'empty-entry60':360,'empty-hero':1500,'empty-exit':2790}.items():
                Image.alpha_composite(bg,frame(ms)).convert('RGB').save(folder/f'{name}.png')
            long_text='这一手先结算蓝色筹码再叠红色倍率最后抽到稀有牌稳稳拿下整局'
            service.live_set(theme_archive_html(theme,sample_text=long_text,duration_seconds=6,auto_replay=False),width=1920,height=1080)
            long=frame(1500);Image.alpha_composite(bg,long).convert('RGB').save(folder/'long-text.png');d=diag()
            runs=d['semantic_text_runs'];checks['long-text']=bool(runs) and ''.join(r['text'] for r in runs)==long_text
            checks['long-safe']=all(r['rect'][0]>=57.6 and r['rect'][1]>=32.4 and r['rect'][0]+r['rect'][2]<=1862.4 and r['rect'][1]+r['rect'][3]<=1058.4 for r in runs)
            row['long_text']=runs
            if ident=='B':
                service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
                with_value=frame(1500);geometry=diag(('.b-coin','.b-dollar','.b-legend'))
                coin=next(r for r in geometry['roots'] if r['selector']=='.b-coin')['rect'];cx,cy=coin[0]+coin[2]/2,coin[1]+coin[3]/2
                blank=copy.deepcopy(theme);blank['cueCss']+=' .b-dollar,.b-dollar-light{visibility:hidden}'
                service.live_set(theme_archive_html(blank,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
                without=frame(1500);delta=np.abs(premult(with_value)-premult(without)).max(axis=2)
                mask=delta>8;mask[:int(coin[1]),:]=False;mask[int(coin[1]+coin[3]):,:]=False;mask[:,:int(coin[0])]=False;mask[:,int(coin[0]+coin[2]):]=False
                yy,xx=np.nonzero(mask);box=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)];center=[(box[0]+box[2])/2,(box[1]+box[3])/2]
                row['dollar_geometry']={'coin':coin,'ink_bbox':box,'ink_center':center,'coin_center':[cx,cy],'offset':[center[0]-cx,center[1]-cy]}
                checks['dollar-centered']=abs(center[0]-cx)<=2 and abs(center[1]-cy)<=2
                # The font's range box includes blank leading. Compare actual
                # painted glyphs, so LUCKY cannot hide behind a box exemption.
                no_legend=copy.deepcopy(theme);no_legend['cueCss']+=' .b-legend{visibility:hidden}'
                service.live_set(theme_archive_html(no_legend,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
                legend_delta=np.abs(premult(with_value)-premult(frame(1500))).max(axis=2)
                ly,lx=np.nonzero(legend_delta>8)
                legend_box=[int(lx.min()),int(ly.min()),int(lx.max()+1),int(ly.max()+1)]
                row['dollar_geometry']['legend_ink_bbox']=legend_box
                row['dollar_geometry']['legend_gap_px']=legend_box[1]-box[3]
                checks['dollar-legend-separated']=legend_box[1]-box[3]>=8
                with_value.crop((int(coin[0])-5,int(coin[1])-5,int(coin[0]+coin[2])+5,int(coin[1]+coin[3])+15)).save(folder/'coin-1to1.png')
            row['passed']=all(checks.values());write_path=folder/'result.json';write_path.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf8')
            print(ident,json.dumps({'passed':row['passed'],'failed':[k for k,v in checks.items() if not v],'dollar':row.get('dollar_geometry')},ensure_ascii=False),flush=True)
    finally:
        service.shutdown();(out/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    if not all(r.get('passed') for r in summary.values()):raise SystemExit(1)


if __name__=='__main__':main()
