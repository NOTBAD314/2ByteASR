"""Real Chromium placement across time, live update and Remotion still export."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=root/'tmp/visible-playback-v2/placement'/time.strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from twobyteasr.web_theme import theme_archive_html
    from twobyteasr.local_subtitle_theme import local_subtitle_theme
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.web_placement import normalize_placement
    design=json.loads((root/'tests/fixtures/polar_bear_f38c393_concepts.json').read_text('utf8'))
    design.setdefault('selected_concept_id',design['concepts'][0]['id'])
    theme=local_subtitle_theme(design);text='北极熊也要认真滑雪'
    service=RendererService();checks={};frames=(.12,.5,1.5,2.65,2.9)
    placements=[normalize_placement(),normalize_placement({'x':.3,'y':.35}),normalize_placement({'x':.7,'y':.35})]
    def bbox(path):
        a=np.array(Image.open(path).convert('RGBA'))[:,:,3];yy,xx=np.nonzero(a>20)
        return [int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())] if len(xx) else None
    try:
        service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=960,height=540)
        for index,placement in enumerate(placements):
            service.live_text(text=text,duration_ms=3000,placement=placement)
            for t in frames:
                png=service.live_pause(cue_ms=t*1000,stage_ms=t*1000)
                (out/f'live-{index}-{t}.png').write_bytes(png)
            # Re-enter the same animation after play/seek and verify placement.
            service.live_play(cue_ms=0,stage_ms=0,rate=1)
            png=service.live_pause(cue_ms=1500,stage_ms=1500)
            (out/f'restart-{index}.png').write_bytes(png)
            checks[f'restart-{index}']=bbox(out/f'restart-{index}.png')==bbox(out/f'live-{index}-1.5.png')
            (out/f'theme-{index}.html').write_text(theme_archive_html(theme,sample_text=text,duration_seconds=3,placement=placement),encoding='utf8')
        for index in (1,2):
            expected=np.array([(placements[index]['x']-.5)*960,(placements[index]['y']-.5)*540]*2)
            for t in frames:
                base=bbox(out/f'live-0-{t}.png');moved=bbox(out/f'live-{index}-{t}.png')
                checks[f'phase-{index}-{t}']=bool(base and moved and np.max(np.abs(np.array(moved)-base-expected))<=2)
        props={'schemaVersion':1,'width':960,'height':540,'fps':30,'durationInFrames':90,
            'cues':[{'id':'fixture','text':text,'speaker':'','startMs':0,'endMs':3000,'styleId':'theme',
                'visual':{'webTheme':theme,'layout':{'webPlacement':placements[1]}}}],
            'recipes':{'theme':{'webTheme':theme,'layout':{'webPlacement':placements[1]}}}}
        result=service.render([RendererJob(str(out/'export.png'),props,45,job_kind='production')],timeout=120)
        checks['renderer_status']=result.status=='OK'
        checks['export_placement']=np.max(np.abs(np.array(bbox(out/'export.png'))-bbox(out/'live-1-1.5.png')))<=2
    finally:
        service.shutdown()
        (out/'checks.json').write_text(json.dumps(checks,indent=2,default=bool),encoding='utf8')
        print(out);print(checks)
    if not all(checks.values()):raise SystemExit(1)


if __name__=='__main__':main()
