"""Export-only timestamp index and sequential decoder.

Preview's latest-frame mailbox is intentionally not an export RPC. This reader
owns its container, retains one past/one future frame, and returns a receipt for
every request, including two timeline samples that address the same source PTS.
"""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from functools import lru_cache
import json
import os
import time
import uuid
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


def probe_media(ffmpeg, path, *, cancelled=None):
    try:
        stat = Path(path).stat()
        return _probe(str(ffmpeg), str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, cancelled)
    except (InterruptedError, ExportMediaError):
        raise
    except Exception as exc:
        raise ExportMediaError('MEDIA_PROBE', {'path':str(path)}, exc) from exc


@lru_cache(maxsize=24)
def _probe(ffmpeg, path, size, modified, cancelled):
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
    def __init__(self, index, *, backend='cpu'):
        from .video_decode_worker import open_decoder
        self.index=index
        self.container,self.stream,self.backend=open_decoder(index.path,backend)
        self.container.seek(0,stream=self.stream,backward=True)
        self.frames=iter(self.container.decode(self.stream));self.current=None;self.future=None
        self.last_target=None;self.request_id=0;self.generation=uuid.uuid4().hex
        self.eof=False;self.cached=None;self.cached_pts=None

    def read(self, seconds, *, context=None):
        from .video_decode_worker import display_bgra
        self.request_id+=1;started=time.perf_counter()
        receipt=dict(context or {}, request_id=self.request_id, generation=self.generation,
            decoder_pid=os.getpid(), command_type='export_frame', source_ms=float(seconds)*1000,
            time_base=str(self.index.time_base), source_duration=float(self.index.last+self.index.interval),
            worker_restarts=0,retries=0,**self.backend)
        try:
            target=self.index.target(seconds)+self.index.origin
            receipt['boundary_clamped']=target != Fraction(seconds)+self.index.origin
            if self.last_target is not None and target<self.last_target:
                self.container.seek(int(target/self.index.time_base),stream=self.stream,backward=True)
                self.frames=iter(self.container.decode(self.stream));self.current=self.future=None;self.eof=False
            self.last_target=target
            while not self.eof:
                if self.future is None:
                    try: self.future=next(self.frames)
                    except StopIteration: self.eof=True;break
                if self.future.pts*self.future.time_base>target:
                    if self.current is None: self.current=self.future
                    break
                self.current,self.future=self.future,None
            if self.current is None: raise ValueError('no frame at target')
            pts=self.current.pts
            if self.cached_pts != pts:
                self.cached=display_bgra(self.current,float(self.stream.sample_aspect_ratio or 1),
                    (max(self.current.width,self.current.height)*16,)*2)
                self.cached_pts=pts
            receipt.update(frame_pts=pts,frame_seconds=float(pts*self.current.time_base-self.index.origin),
                next_pts=self.future.pts if self.future else None, state='FRAME', eof=self.eof,
                elapsed_ms=(time.perf_counter()-started)*1000)
            return self.cached,receipt
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
