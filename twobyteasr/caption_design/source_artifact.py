"""Versioned UTF-8 authoring transport; never executed as a page or command.

The provider owns source and declarative motion. The application owns identity,
serialization and the existing WebTheme/render sandbox. Framing is exact: no
search for a plausible div, no incomplete response recovery, no JSON repair.
"""
from __future__ import annotations

import hashlib
import json
import re

VERSION = '2BYTE-ARTWORK/1'
SECTIONS = ('HTML', 'CSS', 'STAGE_CSS', 'PARAMETERS')
MAX_BYTES = 256 * 1024


def token(identity):
    return hashlib.sha256(str(identity).encode('utf8')).hexdigest()[:24]


def frame(values, identity, *, kind=VERSION):
    return (kind + ' ' + token(identity) + '\n' + ''.join(
        '===' + name + '===\n' + value + '\n' for name, value in values.items())
        + '===END ' + token(identity) + '===')


def unframe(raw, identity, names=SECTIONS, *, kind=VERSION):
    if not isinstance(raw, str) or len(raw.encode('utf8')) > MAX_BYTES:
        raise ValueError('源码工件缺失或超过安全资源预算')
    original = raw
    raw = raw.removeprefix('\ufeff').strip()
    wrappers = []
    if raw.startswith('```'):
        lines = raw.splitlines(keepends=True)
        if lines[0].strip() not in ('```', '```text', '```html', '```2byte') or lines[-1].strip() != '```':
            raise ValueError('源码工件外层围栏不完整')
        raw = ''.join(lines[1:-1]).strip()
        wrappers.append('single_code_fence')
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip('\r\n') != kind + ' ' + token(identity):
        raise ValueError('源码工件版本或本次请求身份不匹配')
    markers = ['===' + name + '===' for name in names] + ['===END ' + token(identity) + '===']
    positions = []
    for marker in markers:
        found = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == marker]
        if len(found) != 1:
            raise ValueError('源码工件边界缺失或重复：' + marker)
        positions.append(found[0])
    if positions != sorted(positions) or positions[0] != 1 or positions[-1] != len(lines) - 1:
        raise ValueError('源码工件分节乱序或包含多份正文')
    values = {}
    for name, start, end in zip(names, positions, positions[1:]):
        value = ''.join(lines[start + 1:end])
        # Remove only the framing newline; preserve every source character.
        values[name] = value[:-2] if value.endswith('\r\n') else value.removesuffix('\n')
    return values, dict(protocol=kind, request_token=token(identity), wrappers=wrappers,
                       original_sha256=hashlib.sha256(original.encode('utf8')).hexdigest())


def contract(identity):
    return ('返回单个完整UTF-8源码工件，严格按以下顺序和独占一行的分隔符。'
            'HTML/CSS原样写入，不转义为JSON，不编码Base64，不加解释或Shell命令。'
            'PARAMETERS使用components组合（其它分节留空），或motionSpec及可选palette/appearance配完整源码；不要重复候选ID、名称、正文或资源归属。'
            'stageHtml由宿主提供；STAGE_CSS可以为空。{{text}}/{{words}}由工程动态绑定。'
            '动画仅用motionSpec由宿主时间驱动，不能用脚本/墙钟/CSS animation。\n'
            + frame(dict(HTML='完整作者HTML片段', CSS='完整静态CSS', STAGE_CSS='',
                         PARAMETERS='{"motionSpec":声明式动画对象,"palette":{"primary":"#RRGGBB","text":"#RRGGBB"}}'), identity)
            + '\nmotionSpec严格使用上方motion_contract；这里不重复Schema。appearance可选fontFamily/fontSize/fontWeight。')


def to_theme(raw, identity, direction):
    parts, receipt = unframe(raw, identity)
    def reject_constant(value):
        raise ValueError('动画参数不能包含非有限值：' + value)
    params = json.loads(parts['PARAMETERS'], parse_constant=reject_constant)
    if not isinstance(params, dict) or not ({'motionSpec','components'} & set(params)):
        raise ValueError('源码工件缺少可按工程时间控制的动画参数')
    if set(params) - {'motionSpec', 'palette', 'appearance','components'}:
        raise ValueError('PARAMETERS只接受短动画、配色与字体参数；源码必须放在原文分节')
    if 'components' in params:
        if set(params)!={'components'} or any(parts[key].strip() for key in ('HTML','CSS','STAGE_CSS')):
            raise ValueError('组件组合与完整源码不可混用；请提交一种完整定义')
        from .caption_components import compose,VERSION as component_version
        expanded=compose(params['components'])
        parts.update(HTML=expanded['cueHtml'],CSS=expanded['cueCss'],STAGE_CSS='')
        params={key:expanded[key] for key in ('motionSpec','palette','appearance')}
        receipt['component_version']='caption-components-'+str(json.loads(parts['PARAMETERS'])['components']['version'])
        receipt['component_definition']=json.loads(unframe(raw,identity)[0]['PARAMETERS'])['components']
    from .web_theme import WEB_THEME_SCHEMA, WEB_THEME_VERSION
    theme = dict(schema=WEB_THEME_SCHEMA, version=WEB_THEME_VERSION,
                 id='artwork-' + token(identity), name=direction['name'],
                 palette=params.get('palette', {'primary':'#ffffff', 'text':'#ffffff'}),
                 appearance=params.get('appearance', {}), stageHtml='',
                 cueHtml=parts['HTML'], cueCss=parts['CSS'], stageCss=parts['STAGE_CSS'],
                 motionSpec=params['motionSpec'], notes='')
    receipt['source_sha256'] = {name: hashlib.sha256(value.encode('utf8')).hexdigest()
                               for name, value in parts.items()}
    return theme, receipt


def from_theme(theme, identity):
    """Serialize existing artwork for scoped repair input and offline tests."""
    return frame(dict(HTML=theme.get('cueHtml', ''), CSS=theme.get('cueCss', ''),
                      STAGE_CSS=theme.get('stageCss', ''),
                      PARAMETERS=json.dumps({key: theme[key] for key in
                          ('motionSpec', 'palette', 'appearance') if key in theme}, ensure_ascii=False)), identity)


def technical_contract():
    from .web_theme import _ALLOWED_TAG_NAMES, _ALLOWED_ATTRS, _MAX_HTML_CHARS, _MAX_CSS_CHARS, _MAX_HTML_NODES
    return (f'HTML片段最多{_MAX_HTML_CHARS}字符/{_MAX_HTML_NODES}节点；CSS最多{_MAX_CSS_CHARS}字符。'
        '宿主已提供舞台，所有图层在HTML分节，不重建宿主、不覆盖整屏。'
        '宿主.wt-cue覆盖整幅1920×1080，并不会自动把作者节点放到底部；position:relative会从左上角开始。'
        '作者须在自己的静态布局层明确位置，例如position:absolute;left:6%;right:6%;bottom:10%;display:flex;justify-content:center，内层再承载局部字幕与动作。此例仅说明坐标，不限定构图。静态定位与动作层分开。'
        '标签白名单：'+','.join(sorted(_ALLOWED_TAG_NAMES))+'。属性白名单：'+','.join(sorted(_ALLOWED_ATTRS))+'。'
        '属性双引号、完整闭合；禁止style属性/事件/脚本/注释/外部资源，SVG几何空元素自闭合。'
        '正文用{{text}}或{{words}}，后者宿主展开.wt-w，不再包入.wt-w；唯一主体data-semantic-text="true"，副本aria-hidden="true"。'
        '正文CSS必须用var(--wt-font)、var(--wt-size)，可用var(--wt-weight)。所选字体写入PARAMETERS.appearance.fontFamily/fontWeight；var(--wt-font)的fallback不会覆盖宿主默认字体。不要@font-face。'
        '尺寸用em/%/vh，固定参考像素用calc(N * var(--wt-u))，1080高时1u=12px。'
        'CSS禁止animation/transition/@keyframes/@import/expression/behavior/脚本与网络URL；内部SVG引用须存在。'
        '默认字幕外透明；正文保持段不透明度≥0.5，左右安全区3%..97%、上下3%..98%；整体覆盖≤40%。'
        '长句换行，短句收紧，允许多层边框、渐变、纹理、局部遮罩与高光。'
        '实际绑定正文的层必须参与build/resolve；终点前完成可见退出。安全检查保留原稿，不靠清理改写通过。')
