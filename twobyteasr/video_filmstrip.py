"""Progressive viewport filmstrips, fair across clips and independent of playback."""
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from PySide6.QtCore import QObject,QRectF,Qt,Signal,QTimer
from PySide6.QtGui import QImage,QPixmap,QColor,QPen


@dataclass(frozen=True)
class FilmstripView:
    source: str
    visible: tuple[int, ...]
    prefetch: tuple[int, ...] = ()
    focus_ms: int = 0
    owner: str = ''
    source_in_ms: int = 0
    source_out_ms: int = 0
    lod_ms: int = 1000


FILMSTRIP_LODS_MS = (125,250,500,1000,2000,5000,10000,20000,30000,60000,120000,300000,600000)


def filmstrip_lod_ms(pixels_per_second, height=40):
    ideal = max(1, height*16/9*1000/max(.001,pixels_per_second))
    return min(FILMSTRIP_LODS_MS,key=lambda step:abs(math.log(step/ideal)))


def filmstrip_tiles(left,right,visible_left,visible_right,source_in,source_out,height):
    """Discrete source-time LOD cells; zoom requests real subsecond samples."""
    scale=(right-left)/max(1,source_out-source_in)
    if scale<=0:return []
    step=filmstrip_lod_ms(scale*1000,height)
    first=math.floor((source_in+(max(left,visible_left)-left)/scale)/step)*step
    result=[]
    for source in range(first,int(source_out)+step,step):
        x=left+(source-source_in)*scale
        if x>=min(right,visible_right):break
        end=min(right,x+step*scale)
        if end>visible_left:
            result.append((max(left,x),end,max(int(source_in),min(int(source_out)-1,source))))
    return result


class FilmstripCache(QObject):
    updated=Signal(str)
    _ready=Signal(str,object,int)

    # 一次超时/EOF 不该把格子判死刑：有限次数退避重试后才是永久失败。
    MAX_FAILED_ATTEMPTS=3
    RETRY_DELAY_S=2.0

    def __init__(self,parent=None,*,cache_root=None,memory_bytes=32*1024*1024):
        super().__init__(parent)
        from .studio_project import studio_data_root
        self.root=Path(cache_root) if cache_root else studio_data_root()/'filmstrip-v3'
        self.limit=memory_bytes;self.bytes=0;self.memory=OrderedDict();self.identities={}
        self.condition=threading.Condition();self.wanted={};self.completed=set();self.failed=set()
        self.attempts={};self.retry_after={}
        self.closed=False;self.paused=False;self.generation=0;self.view_key=None
        self.last_source=''
        self.trace=[];self.started=time.perf_counter();self.view_changed=self.started
        self.views=();self.refined=set();self.idle_cursor={};self.last_idle=0.;self.interacting=False
        self.samples={}
        # Sorted per-source index over ``samples`` for nearest-cell lookups;
        # rebuilt after ``_samples_version`` changes (paint never rescans).
        self._samples_version={};self._sample_index={}
        self.metrics=dict(decoded=0,disk_hits=0,memory_hits=0,cancelled=0,batches=0,errors=0,opens=0,source_frames=0,refined=0,idle_generated=0)
        self._ready.connect(self._accept)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(16)
        self.timer.timeout.connect(lambda:self.updated.emit('batch'))
        self.thread=threading.Thread(target=self._work,daemon=True,name='viewport-filmstrip')
        self.thread.start();self.destroyed.connect(lambda *_:self.close())

    def identity(self,source):
        now=time.monotonic();entry=self.identities.get(source)
        if entry and now-entry[0]<1:return entry[1]
        try:
            path=Path(source);stat=path.stat()
            value=hashlib.sha256(f'{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|srgb-v1'.encode()).hexdigest()[:24]
        except OSError:value=hashlib.sha256(str(source).encode()).hexdigest()[:24]+'-missing'
        self.identities[source]=(now,value)
        return value

    def _decode_source(self,source):
        """FLV 抽帧一律走无损优化副本；remux 未就绪返回 None（退避等待）。

        key/身份永远基于原始（canonical）路径——绘制端查询的就是它；
        解码在 worker 内解析优化副本。此前 collect 侧把视图路由到
        optimized/proxy 身份、paint 侧查 canonical 身份，两者永不相等，
        解码出的格子永远画不上（FLV 缩略图长期占位的深层根因），
        且代理重建还会整批换 key。remux 失败时退回原始文件（慢但可用）。
        """
        if not source.lower().endswith('.flv'):
            return source
        from .indexed_media import GLOBAL_INDEXED_MEDIA
        optimized = GLOBAL_INDEXED_MEDIA.optimized_target(source)
        if optimized is not None:
            return str(optimized)
        return source

    def key(self,source,source_ms,width=128,lod_ms=1000):
        return f'{self.identity(source)}-t{max(0,int(source_ms))}-{width}x72-lod{int(lod_ms)}-srgb3'

    def get(self,source,source_ms,width=128,*,request_missing=True,lod_ms=1000):
        identity=self.identity(source)
        key=f'{identity}-t{max(0,int(source_ms))}-{width}x72-lod{int(lod_ms)}-srgb3'
        image=self.memory.get(key)
        if image is None:
            # Keep old coarse cells visible while the current LOD is filled.
            # This lookup never starts jobs and never reads the disk on paint.
            nearest=self._nearest_sample(identity,source_ms,lod_ms)
            if nearest is not None:
                key=nearest
                image=self.memory.get(key)
        if image is not None:
            self.memory.move_to_end(key);self.metrics['memory_hits']+=1
        # paint is a consumer only. The complete viewport demand is published
        # before drawing either track; V1 paint order cannot steal V2's turn.
        return image

    def _nearest_sample(self,identity,source_ms,lod_ms):
        """Closest decoded cell within its LOD window (bisect, not a full scan:
        at 4x every missing cell of every paint scanned all samples)."""
        entries=self.samples.get(identity)
        if not entries:return None
        version=self._samples_version.get(identity,0)
        index=self._sample_index.get(identity)
        if index is None or index[0]!=version or index[1]!=len(entries):
            ordered=sorted(entries,key=lambda sample:sample[0])
            index=(version,len(entries),[sample[0] for sample in ordered],ordered)
            self._sample_index[identity]=index
        times,ordered=index[2],index[3]
        position=bisect_left(times,source_ms)
        best=None
        for offset in range(max(0,position-8),min(len(ordered),position+8)):
            ms,lod,candidate=ordered[offset]
            distance=abs(ms-source_ms)
            if candidate in self.memory and distance<=max(lod,lod_ms) and (best is None or distance<best[0]):
                best=(distance,candidate)
        return best[1] if best is not None else None

    def set_view(self,views):
        # Compatibility for callers with explicit short source spans. Production
        # passes pixel-derived FilmstripView cells, never a whole second range.
        views=tuple(v if isinstance(v,FilmstripView) else FilmstripView(v[0],tuple(range(max(0,int(v[1])//1000)*1000,int(v[2]),1000))) for v in views)
        view_key=tuple((self.identity(v.source),v.visible,v.prefetch,v.owner,v.source_in_ms,v.source_out_ms,v.lod_ms) for v in views)
        if view_key==self.view_key:
            # A playhead move reprioritizes unfinished cells without throwing
            # away useful viewport work or restarting the decoder generation.
            with self.condition:
                if tuple(v.focus_ms for v in views)!=tuple(v.focus_ms for v in self.views):
                    focus={v.owner or v.source:v.focus_ms for v in views}
                    self.wanted={k:(*job[:5],abs(job[2]-focus.get(job[4],0)),job[6]) for k,job in self.wanted.items()}
                    self.views=views
            return
        wanted={}
        for view in views:
            visible=tuple(dict.fromkeys(view.visible))
            representatives={visible[i] for i in (0,len(visible)//2,len(visible)-1)} if visible else set()
            has_prior=bool(self.samples.get(self.identity(view.source)))
            for source_ms in visible+view.prefetch:
                priority=0 if source_ms in representatives and not has_prior else 1 if source_ms in visible else 2
                key=self.key(view.source,source_ms,lod_ms=view.lod_ms)
                value=(priority,view.source,max(0,int(source_ms)),128,view.owner or view.source,abs(source_ms-view.focus_ms),view.lod_ms)
                if key not in wanted or priority<wanted[key][0]:wanted[key]=value
        with self.condition:
            self.view_key=view_key;self.wanted=wanted;self.generation+=1
            self.views=views
            self.view_changed=time.perf_counter()
            self.failed.intersection_update(wanted)
            self.completed.intersection_update(self.memory)
            # 离开视口的格子重置重试预算（回滚回来时重新开始，而不是继承
            # 旧的失败计数），到期的重试项清掉避免无限增长。
            now=time.perf_counter()
            self.attempts={k:v for k,v in self.attempts.items() if k in wanted}
            self.retry_after={k:t for k,t in self.retry_after.items() if k in wanted and t>now}
            self.condition.notify_all()

    def _fail(self,key,reason=''):
        """Bounded backoff retry instead of a one-shot permanent failure."""
        with self.condition:
            count=self.attempts.get(key,0)+1
            self.attempts[key]=count
            permanent=count>=self.MAX_FAILED_ATTEMPTS
            if permanent:self.failed.add(key)
            else:self.retry_after[key]=time.perf_counter()+self.RETRY_DELAY_S
        # 解码失败必须可诊断：此前异常被静默吞掉，格子永久占位还无迹可查。
        try:
            from .runtime_trace import GLOBAL_STUDIO_TRACE
            GLOBAL_STUDIO_TRACE.emit('FilmstripDecode',{
                'key':key[-48:],'attempt':count,'permanent':permanent,
                'reason':str(reason)[-200:],
            })
        except Exception:
            pass

    def set_paused(self,paused):
        with self.condition:
            self.paused=bool(paused);self.note_activity();self.condition.notify_all()
        if not paused:self.updated.emit('resume')

    def note_activity(self):
        self.view_changed=time.perf_counter()

    def set_interacting(self,active):
        self.interacting=bool(active)
        self.note_activity()

    def _accept(self,key,image,generation):
        if self.closed or generation!=self.generation or key not in self.wanted:
            with self.condition:self.completed.discard(key)
            return
        if image.isNull():
            # 空图既不能显示也不能算成功（旧逻辑会把它留在 completed 里，
            # 该格子整会话占位且永不重试）。
            with self.condition:self.completed.discard(key)
            self._fail(key,'null_image')
            return
        with self.condition:
            self.attempts.pop(key,None)
            self.retry_after.pop(key,None)
        pixmap=QPixmap.fromImage(image)
        old=self.memory.pop(key,None)
        if old is not None:self.bytes-=old.width()*old.height()*4
        self.memory[key]=pixmap;self.bytes+=pixmap.width()*pixmap.height()*4
        job=self.wanted.get(key)
        if job:
            identity=key.split('-')[0]
            self.samples.setdefault(identity,set()).add((job[2],job[6],key))
            self._samples_version[identity]=self._samples_version.get(identity,0)+1
        while self.bytes>self.limit and len(self.memory)>1:
            previous,value=self.memory.popitem(last=False);self.bytes-=value.width()*value.height()*4
            self.completed.discard(previous)
            identity=previous.split('-')[0]
            if identity in self.samples:
                self.samples[identity]={sample for sample in self.samples[identity] if sample[2]!=previous}
                self._samples_version[identity]=self._samples_version.get(identity,0)+1
        if not self.paused and not self.timer.isActive():self.timer.start()

    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()

    def _cancelled(self,generation):
        return self.closed or self.paused or generation!=self.generation

    def _deliver(self,key,image,generation):
        if self._cancelled(generation):return
        with self.condition:self.completed.add(key)
        self._ready.emit(key,image,generation)

    def _idle_job(self):
        """Lazy one-at-a-time refinement/seconds, never a startup prerequisite."""
        now=time.perf_counter()
        if self.interacting or now-self.view_changed<5 or now-self.last_idle<.2:return None
        # This thread owns its decoder. Don't spend even idle decode budget
        # while the machine is busy with rendering/recognition/other work.
        import psutil
        if psutil.cpu_percent()>40:return None
        self.last_idle=now
        pending=[(key,job) for key,job in self.wanted.items() if job[0]<2 and key not in self.refined and key not in self.failed]
        if pending:
            owners=sorted({job[4] for key,job in pending})
            owner=next((s for s in owners if s>self.last_source),owners[0])
            key,job=next(item for item in pending if item[1][4]==owner)
            return key,(3,*job[1:])
        # No idle whole-source crawl. Only the current viewport and its bounded
        # prefetch region may own decode work, even after a long pause.
        return None

    def _work(self):
        # Keep containers open across turns. Sparse viewport cells seek directly
        # to nearby keyframes; don't decode hundreds of invisible frames between
        # cells. This is a preview cache, not an exact frame extraction service.
        import ctypes,sys
        if sys.platform=='win32':
            kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentThread.restype=ctypes.c_void_p
            kernel.SetThreadPriority.argtypes=[ctypes.c_void_p,ctypes.c_int]
            # Background mode also starves disk I/O and made cold first paint
            # take seconds. Below-normal CPU plus explicit playback suspension
            # is sufficient without globally throttling each media read.
            kernel.SetThreadPriority(kernel.GetCurrentThread(),-1)
        import av
        self.root.mkdir(parents=True,exist_ok=True)
        containers=OrderedDict()
        container_leases={}
        decoders={}
        try:
            while True:
                with self.condition:
                    now=time.perf_counter()
                    jobs=[(key,value) for key,value in self.wanted.items()
                          if key not in self.completed and key not in self.failed
                          and self.retry_after.get(key,0.0)<=now]
                    jobs.extend((key,(3,*value[1:])) for key,value in self.wanted.items()
                                if value[0]<2 and key in self.completed and key not in self.refined and key not in self.failed)
                    if self.closed:return
                    if self.paused:self.condition.wait(.05);continue
                    if not jobs:
                        idle=self._idle_job()
                        if idle is None:self.condition.wait(.05);continue
                        key,job=idle;priority=job[0];owner=job[4]
                    else:
                        # Refine the three coarse representatives in the same
                        # chronological pass as other visible exact samples.
                        # Deferring them until after prefetch caused backward
                        # GOP re-decodes and delayed completion of the viewport.
                        rank=lambda job:1 if job[0]==3 else job[0]
                        priority_rank=min(rank(v) for k,v in jobs)
                        owners=sorted({v[4] for k,v in jobs if rank(v)==priority_rank})
                        owner=next((s for s in owners if s>self.last_source),owners[0])
                        key,job=min((item for item in jobs if rank(item[1])==priority_rank and item[1][4]==owner),key=lambda item:(item[1][2],item[1][5]))
                        priority=job[0]
                    self.last_source=owner;generation=self.generation
                job_started=time.perf_counter()
                try:
                    destination=self.root/(key+'.jpg')
                    if destination.is_file():
                        from .storage_service import register_cache
                        register_cache(destination, 'thumbnail', producer='video_filmstrip', source=job[4])
                    image=QImage(str(destination)) if priority<3 and destination.is_file() else QImage()
                    if not image.isNull():
                        metadata=destination.with_suffix('.json')
                        if metadata.is_file() and json.loads(metadata.read_text('utf8')).get('exact'):self.refined.add(key)
                        self.metrics['disk_hits']+=1;self._deliver(key,image,generation);continue
                    if self._cancelled(generation):continue
                    source=job[1]
                    identity=key.split('-')[0]
                    decode_source=self._decode_source(source)
                    if decode_source is None:
                        # FLV 优化副本尚未就绪：不扫原始大文件、不计失败，
                        # 1s 退避等 remux 完成（worker 下轮自动重解析）。
                        with self.condition:self.retry_after[key]=time.perf_counter()+1.0
                        continue
                    handle_key=(decode_source,identity)
                    if handle_key not in containers:
                        # 3s 开窗余量：波形全量解码与缩略图常共用优化副本，
                        # 冷盘/IO 风暴下 1s 超时曾把整批可视格打成永久失败。
                        from .storage_service import cache_lease
                        lease=cache_lease(decode_source);lease.__enter__()
                        try:
                            container=av.open(decode_source,timeout=(3.,3.))
                        except Exception:
                            lease.__exit__(None,None,None)
                            raise
                        container_leases[handle_key]=lease
                        stream=container.streams.video[0]
                        # Full-frame decoding is required for dense subsecond
                        # samples; frame threading avoids serial slice-only H264.
                        stream.codec_context.thread_count=4
                        stream.codec_context.thread_type='AUTO'
                        stream.codec_context.skip_frame='NONKEY'
                        containers[handle_key]=(container,stream)
                        self.metrics['opens']+=1
                        while len(containers)>4:
                            old_handle,old_container=containers.popitem(last=False)
                            old_container[0].close()
                            container_leases.pop(old_handle).__exit__(None,None,None)
                            decoders.pop(old_handle,None)
                    containers.move_to_end(handle_key)
                    container,stream=containers[handle_key]
                    exact = priority != 0
                    stream.codec_context.skip_frame='DEFAULT' if exact else 'NONKEY'
                    origin=container.start_time or 0
                    self.metrics['batches']+=1
                    target=job[2]/1000
                    prior=decoders.get(handle_key) if exact else None
                    if prior and job[2]>=prior[2] and 0<=target-prior[3]<=2:
                        decoder,frame=prior[:2]
                    else:
                        stale=decoders.pop(handle_key,None)
                        if stale is not None:stale[0].close()
                        container.seek(int((target+origin/1e6)/stream.time_base),stream=stream,backward=True)
                        decoder=container.decode(stream)
                        frame=next(decoder,None)
                    if exact:
                        while frame is not None and frame.pts is not None and float(frame.pts*frame.time_base)-origin/1e6 < target-.001:
                            if self._cancelled(generation):break
                            self.metrics['source_frames']+=1
                            frame=next(decoder,None)
                    if self._cancelled(generation):
                        self.metrics['cancelled']+=1
                        decoders.pop(handle_key,None)
                        decoder.close()
                        continue
                    if frame is None:
                        self._fail(key,'eof_before_target')
                        continue
                    pts_seconds=float(frame.pts*frame.time_base)-origin/1e6
                    if exact:decoders[handle_key]=(decoder,frame,job[2],pts_seconds)
                    else:
                        decoders.pop(handle_key,None)
                        decoder.close()
                    self.metrics['source_frames']+=1
                    from .video_decode_worker import display_bgra
                    w,h,pixels=display_bgra(frame,float(stream.sample_aspect_ratio or 1),(128,72))
                    image=QImage(pixels,w,h,w*4,QImage.Format_ARGB32).copy()
                    # Deliver before JPEG/disk work, independently for each clip.
                    self.metrics['decoded']+=1
                    if exact:self.metrics['refined']+=1;self.refined.add(key)
                    if priority==4:self.metrics['idle_generated']+=1
                    if priority<4:self._deliver(key,image,generation)
                    else:self.completed.add(key)
                    if len(self.trace)<4096:self.trace.append(dict(ms=round((time.perf_counter()-self.started)*1000,2),owner=owner,
                        requested_ms=job[2],pts_ms=round(float(frame.pts*frame.time_base)*1000-origin/1000),priority=priority,generation=generation,lod_ms=job[6],exact=exact,
                        job_ms=round((time.perf_counter()-job_started)*1000,2)))
                    if not self._cancelled(generation):
                        temporary=self.root/(key+'.part')
                        if image.save(str(temporary),'JPG',82):
                            temporary.replace(destination)
                            from .storage_service import register_cache
                            register_cache(destination, 'thumbnail', producer='video_filmstrip', source=job[4])
                            from .storage_service import register_cache
                            register_cache(destination,'thumbnail',source=source,producer='video_filmstrip')
                            destination.with_suffix('.json').write_text(json.dumps({'exact':exact,'requested_ms':job[2],'lod_ms':job[6],
                                'pts_ms':round(float(frame.pts*frame.time_base)*1000-origin/1000)}),encoding='utf8')
                            register_cache(destination.with_suffix('.json'), 'thumbnail', producer='video_filmstrip', source=job[4])
                except Exception as exc:
                    self.metrics['errors']+=1
                    self._fail(key,exc)
                    if len(self.trace)<4096:self.trace.append(dict(error=str(exc),key=key,generation=generation))
        finally:
            for container,stream in containers.values():container.close()
            for lease in container_leases.values():lease.__exit__(None,None,None)

    def paint(self,painter,block,source,left,right,source_in,source_out):
        painter.save();painter.setClipRect(block,Qt.ClipOperation.IntersectClip)
        lod=filmstrip_lod_ms((right-left)*1000/max(1,source_out-source_in),block.height())
        for x,end,source_ms in filmstrip_tiles(left,right,block.left(),block.right(),source_in,source_out,block.height()):
            pixmap=self.get(source,source_ms,lod_ms=lod)
            cell=QRectF(x,block.top(),max(1,end-x),block.height())
            if pixmap is not None:painter.drawPixmap(cell.toRect(),pixmap,pixmap.rect())
            else:
                painter.fillRect(cell,QColor(255,255,255,12))
                painter.setPen(QPen(QColor(235,241,242,55),1))
                center=cell.center();painter.drawRect(QRectF(center.x()-7,center.y()-5,14,10))
            painter.setPen(QPen(QColor(0,0,0,55),1));painter.drawLine(round(end),round(block.top()),round(end),round(block.bottom()))
        painter.restore()
