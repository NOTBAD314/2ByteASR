"""Keep RGB caption blending local without subsampling subtitle alpha/chroma."""
import json
from pathlib import Path


def append_region_overlay(filters, base, pixels, *, bounds, width, height,
                          pixel_format, tag, eof_action='repeat', enable='', full_canvas=False):
    """Blend straight RGBA inside an even, padded video region.

    Large/global layers and 10-bit outputs retain full-canvas negotiation.
    Only the completed opaque video patch is converted to 4:2:0.
    """
    output = f'[{tag}out]'
    x, y, right, bottom = bounds
    rx, ry = max(0, (x-8)//2*2), max(0, (y-8)//2*2)
    rright, rbottom = min(width, (right+9)//2*2), min(height, (bottom+9)//2*2)
    rw, rh = rright-rx, rbottom-ry
    condition = f':{enable}' if enable else ''
    if (pixel_format != 'yuv420p' or min(rw, rh) <= 0 or width % 2 or height % 2
            or rw*rh > width*height*.35):
        px, py = (0, 0) if full_canvas else (x, y)
        filters.append(f'{base}{pixels}overlay=x={px}:y={py}:format=auto:eof_action={eof_action}{condition}{output}')
        return output
    filters.append(f'{base}split=2[{tag}main][{tag}area]')
    filters.append(f'[{tag}area]crop={rw}:{rh}:{rx}:{ry},format=rgba[{tag}rgb]')
    if full_canvas:
        filters.append(f'{pixels}crop={rw}:{rh}:{rx}:{ry}[{tag}pixels]')
        pixels, px, py = f'[{tag}pixels]', 0, 0
    else:
        px, py = x-rx, y-ry
    filters.append(f'[{tag}rgb]{pixels}overlay=x={px}:y={py}:format=auto:eof_action={eof_action}{condition}[{tag}painted]')
    filters.append(f'[{tag}painted]format=yuv420p[{tag}patch]')
    filters.append(f'[{tag}main][{tag}patch]overlay=x={rx}:y={ry}:format=yuv420:eof_action=pass{condition}{output}')
    return output


def moving_alpha_bounds(path, *, width, height, frames, cached=None, cancelled=None):
    """Union every decoded alpha sample, including faint 10/12-bit glows.

    Short mixed windows only. The verified MOV digest owns cached bounds;
    text/font/style/canvas/motion/runtime already own that MOV's cache key.
    """
    if frames > 300: return None
    checksum = sidecar = None
    if cached:
        cached = Path(cached)
        sidecar = cached.with_suffix('.roi.json')
        try:
            checksum = cached.with_suffix('.sha256').read_text('ascii').strip()
            data = json.loads(sidecar.read_text('utf8'))
            if not isinstance(data,dict): raise ValueError('invalid alpha bounds cache')
            box=data.get('bounds')
            valid=(box is None or (isinstance(box,list) and len(box)==4 and all(isinstance(v,int) for v in box)
                and 0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height))
            if (data.get('version') == 1 and data.get('sha256') == checksum
                    and data.get('canvas') == [width, height] and data.get('frames') == frames and valid):
                return box
        except (OSError, ValueError): pass
    import av
    import numpy as np
    result, count = None, 0
    with av.open(str(path)) as container:
        container.streams.video[0].codec_context.thread_count = 2
        for frame in container.decode(video=0):
            if cancelled and cancelled(): raise InterruptedError('render cancelled')
            count += 1
            if count > frames or frame.width != width or frame.height != height: return None
            if len(frame.planes) != 4 or not frame.format.name.startswith('yuva444p'): return None
            bits = frame.format.components[3].bits
            if bits > 8 and not frame.format.name.endswith('le'): return None
            dtype = np.dtype('<u2') if bits > 8 else np.dtype('u1')
            plane = frame.planes[3]
            alpha = np.ndarray((height, width), dtype=dtype, buffer=plane,
                strides=(plane.line_size, dtype.itemsize))
            rows = np.flatnonzero(np.any(alpha, axis=1))
            if not rows.size: continue
            columns = np.flatnonzero(np.any(alpha[rows[0]:rows[-1]+1], axis=0))
            box = [int(columns[0]), int(rows[0]), int(columns[-1])+1, int(rows[-1])+1]
            result = box if result is None else [min(result[0],box[0]), min(result[1],box[1]),
                max(result[2],box[2]), max(result[3],box[3])]
    if count != frames: return None
    if sidecar and checksum:
        staged = None
        try:
            import os, uuid
            staged = sidecar.with_name(sidecar.name+'.'+uuid.uuid4().hex+'.tmp')
            staged.write_text(json.dumps(dict(version=1,sha256=checksum,canvas=[width,height],frames=frames,bounds=result)), 'utf8')
            os.replace(staged, sidecar)
        except OSError: pass
        finally:
            if staged is not None: staged.unlink(missing_ok=True)
    return result
