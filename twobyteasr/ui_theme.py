"""Shared visual tokens for the 2ByteASR desktop interface.

The application has several independently rendered surfaces (main workbench,
model workshop and project-owned dialogs).  Keeping the palette, radii and
spacing here prevents those surfaces from drifting into separate themes.

2026-10-14 theme system: a theme is its 29 frozen tokens (ThemeDefinition)
plus optional character in THEME_TRAITS (family, on-accent ink, identity
hues, ...).  Every trait has a default derived from the tokens, so code never
asks ``theme.key == "warm"``: it asks ``theme.is_light`` or reads a role.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Warm neutral surfaces -----------------------------------------------------
BACKGROUND = "#faf7f1"
BACKGROUND_ALT = "#f5f0e7"
SURFACE = "#fffefa"
SURFACE_MUTED = "#f7f3eb"
SURFACE_RAISED = "#ffffff"

# Borders -------------------------------------------------------------------
BORDER = "#e1d7c8"
BORDER_STRONG = "#d2c3ae"
BORDER_ACTIVE = "#9fbd9f"

# Content -------------------------------------------------------------------
INK = "#292a27"
INK_SOFT = "#494943"
MUTED = "#65645d"
MUTED_LIGHT = "#87837a"

# Accents -------------------------------------------------------------------
GREEN = "#4f8557"
GREEN_HOVER = "#43754b"
GREEN_PRESSED = "#396641"
GREEN_SOFT = "#e6efe2"
GREEN_SUBTLE = "#f1f6ee"
AMBER = "#bd8535"
AMBER_SOFT = "#f7edd9"
CORAL = "#b86555"

# Legacy stage names intentionally remain available to the progress UI, but
# use warm, low-saturation values instead of a blue/purple SaaS palette.
BLUE = "#728878"
PURPLE = "#8a7972"
MINT = "#dce9d8"
CHARCOAL = "#3d403a"

# Component geometry --------------------------------------------------------
RADIUS_SM = 8
RADIUS_CONTROL = 10
RADIUS_CARD = 16
RADIUS_SHELL = 18
RADIUS_DIALOG = 20

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24
SPACE_7 = 32

CONTROL_HEIGHT = 40
HEADER_HEIGHT = 58


@dataclass(frozen=True)
class ThemeDefinition:
    """Application-wide semantic colors shared by every desktop surface."""

    key: str
    label: str
    labels: dict[str, str]
    app_background: str
    surface: str
    surface_elevated: str
    panel: str
    input_surface: str
    selected: str
    timeline: str
    media: str
    border: str
    border_strong: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    success: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    shell: str
    shell_border: str
    focus: str
    disabled: str

    # Canonical semantic contract. The legacy names above remain available
    # while independently styled surfaces migrate to role-based tokens.
    @property
    def surface_muted(self) -> str:
        return self.panel

    @property
    def surface_input(self) -> str:
        return self.input_surface

    # 2026-10-14: character beyond the frozen tokens. ``traits`` is the one
    # place a theme states it; each property below falls back to a value
    # derived from the tokens, so a new theme never needs a code branch.
    @property
    def traits(self) -> "ThemeTraits":
        return THEME_TRAITS.get(self.key, _DEFAULT_TRAITS)

    @property
    def is_light(self) -> bool:
        """Light surfaces (dark ink): decided by the window background."""
        return hex_luminance(self.app_background) > 0.35

    @property
    def family(self) -> str:
        """Picker group: ``light`` / ``dark`` / ``contrast``."""
        return self.traits.family or ("light" if self.is_light else "dark")

    @property
    def mood(self) -> dict[str, str]:
        """One short localized line describing the look (appearance picker)."""
        return self.traits.mood

    @property
    def text_on_accent(self) -> str:
        if self.traits.text_on_accent:
            return self.traits.text_on_accent
        ink = self.text if self.is_light else self.app_background
        return "#ffffff" if contrast_ratio("#ffffff", self.accent) >= contrast_ratio(ink, self.accent) else ink

    @property
    def on_accent_is_light(self) -> bool:
        """Glyph color (check marks, dots) drawn on an accent fill."""
        return hex_luminance(self.text_on_accent) > 0.5

    @property
    def media_accent(self) -> str:
        """Selection box and handles drawn over video (2026-10-14).

        The brand colour when it stands out on the media black; ink or very
        dark accents (paper) fall back to the focus colour.
        """
        for candidate in (self.accent, self.accent_text, self.focus):
            if contrast_ratio(candidate, self.media) >= 2.5:
                return candidate
        return "#ffffff"

    @property
    def control_border_hover(self) -> str:
        """Input/combo border under the pointer: one visible step past rest."""
        if self.is_light:
            return blend_hex(self.border_strong, self.text_muted, 0.45)
        return self.text_muted

    @property
    def primary_role(self) -> str:
        return self.accent

    @property
    def secondary_role(self) -> str:
        return self.success

    @property
    def tertiary_role(self) -> str:
        return self.warning

    @property
    def timeline_background(self) -> str:
        return self.timeline

    @property
    def timeline_grid(self) -> str:
        return self.border_strong

    @property
    def timeline_playhead(self) -> str:
        return self.accent

    @property
    def control_background(self) -> str:
        return self.surface_elevated

    @property
    def control_hover(self) -> str:
        return self.selected

    @property
    def control_checked(self) -> str:
        return self.accent_soft

    @property
    def overlay_scrim(self) -> str:
        if self.traits.overlay_scrim:
            return self.traits.overlay_scrim
        # Light themes dim with their own ink; dark themes with their media black.
        red, green, blue = _hex_channels(self.text if self.is_light else self.media)
        return f"rgba({red}, {green}, {blue}, {92 if self.is_light else 156})"

    @property
    def drop_surface(self) -> str:
        return self.surface_elevated

    # 2026-10-07 semantic roles (properties only; TOKEN_FIELDS stays frozen).
    @property
    def accent_text(self) -> str:
        """Brand color readable as text/icon on the theme's surfaces."""
        if self.traits.accent_text:
            return self.traits.accent_text
        value = self.accent
        for _ in range(10):  # step toward the ink until it reads as text
            if contrast_ratio(value, self.surface) >= 4.5:
                break
            value = blend_hex(value, self.text, 0.12)
        return value

    @property
    def info(self) -> str:
        return self.traits.info or self.focus

    @property
    def success_soft(self) -> str:
        return blend_hex(self.surface, self.success, 0.16)

    @property
    def info_soft(self) -> str:
        return blend_hex(self.surface, self.info, 0.16)

    @property
    def accent_tint(self) -> str:
        """Quiet brand wash for selected navigation (never a status)."""
        return blend_hex(self.surface, self.accent, self.traits.tint_amount or 0.22)

    @property
    def hairline(self) -> str:
        """Divider between rows inside one surface; quieter than border."""
        return blend_hex(self.surface, self.border, 0.7)

    @property
    def role_colors(self) -> dict[str, str]:
        """Each theme's own companion palette (identity hues, never status).

        A colour card per theme around its brand: grape = sunset (dusty violet,
        apricot, mauve beside raspberry); warm = garden (cornflower, berry
        rose, mustard beside forest green); plum = orchard (mauve, dusty aqua,
        apricot beside sage); lavender = pastel (sky, peach, lemon beside
        lilac); slate = nordic (sea glass, dusty rose, soft lavender beside
        peach). Readiness is always a labelled chip, never these hues.
        """
        # Dark themes use dusty, lower-chroma tones: noticeable above the
        # surface but never louder than the brand action (user, 2026-10-08).
        if self.traits.role_colors:
            return dict(self.traits.role_colors)
        if self.is_light:
            return {"primary": "#4a6fc2", "timeline": "#b44d7a", "review": "#a8841c"}
        return {"primary": "#a48ad9", "timeline": "#d6957c", "review": "#c48cb4"}

    @property
    def role_wash(self) -> tuple[float, float, float]:
        """(rest, hover, border) blend amounts for identity-tinted cards."""
        if self.traits.role_wash:
            return self.traits.role_wash
        return (0.12, 0.18, 0.5) if self.is_light else (0.08, 0.13, 0.32)

    @property
    def zone_colors(self) -> dict[str, str]:
        """Low-saturation zone hues for the home blocks (user, 2026-10-08):
        Studio berry pink / purple-red, AI magenta rose-violet, content &
        terms grey-violet leaning cyan. Light themes use deeper tones."""
        if self.traits.zone_colors:
            return dict(self.traits.zone_colors)
        if self.is_light:
            return {"studio": "#b25a80", "ai": "#9a5aa6", "content": "#557e8e"}
        return {"studio": "#cc7f9e", "ai": "#b585c4", "content": "#8aa5b8"}

    @property
    def studio_paper(self) -> tuple[str, str, str, str, str]:
        """Home Studio entrance card: paper, paper hover, motif edge, ink, ink secondary."""
        if self.traits.studio_paper:
            return self.traits.studio_paper
        return (blend_hex(self.surface, self.accent, 0.13), blend_hex(self.surface, self.accent, 0.2),
                self.border_strong, self.text, self.text_secondary)

    @property
    def on_vivid(self) -> str:
        """Icon color on a vivid role/status chip."""
        return self.traits.on_vivid or ("#ffffff" if self.is_light else self.app_background)

    @property
    def log_background(self) -> str:
        return self.traits.log_background or self.media

    @property
    def log_text(self) -> str:
        return self.traits.log_text or "#e8e6e1"

    # P9A aliases. Not dataclass fields — TOKEN_FIELDS must stay frozen.
    @property
    def bg_app(self) -> str:
        return self.app_background

    @property
    def bg_panel(self) -> str:
        return self.panel

    @property
    def bg_card(self) -> str:
        return self.surface

    @property
    def bg_control(self) -> str:
        return self.surface_elevated

    @property
    def bg_control_hover(self) -> str:
        return self.selected

    @property
    def bg_control_pressed(self) -> str:
        return self.accent_soft

    @property
    def bg_popup(self) -> str:
        return self.surface_elevated

    @property
    def bg_modal(self) -> str:
        return self.surface

    @property
    def border_subtle(self) -> str:
        return self.border

    @property
    def border_default(self) -> str:
        return self.border_strong

    @property
    def border_focus(self) -> str:
        return self.accent

    @property
    def text_primary(self) -> str:
        return self.text

    @property
    def text_disabled(self) -> str:
        return self.disabled

    @property
    def accent_primary(self) -> str:
        return self.accent



THEMES = {
    # 2026-10-07 视觉体系：保留深葡萄紫气质，但层级改为偏中性的灰紫表面，
    # 品牌莓果色只承担主操作/选中指示；成功/警告/错误/信息使用可区分的色相，
    # 不再与品牌粉紫混在一起。
    "grape": ThemeDefinition(
        key="grape", label="Grape Nocturne",
        labels={"zh": "葡萄夜幕", "zh-Hant": "葡萄夜幕", "en": "Grape Nocturne", "ja": "グレープ・ノクターン", "ko": "그레이프 녹턴"},
        app_background="#19151c", surface="#252028", surface_elevated="#2f2935",
        panel="#1e1a22", input_surface="#1b171e", selected="#3a3241",
        # 2026-10-14: border_strong #4a4152 -> #574c60 so input edges read (1.8 -> 2.2:1).
        timeline="#17131a", media="#0e0c10", border="#342d3a", border_strong="#574c60",
        text="#f4eee9", text_secondary="#d0c6cd", text_muted="#a69ba6",
        accent="#b34470", accent_hover="#c1517d", accent_pressed="#9b3a61", accent_soft="#3a2231",
        success="#69cf9b", warning="#e9b65b", warning_soft="#3a2f1c",
        danger="#f3866b", danger_soft="#3d2425", shell="#141117", shell_border="#2a2430",
        focus="#86b4f7", disabled="#716779",
    ),
    "warm": ThemeDefinition(
        key="warm", label="Cream Garden",
        labels={"zh": "奶油花园", "zh-Hant": "奶油花園", "en": "Cream Garden", "ja": "クリームガーデン", "ko": "크림 가든"},
        app_background=BACKGROUND, surface=SURFACE, surface_elevated=SURFACE_RAISED,
        panel=SURFACE_MUTED, input_surface="#f3eee5", selected=GREEN_SOFT,
        # 2026-10-14 readability: input edge, warning text and focus ring were
        # 1.5 / 3.2 / 2.0:1 on the cards; now 2.2 / 4.6 / 3.2:1.
        timeline="#f5f0e7", media="#30332f", border=BORDER, border_strong="#b9a78f",
        text=INK, text_secondary=INK_SOFT, text_muted=MUTED, accent=GREEN, accent_hover=GREEN_HOVER,
        accent_pressed=GREEN_PRESSED, accent_soft=GREEN_SUBTLE, success=GREEN,
        warning="#93641f", warning_soft=AMBER_SOFT, danger=CORAL, danger_soft="#f7e8e3", shell=SURFACE, shell_border=BORDER,
        focus="#6f9a76", disabled="#99958d",
    ),
    # 五十二轮重设（用户："暗色被强行反色的感觉，不一定继续紫色"）：key 保留
    # "plum" 以兼容已保存的 settings，调色板本体改为与 warm 同源的暗色伙伴——
    # 暖夜炭底 + 奶油文字 + 低饱和绿功能色，surface 层级/border 对比按暗色
    # 独立设计，不再复用亮色体系的映射结果。
    "plum": ThemeDefinition(
        key="plum", label="Ember Night",
        labels={"zh": "炉火暖夜", "zh-Hant": "爐火暖夜", "en": "Ember Night", "ja": "エンバーナイト", "ko": "엠버 나이트"},
        app_background="#262420", surface="#302c26", surface_elevated="#3a352d",
        panel="#2b2722", input_surface="#201d19", selected="#3b4634",
        timeline="#242220", media="#161411", border="#46413a", border_strong="#5b5548",
        text="#f1ebdc", text_secondary="#d7cfba", text_muted="#a59d89", accent="#8fb98c", accent_hover="#a0c99d",
        accent_pressed="#7ba67a", accent_soft="#37402e", success="#8fb98c",
        warning="#c9a25e", warning_soft="#3f3828", danger="#c98573", danger_soft="#45322c", shell="#211f1b", shell_border="#46413a",
        focus="#9db892", disabled="#857e6e",
    ),
    "lavender": ThemeDefinition(
        key="lavender", label="Lavender Dusk",
        labels={"zh": "薰衣暮色", "zh-Hant": "薰衣暮色", "en": "Lavender Dusk", "ja": "ラベンダー・ダスク", "ko": "라벤더 더스크"},
        app_background="#29263a", surface="#49445f", surface_elevated="#5a5474",
        panel="#353149", input_surface="#514b6a", selected="#716b91",
        timeline="#302d43", media="#171725", border="#817aa4", border_strong="#9b93bf",
        text="#f9f7ff", text_secondary="#e4e0f0", text_muted="#d0cbe2", accent="#c19bea", accent_hover="#d0b2f4",
        accent_pressed="#a97fda", accent_soft="#625a80", success="#96d0b3",
        warning="#efc47d", warning_soft="#6a5e65", danger="#ee8a86", danger_soft="#6a5267", shell="#29263a", shell_border="#817aa4",
        focus="#9b93bf", disabled="#8d88a6",
    ),
    "slate": ThemeDefinition(
        key="slate", label="Slate Editorial",
        labels={"zh": "岩灰编辑部", "zh-Hant": "岩灰編輯部", "en": "Slate Editorial", "ja": "スレート・エディトリアル", "ko": "슬레이트 에디토리얼"},
        app_background="#20272b", surface="#303b41", surface_elevated="#3c4a51",
        panel="#273238", input_surface="#37454c", selected="#4c626c",
        timeline="#202a2f", media="#10171a", border="#5d747d", border_strong="#76909a",
        text="#f2f5f4", text_secondary="#ccd7d9", text_muted="#b8c6c8", accent="#e39a73", accent_hover="#f0ae8c",
        accent_pressed="#c77c58", accent_soft="#485b62", success="#8bc6a3",
        warning="#e5c37b", warning_soft="#54564d", danger="#ed8a7e", danger_soft="#564b4d", shell="#20272b", shell_border="#5d747d",
        focus="#76909a", disabled="#7d929b",
    ),
    # 2026-10-14 expansion (user: "看膩了"; white tech and yellow/black first).
    # Every new palette meets: body text >= 7:1, secondary >= 6:1, muted
    # >= 4.5:1, button text >= 4.5:1, status text on its own wash >= 4.5:1,
    # input edge >= 2.2:1 (tests/test_theme_catalog.py holds the bar).
    "frost": ThemeDefinition(  # white tech: silver layers, ice-blue actions
        key="frost", label="Frost Engine",
        labels={"zh": "霜白引擎", "zh-Hant": "霜白引擎", "en": "Frost Engine", "ja": "フロスト・エンジン", "ko": "프로스트 엔진"},
        app_background="#e7ebf0", surface="#f8fafc", surface_elevated="#ffffff",
        panel="#eef1f5", input_surface="#f1f4f8", selected="#dde6f2",
        timeline="#edf0f4", media="#161b22", border="#cfd7e1", border_strong="#95a3b4",
        text="#111821", text_secondary="#344050", text_muted="#556172",
        accent="#1a64d6", accent_hover="#1557bd", accent_pressed="#114aa3", accent_soft="#e1ebfa",
        success="#0d7343", warning="#9a5a00", warning_soft="#fbefd9",
        danger="#c0362f", danger_soft="#fbe4e1", shell="#f4f6f9", shell_border="#cfd7e1",
        focus="#1f7fe0", disabled="#97a2b0",
    ),
    "obsidian": ThemeDefinition(  # yellow/black: layered graphite, signal yellow only for key actions
        key="obsidian", label="Obsidian Signal",
        labels={"zh": "黑曜警戒", "zh-Hant": "黑曜警戒", "en": "Obsidian Signal", "ja": "オブシディアン・シグナル", "ko": "옵시디언 시그널"},
        app_background="#111214", surface="#1d1f23", surface_elevated="#272a2f",
        panel="#16171a", input_surface="#131417", selected="#32363c",
        timeline="#101113", media="#08090a", border="#34383f", border_strong="#525861",
        text="#f4f2eb", text_secondary="#cdcac0", text_muted="#a19e95",
        accent="#f2c230", accent_hover="#ffd24f", accent_pressed="#d8a91a", accent_soft="#3a3215",
        success="#62d394", warning="#ff9f45", warning_soft="#3d2a16",
        danger="#ff6e61", danger_soft="#421f1c", shell="#0b0c0d", shell_border="#26292e",
        focus="#ffd84f", disabled="#62656b",
    ),
    "midnight": ThemeDefinition(  # deep navy workbench, sky blue + ice cyan
        key="midnight", label="Night Blueprint",
        labels={"zh": "夜航蓝图", "zh-Hant": "夜航藍圖", "en": "Night Blueprint", "ja": "ナイト・ブループリント", "ko": "나이트 블루프린트"},
        app_background="#0e1525", surface="#172136", surface_elevated="#1f2b44",
        panel="#121a2c", input_surface="#0f1729", selected="#26375a",
        timeline="#0d1422", media="#060a13", border="#28385a", border_strong="#465b87",
        text="#e8eefb", text_secondary="#b8c4dd", text_muted="#8f9cbc",
        accent="#5c9dff", accent_hover="#79b0ff", accent_pressed="#4787ea", accent_soft="#1c3157",
        success="#4fd1a4", warning="#f1c26b", warning_soft="#383120",
        danger="#ff7d7d", danger_soft="#3c2131", shell="#0a1020", shell_border="#202d48",
        focus="#7dd3fc", disabled="#56627f",
    ),
    "verdant": ThemeDefinition(  # ink green, mineral teal: a quiet pro tool
        key="verdant", label="Teal Workshop",
        labels={"zh": "青岚工坊", "zh-Hant": "青嵐工坊", "en": "Teal Workshop", "ja": "ティール・ワークショップ", "ko": "틸 워크숍"},
        app_background="#101917", surface="#192522", surface_elevated="#21302c",
        panel="#141e1b", input_surface="#111a18", selected="#293c37",
        timeline="#0f1715", media="#060b0a", border="#2a3c37", border_strong="#45615a",
        text="#e7f1ed", text_secondary="#b5cac2", text_muted="#8ba69d",
        accent="#3cc9a7", accent_hover="#5bd7b9", accent_pressed="#2fae90", accent_soft="#1c3a33",
        success="#8bd98f", warning="#e8c06a", warning_soft="#37331f",
        danger="#f28b7f", danger_soft="#3d2623", shell="#0b1311", shell_border="#22322e",
        focus="#7cc4ea", disabled="#5a706a",
    ),
    "neon": ThemeDefinition(  # violet black, electric violet + neon cyan focus
        key="neon", label="Violet Core",
        labels={"zh": "紫电核心", "zh-Hant": "紫電核心", "en": "Violet Core", "ja": "バイオレット・コア", "ko": "바이올렛 코어"},
        app_background="#0d0a14", surface="#1c162b", surface_elevated="#282040",
        panel="#140f20", input_surface="#110d1b", selected="#33294f",
        timeline="#0e0b16", media="#06040b", border="#372c53", border_strong="#58497d",
        text="#f1ecff", text_secondary="#c6bce2", text_muted="#9c91bb",
        accent="#a57cff", accent_hover="#b794ff", accent_pressed="#8e63f2", accent_soft="#2e2152",
        success="#3fdcae", warning="#ffc56b", warning_soft="#392c1e",
        danger="#ff6f93", danger_soft="#3d1a2b", shell="#0a0811", shell_border="#241d38",
        focus="#4fd8ff", disabled="#5e5579",
    ),
    "cinema": ThemeDefinition(  # wine-brown darkroom, copper actions
        key="cinema", label="Darkroom Grade",
        labels={"zh": "暗房调色", "zh-Hant": "暗房調色", "en": "Darkroom Grade", "ja": "ダークルーム・グレード", "ko": "다크룸 그레이드"},
        app_background="#150f10", surface="#241b1c", surface_elevated="#2f2425",
        panel="#1b1415", input_surface="#171112", selected="#3f2e2f",
        timeline="#140f10", media="#090606", border="#413132", border_strong="#684f50",
        text="#f6ece7", text_secondary="#d5c3bc", text_muted="#ab968f",
        accent="#e0875a", accent_hover="#eb9c73", accent_pressed="#c8734a", accent_soft="#3e2720",
        success="#7fcb9b", warning="#e9c46a", warning_soft="#3a3020",
        danger="#ff6f6f", danger_soft="#431d20", shell="#100b0c", shell_border="#2e2223",
        focus="#8fb4ea", disabled="#6d595a",
    ),
    "graphite": ThemeDefinition(  # neutral minimal editor, monochrome actions, one blue focus
        key="graphite", label="Graphite Minimal",
        labels={"zh": "石墨极简", "zh-Hant": "石墨極簡", "en": "Graphite Minimal", "ja": "グラファイト・ミニマル", "ko": "그래파이트 미니멀"},
        app_background="#1a1a1b", surface="#242426", surface_elevated="#2d2d30",
        panel="#1e1e20", input_surface="#1b1b1d", selected="#3a3a3e",
        timeline="#18181a", media="#0c0c0d", border="#3b3b3f", border_strong="#5c5c61",
        text="#ededed", text_secondary="#c4c4c6", text_muted="#9a9a9e",
        accent="#e8e8ea", accent_hover="#ffffff", accent_pressed="#cacacd", accent_soft="#3a3a3e",
        success="#80d09b", warning="#e4be6c", warning_soft="#37321f",
        danger="#f2837a", danger_soft="#3d2523", shell="#141415", shell_border="#2b2b2e",
        focus="#8ab4f8", disabled="#646468",
    ),
    "sand": ThemeDefinition(  # warm sand paper, terracotta: soft creative light
        key="sand", label="Sandstone Atelier",
        labels={"zh": "砂岩画室", "zh-Hant": "砂岩畫室", "en": "Sandstone Atelier", "ja": "サンドストーン・アトリエ", "ko": "샌드스톤 아틀리에"},
        app_background="#ebe4d9", surface="#f7f2ea", surface_elevated="#fcf9f4",
        panel="#f0eae0", input_surface="#f2ebe1", selected="#e8dccb",
        timeline="#eee7dc", media="#28221d", border="#dacebd", border_strong="#a99984",
        text="#271f18", text_secondary="#4a3f35", text_muted="#695d50",
        accent="#a94e2c", accent_hover="#984526", accent_pressed="#843b20", accent_soft="#f3e1d6",
        success="#386b3c", warning="#8c5e0c", warning_soft="#f4e6c8",
        danger="#ad3434", danger_soft="#f5dfda", shell="#f3ede4", shell_border="#d6c9b7",
        focus="#3a6fb2", disabled="#a39686",
    ),
    "paper": ThemeDefinition(  # high-legibility light: clean paper, ink buttons, crisp edges
        key="paper", label="Ink on Paper",
        labels={"zh": "白纸黑字", "zh-Hant": "白紙黑字", "en": "Ink on Paper", "ja": "白紙に墨", "ko": "흰 종이 검은 글씨"},
        app_background="#f1f1ee", surface="#fafaf8", surface_elevated="#ffffff",
        panel="#f6f6f3", input_surface="#ffffff", selected="#e5e5e1",
        timeline="#f3f3f0", media="#161616", border="#bdbdb8", border_strong="#6f6f6a",
        text="#0a0a0a", text_secondary="#262626", text_muted="#474744",
        accent="#161616", accent_hover="#333333", accent_pressed="#000000", accent_soft="#e8e8e4",
        success="#0b6e36", warning="#7d4b00", warning_soft="#f9ebcd",
        danger="#a91f17", danger_soft="#f9e0dc", shell="#ffffff", shell_border="#bdbdb8",
        focus="#0a5bd3", disabled="#85857f",
    ),
    "contrast": ThemeDefinition(  # high-contrast dark: black, white text, bright edges, yellow focus
        key="contrast", label="Polar Night Contrast",
        labels={"zh": "极夜高对比", "zh-Hant": "極夜高對比", "en": "Polar Night Contrast", "ja": "極夜ハイコントラスト", "ko": "극야 고대비"},
        app_background="#050505", surface="#161616", surface_elevated="#242424",
        panel="#0b0b0b", input_surface="#000000", selected="#2e2e2e",
        timeline="#080808", media="#000000", border="#6a6a6a", border_strong="#a8a8a8",
        text="#ffffff", text_secondary="#ececec", text_muted="#cfcfcf",
        accent="#3cd0ff", accent_hover="#7fe0ff", accent_pressed="#16b6e8", accent_soft="#0b3341",
        success="#52f29e", warning="#ffd23f", warning_soft="#3a3000",
        danger="#ff6b6b", danger_soft="#450d0d", shell="#000000", shell_border="#7a7a7a",
        focus="#ffd23f", disabled="#8e8e8e",
    ),
}

DEFAULT_THEME_KEY = "grape"


@dataclass(frozen=True)
class ThemeTraits:
    """What a theme says beyond its 29 tokens (2026-10-14).

    Every field is optional; empty means "derive from the tokens" (see the
    matching ThemeDefinition property).  ``studio_paper`` is the home Studio
    entrance card: paper, paper hover, motif edge, ink, ink secondary.
    """

    family: str = ""
    mood: dict[str, str] = field(default_factory=dict)
    text_on_accent: str = ""
    accent_text: str = ""
    info: str = ""
    overlay_scrim: str = ""
    role_colors: dict[str, str] = field(default_factory=dict)
    role_wash: tuple[float, float, float] | tuple = ()
    zone_colors: dict[str, str] = field(default_factory=dict)
    studio_paper: tuple[str, str, str, str, str] | tuple = ()
    on_vivid: str = ""
    log_background: str = ""
    log_text: str = ""
    # Share of the accent in accent_tint (selected nav / checked tool). Very
    # light or very dark accents (yellow, white, ink) need less to stay clean.
    tint_amount: float = 0.0


_DEFAULT_TRAITS = ThemeTraits()

# Picker groups, in display order.  Paper (high-legibility light) sits with
# the high-contrast theme so both accessibility choices are found together.
THEME_FAMILIES = (
    ("light", {"zh": "浅色", "zh-Hant": "淺色", "en": "Light", "ja": "ライト", "ko": "라이트"}),
    ("dark", {"zh": "深色", "zh-Hant": "深色", "en": "Dark", "ja": "ダーク", "ko": "다크"}),
    ("contrast", {"zh": "高对比与高可读", "zh-Hant": "高對比與高可讀", "en": "High contrast & legibility",
                  "ja": "ハイコントラスト・高可読", "ko": "고대비 · 고가독성"}),
)
THEME_ORDER = ("frost", "sand", "warm", "grape", "obsidian", "midnight", "verdant", "neon", "cinema",
               "graphite", "plum", "lavender", "slate", "paper", "contrast")

THEME_TRAITS: dict[str, ThemeTraits] = {
    # Existing five: the values their key branches used to return, unchanged.
    "grape": ThemeTraits(
        mood={"zh": "深葡萄紫底，莓果色点缀", "zh-Hant": "深葡萄紫底，莓果色點綴",
              "en": "Deep grape graphite with a berry accent", "ja": "深いグレープに、ベリー色のアクセント", "ko": "깊은 포도빛 바탕에 베리색 포인트"},
        text_on_accent="#fff6f9", accent_text="#ec8db0", overlay_scrim="rgba(0, 0, 0, 140)",
        role_colors={"primary": "#a48ad9", "timeline": "#d6957c", "review": "#c48cb4"},
        log_text="#e8e3de",
    ),
    "warm": ThemeTraits(
        mood={"zh": "暖奶油纸面，森林绿操作", "zh-Hant": "暖奶油紙面，森林綠操作",
              "en": "Warm cream paper with forest-green actions", "ja": "温かいクリーム地に、フォレストグリーン", "ko": "따뜻한 크림색 바탕에 포레스트 그린"},
        text_on_accent="#ffffff", accent_text="#4f8557", overlay_scrim="rgba(41, 42, 39, 92)",
        role_colors={"primary": "#4a6fc2", "timeline": "#b44d7a", "review": "#a8841c"},
        zone_colors={"studio": "#b25a80", "ai": "#9a5aa6", "content": "#557e8e"},
        studio_paper=("#F2E3C4", "#F8EBD2", "#BE9A60", "#46351F", "#78603F"),
        log_background="#2b2d29", log_text="#ecebe4",
    ),
    "plum": ThemeTraits(
        mood={"zh": "暖炭灰底，奶油字与鼠尾草绿", "zh-Hant": "暖炭灰底，奶油字與鼠尾草綠",
              "en": "Warm charcoal, cream text and sage green", "ja": "暖かいチャコールに、クリームとセージ", "ko": "따뜻한 차콜 바탕, 크림색 글자와 세이지 그린"},
        text_on_accent="#262420", accent_text="#a9d1a6", overlay_scrim="rgba(16, 15, 12, 160)",
        role_colors={"primary": "#bc8fb0", "timeline": "#86b3b4", "review": "#d0a07c"},
        zone_colors={"studio": "#cc7f9e", "ai": "#b585c4", "content": "#8aa5b8"},
        studio_paper=("#554537", "#66523F", "#B89970", "#FFF0D1", "#E0C8A5"),
        log_text="#e8e3de",
    ),
    "lavender": ThemeTraits(
        mood={"zh": "柔和紫灰，层次明亮", "zh-Hant": "柔和紫灰，層次明亮",
              "en": "Soft violet-grey with bright layers", "ja": "やわらかな紫グレー、明るい階層", "ko": "부드러운 보랏빛 회색, 밝은 레이어"},
        text_on_accent="#29263a", accent_text="#dcc3f7", overlay_scrim="rgba(15, 14, 28, 150)",
        role_colors={"primary": "#93bbe4", "timeline": "#e3a68c", "review": "#d9c78f"},
        zone_colors={"studio": "#cc7f9e", "ai": "#b585c4", "content": "#8aa5b8"},
        studio_paper=("#494361", "#5A5274", "#A79BC4", "#FAF3FF", "#D9CEE9"),
        log_text="#e8e3de",
    ),
    "slate": ThemeTraits(
        mood={"zh": "蓝灰岩面，杏橙强调", "zh-Hant": "藍灰岩面，杏橙強調",
              "en": "Blue-grey slate with an apricot accent", "ja": "青みのスレートに、アプリコット", "ko": "청회색 슬레이트에 살구색 포인트"},
        text_on_accent="#20272b", accent_text="#f2b896", overlay_scrim="rgba(9, 14, 16, 150)",
        role_colors={"primary": "#86bfb7", "timeline": "#d3a2b9", "review": "#b5a7da"},
        zone_colors={"studio": "#cc7f9e", "ai": "#b585c4", "content": "#8aa5b8"},
        studio_paper=("#3B5558", "#49676A", "#8CB7B5", "#F0FCF7", "#C5DEDA"),
        log_text="#e8e3de",
    ),
    # 2026-10-14 new themes.
    "frost": ThemeTraits(
        mood={"zh": "银白冷灰分层，冰蓝操作，精密工具感", "zh-Hant": "銀白冷灰分層，冰藍操作，精密工具感",
              "en": "Silver-white layers, ice-blue actions, a precision tool",
              "ja": "シルバーホワイトの階層とアイスブルー、精密ツールの質感", "ko": "은백색 레이어와 아이스 블루, 정밀 도구 느낌"},
        text_on_accent="#ffffff",
        role_colors={"primary": "#2f6fd0", "timeline": "#0f8584", "review": "#7657c9"},
        zone_colors={"studio": "#3a6cc8", "ai": "#7656c4", "content": "#2b8494"},
        studio_paper=("#e3ecf8", "#d8e5f6", "#95a3b4", "#111821", "#344050"),
        log_background="#161b22", log_text="#dfe6ee",
    ),
    "obsidian": ThemeTraits(
        mood={"zh": "分层石墨黑，信号黄只给关键操作", "zh-Hant": "分層石墨黑，信號黃只給關鍵操作",
              "en": "Layered graphite black; signal yellow only where it matters",
              "ja": "階層のあるグラファイトブラック、要所だけシグナルイエロー", "ko": "레이어드 그래파이트 블랙, 핵심 버튼에만 시그널 옐로"},
        text_on_accent="#16140c", info="#6cc4ff", tint_amount=0.13,
        role_colors={"primary": "#d9b45a", "timeline": "#6fb3c9", "review": "#c98f6d"},
        zone_colors={"studio": "#d4a73c", "ai": "#9d8fd0", "content": "#7aa7b8"},
        studio_paper=("#25282c", "#2c3035", "#8a7430", "#f4f2eb", "#cdcac0"),
        log_text="#e9e6dc",
    ),
    "midnight": ThemeTraits(
        mood={"zh": "深海军蓝工作台，天蓝与冰青点亮", "zh-Hant": "深海軍藍工作台，天藍與冰青點亮",
              "en": "Deep navy workbench lit by sky blue and ice cyan",
              "ja": "深いネイビーの作業台に、スカイブルーとアイスシアン", "ko": "짙은 네이비 작업 공간에 스카이 블루와 아이스 시안"},
        text_on_accent="#06101f",
        role_colors={"primary": "#7aa8ff", "timeline": "#5fc8c0", "review": "#b49cf0"},
        zone_colors={"studio": "#6f9cf0", "ai": "#a690e8", "content": "#62b8c8"},
        studio_paper=("#1b2a48", "#22345a", "#4f6fa8", "#e8eefb", "#b8c4dd"),
        log_text="#dbe4f5",
    ),
    "verdant": ThemeTraits(
        mood={"zh": "墨绿底，矿物青绿操作，安静的专业工具", "zh-Hant": "墨綠底，礦物青綠操作，安靜的專業工具",
              "en": "Ink green with mineral-teal actions; a quiet pro tool",
              "ja": "墨緑の地にミネラルティール、静かなプロツール", "ko": "짙은 녹색 바탕에 미네랄 틸, 차분한 전문 도구"},
        text_on_accent="#05201a",
        role_colors={"primary": "#5fc7a8", "timeline": "#d8b26a", "review": "#8fb8e0"},
        zone_colors={"studio": "#4fbf9f", "ai": "#9ab0dc", "content": "#c8b070"},
        studio_paper=("#1c332d", "#223d36", "#3f8f7a", "#e7f1ed", "#b5cac2"),
        log_text="#dcebe5",
    ),
    "neon": ThemeTraits(
        mood={"zh": "紫黑底，电光紫操作，霓虹青焦点", "zh-Hant": "紫黑底，電光紫操作，霓虹青焦點",
              "en": "Violet-black, electric-violet actions, neon-cyan focus",
              "ja": "紫がかった黒にエレクトリックバイオレット、ネオンシアンのフォーカス", "ko": "보랏빛 검정에 일렉트릭 바이올렛, 네온 시안 포커스"},
        text_on_accent="#12092a",
        role_colors={"primary": "#a98cf0", "timeline": "#4fc8e6", "review": "#e58ac4"},
        zone_colors={"studio": "#d27fd0", "ai": "#9f84f0", "content": "#5cbfe0"},
        studio_paper=("#271d42", "#2f2350", "#6f56b0", "#f1ecff", "#c6bce2"),
        log_text="#e6e0f7",
    ),
    "cinema": ThemeTraits(
        mood={"zh": "酒红棕暗房，铜橙操作，像电影调色台", "zh-Hant": "酒紅棕暗房，銅橙操作，像電影調色台",
              "en": "Wine-brown darkroom with copper actions, like a grading suite",
              "ja": "ワインブラウンの暗室に銅色、グレーディング卓のように", "ko": "와인 브라운 암실에 구리색, 색보정 데스크처럼"},
        text_on_accent="#1f0f09",
        role_colors={"primary": "#d9a06c", "timeline": "#c9787e", "review": "#9fb0d8"},
        zone_colors={"studio": "#d4806e", "ai": "#c28fb5", "content": "#8fb0c4"},
        studio_paper=("#3a2522", "#452c28", "#9a6650", "#f6ece7", "#d5c3bc"),
        log_text="#efe2dc",
    ),
    "graphite": ThemeTraits(
        mood={"zh": "中性石墨灰，黑白操作，只留一抹蓝做焦点", "zh-Hant": "中性石墨灰，黑白操作，只留一抹藍做焦點",
              "en": "Neutral graphite, monochrome actions, one blue for focus",
              "ja": "ニュートラルなグラファイト、モノクロ操作、フォーカスだけ青", "ko": "중립적인 그래파이트, 흑백 버튼, 포커스만 파란색"},
        text_on_accent="#18181a", accent_text="#e8e8ea", tint_amount=0.14,
        role_colors={"primary": "#9fb4d1", "timeline": "#c9b08f", "review": "#b6a3c9"},
        zone_colors={"studio": "#b8a2b4", "ai": "#a3a6cc", "content": "#93b2b8"},
        studio_paper=("#303033", "#38383c", "#6a6a70", "#ededed", "#c4c4c6"),
        log_text="#e4e4e4",
    ),
    "sand": ThemeTraits(
        mood={"zh": "暖灰砂色纸面，陶土红操作，柔和不刺眼", "zh-Hant": "暖灰砂色紙面，陶土紅操作，柔和不刺眼",
              "en": "Warm sand paper with terracotta actions, easy on the eyes",
              "ja": "温かな砂色の紙面にテラコッタ、目にやさしい", "ko": "따뜻한 모래색 바탕에 테라코타, 눈이 편안함"},
        text_on_accent="#ffffff",
        role_colors={"primary": "#4b6fa8", "timeline": "#9a5a3c", "review": "#7a6a2a"},
        zone_colors={"studio": "#a8573a", "ai": "#8a5f8f", "content": "#4f7c82"},
        studio_paper=("#f0dfcf", "#ead4c0", "#b9876a", "#3a2416", "#6a4a36"),
        log_background="#2b2621", log_text="#ece4d8",
    ),
    "paper": ThemeTraits(
        family="contrast",
        mood={"zh": "高可读浅色：纯净纸面，墨黑按钮，清晰边线", "zh-Hant": "高可讀淺色：純淨紙面，墨黑按鈕，清晰邊線",
              "en": "High-legibility light: clean paper, ink buttons, crisp edges",
              "ja": "高可読ライト：白い紙面、墨色ボタン、くっきりした境界", "ko": "고가독성 라이트: 흰 종이 바탕, 먹색 버튼, 또렷한 테두리"},
        text_on_accent="#ffffff", tint_amount=0.12,
        role_colors={"primary": "#2c5aa8", "timeline": "#8a3f62", "review": "#6b5a14"},
        zone_colors={"studio": "#8a3f62", "ai": "#5f4a96", "content": "#2c6a78"},
        studio_paper=("#f1f1ee", "#e8e8e4", "#6f6f6a", "#0a0a0a", "#262626"),
        log_background="#161616", log_text="#f0f0ee",
    ),
    "contrast": ThemeTraits(
        family="contrast",
        mood={"zh": "高对比深色：黑底白字，亮边框，黄色焦点", "zh-Hant": "高對比深色：黑底白字，亮邊框，黃色焦點",
              "en": "High-contrast dark: black, white text, bright edges, yellow focus",
              "ja": "ハイコントラスト・ダーク：黒地に白文字、明るい境界、黄色フォーカス", "ko": "고대비 다크: 검은 바탕에 흰 글자, 밝은 테두리, 노란색 포커스"},
        text_on_accent="#000000", info="#3cd0ff", overlay_scrim="rgba(0, 0, 0, 190)",
        role_colors={"primary": "#3cd0ff", "timeline": "#ffb02e", "review": "#ff7ad9"},
        zone_colors={"studio": "#ff8ad8", "ai": "#b4a7ff", "content": "#5fd8ff"},
        studio_paper=("#1f1f1f", "#2a2a2a", "#a8a8a8", "#ffffff", "#ececec"),
        log_background="#000000", log_text="#ffffff",
    ),
}


def ordered_themes() -> tuple[ThemeDefinition, ...]:
    """Every theme in picker order (THEME_ORDER first, then any others)."""
    ordered = [THEMES[key] for key in THEME_ORDER if key in THEMES]
    return tuple(ordered + [theme for key, theme in THEMES.items() if key not in THEME_ORDER])


def _hex_channels(value: str) -> tuple[int, int, int]:
    raw = str(value or "").lstrip("#")
    if len(raw) != 6:
        return (0, 0, 0)
    return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))


def blend_hex(base: str, overlay: str, amount: float) -> str:
    """Mix ``overlay`` into ``base`` (0..1) in sRGB; used for soft state washes."""
    def channels(value):
        raw = str(value or "").lstrip("#")
        if len(raw) != 6:
            return (0, 0, 0)
        return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))
    first, second = channels(base), channels(overlay)
    amount = max(0.0, min(1.0, float(amount)))
    mixed = (round(a + (b - a) * amount) for a, b in zip(first, second))
    return "#" + "".join(f"{value:02x}" for value in mixed)


def hex_luminance(value: str) -> float:
    raw = str(value or "").lstrip("#")
    if len(raw) != 6:
        return 0.0
    red, green, blue = (int(raw[0:2], 16) / 255.0, int(raw[2:4], 16) / 255.0, int(raw[4:6], 16) / 255.0)

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def contrast_ratio(first: str, second: str) -> float:
    left, right = hex_luminance(first), hex_luminance(second)
    lighter, darker = max(left, right), min(left, right)
    return (lighter + 0.05) / (darker + 0.05)


def theme_definition(key: str | None = None) -> ThemeDefinition:
    return THEMES.get(str(key or DEFAULT_THEME_KEY), THEMES[DEFAULT_THEME_KEY])


WORKSHOP_TOKENS = {
    "page": BACKGROUND,
    "sidebar": SURFACE_MUTED,
    "content": SURFACE,
    "surface": SURFACE_RAISED,
    "detail": "#faf5ea",
    "border": BORDER,
    "border_warm": BORDER_STRONG,
    "green": GREEN,
    "green_hover": GREEN_HOVER,
    "green_soft": GREEN_SOFT,
    "green_subtle": GREEN_SUBTLE,
    "ink": INK,
    "muted": MUTED,
    "icon": "#858177",
    "score_track": "#e8e2d8",
    "score_low": CORAL,
    "score_low_2": "#c77a6c",
    "score_mid": "#be914b",
    "score_high": "#64875b",
    "score_top": "#587e52",
}


def theme_display_label(theme: ThemeDefinition, language: str | None = None) -> str:
    """Localized theme name; the stable ``label`` stays as the English fallback."""
    if language is None:
        from .i18n import current_language

        language = current_language()
    language = str(language)
    if language in theme.labels:
        return theme.labels[language]
    if language == "zh-Hant" and "zh" in theme.labels:
        from .i18n import ui_literal
        return ui_literal(theme.labels["zh"], language)
    return theme.label


def theme_mood(theme: ThemeDefinition, language: str | None = None) -> str:
    """Localized one-line style description shown under the theme name."""
    if language is None:
        from .i18n import current_language

        language = current_language()
    mood = theme.mood
    return mood.get(str(language)) or mood.get("en") or mood.get("zh", "")


def theme_family_label(family: str, language: str | None = None) -> str:
    if language is None:
        from .i18n import current_language

        language = current_language()
    labels = dict(THEME_FAMILIES).get(family, {})
    return labels.get(str(language)) or labels.get("en", family)
