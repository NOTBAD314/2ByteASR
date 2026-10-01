"""Event-driven selection geometry from the renderer's final caption pixels."""
from __future__ import annotations
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading

from PySide6.QtCore import QObject, QRectF, QTimer, Signal
from PySide6.QtGui import QImage


def alpha_bounds(png, subject=None):
    from PIL import Image
    image = Image.open(io.BytesIO(png)).convert('RGBA')
    alpha = image.getchannel('A')
    if subject:
        import math
        if len(subject)!=4 or any(not isinstance(n,(int,float)) or not math.isfinite(n) for n in subject):
            return None
        x,y,w,h=subject
        region=(max(0,math.floor(x)),max(0,math.floor(y)),min(image.width,math.ceil(x+w)),min(image.height,math.ceil(y+h)))
        if region[2]<=region[0] or region[3]<=region[1]: return None
        box=alpha.crop(region).getbbox()
        if box: box=(box[0]+region[0],box[1]+region[1],box[2]+region[0],box[3]+region[1])
    else: box=alpha.getbbox()
    return [box[0],box[1],box[2]-box[0],box[3]-box[1]] if box else None


def image_bounds(image):
    from PIL import Image
    image=image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw=bytes(image.constBits())
    alpha=Image.frombytes('RGBA',(image.width(),image.height()),raw,'raw','RGBA',image.bytesPerLine()).getchannel('A')
    box=alpha.getbbox()
    return [box[0],box[1],box[2]-box[0],box[3]-box[1]] if box else None


def measure_native(project, cue_id, width, height):
    """Use the real ASS compiler and libass alpha raster, including font metrics."""
    from .ass_compiler import compile_ass
    from .advanced_renderer import _ffmpeg_filter_path
    from .runtime_paths import detect_install_root
    from .processes import run_hidden_subprocess
    from .studio_project import studio_data_root
    install=detect_install_root()
    root=studio_data_root()/'cache/selection-geometry';root.mkdir(parents=True,exist_ok=True)
    project.cues=[c for c in project.cues if c.id==cue_id]
    cue=project.cues[0];cue.start_ms=0;cue.end_ms=1000
    with tempfile.TemporaryDirectory(dir=root) as folder:
        ass=Path(folder)/'selected.ass';ass.write_text(compile_ass(project),encoding='utf-8-sig')
        command=[str(install/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','verbose','-f','lavfi','-i',
                 f'color=c=black@0.0:s={width}x{height}:r=1,format=rgba',
                 '-vf',f'ass=filename={_ffmpeg_filter_path(ass)}:fontsdir={_ffmpeg_filter_path(install/"assets/fonts")}:alpha=1',
                 '-frames:v','1','-threads','1','-c:v','png','-f','image2pipe','pipe:1']
        result=run_hidden_subprocess(command,capture_output=True,check=True,timeout=12,purpose='selected caption geometry')
        return dict(bounds=alpha_bounds(result.stdout),viewport=[width,height],renderer='libass',
                    font_selection=[l for l in result.stderr.decode('utf8',errors='replace').splitlines() if 'fontselect:' in l],
                    ass_styles=[l for l in ass.read_text('utf-8-sig').splitlines() if l.startswith('Style:')])


class SelectionGeometryController(QObject):
    completed=Signal(object,object)

    def __init__(self, page):
        super().__init__(page)
        self.page=page;self.overlay=page.position_overlay
        self.key=None;self.pending=None;self.worker=None;self.measurements=0
        self.overlay._requires_measured_bounds=True
        self.completed.connect(self._accept)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(90)
        self.timer.timeout.connect(self._measure)

    def sync(self,cue,recipe):
        recipe=recipe or {}
        self.overlay._web_theme_transform = bool(recipe.get('webTheme'))
        if self.overlay._dragging:
            return  # Freeze the measured handle geometry for this transaction.
        p=self.page;content=self.overlay._content_rect()
        if not cue or p.selected_cue_id!=cue.id or not getattr(p.video,'_paused',True):return
        web=getattr(p,'_web_live_worker',None) if recipe.get('webTheme') else None
        canvas=getattr(p,'advanced_cue_overlay',None)
        # Native text is temporarily promoted to the existing live canvas
        # during a drag. Measure that final raster while it owns visibility.
        pixmap=getattr(canvas,'_display_source',None) if canvas is not None and canvas.isVisible() and not web else None
        image=pixmap.toImage() if pixmap is not None else None
        snap=getattr(canvas,'_snapshot',None)
        # The renderer may normalize newlines in its snapshot. Its visible
        # raster remains authoritative until the next snapshot is published.
        if image is not None and (snap is None or snap.cue_id!=cue.id):image=None
        signature=(id(p.project),cue.id,repr(cue),repr(p.project.styles),repr(recipe),
                   repr(getattr(p,'_live_transform_overrides',{})),repr(getattr(p,'_live_edit_text_overrides',{})),
                   tuple(content.getRect()),p.video.devicePixelRatioF(),
                   id(web),getattr(web,'_configuration_generation',0),
                   getattr(getattr(web,'_time_provider',None),'discontinuity_generation',lambda:None)(),
                   image.cacheKey() if image is not None else None)
        if signature==self.key:return
        self.key=signature;self.pending=(cue.id,web,QImage(image) if image is not None else None)
        self.overlay.set_measured_bounds(None)
        self.timer.start()

    def _measure(self):
        p=self.page
        if not self.pending or not self.overlay.isVisible() or not getattr(p.video,'_paused',True):return
        cue_id,web,image=self.pending;key=self.key
        if p.selected_cue_id!=cue_id:return
        self.measurements+=1
        if web:
            if self.worker is not web:
                self.worker=web
                web.selection_geometry_ready.connect(self._web_ready)
            web.request_selection_geometry(key)
            return
        if image is not None and not image.isNull():
            self._accept(key,dict(bounds=image_bounds(image),viewport=[image.width(),image.height()],renderer='live-raster'))
            return
        project=p._ass_preview_snapshot(p.project)
        if not any(c.id==cue_id for c in project.cues):return
        content=self.overlay._content_rect();dpr=p.video.devicePixelRatioF()
        width=max(2,round(content.width()*dpr));height=max(2,round(content.height()*dpr))
        def work():
            try:data=measure_native(project,cue_id,width,height)
            except Exception as exc:data=dict(error=str(exc),renderer="libass")
            try:self.completed.emit(key,data)
            except RuntimeError:pass  # The owning page may close during libass measurement.
        threading.Thread(target=work,daemon=True,name='selection-geometry').start()

    def _web_ready(self,key,data):
        self._accept(key,data)

    def _accept(self,key,data):
        p=self.page
        if (key!=self.key or p.selected_cue_id!=key[1] or not getattr(p.video,'_paused',True)
                or not self.overlay.isVisible()):return
        content=self.overlay._content_rect();box=data.get('bounds')
        if box:
            width,height=data['viewport'];x,y,w,h=box
            rect=QRectF(content.x()+x*content.width()/width,content.y()+y*content.height()/height,
                        w*content.width()/width,h*content.height()/height)
            self.overlay.set_measured_bounds(rect)
        diagnostic=dict(data,selected_id=p.selected_cue_id,
            content_rect=list(content.getRect()),preview_viewport=[p.video.width(),p.video.height()],
            project_resolution=[p.project.media.width,p.project.media.height],dpr=p.video.devicePixelRatioF(),
            preview_scale=[content.width()/max(1,p.project.media.width),content.height()/max(1,p.project.media.height)],
            overlay_rect=list(self.overlay._subtitle_rect().getRect()),measurement_count=self.measurements)
        from .studio_design_target import design_cue
        cue = design_cue(p.project, key[1])
        if cue is None:
            return
        diagnostic['theme_id']=str((p.project.style_recipes.get(cue.style_id,{})
                                    .get('webTheme') or {}).get('id',''))
        self.overlay.geometry_diagnostics=diagnostic
        if os.environ.get('TWOBYTEASR_SELECTION_DIAGNOSTICS')=='1':
            from .studio_project import studio_data_root
            path=studio_data_root()/'logs/selection-geometry.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('a',encoding='utf8') as f:f.write(json.dumps(diagnostic,ensure_ascii=False,default=str)+'\n')
