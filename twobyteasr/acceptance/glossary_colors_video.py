"""Decode every frame and compare the actual short export with its saved Qt preview."""
from pathlib import Path
import argparse
import json
import os
import subprocess


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('owned tmp output required')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'decode-profile');os.environ['QT_QPA_PLATFORM']='offscreen'
    from ..test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase,QImage,QPainter
    from PySide6.QtCore import QByteArray
    app=QApplication.instance() or QApplication([])
    for name in ('SourceHanSansSC-Heavy.otf','SourceHanSansSC-Medium.otf'):
        QFontDatabase.addApplicationFontFromData(QByteArray((root/'assets/fonts'/name).read_bytes()))
    from ..projects.studio_project import load_project
    from ..caption_style.bilingual_layout import materialize_display_project
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.advanced_live_renderer import render_live_snapshot
    from PIL import Image
    import numpy as np
    first=json.loads((out/'first-result.json').read_text('utf8'));video=Path(first['video'])
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';probe=ffmpeg.with_name('ffprobe.exe')
    info=json.loads(subprocess.check_output([str(probe),'-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,duration','-of','json',str(video)],creationflags=subprocess.CREATE_NO_WINDOW))['streams'][0]
    width,height=info['width'],info['height'];stride=width*height*3
    p=load_project(out/'colors-saved.2byteproj');p=materialize_display_project(p)
    overlay=QImage(width,height,QImage.Format_RGBA8888);overlay.fill(0)
    painter=QPainter(overlay);active=[]
    for cue in p.cues:
        if cue.start_ms<=500<cue.end_ms:
            snap=build_visual_cue_snapshot(p,cue.id,width=width,height=height,resolved_cue=cue)
            painter.drawImage(0,0,render_live_snapshot(snap,width=width,height=height));active.append(cue.id)
    painter.end()
    pixels=np.ndarray((height,width,4),np.uint8,buffer=overlay.constBits(),strides=(overlay.bytesPerLine(),4,1)).copy()
    mask=pixels[:,:,3]>30
    source=subprocess.check_output([str(ffmpeg),'-v','error','-i',p.media.path,'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],creationflags=subprocess.CREATE_NO_WINDOW)
    base=Image.frombytes('RGB',(width,height),source).convert('RGBA')
    expected=Image.alpha_composite(base,Image.fromarray(pixels,'RGBA')).convert('RGB')
    expected.save(out/'expected-preview.png');reference=np.array(expected).astype(np.int16)
    process=subprocess.Popen([str(ffmpeg),'-v','error','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    errors=[];frames=0;first_rgb=None
    try:
        while True:
            frame=process.stdout.read(stride)
            if not frame:break
            if len(frame)!=stride:raise RuntimeError('truncated decoded frame')
            rgb=np.frombuffer(frame,dtype=np.uint8).reshape(height,width,3)
            if first_rgb is None:first_rgb=rgb.copy()
            errors.append(float(np.abs(rgb.astype(np.int16)-reference)[mask].mean()))
            frames+=1
        stderr=process.stderr.read().decode('utf8','replace');code=process.wait(timeout=30)
    finally:
        process.stdout.close();process.stderr.close()
    if first_rgb is not None:Image.fromarray(first_rgb,'RGB').save(out/'actual-export.png')
    result=dict(passed=code==0 and frames>=90 and bool(mask.any()) and max(errors,default=999)<12,
        frames=frames,active_cues=active,video=str(video),preview_pixels=int(mask.sum()),mean_error=sum(errors)/max(1,len(errors)),
        max_frame_mean_error=max(errors,default=None),exit_code=code,stderr=stderr,stream=info)
    (out/'video-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8');print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
