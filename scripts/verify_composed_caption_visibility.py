"""Real browser probes: reveal is legal; clipped/hidden primary is not readable."""
from pathlib import Path
import copy,json,os,sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=Path(sys.argv[1]).resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp output required')
    out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from scripts.verify_ai_render_chain import reference_theme
    from twobyteasr.web_theme import theme_archive_html
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.composed_text_probe import composed_text_probe
    service=RendererService();results=[]
    try:
        for name,css,timepoint,expected in [('reveal-start','',0,False),('readable-hold','',1500,True),
            ('parent-hidden','.paper{opacity:0!important}',1500,False),
            ('clip-empty','.paper{clip-path:inset(100%)}',1500,False),
            ('mask-empty','.paper{mask-image:linear-gradient(transparent,transparent)}',1500,False)]:
            theme=reference_theme();theme['cueCss']+=css
            service.live_set(theme_archive_html(theme,sample_text='字芯清楚',duration_seconds=3,auto_replay=False),width=1280,height=720)
            png=service.live_pause(cue_ms=timepoint,stage_ms=timepoint);(out/(name+'.png')).write_bytes(png)
            d=service._live_request({'type':'live_diagnostics'},timeout=5)['diagnostics']
            probe=composed_text_probe(service,png,d)
            results.append(dict(case=name,expected=expected,diagnostics=d,probe=probe,passed=probe['passed']==expected))
        theme=reference_theme()
        service.live_set(theme_archive_html(theme,sample_text='短句',duration_seconds=.05,auto_replay=False),width=1280,height=720)
        for ms in (0,49):
            png=service.live_pause(cue_ms=ms,stage_ms=ms)
            d=service._live_request({'type':'live_diagnostics'},timeout=5)['diagnostics']
            probe=composed_text_probe(service,png,d);results.append(dict(case=f'50ms-{ms}',probe=probe,passed=probe['passed']))
    finally:
        service.shutdown();(out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({r['case']:r['passed'] for r in results}));assert all(r['passed'] for r in results)


if __name__=='__main__':main()
