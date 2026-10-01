"""User's unchanged Death Stranding response: LIVE/production pixel evidence."""
import argparse
import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    options = parser.parse_args()
    from twobyteasr.web_theme import parse_web_theme_sections, WebThemeDocument, theme_archive_html
    from twobyteasr.renderer_service import RendererService, RendererJob
    from PIL import Image
    import numpy as np
    original = (ROOT/'tests/fixtures/death_stranding_original.txt').read_text(encoding='utf8')
    parsed = parse_web_theme_sections(original)
    theme = WebThemeDocument.from_dict(parsed).to_dict()
    out = ROOT/'tmp/death-stranding-frames'/time.strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True)
    (out/'theme.json').write_text(json.dumps(theme, ensure_ascii=False, indent=2), encoding='utf8')
    html = theme_archive_html(theme, sample_text='我送的不是货，是整个人类的希望', speaker='企鹅带带北极熊', duration_seconds=3, auto_replay=False)
    (out/'theme.html').write_text(html, encoding='utf8')
    service = RendererService()
    frames = [1, 5, 12, 45, 84, 89]
    result = {'baseline':options.baseline, 'frames':[], 'cases':[]}
    print('EVIDENCE', out, flush=True)
    selectors = ['.cargo-cradle','.cargo-plate','.odradek-arm','.odradek-petal','.chiral-cluster',
                 '.stage-scanline','.strand-tether','.timefall-particle','.line','.wt-w']
    props = dict(schemaVersion=1, width=1280, height=720, fps=30, durationInFrames=90,
        cues=[dict(id='original', text='我送的不是货，是整个人类的希望', speaker='企鹅带带北极熊',
                   startMs=0, endMs=3000, styleId='original', visual={'webTheme':theme})],
        recipes={'original':{'webTheme':theme}})
    (out/'export-props.json').write_text(json.dumps(props,ensure_ascii=False),encoding='utf8')
    try:
        service.live_set(html, width=1280, height=720)
        for frame in frames:
            png = service.live_pause(cue_ms=frame/30*1000, stage_ms=frame/30*1000)
            (out/f'live-{frame:03}.png').write_bytes(png)
            result['frames'].append(dict(frame=frame, diagnostics=service._live_request(
                {'type':'live_diagnostics','selectors':selectors}, timeout=5)))
        jobs = [RendererJob(str(out/f'export-{frame:03}.png'),props,frame,job_kind='production') for frame in frames]
        rendered = service.render(jobs, timeout=120)
        result['render_status'] = rendered.status
        for row in result['frames']:
            frame = row['frame']
            if not (out/f'export-{frame:03}.png').exists(): continue
            a = np.array(Image.open(out/f'live-{frame:03}.png').convert('RGBA')).astype(float)
            b = np.array(Image.open(out/f'export-{frame:03}.png').convert('RGBA')).astype(float)
            a[:,:,:3] *= a[:,:,3:]/255
            b[:,:,:3] *= b[:,:,3:]/255
            delta = np.abs(a-b)
            mask = np.maximum(a[:,:,3],b[:,:,3]) > 8
            row['mae_visible'] = float(delta[mask].mean()) if mask.any() else 0
            row['different_pixels'] = int((delta.max(axis=2)>8).sum())
        if not options.baseline:
            for span, words in [(100,'短句'),(300,'短句'),(500,'短句'),(3000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字')]:
                service.live_text(text=words,speaker='很长的说话人身份编号测试',duration_ms=span)
                for ratio in (.15,.5,.95):
                    png=service.live_pause(cue_ms=span*ratio,stage_ms=span*ratio)
                    (out/f'case-{span}-{int(ratio*100)}.png').write_bytes(png)
                    result['cases'].append(dict(span=span, ratio=ratio, diagnostics=service._live_request(
                        {'type':'live_diagnostics','selectors':selectors}, timeout=5)))
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        service.shutdown()
        (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2), encoding='utf8')
        print('RESULT', json.dumps({k:v for k,v in result.items() if k not in ('frames','cases')}), flush=True)


if __name__ == '__main__': main()
