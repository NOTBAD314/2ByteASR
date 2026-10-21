"""Keep a material enhancement attached to the artwork the user selected."""
import copy

PRESERVATION_DIRECTION = '''保护项：主要阅读阶段有实际承托和背景分离作用的主题框体、原角色辨识度及接触关系、已认可元素动效。最新反馈覆盖历史去框/缩小/静止化建议。增强设计感默认在原结构和动作上提高框面材质、内外边缘、局部厚度、明暗、文字与框面关系。允许颜色、纹理、边缘、字体和局部装饰协调调整，不得删框、缩成白色剪影、用裸字替代主题主体或清空持续动作。明确重构结构时须保留原动作意图并重新看完整动画。换句或data-emphasis不匹配也保留框、角色和基本动作。'''

SURFACE_DIRECTION = '''此次为保留构图与动作的材质增强：cueHtml、stageHtml、motionSpec逐值保留。保留现有CSS规则、定位、尺寸、transform、overflow、opacity、visibility、display与动作绑定，不新增会覆盖这些属性的规则。可修改或添加背景材质、颜色、填充、描边、边缘、阴影、字面材质和字体相关声明。不要用background:none、透明填充或大光晕消除实体框。增强后仍需实际画面审查，不以保护检查通过宣称美术达标。'''

PRESERVATION_DIRECTION += '''字面材质独立检查：CRT像素栅格、磷光与玻璃后显像；木刻固定木纹、刻槽暗壁和同光向窄亮边；冰雪霜面与冷反光。框体主体必须完整进出且有主题事件。非发光木材阅读可保持稳定，不强加字面循环扫光。用户明确否定的上下渐隐主动作、扫白亮带、硬切或动作缺失属于可修改缺陷，不作为认可动作冻结；保护框体、角色、稳定字形和已认可材质。明确动画修复/受保护重做允许相关HTML、CSS、图层与MotionSpec协调变化，用户显式锁仍保留。严格材质增强不暗中改动作；动作问题使用动画修复/重做。审查需同条件原稿/修订稿，查看第一帧、末段、固定字区连续1.5/3/6秒，不以少量离散帧或整帧MAE排除字面闪烁。'''


def protect_structure(theme, constraints):
    """This scope freezes topology and motion, not all appearance parameters."""
    rows=copy.deepcopy(constraints)
    for key in ('cueHtml','stageHtml','motionSpec'):
        if key in theme and not any(r['path']==[key] for r in rows):
            rows.append(dict(path=[key],exists=True,value=copy.deepcopy(theme[key]),origin='recognized_structure_and_motion'))
    return rows


def resolve_appearance_references(proposed, original):
    """An explicit current-font reference retains that source's literal value."""
    value=copy.deepcopy(proposed);changes=[]
    appearance=value.get('appearance',{})
    for key,reference in (('fontFamily','var(--wt-font)'),('fontSize','var(--wt-size)')):
        if appearance.get(key)==reference and key in original.get('appearance',{}):
            appearance[key]=copy.deepcopy(original['appearance'][key])
            changes.append(dict(path=['appearance',key],reference=reference,action='retain_current_literal'))
    return value,changes


def validate_surface_revision(before, after):
    """Reject geometry/visibility rewrites instead of transplanting incompatible CSS.

    Material and typography remain editable. Actual render review is still
    required: source invariants cannot establish perceived material quality.
    """
    from .authored_repair import css_values
    material={'color','fill','fill-opacity','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','paint-order',
              'box-shadow','text-shadow','filter','-webkit-text-stroke','-webkit-text-stroke-color',
              '-webkit-text-stroke-width','-webkit-text-fill-color','-webkit-background-clip','letter-spacing','line-height'}
    def editable(prop):
        return prop in material or prop.startswith(('background','border','font'))
    def geometry(css):
        result={}
        for item in css_values(css):
            if not editable(item['property']):
                result.setdefault((item['selector'],item['property']),[]).append(item['value'])
        return result
    for key in ('cueHtml','stageHtml','motionSpec'):
        if before.get(key)!=after.get(key):raise ValueError('材质增强改变了保护的结构或动作：'+key)
    for key in ('cueCss','stageCss'):
        old,new=geometry(before.get(key,'')),geometry(after.get(key,''))
        if old!=new:
            changed=[str(k) for k in old.keys()|new.keys() if old.get(k)!=new.get(k)]
            raise ValueError('材质增强改变了构图或可见性；保留原稿：'+', '.join(changed[:8]))
