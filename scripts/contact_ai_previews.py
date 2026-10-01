"""Finite inspectable contact sheets for actual generated candidate frames."""
from pathlib import Path
import json,sys
from PIL import Image,ImageDraw


def main():
    trial=Path(sys.argv[1]);manifest=json.loads((trial/'review-needed.json').read_text('utf8'))
    for row in manifest['candidates']:
        if not row.get('frames'):continue
        frames=[(Path(f['path']),Image.open(f['path']).convert('RGBA')) for f in row['frames']]
        boxes=[im.getchannel('A').getbbox() for path,im in frames[:3]];boxes=[b for b in boxes if b]
        box=(max(0,min(b[0] for b in boxes)-30),max(0,min(b[1] for b in boxes)-30),
             min(1920,max(b[2] for b in boxes)+30),min(1080,max(b[3] for b in boxes)+30)) if boxes else None
        sheet=Image.new('RGB',(1920,390*((len(frames)+1)//2)),'#1b242b');d=ImageDraw.Draw(sheet)
        for i,(path,im) in enumerate(frames):
            if im.size==(1920,1080) and 'game' not in path.stem and box:im=im.crop(box)
            im.thumbnail((940,345))
            x=i%2*960;y=i//2*390
            sheet.paste(im,(x+(960-im.width)//2,y+35+(345-im.height)//2),im)
            d.text((x+12,y+9),path.stem,fill='white')
        sheet.save(trial/(row['id']+'-review.png'))
        print(str(trial/(row['id']+'-review.png')))


if __name__=='__main__':main()
