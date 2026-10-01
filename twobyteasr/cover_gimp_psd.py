"""Conservative rebuild plan from actual PSD type records, never layer names."""
import math


def rebuild_plan(metadata):
    rows=[];warnings=[]
    def color(value,default='#ffffff'):
        if not isinstance(value,dict) or not all(k in value for k in ('r','g','b')):return default
        return '#'+''.join(f'{max(0,min(255,round(value[k]))):02x}' for k in ('r','g','b'))
    def number(value,default=0):return float(value.get('value',default) if isinstance(value,dict) else value or default)
    def visit(items):
        for layer in items:
            if layer.get('placedLayer'):warnings.append(layer['name']+'：智能对象在 GIMP 中变为像素层，原 PSD 保留。')
            text=layer.get('text')
            if text:
                style=text.get('style',{});transform=text.get('transform',[1,0,0,1,0,0]);runs=text.get('styleRuns',[])
                supported=(layer.get('id') is not None and isinstance(text.get('text'),str) and len(text['text'])<=20000
                           and len(transform)==6 and abs(transform[1])<1e-6 and abs(transform[2])<1e-6
                           and transform[0]>0 and abs(transform[0]-transform[3])<1e-6
                           and text.get('orientation','horizontal')=='horizontal' and text.get('warp',{}).get('style','none')=='none'
                           and not any(run.get('style') and run['style']!=style for run in runs)
                           and style.get('horizontalScale',1)==style.get('verticalScale',1)
                           and 1<=float(style.get('fontSize',0))*transform[3]<=2048)
                if not supported:
                    warnings.append(layer['name']+'：复杂文字变换/混合样式保留原像素层，请手动重建；不猜测文本样式。')
                else:
                    native=dict(family=style.get('font',{}).get('name',''),font_style='',size=float(style['fontSize'])*transform[3],
                                color=color(style.get('fillColor')),alignment=text.get('paragraphStyle',{}).get('justification','left'),stroke=0,shadow=False)
                    effects=layer.get('effects',{})
                    strokes=[s for s in effects.get('stroke',[]) if s.get('enabled')]
                    if len(strokes)==1 and strokes[0].get('fillType')=='color':
                        native.update(stroke=number(strokes[0].get('size')),stroke_color=color(strokes[0].get('color'),'#000000'))
                    shadows=[s for s in effects.get('dropShadow',[]) if s.get('enabled')]
                    if len(shadows)==1:
                        shadow=shadows[0];angle=math.radians(number(shadow.get('angle')));distance=number(shadow.get('distance'))
                        native.update(shadow=True,shadow_x=math.cos(angle)*distance,shadow_y=-math.sin(angle)*distance,
                                      shadow_blur=number(shadow.get('size')),shadow_color='#'+f'{round(float(shadow.get("opacity",1))*255):02x}'+color(shadow.get('color'),'#000000')[1:])
                    rows.append(dict(source_id=layer['id'],text=text['text'].replace('\r','\n'),name=layer['name'],style=native,
                                     visible=not layer.get('hidden',False),opacity=float(layer.get('opacity',1)),x=layer.get('left',0),y=layer.get('top',0)))
                    warnings.append(layer['name']+'：依真实 PSD 文字记录重建；原外观像素层隐藏保留。字体度量、边缘与行距请对照检查。')
            visit(layer.get('children',[]))
    visit(metadata.get('layers',[]))
    return dict(text_layers=rows,warnings=warnings)
