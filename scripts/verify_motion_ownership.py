"""Real Chromium ownership, repeat/mount/seek parity; no provider calls."""
import os,sys,json,argparse,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--theme',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    from twobyteasr.motion_ownership import motion_schedule
    theme=WebThemeDocument.from_dict(json.loads(a.theme.read_text('utf8'))).to_dict();spec=theme['motionSpec']
    code=r'''
    (()=>{const checks={},details={};const original=SPEC;
      const base=Object.keys(__timelines).length,roots=[];
      const make=(id)=>{const r=document.createElement('div');r.innerHTML=MARKUP;r.style.cssText='position:absolute;width:100px;height:100px;left:-500px';document.body.appendChild(r);roots.push(r);return r;};
      const a=make('a'),b=make('b'),c=make('c');
      for(const [i,r] of roots.entries())__2byteMountMotion(r,original,500,'ownership-'+i);
      checks.three_isolated=Object.keys(__timelines).length===base+3;
      const first=__2byteMountMotion(a,original,500,'ownership-0');
      checks.repeat_mount_same=first===__2byteMountMotion(a,original,500,'ownership-0');
      const capture=r=>Array.from(r.querySelectorAll('*')).map(n=>({opacity:gsap.getProperty(n,'opacity'),x:gsap.getProperty(n,'x'),scaleX:gsap.getProperty(n,'scaleX')}));
      const forward={};for(const t of [0,15,40,100,295,350,400,425,445,490,500]){__2byteSeekMotion(a,t);forward[t]=capture(a);}
      for(const t of [400,15,490,0,425,100,500,350,40,295,445]){__2byteSeekMotion(a,t);checks['seek_'+t]=JSON.stringify(forward[t])===JSON.stringify(capture(a));}
      __2byteSeekMotion(b,200);const beforeB=capture(b);
      const bad=JSON.parse(JSON.stringify(original)),duplicate=JSON.parse(JSON.stringify(bad.tracks[0]));
      duplicate.selector='.ownership-alias';a.querySelector(bad.tracks[0].selector).classList.add('ownership-alias');bad.tracks.push(duplicate);
      try{__2byteMountMotion(a,bad,500,'ownership-0');checks.conflict=false;}catch(e){details.conflict=e.issues;checks.conflict=e.name==='MotionOwnershipError'&&e.issues[0].track_indices.join(',')==='0,'+(bad.tracks.length-1);}
      checks.failed_mount_clean=Object.keys(__timelines).length===base+2&&__2byteMotionMap(a).length===0;
      checks.peer_unchanged=JSON.stringify(beforeB)===JSON.stringify(capture(b));
      a.innerHTML=MARKUP;const repaired=__2byteMountMotion(a,original,500,'ownership-0');__2byteSeekMotion(a,350);
      checks.retry_new_instance=repaired!==first&&JSON.stringify(capture(a))===JSON.stringify(forward[350]);
      details.schedules={};for(const duration of [50,100,101,300,500,1500,3000,6000])details.schedules[duration]=__2byteMotionSchedule(original,duration);
      for(const r of roots){__2byteUnmountMotion(r);__2byteUnmountMotion(r);r.remove();}
      checks.closed_no_leaks=Object.keys(__timelines).length===base;
      window.__2byteMetrics=window.__2byteMetrics||{};window.__2byteMetrics.ownership_audit={checks,details};
    })();
    '''.replace('SPEC',json.dumps(spec)).replace('MARKUP',json.dumps(theme['cueHtml']))
    service=RendererService();result={}
    try:
        for duration in (50,100,101,300,500,1500,3000,6000):
            html=theme_archive_html(theme,sample_text='为什么他觉得我要移花子了',duration_seconds=duration/1000,auto_replay=False)
            if duration==500:html=html.replace('</body>','<script>'+code+'</script></body>')
            service.live_set(html,width=1280,height=720)
            (out/f'original-B-{duration}.png').write_bytes(service.live_pause(cue_ms=duration/2,stage_ms=duration/2))
            diag=service._live_request({'type':'live_diagnostics','selectors':['.redstone-text']},timeout=10)['diagnostics']
            result[str(duration)]=diag
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        audit=result['500']['metrics']['ownership_audit']
        for duration,rows in audit['details']['schedules'].items():
            audit['checks']['python_js_schedule_'+duration]=rows==motion_schedule(spec,int(duration))
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(audit['checks'],ensure_ascii=False));assert all(audit['checks'].values())
        assert not any(d['script_errors'] for d in result.values())
    finally:service.shutdown()

if __name__=='__main__':main()
