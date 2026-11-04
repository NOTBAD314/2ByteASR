"""One sparse RGBA stream; decoder/overlay count is independent of cue count."""
from fractions import Fraction
from collections import OrderedDict
import hashlib
import math
import time
from pathlib import Path


def build_caption_timeline(layers, folder, *, fps, duration, cancelled=None, progress=None):
    """Bake only active-set changes, preserving the original layer paint order.

    Pixels stay on disk. The decoded PNG LRU has a 32 MiB budget, and only one
    composite is live. Frame boundaries implement gte(t,start)*lt(t,end).
    """
    from PIL import Image
    folder = Path(folder)
    rate = Fraction(str(fps)).limit_denominator(100100)
    count = math.ceil(Fraction(str(duration)) * rate)
    if count <= 0:
        raise ValueError('Export duration must contain at least one frame')
    bounds = [layer['bounds'] for layer in layers]
    x = min((b[0] for b in bounds), default=0)
    y = min((b[1] for b in bounds), default=0)
    width = max((b[2] for b in bounds), default=1) - x
    height = max((b[3] for b in bounds), default=1) - y
    events = {0: [], count: []}
    for index, layer in enumerate(layers):
        first = max(0, layer.get('first_frame', math.ceil(Fraction(str(layer['start'])) * rate)))
        last = min(count, layer.get('last_frame', math.ceil(Fraction(str(layer['end'])) * rate)))
        if first < last:
            events.setdefault(first, []).append((index, True))
            events.setdefault(last, []).append((index, False))
    active, cache = set(), OrderedDict()
    cache_bytes = peak_cache = 0
    manifests, written = [], set()
    boundaries = sorted(events)
    last_report = time.perf_counter()
    try:
        for position, first in enumerate(boundaries[:-1]):
            if cancelled and cancelled():
                raise InterruptedError('render cancelled')
            for index, enabled in events[first]:
                if enabled:
                    active.add(index)
                else:
                    active.discard(index)
            ordered = sorted(active)
            identity = tuple((str(layers[i]['path']), layers[i]['bounds']) for i in ordered)
            name = 'scene-' + hashlib.sha256(repr(identity).encode('utf8')).hexdigest()[:24] + '.png'
            path = folder / name
            passthrough = (len(ordered) == 1 and layers[ordered[0]]['bounds'] == (x,y,x+width,y+height)
                           and Path(layers[ordered[0]]['path']).parent == folder)
            if passthrough:
                # An unchanged, correctly sized raster is already the final
                # caption plane. Do not decode and encode that PNG a second time.
                name = Path(layers[ordered[0]]['path']).name
                written.add(name)
            elif name not in written:
                with Image.new('RGBA', (width, height)) as composite:
                    for index in ordered:
                        layer = layers[index]
                        key = layer['path']
                        image = cache.pop(key, None)
                        if image is None:
                            with Image.open(key) as source:
                                image = source.convert('RGBA')
                            cache_bytes += image.width * image.height * 4
                        cache[key] = image
                        bx, by, *_ = layer['bounds']
                        composite.alpha_composite(image, (bx-x, by-y))
                        while cache_bytes > 32 * 1024 * 1024 and cache:
                            _, old = cache.popitem(last=False)
                            cache_bytes -= old.width * old.height * 4
                            old.close()
                        peak_cache = max(peak_cache, cache_bytes)
                    composite.save(path, compress_level=1)
                written.add(name)
            frames = boundaries[position+1] - first
            manifests += [f"file '{name}'", f'option framerate {rate}',
                          f'duration {float(frames/rate):.12f}']
            now=time.perf_counter()
            if progress and (now-last_report>=.25 or position==len(boundaries)-2):
                progress(position+1,len(boundaries)-1)
                last_report=now
        # concat needs a following packet to retain the final entry's duration.
        manifests += [f"file '{name}'", f'option framerate {rate}']
        timeline = folder / 'captions.ffconcat'
        timeline.write_text('ffconcat version 1.0\n' + '\n'.join(manifests) + '\n', encoding='utf8')
        return dict(path=timeline, bounds=(x, y, x+width, y+height), start=0, end=duration,
                    sparse=True, scenes=len(written), intervals=len(boundaries)-1,
                    cache_peak_bytes=peak_cache)
    finally:
        for image in cache.values():
            image.close()


def caption_input(layer):
    if layer.get('sparse'):
        return ['-f', 'concat', '-safe', '0', '-threads', '1', '-i', str(layer['path'])]
    return ['-i', str(layer['path'])]


def caption_filter(layer, label, fps):
    if layer.get('sparse'):
        rate = Fraction(str(fps)).limit_denominator(100100)
        return f'{label}fps={rate}:round=near:start_time=0,format=rgba[captionpixels];', '[captionpixels]'
    return '', label
