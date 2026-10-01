"""Web visual themes: AI-authored HTML+CSS subtitle skins for Remotion.

A web theme is a *declarative* document — structure (whitelisted HTML),
styling (CSS) and time-scrubbed CSS animations.  It carries no executable
code: the fixed runtime in ``renderer/src/components/WebThemeSubtitle.tsx``
substitutes the cue placeholders, injects the project's text-appearance
tokens as CSS variables and drives every CSS animation through the Web
Animations ``currentTime`` so renders are deterministic per frame.

Contract (v1)
-------------
Placeholders inside ``cue_html``:
  ``{{text}}``    escaped cue text (newlines become <br>)
  ``{{words}}``   per-character ``<span class="wt-w">…</span>`` for staggered
                   reveals (CJK-friendly)
  ``{{speaker}}`` escaped speaker label (empty string when absent)

Required CSS variables consumed by the theme (injected by the runtime):
  ``--wt-font/-size/-color/-weight/-slant``        project text appearance
  ``--wt-stroke/-stroke-w/-stroke2/-stroke2-w``    outline layers
  ``--wt-w/--wt-h/--wt-u``                         stage size and scaled unit
  ``--wt-dur``                                     cue duration in seconds
  ``--wt-t``                                       cue-relative time in seconds
  ``--wt-at``                                      absolute stage time in seconds

Animation scrubbing: the runtime pauses every animation inside the stage and
sets ``animation.currentTime`` each frame (stage-scoped animations advance
with absolute time, cue-scoped with cue-relative time), which makes plain CSS
keyframes — including infinite loops and negative delays — deterministic for
both still previews and ProRes export.
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping


WEB_THEME_SCHEMA = "2byte.web-visual-theme"
WEB_THEME_VERSION = 1

_MAX_HTML_CHARS = 16384  # Unicode code points; independent 400-node/resource gates remain.
_MAX_CSS_CHARS = 32768
_MAX_HTML_NODES = 400
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(text|words|speaker|translation)\s*\}\}")

# Structural tags only; styling lives in the CSS sections.  SVG gives the AI
# gradients, shapes and filters without scripting or external references.
_ALLOWED_TAGS: frozenset[str] = frozenset({
    "div", "span", "p", "br", "i", "b", "em", "strong",
    "svg", "g", "defs", "mask", "clipPath", "pattern", "linearGradient",
    "radialGradient", "stop", "filter", "feGaussianBlur", "feColorMatrix",
    "feOffset", "feBlend", "feTurbulence", "feDisplacementMap", "feFlood",
    "feComposite", "feMerge", "feMergeNode", "path", "circle", "rect", "ellipse", "line", "polyline",
    "polygon", "text",
})
_VOID_TAGS: frozenset[str] = frozenset({"br", "stop", "circle", "rect", "ellipse", "line", "path", "polygon", "polyline"})

_ALLOWED_ATTRS: frozenset[str] = frozenset({
    "class", "id",
    "aria-hidden", "data-semantic-text", "data-block", "data-emphasis",
    # SVG geometry / paint.  Values are checked for forbidden substrings.
    "d", "cx", "cy", "r", "rx", "ry", "x", "y", "width", "height", "viewBox",
    "points", "transform", "fill", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "opacity",
    "fill-opacity", "stroke-opacity", "offset", "stop-color", "stop-opacity",
    "x1", "y1", "x2", "y2", "gradientUnits", "patternUnits", "patternTransform",
    "preserveAspectRatio", "mask", "clip-path", "filter", "font-size",
    "font-family", "text-anchor", "font-weight", "letter-spacing",
    "stdDeviation", "flood-color", "flood-opacity", "in", "in2", "result",
    "values", "type", "mode", "dx", "dy", "baseFrequency", "numOctaves", "seed",
    "scale", "xChannelSelector", "yChannelSelector", "operator",
})
_FORBIDDEN_ATTR_VALUE_TOKENS: tuple[str, ...] = (
    "javascript:", "url(http", "url(https", "url('//", 'url("//', "<", ">",
)
_FORBIDDEN_CSS_TOKENS: tuple[str, ...] = (
    "@import", "expression(", "behavior:", "-moz-binding", "javascript:",
    "url(http", "url(https", "url('//", 'url("//', "</",
)
_ALLOWED_TAG_NAMES = _ALLOWED_TAGS | frozenset(name.casefold() for name in _ALLOWED_TAGS)
_CANONICAL_ATTR_NAMES = {name.casefold(): name for name in _ALLOWED_ATTRS}


class WebThemeValidationError(ValueError):
    """Raised when a theme document violates the v1 contract."""


def inline_svg_attribute_problem(tag, name, value):
    if str(name).casefold() == 'seed':
        if str(tag).casefold() != 'feturbulence' or not re.fullmatch(r'\d{1,4}', str(value or '')) or int(value) > 4096:
            return 'feTurbulence seed 必须为 0–4096 整数'
    return ''


def sanitize_html(source: str, *, section: str) -> str:
    """Rebuild HTML with a tag/attribute whitelist; comments are dropped."""
    text = str(source or "").strip()
    if not text:
        if section == "stage": return ""
        raise WebThemeValidationError(f"{section} HTML 不能为空")
    if len(text) > _MAX_HTML_CHARS:
        raise WebThemeValidationError(
            f"{section} HTML 超过 {_MAX_HTML_CHARS} 字符上限"
        )
    return _sanitize_html_text(text, section)


@lru_cache(maxsize=128)
def _sanitize_html_text(text: str, section: str) -> str:
    # Playback routes validate the same immutable sections on every tick.
    # Cache only bounded strings, never mutable theme DTOs; edited bytes must
    # pass the parser again. Invalid input/raised errors are never cached.

    class _Rebuilder(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.depth = 0
            self.nodes = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._emit(tag, attrs, self_closing=False)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._emit(tag, attrs, self_closing=True)

        def _emit(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> None:
            if tag not in _ALLOWED_TAG_NAMES:
                raise WebThemeValidationError(
                    f"{section} HTML 含不允许的标签 <{tag}>（白名单：结构与 SVG）"
                )
            self.nodes += 1
            if self.nodes > _MAX_HTML_NODES:
                raise WebThemeValidationError(f"{section} HTML 节点数超过 {_MAX_HTML_NODES}")
            keep: list[str] = []
            for name, value in attrs:
                # HTMLParser lowercases SVG attributes; restore their canonical
                # spelling so viewBox/gradientUnits survive safe import.
                name = _CANONICAL_ATTR_NAMES.get(name.casefold(), name)
                if name not in _ALLOWED_ATTRS:
                    continue
                cleaned = str(value if value is not None else "").strip()
                problem = inline_svg_attribute_problem(tag, name, cleaned)
                if problem:
                    raise WebThemeValidationError(problem)
                if name=='data-block':
                    from .theme_texture_resource import valid_data_block
                    if not valid_data_block(cleaned):raise WebThemeValidationError('data-block must be a bounded declarative identifier')
                if name == 'id' and (not re.fullmatch(r'[A-Za-z_][\w:.-]*', cleaned)
                                     or cleaned in {'wt-cue', 'wt-frame', 'wt-theme-data'}):
                    raise WebThemeValidationError(f'{section} HTML 含无效或保留的 id')
                from .theme_texture_resource import checked_css_urls
                try:
                    lowered = checked_css_urls(cleaned, allow_texture=False).casefold()
                except ValueError as exc:
                    raise WebThemeValidationError(f'{section} HTML 属性 {name}: {exc}') from exc
                if any(token in lowered for token in _FORBIDDEN_ATTR_VALUE_TOKENS):
                    raise WebThemeValidationError(
                        f"{section} HTML 属性 {name} 含禁止的值：{cleaned[:80]}"
                    )
                keep.append(name + '="' + cleaned.replace("&", "&amp;").replace('"', "&quot;") + '"')
            attributes = (" " + " ".join(keep)) if keep else ""
            if tag in _VOID_TAGS or self_closing:
                self.parts.append(f"<{tag}{attributes}/>")
            else:
                self.depth += 1
                self.parts.append(f"<{tag}{attributes}>")

        def handle_endtag(self, tag: str) -> None:
            # html.parser 会把标签名小写化：白名单里的 SVG 驼峰标签
            # （linearGradient/clipPath…）必须同样 casefold 匹配，否则闭合
            # 标签被跳过 → depth 泄漏 → 误报"未闭合标签"（二十七轮实测）。
            if tag in _VOID_TAGS or tag not in _ALLOWED_TAG_NAMES:
                return
            self.depth = max(0, self.depth - 1)
            self.parts.append(f"</{tag}>")

        def handle_data(self, data: str) -> None:
            self.parts.append(
                str(data)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

    rebuilder = _Rebuilder()
    try:
        rebuilder.feed(text)
        rebuilder.close()
    except WebThemeValidationError:
        raise
    except Exception as exc:  # malformed markup
        raise WebThemeValidationError(f"{section} HTML 解析失败：{exc}") from exc
    if rebuilder.depth != 0:
        raise WebThemeValidationError(f"{section} HTML 存在未闭合标签")
    return "".join(rebuilder.parts)


def sanitize_css(source: str, *, section: str) -> str:
    """Reject CSS with external references or scripting hooks."""
    text = str(source or "").strip()
    if not text:
        if section == "stage": return ""
        raise WebThemeValidationError(f"{section} CSS 不能为空")
    if len(text) > _MAX_CSS_CHARS:
        raise WebThemeValidationError(f"{section} CSS 超过 {_MAX_CSS_CHARS} 字符上限")
    return _sanitize_css_text(text, section)


@lru_cache(maxsize=128)
def _sanitize_css_text(text: str, section: str) -> str:
    comments = re.compile(r"/\*.*?\*/", re.DOTALL)
    cleaned = comments.sub(" ", text)
    from .theme_texture_resource import checked_css_urls
    try:lowered = checked_css_urls(cleaned).casefold()
    except ValueError as exc:raise WebThemeValidationError(f'{section} CSS resource: {exc}') from exc
    for token in _FORBIDDEN_CSS_TOKENS:
        if token in lowered:
            raise WebThemeValidationError(
                f"{section} CSS 含禁止结构 {token!r}（禁止外链/脚本钩子）"
            )
    return text


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# 十九轮：AI 常把 {{words}} 再包一层 .wt-w——运行时替换后变成嵌套双重渲染
# （外层+内层都套渐变/描边/逐字动画），文字糊成一团。直接拒收。
_WORDS_WRAPPER_RE = re.compile(
    r"<[a-zA-Z]+[^>]*class\s*=\s*[\"'][^\"']*\bwt-w\b[^\"']*[\"'][^>]*>\s*\{\{\s*words\s*\}\}",
)


def _reject_words_wrapper(cue_html: str) -> None:
    if _WORDS_WRAPPER_RE.search(cue_html or ""):
        raise WebThemeValidationError(
            "{{words}} 必须直接放在行容器里，不能再包进 .wt-w span（会嵌套双重渲染糊字）"
        )


# 二十一轮：CONCEPT=承诺清单的机械化——概念里每个 `.classname` 标注都必须
# 真的出现在 stage/cue HTML 里（"只写不做=未完成"从口号变成校验）。
_CONCEPT_CLASS_RE = re.compile(r"\.([a-zA-Z][a-zA-Z0-9_-]{1,40})")

# 二十一轮：舞台层不得有不透明全屏背景——视频可见性优先。只查全幅表面
# （.wt-stage/html/body/:root）的 background 声明，启发式覆盖最常见的翻车形态
# （模型给舞台刷白灰渐变=整个视频被盖住）。
_STAGE_SURFACE_RE = re.compile(
    r"(?:^|\})\s*(\.wt-stage|html|body|:root)\s*\{[^}]*\}",
    re.DOTALL,
)
_OPAQUE_BG_RE = re.compile(
    r"background(?:-color)?\s*:\s*[^;]*?(?:"
    r"#[0-9a-fA-F]{6}(?![0-9a-fA-F]{2})"       # #RRGGBB（无 alpha=不透明）
    r"|#[0-9a-fA-F]{8}"                          # #RRGGBBAA 后面再判 alpha
    r"|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)"    # rgb() 无 alpha
    r")",
)


def _reject_opaque_stage_surface(stage_css: str) -> None:
    for block in _STAGE_SURFACE_RE.finditer(stage_css or ""):
        body = block.group(0)
        for hit in _OPAQUE_BG_RE.finditer(body):
            value = hit.group(0)
            hex8 = re.search(r"#[0-9a-fA-F]{8}", value)
            if hex8 is not None:
                alpha = int(hex8.group(0)[7:9], 16) / 255.0
                if alpha < 0.35:
                    continue
            raise WebThemeValidationError(
                "舞台层（.wt-stage/html/body）不得有不透明全屏背景——视频画面必须可见；"
                f"纹理/氛围请用低透明度叠加（当前：{value[:60]}）"
            )


_GENERIC_PROMISE_CLASSES = {
    "wt-w", "wt-cue", "wt-stage", "line", "tag", "plate", "card", "box",
    "text", "face", "wrap",
}
_PLATE_HINTS = ("plate", "card", "box", "bar", "board", "case", "cabinet", "hud")
_GLASS_WORDS = ("玻璃", "glass", "透明框", "半透明框")


def _text_container_classes(document: "WebThemeDocument") -> set[str]:
    """Find actual subtitle ancestors, so telemetry bars are not cue plates."""
    from html.parser import HTMLParser
    class Containers(HTMLParser):
        def __init__(self):
            super().__init__();self.stack=[];self.classes=set()
        def handle_starttag(self,tag,attrs):
            if tag not in {'br','hr','img','input','meta','link','wbr'}:
                self.stack.append((tag,dict(attrs).get('class','').split()))
        def handle_startendtag(self,tag,attrs):pass
        def handle_endtag(self,tag):
            for index in range(len(self.stack)-1,-1,-1):
                if self.stack[index][0]==tag:
                    del self.stack[index:];break
        def handle_data(self,data):
            if re.search(r'\{\{\s*(?:words|text)\s*\}\}',data):
                self.classes.update(c for _,classes in self.stack for c in classes)
    parser=Containers();parser.feed(document.cue_html)
    return parser.classes | {'wt-cue'}


def _reject_thin_scene(document: "WebThemeDocument") -> None:
    """二十二轮：承诺核验管"写了的"，管不了"写太少"——最低场景丰富度。

    ≥4 个具体物件类（排除 wt-w/tag/line/plate 等通用名），且其中 ≥2 个
    的 CSS 规则带 infinite（持续动效：卷轴滚动/灯牌闪烁/机柜灯…）。
    """
    concept = str(document.concept or "")
    promised = [
        name for name in dict.fromkeys(_CONCEPT_CLASS_RE.findall(concept))
        if name.lower() not in _GENERIC_PROMISE_CLASSES
    ]
    if len(promised) < 4:
        raise WebThemeValidationError(
            f"场景物件太少（{len(promised)} 个具体物件，至少 4 个）：CONCEPT 需要"
            "至少承诺 4 个场景物件类（如 卷轴 .reel / 机柜 .cabinet / 灯牌 .marquee /"
            " 帽子 .hat），每个都有 DOM 与动画"
        )
    css_all = document.stage_css + "\n" + document.cue_css
    looping = 0
    for name in promised:
        # 该类的规则块里是否有 infinite 动画（含选择器本体或后代）
        for block in re.findall(r"[^{}]*\." + re.escape(name) + r"[^{}]*\{[^}]*\}", css_all):
            if "infinite" in block:
                looping += 1
                break
    if looping < 2:
        raise WebThemeValidationError(
            f"持续动效太少（{looping}/≥2 个物件带 infinite 循环动画）：卷轴滚动/"
            "灯牌闪烁/机柜灯等物件应有各自的 infinite 动画"
        )


def _reject_washed_out_plate(document: "WebThemeDocument", instruction: str) -> None:
    """二十二轮：字幕框/状态条要结实——透明规则只针对舞台全屏层。"""
    context = f"{instruction} {document.concept}"
    if any(word in context for word in _GLASS_WORDS):
        return  # 用户点名玻璃/透明框效果
    containers=_text_container_classes(document)
    for block in re.findall(r"[^{}]*\{[^}]*\}", document.cue_css):
        selector = block.split("{", 1)[0]
        if not any(hint in selector.lower() for hint in _PLATE_HINTS):
            continue
        if not containers.intersection(re.findall(r'\.([\w-]+)',selector)):
            continue
        for hit in re.finditer(r"background(?:-color)?\s*:\s*rgba?\(([^)]*)\)", block):
            parts = [part.strip() for part in hit.group(1).split(",")]
            if len(parts) == 4:
                try:
                    alpha = float(parts[3])
                except ValueError:
                    continue
                if alpha < 0.55:
                    raise WebThemeValidationError(
                        "字幕框/状态条底板太透（rgba alpha "
                        f"{alpha:.2f} < 0.55）——透明规则只针对舞台全屏层；"
                        "字幕框应当结实可读（除非用户点名玻璃效果）"
                    )


def _reject_looping_text_layers(document: "WebThemeDocument") -> None:
    """二十四轮：时间轴铁律——字幕文字层不得 infinite，字幕框氛围循环要慢。

    用户实测"字幕 3 秒而动画 1 秒=连续重复 3 次"的机制面根因之一是模型把
    入场/文字动画写成 infinite 短周期循环。规则：
    - ``.wt-text`` / ``.wt-w`` 选择器的规则块禁止任何 infinite；
    - ``.wt-cue`` 直挂 infinite 仅允许慢周期（≥2.5s，呼吸/漂浮类氛围）。
    """
    for block in re.findall(r"[^{}]*\{[^}]*\}", document.cue_css or ""):
        if "infinite" not in block:
            continue
        selector = block.split("{", 1)[0]
        is_text = ".wt-text" in selector or ".wt-w" in selector
        is_cue = ".wt-cue" in selector and not is_text
        if not (is_text or is_cue):
            continue
        if is_text:
            raise WebThemeValidationError(
                "字幕文字层（.wt-text/.wt-w）动画不得 infinite——入场/出场/逐字都"
                "是一次性动画；持续氛围放在场景物件（灯珠/筹码/帽子…）上"
            )
        for decl in re.finditer(r"animation\s*:[^;]*infinite[^;]*", block):
            duration = re.search(r"([\d.]+)s", decl.group(0))
            if duration is None or float(duration.group(1)) < 2.5:
                raise WebThemeValidationError(
                    "字幕框（.wt-cue）直挂的 infinite 动画必须是慢周期（≥2.5s，"
                    "呼吸/漂浮类）——短周期循环在字幕时长内反复重播（用户实测"
                    "'3 秒字幕重复 3 次'）；入场/出场用一次性动画"
                )


def _require_dur_anchored_exit(document: "WebThemeDocument") -> None:
    """二十四轮：出场必须锚定字幕时长——cue_css 引用 var(--wt-dur)。"""
    if "var(--wt-dur)" not in (document.cue_css or ""):
        raise WebThemeValidationError(
            "CUE_CSS 必须用 var(--wt-dur) 锚定出场（animation-delay: "
            "calc(var(--wt-dur) - Ns)）——否则出场时机与字幕时长脱节"
        )


def _reject_flat_plate(document: "WebThemeDocument", instruction: str) -> None:
    """二十七轮：字幕底板禁止平涂——必须有渐变/纹理材质。

    用户实测（死亡搁浅主题）："很简单的字幕框和描边颜色，单调且难看"——
    平涂 rgba 底板+描边就是全部观感，装置再多家底也是"一个框"。底板
    （plate 类选择器）的 background 声明里必须出现 gradient。玻璃/透明框
    点名豁免（与 二十二轮 washed-out 门同款豁免词）。
    """
    context = f"{instruction} {document.concept}"
    if any(word in context for word in _GLASS_WORDS):
        return
    containers=_text_container_classes(document)
    for block in re.findall(r"[^{}]*\{[^}]*\}", document.cue_css or ""):
        selector = block.split("{", 1)[0]
        if not any(hint in selector.lower() for hint in _PLATE_HINTS):
            continue
        if not containers.intersection(re.findall(r'\.([\w-]+)',selector)):
            continue
        # 只检查底板本体（简单选择器）：后代/伪元素规则（如 .plate .screw::after
        # 这类小零件）常合法地用平涂色，不该被门拦。先 strip 再判（选择器与
        # 花括号之间的空白不算后代组合器）。
        selector = selector.strip()
        if " " in selector or "::" in selector or ">" in selector:
            continue
        body = block.split("{", 1)[1]
        for hit in re.finditer(r"background(?:-image)?\s*:\s*([^;}]+)", body):
            value = hit.group(1)
            if "gradient" in value:
                break
        else:
            # 该块有 background 声明但无渐变 → 平涂底板。
            if "background" in body:
                raise WebThemeValidationError(
                    "字幕底板（plate 类）背景禁止平涂纯色——必须用渐变"
                    "（linear/radial/conic）或 repeating-* 微纹理叠出材质"
                    "（深-中-亮 ≥3 档明度），否则整个画面只是'一个描边框'"
                    "（用户实测单调难看）。用户点名玻璃效果时才可通透平涂"
                )


def _reject_unbalanced_css(document: "WebThemeDocument") -> None:
    """二十五轮：CSS 括号必须配对——一个未闭合的 ``calc(`` 会把后续声明整段
    吞掉（用户实测：死亡搁浅主题 .wt-w 少一个右括号 → animation 被吞 →
    文字永远 opacity:0 隐形）。剥离注释后按段落计数配对。
    """
    for section, css in (("STAGE_CSS", document.stage_css), ("CUE_CSS", document.cue_css)):
        clean = re.sub(r"/\*.*?\*/", "", str(css or ""), flags=re.S)
        for open_ch, close_ch in (("{", "}"), ("(", ")")):
            depth = 0
            first_line = -1
            for index, ch in enumerate(clean):
                if ch == open_ch:
                    depth += 1
                    if first_line < 0:
                        first_line = clean.count("\n", 0, index) + 1
                elif ch == close_ch:
                    depth -= 1
            if depth != 0:
                raise WebThemeValidationError(
                    f"{section} 的 {open_ch}{close_ch} 括号不配对"
                    f"（差 {depth} 个 {close_ch}，首个 {open_ch} 约在第 {first_line} 行）"
                    "——未闭合的括号会让浏览器把后续声明整段丢弃（如 animation 被吞"
                    "=元素永久隐形）。请逐个检查 calc()/translateY()/clip-path() 的闭合"
                )


def validate_generated_theme(
    document: "WebThemeDocument", *, instruction: str = "", design_version: int = 1,
) -> "WebThemeDocument":
    """生成期硬门（二十一轮+二十二轮+二十四轮+二十五轮）。

    只在 AI 生成/修改主题后调用——存量工程与内置金样例不做追溯（否则
    旧主题连重套都会被拒，破坏用户数据）。
    """
    _reject_opaque_stage_surface(document.stage_css)
    _reject_unfulfilled_promises(document)
    if design_version < 2:
        _reject_thin_scene(document)
        _reject_washed_out_plate(document, instruction)
    _reject_looping_text_layers(document)
    if not document.motion_spec:_require_dur_anchored_exit(document)
    if design_version < 2:
        _reject_flat_plate(document, instruction)
    _reject_unbalanced_css(document)
    return document


def validate_preserved_theme_revision(document: "WebThemeDocument", original: Mapping[str, Any]) -> "WebThemeDocument":
    """A surface revision of existing markup must not acquire legacy ideation gates.

    The full document parser still validates resources, markup and MotionSpec.
    Actual material/geometry/readability checks happen in the production render.
    """
    value=document.to_dict()
    for key in ('cueHtml','stageHtml','motionSpec'):
        if value.get(key)!=original.get(key):
            raise WebThemeValidationError('材质修订不得改写原结构或动作：'+key)
    return validate_existing_authored_revision(document)


def validate_existing_authored_revision(document: "WebThemeDocument") -> "WebThemeDocument":
    """Retain safety without imposing legacy ideation on an existing GSAP work.

    Directed repair may change HTML and motion. Existing concepts need not
    acquire old four-object / infinite-CSS-animation promises, which conflict
    with the finite single-clock motion contract. Explicit promises still apply.
    """
    _reject_opaque_stage_surface(document.stage_css)
    _reject_looping_text_layers(document)
    _reject_unbalanced_css(document)
    if not document.motion_spec:_require_dur_anchored_exit(document)
    if _CONCEPT_CLASS_RE.findall(str(document.concept or '')):
        _reject_unfulfilled_promises(document)
    return document


def _reject_unfulfilled_promises(document: "WebThemeDocument") -> None:
    concept = str(document.concept or "")
    promised = _CONCEPT_CLASS_RE.findall(concept)
    if not promised:
        raise WebThemeValidationError(
            "CONCEPT 必须给每个点名物件标注实现它的类名（例：老虎机三格卷轴 .reel；"
            "红黑筹码堆 .chips）——类名会与 HTML 对照核验"
        )
    html_all = f"{document.stage_html} {document.cue_html}"
    css_all = f"{document.stage_css} {document.cue_css}"
    missing = [
        name for name in dict.fromkeys(promised)
        if name not in html_all and name not in css_all
    ]
    if missing:
        raise WebThemeValidationError(
            "CONCEPT 点名的物件未实现（承诺清单核验失败）：" + ", ".join(f".{n}" for n in missing[:6])
        )


def _clean_palette(payload: Mapping[str, Any] | None) -> dict[str, str]:
    data = dict(payload or {})
    palette: dict[str, str] = {}
    for key in ("primary", "secondary", "background", "accent", "text"):
        raw = str(data.get(key) or "").strip()
        if raw and not _HEX_COLOR_RE.match(raw):
            raise WebThemeValidationError(
                f"palette.{key} 必须是 #RRGGBB 颜色，收到 {raw[:20]!r}"
            )
        palette[key] = raw
    if not palette.get("primary") or not palette.get("text"):
        raise WebThemeValidationError("palette 至少需要 primary 与 text 两个 #RRGGBB 颜色")
    return palette


# Theme-owned text-appearance design intent (2026-09-02 十八轮)：主题自带
# 字体栈/文字颜色/描边，优先于工程快照（快照只补缺）。全部键可缺省。
_DEFAULT_APPEARANCE: dict[str, Any] = {
    "fontFamily": '"Microsoft YaHei UI", "PingFang SC", sans-serif',
    "fontSize": 58,
    "bold": True,
    "italic": False,
    "color": "#FFFFFF",
    "strokeColor": "#000000",
    "strokeWidth": 3.0,
    "stroke2Color": "#000000",
    "stroke2Width": 0.0,
    "letterSpacing": 0.0,
}
_APPEARANCE_FONT_MAX = 160


def _clean_appearance(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the optional theme-owned appearance block (all keys optional)."""
    data = payload if isinstance(payload, Mapping) else {}
    appearance: dict[str, Any] = {}
    family = str(data.get("fontFamily") or "").strip()
    if family:
        if len(family) > _APPEARANCE_FONT_MAX or any(
            token in family.casefold()
            for token in ("javascript:", "url(", "var(", "@import", "<", ">")
        ):
            raise WebThemeValidationError("appearance.fontFamily 含非法字体栈")
        appearance["fontFamily"] = family
    for key, low, high in (
        ("fontSize", 16.0, 200.0),
        ("fontWeight", 1.0, 1000.0),
        ("strokeWidth", 0.0, 30.0),
        ("stroke2Width", 0.0, 30.0),
        ("letterSpacing", -8.0, 40.0),
    ):
        if key not in data:
            continue
        try:
            value = float(data.get(key))
        except (TypeError, ValueError):
            raise WebThemeValidationError(f"appearance.{key} 必须是数字")
        appearance[key] = min(high, max(low, value))
    for key in ("bold", "italic"):
        if key in data:
            appearance[key] = bool(data.get(key))
    for key in ("color", "strokeColor", "stroke2Color"):
        raw = str(data.get(key) or "").strip()
        if not raw:
            if key in data:
                appearance[key] = ""
            continue
        if not _HEX_COLOR_RE.match(raw):
            raise WebThemeValidationError(
                f"appearance.{key} 必须是 #RRGGBB 颜色，收到 {raw[:20]!r}"
            )
        appearance[key] = raw
    return appearance


def effective_appearance(
    theme: Mapping[str, Any] | None,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge appearance tokens theme-first: theme design wins, fallback gaps.

    ``fallback`` is the project text-appearance snapshot (or preview
    defaults). Keys the theme does not pin keep the fallback value, so
    pre-appearance themes render exactly as before.
    """
    merged: dict[str, Any] = dict(_DEFAULT_APPEARANCE)
    if fallback is not None:
        for key in (*_DEFAULT_APPEARANCE, 'fontWeight'):
            if key in fallback and fallback.get(key) not in (None, ""):
                merged[key] = fallback.get(key)
    own = theme.get("appearance") if isinstance(theme, Mapping) else None
    own = own if isinstance(own, Mapping) else {}
    for key in (*_DEFAULT_APPEARANCE, 'fontWeight'):
        if key in own and own.get(key) not in (None, ""):
            merged[key] = own.get(key)
    if 'fontWeight' not in own and ('fontFamily' in own or 'bold' in own):
        merged.pop('fontWeight', None)
    if 'fontWeight' not in merged:
        # A full face alias (e.g. Heavy) carries weight even with bold=False.
        family = str(merged['fontFamily']).strip().strip('\"\'')
        if ',' not in family:
            from .font_metadata import resolve_local_face
            face, _warning = resolve_local_face(family, bold=bool(merged['bold']))
            if face is not None and not _warning:
                merged['fontWeight'] = face.weight
    return merged


@dataclass
class WebThemeDocument:
    """Validated, sanitized web visual theme."""

    name: str
    concept: str = ""
    palette: dict[str, str] = field(default_factory=dict)
    stage_html: str = ""
    stage_css: str = ""
    cue_html: str = ""
    cue_css: str = ""
    notes: str = ""
    appearance: dict[str, Any] = field(default_factory=dict)
    motion_spec: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def validate(self) -> "WebThemeDocument":
        from .theme_metadata import validate_name, validate_id, stable_theme_id
        try:
            self.name = validate_name(self.name)
            if self.id:
                self.id = validate_id(self.id)
        except ValueError as exc:
            raise WebThemeValidationError(str(exc)) from exc
        self.concept = str(self.concept or "").strip()[:600]
        self.notes = str(self.notes or "").strip()[:600]
        self.palette = _clean_palette(self.palette)
        self.appearance = _clean_appearance(self.appearance)
        self.stage_html = sanitize_html(self.stage_html, section="stage")
        self.stage_css = sanitize_css(self.stage_css, section="stage")
        self.cue_html = sanitize_html(self.cue_html, section="cue")
        self.cue_css = sanitize_css(self.cue_css, section="cue")
        if self.motion_spec:
            from .theme_motion import validate_motion_spec
            try:self.motion_spec=validate_motion_spec(self.motion_spec,cue_html=self.cue_html)
            except ValueError as exc:raise WebThemeValidationError(str(exc)) from exc
            if re.search(r'@keyframes|(?:^|[;{])\s*(?:animation(?:-[\w-]+)?|transition(?:-[\w-]+)?)\s*:',self.stage_css+'\n'+self.cue_css,re.I):
                raise WebThemeValidationError('GSAP主题必须使用静态CSS，不能再含CSS animation/transition')
            if self.stage_html.strip():
                raise WebThemeValidationError('GSAP主题的所有图层应放在cueHtml中，统一随cue结束清除')
        if not _PLACEHOLDER_RE.search(self.cue_html):
            raise WebThemeValidationError(
                "cue_html 必须包含 {{text}} 或 {{words}} 占位符"
            )
        _reject_words_wrapper(self.cue_html)
        for token in ("var(--wt-font",):
            # 二十轮：--wt-color 不再强制（theme-first 下主题可自带完整配色；
            # 曾把 Grok 富创意首版拒掉——模型用自带金色渐变+var(--wt-stroke)
            # 完全合法）。字体耦合仍必须：外观调整入口靠它。
            if token not in self.cue_css:
                raise WebThemeValidationError(
                    f"cue_css 必须通过 {token}…) 消费字体 token（颜色 token 可选：主题可自带配色）"
                )
        if not self.id:
            self.id = stable_theme_id(self.to_dict())
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": WEB_THEME_SCHEMA,
            "version": WEB_THEME_VERSION,
            "name": self.name,
            "id": self.id,
            "concept": self.concept,
            "palette": dict(self.palette),
            "stageHtml": self.stage_html,
            "stageCss": self.stage_css,
            "cueHtml": self.cue_html,
            "cueCss": self.cue_css,
            "notes": self.notes,
        }
        if self.appearance:
            payload["appearance"] = dict(self.appearance)
        if self.motion_spec:payload['motionSpec']=self.motion_spec
        if not self.id:
            from .theme_metadata import stable_theme_id
            self.id = stable_theme_id(payload)
            payload['id'] = self.id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WebThemeDocument":
        from .structured_output import object_value
        from .theme_metadata import normalize_theme_input
        if not isinstance(payload, Mapping):
            raise WebThemeValidationError("web theme 根必须是对象")
        try:
            payload = normalize_theme_input(payload)
        except ValueError as exc:
            raise WebThemeValidationError(str(exc)) from exc
        for field in ('palette', 'appearance', 'motionSpec'):
            if field not in payload or payload[field] is None:
                continue
            try:
                payload[field] = object_value(payload[field], 'webTheme.' + field)
            except ValueError as exc:
                raise WebThemeValidationError(str(exc)) from exc
        if str(payload.get("schema") or WEB_THEME_SCHEMA) != WEB_THEME_SCHEMA:
            raise WebThemeValidationError(
                f"web theme schema 不受支持：{payload.get('schema')!r}"
            )
        version = int(payload.get("version") or WEB_THEME_VERSION)
        if version != WEB_THEME_VERSION:
            raise WebThemeValidationError(f"web theme 版本不受支持：{version}")
        if 'motionSpec' in payload:
            from .theme_motion import validate_motion_spec
            try:validate_motion_spec(payload['motionSpec'],cue_html=str(payload.get('cueHtml','')))
            except ValueError as exc:raise WebThemeValidationError(str(exc)) from exc
        return cls(
            name=payload.get("name", ""),
            id=payload.get("id", ""),
            concept=str(payload.get("concept") or ""),
            palette=dict(payload.get("palette") or {}),
            stage_html=str(payload.get("stageHtml") or payload.get("stage_html") or ""),
            stage_css=str(payload.get("stageCss") or payload.get("stage_css") or ""),
            cue_html=str(payload.get("cueHtml") or payload.get("cue_html") or ""),
            cue_css=str(payload.get("cueCss") or payload.get("cue_css") or ""),
            notes=str(payload.get("notes") or ""),
            appearance=dict(payload.get("appearance") or {}),
            motion_spec=dict(payload.get('motionSpec') or {}),
        ).validate()

    def clone(self) -> "WebThemeDocument":
        return WebThemeDocument.from_dict(self.to_dict())

    def native_mirror_style(self) -> dict[str, Any]:
        """Appearance fallback values for mpv ASS / native mirror styles."""
        palette = self.palette
        own = self.appearance or {}
        family = str(own.get("fontFamily") or "")
        # The mirror wants ONE family name (ASS/libass has no stack syntax):
        # take the first entry of the theme's stack.
        if family:
            family = family.split(",")[0].strip().strip('"').strip("'")
        mirror: dict[str, Any] = {
            "primary_color": own.get("color") or palette.get("text") or "#FFFFFF",
            "outline_color": (
                own.get("strokeColor")
                or palette.get("primary") or "#000000"
            ),
            "outline_width": 3,
            "outline2_color": own.get("stroke2Color") or palette.get("accent")
            or palette.get("secondary") or "#000000",
            "outline2_width": 1,
            "back_color": palette.get("background") or "#000000",
        }
        if own.get("strokeWidth") is not None:
            try:
                mirror["outline_width"] = min(
                    8.0, max(0.5, float(own.get("strokeWidth", 3)))
                )
            except (TypeError, ValueError):
                pass
        if family:
            mirror["font_family"] = family
        if own.get("fontSize") is not None:
            try:
                mirror["font_size"] = min(200.0, max(12.0, float(own.get("fontSize"))))
            except (TypeError, ValueError):
                pass
        return mirror


# ---------------------------------------------------------------------------
# Built-in golden themes
# ---------------------------------------------------------------------------

_CLEAN_STAGE_HTML = (
    '<div class="wt-backdrop"></div>'
    '<div class="wt-sheen"></div>'
)

_CLEAN_STAGE_CSS = """
.wt-stage { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.wt-backdrop {
  position: absolute; inset: 0;
  background: linear-gradient(160deg, rgba(10, 14, 22, 0.00) 40%, rgba(10, 14, 22, 0.32) 100%);
}
.wt-sheen {
  position: absolute; left: -20%; bottom: -30%; width: 140%; height: 70%;
  background: radial-gradient(closest-side, rgba(120, 160, 255, 0.10), transparent 70%);
  animation: wt-clean-breathe 5.2s ease-in-out infinite;
}
@keyframes wt-clean-breathe {
  0%, 100% { transform: translateY(0) scale(1); opacity: 0.75; }
  50% { transform: translateY(-2.4% ) scale(1.05); opacity: 1; }
}
"""

_CLEAN_CUE_HTML = (
    '<div class="wt-sub">{{translation}}</div>'
    '<div class="wt-card"><div class="wt-text">{{words}}</div></div>'
)

_CLEAN_CUE_CSS = """
.wt-sub:empty { display: none; }
.wt-sub {
  font-family: var(--wt-font); font-size: calc(var(--wt-size) * 0.6);
  color: var(--wt-stroke); opacity: 0.92; text-align: center;
  margin-bottom: calc(0.5 * var(--wt-u)); letter-spacing: 0.02em;
}
.wt-cue {
  position: absolute; left: 50%; bottom: 8.5%;
  transform: translateX(-50%);
  animation: wt-clean-in .38s cubic-bezier(.2, .9, .3, 1) both,
             wt-clean-out .3s ease-in both;
  animation-delay: 0s, calc(var(--wt-dur) - 0.3s);
}
.wt-card {
  padding: calc(1.1 * var(--wt-u)) calc(2.2 * var(--wt-u));
  background: rgba(12, 16, 24, 0.42);
  border: calc(0.12 * var(--wt-u)) solid rgba(255, 255, 255, 0.14);
  border-radius: calc(0.9 * var(--wt-u));
  backdrop-filter: blur(6px);
}
.wt-text {
  font-family: var(--wt-font);
  font-size: var(--wt-size);
  font-weight: var(--wt-weight);
  font-style: var(--wt-slant);
  color: var(--wt-color);
  letter-spacing: 0.02em;
  text-shadow:
    calc(var(--wt-stroke-w) * 1) 0 0 var(--wt-stroke),
    calc(var(--wt-stroke-w) * -1) 0 0 var(--wt-stroke),
    0 calc(var(--wt-stroke-w) * 1) 0 var(--wt-stroke),
    0 calc(var(--wt-stroke-w) * -1) 0 var(--wt-stroke),
    calc(var(--wt-stroke-w) * 0.7) calc(var(--wt-stroke-w) * 0.7) 0 var(--wt-stroke),
    calc(var(--wt-stroke-w) * -0.7) calc(var(--wt-stroke-w) * 0.7) 0 var(--wt-stroke),
    calc(var(--wt-stroke-w) * 0.7) calc(var(--wt-stroke-w) * -0.7) 0 var(--wt-stroke),
    calc(var(--wt-stroke-w) * -0.7) calc(var(--wt-stroke-w) * -0.7) 0 var(--wt-stroke),
    calc(0.16 * var(--wt-u)) calc(0.22 * var(--wt-u)) calc(0.5 * var(--wt-u)) rgba(0, 0, 0, 0.45);
}
.wt-text .wt-w { display: inline-block; }
.wt-text .wt-w:nth-child(odd) { animation: wt-clean-word .26s cubic-bezier(.2, .9, .3, 1) both; }
.wt-text .wt-w:nth-child(even) { animation: wt-clean-word .26s cubic-bezier(.2, .9, .3, 1) both; animation-delay: 0.035s; }
@keyframes wt-clean-word {
  from { opacity: 0; transform: translateY(18%); }
  to { opacity: 1; transform: none; }
}
@keyframes wt-clean-in {
  from { opacity: 0; transform: translate(-50%, 26%); }
  to { opacity: 1; transform: translate(-50%, 0); }
}
@keyframes wt-clean-out {
  from { opacity: 1; transform: translate(-50%, 0); }
  to { opacity: 0; transform: translate(-50%, -14%); }
}
"""

_CLEAN_THEME = WebThemeDocument(
    name="Clean Glass",
    concept="低干扰玻璃卡片：可读性优先，轻呼吸光晕与逐字入场。",
    palette={
        "primary": "#1B2A41",
        "secondary": "#3E5C76",
        "background": "#0C1018",
        "accent": "#9FB4C7",
        "text": "#FFFFFF",
    },
    stage_html=_CLEAN_STAGE_HTML,
    stage_css=_CLEAN_STAGE_CSS,
    cue_html=_CLEAN_CUE_HTML,
    cue_css=_CLEAN_CUE_CSS,
    notes="兜底主题：任何网页主题生成失败时使用。",
)


def _balatro_theme() -> WebThemeDocument:
    from .balatro_theme import balatro_theme_data
    return WebThemeDocument.from_dict(balatro_theme_data())




# ---------------------------------------------------------------------------
# DOOM95 HUD（十八轮用户点名重制）：像素字体（Cubic 11 类）+ 枪灰渐变字 +
# 红点泼溅（DOOM 标题血溅）+ 绿色 CRT HUD 扫描框 + 硬切白闪入场。
# ---------------------------------------------------------------------------

_DOOM95_STAGE_HTML = (
    '<div class="vignette"></div>'
    '<div class="scanlines"></div>'
    '<div class="sweep"></div>'
    '<div class="ember e1"></div>'
    '<div class="ember e2"></div>'
    '<div class="ember e3"></div>'
    '<div class="ember e4"></div>'
    '<div class="ember e5"></div>'
    '<div class="ember e6"></div>'
    '<div class="hudgrid"></div>'
    '<div class="pulse"></div>'
)

_DOOM95_STAGE_CSS = """
.wt-stage .vignette{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse 58% 42% at 50% 86%,rgba(46,204,113,.10) 0%,transparent 60%),radial-gradient(ellipse at center,transparent 46%,rgba(0,0,0,.5) 100%)}
.wt-stage .scanlines{position:absolute;inset:0;opacity:.16;background:repeating-linear-gradient(0deg,rgba(46,204,113,.5) 0 2px,transparent 2px 5px);animation:wt-doom-scan 5s linear infinite}
.wt-stage .sweep{position:absolute;top:70%;left:0;width:26%;height:16%;pointer-events:none;background:linear-gradient(105deg,transparent 0%,rgba(220,255,230,.16) 48%,transparent 62%);transform:translateX(-130%) skewX(-16deg);animation:wt-doom-sweep 6.4s linear infinite}
.wt-stage .ember{position:absolute;width:calc(1.6 * var(--wt-u));height:calc(1.6 * var(--wt-u));background:#C22B1E;opacity:.4;animation:wt-doom-flick 4.8s steps(3,end) infinite}
.wt-stage .e1{left:9%;top:76%;animation-delay:-.5s}
.wt-stage .e2{left:21%;top:88%;animation-delay:-1.4s;background:#E8A33D;animation-duration:6.2s}
.wt-stage .e3{left:38%;top:72%;animation-delay:-2.3s;background:#2ECC71;opacity:.32}
.wt-stage .e4{left:57%;top:84%;animation-delay:-.9s;animation-duration:7s}
.wt-stage .e5{left:76%;top:74%;animation-delay:-3.1s;background:#E8A33D}
.wt-stage .e6{left:90%;top:87%;animation-delay:-1.9s;background:#2ECC71;opacity:.3}
.wt-stage .hudgrid{position:absolute;left:4%;right:4%;bottom:3.4%;height:calc(.9 * var(--wt-u));background:repeating-linear-gradient(90deg,rgba(46,204,113,.4) 0 calc(2.4 * var(--wt-u)),transparent calc(2.4 * var(--wt-u)) calc(5 * var(--wt-u)));opacity:.4;animation:wt-doom-grid 3.2s steps(2,end) infinite}
.wt-stage .pulse{position:absolute;left:30%;right:30%;bottom:0;height:calc(9 * var(--wt-u));pointer-events:none;background:radial-gradient(ellipse closest-side at 50% 100%,rgba(194,43,30,.22),transparent 78%);animation:wt-doom-pulse 3.6s ease-in-out infinite}
@keyframes wt-doom-scan{0%{transform:translateY(0)}100%{transform:translateY(calc(3 * var(--wt-u)))}}
@keyframes wt-doom-sweep{0%{transform:translateX(-130%) skewX(-16deg)}100%{transform:translateX(430%) skewX(-16deg)}}
@keyframes wt-doom-flick{0%,100%{opacity:.18;transform:translate(0,0)}50%{opacity:.55;transform:translate(calc(1.2 * var(--wt-u)),calc(-2.4 * var(--wt-u)))}}
@keyframes wt-doom-grid{0%,100%{opacity:.22}50%{opacity:.44}}
@keyframes wt-doom-pulse{0%,100%{opacity:.5}50%{opacity:1}}
"""

_DOOM95_CUE_HTML = (
    '<div class="plate">'
    '<i class="corner c1"></i><i class="corner c2"></i>'
    '<i class="corner c3"></i><i class="corner c4"></i>'
    '<i class="splat s1"></i><i class="splat s2"></i><i class="splat s3"></i>'
    '<span class="tag">{{speaker}}</span>'
    '<div class="face"><span class="line">{{words}}</span></div>'
    '<i class="blood b1"></i><i class="blood b2"></i><i class="blood b3"></i>'
    '<i class="blood b4"></i><i class="blood b5"></i><i class="blood b6"></i>'
    '</div>'
)

_DOOM95_CUE_CSS = """
.wt-cue{position:absolute;left:8%;right:8%;bottom:8%;top:auto;display:flex;justify-content:center;pointer-events:none}
.wt-cue .plate{position:relative;max-width:86%;padding:calc(2.4 * var(--wt-u)) calc(3.6 * var(--wt-u)) calc(2.6 * var(--wt-u));background:repeating-linear-gradient(0deg,rgba(46,204,113,.06) 0 2px,transparent 2px 4px),linear-gradient(180deg,#0D1A11 0%,#0A140D 58%,#08100A 100%);border:calc(.42 * var(--wt-u)) solid #2E8B4F;box-shadow:0 0 0 calc(.28 * var(--wt-u)) #071209,0 0 0 calc(.62 * var(--wt-u)) #1E4D31,calc(.66 * var(--wt-u)) calc(.66 * var(--wt-u)) 0 #000,inset 0 0 calc(2.6 * var(--wt-u)) rgba(46,204,113,.16),0 0 calc(12 * var(--wt-u)) rgba(194,43,30,.25);animation:wt-doom-in .4s steps(5,end) both,wt-doom-out .3s steps(3,end) both;animation-delay:0s,calc(var(--wt-dur) - .3s)}
.wt-cue .corner{position:absolute;width:calc(1.8 * var(--wt-u));height:calc(1.8 * var(--wt-u));border:calc(.34 * var(--wt-u)) solid #58E88C;opacity:.85}
.wt-cue .c1{left:calc(-.9 * var(--wt-u));top:calc(-.9 * var(--wt-u));border-right:none;border-bottom:none}
.wt-cue .c2{right:calc(-.9 * var(--wt-u));top:calc(-.9 * var(--wt-u));border-left:none;border-bottom:none}
.wt-cue .c3{left:calc(-.9 * var(--wt-u));bottom:calc(-.9 * var(--wt-u));border-right:none;border-top:none}
.wt-cue .c4{right:calc(-.9 * var(--wt-u));bottom:calc(-.9 * var(--wt-u));border-left:none;border-top:none}
.wt-cue .tag{position:absolute;left:calc(1.4 * var(--wt-u));top:calc(-2.7 * var(--wt-u));padding:0 calc(1.1 * var(--wt-u));font-family:var(--wt-font);font-size:calc(var(--wt-size) * .4);font-weight:700;color:#06120A;background:#58E88C;letter-spacing:var(--wt-spacing,calc(.12 * var(--wt-u)));box-shadow:calc(.28 * var(--wt-u)) calc(.28 * var(--wt-u)) 0 #000}
.wt-cue .tag:empty{display:none}
.wt-cue .face{position:relative;z-index:2}
.wt-cue .line{display:flex;flex-wrap:wrap;justify-content:center;gap:0 .04em}
.wt-cue .wt-w{display:inline-block;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight,700);font-style:var(--wt-slant,normal);letter-spacing:var(--wt-spacing,calc(.1 * var(--wt-u)));background:linear-gradient(180deg,#FBFCFD 0%,var(--wt-color,#C9D1D9) 30%,#9AA4AE 58%,#66717C 90%);-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;filter:drop-shadow(calc(var(--wt-stroke-w,3px) * .9) 0 0 var(--wt-stroke,#10181E)) drop-shadow(calc(var(--wt-stroke-w,3px) * -.9) 0 0 var(--wt-stroke,#10181E)) drop-shadow(0 calc(var(--wt-stroke-w,3px) * .9) 0 var(--wt-stroke,#10181E)) drop-shadow(0 calc(var(--wt-stroke-w,3px) * -.9) 0 var(--wt-stroke,#10181E)) drop-shadow(calc(.3 * var(--wt-u)) calc(.3 * var(--wt-u)) 0 #04070A) drop-shadow(0 0 calc(.5 * var(--wt-u)) rgba(194,43,30,.4));animation:wt-doom-glyph .15s steps(2,end) both}
.wt-cue .line .wt-w:nth-child(1){animation-delay:.00s}
.wt-cue .line .wt-w:nth-child(2){animation-delay:.04s}
.wt-cue .line .wt-w:nth-child(3){animation-delay:.08s}
.wt-cue .line .wt-w:nth-child(4){animation-delay:.12s}
.wt-cue .line .wt-w:nth-child(5){animation-delay:.16s}
.wt-cue .line .wt-w:nth-child(6){animation-delay:.20s}
.wt-cue .line .wt-w:nth-child(7){animation-delay:.24s}
.wt-cue .line .wt-w:nth-child(8){animation-delay:.28s}
.wt-cue .line .wt-w:nth-child(9){animation-delay:.32s}
.wt-cue .line .wt-w:nth-child(10){animation-delay:.36s}
.wt-cue .line .wt-w:nth-child(n+11){animation-delay:.40s}
.wt-cue .splat{position:absolute;background:#C22B1E;opacity:.62;animation:wt-doom-splat 2.8s steps(3,end) infinite}
.wt-cue .s1{left:calc(-2.6 * var(--wt-u));top:calc(-1.2 * var(--wt-u));width:calc(2 * var(--wt-u));height:calc(2.6 * var(--wt-u));border-radius:46% 54% 52% 48% / 60% 42% 58% 40%;animation-delay:-.4s}
.wt-cue .s2{right:calc(-2.2 * var(--wt-u));top:calc(24%);width:calc(1.7 * var(--wt-u));height:calc(1.7 * var(--wt-u));border-radius:58% 42% 46% 54% / 46% 58% 42% 54%;background:#8E1A10;animation-delay:-1.3s}
.wt-cue .s3{left:calc(12%);bottom:calc(-2 * var(--wt-u));width:calc(1.4 * var(--wt-u));height:calc(1.4 * var(--wt-u));border-radius:52% 48% 58% 42% / 44% 56% 44% 56%;animation-delay:-2.1s}
.wt-cue .blood{position:absolute;top:42%;left:50%;width:calc(1.5 * var(--wt-u));height:calc(1.5 * var(--wt-u));background:#D44830;box-shadow:calc(.4 * var(--wt-u)) calc(.4 * var(--wt-u)) 0 #8E1A10;animation:wt-doom-burst .5s steps(4,end) both;opacity:0}
.wt-cue .b1{--bx:calc(-19 * var(--wt-u));--by:calc(-11 * var(--wt-u));animation-delay:.02s}
.wt-cue .b2{--bx:calc(17 * var(--wt-u));--by:calc(-13 * var(--wt-u));animation-delay:.06s;background:#C22B1E}
.wt-cue .b3{--bx:calc(-15 * var(--wt-u));--by:calc(9 * var(--wt-u));animation-delay:.10s}
.wt-cue .b4{--bx:calc(21 * var(--wt-u));--by:calc(7 * var(--wt-u));animation-delay:.14s;background:#8E1A10}
.wt-cue .b5{--bx:calc(5 * var(--wt-u));--by:calc(-17 * var(--wt-u));animation-delay:.08s}
.wt-cue .b6{--bx:calc(-7 * var(--wt-u));--by:calc(15 * var(--wt-u));animation-delay:.12s;background:#C22B1E}
@keyframes wt-doom-in{0%{transform:translateX(calc(-46 * var(--wt-u))) rotate(-7deg);filter:brightness(4)}55%{transform:translateX(calc(1.6 * var(--wt-u))) rotate(1.2deg);filter:brightness(1.7)}100%{transform:translateX(0) rotate(0);filter:brightness(1)}}
@keyframes wt-doom-out{0%{transform:translateX(0);opacity:1;filter:brightness(1)}60%{filter:brightness(2.4) saturate(2)}100%{transform:translateX(calc(30 * var(--wt-u))) rotate(5deg);opacity:0}}
@keyframes wt-doom-glyph{0%{transform:translateY(calc(3.4 * var(--wt-u)));filter:brightness(5)}100%{transform:none;filter:none}}
@keyframes wt-doom-burst{0%{opacity:1;transform:translate(0,0) rotate(0)}100%{opacity:0;transform:translate(var(--bx),var(--by)) rotate(90deg)}}
@keyframes wt-doom-splat{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:.72;transform:scale(1.12)}}
"""


def _doom95_theme() -> WebThemeDocument:
    return WebThemeDocument(
        name="DOOM95 HUD",
        concept=(
            "1995 DOS FPS 的绿色 CRT HUD：像素字、枪灰金属渐变字、血红泼溅点缀，"
            "绿色扫描线框+琥珀火花+底部弹药格；字幕像状态条一样硬切甩入，白闪一下。"
        ),
        palette={
            "primary": "#C22B1E",
            "secondary": "#8A949E",
            "background": "#0A140D",
            "accent": "#2ECC71",
            "text": "#C9D1D9",
        },
        stage_html=_DOOM95_STAGE_HTML,
        stage_css=_DOOM95_STAGE_CSS,
        cue_html=_DOOM95_CUE_HTML,
        cue_css=_DOOM95_CUE_CSS,
        notes="像素字体优先：Cubic 11/俐方体11号 → Cascadia/Consolas 等宽兜底。",
        appearance={
            "fontFamily": '"Cubic 11", "俐方体11号", "Cascadia Mono", "Consolas", monospace',
            "fontSize": 54,
            "bold": True,
            "italic": False,
            "color": "#C9D1D9",
            "strokeColor": "#10181E",
            "strokeWidth": 3.4,
            "stroke2Color": "",
            "stroke2Width": 0.0,
            "letterSpacing": 1.2,
        },
    )


def _strand_timefall_theme() -> WebThemeDocument:
    """二十八轮重制（用户定调：枪灰+黑流体主体，chiral 金只做点缀）。

    二十七轮金版被用户判定"钢铁侠感/大元素显俗"——按新视觉方案十装置
    （Odradek 伞骨/时雨帘/BT 五指手印/掌纹脉/chiral 晶体/BB 舱/Strand 缆线/
    Q-pid 铭牌/货运角码/雨水痕）+ 70/25/5 色彩铁律重建：底板=黑流体多层暗
    渐变+扫描线+边缘高光细线；手印=炭黑 BT；装置=做旧枪灰结构件（细线、
    辉光弱）；全场景仅中段缆线一根 chiral 金丝+晶体簇+Q-pid 金芯三处点缀。
    """
    stage_html = (
        '<div class="haze"></div>\n'
        '<div class="vignette"></div>\n'
        '<div class="strand-floor">\n'
        '  <i class="strand s1"></i><i class="strand s2"></i><i class="strand s3"></i>\n'
        '</div>\n'
        '<div class="timefall t-a"></div>\n'
        '<div class="timefall t-b"></div>\n'
        '<div class="rain-bead b1"></div>\n'
        '<div class="rain-bead b2"></div>\n'
        '<div class="rain-bead b3"></div>\n'
        '<div class="chiral c1"></div>\n'
        '<div class="chiral c2"></div>\n'
        '<div class="chiral c3"></div>\n'
        '<div class="odradek">\n'
        '  <span class="arm a1"></span><span class="arm a2"></span><span class="arm a3"></span>\n'
        '  <span class="arm a4"></span><span class="arm a5"></span><span class="hub"></span>\n'
        '</div>'
    )
    cue_html = (
        '<div class="plate">\n'
        '  <div class="cargo-lug lg1"></div>\n'
        '  <div class="cargo-lug lg2"></div>\n'
        '  <div class="qpid"><span></span></div>\n'
        '  <div class="bb-pod"><i></i></div>\n'
        '  <div class="handprint">\n'
        '    <span class="finger f1"></span><span class="finger f2"></span><span class="finger f3"></span>\n'
        '    <span class="finger f4"></span><span class="finger f5"></span>\n'
        '    <span class="palm"></span>\n'
        '    <span class="palm-vein"></span>\n'
        '  </div>\n'
        '  <div class="scan-beam"></div>\n'
        '  <div class="tag">{{speaker}}</div>\n'
        '  <div class="line">{{words}}</div>\n'
        '</div>'
    )
    return WebThemeDocument(
        name="Strand Timefall（死亡搁浅·时雨货运带）",
        concept=(
            "死亡搁浅特效字幕：底部 Strand 货运带上，手印、时雨、Odradek、BB舱与手印同时把句子从手印里“接生”出来。入场：Odradek 伞骨张开扫描 .odradek → 时雨斜线扫过底板 .timefall → 手印从雾里拍上底板 .handprint → chiral 晶体碎光闪一下 .chiral → 字幕从手印中心被 Strand 绳拉出。出场：Odradek 收伞、手印褪成灰、绳索把字抽走。场景物件：Odradek 传感器伞骨 .odradek；时雨斜线帘 .timefall；BT 五指手印 .handprint；手印掌纹脉 .palm-vein；chiral 金橙晶体簇 .chiral；BB 舱圆窗 .bb-pod；Strand 绳结与缆线 .strand；Q-pid 菱形铭牌 .qpid；货运箱角码 .cargo-lug；时雨水痕 .rain-bead。"
        ),
        palette={
            "primary": "#8A939C",
            "secondary": "#3A4854",
            "background": "#0A0C0E",
            "accent": "#E8A04A",
            "text": "#EDF1F5",
        },
        stage_html=stage_html,
        stage_css='.wt-stage{position:absolute;inset:0;overflow:hidden;pointer-events:none}\n/* 二十八轮 v2（agy 5.2 分评审重制）：枪灰+黑流体主体，装置具象化，\n   chiral 金只留缆丝+晶体+Q-pid 金芯三处（≈1.1%）。 */\n.haze{position:absolute;left:0;right:0;bottom:0;height:30%;background:radial-gradient(ellipse 72% 84% at 50% 100%,rgba(38,46,54,.20),rgba(8,10,12,.06) 55%,transparent 75%);filter:blur(calc(8*var(--wt-u)));opacity:.85;animation:wt-amb-out .3s ease-in calc(var(--wt-dur) - .3s) forwards}\n.vignette{position:absolute;inset:0;background:radial-gradient(ellipse 58% 42% at 50% 88%,rgba(120,132,142,.06),transparent 62%);pointer-events:none;animation:wt-amb-out .3s ease-in calc(var(--wt-dur) - .3s) forwards}\n/* Strand 碳纤编织缆索层：上文本/中承载/下缆索 */\n.strand-floor{position:absolute;left:6%;right:6%;bottom:6%;height:calc(1.6*var(--wt-u));opacity:.55;animation:wt-amb-out .3s ease-in calc(var(--wt-dur) - .3s) forwards}\n.strand{position:absolute;height:calc(.22*var(--wt-u));background:repeating-linear-gradient(45deg,#1A2026 0,#1A2026 2px,#48525D 2px,#48525D 4px);box-shadow:0 calc(.2*var(--wt-u)) calc(.5*var(--wt-u)) #000}\n.s1{top:0;left:0;width:100%}\n.s2{top:calc(.6*var(--wt-u));left:4%;width:92%;background:linear-gradient(90deg,transparent,#48525D 15%,rgba(232,160,74,.75) 50%,#48525D 85%,transparent);box-shadow:0 0 calc(.5*var(--wt-u)) rgba(232,160,74,.25)}\n.s3{top:calc(1.1*var(--wt-u));left:10%;width:80%;opacity:.4}\n/* 时雨：全屏纵深贯通、双层景深 */\n.timefall{position:absolute;inset:0;height:100%;pointer-events:none;background:repeating-linear-gradient(112deg,transparent 0,transparent calc(1.8*var(--wt-u)),rgba(195,215,230,.32) calc(1.8*var(--wt-u)),rgba(195,215,230,.32) calc(1.95*var(--wt-u)),transparent calc(1.95*var(--wt-u)),transparent calc(4.2*var(--wt-u)));opacity:.5;mask-image:linear-gradient(180deg,rgba(0,0,0,.9) 0%,rgba(0,0,0,.6) 75%,transparent 100%);animation:wt-rain-drift 1.4s linear infinite,wt-amb-out .3s ease-in calc(var(--wt-dur) - .3s) forwards}\n.t-b{opacity:.27;background-size:140% 140%;animation-duration:2.1s;animation-direction:reverse}\n/* Odradek：装配在左下支架上的同向扇面折叶（侦测拍合），出场收伞 */\n.odradek{position:absolute;left:3.5%;bottom:3.2%;width:calc(4.5*var(--wt-u));height:calc(4.5*var(--wt-u));z-index:3;opacity:.85;filter:drop-shadow(0 calc(.4*var(--wt-u)) calc(.8*var(--wt-u)) rgba(0,0,0,.8));animation:wt-odr-open .5s cubic-bezier(.2,1.3,.3,1) both,wt-odr-collapse .45s ease-in calc(var(--wt-dur) - .45s) forwards}\n.odradek .hub{position:absolute;left:15%;bottom:15%;width:calc(1.3*var(--wt-u));height:calc(1.3*var(--wt-u));border-radius:50%;background:radial-gradient(circle at 35% 30%,#BDC5CC,#4A535B 50%,#12161A);border:calc(.1*var(--wt-u)) solid #2A3036;box-shadow:inset 0 0 calc(.3*var(--wt-u)) #000}\n.odradek .arm{position:absolute;left:20%;bottom:20%;width:calc(.42*var(--wt-u));height:calc(3.4*var(--wt-u));transform-origin:bottom center;background:linear-gradient(90deg,#A8B2BC,#48525B 45%,#22282E);clip-path:polygon(30% 0,70% 0,100% 75%,50% 100%,0 75%);box-shadow:0 0 calc(.3*var(--wt-u)) rgba(0,0,0,.6);animation:wt-odradek-clap .85s cubic-bezier(.25,2,.4,1) infinite}\n.a1{transform:rotate(-25deg);animation-delay:0s}\n.a2{transform:rotate(-10deg);animation-delay:.06s}\n.a3{transform:rotate(8deg);animation-delay:.12s}\n.a4{transform:rotate(26deg);animation-delay:.18s}\n.a5{transform:rotate(44deg);animation-delay:.24s}\n/* 开罗尔簇晶：破土手掌多棱柱（金色主点缀，根部焦油浸润） */\n.chiral{position:absolute;bottom:8%;width:calc(1.4*var(--wt-u));height:calc(2.2*var(--wt-u));border-bottom:calc(.3*var(--wt-u)) solid rgba(8,10,13,.92);filter:drop-shadow(0 0 calc(.6*var(--wt-u)) rgba(232,160,74,.35));opacity:.75;animation:wt-amb-out .3s ease-in calc(var(--wt-dur) - .3s) forwards}\n.chiral::before{content:"";position:absolute;left:0;bottom:0;width:55%;height:90%;clip-path:polygon(40% 0,75% 0,100% 70%,65% 100%,0 85%,15% 30%);background:linear-gradient(135deg,#FFE4B5 0%,#E8A04A 40%,#7A4A18 80%,#301804 100%)}\n.chiral::after{content:"";position:absolute;right:0;bottom:0;width:60%;height:100%;clip-path:polygon(30% 0,65% 0,100% 80%,70% 100%,0 80%,20% 25%);background:linear-gradient(120deg,#FFFFFF 0%,#FFA834 35%,#8A5015 75%,#1F1003 100%);transform:rotate(14deg)}\n.c1{left:9%;transform:rotate(-8deg)}\n.c2{right:10%;transform:rotate(12deg)}\n.c3{right:14%;bottom:6%;width:calc(.9*var(--wt-u));height:calc(1.3*var(--wt-u));opacity:.45}\n@keyframes wt-amb-out{to{opacity:0}}\n@keyframes wt-rain-drift{0%{background-position:0 0}100%{background-position:calc(12*var(--wt-u)) calc(28*var(--wt-u))}}\n@keyframes wt-odr-open{0%{transform:scale(.3) rotate(-30deg);opacity:0}70%{opacity:1}100%{transform:none;opacity:.85}}\n@keyframes wt-odr-collapse{to{transform:scale(.55) rotate(-16deg);opacity:0}}\n@keyframes wt-odradek-clap{0%,100%{height:calc(3.4*var(--wt-u));filter:brightness(1)}35%{height:calc(3.8*var(--wt-u));filter:brightness(1.25)}50%{height:calc(3.1*var(--wt-u))}}',
        cue_html=cue_html,
        cue_css='.wt-cue{position:absolute;left:0;right:0;bottom:0;top:auto;height:28%;display:flex;align-items:flex-end;justify-content:center;padding:0 8% 8%;box-sizing:border-box;pointer-events:none}\n/* 底板：黑流体+枪灰货箱（多层暗渐变+扫描线+边缘高光细线，无金属高光框） */\n.plate{position:relative;width:min(78%,calc(118*var(--wt-u)));padding:calc(2.2*var(--wt-u)) calc(4.5*var(--wt-u)) calc(2*var(--wt-u));background:repeating-linear-gradient(90deg,rgba(150,160,170,.045) 0 2px,transparent 2px 7px),linear-gradient(180deg,rgba(36,41,47,.93),rgba(16,19,23,.94) 55%,rgba(8,10,13,.96)),radial-gradient(120% 160% at 50% -20%,rgba(140,152,162,.07),transparent 55%);border:calc(.16*var(--wt-u)) solid rgba(138,148,158,.5);box-shadow:0 calc(1.2*var(--wt-u)) calc(4*var(--wt-u)) rgba(0,0,0,.6),inset 0 calc(.18*var(--wt-u)) calc(.7*var(--wt-u)) rgba(198,206,214,.14),inset 0 0 calc(3*var(--wt-u)) rgba(30,38,46,.35);clip-path:polygon(2% 0,98% 0,100% 18%,100% 82%,98% 100%,2% 100%,0 82%,0 18%);animation:wt-plate-in .7s cubic-bezier(.2,1.4,.3,1) both,wt-plate-out .42s ease-in calc(var(--wt-dur) - .42s) forwards}\n.plate::before{content:"";position:absolute;inset:calc(.35*var(--wt-u));border:1px solid rgba(138,148,158,.24);pointer-events:none}\n/* 货运箱左右 L 型防撞角码+沉头螺钉 */\n.cargo-lug{position:absolute;width:calc(.65*var(--wt-u));height:calc(3.4*var(--wt-u));top:50%;margin-top:calc(-1.7*var(--wt-u));background:linear-gradient(180deg,#4A545E 0%,#20262C 50%,#4A545E 100%);border:1px solid #14181C;box-shadow:inset 0 0 calc(.2*var(--wt-u)) #000,0 calc(.2*var(--wt-u)) calc(.6*var(--wt-u)) rgba(0,0,0,.8)}\n.cargo-lug::after{content:"";position:absolute;left:20%;top:15%;bottom:15%;width:60%;background:radial-gradient(circle at 50% 15%,#9AA4AE 20%,#15181C 60%),radial-gradient(circle at 50% 85%,#9AA4AE 20%,#15181C 60%)}\n.lg1{left:calc(-.32*var(--wt-u))}.lg2{right:calc(-.32*var(--wt-u))}\n/* Q-pid：右上内嵌数据坞+细钛链+极小金芯 */\n.qpid{position:absolute;right:calc(2.4*var(--wt-u));top:calc(-.6*var(--wt-u));width:calc(1.6*var(--wt-u));height:calc(1.6*var(--wt-u));transform:rotate(45deg);background:linear-gradient(135deg,#A8B2BC,#3F474F 60%,#181D21);border:calc(.08*var(--wt-u)) solid #6A747E;box-shadow:0 calc(.3*var(--wt-u)) calc(.8*var(--wt-u)) rgba(0,0,0,.85);animation:wt-qpid-in .45s .3s both,wt-qpid-out .35s calc(var(--wt-dur) - .4s) forwards}\n.qpid::before{content:"";position:absolute;top:-80%;left:45%;width:1px;height:80%;background:#8A939C}\n.qpid span{position:absolute;inset:28%;background:radial-gradient(circle,#FFE4B5 15%,#E8A04A 70%,#683E10);box-shadow:0 0 calc(.35*var(--wt-u)) rgba(232,160,74,.7);border-radius:20%}\n/* BB 舱：厚装甲潜望观察窗（暗琥珀羊水+压铸双环+玻璃月牙+胎儿暗影） */\n.bb-pod{position:absolute;left:calc(1.2*var(--wt-u));top:50%;width:calc(3*var(--wt-u));height:calc(3*var(--wt-u));margin-top:calc(-1.5*var(--wt-u));border-radius:50%;border:calc(.14*var(--wt-u)) solid #4E5965;background:radial-gradient(circle at 45% 42%,rgba(215,135,42,.32) 0%,rgba(110,62,14,.45) 48%,rgba(10,14,18,.96) 78%);box-shadow:0 0 0 calc(.08*var(--wt-u)) #1A2026,0 0 0 calc(.18*var(--wt-u)) #2F3842,inset 0 calc(.2*var(--wt-u)) calc(.5*var(--wt-u)) rgba(0,0,0,.85),0 calc(.4*var(--wt-u)) calc(1.2*var(--wt-u)) rgba(0,0,0,.75);animation:wt-bb-breathe 3.6s ease-in-out infinite}\n.bb-pod::before{content:"";position:absolute;inset:calc(.15*var(--wt-u));border-radius:50%;background:linear-gradient(135deg,rgba(235,245,255,.6) 0%,rgba(170,195,220,.18) 28%,transparent 55%);pointer-events:none}\n.bb-pod i{position:absolute;left:32%;top:30%;width:36%;height:36%;border-radius:45% 55% 60% 40%;background:radial-gradient(circle,rgba(16,20,24,.85),rgba(4,6,8,.95));box-shadow:0 0 calc(.4*var(--wt-u)) rgba(232,160,74,.25);opacity:.85}\n/* BT 焦油手印：液态高光+弧面渐变+受压飞溅拍击（0.24-0.48s 落定） */\n.handprint{position:absolute;left:calc(4.8*var(--wt-u));bottom:calc(-.3*var(--wt-u));width:calc(5.8*var(--wt-u));height:calc(6.6*var(--wt-u));opacity:.92;filter:drop-shadow(0 calc(.6*var(--wt-u)) calc(1.2*var(--wt-u)) rgba(0,0,0,.95)) drop-shadow(0 0 calc(.25*var(--wt-u)) rgba(175,195,215,.32));transform-origin:35% 85%;animation:wt-hand-slap .48s cubic-bezier(.12,1.4,.25,1) .24s both,wt-hand-fade .4s calc(var(--wt-dur) - .4s) forwards}\n.palm{position:absolute;left:18%;bottom:8%;width:64%;height:54%;background:radial-gradient(ellipse 70% 65% at 42% 38%,rgba(42,50,60,.96) 0%,rgba(14,17,21,.98) 55%,#050608 100%);border-radius:52% 46% 44% 58% / 58% 52% 48% 44%;box-shadow:inset calc(.14*var(--wt-u)) calc(.14*var(--wt-u)) calc(.5*var(--wt-u)) rgba(215,230,245,.18),inset calc(-.25*var(--wt-u)) calc(-.25*var(--wt-u)) calc(.7*var(--wt-u)) #000;clip-path:ellipse(50% 48% at 50% 50%)}\n.finger{position:absolute;width:calc(.72*var(--wt-u));background:linear-gradient(180deg,rgba(48,56,66,.95) 0%,rgba(16,20,24,.98) 45%,#050608 100%);border-radius:38% 42% calc(.4*var(--wt-u)) calc(.4*var(--wt-u));box-shadow:inset calc(.08*var(--wt-u)) calc(.15*var(--wt-u)) calc(.25*var(--wt-u)) rgba(220,235,250,.24),inset 0 calc(-.2*var(--wt-u)) calc(.3*var(--wt-u)) #000}\n.f1{left:8%;bottom:42%;height:calc(2.4*var(--wt-u));transform:rotate(-38deg)}.f2{left:26%;bottom:52%;height:calc(2.9*var(--wt-u));transform:rotate(-14deg)}.f3{left:46%;bottom:56%;height:calc(3.2*var(--wt-u))}.f4{left:64%;bottom:50%;height:calc(2.7*var(--wt-u));transform:rotate(16deg)}.f5{left:78%;bottom:38%;height:calc(1.9*var(--wt-u));transform:rotate(38deg)}\n/* 掌纹脉：开罗尔有机神经网（径向弧纹+screen 混合脉动） */\n.palm-vein{position:absolute;left:20%;bottom:16%;width:58%;height:46%;pointer-events:none;background:radial-gradient(ellipse 80% 30% at 30% 65%,transparent 22%,rgba(185,205,225,.45) 24%,transparent 27%),radial-gradient(ellipse 60% 40% at 65% 35%,transparent 18%,rgba(232,160,74,.38) 20%,transparent 24%),linear-gradient(118deg,transparent 46%,rgba(160,180,200,.4) 48%,transparent 52%);filter:blur(calc(.03*var(--wt-u)));mix-blend-mode:screen;opacity:.65;animation:wt-vein-pulse 4.2s ease-in-out infinite alternate}\n.scan-beam{position:absolute;left:8%;right:8%;top:0;height:calc(.24*var(--wt-u));background:linear-gradient(90deg,transparent,rgba(200,210,218,.85),rgba(240,246,250,.9),rgba(138,148,158,.8),transparent);box-shadow:0 0 calc(1.1*var(--wt-u)) rgba(178,192,204,.5);animation:wt-scan 1.1s ease-out .2s both,wt-scan-out .35s calc(var(--wt-dur) - .4s) forwards;opacity:.8}\n/* 时雨水痕：挂在底板上框的下流拉丝 */\n.rain-bead{position:absolute;top:calc(-.3*var(--wt-u));width:calc(.22*var(--wt-u));height:calc(2.4*var(--wt-u));border-radius:calc(.1*var(--wt-u)) calc(.1*var(--wt-u)) 50% 50%;background:linear-gradient(180deg,rgba(240,248,255,.8) 0%,rgba(170,190,205,.3) 60%,transparent 100%);box-shadow:0 0 calc(.2*var(--wt-u)) rgba(200,220,240,.5);opacity:.65;animation:wt-bead-stream 2.4s cubic-bezier(.4,0,.2,1) infinite}\n.b1{left:24%;animation-delay:.2s;height:calc(2.8*var(--wt-u))}\n.b2{left:52%;animation-delay:1.1s;height:calc(2.2*var(--wt-u))}\n.b3{left:76%;animation-delay:.7s;height:calc(2.6*var(--wt-u))}\n.tag:empty{display:none}\n.tag{position:absolute;left:calc(8.5*var(--wt-u));top:calc(-1.05*var(--wt-u));font-family:var(--wt-font);font-size:calc(.9*var(--wt-u));letter-spacing:.18em;color:#D5DCE2;background:linear-gradient(90deg,rgba(30,35,41,.92),rgba(20,24,29,.85));border:1px solid rgba(138,148,158,.4);padding:.12em .7em;clip-path:polygon(8% 0,100% 0,92% 100%,0 100%);box-shadow:0 0 calc(.7*var(--wt-u)) rgba(16,20,24,.5)}\n/* 文字：左锚定（手印→首字 1.8u 张力轴），基线上抬给缆索留呼应 */\n.line{position:relative;z-index:2;text-align:left;padding-left:calc(7.6*var(--wt-u));margin-bottom:calc(.2*var(--wt-u));animation:wt-line-out .4s ease-in calc(var(--wt-dur) - .4s) forwards}\n.wt-text,.wt-w{font-family:var(--wt-font);font-size:var(--wt-size);color:#EDF1F5;letter-spacing:.04em;font-weight:700;text-shadow:calc(.12*var(--wt-u)) calc(.12*var(--wt-u)) 0 #0A0C0E,calc(-.12*var(--wt-u)) calc(.12*var(--wt-u)) 0 #0A0C0E,calc(.12*var(--wt-u)) calc(-.12*var(--wt-u)) 0 #0A0C0E,calc(-.12*var(--wt-u)) calc(-.12*var(--wt-u)) 0 #0A0C0E,0 0 calc(1.2*var(--wt-u)) rgba(196,206,214,.35),0 calc(.2*var(--wt-u)) calc(.6*var(--wt-u)) #000}\n/* 前两字带焦灰（刚从掌心拉出），后续纯冷白 */\n.wt-w:nth-child(-n+2){color:#D8DEE4}\n.wt-w{display:inline-block;animation:wt-word-strand .48s cubic-bezier(.1,1.35,.2,1) both}\n.wt-w:nth-child(1){animation-delay:.52s}.wt-w:nth-child(2){animation-delay:.57s}.wt-w:nth-child(3){animation-delay:.62s}.wt-w:nth-child(4){animation-delay:.67s}.wt-w:nth-child(5){animation-delay:.72s}.wt-w:nth-child(6){animation-delay:.77s}.wt-w:nth-child(7){animation-delay:.82s}.wt-w:nth-child(8){animation-delay:.87s}.wt-w:nth-child(9){animation-delay:.92s}.wt-w:nth-child(10){animation-delay:.97s}.wt-w:nth-child(11){animation-delay:1.02s}.wt-w:nth-child(12){animation-delay:1.07s}.wt-w:nth-child(13){animation-delay:1.12s}.wt-w:nth-child(14){animation-delay:1.17s}.wt-w:nth-child(15){animation-delay:1.22s}.wt-w:nth-child(n+16){animation-delay:1.27s}\n@keyframes wt-plate-in{0%{transform:perspective(900px) rotateX(28deg) translateY(calc(8*var(--wt-u))) scale(.92);opacity:0;filter:blur(calc(.4*var(--wt-u)))}100%{transform:none;opacity:1;filter:none}}\n@keyframes wt-plate-out{to{transform:perspective(900px) rotateX(-18deg) translateY(calc(6*var(--wt-u))) scale(.96);opacity:0;filter:brightness(.5)}}\n@keyframes wt-hand-slap{0%{transform:scale(.25) rotate(-28deg) translateY(calc(-4*var(--wt-u)));opacity:0;filter:blur(calc(.4*var(--wt-u)))}65%{transform:scale(1.15) rotate(3deg) translateY(calc(.2*var(--wt-u)));opacity:1;filter:none}82%{transform:scale(.96) rotate(-1deg)}100%{transform:none;opacity:.92}}\n@keyframes wt-hand-fade{to{opacity:0;filter:grayscale(1) blur(calc(.3*var(--wt-u)))}}\n@keyframes wt-vein-pulse{0%{opacity:.45;filter:blur(calc(.05*var(--wt-u)))}100%{opacity:.8;filter:blur(calc(.02*var(--wt-u)))}}\n@keyframes wt-bead-stream{0%{transform:translateY(0) scaleY(.3);opacity:0}30%{opacity:.75}100%{transform:translateY(calc(3.5*var(--wt-u))) scaleY(1.3);opacity:0}}\n@keyframes wt-scan{0%{transform:translateX(-40%);opacity:0}100%{transform:translateX(0);opacity:.8}}\n@keyframes wt-scan-out{to{opacity:0;transform:translateX(30%)}}\n@keyframes wt-qpid-in{0%{transform:rotate(45deg) scale(0)}100%{transform:rotate(45deg) scale(1)}}\n@keyframes wt-qpid-out{to{transform:rotate(45deg) scale(0);opacity:0}}\n@keyframes wt-bb-breathe{0%,100%{box-shadow:0 0 0 calc(.08*var(--wt-u)) #1A2026,0 0 0 calc(.18*var(--wt-u)) #2F3842,0 0 calc(.6*var(--wt-u)) rgba(215,135,42,.12)}50%{box-shadow:0 0 0 calc(.08*var(--wt-u)) #1A2026,0 0 0 calc(.18*var(--wt-u)) #3F4B58,0 0 calc(1.4*var(--wt-u)) rgba(215,135,42,.28)}}\n/* 接生：0.52s 起字被缆绳从掌心拖出（水平拉长+破膜回弹） */\n@keyframes wt-word-strand{0%{transform:translateX(calc(-5*var(--wt-u))) scaleX(.15) scaleY(.5) skewX(24deg);opacity:0;filter:blur(calc(.35*var(--wt-u)))}65%{transform:translateX(calc(.4*var(--wt-u))) scaleX(1.08) scaleY(1.04) skewX(-4deg);opacity:.95;filter:none}100%{transform:none;opacity:1;filter:none}}\n/* 出场：绳索把整句抽走（右拉+倾斜） */\n@keyframes wt-line-out{to{transform:translateX(calc(5*var(--wt-u))) skewX(-14deg);opacity:0}}',
        notes=(
            "死亡搁浅风格：枪灰货运底板沉在黑流体里，BT 黑手印拍出字幕，Odradek 伞骨扫描锁定，出场时绳索把字抽回雨里。"
        ),
        appearance={
            "fontFamily": '"Source Han Sans CN", "Noto Sans SC", "Microsoft YaHei UI", sans-serif',
            "fontSize": 56,
            "bold": True,
            "italic": False,
            "color": "#EDF1F5",
            "strokeColor": "#0A0C0E",
            "strokeWidth": 3.4,
            "letterSpacing": 1.2,
        },
    )


_BUILTIN_THEME_BUILDERS = {
    "balatro-joker": _balatro_theme,
    "clean-glass": lambda: _CLEAN_THEME,
    "doom95": lambda: _doom95_theme(),
    "strand-timefall": _strand_timefall_theme,
}


def builtin_web_themes() -> dict[str, WebThemeDocument]:
    return {key: builder() for key, builder in _BUILTIN_THEME_BUILDERS.items()}


def fallback_web_theme(instruction: str = "") -> WebThemeDocument:
    """Deterministic offline fallback picked from the user instruction."""
    text = str(instruction or "").casefold()
    for token, key in (
        ("小丑", "balatro-joker"), ("balatro", "balatro-joker"),
        ("赌", "balatro-joker"), ("卡牌", "balatro-joker"), ("joker", "balatro-joker"),
        ("doom", "doom95"), ("像素", "doom95"), ("pixel", "doom95"),
        ("复古", "doom95"), ("retro", "doom95"), ("fps", "doom95"),
        ("死亡搁浅", "strand-timefall"), ("death stranding", "strand-timefall"),
        ("手印", "strand-timefall"), ("chiral", "strand-timefall"), ("搁浅", "strand-timefall"),
        ("strand", "strand-timefall"), ("时雨", "strand-timefall"), ("timefall", "strand-timefall"),
    ):
        if token in text:
            return builtin_web_themes()[key]
    return builtin_web_themes()["clean-glass"]


_SECTION_MARKER_RE = re.compile(r"^\s*={2,}\s*([A-Za-z_]+)\s*={2,}\s*$")
_SECTION_KEYS = {
    "NAME": "name",
    "CONCEPT": "concept",
    "PALETTE": "palette",
    "APPEARANCE": "appearance",
    "MOTION_SPEC": "motionSpec",
    "STAGE_HTML": "stageHtml",
    "STAGE_CSS": "stageCss",
    "CUE_HTML": "cueHtml",
    "CUE_CSS": "cueCss",
    "NOTES": "notes",
}


def parse_web_theme_sections(text: str) -> dict[str, Any]:
    """Parse the ===SECTION=== plain-text protocol into a theme payload.

    Transport for theme generation: HTML/CSS sections live verbatim between
    markers instead of being JSON-escaped — embedding big HTML/CSS inside a
    JSON string is the single most common way for structured-output models
    (DeepSeek et al.) to produce an invalid payload. Accepts leading prose
    before the first marker; fenced blocks at section edges are stripped.
    """
    payload: dict[str, Any] = {}
    current: str | None = None
    buffer: list[str] = []
    # Some providers put a section value on the marker's own line. Normalize
    # only known protocol markers at line starts, never arbitrary CSS/HTML.
    protocol='|'.join(_SECTION_KEYS)
    text=re.sub(r'(?m)^([ \t]*={2,}[ \t]*(?:'+protocol+r')[ \t]*={2,})[ \t]*(?=[^\s=])',r'\1\n',str(text or ''),flags=re.I)
    for line in text.splitlines():
        match = _SECTION_MARKER_RE.match(line)
        if match is not None:
            if current is not None:
                payload[current] = _clean_section("\n".join(buffer))
            current = _SECTION_KEYS.get(str(match.group(1)).upper())
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    if current is not None:
        payload[current] = _clean_section("\n".join(buffer))
    if "palette" in payload:
        payload["palette"] = _parse_palette_entries(payload["palette"])
    if "appearance" in payload:
        payload["appearance"] = _parse_appearance_entries(payload["appearance"])
    if 'motionSpec' in payload:payload['motionSpec']=json.loads(payload['motionSpec'])
    return payload


def _parse_appearance_entries(body: str) -> dict[str, Any]:
    """`fontFamily=...` / `fontSize=58` style k=v lines (one key per line)."""
    appearance: dict[str, Any] = {}
    for line in str(body or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        raw = value.strip()
        if key == "fontFamily":
            appearance["fontFamily"] = raw
        elif key in ("fontSize", "fontWeight", "strokeWidth", "stroke2Width", "letterSpacing"):
            try:
                appearance[key] = float(raw)
            except ValueError:
                appearance[key] = raw
        elif key in ("bold", "italic"):
            appearance[key] = raw.strip().lower() not in {"0", "false", "no", "否", "off"}
        elif key in ("color", "strokeColor", "stroke2Color"):
            appearance[key] = raw
    return appearance


def _clean_section(body: str) -> str:
    text = str(body or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().casefold() in {"```", "```html", "```css", "```text"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_palette_entries(body: str) -> dict[str, str]:
    palette: dict[str, str] = {}
    for token in str(body or "").replace(",", " ").replace(";", " ").split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        palette[key.strip().lower()] = value.strip()
    return palette


def substitute_placeholders(
    cue_html: str,
    *,
    text: str,
    speaker: str = "",
    translation: str = "",
) -> str:
    """Fill the v1 placeholders (Python side mirrors the TSX runtime)."""
    from .caption_text_layout import normalized_caption_text
    text = normalized_caption_text(text or '')
    escaped = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    escaped = '<span data-caption-text="true">' + escaped + '</span>'
    words = '<span data-caption-text="true">' + "".join(
        f'<span class="wt-w">{char.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}</span>'
        if not char.isspace() else char
        for char in str(text or "")
    ) + '</span>'
    speaker_escaped = (
        str(speaker or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    translation_escaped = (
        str(translation or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    html = _PLACEHOLDER_RE.sub(
        lambda match: {
            "text": escaped,
            "words": words,
            "speaker": speaker_escaped,
            "translation": translation_escaped,
        }[match.group(1)],
        str(cue_html or ""),
    )
    return html


# ---------------------------------------------------------------------------
# Theme archives — standalone, drag-anywhere asset files (2026-09-02)
# ---------------------------------------------------------------------------

ARCHIVE_DIR_SUFFIX = ".2byte-theme"
ARCHIVE_DEMO_SECONDS = 3.4

# Live 预览驱动（十九轮起；二十四轮修订）。关键纪律与 TSX 运行时相同——WAAPI
# pause() 是异步 pending，必须 await ready 再写 currentTime，否则帧内容会被
# pending pause 结算覆盖。二十四轮两修：
# ① __2bytePlay 不再把 play() 打到已完成的有限动画上——WAAPI 语义是 play()
#   作用于 finished 的正向动画会把 currentTime 回卷到 0 重播（"1s 入场在 3s
#   字幕里重复 3 次"的根因：每次重同步都重播入场）。已完成的动画钉在末态。
# ② __2byteSeek 同步 --wt-t/--wt-at/--wt-p token（与 TSX 运行时对齐，供
#   用 calc(var(--wt-t)) 表达时间的主题在 live 页同样成立）。
_LIVE_DRIVER_SCRIPT = """
window.__2byteSeek = async function (cueMs, stageMs) {
  var started = performance.now();
  var metrics = window.__2byteMetrics || (window.__2byteMetrics = {seeks:0, domSwaps:0});
  var stage = document.querySelector('.wt-stage');
  var cue = document.getElementById('wt-cue');
  var scope = document.querySelector('.wt-scope');
  var rawDuration = scope ? getComputedStyle(scope).getPropertyValue('--wt-dur').trim() : '0s';
  var durationMs = (parseFloat(rawDuration) || 0) * (/ms$/.test(rawDuration) ? 1 : 1000);
  await window.__2bytePrepareCaption(cue);
  if(window.__2byteMotionSpec){
    cue.getBoundingClientRect();
    await document.fonts.ready;
    window.__2byteMountMotion(cue,window.__2byteMotionSpec,durationMs);
  }
  window.__2byteFitCueAnimations(cue, durationMs);
  async function scrub(root, tMs) {
    if (!root) return 0;
    return await window.__2byteDriveAnimations(root, tMs);
  }
  var counts = await Promise.all([scrub(stage, stageMs), scrub(cue, cueMs)]);
  var count = counts.reduce((total,value)=>total+value,0);
  metrics.seeks++; metrics.animationCount = count;
  metrics.seekMs = performance.now()-started;
  // 二十四轮：与 TSX 运行时同款 token——部分主题用 var(--wt-t) 参与计算。
  try {
    var scope = document.querySelector('.wt-scope');
    if (scope) {
      var dRaw = getComputedStyle(scope).getPropertyValue('--wt-dur') || '0s';
      var durMs = (parseFloat(dRaw) || 0) * (/ms$/.test(dRaw.trim()) ? 1 : 1000);
      var progress = durMs > 0 ? Math.max(0, Math.min(1, cueMs / durMs)) : 0;
      var s = scope.style;
      s.setProperty('--wt-t', Math.max(0, cueMs) + 'ms');
      s.setProperty('--wt-at', Math.max(0, stageMs) + 'ms');
      s.setProperty('--wt-p', String(Math.round(progress * 1000) / 1000));
    }
  } catch (e) {}
};
// 二十轮引入自由播放；二十四轮修正 play() 语义：已完成的有限动画（入场/
// 出场这类一次性 keyframes）钉在末态，只有未完成/无限动画继续走。
window.__2bytePlay = async function (cueMs, stageMs, rate) {
  await window.__2byteSeek(cueMs, stageMs);
  if(window.__2byteMotionSpec)return; // Studio pumps explicit time; no second animation clock.
  var stage = document.querySelector('.wt-stage');
  var cue = document.getElementById('wt-cue');
  function play(root, r) {
    if (!root) return;
    var anims = root.getAnimations({subtree: true});
    for (var i = 0; i < anims.length; i++) {
      var a = anims[i];
      try {
        a.playbackRate = r;
        var end = Infinity;
        try {
          var timing = a.effect && a.effect.getComputedTiming();
          if (timing && Number.isFinite(timing.endTime)) end = timing.endTime;
        } catch (e) {}
        if (Number.isFinite(end) && (a.currentTime == null || a.currentTime >= end)) {
          a.currentTime = end;  // 钉末态：play() 会回卷 finished 动画重播
          a.pause();
        } else {
          a.play();
        }
      } catch (e) {}
    }
  }
  play(stage, rate);
  play(cue, rate);
};
// 二十二轮（换字快速路径）：同主题换文案不重载页面——用内嵌模板重建 cue 层
// DOM（Python 侧 substitute_placeholders 的 JS 镜像）；重建后由调用方重新
// __2bytePlay/__2byteSeek 同步动画（新 DOM = 新动画实例）。换页 1-2s vs 换字
// ~50ms——cue 切换不再丢入场首帧。
var preparedCues = new Map();
function cuePoolKey(text,speaker) { return JSON.stringify([String(text||''),String(speaker||'')]); }
window.__2bytePrepareCue = function (text, speaker) {
  var started = performance.now();
  var template = window.__2byteCueTemplate;
  if (typeof template !== 'string') return false;
  var key=cuePoolKey(text,speaker);
  if(preparedCues.has(key)) return true;
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  var s = String(text == null ? '' : text);
  s=s.replace(/\\r\\n|[\\r\\u2028\\u2029]/g,'\\n');
  var escaped = '<span data-caption-text="true">'+esc(s)+'</span>';
  var words = '';
  var chars = Array.from(s);
  for (var i = 0; i < chars.length; i++) {
    var ch = chars[i];
    words += /\\s/.test(ch) ? ch : '<span class="wt-w">' + esc(ch) + '</span>';
  }
  words='<span data-caption-text="true">'+words+'</span>';
  var html = template
    .replace(/\\{\\{\\s*text\\s*\\}\\}/g, escaped)
    .replace(/\\{\\{\\s*words\\s*\\}\\}/g, words)
    .replace(/\\{\\{\\s*speaker\\s*\\}\\}/g, esc(String(speaker || '')))
    .replace(/\\{\\{\\s*translation\\s*\\}\\}/g, '');
  var holder=document.createElement('template');
  holder.innerHTML=html;
  preparedCues.set(key,Array.from(holder.content.childNodes));
  while(preparedCues.size>6) preparedCues.delete(preparedCues.keys().next().value);
  var metrics=window.__2byteMetrics || (window.__2byteMetrics={seeks:0,domSwaps:0});
  metrics.cueBuilds=(metrics.cueBuilds||0)+1;
  metrics.prepareMs=performance.now()-started;
  return true;
};
window.__2byteSetCue = function(text,speaker,durationMs) {
  var started=performance.now(), cue=document.getElementById('wt-cue');
  if(!cue) return false;
  var key=cuePoolKey(text,speaker), hit=preparedCues.has(key);
  if(!hit && !window.__2bytePrepareCue(text,speaker)) return false;
  var nodes=preparedCues.get(key);
  // Retain node identity, including on revisits; only the active cue is attached.
  preparedCues.delete(key); preparedCues.set(key,nodes);
  var scope=document.querySelector('.wt-scope');
  if(scope && Number.isFinite(durationMs)) scope.style.setProperty('--wt-dur',Math.max(50,durationMs)+'ms');
  if(window.__2byteUnmountMotion)window.__2byteUnmountMotion(cue);
  cue.replaceChildren(...nodes);
  var metrics = window.__2byteMetrics || (window.__2byteMetrics = {seeks:0,domSwaps:0});
  metrics.cuePoolHits=(metrics.cuePoolHits||0)+(hit?1:0);
  metrics.cuePoolMisses=(metrics.cuePoolMisses||0)+(hit?0:1);
  metrics.domSwaps++; metrics.domMs=performance.now()-started;
  return true;
};
"""


def theme_archive_html(
    theme: Mapping[str, Any],
    *,
    sample_text: str = "这是字幕特效的动画演示",
    speaker: str = "",
    duration_seconds: float = ARCHIVE_DEMO_SECONDS - 1.0,
    auto_replay: bool = True,
    placement: Mapping[str, Any] | None = None,
) -> str:
    """Self-contained HTML archive: theme CSS + sample cue + auto-replay loop.

    Any browser plays the real animation on double-click (no Remotion, no
    build). The full theme JSON rides along in a data island so the app (and
    users) can re-import the exact theme later. ``auto_replay=False`` plus
    the embedded ``__2byteSeek`` driver turns the same document into the
    live preview page (round 19: real-time frame pump for the video layer).
    """
    document = WebThemeDocument.from_dict(dict(theme))
    from .web_placement import normalize_placement
    placement_json = json.dumps(normalize_placement(placement), allow_nan=False)
    from .runtime_paths import detect_install_root
    animation_runtime = (detect_install_root() / 'renderer/src/webThemeClock.js').read_text(encoding='utf8')
    motion_runtime=''
    if document.motion_spec:
        motion_runtime=(detect_install_root()/'renderer/node_modules/gsap/dist/gsap.min.js').read_text('utf8')+'\n'+(detect_install_root()/'renderer/src/webThemeMotion.js').read_text('utf8')
    motion_json=json.dumps(document.motion_spec,ensure_ascii=False).replace('</','<\\/') if document.motion_spec else 'null'
    payload = json.dumps(document.to_dict(), ensure_ascii=False).replace("</", "<\\/")
    # 二十二轮：内嵌原始 cue 模板（含占位符），__2byteSetCue 换字不换页。
    cue_template_json = json.dumps(document.cue_html, ensure_ascii=False).replace("</", "<\\/")
    cue_html = substitute_placeholders(
        document.cue_html, text=sample_text, speaker=speaker,
    )
    # 十八轮：档案演示注入主题自带外观（像素字体栈/主题文字色），
    # 双击浏览器打开就是主题设计本貌，而不是工程默认外观。
    look = effective_appearance(document.to_dict())
    from .web_theme_fonts import offline_font_css, css_font_stack
    font_css=offline_font_css(look['fontFamily'])
    duration = max(0.05, float(duration_seconds))
    replay_script = ("<script>(function(){var timer=null,enabled=true;"
        "window.__2byteStopReplay=function(){enabled=false;clearTimeout(timer);};"
        "async function replay(){clearTimeout(timer);await window.__2bytePlay(0,0,1);"
        f"if(enabled)timer=setTimeout(replay,{int((duration+.5)*1000)});}}"
        "document.getElementById('wt-frame').addEventListener('click',function(){enabled=true;replay();});"
        "replay();})();</script>"
        if auto_replay else "")
    if document.motion_spec and auto_replay:
        # The preview transport owns wall time; only explicit seek mutates the
        # paused animation. Export/LIVE omit this optional transport entirely.
        replay_script=("<script>(function(){let request=0,enabled=true,anchor;"
            "window.__2byteStopReplay=()=>{enabled=false;cancelAnimationFrame(request);};"
            "async function frame(now){if(!enabled)return;if(anchor==null)anchor=now;"
            f"const ms=(now-anchor)%{int((duration+.5)*1000)};"
            "await window.__2byteSeek(ms,ms);if(enabled)request=requestAnimationFrame(frame);}"
            "document.getElementById('wt-frame').addEventListener('click',()=>{window.__2byteStopReplay();enabled=true;anchor=null;request=requestAnimationFrame(frame);});"
            "request=requestAnimationFrame(frame);})();</script>")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'">
<title>{html_escape(document.name)} · 2ByteASR 字幕特效档案</title>
<style>
{font_css}
  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: transparent; overflow: hidden; }}
  .wt-frame {{ position: relative; width: 100%; height: 100%; overflow: hidden; }}
  .wt-scope {{ position: absolute; inset: 0;
    --wt-font: {css_font_stack(look["fontFamily"])};
    --wt-size: {float(look["fontSize"])/10.8:.6f}vh; --wt-weight: {look.get("fontWeight", 700 if look["bold"] else 400)}; --wt-slant: {"italic" if look["italic"] else "normal"}; --wt-color: {look["color"]};
    --wt-stroke: {look["strokeColor"]}; --wt-stroke-w: {float(look["strokeWidth"])/10.8:.6f}vh; --wt-stroke2: {look["stroke2Color"]}; --wt-stroke2-w: {float(look["stroke2Width"])/10.8:.6f}vh;
    --wt-spacing: {float(look["letterSpacing"])/10.8:.6f}vh; --wt-u: 1.111111vh; --wt-w: 100vw; --wt-h: 100vh; --wt-dur: {duration:.3f}s; --wt-t: 0s; --wt-at: 0s; --wt-p: 0;
    box-sizing: border-box;
  }}
  .wt-stage {{ position: absolute; inset: 0; }}
  .wt-cue {{ position: absolute; inset: 0; }}
{document.stage_css}
{document.cue_css}
</style>
</head>
<body>
<div class="wt-frame" id="wt-frame">
 <subtitle-placement id="subtitle-placement">
  <div class="theme-motion">
  <div class="wt-scope">
    <div class="wt-stage">{document.stage_html}</div>
    <div class="wt-cue" id="wt-cue">{cue_html}</div>
  </div>
  </div>
 </subtitle-placement>
</div>
<script type="application/json" id="wt-theme-data">{payload}</script>
<script>window.__2byteCueTemplate = {cue_template_json};</script>
<script>
{motion_runtime}
window.__2byteMotionSpec={motion_json};
{animation_runtime}
window.__2byteSetPlacement=function(value){{window.__2byteApplyPlacement(document.getElementById('subtitle-placement'),value);}};
window.__2byteSetPlacement({placement_json});
{_LIVE_DRIVER_SCRIPT}
</script>
{replay_script}
</body>
</html>
"""


def export_theme_archive(
    theme: Mapping[str, Any],
    dest_dir: str | os.PathLike[str],
    *,
    sample_text: str = "这是字幕特效的动画演示",
    speaker: str = "",
    validate_before_publish=None,
    cancel_check=None,
    placement: Mapping[str, Any] | None = None,
) -> Path:
    """Stage, reread and atomically publish a new archive; never overwrite."""
    import tempfile
    import shutil
    import uuid
    from .theme_metadata import validate_theme_before_save
    document = WebThemeDocument.from_dict(validate_theme_before_save(theme))
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', document.name).strip(' ._')[:90] or 'theme'
    destination = Path(dest_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    folder = destination / f"{safe}{ARCHIVE_DIR_SUFFIX}"
    if folder.exists(): folder = destination / f'{safe}-{uuid.uuid4().hex[:8]}{ARCHIVE_DIR_SUFFIX}'
    staging = Path(tempfile.mkdtemp(prefix='.2byte-theme-', dir=destination))
    try:
        payload = document.to_dict()
        for name, content in (
            ('theme.json',json.dumps(payload,ensure_ascii=False,indent=2)),
            ('theme.html',theme_archive_html(payload,sample_text=sample_text,speaker=speaker,duration_seconds=6.,placement=placement)),
            ('placement.json',json.dumps(placement or {},ensure_ascii=False,indent=2))):
            with (staging/name).open('w',encoding='utf8',newline='\n') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        if import_theme_archive(staging/'theme.json') != payload or import_theme_archive(staging/'theme.html') != payload:
            raise WebThemeValidationError('导出档案重读不一致')
        if validate_before_publish is not None: validate_before_publish(staging)
        if cancel_check is not None and cancel_check():
            raise WebThemeValidationError('档案导出已取消')
        if import_theme_archive(staging/'theme.json') != payload or import_theme_archive(staging/'theme.html') != payload:
            raise WebThemeValidationError('档案发布前 schema/内容重验不一致；原档案已保留，请重试导出。')
        staging.rename(folder)
        return folder
    finally:
        if staging.exists():
            # This is only the temp directory created by this invocation.
            if staging.resolve().parent != destination or not staging.name.startswith('.2byte-theme-'):
                raise RuntimeError('unexpected archive staging path')
            shutil.rmtree(staging)


def import_theme_archive(source: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a theme back from an archive folder / theme.html / theme.json.

    Returns the validated theme dict; raises WebThemeValidationError on
    anything that is not a 2ByteASR web theme archive.
    """
    path = Path(source)
    candidates: list[Path] = []
    if path.is_dir():
        candidates.extend([path / "theme.json", path / "theme.html"])
    else:
        candidates.append(path)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        if candidate.suffix.lower() == ".html":
            match = re.search(
                r'<script[^>]*id="wt-theme-data"[^>]*>(.*?)</script>',
                text, flags=re.DOTALL,
            )
            if not match:
                raise WebThemeValidationError(
                    f"{candidate.name} 里没有 wt-theme-data 数据岛，不是 2ByteASR 字幕特效档案。"
                )
            text = match.group(1).replace("<\\/", "</")
        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise WebThemeValidationError("档案数据不是 JSON 对象。")
        return WebThemeDocument.from_dict(dict(payload)).to_dict()
    raise WebThemeValidationError(f"找不到可导入的档案文件：{path}")


__all__ = [
    "WEB_THEME_SCHEMA",
    "WEB_THEME_VERSION",
    "ARCHIVE_DIR_SUFFIX",
    "WebThemeDocument",
    "WebThemeValidationError",
    "builtin_web_themes",
    "fallback_web_theme",
    "parse_web_theme_sections",
    "sanitize_css",
    "sanitize_html",
    "substitute_placeholders",
    "export_theme_archive",
    "import_theme_archive",
    "theme_archive_html",
]
