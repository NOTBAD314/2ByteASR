"""Immutable theme identity and deterministic render evidence for AI drafts."""
from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable


def canonical_theme(theme):
    from .web_theme import WebThemeDocument
    return json.dumps(WebThemeDocument.from_dict(dict(theme)).to_dict(),
                      ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()


@dataclass(frozen=True)
class ThemeDraft:
    request_id: str
    generation: int
    cue_id: str
    text: str
    speaker: str = ''
    scope: str = 'subtitle'
    provider: str = ''
    model: str = ''
    theme_json: str = ''
    trace_path: str = ''

    @property
    def theme(self):
        return json.loads(self.theme_json) if self.theme_json else {}

    @property
    def content_hash(self):
        return digest(self.theme_json)

    def with_theme(self, theme, trace_path=''):
        return replace(self, theme_json=canonical_theme(theme), trace_path=trace_path)


def theme_structure(theme):
    """Diagnostic fingerprint: never substitute a theme because names match."""
    html = str(theme.get('stageHtml','')) + str(theme.get('cueHtml',''))
    css = str(theme.get('stageCss','')) + str(theme.get('cueCss',''))
    return dict(sha256=digest(canonical_theme(theme)),
        sections={key:dict(chars=len(str(theme.get(key,''))), sha256=digest(str(theme.get(key,''))))
                  for key in ('stageHtml','stageCss','cueHtml','cueCss')},
        classes=sorted(set(item for group in re.findall(r'class=[\"\']([^\"\']+)',html) for item in group.split())),
        keyframes=sorted(set(re.findall(r'@keyframes\s+([\w-]+)',css))),
        ids=re.findall(r'id=[\"\']([^\"\']+)',html))


class DraftValidationError(RuntimeError):
    def __init__(self, message, category='render_validation'):
        super().__init__(message)
        self.category = category


def _caption_runs(details, text):
    if 'semantic_text_runs' in details:
        return details['semantic_text_runs']
    # Older service diagnostics and legacy CSS themes remain readable.
    return details.get('words',[]) or [r for r in details.get('text_runs',[]) if r['text'].strip() in text]


def _bound_text_phases(details, gsap, duration_ms=3000):
    if gsap:
        bound=[t for t in details.get('motion_map',[]) if t.get('affects_text') and t.get('targets',0)>0]
        timelines=details.get('timelines',[])
        active=bool(len(timelines)==1 and timelines[0].get('paused') and not details.get('animations'))
        duration=float(timelines[0].get('duration',3)) if timelines else 3
        entrance=active and any(t['phase']=='build' and 0<t['end']<duration*.5 for t in bound)
        exit=active and any(t['phase']=='resolve' and t['start']>duration*.5 and duration*.8<t['end']<=duration+.05 for t in bound)
        return entrance,exit,active and bool(bound)
    bound=[a for a in details.get('animations',[]) if a.get('cue') and a.get('affects_text') and a.get('iterations') is not None]
    return (any(0<(a.get('end') or 0)<duration_ms*.67 for a in bound),
            any(a.get('delay',0)>duration_ms*.5 and duration_ms*.8<(a.get('end') or 0)<=duration_ms+50 for a in bound),bool(details.get('animations')))


def validate_draft_frames(draft: ThemeDraft, output: Path, *, cancel_check: Callable[[], bool],
                          progress=lambda stage: None, deadline_seconds=35., service=None,
                          exact_html_path=None,placement=None):
    """Six real Chromium frames, computed geometry and premultiplied pixels.

    This runs off the GUI on a private page lease. It doesn't call a provider
    or mutate a project. Failed evidence remains available for diagnostics.
    """
    from .renderer_service import GLOBAL_RENDERER_SERVICE, LiveRendererSession
    from .web_theme import theme_archive_html
    from PySide6.QtGui import QImage
    import numpy as np
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(request_id=draft.request_id, content_hash=draft.content_hash,
                  structure=theme_structure(draft.theme), frames=[], errors=[], warnings=[],
                  visual_review='未进行视觉模型复核', viewport=[1280,720],
                  placement=placement,anchor_validation='user placement' if placement is not None else 'design default')
    def check():
        if cancel_check(): raise DraftValidationError('当前草稿已取消', 'cancelled')
        if time.monotonic()-started > deadline_seconds:
            raise DraftValidationError('主题渲染超过时限，可仅重试预览', 'render_timeout')
    session = LiveRendererSession(service or GLOBAL_RENDERER_SERVICE)
    selectors = ['.line','.wt-w'] + ['.'+c for c in result['structure']['classes'][:60]]
    html = (Path(exact_html_path).read_text(encoding='utf8') if exact_html_path else
            theme_archive_html(draft.theme, sample_text=draft.text, speaker=draft.speaker,
                               duration_seconds=6., auto_replay=False,placement=placement))
    result['html_source'] = str(exact_html_path or 'current_draft')
    (output/'theme.html').write_text(html, encoding='utf8')
    (output/'theme.json').write_text(draft.theme_json, encoding='utf8')
    result['html_sha256'] = digest(html)
    pixels = []
    try:
        check()
        progress('加载当前主题')
        session.live_set(html, width=1280, height=720, timeout=12.)
        for index, seconds in enumerate((.06,.36,.90,3.0,5.49,5.91)):
            check()
            if index==5 and draft.theme.get('motionSpec') and result['frames']:
                # Track fractions are local to the resolve phase. A valid
                # short exit can start after the old fixed 2.91 s sample.
                # Sample the actual bound text exit, preserving the same
                # pixel-change threshold and all six independent frames.
                exits=[t for t in result['frames'][-1]['diagnostics'].get('motion_map',[])
                       if t.get('affects_text') and t.get('targets',0)>0 and t.get('phase')=='resolve'
                       and 3<float(t.get('start',0))<float(t.get('end',0))<=6.05]
                if exits and all(float(t['start'])>=seconds for t in exits):
                    exit_track=min(exits,key=lambda t:float(t['start']))
                    seconds=min(5.99,float(exit_track['start'])+.65*(float(exit_track['end'])-float(exit_track['start'])))
                    result['tail_sample_reason']='inside resolved text exit interval'
            progress(f'校验分镜 {index+1}/6')
            frame_start = time.perf_counter()
            png = session.live_pause(cue_ms=seconds*1000,stage_ms=seconds*1000,timeout=4.)
            image = QImage.fromData(png).convertToFormat(QImage.Format.Format_RGBA8888)
            if image.isNull(): raise DraftValidationError('渲染器没有返回有效图像', 'empty_frame')
            data = np.frombuffer(image.constBits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine())
            rgba = data[:,:image.width()*4].reshape(image.height(),image.width(),4).astype(np.float32)
            rgba[:,:,:3] *= rgba[:,:,3:]/255
            pixels.append(rgba)
            path = output/f'frame-{index+1:02}.png'
            path.write_bytes(png)
            details = session._live_request({'type':'live_diagnostics','selectors':selectors,'include_fonts':index==3},timeout=5.)['diagnostics']
            result['frames'].append(dict(seconds=seconds,path=str(path),sha256=hashlib.sha256(png).hexdigest(),
                render_ms=(time.perf_counter()-frame_start)*1000,diagnostics=details))
        middle = result['frames'][3]['diagnostics']
        from .composed_text_probe import composed_text_probe
        session.live_pause(cue_ms=3000,stage_ms=3000)
        result['composed_text']=composed_text_probe(session,Path(result['frames'][3]['path']).read_bytes(),middle)
        if not result['composed_text']['passed']:
            result['errors'].append('保持段正文在最终合成中没有可见像素贡献（检查父容器、遮罩、clip与遮挡）')
        roots = {r['selector']:r for r in middle['roots']}
        cue = roots.get('.wt-cue',{})
        if cue.get('missing') or not cue.get('rect'):
            result['errors'].append('字幕根节点不存在')
        words = _caption_runs(middle,draft.text)
        if draft.text.replace('\n','').strip() not in middle.get('cue_text','').replace('\n',''):
            result['errors'].append('当前草稿文案未完整进入 DOM')
        if words:
            invisible = [w for w in words if w['opacity'] < .5 or w['rect'][2] <= 0]
            clipped = [w for w in words if w['rect'][0]<1280*.03 or w['rect'][1]<720*.03
                       or w['rect'][0]+w['rect'][2]>1280*.97 or w['rect'][1]+w['rect'][3]>720*.98]
            if invisible: result['errors'].append(f'保持段有{len(invisible)}段正文不可见')
            if clipped: result['errors'].append(f'有{len(clipped)}段正文超出画面安全边距（左右3%，上3%，下2%）；需调整作者布局')
        elif not words:
            result['errors'].append('字幕文本未进入 DOM')
        result['motion_differences'] = [float(np.abs(b-a).mean()) for a,b in zip(pixels,pixels[1:])]
        entrance,exit,has_motion=_bound_text_phases(middle,bool(draft.theme.get('motionSpec')),6000)
        if not entrance:
            result['errors'].append('主字幕没有实际绑定的有限入场动画')
        if not exit:
            result['errors'].append('主字幕没有实际绑定到cue尾部的有限出场动画')
        # A user can place the cue anywhere in the video. Inspect the actual
        # text region across these frames, not a hard-coded bottom stripe.
        text_rects=[]
        for row in result['frames']:
            details=row['diagnostics']
            runs=_caption_runs(details,draft.text)
            text_rects.extend(r['rect'] for r in runs if r['rect'][2]>0 and r['rect'][3]>0)
        x0=y0=0;x1,y1=1280,720
        if text_rects:
            x0=max(0,int(min(r[0] for r in text_rects))-24);y0=max(0,int(min(r[1] for r in text_rects))-24)
            x1=min(1280,int(max(r[0]+r[2] for r in text_rects))+24);y1=min(720,int(max(r[1]+r[3] for r in text_rects))+24)
        result['cue_motion_region']=[x0,y0,x1,y1]
        result['cue_motion_differences'] = [float(np.abs(b[y0:y1,x0:x1]-a[y0:y1,x0:x1]).mean()) if x1>x0 and y1>y0 else 0. for a,b in zip(pixels,pixels[1:])]
        if max(result['cue_motion_differences'][:2],default=0)<.025 or result['cue_motion_differences'][-1]<.025:
            result['errors'].append('字幕入场或退场未检出实际像素变化')
        if not has_motion or max(result['motion_differences'],default=0) < .025:
            result['errors'].append('六帧未检出真实动画变化')
        if middle.get('missing_svg_ids'):
            result['errors'].append('SVG引用缺失：'+', '.join(middle['missing_svg_ids']))
        if middle.get('script_errors'):
            result['errors'].append('页面脚本错误：'+'；'.join(middle['script_errors']))
        result['alpha_coverage'] = float((pixels[3][:,:,3] > 230).mean())
        # Legible, compact screenshot panels for CLI vision transports. These
        # are actual rendered pixels, never a code-only aesthetic substitute.
        from PIL import Image,ImageDraw
        images=[Image.open(row['path']).convert('RGBA') for row in result['frames']]
        boxes=[im.getchannel('A').getbbox() for im in images];boxes=[b for b in boxes if b]
        if boxes:
            left=max(0,min(b[0] for b in boxes)-20);top=max(0,min(b[1] for b in boxes)-25)
            right=min(1280,max(b[2] for b in boxes)+20);bottom=min(720,max(b[3] for b in boxes)+25)
            panel=Image.new('RGB',(720,360),'#18222d')
            for i,index in enumerate((0,1,2,4,5)):
                crop=images[index].crop((left,top,right,bottom));crop.thumbnail((650,66))
                panel.paste(crop,(65,i*72),crop);ImageDraw.Draw(panel).text((5,i*72+20),f"{result['frames'][index]['seconds']}s",fill='white')
            panel.save(output/'review-motion.png')
            panel=Image.new('RGB',(720,360),'#18222d')
            for i,color in enumerate(('#eee9df','#18222d')):
                full=Image.alpha_composite(Image.new('RGBA',(1280,720),color),images[3]);full.thumbnail((360,203));panel.paste(full,(i*360,0))
                crop=images[3].crop((left,top,right,bottom));crop.thumbnail((350,140))
                backdrop=Image.new('RGB',(360,157),color);backdrop.paste(crop,((360-crop.width)//2,8),crop);panel.paste(backdrop,(i*360,203))
            panel.save(output/'review-contrast.png')
            result['review_images']=[str(output/'review-contrast.png'),str(output/'review-motion.png')]
        if result['alpha_coverage'] > .4:
            result['errors'].append('大面积不透明区域遮挡视频，须降低背景遮挡')
        result['text_cases']=[]
        for duration,text,speaker in ((50,'短句',''),(100,'短句',''),(300,'短句','说话人'),(500,'短句',''),
                (3000,'第一行明确换行\n第二行继续说明',''),
                (3000,'就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字','长说话人身份编号')):
            check();progress(f'检查中文与短字幕 {duration}ms')
            session.live_text(text=text,speaker=speaker,duration_ms=duration)
            png=session.live_pause(cue_ms=duration*.5,stage_ms=duration*.5,timeout=4.)
            case_key=f'{duration}-{len(text)}'
            path=output/f'text-case-{case_key}.png';path.write_bytes(png)
            details=session._live_request({'type':'live_diagnostics','selectors':['.wt-w']},timeout=3.)['diagnostics']
            runs=_caption_runs(details,text)
            invalid=[r for r in runs if r['opacity']<.5 or r['rect'][2]<=0 or r['rect'][0]<1280*.03
                or r['rect'][0]+r['rect'][2]>1280*.97 or r['rect'][1]<720*.03 or r['rect'][1]+r['rect'][3]>720*.98]
            composed=composed_text_probe(session,png,details)
            passed=bool(runs) and not invalid and text.replace('\n','') in details.get('cue_text','').replace('\n','') and composed['passed']
            result['text_cases'].append(dict(duration_ms=duration,text=text,speaker=speaker,path=str(path),
                passed=passed,invalid_runs=invalid,diagnostics=details,composed_text=composed))
            if not passed:
                reasons=[]
                if invalid:reasons.append('正文位置超出安全边距或尺寸/不透明度无效')
                if not runs or text.replace('\n','') not in details.get('cue_text','').replace('\n',''):reasons.append('正文DOM不完整')
                if not composed['passed']:reasons.append('合成正文不可见')
                result['errors'].append(f'{duration}ms中文案例：'+ '；'.join(reasons))
            phases=[]
            for fraction in ((0.,(duration-1)/duration) if duration<=100 else (.15,.95)):
                check();progress(f'检查 {duration}ms 字幕 {round(fraction*100)}% 动画')
                png=session.live_pause(cue_ms=duration*fraction,stage_ms=duration*fraction,timeout=4.)
                path=output/f'text-case-{case_key}-{round(fraction*100)}.png'
                path.write_bytes(png)
                diagnostics=session._live_request({'type':'live_diagnostics','selectors':['.wt-w']},timeout=3.)['diagnostics']
                phases.append(dict(fraction=fraction,path=str(path),diagnostics=diagnostics))
                if duration<=100:
                    phases[-1]['composed_text']=composed_text_probe(session,png,diagnostics)
                    if not phases[-1]['composed_text']['passed']:result['errors'].append(f'{duration}ms字幕首尾合成正文不可见')
                if diagnostics.get('script_errors'):
                    result['errors'].append(f'{duration}ms字幕动画页面错误')
            result['text_cases'][-1]['entry_exit_frames']=phases
        result['elapsed_seconds'] = time.monotonic()-started
        check()
        if result['errors']: raise DraftValidationError('；'.join(result['errors']))
        result['passed'] = True
        return result
    except Exception as exc:
        category = getattr(exc, 'category', None) or (
            'render_timeout' if any(word in str(exc).lower() for word in ('timeout','timed out')) else 'render_error')
        result.update(passed=False,error=f'{type(exc).__name__}: {exc}',
                      category=category)
        if isinstance(exc, DraftValidationError):
            exc.render_evidence=result
            raise
        failure=DraftValidationError(str(exc), category=category)
        failure.render_evidence=result
        raise failure from exc
    finally:
        (output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        session.close()
