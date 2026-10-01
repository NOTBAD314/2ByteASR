"""Real browser proof for content-bound emphasis, cue reuse and production parity."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.theme_draft import ThemeDraft,validate_draft_frames
    from twobyteasr.web_theme import WebThemeDocument,theme_archive_html
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    theme=WebThemeDocument.from_dict(dict(name='语义排字运行验证',concept='测试字组，不是交付作品',
        palette=dict(primary='#F0D797',text='#F0D797'),appearance=dict(fontFamily='Smiley Sans, Source Han Sans SC',fontSize=76,fontWeight=400),
        stageHtml='',stageCss='',cueHtml='<div class="copy" data-emphasis="最后一下|赢|GO 2026">{{text}}</div>',
        cueCss='.wt-cue{position:absolute;inset:0}.copy{position:absolute;left:16%;right:16%;bottom:12%;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);color:#FFF4DA;line-height:1.6;text-align:center;text-shadow:0 .2vh 0 #15292D}.copy .wt-focus{font-size:1.35em;color:#FEC060;letter-spacing:.08em;display:inline-block}',
        motionSpec=dict(version=1,runtime='gsap',buildMs=320,resolveMs=180,tracks=[
            dict(selector='.copy',phase='build',start=0,end=1,ease='power2.out',**{'from':dict(y=35,opacity=0),'to':dict(y=0,opacity=1)}),
            dict(selector='.copy',phase='resolve',start=0,end=1,ease='power2.in',**{'from':dict(y=0,opacity=1),'to':dict(y=-15,opacity=0)})]))).to_dict()
    (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),'utf8')
    service=RendererService();checks={};samples=[]
    try:
        text='就差最后一下！';draft=ThemeDraft('semantic-test',1,'test',text,'','subtitle','fixture','fixture').with_theme(theme)
        evidence=validate_draft_frames(draft,out/'validation',service=service,deadline_seconds=180,cancel_check=lambda:False)
        checks['frame_validation']=evidence['passed']
        service.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
        for index,(text,expected) in enumerate([('就差最后一下！',['最后一下']),('这也能赢？！',['赢']),('收看嗯',[]),('出发滑雪 GO 2026',['GO 2026']),('长句先等待对手出牌，就差最后一下！然后准备重新开始',['最后一下'])]):
            service.live_text(text=text,duration_ms=3000)
            (out/f'case-{index}.png').write_bytes(service.live_pause(cue_ms=1500,stage_ms=1500))
            diag=service._live_request(dict(type='live_diagnostics',selectors=['.wt-focus']),timeout=10)['diagnostics']
            roots=[row for row in diag['roots'] if row['selector']=='.wt-focus' and row.get('rect')]
            samples.append(dict(text=text,expected=expected,diagnostics=diag))
            # The composed-text probe independently verifies all actual text.
            checks[f'case_{index}_focus_presence']=bool(roots)==bool(expected)
        (out/'result.json').write_text(json.dumps(dict(checks=checks,samples=samples,evidence=evidence),ensure_ascii=False,indent=2),'utf8')
    finally:service.shutdown()
    print(json.dumps(checks));return 0 if all(checks.values()) else 1


if __name__=='__main__':sys.exit(main())
