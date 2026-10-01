"""Latest decoded layers -> off-GUI QImage raster -> native upload mailbox."""
from collections import deque
from copy import deepcopy
import threading
import time
from PySide6.QtCore import QRect,QRectF,Qt
from PySide6.QtGui import QImage,QPainter


class VideoCompositionWorker:
    def __init__(self,publish):
        self.publish=publish;self.condition=threading.Condition();self.state=None;self.frames={}
        self.dirty=False;self.closed=False;self.version=0;self.signature=None
        self.samples=deque(maxlen=1200)
        self.thread=threading.Thread(target=self._run,daemon=True,name='video-raster-compositor');self.thread.start()

    def configure(self,state):
        signature=repr((state['size'],state['display_rect'],state['base'],state.get('publication_epoch'),
            [(x['clip_id'],x['path'],x['generation'],x.get('decode_epoch'),x['transform'],x['effects']) for x in state['layers']])) if state else None
        with self.condition:
            if signature!=self.signature:
                self.version+=1;self.signature=signature;self.dirty=True
            self.state=state
            if state:self.frames={k:v for k,v in self.frames.items() if any(x['clip_id']==k for x in state['layers'])}
            self.condition.notify()

    def receive(self,clip_id,frame):
        with self.condition:
            if not self.state or self.closed:return
            expected=next((layer for layer in self.state['layers'] if layer['clip_id']==clip_id),None)
            if expected is None or frame.generation!=expected['generation'] or frame.path!=expected['path']:return
            if expected.get('decode_epoch') is not None and frame.epoch!=expected['decode_epoch']:return
            old=self.frames.get(clip_id)
            if old and old.generation==frame.generation and old.pts_ms>=frame.pts_ms:return
            self.frames[clip_id]=frame;self.dirty=True;self.condition.notify()

    def close(self):
        with self.condition:self.closed=True;self.state=None;self.frames={};self.condition.notify()

    def _run(self):
        from .video_compositor import layer_geometry,apply_chroma_key,_BLEND_COMPOSITION_MODES
        last=0
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or (self.state is not None and self.dirty))
                if self.closed:return
                delay=.016-(time.perf_counter()-last)
                if delay>0:self.condition.wait(delay)
                if not self.state:continue
                state=self.state;frames=dict(self.frames);version=self.version;self.dirty=False
            width,height=state['size'];start=time.perf_counter()
            # A single opaque, untransformed follower already is the final
            # raster. Let mpv's GPU scale it directly instead of resampling a
            # full image through QPainter and allocating a second canvas.
            direct=None
            if len(state['layers'])==1 and not state['base']:
                layer=state['layers'][0];frame=frames.get(layer['clip_id'])
                defaults=dict(position_x=.5,position_y=.5,scale_x=1.,scale_y=1.,rotation=0.,opacity=1.,anchor_x=.5,anchor_y=.5,fit_mode='contain')
                if (frame is not None and frame.generation==layer['generation'] and frame.path==layer['path']
                        and (layer.get('decode_epoch') is None or frame.epoch==layer['decode_epoch'])
                        and all(layer['transform'].get(k,v)==v for k,v in defaults.items())
                        and layer['effects'].get('blendMode','normal')=='normal'
                        and not (layer['effects'].get('chromaKey') or {}).get('enabled')
                        and abs(frame.width/frame.height-width/height)<.005):
                    direct=(layer,frame)
            if direct:
                layer,frame=direct
                image=QImage(frame.pixels,frame.width,frame.height,frame.width*4,QImage.Format_ARGB32)
                context=dict(caller='video_compositor_worker',project_ms=state['project_ms'],publication_epoch=state.get('publication_epoch'),
                    compose_start=start,compose_end=time.perf_counter(),composition_ms=(time.perf_counter()-start)*1000,
                    direct_gpu_scale=True,layers=[dict(clip_id=layer['clip_id'],pts_ms=frame.pts_ms,generation=frame.generation,
                        decode_epoch=frame.epoch,codec_decoded_at=frame.codec_decoded_at,decoded_at=frame.decoded_at,received_at=frame.received_at)])
                with self.condition:
                    if not self.closed and self.state is not None and version==self.version:
                        self.publish(image,QRect(*state['display_rect']),context);self.samples.append(context)
                last=time.perf_counter();continue
            image=QImage(width,height,QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.black if state['base'] else Qt.transparent)
            painter=QPainter(image);painter.setRenderHint(QPainter.SmoothPixmapTransform)
            presented=[]
            for layer in state['layers']:
                frame=frames.get(layer['clip_id'])
                if frame is None or frame.generation!=layer['generation'] or frame.path!=layer['path']:continue
                if layer.get('decode_epoch') is not None and frame.epoch!=layer['decode_epoch']:continue
                pixels=QImage(frame.pixels,frame.width,frame.height,frame.width*4,QImage.Format_ARGB32)
                effects=layer['effects'];chroma=effects.get('chromaKey')
                if isinstance(chroma,dict) and chroma.get('enabled'):pixels=apply_chroma_key(pixels,chroma)
                local,matrix=layer_geometry(width,height,layer,frame.width,frame.height)
                painter.save();painter.setOpacity(max(0,min(1,float(layer['transform'].get('opacity',1)))))
                painter.setCompositionMode(_BLEND_COMPOSITION_MODES.get(effects.get('blendMode','normal'),QPainter.CompositionMode_SourceOver))
                painter.setTransform(matrix);painter.drawImage(local,pixels);painter.restore()
                presented.append(dict(clip_id=layer['clip_id'],pts_ms=frame.pts_ms,generation=frame.generation,decode_epoch=frame.epoch,
                    codec_decoded_at=frame.codec_decoded_at,
                    decoded_at=frame.decoded_at,received_at=frame.received_at))
            painter.end();rendered=time.perf_counter()
            with self.condition:
                if not self.closed and self.state is not None and version==self.version and presented:
                    context=dict(caller='video_compositor_worker',project_ms=state['project_ms'],
                        publication_epoch=state.get('publication_epoch'),
                        compose_start=start,compose_end=rendered,layers=presented,composition_ms=(rendered-start)*1000)
                    # The queue put is nonblocking. Serialize it with revoke so
                    # an old raster cannot acquire the next visibility epoch.
                    self.publish(image,QRect(*state['display_rect']),context)
                    self.samples.append(context)
            last=time.perf_counter()
