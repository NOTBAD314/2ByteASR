"""统一 UI 字体层级。

正文使用随包思源黑体 Medium，重点使用 Heavy。显式指定两个字面，
避免只有 Heavy 的机器把所有正文替换为 Heavy，或回退到过细的系统字体。
2026-11-13 起所有重点（字重 ≥ 600）都用真 Heavy，见文件末 emphasis 一节。
"""

from __future__ import annotations

import functools
import re
import sys

from ..caption_style.font_system import SOURCE_HAN_FAMILY_ALIASES

UI_FONT_FAMILIES = (
    "Source Han Sans SC Medium",
    "思源黑体 Medium",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI Variable",
    "Segoe UI",
    "Noto Sans CJK SC",
    "PingFang SC",
)
UI_FONT_STACK = ", ".join(f'"{name}"' for name in UI_FONT_FAMILIES) + ", sans-serif"

# 时间码/数值等宽栈：编辑器高频读数必须 tabular（数字跳动不位移）。
MONO_FONT_FAMILIES = (
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "SF Mono",
    "Menlo",
    "DejaVu Sans Mono",
    # CJK glyphs in logs/timecodes fall back to the bundled UI face instead of
    # whatever system CJK font Windows picks (2026-10-07 visual system).
    "Source Han Sans SC Medium",
    "Microsoft YaHei UI",
)
MONO_FONT_STACK = ", ".join(f'"{name}"' for name in MONO_FONT_FAMILIES) + ", monospace"

TITLE_FONT_FAMILIES = SOURCE_HAN_FAMILY_ALIASES + UI_FONT_FAMILIES
TITLE_FONT_STACK = ", ".join(f'"{name}"' for name in TITLE_FONT_FAMILIES) + ", sans-serif"

# 数值在此定义，design.tokens.WEIGHT_SCALE 为 QSS 提供同源语义映射。
# 字重规则（2026-11-13 修订；原 2026-10-07 规则把 600 当作 Medium 合成半粗）：
# 随包只有 Medium 与 Heavy 两个真实字面，Qt 没有中间档可用。
#   400/500 → Medium 字面（正文、控件、说明、普通数值）
#   ≥ 600   → Heavy 字面：所有重点——页标题、区块标题、主按钮、选中页签、
#             关键数字、标签 chip。QSS 规则里写 font-family: TITLE_FONT_STACK
#             （出口过 emphasis_qss() 会自动补），自绘文字用 heavy_font() /
#             weighted_font()。合成粗体（Medium + bold）一律不用：在 Windows
#             上 600 起就合成，看起来只比正文略粗，重点会“消失”。
# 650–950 与 600 渲染相同，新代码只写 500 / 600 / 800。
REGULAR = 400
MEDIUM = 500
SEMIBOLD = 600
BOLD = 700
HEAVY = 800

# 字号语义（px）：
#   PAGE_TITLE  页面大标题 21px Heavy
#   SECTION     分区标题   14px Heavy
#   BODY        正文       13px regular
#   VALUE       重要数值   13px Heavy
#   SECONDARY   次级信息   11-12px
PAGE_TITLE = 21
SECTION = 14
BODY = 13
VALUE = 13
SECONDARY = 11


def density_tokens(comfortable: bool) -> dict[str, int]:
    """两档字号 token。

    Compact（≤1440 宽，含 1366）：页面标题 18、角色卡模型名 22；
    Comfortable（≥1600，1920 主力）：页面标题 21、角色卡模型名 26、
    模型名 16、详情标题 20。禁止同比放大按钮；只调字号与少量行高。
    """
    if comfortable:
        return {
            "PAGE_TITLE": 21,
            "SECTION": 15,
            "BODY": 13,
            "VALUE": 13,
            "SECONDARY": 11,
            "ROLE_MODEL": 26,
            "ROLE_MODEL_COMPACT": 22,
            "MODEL_TITLE": 16,
            "DESCRIPTION": 13,
            "METADATA": 12,
            "DETAIL_TITLE": 20,
        }
    return {
        "PAGE_TITLE": 18,
        "SECTION": 13,
        "BODY": 12,
        "VALUE": 12,
        "SECONDARY": 10,
        "ROLE_MODEL": 22,
        "ROLE_MODEL_COMPACT": 20,
        "MODEL_TITLE": 15,
        "DESCRIPTION": 12,
        "METADATA": 11,
        "DETAIL_TITLE": 18,
    }


def application_font():
    """随包 Medium 作为正文默认；重点通过独立 Heavy 字面覆盖（emphasis_qss / heavy_font）。"""
    from PySide6.QtGui import QFont

    font = QFont(UI_FONT_FAMILIES[0], 9)
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setWeight(QFont.Weight.Medium)
    return font


# --------------------------------------------------------------- emphasis
# 2026-11-13 重点改用真 Heavy（用户：“很多地方的重点都缺失了，尽量别用默认字体”）。
# Windows 上 Medium 字族请求 600 起就画成合成粗体，和 700/800 一样细；Heavy 字族
# 不论请求多少字重都画成随包 Heavy。所以分界是 600：
#   QSS：规则里 font-weight ≥ 600 → 同一规则写 font-family: TITLE_FONT_STACK；
#        font-weight < 600 → 正文栈（避免宽泛的 Heavy 规则把具体的正文规则带成 Heavy）。
#        样式表生成出口统一过 emphasis_qss()，不必逐条手写；已写其它字族（等宽、
#        字幕字体）的规则不动。
#   自绘：heavy_font(font) / weighted_font(font, weight)。
EMPHASIS_WEIGHT = SEMIBOLD

_RULE = re.compile(r"([^{}]*)\{([^{}]*)\}")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_WEIGHT = re.compile(r"(?<![\w-])font-weight\s*:\s*([0-9]+|bold|bolder|normal|lighter)\b", re.I)
_FAMILY = re.compile(r"(?<![\w-])font-family\s*:\s*([^;{}]*)", re.I)
_BODY_FAMILIES = {name.casefold() for name in UI_FONT_FAMILIES[:2]} | {"source han sans sc", "思源黑体"}
_WEIGHT_WORDS = {"bold": 700, "bolder": 700, "normal": 400, "lighter": 400}
_EMPHASIS_CACHE: dict[str, str] = {}


def _rule_weight(body: str) -> int | None:
    found = _WEIGHT.findall(_COMMENT.sub("", body))
    if not found:
        return None
    value = found[-1].casefold()
    return _WEIGHT_WORDS.get(value) or int(value)


def _declarations(body: str) -> str:
    weight = _rule_weight(body)
    if weight is None:
        return body
    family = _FAMILY.search(body)
    first = family.group(1).split(",")[0].strip().strip("'\"").casefold() if family else ""
    # CoreText groups Medium and Heavy under one family. At 600 its nearest
    # real face is Medium (500); request the bundled Heavy's actual 900 weight.
    ui_face = not family or first in _BODY_FAMILIES or first in {n.casefold() for n in TITLE_FONT_FAMILIES}
    if sys.platform == "darwin" and weight >= EMPHASIS_WEIGHT and ui_face:
        body = _WEIGHT.sub(lambda m: m.group(0).replace(m.group(1), "900"), body)
        family = _FAMILY.search(body)
    stack = TITLE_FONT_STACK if weight >= EMPHASIS_WEIGHT else UI_FONT_STACK
    if family is None:
        end = len(body.rstrip())
        joiner = "" if body[:end].rstrip().endswith(";") or not body[:end].strip() else ";"
        return f"{body[:end]}{joiner} font-family: {stack};{body[end:]}"
    first = family.group(1).split(",")[0].strip().strip("'\"").casefold()
    if weight >= EMPHASIS_WEIGHT and first in _BODY_FAMILIES:
        return body[:family.start(1)] + stack + body[family.end(1):]
    return body


# Qt applies a font only when it polishes a widget, so font changes in a
# widget-level ``:checked`` rule never show (the 2026-10 "selected item is
# bold" rules were all silently Medium). emphasis_qss mirrors such rules as
# ``[checked="true"]`` and records the target here; theme_manager re-polishes
# those buttons when they toggle. Sub-controls (``::tab:selected``,
# ``::item:selected``) are drawn per state and need nothing.
CHECKED_EMPHASIS: set[str] = set()
_TARGET = re.compile(r"([A-Za-z_][\w]*)?(?:#([\w-]+))?[^\s>+~#]*:checked\b")


def _checked_mirror(selector: str) -> str:
    parts = []
    for part in selector.split(","):
        if ":checked" not in part or "::" in part:
            continue
        match = _TARGET.search(part.strip().split()[-1]) if part.strip() else None
        if match:
            CHECKED_EMPHASIS.add(match.group(2) or match.group(1) or "")
        parts.append(part.strip().replace(":checked", '[checked="true"]'))
    return ", ".join(parts)


def _emphasis_rules(sheet: str) -> str:
    def rule(match):
        selector, body = match.group(1), _declarations(match.group(2))
        text = selector + "{" + body + "}"
        weight = _rule_weight(body)
        if weight is not None and weight >= EMPHASIS_WEIGHT and ":checked" in selector:
            mirrored = _checked_mirror(selector)
            mirror = f"\n{mirrored} {{{body}}}" if mirrored else ""
            if mirror and not sheet.startswith(mirror, match.end()):
                text += mirror
        return text
    return _RULE.sub(rule, sheet)


def wants_checked_emphasis(widget) -> bool:
    """A checkable button some sheet gives a heavier face when checked."""
    if not CHECKED_EMPHASIS:
        return False
    if widget.objectName() in CHECKED_EMPHASIS:
        return True
    meta = widget.metaObject()
    while meta is not None:
        if meta.className() in CHECKED_EMPHASIS:
            return True
        meta = meta.superClass()
    return False


def emphasis_qss(sheet: str) -> str:
    """Give every QSS rule that sets a weight the matching bundled face.

    Idempotent: a rule that already names a family is only touched when it
    asks for emphasis on the body face. Works on full sheets and on bare
    declaration lists (``widget.setStyleSheet("font-weight: 700")``).
    """
    if not sheet or "font-weight" not in sheet:
        return sheet
    cached = _EMPHASIS_CACHE.get(sheet)
    if cached is not None:
        return cached
    result = _emphasis_rules(sheet) if "{" in sheet else _declarations(sheet)
    if len(_EMPHASIS_CACHE) > 256:
        _EMPHASIS_CACHE.clear()
    _EMPHASIS_CACHE[sheet] = result
    _EMPHASIS_CACHE[result] = result
    return result


def emphasized(build):
    """Decorator for stylesheet builders: their output goes through emphasis_qss."""
    @functools.wraps(build)
    def wrapper(*args, **kwargs):
        return emphasis_qss(build(*args, **kwargs))
    return wrapper


def heavy_font(font):
    """The bundled 思源黑体 Heavy face for painted emphasis (in place; returns ``font``)."""
    from PySide6.QtGui import QFont
    font.setFamilies(list(TITLE_FONT_FAMILIES))
    font.setWeight(QFont.Weight.ExtraBold)
    return font


def _weight_value(weight) -> int:
    return int(getattr(weight, "value", weight))


# Families a painted font may carry when it means "the interface face": the
# bundled faces and the system UI fonts older code named directly.
_PAINT_BODY = ({name.casefold() for name in UI_FONT_FAMILIES[:6]}
               | {name.casefold() for name in TITLE_FONT_FAMILIES})


def weighted_font(font, weight):
    """Set ``weight`` with the face that goes with it: Heavy from 600, else Medium.

    Only interface fonts change face; a font on another family (mono time
    codes, caption fonts, the mascot's hand-lettered face) just takes the
    weight. In place; returns ``font``.
    """
    from PySide6.QtGui import QFont
    value = _weight_value(weight)
    families = [name for name in (font.families() or [font.family()]) if name]
    first = families[0].casefold() if families else ""
    qt_weight = weight if isinstance(weight, QFont.Weight) else QFont.Weight(value)
    if first and first not in _PAINT_BODY:
        font.setWeight(qt_weight)
        return font
    if value >= EMPHASIS_WEIGHT:
        return heavy_font(font)
    if not first or first in {name.casefold() for name in TITLE_FONT_FAMILIES[:5]}:
        font.setFamilies(list(UI_FONT_FAMILIES))
    font.setWeight(qt_weight)
    return font
