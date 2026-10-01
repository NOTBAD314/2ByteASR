"""Optional same-provider observations on real frames, never an aesthetic gate."""
import base64
import json
from pathlib import Path


def review_frame_paths(proof):
    """Bound image count without silently excluding departure evidence."""
    labels = {'motion_entry','motion_hold','motion_exit','game','detail'}
    if not any(row['label']=='motion_exit' for row in proof['frames']):
        labels = {'entrance','focal','hold','exit','end','game','detail'}
    return [row['path'] for row in proof['frames'] if row['label'] in labels]


def frame_review_prompt(proof):
    return ('检查这些真实渲染的字幕打样图，不要脑补未出现的图形。全幅按实际尺寸看，细节图查框、角色、字面和连接关系。'
        '默认要求保留有实际承托的主题框、角色辨识和已认可动作；用户明确无框才例外。'
        '只输出具体观察和可执行改法：原框体与角色是否保留；框面、边缘和新增材质是否可辨；'
        '文字本身是否具有可辨的主题材质/滤镜，而非仅字体正确或贴在底板上；板内是否有无意义大面积留白；'
        'CRT字的栅格磷光、玻璃后显像，木刻字的阴刻暗边/压印高光及纹理结合是否真实可见。'
        '图文装饰是否更协调且丰富清楚；逐看motion_entry/hold/exit中6秒和1.5秒两行：'
        '框体是否从第一帧就硬切出现、到最后才突然消失；文字→屏幕→机身的出场是否相互呼应；'
        '入场/退场是否有主题事件，还是主要依赖上下位移和渐隐；CRT失锁应仅屏内一次且恢复、余辉必须实际可见，木刻字纹必须随板收合。'
        '先区分材料是否发光：非发光木纹、刻槽和主要受光边应固定，不奖励扫白字面的循环光；木材大形/厚边/局部年轮在全幅是否可辨。'
        '阅读段是否正文稳定、变化与材料相符。不能因阶段名breathe就要求木头自发光或持续循环。'
        '指出具体时刻；离散帧无法排除局部闪烁或确认节奏，需同条件固定字区连续1.5/3/6秒正常播放，整帧MAE不能代替。'
        '仅恢复结构不算精修；没有旧稿同条件图就不能声称比旧稿更精致。下一版应增强哪处字面/框体材质及动作。'
        '去框、变小、开放排字、文字占比高、实涂面积低或持续动作少都不是改善依据。失败新稿仅为反例。'
        '不打审美分、不数图层/粒子、不声称已看完整动画，不声称用户已认可。此处仅为少量关键帧。'
        '\n样例与时间：'+json.dumps({k:proof[k] for k in ('sample_text','viewport','frames')},ensure_ascii=False))


def same_provider_reviewer(client,selection,*,cancel_check=None):
    capabilities=getattr(client,'capabilities',lambda:None)()
    if not getattr(capabilities,'vision',False):return None
    def review(proof):
        paths=review_frame_paths(proof)
        content=[dict(type='text',text=frame_review_prompt(proof))]
        content.extend(dict(type='image_url',image_url=dict(url='data:image/png;base64,'+
            base64.b64encode(Path(path).read_bytes()).decode('ascii'))) for path in paths)
        result=client.complete([dict(role='user',content=content)],max_tokens=2400,timeout=75,
            operation_kind='visual_feedback',input_scope=dict(kind='actual_keyframes'),cancel_check=cancel_check)
        return dict(status='reviewed',provider=selection.provider,model=selection.model,observations=str(result),blocking=False)
    return review
