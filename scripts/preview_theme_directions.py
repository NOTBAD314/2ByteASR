"""Render the real V2 component cards and a local browser gallery."""
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    source=Path(sys.argv[1]);out=source.parent/'previews';out.mkdir(exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.theme_art_direction_v2 import preview_theme
    from twobyteasr.web_theme import theme_archive_html
    from html import escape
    data=json.loads(source.read_text('utf8'));service=RendererService();cards=[]
    try:
        for c in data['concepts']:
            theme=preview_theme(c);html=theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False)
            path=out/(c['id']+'.html');path.write_text(html,encoding='utf8')
            service.live_set(html,width=960,height=540)
            (out/(c['id']+'.png')).write_bytes(service.live_pause(cue_ms=1500,stage_ms=1500))
            from PIL import Image
            image=Image.open(out/(c['id']+'.png')).convert('RGBA');bounds=image.getchannel('A').getbbox()
            if bounds:image.crop((max(0,bounds[0]-45),max(0,bounds[1]-35),min(image.width,bounds[2]+45),min(image.height,bounds[3]+35))).save(out/(c['id']+'-detail.png'))
            cards.append(f'<article><h2>{escape(c["name"])}</h2><img src="{c["id"]}-detail.png"><p>{escape(c["composition"])}</p><p class="motion">入场：{escape(c["motion"]["entrance"])}</p><a href="{c["id"]}.html">打开完整透明设计画布</a></article>')
    finally:service.shutdown()
    (out/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>字幕视觉方向</title><style>
body{margin:0;padding:36px;background:#171d25;color:#efeee8;font:16px "Microsoft YaHei UI",sans-serif}h1{font-size:30px}main{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}article{border-top:1px solid #69737c;padding-top:12px}h2{font-size:21px}img{width:100%;background:linear-gradient(120deg,#283742,#384047);border:1px solid #44525d}p{line-height:1.65}a{color:#bce1ed}.motion{color:#bac4c9}header p{color:#b2b9c1}@media(max-width:900px){main{grid-template-columns:1fr}}</style><header><h1>选择一个方向，继续制作完整动画</h1><p>Grok 4.6 美术规格 · 本地组件实渲预览。下面展示构图与材质；选中后实现所述动作。</p></header><main>'''+''.join(cards)+'</main>',encoding='utf8')
    print(out)


if __name__=='__main__':main()
