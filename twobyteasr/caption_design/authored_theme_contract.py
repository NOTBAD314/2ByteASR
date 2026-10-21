"""Fresh authored delivery: describe existing validation, never rewrite artwork.

The schema guides providers and catches representable format errors. HTML
parsing, cross-track relationships and rendered pixels remain authoritative.
Legacy project/import contracts are deliberately unchanged.
"""
from __future__ import annotations

import re

from .theme_metadata import NAME_SCHEMA, ID_SCHEMA
from .theme_motion import MOTION_OUTPUT_SCHEMA
from .web_theme import (
    WEB_THEME_SCHEMA, WEB_THEME_VERSION, _MAX_HTML_CHARS, _MAX_CSS_CHARS,
    _MAX_HTML_NODES, _ALLOWED_TAG_NAMES, _ALLOWED_ATTRS,
    _FORBIDDEN_CSS_TOKENS, _WORDS_WRAPPER_RE, _APPEARANCE_FONT_MAX,
)


def _literal_pattern(text):
    # JSON Schema uses ECMA-compatible patterns; inline Python (?i) flags
    # would make the same schema unusable on other provider transports.
    return ''.join('['+c.lower()+c.upper()+']' if c.isascii() and c.isalpha()
                   else re.escape(c) for c in text)


HEX_COLOR = {'type': 'string', 'pattern': r'^#[0-9a-fA-F]{6}$'}
OPTIONAL_COLOR = {'type': 'string', 'pattern': r'^(?:|#[0-9a-fA-F]{6})$'}
STATIC_CSS_FORBIDDEN = (
    _literal_pattern('@keyframes') + r'|(?:^|[;{])\s*(?:' +
    _literal_pattern('animation') + '|' + _literal_pattern('transition') +
    r')(?:-[\w-]+)?\s*:'
)
CSS_SCHEMA = {'type': 'string', 'maxLength': _MAX_CSS_CHARS, 'allOf': [
    {'not': {'pattern': STATIC_CSS_FORBIDDEN}},
    {'not': {'pattern': '|'.join(_literal_pattern(t) for t in _FORBIDDEN_CSS_TOKENS)}},
    # URL semantics belong to checked_css_urls + the SVG parser. Searching the
    # entire string also matches encoded SVG filter="url(%23id)" inside data.
]}
PALETTE_SCHEMA = {'type': 'object', 'required': ['primary', 'text'], 'properties': {
    'primary': HEX_COLOR, 'text': HEX_COLOR,
    **{key: OPTIONAL_COLOR for key in ('secondary', 'background', 'accent')},
}}
APPEARANCE_SCHEMA = {'type': 'object', 'properties': {
    'fontFamily': {'type': 'string', 'maxLength': _APPEARANCE_FONT_MAX,
        'not': {'pattern': '|'.join(_literal_pattern(t) for t in
                 ('javascript:', 'url(', '@import', '<', '>'))}},
    **{key: {'type': 'number', 'minimum': low, 'maximum': high} for key, low, high in (
        ('fontSize', 16, 200), ('fontWeight', 1, 1000), ('strokeWidth', 0, 30),
        ('stroke2Width', 0, 30), ('letterSpacing', -8, 40))},
    'bold': {'type': 'boolean'}, 'italic': {'type': 'boolean'},
    **{key: OPTIONAL_COLOR for key in ('color', 'strokeColor', 'stroke2Color')},
}}
AUTHORED_SOURCE_SCHEMA = {'type': 'object',
    'required': ['name', 'palette', 'cueHtml', 'cueCss', 'stageHtml', 'stageCss', 'motionSpec'],
    'properties': {
        'schema': {'const': WEB_THEME_SCHEMA}, 'version': {'const': WEB_THEME_VERSION},
        'name': NAME_SCHEMA, 'id': ID_SCHEMA, 'concept': {'type': 'string'}, 'notes': {'type': 'string'},
        'palette': PALETTE_SCHEMA, 'appearance': APPEARANCE_SCHEMA,
        'stageHtml': {'type': 'string', 'pattern': r'^\s*$',
            'description': '必须为空字符串；宿主创建舞台，作者全部图层放在cueHtml。'},
        'stageCss': dict(CSS_SCHEMA, description='可为空；只允许静态CSS，推荐所有作者样式放cueCss。'),
        'cueHtml': {'type': 'string', 'minLength': 1, 'maxLength': _MAX_HTML_CHARS,
            'pattern': r'\{\{\s*(?:text|words)\s*\}\}',
            'not': {'pattern': _WORDS_WRAPPER_RE.pattern},
            'description': '仅作者内容片段，不能是完整网页，也不得重建宿主；使用白名单HTML和属性。'},
        'cueCss': dict(CSS_SCHEMA, minLength=1, pattern=r'var\(--wt-font',
            description='完整静态CSS，正文使用var(--wt-font)和var(--wt-size)。'),
        'motionSpec': MOTION_OUTPUT_SCHEMA,
    },
}
COLOR_ROLES = ('base', 'primary', 'contrast', 'support', 'highlight', 'shadow')
COLOR_ROLE_SCHEMA = {'type': 'array', 'items': {'type': 'object', 'required': ['role', 'percent'],
    'properties': {'role': {'type': 'string'}, 'percent': {'type': 'number', 'minimum': 0, 'maximum': 100},
                   'hex': HEX_COLOR}},
    'allOf': [{'contains': {'type': 'object', 'required': ['role'],
                          'properties': {'role': {'const': role}}}} for role in COLOR_ROLES],
}
SEMANTIC_MOTION_SCHEMA = {'type': 'object', 'required': ['entrance', 'hold', 'exit'],
    'properties': {phase: {'not': {'enum': [None, False, 0, '', {}, []]},
        'description': '非空语义动作说明，通常为字符串或对象。'} for phase in ('entrance', 'hold', 'exit')},
}

AUTHORED_TECHNICAL_DELIVERY = f'''以下是实际作者源码入口和选中后的渲染验收契约，不是美术模板；在这些边界内独立设计，不用固定布局代替用户主题。
1. 宿主与片段：stageHtml 必须为空字符串。宿主已创建html/body/.wt-frame/.wt-stage/.wt-scope/.wt-cue/subtitle-placement/.theme-motion；不得自行创建宿主或在cueHtml再嵌套.wt-cue。cueHtml只包含作者的字幕、材质和装饰节点，全部随cue销毁。stageCss可为空，推荐把作者静态样式全部放cueCss；不得改宿主placement/transform或创建全屏背景。宿主.wt-cue覆盖整个画面，并不自动把作者节点布局到底部。
2. 字段与颜色：可省略schema/version；提供时只能是{WEB_THEME_SCHEMA}/1。name是1–80字单行非空字符串，id是独立稳定英文标识。palette必须有primary/text，颜色用#RRGGBB，不用#RGB、rgba、颜色名或transparent；可选secondary/background/accent可以为空。appearance是对象；fontFamily最多{_APPEARANCE_FONT_MAX}字符，不含URL/脚本/标记；fontSize16–200、fontWeight1–1000、strokeWidth/stroke2Width0–30、letterSpacing -8–40，均为数字；bold/italic为布尔；color/strokeColor/stroke2Color用#RRGGBB或空字符串。
3. HTML 白名单：{', '.join(sorted(_ALLOWED_TAG_NAMES))}。每段HTML最多{_MAX_HTML_CHARS}字符、{_MAX_HTML_NODES}节点；HTML应完整闭合。属性白名单：{', '.join(sorted(_ALLOWED_ATTRS))}。不能使用style 属性、事件属性、任意data-*属性、脚本、img、iframe、外部资源或HTML 注释；它们会被拒绝或在安全重建后因作者源码改变而拒收。属性用双引号；SVG标签用白名单中的小写拼写，属性用上列规范拼写；几何空元素自闭合，不额外闭合；文本直接用Unicode，避免实体编码导致安全重建改变源码。id须以英文字母或下划线开头，仅字母数字/下划线/冒号/点/连字符，不能用wt-cue/wt-frame/wt-theme-data。不要依赖适配器删除或修改原稿来通过。
4. 正文与字体：正文必须保留{{{{text}}}}或{{{{words}}}}，不能只写固定示例文本或speaker。{{{{words}}}}会由宿主展开成.wt-w，不要再包进.wt-w。需要多层描边/扫描副本时仅一个主体标data-semantic-text="true"，其他正文副本标aria-hidden="true"，共用字体与尺寸。cueCss必须消费var(--wt-font)，正文同时使用var(--wt-size)，字重可用var(--wt-weight)。离线字体由应用提供，按给定字体名称选择，不写@font-face或字体资源URL；不在普通文字上用伪粗体冒充Cubic 11字形。CSS尺寸用百分比/vh或calc(N * var(--wt-u))适配画布；1080高时1u=12px，--wt-size已是CSS长度。
5. CSS：每段最多{_MAX_CSS_CHARS}字符，cueCss不能为空。只允许静态CSS，不能有animation/transition/@keyframes，不输出相关声明的注释。禁止@import/expression/behavior/-moz-binding/javascript及任何外部/data URL；仅允许url(#内部SVG引用)，引用id必须实际存在。括号、花括号、calc/inset/polygon等都要闭合。静态CSS的类选择器可以组合，但MotionSpec选择器另受更窄语法限制。
6. 作者契约：三稿在构图、材质、字形或动作上应有可辨识的视觉区别，由实际预览判断；相同DOM标签树合法，不要增加无意义节点。ColorRole覆盖base/primary/contrast/support/highlight/shadow六用途，每项percent是0–100数字；颜色可复用。MaterialContract每个selector必须匹配cueHtml中有实际样式的材质节点，允许单class、复合class、class后代/子级链，不要求CSS规则与契约逐字相同。MotionContract含非空entrance/hold/exit语义说明。
7. 主题职责：用户原始需求为唯一主题来源，不要求在多个对象重复填写theme。艺术契约写具体辨识点及用户指定/作者补充的区别；设计说明写构图、形体、材质、字体文字区域及配色。字段含有主题名称不能证明实际画面达标。不得把其他任务的历史题材或固定类名强加给当前作品。主题与审美在真实帧上单独检查，技术检查仅验证可执行契约。
8. 实际渲染：主字幕必须绑定 build 和 resolve，目标应是实际承载正文的内部元素或其作者祖先，不能只让装饰运动；buildMs/resolveMs要留出真实可见的有限动作，两端from/to属性集合完全相同，实际同一节点同一属性的窗口不重叠，顺序阶段合法。先用6秒真实中文完成完整作品，再做短句、多行和短cue适配；保持段正文完整，左右在0.03..0.97内、上下在0.03..0.98内并留描边余量。构图由主题决定，不强制狭长条或底部居中。整体不透明像素覆盖不能超过40%，透明区域让视频可见。6秒预览会检查建立、阅读和退出的连续动画，正文入退场须有真实像素变化，保持段不透明度至少0.5。技术通过不等于视觉通过，仍需实际看图。
9. 可读性按合成时间线验证：没有入场时首个呈现帧就是正确正文；有明确入场时允许短暂揭示或opacity=0，默认尽早可读，装饰可以继续入场。不逐轨要求可见；父容器、遮罩、裁切、位置与字层共同决定结果。50–100ms短cue由宿主直接呈现稳定阅读姿态，不改cue时间。缓存未准备、旧字或占位仍是运行错误。
10. 画幅实测1920×1080、1280×720与960×540。固定px不会自动缩放；作者可定义--design-px:calc(100vh / 1080)，长度写calc(N * var(--design-px))。静态根定位与动作层分开，长句允许安全宽度内换行，主体石纹/材质只占局部框体，不让满幅SVG rect遮挡视频。内联feTurbulence的seed只允许0..4096整数；feMerge及feMergeNode可用，禁止外部资源。
提交前自检完整JSON、stageHtml空、白名单、字体token、颜色、六用途、材质实层及MotionSpec；视觉质量需看实际预览。'''

# A single bounded exception to the external/data URL prohibition above. Both
# the full import validator and aggregate repair diagnostics use the same parser.
AUTHORED_TECHNICAL_DELIVERY=AUTHORED_TECHNICAL_DELIVERY.replace(
    '禁止@import/expression/behavior/-moz-binding/javascript及任何外部/data URL；仅允许url(#内部SVG引用)，引用id必须实际存在。',
    '禁止@import/expression/behavior/-moz-binding/javascript及网络、文件、任意data URL。允许url(#内部SVG引用)，仅用于SVG paint/filter/clip，不能作为CSS background-image。背景纹理另支持有引号的url("data:image/svg+xml,百分号编码SVG")：解码≤4096字节、≤64节点、宽高1–1024；只支持svg/g/rect/circle/ellipse/line/polyline/polygon/path及数值几何、纯色#RGB或#RRGGBB fill/stroke/opacity。禁止script/style/事件/href/image/foreignObject/动画/字体/递归引用/DTD/实体。复杂纹理直接使用白名单内联SVG或CSS渐变。所有纹理随主题内嵌，不依赖外部文件。')
AUTHORED_TECHNICAL_DELIVERY+='\n额外声明性属性支持data-block，值为1–48个英文数字下划线连字符且英文字母开头；data-emphasis用于下文说明的正文词组匹配。二者均不会执行代码，MotionSpec仍仅选择class。其余未列入白名单的data-*禁止。MaterialContract另允许SVG标签后代/子级选择器及实际data-emphasis对应的可选.wt-focus材质；此能力不放宽MotionSpec选择器。'
AUTHORED_TECHNICAL_DELIVERY+='\n静态SVG纹理还支持defs/filter/feTurbulence：最多4个带唯一id的filter，每个仅一个feTurbulence；baseFrequency为0.001–1，numOctaves为1–4，seed为0–4096整数（省略为固定0）。形状filter仅引用同一SVG内url(#id)。禁止href、feImage、嵌套滤镜/输入图、外链与可执行内容。'
