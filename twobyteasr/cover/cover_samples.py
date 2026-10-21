"""Two deliberately different sample covers, with an original test character.

The character is a drawn demo asset, not an extracted game/streamer portrait.
Callers supply their authorized frozen frame; no media or model is downloaded.
"""
from io import BytesIO
from PIL import Image,ImageDraw
from .cover_document import CoverDocument
from .cover_psd import psd_id


def png(image):
    buffer=BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()


def demo_character():
    image=Image.new('RGBA',(600,800))
    d=ImageDraw.Draw(image)
    # Neutral illustrated host in a headset. Large transparent outside area
    # is intentional, exercising rectangular selection and alpha preservation.
    d.ellipse((92,722,525,786),fill=(0,0,0,80))
    d.polygon([(143,462),(433,460),(514,722),(451,766),(135,766),(66,711)],fill='#142c28',outline='#eff7ec',width=12)
    d.polygon([(185,462),(300,545),(389,462),(418,754),(171,754)],fill='#548774')
    d.polygon([(145,465),(254,535),(188,600),(163,750),(96,720)],fill='#233e35')
    d.polygon([(430,460),(340,540),(410,608),(446,750),(497,710)],fill='#233e35')
    d.rounded_rectangle((252,647,332,682),radius=5,fill='#e4bf58')
    d.rounded_rectangle((239,408,352,515),radius=35,fill='#edb9a0',outline='#1c3029',width=8)
    d.ellipse((112,142,489,485),fill='#263d35',outline='#e9f3e9',width=12)
    d.ellipse((148,193,456,482),fill='#f1c5a9',outline='#22372e',width=9)
    d.ellipse((138,183,451,367),fill='#dbe1d3')
    d.polygon([(132,297),(147,196),(211,134),(295,122),(403,164),(460,253),(418,326),(402,240),(342,320),(333,225),(257,330),(246,234),(184,336)],fill='#ecf0e3',outline='#283d32',width=7)
    d.arc((137,140,467,441),185,358,fill='#2c3930',width=22)
    d.rounded_rectangle((112,293,169,408),radius=19,fill='#203b34',outline='#a9d5c0',width=8)
    d.rounded_rectangle((430,293,487,409),radius=19,fill='#203b34',outline='#a9d5c0',width=8)
    d.line((457,400,416,452,354,452),fill='#213b31',width=12)
    d.ellipse((339,441,372,462),fill='#e4bf58')
    for x in (205,337):
        d.rounded_rectangle((x,341,x+42,370),radius=12,fill='#20382f')
        d.ellipse((x+7,344,x+17,354),fill='#faffec')
    d.arc((262,387,329,430),0,170,fill='#773e37',width=7)
    d.polygon([(103,634),(25,554),(48,505),(90,531),(154,601)],fill='#eec2a5',outline='#223a30',width=9)
    d.polygon([(429,617),(498,508),(535,496),(566,537),(485,673)],fill='#eec2a5',outline='#223a30',width=9)
    return png(image)


def sample_documents(frame):
    image=Image.open(BytesIO(frame)).convert('RGB');image.thumbnail((1920,1920))
    base=png(image);portrait=demo_character()
    results=[]
    for index,(width,height,name) in enumerate([(1920,1080,'实况战报 · 横版'),(1080,1080,'挑战档案 · 方形')]):
        doc=CoverDocument(width=width,height=height);doc.background_fit='fill'
        background=doc.add_image(base,'示例底图 · 可替换',(image.width,image.height),background=True)
        background.id=f'sample-{index}-background';doc.background_id=background.id
        mask=Image.new('RGBA',(width,height));pixels=mask.load()
        for x in range(width):
            alpha=int(205*(1-x/width)) if index==0 else 125
            for y in range(height):pixels[x,y]=(6,15,13,alpha)
        overlay=doc.add_image(png(mask),'构图暗部',(width,height));overlay.x=overlay.y=0;overlay.width=width;overlay.height=height;overlay.locked=True
        person=doc.add_image(portrait,'示例角色 · 可替换',(600,800));person.id=f'sample-{index}-character'
        person.width,person.height=(615,820) if index==0 else (400,533)
        person.x,person.y=(1235,260) if index==0 else (-25,545)
        title=doc.add_text('山谷探索\n初见远方之光' if index==0 else '极限闪避\n一局实战')
        title.id=f'sample-{index}-title';title.name='主标题'
        title.x,title.y,title.width=(50,335,1170) if index==0 else (80,210,920)
        title.style.update(size=142 if index==0 else 136,stroke=4,shadow_blur=4,shadow_x=3,shadow_y=6,
                           color='#f2f6e9' if index==0 else '#f4ce62',alignment='left')
        subtitle=doc.add_text('实况战报  /  BOSS FIRST LOOK' if index==0 else '把失误剪掉，留下这一秒')
        subtitle.id=f'sample-{index}-subtitle';subtitle.name='副标题'
        subtitle.x,subtitle.y,subtitle.width=(76,174,1200) if index==0 else (350,775,700)
        subtitle.style.update(size=42 if index==0 else 36,stroke=0,shadow=False,color='#c0d9b2')
        tag=doc.add_text('PLAY / 01' if index==0 else 'CHALLENGE\nNO. 02');tag.name='固定系列标记'
        tag.x,tag.y,tag.width=(77,853,1100) if index==0 else (73,45,760)
        tag.style.update(size=46 if index==0 else 39,stroke=0,shadow=False,color='#e1be62');tag.locked=True
        results.append((name,doc,dict(background=psd_id(background.id),title=psd_id(title.id),subtitle=psd_id(subtitle.id))))
    return results
