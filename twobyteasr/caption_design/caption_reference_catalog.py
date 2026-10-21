"""Author-read public projects and explicit adaptations, never imported code."""
import re


def is_ice(prompt):
    return bool(re.search(r'冰|霜|冰河世纪|ice\s*age|glaci(?:er|al)|frost|frozen',str(prompt),re.I))


def component_style(prompt):
    from .caption_noita import is_noita
    if is_noita(prompt):
        return 'noita'
    from .caption_style_reference import is_balatro
    return 'ice' if is_ice(prompt) else 'balatro' if is_balatro(prompt) else None


PROJECTS = [
    dict(title='Remotion Captioneer / Karaoke',url='https://github.com/neutral-Stage/remotion-captioneer/blob/main/src/components/Karaoke.tsx',
         observation='逐帧时间驱动字内渐变填充；转译为正文稳定、局部冰光/冻结显现，与真实cue时间绑定，不伪造字级音频对齐。'),
    dict(title='Codrops KineticTypePageTransition',url='https://github.com/codrops/KineticTypePageTransition/blob/main/src/js/typeTransition.js',
         observation='暂停GSAP时间线、独立层次及逆向错峰；转译成冰壳/霜层/文字分层凝结和逆序退散，不照搬全屏旋转与大幅字位移。'),
    dict(title='Textillate',url='https://github.com/jschr/textillate/blob/master/jquery.textillate.js',
         observation='入场/出场分开、分组与延迟参数独立；转译为有界组错峰，短cue压缩阶段，不引入随机顺序或第二时钟。'),
    dict(title='Codrops Kinetic Typography with Three.js',url='https://github.com/marioecg/codrops-kinetic-typo',
         observation='研究作者README的字面材质/着色器方向；在本项目用静态SVG切面和局部混合模拟体积，不导入Three.js或声称物理折射。'),
]

TRANSLATION = [
    '先列材料的结构、透光/反光与形成/消散过程，再选配色：冰是厚边/内部切面/局部裂纹/霜，火是热源/余烬/热扰动，金属是倒角/固定拉丝/移动反光，木刻是纤维/凹槽/压印，CRT是磷光和持续扫描。',
    '底板承托、字面填充和强调层分开；正文用完整实心笔画和低噪声阅读区，材质集中在厚边与局部字面，不用空心双描边代替冰刻。',
    '主体进退表达主题事件：局部凝结/短距归位→字与前壳成型→联合轻颤→沿已有裂纹携字片解体。固定冰纹理不流动，不用通栏扫光；短cue减少次要事件，超短取成型阅读态。',
    '字幕本体中性底、统一包络动画先审查，再看视频叠加；保留全幅坐标与透明输出，短cue/长句/无重点词不丢框。',
]

HYPERFRAMES_COMMIT = '2be82f00999569e2e2d462a9f3eab57bd36d371e'
HYPERFRAMES_REFERENCES = [
    dict(title='HyperFrames frost-sequence-camera-orbit / SharedSurface',
         url=f'https://github.com/heygen-com/hyperframes/blob/{HYPERFRAMES_COMMIT}/registry/blocks/frost-sequence-camera-orbit/source/src/ice/SharedSurface.ts',
         observation='已读实现：完整冰体和碎片用同一局部坐标求值；局部低频霜域、高频结晶、内部深度杂质分层。2D转译为共享材料坐标和跨字框前霜，不引入整段WebGPU演出。'),
    dict(title='HyperFrames glass-shard-title / glass-main',
         url=f'https://github.com/heygen-com/hyperframes/blob/{HYPERFRAMES_COMMIT}/registry/blocks/glass-shard-title/assets/glass-main.mjs',
         observation='已读实现：整句字形mask、Voronoi片组与共享字面UV；转译为携字/冰体/前壳的同组polygon切片，独立归位与解体路径，不复制Logo或全屏飞行。'),
    dict(title='HyperFrames caption-texture',
         url=f'https://github.com/heygen-com/hyperframes/blob/{HYPERFRAMES_COMMIT}/registry/components/caption-texture/caption-texture.html',
         observation='已读实现：字形纹理遮罩与外层独立阴影。六种自带纹理没有冰，未使用这些贴图；冰霜纹理由本项目程序制作，不把金属贴图染蓝。'),
    dict(title='HyperFrames camera-shake',
         url=f'https://github.com/heygen-com/hyperframes/blob/{HYPERFRAMES_COMMIT}/registry/components/camera-shake/camera-shake.html',
         observation='已读实现：固定seed连续噪声+绝对时间driver属性setter；适配现有GSAP seek(t,true)，作用字幕wrapper，排除相机投影/overscan/第二时钟。'),
]
