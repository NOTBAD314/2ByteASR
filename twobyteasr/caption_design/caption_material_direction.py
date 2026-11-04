"""Art guidance shared with every fresh authored request, not a layout template."""

MATERIAL_DIRECTION = {
    'priority': '主题辨识与完整动效优先。字幕约束正文、读性和时间，不预设抽象UI或厚长框；主题符号、器物、角色可按构图选用，遵守本次用户明确要求。',
    'composition': '真实文字、支撑结构与主题元素共同构图，短句收紧长句换行；自由选择非矩形、开放构图、器物或角色，不强塞也不预先禁止具象元素。',
    'typography': '按真实中文字体与字重设计正文和关键词层级，有方向的描边、轻压印、双色套印、局部渐变与关键词底纹独立组合；实际字幕占比下可读、有效。',
    'color': '先定专属轮廓、纹样与主题事件，再选配色；如Balatro的筹码倍率/卡牌、塞尔达的纹环/古代能量/遗迹关系，不能只换色套框。',
    'motion': '按题材设计凝结/扣合/压印/贴签等主题事件→正文落位→关键词响应→可读的主题运动→主题消散。固定材料纹理不滑动；冰字/壳/框成型后联合微颤，CRT可持续扫描，其他主题可选逐字波动/词组震动/弹性回落。opacity配合真实动作，不只整板展开或淡入淡出。',
    'timing': 'cue终点硬清场必须保留，视觉退出须在终点前完成。不延长cue，不借下一句。v2短cue采用稳定阅读或轻量动作；错峰总窗口有上限，不伪装音频字戳。',
    'restraint': '不以层数、错峰或回弹次数评审；去掉名称后检查主题是否仍可辨。简洁不等于素条幅，具象不等于堆贴图，材料和动效按主题取舍。',
    'review': '技术通过可预览保存采用；审美建议不强制收费修复。真实比例视频叠加、细节与完整正常速度动画分别检查，用户满意后才标审美签收。',
}

DESIGN_SPEC_FIELDS = {
    'theme_identifiers': '当前主题如何体现在可见字形、配色关系、材质或图文关系中；不靠额外口号说明题材。',
    'shape': '主要阅读段背景框/底板的主体轮廓、内外边界、边角与明暗层次、内边距与正文比例；形状和具象程度由主题决定。修订历史作品遵守本次明确保留的结构。',
    'material': '分别说明框体和字面材质如何成立：可见纹理、阴刻暗边/压印高光、油墨厚薄或玻璃显像的具体实现，以及字与底板的明暗接触关系；指出相对当前稿新增哪处可见质感。先区分材料是否发光、固定纹理与动态照明；非发光木材的纹理、刻槽暗部和主要受光边固定，工艺落定后可稳定阅读，不强加循环。发光屏幕扫描等按真实时间低频变化，正文稳定。不以堆层或灯光数量计分。',
    'typography': '引用本句真实重点字组（或整句统一），说明真实可加载字体/字重、字号/间距/布局；字面可组合方向描边、轻压印、双色套印或局部渐变，实际字幕比例下清晰，不改词。',
    'text_region': '真实正文的行宽、字组与换行；底板随文字自适应，短句不留空框，长句不一味缩字号。滤镜与阴影副本保持同尺寸同位置，阅读不被装饰压过。',
    'composition': '在共同局部坐标内组织文字、框体、内外边界与关键词强调；说明支撑建立、字组落位、强调收束、稳定阅读及终点前退出。具象符号或角色可参与主题表达；历史稿按本次锁定项兼容保留。',
}

TEXT_EMPHASIS_DELIVERY = '''语义字组可选能力：在{{text}}的直接父容器写data-emphasis="重点字组|另一字组"（最多4组，每组24字）。宿主只给实际正文中匹配的文字包裹.wt-focus，不插入、删除或改写文字；没有匹配则整句原样；文字框与基本动作不依赖重点词存在，必须继续显示。用作者容器 .copy .wt-focus 设置相对字号、材质和字距，长句自然换行。不要用固定nth-child假设每句第几个字都重要，不要把全文/助词逐字设为重点。不同样例没有相同关键词时允许统一排字。v1不要对可能不存在的.wt-focus添加轨道；v2须用optional:true。'''

MOTION_DELIVERY = '''1920×1080透明外画布、局部实体字幕簇；{{text}}、var(--wt-font)、var(--wt-size)；静态CSS，无animation/transition/keyframes，图层在cueHtml。不使用脚本、网络URL、回调、墙钟或随机数。
MotionSpec version=1兼容，新增作品可用version=2/runtime=gsap/buildMs(0..800)/resolveMs(0..500)/tracks(1..64)；每条track限定内部class selector、phase build/breathe/resolve、start/end 0..1、ease、from/to相同属性。
start/end是所属phase内部的比例，绝不是整句cue的比例。例：6000ms句长、buildMs=600、resolveMs=400，build start=0/end=1对应0..600ms；resolve start=0/end=0.8对应5600..5920ms。resolve start=0.96会等到最后16ms才开始！将各层退出安排在resolve的0..0.95，终点前留清场余量；不要把全句进度再次填入阶段比例。正文入场应在build窗口内有可读节拍，不能全部挤在0..0.2。
selector只支持单class（如.subject）、class后代链（.subject .detail）、class子级链（.subject > .detail），或末尾:first-child/:last-child/:nth-child(1..99)/:nth-last-child(1..99)。不支持复合class .a.b（例如.subject.main）、逗号、ID、标签或属性选择器；需要更精确目标时在自己cueHtml的目标元素上设计独立class。不可选择.wt-cue/.wt-stage/.wt-scope/.subtitle-placement/.theme-motion或含这些前缀的class，宿主位置由用户所有。
可用opacity/x/y/xPercent/yPercent/rotation/rotationX/rotationY/scaleX/scaleY/clipPath(inset或polygon)/backgroundPositionX/backgroundPositionY；坐标数字以1080高参考像素计，scale为倍率。ease可用none、power1/2/3.in/out/inOut、sine.in/out/inOut、expo.in/out、固定back.out(1.7)用于短促装配回弹及steps(2)..steps(32)。
数值范围：opacity 0..1；x/backgroundPositionX -1920..1920；y/backgroundPositionY -1080..1080；xPercent/yPercent -100..100；rotation -180..180；rotationX/rotationY -80..80（不能用180度翻面）；scaleX/scaleY 0..3；strokeDashoffset -10000..10000。全部为JSON数字；clipPath只用数字组成的inset()/polygon()，transformOrigin形如50% 50%。start必须小于end，实际同一节点同一属性的时间区间不可重叠，顺序相位合法；不同selector可能匹配同一节点。创作时在这些有限范围内设计动作，不假定适配器会重写超界值。
breathe最多8条，允许repeat整数0..24和yoyo布尔值；start/end包含全部重复的总窗口，并非单次长度。分层组织环境、装置或材质动作；阅读期按主题选择整组/词组/单字/材质运动，不给宿主动作；结束硬清场，至少65%稳定阅读段。固定材料纹理不要在字形内滑动；动态显像等发光材质可分层处理。breathe可选durationMs=120..30000，表示每次变化的真实毫秒时长；start/end仍限制可用窗口，repeat仍有界，窗口不足仅播放动作前缀，不能假定短句已到末态。不填durationMs保留旧的整窗口均分行为。扫描副本文案必须aria-hidden并与正文共用字体尺寸。'''

MOTION_DELIVERY += "\nversion=2新增stagger:{amountMs:0..240,groupSize:1..8,order:forward|reverse|center}，只用于build/resolve，宿主按真实目标展开，总错峰最多占该track窗口40%。不要为每个字复制track。{{words}}生成.wt-w；data-emphasis可同时包裹匹配字组.wt-focus，optional:true仅允许重点词轨道，无匹配正常跳过。受控变量--caption-reveal(0..1)、--caption-sheen(0..100)。顺序关键帧用不重叠track，不支持任意keyframes字段。v2<=700ms稳定阅读，700..1600ms轻量动作，至少65%阅读；v1保持兼容。"
MOTION_DELIVERY += "\n阅读期持续材质用v2的sustain:true、durationMs:真实毫秒周期、start:0/end:1，不同时指定repeat；循环次数由当前cue窗口决定，窗口结束即停止，暂停/seek/导出使用同一时钟。CRT扫描、颗粒/foil和轻微游戏wiggle应覆盖阅读期，局部微动可约0.2度/0.7像素，不把整句大幅抖动当生命力。微动容器与进退容器分开，退场接纳最后保持姿态，不能复位跳变。"
TEXT_EMPHASIS_DELIVERY += "\nMotionSpec v2允许给.wt-focus轨道显式optional:true；{{words}}也支持data-emphasis，宿主保留字符拓扑。"

MOTION_DELIVERY += "\nv2可选minCueMs:0..30000；时长不足时该轨取成型阅读态。确定性wiggle及材质分层契约见reusable_effects；这些字段会保留到保存与导出，不写onUpdate回调。"
from .pixel_motion import capability_text as _pixel_capability
MOTION_DELIVERY += '\n'+_pixel_capability()
MOTION_DELIVERY += "\nv2 wiggle轨使用独立wrapper与全零from/to x/y/rotation；wiggle全部字段：amplitudeX/amplitudeY:0..240px、rotation:0..30度、frequency:0.1..60Hz、seed:整数0..2147483647、intensity:0..4、fadeInMs/fadeOutMs:0..30000。按cue绝对时间确定性采样，不能同时有repeat/yoyo/sustain/stagger。durationMs可限制短震颤窗口。minCueMs跳过短句次要事件，不加速频率；无需模型编写JS。"
