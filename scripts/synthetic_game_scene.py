"""Deterministic fictional game background; no source footage or desktop data."""
from PIL import Image,ImageDraw,ImageFont


def create(path):
    im=Image.new('RGB',(1920,1080));d=ImageDraw.Draw(im)
    for y in range(1080):
        t=y/1080;d.line((0,y,1920,y),fill=(int(38-18*t),int(57-24*t),int(65-30*t)))
    d.polygon([(0,0),(650,350),(650,690),(0,1080)],fill='#273839')
    d.polygon([(1920,0),(1260,350),(1260,690),(1920,1080)],fill='#37403b')
    d.rectangle((650,350,1260,690),fill='#182b2d')
    d.polygon([(0,1080),(650,690),(1260,690),(1920,1080)],fill='#435149')
    for x in (-700,-150,250,550,850,1070,1370,1670,2070,2600):
        d.line((960,640,x,1080),fill='#687261',width=3)
    for y in (745,820,940):d.line((0,y,1920,y),fill='#6e7867',width=3)
    for x in (95,325,1490,1750):
        d.rectangle((x,120,x+65,855),fill='#151f21');d.rectangle((x+10,120,x+46,855),fill='#4d5b52')
        for y in (170,380,590,800):d.line((x,y,x+65,y),fill='#819183',width=3)
    d.rectangle((842,406,1070,710),fill='#101d20',outline='#7c9b81',width=10)
    d.rectangle((870,432,1040,710),fill='#4d7563')
    d.polygon([(875,445),(1036,445),(1036,701),(875,701)],fill='#80aa7b')
    d.ellipse((958,580,970,592),fill='#f1d48a')
    for x in (475,1375):
        d.rectangle((x,460,x+45,510),fill='#171f20')
        d.polygon([(x+12,455),(x+24,405),(x+37,455)],fill='#edcb87')
    d.polygon([(1360,1080),(1460,828),(1510,834),(1510,1080)],fill='#182127')
    d.polygon([(1460,835),(1620,620),(1640,632),(1510,860)],fill='#a8b9b5')
    d.rounded_rectangle((65,62,350,98),radius=8,fill='#152429',outline='#8bada0',width=2)
    d.rounded_rectangle((75,71,286,88),radius=4,fill='#89bda0')
    d.line((945,540,975,540),fill='#d6ddc6',width=2);d.line((960,525,960,555),fill='#d6ddc6',width=2)
    im.save(path)
