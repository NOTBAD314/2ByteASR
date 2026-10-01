"""Independent-process barcode probe: GUI GIL stalls must not stall sampling."""
import json
from pathlib import Path
import sys
import time
import traceback
from twobyteasr.visible_playback_audit import ScreenPixels,decode_barcode


def main(folder_arg=None):
    from PIL import Image
    folder=Path(folder_arg or sys.argv[1]);config=json.loads((folder/'capture-config.json').read_text('utf8'))
    geometry=config['geometry'];rects=config['rects'];rows=[];surface=None;error=''
    try:
        barcode_y=config.get('barcode_y',890)
        cells=[(x+(128+64*i)/1920*w,y+barcode_y/1080*h) for x,y,w,h in rects.values() for i in range(16)]
        left=int(min(x for x,y in cells))-4;top=int(min(y for x,y in cells))-4
        right=int(max(x for x,y in cells))+5;bottom=int(max(y for x,y in cells))+5
        rects={k:(x-left,y-top,w,h) for k,(x,y,w,h) in rects.items()}
        surface=ScreenPixels(geometry[0]+left,geometry[1]+top,right-left,bottom-top)
        (folder/'capture-ready').touch()
        deadline=time.perf_counter()+config['seconds']+4;next_image=0
        while time.perf_counter()<deadline and not (folder/'capture-stop').exists():
            begin=time.perf_counter();pixels=surface.grab();now=time.perf_counter()
            row={'at':now,'capture_ms':(now-begin)*1000}
            row.update({key:decode_barcode(pixels,rect,barcode_y) for key,rect in rects.items()});rows.append(row)
            if now>=next_image:
                Image.fromarray(pixels[:,:,[2,1,0]].copy()).save(folder/f'barcode-screen-{len(rows):05}.png')
                next_image=now+5
            time.sleep(max(.001,.008-(time.perf_counter()-begin)))
    except Exception:error=traceback.format_exc()
    finally:
        if surface:surface.close()
        (folder/'probe.json').write_text(json.dumps({'rows':rows,'error':error}),encoding='utf8')


if __name__=='__main__':main()
