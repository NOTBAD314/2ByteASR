"""Static caption design contract. Asset/visual gates precede motion authoring.

This module produces static local preview documents only. It neither changes
the shared paused-GSAP runtime nor creates a MotionSpec or a selected option.
"""
from __future__ import annotations

import base64
import copy
import hashlib
from html import escape
import math
from pathlib import Path
import re


V3_FIELDS = (
    "canvas_transparent", "local_backplate", "text_fill_layers", "gradient_stops",
    "outline_layers", "shadow_layers", "material_stack", "palette_roles", "motif_asset",
    "asset_source", "asset_min_display_size", "composition_silhouette", "semantic_integration",
    "motion_beats", "safe_area",
)

V3_CONCEPT_RULES = """
DesignSpec V3：design.visual_contract_version=3，保留metaphor/silhouette/hierarchy/font/colors/material/rhythm/forbidden/content_relevance，
并给出canvas_transparent、local_backplate、text_fill_layers、gradient_stops、outline_layers、shadow_layers、
material_stack、palette_roles、motif_asset、asset_source、asset_min_display_size、composition_silhouette、semantic_integration、motion_beats、safe_area。
透明画布允许、且本次要求字幕簇的局部冰雪底板。text_fill_layers明确渐变，gradient_stops引用颜色职责；至少两层非单黑描边。
角色仅在有清楚可辨的合格PNG/WebP时使用。图像工具404/超时/不可用后，记录实际错误，motif_asset=null、asset_source.kind=omitted，立即生成无角色方案，不阻断排版、底板、材质和构图。
不得用inline SVG、CSS图形、emoji、抽象白块代替关键吉祥物，不允许捏造资产路径或已通过的视觉检查。
三稿轮廓、底板、主题元素、字体材质和密度不同；同句同背景同1920x1080及底部安全区。无角色稿不保留空的角色占位区。
motion_beats此时只写动作隐喻说明，禁止MotionSpec、GSAP代码或任何动画。输出结构化设计，不输出HTML。
"""


class DesignSpecError(ValueError):
    pass


class MotifAssetUnavailable(DesignSpecError):
    pass


def _number(value, lo, hi, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise DesignSpecError(f"{field} 必须在 {lo}..{hi} 范围")
    return float(value)


def validate_design_spec(spec):
    """Validate the design, allowing an explicit pending asset checkpoint."""
    if not isinstance(spec, dict) or spec.get("visual_contract_version") != 3:
        raise DesignSpecError("需要 DesignSpec visual_contract_version=3")
    missing = [key for key in V3_FIELDS if key not in spec]
    if missing:
        raise DesignSpecError("DesignSpec V3 缺少：" + "、".join(missing))
    if spec["canvas_transparent"] is not True:
        raise DesignSpecError("字幕画布必须透明；局部底板由local_backplate单独控制")
    roles = spec["palette_roles"]
    if not isinstance(roles, dict) or not 3 <= len(roles) <= 5:
        raise DesignSpecError("palette_roles需要3–5个明确颜色职责")
    for role, color in roles.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", str(role)) or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            raise DesignSpecError("palette_roles需要安全角色名和#RRGGBB")
    def role_in(layer):
        if not isinstance(layer, dict) or layer.get("role") not in roles:
            raise DesignSpecError("视觉图层必须引用palette_roles中的角色")
    stops = spec["gradient_stops"]
    if not isinstance(stops, list) or not 2 <= len(stops) <= 5:
        raise DesignSpecError("文字渐变至少需要两个gradient_stops")
    positions = []
    for stop in stops:
        role_in(stop)
        positions.append(_number(stop.get("offset"), 0, 1, "gradient_stops.offset"))
    if positions != sorted(positions) or positions[0] != 0 or positions[-1] != 1 or len({roles[x["role"]].lower() for x in stops}) < 2:
        raise DesignSpecError("gradient_stops必须从0到1按顺序且包含不同颜色，不能以纯色冒充渐变")
    fills = spec["text_fill_layers"]
    if not isinstance(fills, list) or not 1 <= len(fills) <= 3:
        raise DesignSpecError("text_fill_layers需要1–3层")
    for fill in fills:
        if not isinstance(fill,dict) or fill.get("kind") != "linear_gradient" or fill.get("stops") != "gradient_stops":
            raise DesignSpecError("文字填充必须实际引用gradient_stops")
        _number(fill.get("angle"), 0, 360, "fill.angle")
        _number(fill.get("opacity", 1), 0.1, 1, "fill.opacity")
    outlines = spec["outline_layers"]
    if not isinstance(outlines, list) or not 2 <= len(outlines) <= 4:
        raise DesignSpecError("必须使用2–4层边缘，不能只有单层纯黑描边")
    widths = []
    for layer in outlines:
        role_in(layer)
        widths.append(_number(layer.get("width"), .5, 16, "outline.width"))
    if widths != sorted(widths, reverse=True) or len(set(widths)) != len(widths):
        raise DesignSpecError("描边按外到内递减，否则后层会覆盖前层")
    if len({roles[x["role"]].lower() for x in outlines}) < 2:
        raise DesignSpecError("多层边缘必须有不同色阶")
    if not isinstance(spec["shadow_layers"], list) or len(spec["shadow_layers"]) > 2:
        raise DesignSpecError("shadow_layers最多2层")
    for shadow in spec["shadow_layers"]:
        role_in(shadow)
        for key, lo, hi in (("x",-12,12),("y",-12,12),("blur",0,16),("opacity",0,1)):
            _number(shadow.get(key),lo,hi,"shadow."+key)
    plate = spec["local_backplate"]
    if not isinstance(plate, dict) or plate.get("enabled") is not True:
        raise DesignSpecError("本设计需要围绕字幕簇的局部冰雪底板")
    for key in ("role", "edge_role"):
        role_in({"role":plate.get(key)})
    if plate.get("structure") not in {"ice-ledge", "split-slab", "snow-crest", "glacier-window", "frost-ticket"}:
        raise DesignSpecError("local_backplate.structure不受支持")
    materials = spec["material_stack"]
    if not isinstance(materials, list) or not 1 <= len(materials) <= 3:
        raise DesignSpecError("material_stack需要1–3层")
    for layer in materials:
        role_in(layer)
        if layer.get("kind") not in {"frost_grain", "ice_strata", "etched_lines"}:
            raise DesignSpecError("未知material_stack材质")
        _number(layer.get("opacity"),.01,.5,"material.opacity")
    layout = spec["composition_silhouette"]
    if not isinstance(layout,dict) or layout.get("motif_position") not in {"left", "right", "center", "none"} or not layout.get("description"):
        raise DesignSpecError("composition_silhouette需要轮廓说明和熊的位置")
    _number(layout.get("width"), 700, 1500, "silhouette.width")
    _number(layout.get("font_size"), 60, 100, "silhouette.font_size")
    size = spec["asset_min_display_size"]
    if not isinstance(size,dict):
        raise DesignSpecError("asset_min_display_size需要width和height")
    _number(size.get("width"),140,240,"asset_min_display_size.width")
    _number(size.get("height"),140,198,"asset_min_display_size.height")
    if layout["motif_position"] == "center" and size["height"] + layout["font_size"]*1.03 + max(widths)/2 > 216:
        raise DesignSpecError("中央熊与正文的实际尺寸超出216px底部安全区")
    safe = spec["safe_area"]
    if not isinstance(safe,dict) or safe.get("canvas") != [1920,1080]:
        raise DesignSpecError("safe_area.canvas必须为1920x1080")
    if safe.get("bounds") != [96,810,1824,1026]:
        raise DesignSpecError("三个候选必须使用相同底部安全区[96,810,1824,1026]")
    if not isinstance(spec["semantic_integration"],str) or len(spec["semantic_integration"].strip()) < 10:
        raise DesignSpecError("semantic_integration必须说明熊、框体与文字的关系")
    beats = spec["motion_beats"]
    if not isinstance(beats,dict) or set(beats) != {"build","breathe","resolve"} or not all(isinstance(v,str) and v.strip() for v in beats.values()):
        raise DesignSpecError("motion_beats此时只允许三段动作隐喻文字")
    source = spec["asset_source"]
    if not isinstance(source,dict) or source.get("kind") not in {"pending","omitted","existing","imagegen"} or not source.get("description"):
        raise DesignSpecError("asset_source需要真实来源，缺失资产明确pending")
    asset = spec["motif_asset"]
    if source["kind"] in {"pending","omitted"}:
        if asset is not None:
            raise DesignSpecError("pending资产不能伪造motif_asset")
    elif not isinstance(asset,dict) or not asset.get("path") or not re.fullmatch(r"[0-9a-f]{64}",str(asset.get("sha256",""))):
        raise DesignSpecError("motif_asset需要本地路径和实际SHA256")
    return copy.deepcopy(spec)


def resolve_motif(spec, asset_root):
    """No placeholders, remote downloads or generated-path guesses."""
    validate_design_spec(spec)
    asset = spec["motif_asset"]
    if asset is None:
        raise MotifAssetUnavailable("缺少合格的北极熊+滑雪镜透明PNG/WebP；静态英雄帧未生成")
    root = Path(asset_root).resolve()
    relative = Path(asset["path"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or path.suffix.lower() not in {".png",".webp"}:
        raise DesignSpecError("吉祥物必须来自指定资产目录中的PNG/WebP")
    if not path.is_file():
        raise MotifAssetUnavailable("指定吉祥物文件不存在："+asset["path"])
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != asset["sha256"]:
        raise DesignSpecError("吉祥物文件SHA256已变化，需要重新检查")
    from PIL import Image
    with Image.open(path) as image:
        if image.format not in {"PNG","WEBP"} or "A" not in image.getbands():
            raise DesignSpecError("吉祥物必须具有真实Alpha透明通道")
        alpha = image.getchannel("A")
        if alpha.getextrema() != (0,255) or alpha.getbbox() is None:
            raise DesignSpecError("吉祥物缺少透明区域或实心主体")
        if image.width < spec["asset_min_display_size"]["width"] or image.height < spec["asset_min_display_size"]["height"]:
            raise DesignSpecError("资产分辨率小于实际展示尺寸")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/webp"
    return "data:"+mime+";base64,"+base64.b64encode(blob).decode("ascii")


def optional_motif(spec,asset_root):
    """An unavailable/unsuitable character degrades to a complete character-free design."""
    if spec.get('motif_asset') is None:
        return None,dict(status='omitted',reason=spec.get('asset_source',{}).get('description','no character asset'),
                         provider_error=spec.get('asset_source',{}).get('provider_error'))
    try:
        return resolve_motif(spec,asset_root),dict(status='qualified')
    except (DesignSpecError,OSError,ValueError) as exc:
        return None,dict(status='omitted',reason=str(exc),category='character_asset_unavailable')


def compile_static_html(spec, text, *, asset_root, background_data=""):
    """Consume the visual contract; missing characters never block static typography."""
    spec = validate_design_spec(spec)
    motif,asset_status = optional_motif(spec,asset_root)
    from .web_theme_fonts import FONT_FILES, offline_font_css
    family = spec.get("font_family")
    if family not in FONT_FILES:
        raise DesignSpecError("font_family必须是已注入的本地字体")
    if background_data and not re.fullmatch(r"data:image/(?:png|webp|jpeg);base64,[A-Za-z0-9+/=]+",background_data):
        raise DesignSpecError("背景必须为调用者冻结的本地图像数据")
    aliases={'ice_white':spec['gradient_stops'][0]['role'],'ice_blue':spec['gradient_stops'][-1]['role'],
             'blue_grey':spec['local_backplate']['edge_role'],'deep_blue':spec['local_backplate']['role'],
             'glacier':spec['gradient_stops'][-1]['role']}
    def color(role): return spec["palette_roles"].get(role,spec['palette_roles'].get(aliases.get(role,''),next(iter(spec['palette_roles'].values()))))
    def rgba(role,opacity):
        rgb = color(role)
        return f"rgba({int(rgb[1:3],16)},{int(rgb[3:5],16)},{int(rgb[5:7],16)},{opacity})"
    stops = ",".join(f"{color(s['role'])} {s['offset']*100:g}%" for s in spec["gradient_stops"])
    plate = spec["local_backplate"]
    layout = spec["composition_silhouette"]
    shape = plate["structure"]
    shadows = ",".join(f"{s['x']}px {s['y']}px {s['blur']}px {rgba(s['role'],s['opacity'])}" for s in spec["shadow_layers"]) or "none"
    layers=[]
    for index, layer in enumerate(spec["outline_layers"]):
        layers.append(f'<span class="v3-letter outline" aria-hidden="true" style="-webkit-text-stroke:{layer["width"]}px {color(layer["role"])};color:{color(layer["role"])};text-shadow:{shadows if index==0 else "none"}">{escape(text)}</span>')
    for layer in spec["text_fill_layers"]:
        layers.append(f'<span class="v3-letter fill" style="background-image:linear-gradient({layer["angle"]}deg,{stops});opacity:{layer.get("opacity",1)}">{escape(text)}</span>')
    materials=[]
    for layer in spec["material_stack"]:
        c=rgba(layer["role"],layer["opacity"])
        pattern={"frost_grain":f"radial-gradient({c} .7px,transparent 1px)",
                 "ice_strata":f"repeating-linear-gradient(170deg,transparent 0 7px,{c} 8px 9px,transparent 10px 23px)",
                 "etched_lines":f"repeating-linear-gradient(90deg,transparent 0 29px,{c} 30px 31px)"}[layer["kind"]]
        materials.append(f'<div class="v3-material" style="background-image:{pattern};background-size:{"4px 4px" if layer["kind"]=="frost_grain" else "auto"}"></div>')
    font_css=offline_font_css(family)
    variables=";".join(f"--palette-{key}:{value}" for key,value in spec["palette_roles"].items())
    asset_size=spec["asset_min_display_size"]
    decoration='''<div class="v3-structure" aria-hidden="true"><i class="joint joint-left"></i><i class="joint joint-right"></i><i class="crest"></i><i class="edge-rail"></i><i class="facet"></i></div>'''
    # All theme elements carry the plate, border or stamped treatment. No
    # pseudo-character is substituted when the optional mascot is unavailable.
    extra_css=f'''
.without-motif .v3-type{{left:80px;right:80px;top:97px}}
.v3-structure{{position:absolute;inset:0;pointer-events:none;color:{color('ice_blue')}}}
.v3-structure i{{position:absolute;display:block}}
.glacier-window .v3-backplate{{inset:64px 0 9px;clip-path:polygon(3% 0,97% 0,100% 20%,100% 80%,97% 100%,3% 100%,0 80%,0 20%);border:0;background:linear-gradient(160deg,{color('blue_grey')},{color('deep_blue')} 16%,{color('deep_blue')} 75%,{color('blue_grey')});box-shadow:inset 0 3px 0 {color('ice_white')},inset 0 -6px 0 {color('deep_blue')}}}
.glacier-window .v3-backplate::before{{content:"";position:absolute;inset:9px 13px;border:2px solid {color('ice_blue')};clip-path:polygon(2% 0,98% 0,100% 16%,100% 84%,98% 100%,2% 100%,0 84%,0 16%);background:linear-gradient(174deg,{rgba('ice_blue',.22)},transparent 30%,{rgba('glacier',.1)} 80%);box-shadow:inset 0 1px 0 {rgba('ice_white',.8)}}}
.glacier-window .joint{{top:90px;width:42px;height:68px;border:2px solid {color('ice_blue')};background:linear-gradient(100deg,{color('blue_grey')},{color('deep_blue')});clip-path:polygon(0 14%,80% 0,100% 14%,100% 86%,80% 100%,0 86%)}}
.glacier-window .joint-left{{left:-12px}}.glacier-window .joint-right{{right:-12px;transform:scaleX(-1)}}
.glacier-window .edge-rail{{left:12%;right:12%;top:60px;height:6px;border-top:2px solid {color('ice_white')};background:{color('glacier')}}}
.glacier-window .facet{{top:66px;left:51px;width:30px;height:127px;background:linear-gradient(130deg,{rgba('ice_white',.22)},transparent);clip-path:polygon(0 0,100% 0,35% 100%,0 100%)}}
.split-slab .v3-backplate{{inset:82px 14px 6px;transform:skewX(-7deg);border:0;background:linear-gradient(168deg,{color('ice_white')} 0%,{color('blue_grey')} 8%,{color('deep_blue')} 10%,{color('blue_grey')} 82%,{color('ice_blue')} 84%,{color('deep_blue')} 100%);clip-path:polygon(3% 0,96% 0,100% 20%,97% 86%,68% 100%,2% 92%,0 68%)}}
.split-slab .v3-type{{top:83px;left:100px;right:88px}}
.split-slab .edge-rail{{bottom:6px;left:50px;right:62px;height:26px;background:linear-gradient(177deg,{color('ice_blue')},{color('glacier')} 30%,{color('deep_blue')} 35%);clip-path:polygon(0 0,100% 0,85% 75%,30% 100%,0 55%)}}
.split-slab .facet{{left:9px;bottom:23px;width:89px;height:137px;background:linear-gradient(122deg,{color('ice_white')} 0 25%,{color('ice_blue')} 26% 52%,{color('blue_grey')} 53% 76%,{color('glacier')} 77%);clip-path:polygon(63% 0,100% 72%,46% 100%,0 75%);filter:drop-shadow(4px 3px 0 {color('deep_blue')})}}
.split-slab .joint-right{{right:0;top:87px;width:67px;height:91px;background:linear-gradient(70deg,{color('ice_blue')},{color('blue_grey')});clip-path:polygon(0 0,84% 0,100% 45%,30% 100%)}}
.frost-ticket .v3-backplate{{inset:58px 20px 10px;border:3px solid {color('blue_grey')};background:linear-gradient(155deg,{color('ice_white')},{color('ice_blue')} 60%,{color('blue_grey')});clip-path:polygon(0 4%,100% 0,100% 91%,1% 100%);box-shadow:inset 0 3px 0 {color('ice_white')},inset 0 -10px 0 {rgba('deep_blue',.15)}}}
.frost-ticket::before{{content:"";position:absolute;inset:65px 17px 7px;background:{rgba('deep_blue',.55)};clip-path:polygon(0 4%,100% 0,100% 91%,1% 100%)}}
.frost-ticket .v3-type{{left:220px;right:45px;top:95px}}
.frost-ticket .joint-left{{left:33px;top:66px;width:167px;height:127px;border-right:2px dashed {color('blue_grey')};background:radial-gradient(circle at 50% 50%,{color('ice_white')} 0 31%,{color('ice_blue')} 32% 40%,{color('deep_blue')} 41% 42%,transparent 43%)}}
.frost-ticket .crest{{left:84px;top:104px;width:64px;height:64px;background:linear-gradient(140deg,{color('blue_grey')},{color('deep_blue')});clip-path:polygon(42% 0,58% 0,58% 28%,82% 12%,90% 25%,66% 42%,100% 42%,100% 58%,67% 58%,90% 77%,82% 89%,58% 72%,58% 100%,42% 100%,42% 72%,18% 89%,10% 77%,33% 58%,0 58%,0 42%,33% 42%,10% 25%,18% 12%,42% 28%)}}
.frost-ticket .edge-rail{{left:239px;right:65px;top:79px;height:3px;background:linear-gradient(90deg,{color('blue_grey')} 0 35%,transparent 35% 38%,{color('blue_grey')} 38% 100%)}}
.frost-ticket .joint-right{{right:42px;bottom:25px;width:43px;height:11px;background:repeating-linear-gradient(90deg,{color('deep_blue')} 0 2px,transparent 2px 5px)}}
'''
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{escape(spec.get("name","V3 static"))}</title>
<style>{font_css}
html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:transparent}}
.frame{{position:relative;width:1920px;height:1080px;{variables}}}.game{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.subtitle-placement{{position:absolute;left:96px;top:810px;width:1728px;height:216px}}
.v3-cluster{{position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:{layout['width']}px;height:216px}}
.v3-backplate{{position:absolute;inset:74px 0 0;background:linear-gradient(150deg,{color(plate['edge_role'])},{color(plate['role'])} 35%,{color(plate['role'])} 75%,{color(plate['edge_role'])});border:3px solid {color(plate['edge_role'])};box-shadow:0 4px 0 {color(plate['role'])};overflow:hidden}}
.ice-ledge .v3-backplate{{clip-path:polygon(2% 0,98% 0,100% 16%,98% 88%,86% 100%,8% 94%,0 77%,0 12%)}}
.split-slab .v3-backplate{{clip-path:polygon(3% 0,90% 0,94% 15%,100% 15%,97% 91%,58% 100%,55% 91%,0 100%)}}
.snow-crest .v3-backplate{{inset:82px 8% 0;clip-path:polygon(0 8%,18% 8%,23% 0,77% 0,82% 8%,100% 8%,96% 84%,50% 100%,4% 84%)}}
.v3-material{{position:absolute;inset:0;pointer-events:none}}.v3-type{{position:absolute;top:96px;left:220px;right:36px;display:grid}}
.v3-letter{{grid-area:1/1;font:900 {layout['font_size']}px/1.03 "{family}";text-align:center;white-space:pre-wrap;overflow-wrap:anywhere;letter-spacing:.015em}}
.fill{{background-clip:text;-webkit-background-clip:text;color:transparent;-webkit-text-stroke:0;text-shadow:none}}
.v3-motif{{position:absolute;bottom:12px;left:12px;width:{asset_size['width']}px;height:{asset_size['height']}px;object-fit:contain}}
.right .v3-motif{{left:auto;right:8px}}.right .v3-type{{left:30px;right:220px}}
.center .v3-motif{{left:50%;transform:translateX(-50%);bottom:auto;top:0}}.center .v3-type{{top:{asset_size['height']}px;left:110px;right:110px}}
{extra_css}</style><div class="frame">{f'<img class="game" src="{background_data}" alt="">' if background_data else ''}<div class="subtitle-placement">
<div class="v3-cluster {shape} {layout['motif_position'] if motif else 'without-motif'}" data-character-status="{asset_status['status']}" data-semantic-integration="{escape(spec['semantic_integration'],quote=True)}">
<div class="v3-backplate">{''.join(materials)}</div>{decoration}{f'<img class="v3-motif" src="{motif}" alt="戴滑雪镜的北极熊">' if motif else ''}
<div class="v3-type">{''.join(layers)}</div></div></div></div></html>'''


def validate_static_visual_evidence(evidence):
    """A technical render or checked=0 can never satisfy the human selection gate."""
    required = ("gradient_visible","layered_edges","local_backplate","integrated_silhouette","readable_actual_size",
                "palette_consumed","safe_area","reference_completeness")
    if isinstance(evidence,dict) and evidence.get('character_present'):
        required += ('bear_recognizable','goggles_recognizable')
    checked = evidence.get("checked",0) if isinstance(evidence,dict) else 0
    if isinstance(checked,bool) or not isinstance(checked,int) or checked <= 0:
        raise DesignSpecError("checked=0：没有有效静态视觉检查")
    backgrounds=evidence.get("backgrounds",[])
    if not isinstance(backgrounds,list) or not {"game","light","dark"} <= set(backgrounds):
        raise DesignSpecError("必须实际完成游戏/浅色/深色多背景检查")
    checks=evidence.get("checks",{})
    if not isinstance(checks,dict):
        raise DesignSpecError("静态视觉检查缺少逐项证据")
    for key in required:
        row=checks.get(key,{})
        if not isinstance(row,dict) or row.get("passed") is not True or not isinstance(row.get("evidence"),str) or len(row["evidence"].strip())<8:
            raise DesignSpecError("静态视觉硬门未通过："+key)
    return copy.deepcopy(evidence)
