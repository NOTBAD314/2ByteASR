"""Real libass pixels must retain authored em size, not just equal JSON numbers."""
from copy import deepcopy
from pathlib import Path
import re
import pytest
from PIL import Image, ImageFont
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.rendering.ass_font_units import ass_font_style
from twobyteasr.caption_style.font_metadata import resolve_local_face
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.projects.studio_project import SubtitleProject, SubtitleStyle, StudioMedia, StudioCue

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ['一二三四五六七', '一二三四五六七八九十甲乙丙丁戊',
         '这是怎么做到的居然还能继续上传吗', '字幕测试 Aa123，Hello！']


@pytest.mark.parametrize('text', TEXTS)
def test_real_libass_matches_actual_face_em_width_without_mutation(tmp_path, text):
    ffmpeg = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
    if not ffmpeg.exists(): pytest.skip('production FFmpeg required')
    style = SubtitleStyle('default', 'Heavy', font_family='思源黑体 Heavy', font_size=90,
                          font_weight=900, font_style_name='Heavy', bold=False,
                          position_x=960, position_y=800, outline_width=0, shadow=0)
    p = SubtitleProject(media=StudioMedia('fixture.mp4', width=1920, height=1080, duration_ms=1000),
                        styles=[style], cues=[StudioCue('c', 0, 1000, text)])
    p.validate(); original = deepcopy(p.to_dict())
    face, warning = resolve_local_face(style.font_family, 900)
    assert not warning and (face.units_per_em,face.win_ascent,face.win_descent)==(1000,1160,288)
    adapted = ass_font_style(style,1920,1080)
    assert adapted.font_size==pytest.approx(130.32)
    (tmp_path/'p.ass').write_text(compile_ass(p), encoding='utf8')
    # Isolated copy of the exact production font, never relying on a system fallback.
    import shutil
    (tmp_path/'fonts').mkdir(); shutil.copy2(face.file,tmp_path/'fonts/font.otf')
    result=run_hidden_subprocess([str(ffmpeg),'-v','verbose','-y','-f','lavfi','-i',
        'color=black:s=1920x1080:r=60:d=1','-vf','ass=p.ass:fontsdir=fonts',
        '-frames:v','1','p.png'],cwd=tmp_path,capture_output=True,check=True,timeout=20,
        purpose='actual libass font units regression')
    assert b'(Source Han Sans SC Heavy, 900, 0) -> SourceHanSansSC-Heavy' in result.stderr
    image=Image.open(tmp_path/'p.png').convert('L').point(lambda x:255 if x>220 else 0)
    bbox=image.getbbox(); assert bbox is not None
    font=ImageFont.truetype(face.file,90,index=face.index)
    ink=font.getmask(text).getbbox()
    assert abs((bbox[2]-bbox[0])-(ink[2]-ink[0]))<=3
    assert bbox[3]-bbox[1] < 100  # all four authored samples remain one line
    assert p.to_dict()==original and style.font_size==90
