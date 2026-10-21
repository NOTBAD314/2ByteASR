"""Private libavcodec follower. Only received project demands advance video.

stdin: latest JSON demand; stdout: length-prefixed JSON + owned BGRA bytes.
Each direction has one replaceable slot. Native decode-ahead is bounded to
16 frames; conversion happens only for the newest frame at/before demand.
No Qt, audio endpoint, project state, or independent playback clock lives here.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time
from collections import deque

_conversion = threading.local()


def open_decoder(path, backend='auto'):
    """Probe one real frame before committing to hardware; retain CPU fallback.

    CUDA surfaces stay on the device until display_bgra selects a visible frame.
    Unsupported codecs/adapters fail here rather than freezing the follower.
    """
    import av
    from av.codec.hwaccel import HWAccel
    errors=[]
    modes=['cuda','cpu'] if backend=='auto' and sys.platform=='win32' else [backend if backend!='auto' else 'cpu']
    if modes[-1]!='cpu':modes.append('cpu')
    for mode in modes:
        container=None
        try:
            kwargs={} if mode=='cpu' else dict(hwaccel=HWAccel(mode,allow_software_fallback=False,is_hw_owned=True))
            container=av.open(path,timeout=(4.,4.),**kwargs)
            stream=container.streams.video[0]
            stream.codec_context.thread_count=8 if mode=='cpu' else 1
            stream.codec_context.thread_type='FRAME' if mode=='cpu' else 'SLICE'
            first=next(container.decode(stream))
            # Epoch initialization seeks again; this only checks the actual
            # codec/device and its transfer path, including unsupported formats.
            display_bgra(first,float(stream.sample_aspect_ratio or 1),(128,72))
            return container,stream,dict(backend='nvdec-process' if mode=='cuda' else 'libavcodec-process',
                hardware_frame_format=first.format.name,hardware_fallback='; '.join(errors))
        except Exception as exc:
            if container is not None:container.close()
            errors.append(f'{mode}: {type(exc).__name__}: {exc}')
    raise RuntimeError('; '.join(errors))


def source_pts_ms(frame, container_start_us=0):
    if frame.pts is None or frame.time_base is None:
        raise ValueError('decoded frame has no timestamp')
    # Only the container timeline origin is removed. stream.start_time is
    # diagnostic information, not an extra offset to add to ClipTimeMapper.
    return round(float(frame.pts * frame.time_base) * 1000 - container_start_us / 1000)


def display_bgra(frame, sar, max_size):
    """Apply container display geometry after bounded conversion, like autorotate.

    Ordinary landscape frames keep the zero-array fast path. DISPLAYMATRIX also
    carries reflections, which cannot be reconstructed from frame.rotation.
    """
    matrix = frame.side_data.get('DISPLAYMATRIX')
    values = struct.unpack('=9i', bytes(matrix)) if matrix is not None else None
    a, b, c, d = ([values[i] / 65536 for i in (0, 1, 3, 4)]
                  if values else (1., 0., 0., 1.))
    source_width = max(2, round(frame.width * sar))
    display_width = abs(a)*source_width + abs(c)*frame.height
    display_height = abs(b)*source_width + abs(d)*frame.height
    factor = min(1., max_size[0]/max(2, display_width), max_size[1]/max(2, display_height))
    width, height = max(2, round(source_width*factor)), max(2, round(frame.height*factor))
    # VideoFrame.reformat creates a per-frame SwsContext. Its default thread
    # count is the entire machine, causing repeated thread creation and long
    # spikes. Reuse one context per decoder thread with a bounded worker count.
    if not hasattr(_conversion,'reformatter'):
        from av.video.reformatter import VideoReformatter
        _conversion.reformatter=VideoReformatter()
    converted = _conversion.reformatter.reformat(frame,width=width,height=height,format='bgra',threads=2)
    plane = converted.planes[0]
    # Arbitrary viewport widths often have a padded libav stride. Calling
    # to_ndarray here lazily loads NumPy/OpenBLAS in the frozen child and can
    # block its first frame beyond the heartbeat deadline. Pack rows directly.
    view = memoryview(plane)
    packed = (bytes(view) if plane.line_size == width*4 else
              b''.join(view[y*plane.line_size:y*plane.line_size+width*4] for y in range(height)))
    if (a, b, c, d) == (1., 0., 0., 1.):
        return width, height, packed
    from PIL import Image
    # Only move pixels: channel names do not matter, the byte order stays BGRA.
    image = Image.frombytes('RGBA', (width, height), packed)
    rounded = tuple(round(x) for x in (a, b, c, d))
    orthogonal = all(abs(x-y)<.0001 for x,y in zip((a,b,c,d),rounded))
    if orthogonal and b == c == 0 and abs(a) == abs(d) == 1:
        if a < 0: image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if d < 0: image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    elif orthogonal and a == d == 0 and abs(b) == abs(c) == 1:
        image = image.transpose(Image.Transpose.TRANSPOSE)
        if c < 0: image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if b < 0: image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    else:
        corners = [(a*x+c*y,b*x+d*y) for x,y in ((0,0),(width,0),(0,height),(width,height))]
        low_x,low_y = min(x for x,y in corners),min(y for x,y in corners)
        size = (max(2,round(max(x for x,y in corners)-low_x)),
                max(2,round(max(y for x,y in corners)-low_y)))
        determinant = a*d-b*c
        if abs(determinant)<1e-10:raise ValueError('singular video display matrix')
        ia,ic,ib,id_ = d/determinant,-c/determinant,-b/determinant,a/determinant
        image = image.transform(size, Image.Transform.AFFINE,
            (ia,ic,ia*low_x+ic*low_y,ib,id_,ib*low_x+id_*low_y),
            resample=Image.Resampling.BICUBIC)
    return image.width, image.height, image.tobytes()


def main():
    import av
    import ctypes
    multimedia = ctypes.WinDLL('winmm') if sys.platform == 'win32' else None
    if multimedia: multimedia.timeBeginPeriod(1)
    demand_condition = threading.Condition()
    output_condition = threading.Condition()
    latest = [None]
    outgoing = [None]
    closed = threading.Event()
    stats = dict(backend='libavcodec-process', decoded=0, converted=0, skipped=0,
                 replaced=0, seeks=0, opens=0, state='IDLE', queue_frames=0,
                 decode_ms=0., convert_ms=0., write_ms=0., error='')

    def reader():
        try:
            for line in sys.stdin.buffer:
                value = json.loads(line)
                with demand_condition:
                    latest[0] = value
                    demand_condition.notify_all()
        finally:
            closed.set()
            with demand_condition: demand_condition.notify_all()
            with output_condition: output_condition.notify_all()

    def publish(header, pixels=b''):
        with output_condition:
            if outgoing[0] is not None:
                # A blocked pipe can keep the last paused raster pending.
                # Heartbeats must not discard it: unchanged PTS is never
                # converted again until another demand arrives.
                if header.get('heartbeat') and outgoing[0][1]:
                    return
                stats['replaced'] += 1
            outgoing[0] = ({**header, 'stats':dict(stats), 'pixel_bytes':len(pixels)}, pixels)
            output_condition.notify()

    def writer():
        try:
            while not closed.is_set():
                with output_condition:
                    output_condition.wait_for(lambda: outgoing[0] is not None or closed.is_set())
                    item, outgoing[0] = outgoing[0], None
                if item is None: continue
                header, pixels = item
                encoded = json.dumps(header, separators=(',', ':')).encode('utf8')
                start = time.perf_counter()
                sys.stdout.buffer.write(struct.pack('!I', len(encoded)))
                sys.stdout.buffer.write(encoded)
                if pixels: sys.stdout.buffer.write(pixels)
                sys.stdout.buffer.flush()
                stats['write_ms'] = (time.perf_counter()-start)*1000
        except (BrokenPipeError, OSError):
            closed.set()

    threading.Thread(target=reader, daemon=True, name='video-demands').start()
    threading.Thread(target=writer, daemon=True, name='video-latest-frame').start()
    container = stream = decoder = None
    path = ''
    epoch = -1
    frames = deque()
    head = -1
    published_pts = -1
    last_publish = last_heartbeat = 0.
    failed_epoch = None
    try:
        while not closed.is_set():
            with demand_condition:
                request = latest[0]
                if not request or request.get('cancel') or request['epoch'] == failed_epoch:
                    if request and time.perf_counter()-last_heartbeat > .5:
                        publish(dict(epoch=request['epoch'], heartbeat=True))
                        last_heartbeat = time.perf_counter()
                    demand_condition.wait(.05)
                    continue
            try:
                new_epoch = epoch != request['epoch']
                if path != request['path'] or container is None:
                    if container is not None: container.close()
                    start = time.perf_counter()
                    container,stream,backend_stats=open_decoder(request['path'],os.environ.get('TWOBYTEASR_VIDEO_DECODE_BACKEND','auto'))
                    stats.update(backend_stats)
                    path = request['path']
                    stats.update(opens=stats['opens']+1, open_ms=(time.perf_counter()-start)*1000,
                        stream_start_time=stream.start_time, time_base=str(stream.time_base),
                        container_start_us=container.start_time or 0, codec=stream.codec_context.name)
                    new_epoch = True
                origin = container.start_time or 0
                if new_epoch:
                    epoch = request['epoch']
                    start = time.perf_counter()
                    target = max(0, int((request['source_ms']/1000 + origin/1e6)/stream.time_base))
                    container.seek(target, stream=stream, backward=True, any_frame=False)
                    decoder = iter(container.decode(stream))
                    frames.clear()
                    head = published_pts = -1
                    stats.update(seeks=stats['seeks']+1, seek_ms=(time.perf_counter()-start)*1000,
                                 eof=False, error='', state='PREROLL')
                target_ms = request['source_ms']
                if not request['paused'] and request.get('clock_observed_at'):
                    # Extrapolate the received PlaybackClock anchor, never a
                    # separate playback clock. Cover a bounded GUI cue swap
                    # while audio/native V1 keep running; explicit pause/seek
                    # arrives on the control channel and cancels this anchor.
                    age=max(0,min(.5,time.perf_counter()-request['clock_observed_at']))
                    target_ms+=age*1000*request['rate']
                # Retain one latest past frame plus a bounded native lookahead.
                while len(frames) > 1 and frames[1][0] <= target_ms:
                    frames.popleft()
                    stats['skipped'] += 1
                ahead_ms = 20 if request['paused'] else 60*request['rate']
                if head < target_ms + ahead_ms and len(frames) < 16 and not stats.get('eof'):
                    started = time.perf_counter()
                    try: frame = next(decoder)
                    except StopIteration:
                        stats.update(eof=True, state='EOF')
                        continue
                    stats['decode_ms'] = (time.perf_counter()-started)*1000
                    stats['last_decoded_at'] = time.perf_counter()
                    pts = source_pts_ms(frame, origin)
                    stats['decoded'] += 1
                    stats['raw_pts'] = frame.pts
                    stats['raw_dts'] = frame.dts
                    if head < 0:
                        stats.update(first_decoded_pts_ms=pts, first_decoded_raw_pts=frame.pts,
                                     first_decoded_dts=frame.dts, first_decoded_at=time.perf_counter())
                    head = pts
                    if frames and pts <= target_ms:
                        while frames and frames[-1][0] <= target_ms:
                            frames.pop()
                            stats['skipped'] += 1
                    frames.append((pts, frame, stats['last_decoded_at']))
                    stats['queue_frames'] = len(frames)
                    # Decode through preroll without converting or publishing
                    # its old frames; demand may change at every packet.
                    if pts < target_ms: continue
                now = time.perf_counter()
                candidates = [item for item in frames if item[0] <= target_ms]
                # A stream can begin a fraction of a frame after container zero.
                # Show its true first image, without claiming a fabricated PTS=0.
                if not candidates and frames and target_ms == 0:
                    candidates = [frames[0]]
                if candidates and candidates[-1][0] != published_pts and (
                        request['paused'] or now-last_publish >= 1/60):
                    pts, frame, codec_decoded_at = candidates[-1]
                    sar = float(stream.sample_aspect_ratio or 1)
                    started = time.perf_counter()
                    width, height, pixels = display_bgra(frame, sar, request.get('max_size') or (1920,1080))
                    stats.update(converted=stats['converted']+1, convert_ms=(time.perf_counter()-started)*1000,
                                 queue_frames=len(frames), state='READY')
                    publish(dict(epoch=epoch, generation=request['generation'], path=path,
                        requested_ms=target_ms, pts_ms=pts, raw_pts=frame.pts, raw_dts=frame.dts,
                        time_base=str(frame.time_base), width=width, height=height,
                        decoded_at=now, codec_decoded_at=codec_decoded_at, published_at=time.perf_counter()), pixels)
                    published_pts = pts
                    last_publish = now
                elif now-last_heartbeat > .5:
                    publish(dict(epoch=epoch, heartbeat=True))
                    last_heartbeat = now
                with demand_condition:
                    # Fill the bounded native lookahead without sleeping per
                    # source frame (4x needs 240 source frames per wall second).
                    # Old frames are discarded before GPU download/BGRA work.
                    if head < target_ms+ahead_ms and len(frames)<16 and not stats.get('eof'):
                        continue
                    if latest[0] is request:
                        demand_condition.wait(max(.001,min(.01,1/60-(time.perf_counter()-last_publish))))
            except Exception as exc:
                failed_epoch = request['epoch']
                stats.update(error=f'{type(exc).__name__}: {exc}', state='FAILED', failures=1)
                publish(dict(epoch=failed_epoch, heartbeat=True))
                print(stats['error'], file=sys.stderr, flush=True)
    finally:
        closed.set()
        if container is not None: container.close()
        if multimedia: multimedia.timeEndPeriod(1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
