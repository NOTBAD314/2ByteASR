"""Latest native subtitle rasters, with private buffers and revocable publishes."""
from collections import OrderedDict
from pathlib import Path
import threading
import uuid
from PySide6.QtCore import QRect,Qt
from PySide6.QtGui import QImage,QPainter


class SubtitleRasterPublisher:
    def __init__(self,folder):
        self.folder=Path(folder);self.condition=threading.Condition();self.pending=OrderedDict()
        self.epochs={};self.closed=False
        self.identity=uuid.uuid4().hex[:12]
        self.thread=threading.Thread(target=self._run,daemon=True,name='subtitle-raster-publisher');self.thread.start()

    def submit(self,overlay_id,image,rect,opacity,controller,*,cue_id=''):
        with self.condition:
            if self.closed:return False
            epoch=self.epochs.get(overlay_id,0)
            self.pending[overlay_id]=(epoch,QImage(image),QRect(rect),opacity,controller,cue_id)
            self.condition.notify()
        return True

    def current(self,overlay_id,epoch):
        return not self.closed and self.epochs.get(overlay_id,0)==epoch

    def revoke(self,overlay_id):
        with self.condition:
            self.epochs[overlay_id]=self.epochs.get(overlay_id,0)+1
            self.pending.pop(overlay_id,None)

    def close(self):
        with self.condition:self.closed=True;self.pending.clear();self.condition.notify()

    def _run(self):
        from .overlay_buffer import OverlayBuffer
        import numpy as np
        buffers={};slots={}
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.closed or self.pending)
                    if self.closed:return
                    overlay_id,(epoch,image,target,opacity,controller,cue_id)=self.pending.popitem(last=False)
                if not self.current(overlay_id,epoch) or not controller.running:continue
                try:
                    image=image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                    if opacity<.999:
                        faded=QImage(image.size(),QImage.Format_ARGB32_Premultiplied);faded.fill(Qt.transparent)
                        painter=QPainter(faded);painter.setOpacity(opacity);painter.drawImage(0,0,image);painter.end();image=faded
                    alpha=np.ndarray((image.height(),image.width(),4),dtype=np.uint8,buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))[:,:,3]
                    rows=np.flatnonzero(np.any(alpha,axis=1));cols=np.flatnonzero(np.any(alpha,axis=0))
                    bounds=QRect(int(cols[0]),int(rows[0]),int(cols[-1]-cols[0]+1),int(rows[-1]-rows[0]+1)) if rows.size and cols.size else QRect(0,0,1,1)
                    display=QRect(round(target.x()+bounds.x()*target.width()/image.width()),round(target.y()+bounds.y()*target.height()/image.height()),
                        max(1,round(bounds.width()*target.width()/image.width())),max(1,round(bounds.height()*target.height()/image.height())))
                    cropped=image.copy(bounds);pixels=cropped.constBits();slot=1-slots.get(overlay_id,1)
                    key=(overlay_id,slot);buffer=buffers.get(key)
                    if buffer is None or buffer.capacity<len(pixels):
                        if buffer is not None:buffer.close()
                        self.folder.mkdir(parents=True,exist_ok=True)
                        buffer=buffers[key]=OverlayBuffer(self.folder/f'native-{self.identity}-{overlay_id}-{slot}.rgba',len(pixels))
                    buffer.write(pixels)
                    if not self.current(overlay_id,epoch):continue
                    acknowledged=threading.Event()
                    posted=controller.post_raw_overlay(overlay_id,buffer.path,
                        cue_id=cue_id,
                        valid_when=lambda oid=overlay_id,gen=epoch:self.current(oid,gen),
                        on_applied=lambda ok,event=acknowledged:event.set(),
                        coalesce_key=f'native-subtitle:{overlay_id}',x=display.x(),y=display.y(),
                        width=cropped.width(),height=cropped.height(),stride=cropped.bytesPerLine(),
                        display_width=display.width(),display_height=display.height())
                    # No slot can be overwritten while mpv still reads it.
                    while posted and not acknowledged.wait(.005) and controller.running:pass
                    slots[overlay_id]=slot
                except (OSError,RuntimeError,ValueError):
                    continue
        finally:
            for buffer in buffers.values():buffer.close()
