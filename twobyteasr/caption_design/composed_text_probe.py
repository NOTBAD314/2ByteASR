"""Measure actual caption contribution after browser transforms/masks/compositing."""
import base64
from io import BytesIO


def composed_text_probe(session, visible_png, diagnostics):
    import numpy as np
    from PIL import Image
    hidden = base64.b64decode(session._live_request(
        {'type':'live_material_frame','semantic_only':True},timeout=4)['png_base64'])
    arrays=[]
    for png in (visible_png,hidden):
        a=np.asarray(Image.open(BytesIO(png)).convert('RGBA')).astype(float)
        a[:,:,:3]*=a[:,:,3:]/255
        arrays.append(a)
    delta=np.max(np.abs(arrays[0]-arrays[1]),axis=2)
    rows=[]
    for run in diagnostics.get('semantic_text_runs',[]):
        x,y,w,h=run['rect'];pad=2
        crop=delta[max(0,int(y)-pad):min(delta.shape[0],int(y+h)+pad),
                   max(0,int(x)-pad):min(delta.shape[1],int(x+w)+pad)]
        changed=int((crop>8).sum())
        rows.append(dict(text=run['text'],changed_pixels=changed,
            contributing=changed>=max(3,int(w*h*.002))))
    layout_overflow=bool(diagnostics.get('caption_layout',{}).get('overflow'))
    return dict(method='same-time semantic text hidden/restored, premultiplied RGBA difference',
        changed_pixels=int((delta>8).sum()),runs=rows,layout_overflow=layout_overflow,
        passed=bool(rows) and not layout_overflow and all(r['contributing'] for r in rows))
