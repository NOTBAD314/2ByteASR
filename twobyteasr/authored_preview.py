"""Actual candidate preview artifacts shared by generation and saved-draft UI."""
from pathlib import Path
import json
import time
from functools import lru_cache

PREVIEW_VERSION='authored-preview-subject-9'

@lru_cache(maxsize=256)
def _dependency_hash(path,mtime,size):
    from .caption_creative_pipeline import digest
    return digest(Path(path).read_bytes())

def dependency_hash(path):
    stat=path.stat()
    return _dependency_hash(str(path),stat.st_mtime_ns,stat.st_size)

def preview_fingerprint(theme,text,ledger,html=None):
    from .caption_creative_pipeline import digest,canonical
    from .runtime_paths import detect_install_root
    from .web_theme import theme_archive_html
    root=detect_install_root()
    dependencies={}
    for relative in ('renderer/service.mjs','renderer/src/webThemeClock.js','renderer/src/webThemeMotion.js',
                     'renderer/package-lock.json','twobyteasr/theme_draft.py','twobyteasr/composed_text_probe.py',
                     'twobyteasr/theme_texture_resource.py','twobyteasr/web_theme.py',
                     'twobyteasr/authored_motion_review.py','twobyteasr/authored_keyframe_review.py',
                     'twobyteasr/authored_preview.py','twobyteasr/theme_direction_preview.py','2byteasr_build.json'):
        path=root/relative
        if path.is_file():dependencies[relative]=dependency_hash(path)
    for path in sorted((root/'assets/fonts').glob('*')):
        if path.suffix.lower() in {'.ttf','.otf','.woff2'}:dependencies['font/'+path.name]=dependency_hash(path)
    html=html if html is not None else theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
    references=[(r['role'],digest(Path(r['path']).read_bytes()) if Path(r['path']).is_file() else None)
                for r in ledger.value.get('reference_files',[])]
    return digest(canonical([PREVIEW_VERSION,ledger.value['raw_prompt_hash'],theme,text,digest(html),dependencies,references]))

def reusable_preview(concept,text):
    from .caption_creative_pipeline import ThemeLedger,digest
    try:
        ledger=ThemeLedger.open(concept['ledger_path'])
        row=next(c for c in ledger.value['candidates'] if c['id']==concept['id'])
        receipt=row.get('preview_receipt',{})
        if receipt.get('dependency_fingerprint')!=preview_fingerprint(concept['authored_theme'],text,ledger):return None
        if not receipt.get('validation',{}).get('passed'):return None
        frames=row.get('rendered_previews',[])
        if len(frames)<5 or any(not Path(f['path']).is_file() or digest(Path(f['path']).read_bytes())!=f['sha256'] for f in frames):return None
        return receipt
    except (OSError,ValueError,KeyError,StopIteration):return None

def render_candidate_preview(concept,folder,text,*,cancel_check=lambda:False,progress=lambda value:None,keyframe_review=None):
    from .caption_creative_pipeline import ThemeLedger,digest,canonical
    from .renderer_service import GLOBAL_RENDERER_SERVICE,LiveRendererSession
    from .web_theme import theme_archive_html
    from .theme_draft import ThemeDraft,validate_draft_frames
    from .theme_direction_preview import render_motion_preview
    from PIL import Image
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cached=reusable_preview(concept,text)
    if cached:return dict(cached,reused=True)
    started=time.monotonic();service=LiveRendererSession(GLOBAL_RENDERER_SERVICE)
    milestones={};advisory_failures=[]
    theme=concept['authored_theme'];ident=concept['id']
    ledger=ThemeLedger.open(concept['ledger_path'])
    try:
        draft=ThemeDraft(ledger.root.name,1,ident,text,'','subtitle',concept.get('provider',''),'').with_theme(theme)
        evidence=validate_draft_frames(draft,folder/'validation',cancel_check=cancel_check,
            progress=progress,deadline_seconds=90,service=GLOBAL_RENDERER_SERVICE)
        milestones['technical_validation_complete']=time.time()
        html=theme_archive_html(theme,sample_text=text,duration_seconds=6,auto_replay=False)
        (folder/'theme.html').write_text(html,'utf8')
        service.live_set(html,width=1920,height=1080)
        frames=[]
        stamps=[('start',0),('entrance',160),('focal',560),('hero',1500),('hold',3500),('exit',5850),('last',5999),('end',6000),('after',6100)]
        for label,ms in stamps:
            if cancel_check():raise InterruptedError('候选预览已取消')
            path=folder/(label+'.png');path.write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms));frames.append(path)
            if label=='hero':
                from .web_theme_fonts import font_use_receipt
                fonts=service._live_request({'type':'live_diagnostics','include_fonts':True},timeout=5)['diagnostics']
                font_receipt=font_use_receipt(theme.get('appearance',{}).get('fontFamily',''),fonts)
        bitmap=Image.open(folder/'hero.png').convert('RGBA');bounds=bitmap.getchannel('A').getbbox()
        detail=folder/'detail.png'
        (bitmap.crop((max(0,bounds[0]-30),max(0,bounds[1]-30),min(1920,bounds[2]+30),min(1080,bounds[3]+30))) if bounds else bitmap).save(detail)
        frames.append(detail)
        with Image.open(detail) as source:
            subject=Image.alpha_composite(Image.new('RGBA',source.size,'#20262e'),source.convert('RGBA'))
        subject_path=folder/'subject.png';subject.save(subject_path);frames.append(subject_path)
        media=next((r['path'] for r in ledger.value['reference_files'] if r['role']=='current-media' and r['exists']),None)
        if media:
            game=folder/'game.png';background=Image.open(media).convert('RGBA').resize((1920,1080))
            Image.alpha_composite(background,bitmap).save(game);frames.append(game)
        milestones['first_static_preview']=time.time()
        concept.update(preview_picture=str(subject_path),full_frame_preview=str(folder/'hero.png'),
                       static_preview_ready=True)
        progress('真实静态关键帧已就绪 · 正在制作完整动画')
        from .authored_motion_review import capture_motion_review
        try:
            motion_frames, motion_sampling = capture_motion_review(service,theme,text,folder,cancel_check=cancel_check)
        except Exception as exc:
            if cancel_check():raise InterruptedError('候选预览已取消') from exc
            motion_frames=[];motion_sampling=dict(status='failed',error=str(exc)[:500])
            advisory_failures.append(dict(stage='motion_contact_sheet',error=str(exc)[:500],blocking=False))
        frames.extend(motion_frames)
        # This receipt is durable before the expensive continuous preview.
        # Review failures are advisory and cannot hide a technically valid work.
        proof=dict(source_hash=digest(canonical(theme)),sample_text=text,viewport=[1920,1080],
            frames=[dict(label=p.stem,path=str(p),sha256=digest(p.read_bytes()),
                         milliseconds=None if p.stem.startswith('motion_') else dict(stamps).get(p.stem,1500)) for p in frames],
            motion_sampling=motion_sampling,
            subject_bbox=list(bounds) if bounds else None,validation_passed=True,
            review=dict(status='not_run',reason='当前生成模型未提供图像复核能力',blocking=False))
        proof_path=folder/'keyframe-proof.json'
        def save_proof():proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),'utf8')
        save_proof();progress('真实文字关键帧已保存 · 检查构图与阅读')
        if keyframe_review:
            try:
                proof['review']=dict(keyframe_review(proof),blocking=False)
            except Exception as exc:
                if cancel_check():raise InterruptedError('关键帧检查已取消') from exc
                proof['review']=dict(status='failed',error=str(exc)[:600],blocking=False)
            save_proof()
        if cancel_check():raise InterruptedError('候选预览已取消')
        progress('关键帧检查结束 · 制作完整动画')
        motion=render_motion_preview(service,html,folder,ident,cancel_check=cancel_check,progress=progress,background_path=media)
        short_motion = None
        # Every theme needs a representative short-cue preview.
        short_html=theme_archive_html(theme,sample_text=text,duration_seconds=1.5,auto_replay=False)
        try:
            short_motion=render_motion_preview(service,short_html,folder,ident+'-short',
                cancel_check=cancel_check,progress=progress,background_path=media,duration_ms=1500)
            frames.extend([Path(short_motion['video']),Path(short_motion['gif'])])
            frames.extend(Path(short_motion['context'][kind]) for kind in ('video','gif') if short_motion.get('context',{}).get(kind))
        except Exception as exc:
            if cancel_check():raise InterruptedError('候选预览已取消') from exc
            advisory_failures.append(dict(stage='short_preview',error=str(exc)[:500],blocking=False))
            progress('完整动画已就绪；短片补充预览失败，已保留可采用作品')
        milestones['first_complete_animation_preview']=time.time()
        frames.extend([Path(motion['video']),Path(motion['gif'])])
        frames.extend(Path(motion['context'][kind]) for kind in ('video','gif') if motion.get('context',{}).get(kind))
        ledger.record_preview(ident,frames)
        receipt=dict(version=PREVIEW_VERSION,source_hash=digest(canonical(theme)),
            dependency_fingerprint=preview_fingerprint(theme,text,ledger,html),
            html_sha256=digest(html),sample_text=text,viewport=[1920,1080],duration_ms=6000,
            elapsed_seconds=time.monotonic()-started,milestones=milestones,validation=evidence,semantic_review=proof['review']['status'],
            fonts=font_receipt,
            keyframe_proof=str(proof_path),keyframe_review=proof['review'],
            picture=str(subject_path),transparent_picture=str(detail),presentation='subject',
            full_frame=str(folder/('game.png' if media else 'hero.png')),motion=motion,
            short_motion=short_motion,advisory_failures=advisory_failures,style_review=dict(status='awaiting_pixel_and_movie_review',
                reference_source=ledger.value.get('style_reference',{}).get('source') if ledger.value.get('style_reference') else None,
                questions=['背景框/内外边界在正常比例可辨','中文字面与关键词层次',
                    '风格由字幕本体承担而非插图','入场/阅读局部细节/退出正常速度成立',
                    '三候选结构/材质/关键词/动作确实不同'],automatic_aesthetic_approval=False))
        row=next(c for c in ledger.value['candidates'] if c['id']==ident)
        row['preview_receipt']=receipt;ledger.save()
        (folder/'preview.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
        return receipt
    finally:service.close()
