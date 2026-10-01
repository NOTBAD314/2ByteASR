"""Synthetic, offline G01/G03 production renderer verification (source or candidate)."""
import argparse, copy, json, os, sys, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--renderer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    output=args.output.resolve()
    if not output.is_relative_to(root/'tmp'): raise ValueError('evidence must be under workspace tmp')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    os.environ['USERPROFILE']=str(output)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.processes import run_hidden_subprocess,renderer_node_command,renderer_child_environment
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from PIL import Image
    requests=[]
    class Trap(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'trap')
        def log_message(self,*a): pass
    trap=ThreadingHTTPServer(('127.0.0.1',0),Trap)
    threading.Thread(target=trap.serve_forever,daemon=True).start()
    target=f'http://127.0.0.1:{trap.server_port}/trap'
    root_renderer=args.renderer.resolve()
    browser=root_renderer/'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'
    os.environ['TWOBYTEASR_RENDERER_CHROME']=str(output/'absent-system-chrome.exe')
    from urllib.parse import quote
    texture='data:image/svg+xml,'+quote('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#234"/></svg>',safe='')
    css='.box{position:absolute;left:20%;top:40%;color:white;font:36px var(--wt-font);background-image:url("'+texture+'");padding:8px;filter:url(#blur)}'
    html='<svg width="0" height="0"><defs><filter id="blur"><feGaussianBlur stdDeviation="0.1"/></filter></defs></svg><div class="box">{{text}}</div>'
    web=dict(name='Synthetic',cueHtml=html,cueCss=css,stageHtml='',stageCss='',appearance={'fontFamily':'Cubic 11','fontSize':90})
    recipe=dict(name='Synthetic',typography={'fontFamily':'Cubic 11','fontSize':90,'bold':False},layout={},webTheme=web)
    props=dict(schemaVersion=1,width=320,height=180,fps=12,durationInFrames=24,cues=[
        dict(id='one',text='字幕测试',startMs=0,endMs=1000,styleId='s'),
        dict(id='two',text='保存重开',startMs=1500,endMs=2000,styleId='s')],recipes={'s':recipe})
    # Deliberately bypass author validation to exercise the second boundary.
    props['recipes']['s']['webTheme']['cueCss']+=' .probe{width:5px;height:5px;background-image:image-set("'+target+'" 1x)}'
    props['recipes']['s']['webTheme']['cueHtml']+='<div class="probe"></div>'
    props_path=output/'props.json';props_path.write_text(json.dumps(props,ensure_ascii=False),encoding='utf8')
    document=WebThemeDocument(name='Synthetic',palette={'primary':'#112233','text':'#FFFFFF'},cue_html=html,cue_css=css,
        appearance={'fontFamily':'Cubic 11','fontSize':90})
    live_html=theme_archive_html(document.to_dict(),sample_text='字幕测试')
    live_html=live_html.replace('</style>',' .probe{width:5px;height:5px;background-image:image-set("'+target+'" 1x)}</style>',1).replace('</body>','<div class="probe"></div></body>')
    receipt={'renderer':str(root_renderer),'browser':str(browser),'trap_requests':requests,'checks':{}}
    try:
        for generation in range(2):
            service=RendererService(root_renderer)
            try:
                service.live_set(live_html,width=320,height=180)
                for frame in (0,500,100):
                    png=output/f'live-{generation}-{frame}.png'
                    png.write_bytes(service.live_frame(cue_ms=frame,stage_ms=frame))
                    with Image.open(png) as im:
                        if not im.getchannel('A').getbbox(): raise AssertionError('empty LIVE frame')
                job=RendererJob(str(output/f'still-{generation}.png'),props,3)
                result=service.submit([job],timeout=90).result(95)
                result.require_job(job)
                with Image.open(job.output) as im:
                    if not im.getchannel('A').getbbox(): raise AssertionError('empty still')
                receipt['checks'][f'live_still_restart_{generation}']=True
            finally:service.shutdown()
        for label,segments in [('single',[(0,11)]),('segments',[(0,7),(18,23)])]:
            manifest={'props':str(props_path),'browser':str(browser),'referenceBrowser':str(output/'absent-system-chrome.exe'),'pages':2,
                'segments':[{'start':a,'end':b,'output':str(output/f'{label}-{a}-{b}.mov')} for a,b in segments]}
            manifest_path=output/f'{label}.json';manifest_path.write_text(json.dumps(manifest),encoding='utf8')
            result=run_hidden_subprocess(renderer_node_command(root_renderer,root_renderer/'render-overlays.mjs',manifest_path),purpose='release-blocker-render',cwd=root_renderer,env=renderer_child_environment(),capture_output=True,text=True,encoding='utf8',timeout=120)
            (output/f'{label}.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
            if result.returncode: raise RuntimeError(result.stderr[-4000:])
            ffmpeg=root_renderer.parent/'tools/ffmpeg/bin/ffmpeg.exe'
            for segment in manifest['segments']:
                check=run_hidden_subprocess([ffmpeg,'-v','error','-i',segment['output'],'-f','null','-'],purpose='release-blocker-decode',capture_output=True,timeout=30)
                if check.returncode: raise RuntimeError(check.stderr.decode(errors='replace'))
            receipt['checks'][label+'_render_full_decode']=True
        if requests: raise AssertionError('renderer contacted trap: '+str(requests))
        receipt['checks']['zero_trap_requests']=True
    finally:
        trap.shutdown();trap.server_close()
        (output/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
