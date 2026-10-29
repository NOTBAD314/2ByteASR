"""Executable material/motion examples for the existing source authoring path.

No renderer or timeline lives here. The exact same HTML and MotionSpec contract
is validated, serialized and consumed by the shared production renderer.
"""


def capability_text():
    return '''可复用能力 caption-effects-1（2ByteASR自有接口，不是HyperFrames原生API）：
材质填字/独立阴影：同一定位组内后置aria-hidden字形副本承载实色厚度/阴影，前置唯一data-semantic-text="true"正文的透明填字必须text-shadow:none。示例HTML：<div class="material-group"><div class="type-depth" aria-hidden="true">{{text}}</div><div class="type-face" data-semantic-text="true">{{text}}</div><div class="front-shell" aria-hidden="true"></div></div>。CSS各字形层共用font-family:var(--wt-font);font-size:var(--wt-size);line-height/letter-spacing/padding；depth绝对inset:0，face相对定位。face [data-caption-text]用background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-shadow:none；background可叠加数个非均匀radial-gradient、细纹与主色层，不只单一线性渐变。共享材料坐标时把background应用于整句块，而非每个.wt-w重复小贴图；SVG纹理/遮罩使用内部defs与url(#id)。前壳绝对inset:0，局部稀疏覆盖字和框，静态空间坐标与字面一致；screen/multiply/soft-light按区域需要选用，不强制全用。不用backdrop-filter声称独立RGBA会折射未知视频。
确定性wiggle：MotionSpec2 track用独立内层selector指定整组/词组/单字/材质；外层负责静态落位，另一层负责入退场。from/to必须都是{"x":0,"y":0,"rotation":0}。wiggle字段全部必填：amplitudeX/amplitudeY（1080高参考px）、rotation（度）、frequency（Hz）、seed（固定整数0..2147483647）、intensity（0..4）、fadeInMs/fadeOutMs（0..30000ms）；幅度0..240、旋转0..30、频率0.1..60。wiggle轨不混repeat/yoyo/sustain/stagger。每帧只取cueTime/seed/参数，宿主GSAP属性setter在seek(t,true)下也会采样；不写JS/onUpdate/rAF。
低强度整组例：{"selector":".material-wiggle","phase":"breathe","start":0,"end":1,"ease":"none","from":{"x":0,"y":0,"rotation":0},"to":{"x":0,"y":0,"rotation":0},"wiggle":{"amplitudeX":1.0,"amplitudeY":0.65,"rotation":0.1,"frequency":1.6,"seed":29,"intensity":1,"fadeInMs":160,"fadeOutMs":180}}。
短颤例：使用其内层.material-shiver，同样零基态from/to，phase:breathe,start:0.45,end:0.65,durationMs:180,minCueMs:2600，wiggle:{amplitudeX:1.6,amplitudeY:0.8,rotation:0.13,frequency:22,seed:73,intensity:1,fadeInMs:35,fadeOutMs:100}。短cue省略次要事件，频率不因缩短cue加速。关闭intensity:0；可选弱/中/强通过实际参数表达。选择.wt-w或.wt-focus时仍遵守真实拓扑/optional，不给宿主subtitle-placement运动。
碎裂：把共享坐标的框体/字面/前壳放在同一个piece组内，静态polygon裁成覆盖主体的片组；每片build短距归位、resolve沿其对应裂纹分别旋转/脱落，文字随该片退出。不要只飞装饰片后矩形擦除主体。各片轨道可独立，最多64条；minCueMs可省略短句次要事件，保持完整成型阅读态。冰未裂开时整个组关联运动；其他主题可选逐字波动、词组震动或弹性落位。不得为冰复制中心横展、果冻拉伸、持续流动纹理、通栏扫光。'''
