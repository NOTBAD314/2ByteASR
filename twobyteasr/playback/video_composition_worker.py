"""Latest decoded layers -> off-GUI QImage raster -> native upload mailbox."""
from collections import deque
from copy import deepcopy
import threading
import time
from PySide6.QtCore import QRect,QRectF,Qt
from PySide6.QtGui import QImage,QPainter,QTransform


class VideoCompositionWorker:
    def __init__(self,publish):
        self.publish=publish;self.condition=threading.Condition();self.state=None;self.frames={}
        self.dirty=False;self.closed=False;self.version=0;self.signature=None
        self.samples=deque(maxlen=1200)
        self.submitted_count = 0
        self.thread=threading.Thread(target=self._run,daemon=True,name='video-raster-compositor');self.thread.start()

    def configure(self,state):
        signature=repr((state['size'],state['display_rect'],state['base'],state.get('publication_epoch'),
            [(x['clip_id'],x['path'],x['generation'],x.get('decode_epoch'),x['transform'],x['effects'],x.get('transition_fx')) for x in state['layers']])) if state else None
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

    def _submit(self, image, rect, context):
        context['raster'] = dict(width=image.width(), height=image.height(),
            stride=image.bytesPerLine(), bytes=image.sizeInBytes(), display_rect=rect.getRect())
        context['submitted_at'] = time.perf_counter()
        if self.publish(image, rect, context) is not False:
            self.submitted_count += 1
            self.samples.append(context)

    @staticmethod
    def _display_rect(state, area):
        """Map a canvas-space area to the device-pixel rectangle mpv draws."""
        x,y,w,h=state['display_rect'];width,height=state['size']
        sx,sy=w/max(1,width),h/max(1,height)
        left,top=round(x+area.left()*sx),round(y+area.top()*sy)
        return QRect(left,top,max(1,round(x+area.right()*sx)-left),max(1,round(y+area.bottom()*sy)-top))

    @staticmethod
    def _frame_context(layer, frame):
        result = dict(clip_id=layer['clip_id'],pts_ms=frame.pts_ms,generation=frame.generation,
            requested_ms=frame.requested_ms,
            decode_epoch=frame.epoch,codec_decoded_at=frame.codec_decoded_at,
            decoded_at=frame.decoded_at,received_at=frame.received_at,
            published_at=frame.published_at,write_started_at=frame.write_started_at)
        if frame.costs:
            result['pixel_costs'] = frame.costs
        return result

    def _run(self):
        from .video_compositor import layer_geometry,apply_chroma_key,_BLEND_COMPOSITION_MODES
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or (self.state is not None and self.dirty))
                if self.closed:return
                if not self.state:continue
                state=self.state;frames=dict(self.frames);version=self.version;self.dirty=False
            width,height=state['size'];start=time.perf_counter()
            canvas=QRectF(0,0,width,height)
            current=[(layer,frames.get(layer['clip_id'])) for layer in state['layers']]
            current=[(layer,frame) for layer,frame in current if frame is not None and frame.generation==layer['generation']
                     and frame.path==layer['path'] and (layer.get('decode_epoch') is None or frame.epoch==layer['decode_epoch'])]
            # A single opaque, unrotated follower inside the canvas already is
            # the final raster at any scale/position (picture-in-picture too).
            # Let mpv's GPU scale and place it instead of resampling it through
            # QPainter into a full-canvas transparent image every frame.
            direct=None
            if len(state['layers'])==1 and len(current)==1 and not state['base']:
                layer,frame=current[0]
                transform=layer['transform']
                if (float(transform.get('rotation',0.))%360==0 and float(transform.get('opacity',1.))>=1.
                        and layer['effects'].get('blendMode','normal')=='normal'
                        and not (layer['effects'].get('chromaKey') or {}).get('enabled')
                        and not layer.get('transition_fx')):
                    local,matrix=layer_geometry(width,height,layer,frame.width,frame.height)
                    placed=matrix.mapRect(local)
                    if canvas.adjusted(-.5,-.5,.5,.5).contains(placed) and placed.width()>=1 and placed.height()>=1:
                        direct=(layer,frame,placed)
            if direct:
                layer,frame,placed=direct
                image=QImage(frame.pixels,frame.width,frame.height,frame.width*4,QImage.Format_ARGB32)
                context=dict(caller='video_compositor_worker',project_ms=state['project_ms'],publication_epoch=state.get('publication_epoch'),
                    compose_start=start,compose_end=time.perf_counter(),composition_ms=(time.perf_counter()-start)*1000,
                    direct_gpu_scale=True,layers=[self._frame_context(layer,frame)])
                with self.condition:
                    if not self.closed and self.state is not None and version==self.version:
                        self._submit(image,self._display_rect(state,placed),context)
                continue
            # Paint only the area the layers can touch. A transparent canvas
            # outside that box carried no pixels but still cost a full-size
            # fill, a full-size mmap write and a full-size mpv texture upload.
            region=QRect(0,0,width,height)
            if not state['base'] and not any(layer.get('transition_fx') for layer,_ in current):
                # Transition looks (push, zoom, ...) move pixels beyond the
                # layer's resting geometry; they keep the full canvas.
                touched=QRectF()
                for layer,frame in current:
                    local,matrix=layer_geometry(width,height,layer,frame.width,frame.height)
                    touched=touched.united(matrix.mapRect(local))
                region=touched.intersected(canvas).toAlignedRect().intersected(region)
                if region.isEmpty():region=QRect(0,0,1,1)
            image=QImage(region.width(),region.height(),QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.black if state['base'] else Qt.transparent)
            painter=QPainter(image);painter.setRenderHint(QPainter.SmoothPixmapTransform)
            offset=QTransform.fromTranslate(-region.x(),-region.y())
            presented=[]
            for layer,frame in current:
                pixels=QImage(frame.pixels,frame.width,frame.height,frame.width*4,QImage.Format_ARGB32)
                effects=layer['effects'];chroma=effects.get('chromaKey')
                if isinstance(chroma,dict) and chroma.get('enabled'):pixels=apply_chroma_key(pixels,chroma)
                local,matrix=layer_geometry(width,height,layer,frame.width,frame.height)
                matrix=matrix*offset
                mode=_BLEND_COMPOSITION_MODES.get(effects.get('blendMode','normal'),QPainter.CompositionMode_SourceOver)
                if layer.get('transition_fx'):
                    from .transition_looks import paint_with_effects
                    paint_with_effects(painter,(width,height),pixels,local,matrix,layer['transition_fx'],
                                       opacity=float(layer['transform'].get('opacity',1)),mode=mode)
                else:
                    painter.save();painter.setOpacity(max(0,min(1,float(layer['transform'].get('opacity',1)))))
                    painter.setCompositionMode(mode)
                    painter.setTransform(matrix);painter.drawImage(local,pixels);painter.restore()
                presented.append(self._frame_context(layer,frame))
            painter.end();rendered=time.perf_counter()
            with self.condition:
                if not self.closed and self.state is not None and version==self.version and presented:
                    context=dict(caller='video_compositor_worker',project_ms=state['project_ms'],
                        publication_epoch=state.get('publication_epoch'),
                        compose_start=start,compose_end=rendered,layers=presented,composition_ms=(rendered-start)*1000)
                    # The queue put is nonblocking. Serialize it with revoke so
                    # an old raster cannot acquire the next visibility epoch.
                    self._submit(image,self._display_rect(state,QRectF(region)),context)
