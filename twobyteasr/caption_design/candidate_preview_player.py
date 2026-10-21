"""Play the already-rendered PNG sequence; never re-evaluate authored motion."""
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import QObject,Signal,QTimer,QElapsedTimer,Qt
from PySide6.QtGui import QMovie,QPixmap


class CandidatePreviewPlayer(QObject):
    frameChanged=Signal(int)

    def __init__(self,motion,*,context=False,parent=None):
        super().__init__(parent)
        overlay=motion.get('context',{}) if context else {}
        self.folder=Path(overlay['frames'] if overlay.get('background')=='current-media' else motion['transparent_frames'])
        self.fps=float(motion.get('fps',24))
        self.count=int(motion['frame_count']);self.duration=float(motion['duration_ms'])
        self.crop=None if context else motion.get('subject_bbox')
        self._frame=0;self._state=QMovie.NotRunning;self._speed=100;self._position=0.
        self.cache=OrderedDict();self.clock=QElapsedTimer()
        self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer);self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def frameCount(self):return self.count
    def currentFrameNumber(self):return self._frame
    def state(self):return self._state
    def speed(self):return self._speed
    def setCacheMode(self,*unused):pass
    def currentPixmap(self):
        if self._frame not in self.cache:
            pix=QPixmap(str(self.folder/f'{self._frame:04}.png'))
            if self.crop:
                x,y,r,b=self.crop;pix=pix.copy(x,y,r-x,b-y)
            self.cache[self._frame]=pix
            while len(self.cache)>12:self.cache.popitem(last=False)
        self.cache.move_to_end(self._frame)
        return self.cache[self._frame]
    def _now(self):
        return self._position+(self.clock.elapsed()*self._speed/100 if self._state==QMovie.Running else 0)
    def _tick(self):
        frame=min(self.count-1,int((self._now()%self.duration)*self.fps/1000))
        if frame!=self._frame:self._frame=frame;self.frameChanged.emit(frame)
    def setSpeed(self,value):
        self._position=self._now()%self.duration;self.clock.start();self._speed=value
    def jumpToFrame(self,frame):
        self._frame=max(0,min(self.count-1,int(frame)));self._position=self._frame*1000/self.fps
        self.clock.start();self.frameChanged.emit(self._frame);return True
    def start(self):self._state=QMovie.Running;self.clock.start();self.timer.start();self.frameChanged.emit(self._frame)
    def stop(self):self._position=self._now()%self.duration;self._state=QMovie.NotRunning;self.timer.stop()
    def setPaused(self,value):
        self._position=self._now()%self.duration;self._state=QMovie.Paused if value else QMovie.Running
        self.clock.start();self.timer.stop() if value else self.timer.start()
