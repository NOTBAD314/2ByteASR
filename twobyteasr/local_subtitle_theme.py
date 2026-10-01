"""Explicit, offline polar-bear recovery template for preserved concepts."""
import json
from .web_theme import WebThemeDocument, validate_generated_theme


def supports_local_theme(design):
    return '北极熊' in json.dumps(design.get('brief',{}),ensure_ascii=False)


def local_subtitle_theme(design):
    if not supports_local_theme(design):
        raise ValueError('该主题还没有本地稳定模板，请保留候选并重试当前 Provider')
    selected=next((c for c in design.get('concepts',[]) if c.get('id')==design.get('selected_concept_id')),None)
    if selected is None:raise ValueError('请先选择一个已保存的候选')
    identity=selected['id']
    variant='slide' if 'ski' in identity else 'powder' if 'powder' in identity else 'peek'
    accent={'slide':'#E79083','powder':'#A2D7EA','peek':'#DEA856'}[variant]
    html='''<div class="polar-cluster VARIANT">
<div class="bear"><i class="ear left-ear"></i><i class="ear right-ear"></i>
<div class="bear-head"><i class="muzzle"></i><i class="nose"></i>
<div class="goggles"><i class="lens-glint"></i></div></div>
<i class="paw left-paw"></i><i class="paw right-paw"></i><i class="ski"></i></div>
<div class="line">{{words}}</div><i class="iceledge"></i>
<i class="snow snow-one"></i><i class="snow snow-two"></i><i class="snow snow-three"></i>
</div>'''.replace('VARIANT',variant)
    css='''
.wt-cue{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.polar-cluster{position:absolute;left:50%;bottom:5.3%;width:max-content;max-width:76%;padding:0 calc(2 * var(--wt-u)) calc(6.6 * var(--wt-u));transform:translateX(-50%);animation:wt-polar-in .42s ease-out both,wt-polar-out .4s ease-in forwards;animation-delay:0s,calc(var(--wt-dur) - .4s)}
.line{position:relative;z-index:3;text-align:center;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:900;line-height:1.12;color:#FEFFFF;letter-spacing:.025em;-webkit-text-stroke:calc(.17 * var(--wt-u)) #547B96;paint-order:stroke fill;text-shadow:0 calc(.2 * var(--wt-u)) 0 #BFE2EC;overflow-wrap:anywhere}
.line .wt-w{display:inline-block}
.bear{position:absolute;left:50%;bottom:0;width:calc(13 * var(--wt-u));height:calc(8 * var(--wt-u));margin-left:calc(-6.5 * var(--wt-u));animation:wt-bear-breathe 2.8s ease-in-out infinite;transform-origin:50% 100%;z-index:2}
.bear-head{position:absolute;inset:calc(.7 * var(--wt-u)) 0 0;border-radius:46% 46% 40% 40%;background:radial-gradient(ellipse at 35% 25%,#FFFFFF 15%,#F5F8F3 62%,#C5E0EA);border:calc(.15 * var(--wt-u)) solid #A5CDD9}
.ear{position:absolute;top:0;width:calc(3.1 * var(--wt-u));height:calc(3.3 * var(--wt-u));border-radius:50%;background:radial-gradient(ellipse,#D2E6EA 20%,#F8FAF5 27%,#F8FAF5 60%,#BBD9E2 65%)}
.left-ear{left:calc(.4 * var(--wt-u))}.right-ear{right:calc(.4 * var(--wt-u))}
.muzzle{position:absolute;width:42%;height:40%;left:29%;bottom:4%;border-radius:50%;background:linear-gradient(#FFFFFF,#E8F2F2)}
.nose{position:absolute;left:45%;bottom:25%;width:10%;height:12%;border-radius:40% 40% 55% 55%;background:#3E647D;z-index:2}
.goggles{position:absolute;left:9%;top:16%;width:82%;height:43%;border-radius:38% 38% 45% 45%;background:linear-gradient(160deg,#FFEBCB 0%,ACCENT 30%,#628EA8 85%);border:calc(.4 * var(--wt-u)) solid #E6F1F4;box-shadow:0 calc(.17 * var(--wt-u)) 0 #6E98AE;overflow:hidden}
.lens-glint{position:absolute;left:-30%;top:-40%;width:22%;height:180%;background:linear-gradient(90deg,transparent,#FFFFFF,transparent);opacity:0;transform:rotate(20deg);animation:wt-goggle-flash 3.6s ease-in-out infinite}
.paw{position:absolute;bottom:0;width:25%;height:32%;border-radius:50%;background:linear-gradient(#FFFFFF,#D3E8ED);border-bottom:calc(.14 * var(--wt-u)) solid #A6CDDA;z-index:4}
.left-paw{left:-8%}.right-paw{right:-8%}
.iceledge{position:absolute;left:15%;right:15%;bottom:calc(.1 * var(--wt-u));height:calc(.45 * var(--wt-u));border-radius:50%;background:linear-gradient(180deg,#FFFFFF,#A8D4E7);opacity:.8}
.snow{position:absolute;bottom:calc(6 * var(--wt-u));width:calc(.33 * var(--wt-u));height:calc(.33 * var(--wt-u));border-radius:45%;background:#EDFAFF;opacity:0;animation:wt-polar-snow 2.7s linear infinite}
.snow-one{left:7%;animation-delay:.3s}.snow-two{right:9%;animation-delay:1.1s}.snow-three{left:65%;animation-delay:1.9s}
.ski{display:none}.slide .bear{left:86%;width:calc(9 * var(--wt-u));height:calc(6 * var(--wt-u));margin-left:calc(-4.5 * var(--wt-u));animation:wt-ski-enter .65s ease-out both,wt-bear-breathe 2.8s .65s ease-in-out infinite}
.slide .ski{display:block;position:absolute;left:-25%;bottom:calc(-.35 * var(--wt-u));width:150%;height:calc(.5 * var(--wt-u));border-radius:50%;background:linear-gradient(#FFFFFF,#78B5D3);transform:rotate(-4deg)}
.powder .bear{left:82%;animation:wt-powder-shake .5s ease-out both,wt-bear-breathe 2.8s .5s ease-in-out infinite}
.powder .snow{width:calc(.6 * var(--wt-u));height:calc(.6 * var(--wt-u));background:radial-gradient(#FFFFFF,#DBEDF4,transparent)}
@keyframes wt-polar-in{from{opacity:0;transform:translate(-50%,22%)}to{opacity:1;transform:translate(-50%,0)}}
@keyframes wt-polar-out{from{opacity:1;transform:translate(-50%,0)}to{opacity:0;transform:translate(-50%,32%)}}
@keyframes wt-bear-breathe{0%,100%{transform:translateY(0) rotate(-1deg)}50%{transform:translateY(-3%) rotate(1deg)}}
@keyframes wt-goggle-flash{0%,20%,100%{opacity:0;transform:translateX(0) rotate(20deg)}8%,12%{opacity:.8}18%{opacity:0;transform:translateX(650%) rotate(20deg)}}
@keyframes wt-polar-snow{0%{opacity:0;transform:translateY(-30%)}20%{opacity:.75}100%{opacity:0;transform:translateY(700%) rotate(80deg)}}
@keyframes wt-ski-enter{from{opacity:0;transform:translateX(-160%)}to{opacity:1;transform:translateX(0)}}
@keyframes wt-powder-shake{0%{transform:rotate(-8deg)}30%{transform:rotate(8deg)}60%{transform:rotate(-4deg)}100%{transform:rotate(0)}}
'''.replace('ACCENT',accent)
    data=dict(name=selected['name']+' · 本地模板',concept='本地降级：圆耳白熊 .bear；滑雪镜 .goggles；镜片反光 .lens-glint；字底冰沿 .iceledge；碎雪 .snow。'+selected['composition'],
        palette=dict(primary='#F7F9F4',secondary='#AED6E6',background='#FFFFFF',accent=accent,text='#FEFFFF'),
        appearance=dict(fontFamily='"Microsoft YaHei UI", "Noto Sans SC", sans-serif',fontSize=58,color='#FEFFFF',strokeColor='#547B96',strokeWidth=3,letterSpacing=1),
        stageHtml='<div class="polar-stage"></div>',stageCss='.polar-stage{display:none}',cueHtml=html,cueCss=css,
        notes='LOCAL_FALLBACK：使用本地稳定模板生成；保留所选候选与配色，不是 Provider 返回的主题。')
    doc=WebThemeDocument.from_dict(data);validate_generated_theme(doc,instruction='透明背景，北极熊字幕，不要底板')
    return doc.to_dict()
