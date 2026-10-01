"""统一 UI 字体层级。

正文使用随包思源黑体 Medium，重点使用 Heavy。显式指定两个字面，
避免只有 Heavy 的机器把所有正文替换为 Heavy，或回退到过细的系统字体。
"""

from __future__ import annotations

from .font_system import SOURCE_HAN_FAMILY_ALIASES

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
)
MONO_FONT_STACK = ", ".join(f'"{name}"' for name in MONO_FONT_FAMILIES) + ", monospace"

TITLE_FONT_FAMILIES = SOURCE_HAN_FAMILY_ALIASES + UI_FONT_FAMILIES
TITLE_FONT_STACK = ", ".join(f'"{name}"' for name in TITLE_FONT_FAMILIES) + ", sans-serif"

# 数值在此定义，design.tokens.WEIGHT_SCALE 为 QSS 提供同源语义映射。
# Heavy 只用于主视觉；区块标题 semibold、正文 regular。
REGULAR = 400
MEDIUM = 500
SEMIBOLD = 600
BOLD = 700
HEAVY = 800

# 字号语义（px）：
#   PAGE_TITLE  页面大标题 21px Heavy
#   SECTION     分区标题   14px semibold
#   BODY        正文       13px regular
#   VALUE       重要数值   13px semibold
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
    """随包 Medium 作为正文默认；标题通过独立 Heavy 字面覆盖。"""
    from PySide6.QtGui import QFont

    font = QFont(UI_FONT_FAMILIES[0], 9)
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setWeight(QFont.Weight.Medium)
    return font
