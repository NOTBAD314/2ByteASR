"""Isolated renderer + headed workbench evidence; no provider calls/user data."""
from pathlib import Path
import argparse, json, os, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'tmp/zelda-workbench-20260927/verification'
OUT.mkdir(parents=True,exist_ok=True)
os.environ['TWOBYTEASR_TEST_ROOT']=str(OUT/'isolation')
from twobyteasr.test_isolation import install
install()


def render(quick=False):
    from io import BytesIO
    from PIL import Image
    from examples.zelda_wind_seal import theme_source
    from twobyteasr.web_theme import WebThemeDocument,export_theme_archive,theme_archive_html
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.theme_direction_preview import render_motion_preview
    theme=WebThemeDocument.from_dict(theme_source()).to_dict()
    archive=export_theme_archive(theme,OUT/'archives')
    service=RendererService();checks={};movies={}
    text='这片天空，藏着怎样的冒险？'
    try:
        for duration in ([6000] if quick else [6000,1500]):
            html=theme_archive_html(theme,sample_text=text,duration_seconds=duration/1000,auto_replay=False)
            (OUT/f'theme-{duration}.html').write_text(html,'utf8')
            service.live_set(html,width=960,height=540)
            images={}
            for t in [0,150,300,500,900,duration-300,duration-80,duration-1000/24,duration]:
                im=Image.open(BytesIO(service.live_pause(cue_ms=t,stage_ms=t))).convert('RGBA')
                images[t]=im;im.save(OUT/f'{duration}-{round(t)}.png')
            checks[f'{duration}_start_clear']=not images[0].getchannel('A').getbbox()
            checks[f'{duration}_end_clear']=not images[duration].getchannel('A').getbbox()
            checks[f'{duration}_last_encoded_clear']=not images[duration-1000/24].getchannel('A').getbbox()
            hero=images[900];canvas=Image.new('RGBA',hero.size,'#20262e')
            Image.alpha_composite(canvas,hero).convert('RGB').save(OUT/f'hero-{duration}.png')
            diag=service._live_request({'type':'live_diagnostics','selectors':['.zs-body','.zs-copy','.zs-seal'],
                'include_fonts':True},timeout=20)['diagnostics']
            (OUT/f'diagnostics-{duration}.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2),'utf8')
            checks[f'{duration}_fonts_ready']=diag['fonts_ready'] and not diag['script_errors']
            if not quick:
                movies[str(duration)]=render_motion_preview(service,html,OUT,f'zelda-{duration}',duration_ms=duration,progress=print)
        if not quick:
            long='这里的遗迹居然连到了天空，难道还要再爬一次吗？Link 123！'
            html=theme_archive_html(theme,sample_text=long,duration_seconds=6,auto_replay=False)
            service.live_set(html,width=960,height=540)
            first=service.live_pause(cue_ms=1000,stage_ms=1000)
            service.live_pause(cue_ms=5500,stage_ms=5500)
            second=service.live_pause(cue_ms=1000,stage_ms=1000)
            checks['backward_seek_equal']=first==second
            Image.open(BytesIO(second)).save(OUT/'long-text.png')
        result=dict(archive=str(archive),source_origin='codex-local-authored-example',new_provider_calls=0,checks=checks,movies=movies)
        (OUT/'render-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(checks));assert all(checks.values()),checks
    finally:service.shutdown()


def workbench():
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtGui import QMovie
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from twobyteasr.theme_concept_dialog import ThemeConceptDialog
    from twobyteasr.theme_manager import apply_theme
    from twobyteasr.ui_theme import THEMES
    from twobyteasr.web_theme import import_theme_archive
    app=QApplication.instance() or QApplication([])
    movie=json.loads((OUT/'render-result.json').read_text('utf8'))['movies']['6000']
    concept=dict(id='A',name='海拉鲁 · 风之封印',composition='本地原创示例：青绿断片纹环与金色三角徽记，薄石构承托正文；纹环触发、两翼展开、字组刻印，退出撤印并收回能量。',
        authored_theme=import_theme_archive(json.loads((OUT/'render-result.json').read_text('utf8'))['archive']),motion_preview=movie,
        preview_integrity_verified=True,technical_status='passed',preview_picture=str(OUT/'hero-6000.png'),source_origin='codex-local-authored-example')
    d=ThemeConceptDialog([concept],{'A':concept['preview_picture']});d.show();d.resize(1120,760);QTest.qWait(250)
    checks={'autoplay':d.movie.state()==QMovie.Running}
    seen=[];d.movie.frameChanged.connect(seen.append);QTest.qWait(6400)
    checks['wraps']=any(b<a for a,b in zip(seen,seen[1:]))
    for key in THEMES:
        apply_theme(key,app);QTest.qWait(120);d.seek_frame(36);QTest.qWait(80)
        d.grab().save(str(OUT/f'workbench-{key}.png'))
    s=d.scrubber
    QTest.mouseClick(s,Qt.LeftButton,pos=QPoint(round(s.width()*.7),s.height()//2))
    checks['click_seek']=d.movie.state()==QMovie.Paused and abs(d.movie.currentFrameNumber()-100)<=3
    QTest.mouseClick(d.picture,Qt.LeftButton);checks['picture_resume']=d.movie.state()==QMovie.Running
    QTest.mouseClick(d.picture,Qt.LeftButton);checks['picture_pause']=d.movie.state()==QMovie.Paused
    for width in [720,900,1120]:
        d.resize(width,760);QTest.qWait(90)
        checks[f'layout_{width}']=d.picture.width()>100 and d.rect().contains(d.primary.geometry())
        d.grab().save(str(OUT/f'workbench-width-{width}.png'))
    d.close();checks['close_stops']=d.movie.state()==QMovie.NotRunning
    (OUT/'ui-result.json').write_text(json.dumps(dict(checks=checks,real_user_click=False),indent=2),'utf8')
    print(checks);assert all(checks.values())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--quick',action='store_true');parser.add_argument('--ui',action='store_true');args=parser.parse_args()
    workbench() if args.ui else render(args.quick)
