"""Expose the production theme/GSAP compiler to HyperFrames' real CLI audits."""
from pathlib import Path
import argparse,json,re,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from twobyteasr.web_theme import theme_archive_html,WebThemeDocument
    parser=argparse.ArgumentParser();parser.add_argument('theme',type=Path);parser.add_argument('output',type=Path)
    a=parser.parse_args();theme=WebThemeDocument.from_dict(json.loads(a.theme.read_text('utf8'))).to_dict()
    if not theme.get('motionSpec'):raise ValueError('The audit requires the production MotionSpec')
    a.output.mkdir(parents=True,exist_ok=True)
    html=theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False)
    # Keep the exact production markup/CSS/fonts. The CLI supplies time; the
    # standalone archive transport and its diagnostics are not animation code.
    html=re.sub(r'<script\b[^>]*>[\s\S]*?</script>','',html)
    html=html.replace('id="wt-frame"','id="wt-frame" data-composition-id="subtitle-theme" data-start="0" data-width="1920" data-height="1080" data-duration="3"')
    # The CLI doesn't inherit aria-hidden when evaluating descendant glyphs.
    # Map explicit decorative duplicates only; primary text and microcopy retain
    # the full contrast/layout audit. This adds metadata, never changes pixels.
    html=html.replace('aria-hidden="true"','aria-hidden="true" data-layout-ignore')
    # A rotating circular specular arc is deliberately clipped to its coin rim.
    html=html.replace('class="b-rim-specular"','class="b-rim-specular" data-layout-allow-overflow')
    # Cubic's dollar range includes unpainted font metrics; its rotated AABB
    # overlaps LUCKY. The object verifier measures both actual ink masks and
    # enforces their separation. Exempt this pair's box test, not contrast.
    html=html.replace('class="b-dollar"','class="b-dollar" data-layout-allow-overlap')
    # Placement is the unchanged full-frame host for this transparent sample.
    html=html.replace('</style>','subtitle-placement,.theme-motion{position:absolute;inset:0;display:block}</style>')
    for source,target in [(ROOT/'renderer/node_modules/gsap/dist/gsap.min.js','gsap.min.js'),(ROOT/'renderer/src/webThemeMotion.js','webThemeMotion.js'),(ROOT/'renderer/src/webThemeClock.js','webThemeClock.js')]:
        shutil.copyfile(source,a.output/target)
    bootstrap='''<script src="./gsap.min.js"></script><script src="./webThemeMotion.js"></script><script src="./webThemeClock.js"></script><script>
    const root=document.getElementById('wt-cue');
    window.__timelines = window.__timelines || {};
    window.__2bytePrepareCaption(root).then(()=>{
      window.__timelines['subtitle-theme']=window.__2byteMountMotion(root,MOTION_SPEC,3000,'subtitle-theme');
    });
    </script>'''.replace('MOTION_SPEC',json.dumps(theme['motionSpec']).replace('</','<\\/'))
    html=html.replace('</body>',bootstrap+'</body>')
    (a.output/'index.html').write_text(html,encoding='utf8')
    (a.output/'index.motion.json').write_text(json.dumps(dict(duration=3,assertions=[
        dict(kind='appearsBy',selector='.lettering',bySec=.5),
        dict(kind='staysInFrame',selector='.lettering'),
        dict(kind='staysInFrame',selector='.object' if '.object' in theme['cueHtml'] or 'class="object ' in theme['cueHtml'] else '.chips-stack' if '.chips-stack' in theme['cueCss'] else '.bear' if '.bear' in theme['cueCss'] else '.snow-edge')]),indent=2),encoding='utf8')
    print(a.output)


if __name__=='__main__':main()
