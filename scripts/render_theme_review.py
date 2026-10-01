"""Render an actual provider theme, frozen five-phase frames, and browser controls."""
import argparse,json,os,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('theme',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--background',type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import theme_archive_html
    from PIL import Image,ImageDraw
    theme=json.loads(args.theme.read_text('utf8'));theme=theme.get('theme',theme)
    html=theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False)
    (out/'theme.html').write_text(html,encoding='utf8');(out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),encoding='utf8')
    if args.background:Image.open(args.background).convert('RGB').resize((960,540)).save(out/'game.jpg',quality=90)
    service=RendererService();phases=(.12,1.2,1.74,2.65,2.97);frames=[]
    try:
        service.live_set(html,width=960,height=540)
        for t in phases:
            path=out/f'alpha-{t:g}.png';path.write_bytes(service.live_pause(cue_ms=t*1000,stage_ms=t*1000));frames.append(Image.open(path).convert('RGBA'))
        diagnostics=service._live_request({'type':'live_diagnostics','selectors':['.wt-copy','.wt-mascot']},timeout=4)['diagnostics']
        (out/'diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding='utf8')
    finally:service.shutdown()
    boxes=[im.getchannel('A').getbbox() for im in frames];boxes=[b for b in boxes if b]
    band_top=max(0,min((b[1] for b in boxes),default=340)-35)
    band_bottom=min(540,max((b[3] for b in boxes),default=540)+35)
    band_height=max(100,band_bottom-band_top)
    for index,bg in enumerate(('light','dark','game')):
        base=Image.open(out/'game.jpg').convert('RGBA') if bg=='game' and (out/'game.jpg').exists() else Image.new('RGBA',(960,540),'#e9e5dc' if bg=='light' else '#1b242e')
        strip=Image.new('RGB',(960,band_height*5),'#252d36')
        for i,(t,frame) in enumerate(zip(phases,frames)):
            composite=Image.alpha_composite(base,frame);composite.save(out/f'{bg}-{t:g}.png')
            crop=composite.crop((0,band_top,960,band_bottom));strip.paste(crop,(0,i*band_height));ImageDraw.Draw(strip).text((8,i*band_height+8),str(t)+'s',fill='#ff9292')
        strip.save(out/f'{bg}-five-phases.jpg',quality=90)
    bounds=frames[2].getchannel('A').getbbox()
    if bounds:
        for bg in ('light','dark','game'):
            im=Image.open(out/f'{bg}-{phases[2]:g}.png');im.crop((max(0,bounds[0]-20),max(0,bounds[1]-20),min(960,bounds[2]+20),min(540,bounds[3]+20))).save(out/f'{bg}-detail.png')
    controls=''.join(f'<button onclick="seek({t})">{label} {t}s</button>' for t,label in zip(phases,('入场初期','入场完成','保持','出场开始','出场末尾')))
    (out/'review.html').write_text('''<!doctype html><meta charset="utf-8"><title>雪绒刹停 · 实际动画审查</title><style>body{margin:24px;background:#171d25;color:#eee;font:16px "Microsoft YaHei UI"}button{margin:4px;padding:10px 14px;background:#35434e;color:white;border:1px solid #607381;cursor:pointer}#canvas{width:960px;height:540px;background:#1b242e;background-size:cover}iframe{border:0;width:100%;height:100%}h1{font-size:25px}#time{color:#bce2ec}</style><h1>雪绒刹停 · Grok 4.6 完整动画</h1><div>'''+controls+'''<button onclick="play()">播放一遍</button></div><div><button onclick="bg('light')">浅色背景</button><button onclick="bg('dark')">深色背景</button><button onclick="bg('game')">游戏背景</button><span id="time"></span></div><div id="canvas"><iframe src="theme.html" onload="seek(1.5)"></iframe></div><script>let f=document.querySelector('iframe');async function seek(t){await f.contentWindow.__2byteSeek(t*1000,t*1000);document.getElementById('time').textContent=t+' 秒'}function bg(v){document.getElementById('canvas').style.background=v==='game'?'url(game.jpg) center/cover':v==='light'?'#e9e5dc':'#1b242e'}async function play(){await f.contentWindow.__2bytePlay(0,0,1);setTimeout(()=>seek(2.99),3000)}</script>''',encoding='utf8')
    print(out)

if __name__=='__main__':main()
