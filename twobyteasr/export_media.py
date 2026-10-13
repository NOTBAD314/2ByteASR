"""Export-only timestamp index and sequential decoder.

Preview's latest-frame mailbox is intentionally not an export RPC. This reader
owns its container, retains one past/one future frame, and returns a receipt for
every request, including two timeline samples that address the same source PTS.
"""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from bisect import bisect_right
from collections import OrderedDict
import json
import os
import time
import uuid
import threading
from .processes import run_hidden_subprocess


class ExportMediaError(RuntimeError):
    def __init__(self, category, receipt, detail):
        self.receipt = dict(receipt, category=category, detail=str(detail))
        super().__init__(f"视频预检/解码失败 [{category}] clip={receipt.get('clip_id', '')} "
            f"frame={receipt.get('timeline_frame_index', '')} source={receipt.get('source_ms', '')}ms: {detail}")


@dataclass(frozen=True)
class MediaIndex:
    path: str
    origin: Fraction
    time_base: Fraction
    pts: tuple[int, ...]
    fps: Fraction
    probe_json: str
    elapsed: float

    @property
    def last(self): return self.pts[-1] * self.time_base - self.origin
    @property
    def interval(self):
        return (self.pts[-1]-self.pts[-2])*self.time_base if len(self.pts)>1 else 1/self.fps

    def target(self, seconds):
        value = Fraction(seconds)
        first = self.pts[0]*self.time_base-self.origin
        if value < first-self.interval or value > self.last+self.interval:
            raise ValueError(f'target {float(value):.9f}s outside decodable interval ending {float(self.last):.9f}s')
        return min(self.last, max(first, value))


_PROBE_CACHE = OrderedDict()
_PROBE_CACHE_LOCK = threading.Lock()
_PROBE_CACHE_LIMIT = 24


def _check_cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('render cancelled')


def probe_media(ffmpeg, path, *, cancelled=None):
    try:
        _check_cancel(cancelled)
        stat = Path(path).stat()
        return _probe(str(ffmpeg), str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, cancelled)
    except (InterruptedError, ExportMediaError):
        raise
    except Exception as exc:
        raise ExportMediaError('MEDIA_PROBE', {'path':str(path)}, exc) from exc


def _probe(ffmpeg, path, size, modified, cancelled):
    # A cancellation callback belongs to one export, not to the media index.
    # Only successful, unchanged full scans enter this bounded cache.
    _check_cancel(cancelled)
    key = (ffmpeg, path, size, modified)
    with _PROBE_CACHE_LOCK:
        cached = _PROBE_CACHE.get(key)
        if cached is not None:
            _PROBE_CACHE.move_to_end(key)
    if cached is not None:
        _check_cancel(cancelled)
        return cached
    value = _build_probe(ffmpeg, path, cancelled)
    _check_cancel(cancelled)
    current = Path(path).stat()
    if (current.st_size, current.st_mtime_ns) != (size, modified):
        raise ValueError('media changed during full decode preflight')
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE[key] = value
        _PROBE_CACHE.move_to_end(key)
        while len(_PROBE_CACHE) > _PROBE_CACHE_LIMIT:
            _PROBE_CACHE.popitem(last=False)
    return value


def _build_probe(ffmpeg, path, cancelled):
    import av
    started = time.perf_counter()
    result = run_hidden_subprocess([str(Path(ffmpeg).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')),
        '-v','error','-show_streams','-show_format','-of','json',path], purpose='export media preflight',
        capture_output=True, check=True, timeout=15)
    probe = json.loads(result.stdout)
    points=[]
    try:
        with av.open(path) as container:
            stream = container.streams.video[0]
            stream.thread_type='AUTO';stream.thread_count=8
            origin = Fraction(container.start_time or 0, 1_000_000)
            time_base = Fraction(stream.time_base)
            fps = Fraction(stream.average_rate or stream.base_rate or 30)
            for frame in container.decode(stream):
                if cancelled and cancelled(): raise InterruptedError('render cancelled')
                if frame.pts is None: raise ValueError('frame without PTS')
                if getattr(frame,'is_corrupt',False): raise ValueError(f'corrupt frame PTS={frame.pts}')
                if points and frame.pts <= points[-1]: raise ValueError('non-monotonic decoded PTS')
                points.append(frame.pts)
    except InterruptedError: raise
    except Exception as exc:
        raise ExportMediaError('MEDIA_DECODE', {'path':path, 'source_ms':''}, exc) from exc
    if not points: raise ExportMediaError('NO_VIDEO_FRAMES',{'path':path},'no decodable video')
    declared = next(s for s in probe['streams'] if s['codec_type']=='video').get('nb_frames')
    if declared not in (None, 'N/A') and int(declared) != len(points):
        raise ExportMediaError('FRAME_COUNT',{'path':path},f'declared {declared}, decoded {len(points)}')
    return MediaIndex(path,origin,time_base,tuple(points),fps,json.dumps(probe),time.perf_counter()-started)


class SequentialExportDecoder:
    def __init__(self, index, *, backend='cpu', cancelled=None):
        from .video_decode_worker import open_decoder
        self.index=index
        self.cancelled=cancelled
        _check_cancel(cancelled)
        self.container,self.stream,self.backend=open_decoder(index.path,backend)
        self.last_target=None;self.request_id=0;self.generation=uuid.uuid4().hex
        self.cached=None;self.cached_pts=None;self.decoded_frames=0
        try:
            self._seek(0)
        except BaseException:
            self.container.close()
            raise

    def _seek(self, pts):
        _check_cancel(self.cancelled)
        self.container.seek(pts,stream=self.stream,backward=True)
        _check_cancel(self.cancelled)
        self.frames=iter(self.container.decode(self.stream))
        self.current=self.future=None;self.eof=False

    def _advance(self, target):
        while not self.eof:
            _check_cancel(self.cancelled)
            if self.future is None:
                try:
                    self.future=next(self.frames)
                except StopIteration:
                    self.eof=True
                    break
                self.decoded_frames+=1
                _check_cancel(self.cancelled)
                if self.future.pts is None or getattr(self.future,'is_corrupt',False):
                    raise ValueError('invalid frame after seek')
            if self.future.pts*self.future.time_base>target:
                if self.current is None:self.current=self.future
                break
            self.current,self.future=self.future,None

    def read(self, seconds, *, context=None):
        from .video_decode_worker import display_bgra
        self.request_id+=1;started=time.perf_counter()
        decoded_before=self.decoded_frames
        receipt=dict(context or {}, request_id=self.request_id, generation=self.generation,
            decoder_pid=os.getpid(), command_type='export_frame', source_ms=float(seconds)*1000,
            time_base=str(self.index.time_base), source_duration=float(self.index.last+self.index.interval),
            worker_restarts=0,retries=0,**self.backend)
        try:
            _check_cancel(self.cancelled)
            target=self.index.target(seconds)+self.index.origin
            receipt['boundary_clamped']=target != Fraction(seconds)+self.index.origin
            expected=self.index.pts[max(0,bisect_right(self.index.pts,target/self.index.time_base)-1)]
            receipt.update(expected_frame_pts=expected,seek_fallback=False)
            seek_needed=(self.last_target is None and expected!=self.index.pts[0]
                         or self.last_target is not None and target<self.last_target)
            try:
                if seek_needed:
                    self._seek(0 if expected==self.index.pts[0] else expected)
                self._advance(target)
            except InterruptedError:
                raise
            except Exception:
                if not seek_needed:raise
                receipt['seek_fallback']=True
                self._seek(0)
                self._advance(target)
            # Some FLV/container indexes seek past the desired boundary. The
            # successful full decode index, not a plausible nearby frame,
            # decides correctness. Retry from the head once, then fail closed.
            if self.current is None or self.current.pts!=expected:
                if not receipt['seek_fallback']:
                    receipt['seek_fallback']=True
                    self._seek(0)
                    self._advance(target)
                if self.current is None or self.current.pts!=expected:
                    raise ValueError(f'decoded frame does not match full index PTS {expected}')
            self.last_target=target
            pts=self.current.pts
            if self.cached_pts != pts:
                self.cached=display_bgra(self.current,float(self.stream.sample_aspect_ratio or 1),
                    (max(self.current.width,self.current.height)*16,)*2)
                self.cached_pts=pts
            receipt.update(frame_pts=pts,frame_seconds=float(pts*self.current.time_base-self.index.origin),
                next_pts=self.future.pts if self.future else None, state='FRAME', eof=self.eof,
                decoded_frames=self.decoded_frames-decoded_before,
                elapsed_ms=(time.perf_counter()-started)*1000)
            return self.cached,receipt
        except InterruptedError:
            raise
        except Exception as exc:
            raise ExportMediaError('FRAME_REQUEST',receipt,exc) from exc

    def close(self): self.container.close()


def identity_video_graph(graph, media_path):
    """Prove a V1 graph is equivalent to the original media, including audio."""
    tracks=[t for t in graph.get('video_tracks',[]) if t.get('enabled',True)]
    if len(tracks)!=1: return False
    clips=[c for c in tracks[0].get('clips',[]) if c.get('enabled',True)]
    if len(clips)!=1: return False
    c=clips[0];assets={a['asset_id']:a for a in graph['media_pool']}
    if Path(assets[c['asset_id']]['canonical_source']).resolve()!=Path(media_path).resolve():return False
    if c['source_in_ms']!=0 or c['timeline_in_ms']!=0 or c['source_out_ms']!=c['timeline_out_ms'] or c.get('playback_rate',1)!=1:return False
    t=c.get('transform',{});e=c.get('effects',{})
    defaults=dict(anchor_x=.5,anchor_y=.5,position_x=.5,position_y=.5,scale_x=1.,scale_y=1.,rotation=0.,opacity=1.,fit_mode='contain')
    if any(t.get(k,v)!=v for k,v in defaults.items()):return False
    if e.get('blendMode','normal')!='normal' or (e.get('chromaKey') or {}).get('enabled'):return False
    audio=graph.get('audio_mix')
    if audio is None:return True
    if len(audio)!=1:return False
    a=audio[0]
    return (Path(a['source_path']).resolve()==Path(media_path).resolve() and a['source_in_ms']==0
        and a['timeline_in_ms']==0 and a['timeline_out_ms']==c['timeline_out_ms']
        and a.get('gain_db',0)==0 and a.get('playback_rate',1)==1)
