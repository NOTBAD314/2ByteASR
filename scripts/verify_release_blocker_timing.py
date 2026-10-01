"""Real final-composite timing, including cold/warm cache and nonzero job start."""
import argparse,json,os,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--renderer',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('tmp output required')
    out.mkdir(parents=True,exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='offscreen',USERPROFILE=str(out),TWOBYTEASR_RENDERER_CHROME=str(out/'missing-system-chrome.exe'))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.web_theme import WebThemeDocument
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.studio_render import RenderSettings,RenderJob
    from twobyteasr.advanced_renderer import AdvancedRendererBackend
    from PIL import Image
    ffmpeg=args.renderer.resolve().parent/'tools/ffmpeg/bin/ffmpeg.exe'
    media=out/'blue.mp4'
    run_hidden_subprocess([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=blue:s=320x180:r=12:d=6','-c:v','libx264',media],purpose='timing fixture',check=True,timeout=30)
    theme=WebThemeDocument(name='Timing',palette={'primary':'#00FF00','text':'#FFFFFF'},cue_html='<div class="box">{{text}}</div>',
        cue_css='.box{position:absolute;left:25%;top:25%;width:150px;height:80px;background:#00FF00;color:white;font:30px var(--wt-font)}').validate()
    p=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=6000,width=320,height=180),cues=[StudioCue('late',3000,4000,'时序')]);p.validate()
    p.style_recipes[p.cues[0].style_id]=StyleRecipe(name='Timing',engine='remotion',web_theme=theme.to_dict()).to_dict()
    settings=RenderSettings(width=320,height=180,fps=12,encoder='libx264',audio_codec='none',preset='ultrafast')
    results={'renderer':str(args.renderer.resolve()),'checks':{},'traces':{}}
    try:
        for label,start in [('cold',0),('warm',0),('offset',1)]:
            trace=[];output=out/f'{label}.mp4'
            AdvancedRendererBackend(args.renderer).render(p,ffmpeg,RenderJob(str(media),'',str(output),settings,start_seconds=start,duration_seconds=6-start),trace=lambda event,value:trace.append([event,value]))
            results['traces'][label]=trace
            for sample,expect in [(0.5,False),(3.5-start,True),(4.7-start,False)]:
                frame=out/f'{label}-{sample}.png'
                run_hidden_subprocess([ffmpeg,'-v','error','-y','-ss',str(sample),'-i',output,'-frames:v','1',frame],purpose='composite timing pixel',check=True,timeout=20)
                with Image.open(frame) as image:
                    green=sum(1 for r,g,b in image.convert('RGB').getdata() if g>150 and r<100 and b<100)
                results['checks'][f'{label}-{sample}']={'green_pixels':green,'expected_visible':expect,'passed':(green>200)==expect}
                if (green>200)!=expect:raise AssertionError(f'{label} at {sample}: visible pixels {green}, expected {expect}')
            run_hidden_subprocess([ffmpeg,'-v','error','-i',output,'-f','null','-'],purpose='final composite full decode',check=True,capture_output=True,timeout=30)
        if not any(event=='advanced_overlay_segment_cache' for event,_ in results['traces']['warm']):raise AssertionError('warm cache not exercised')
        results['passed']=True
    finally:(out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':True,'checks':results['checks']},ensure_ascii=False))

if __name__=='__main__':main()
