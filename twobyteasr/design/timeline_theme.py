"""Tokenized color palettes for the Studio Timeline's custom painting.

The WaveformTimeline paints everything with QPainter, so it cannot follow
QSS theming. This module gives every painted surface an explicit token per
theme (warm cream / plum + coral / lavender workspace / slate editorial).

2026-10-14: the original five keep their hand-tuned palettes; every other
theme gets one derived from its ui_theme tokens (derive_timeline_palette)
plus a small per-theme tuning (playhead, waveform, speaker hues), so adding a
theme never falls back to the light warm palette on a dark window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor


def mix(first: str | QColor, second: str | QColor, ratio: float) -> QColor:
    """Linear RGB blend: ratio 0 -> first, 1 -> second."""
    a = QColor(first) if isinstance(first, str) else QColor(first)
    b = QColor(second) if isinstance(second, str) else QColor(second)
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(a.red() + (b.red() - a.red()) * ratio),
        round(a.green() + (b.green() - a.green()) * ratio),
        round(a.blue() + (b.blue() - a.blue()) * ratio),
    )


def rgba_color(token: str) -> QColor:
    """Parse '#rrggbb' or 'rgba(r,g,b,a-int)' tokens into QColor."""
    if token.startswith("rgba("):
        r, g, b, a = (int(part.strip()) for part in token[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(token)


@dataclass(frozen=True)
class TimelinePalette:
    key: str
    dark: bool
    background: str
    header: str
    ruler: str
    grid_major: str
    grid_minor: str
    track_background: str
    track_alternate: str
    track_header: str
    playhead: str
    playhead_label_text: str
    time_label: str
    clip_text: str
    clip_selected_border: str
    clip_selected_glow: str
    clip_multi_border: str
    clip_border_shade: float          # clip border = speaker mixed toward this shade
    clip_fill_mix: float              # 0 = pure speaker color, 1 = track background
    clip_fill_lighten: int            # extra lighter() on the mixed fill
    handle_dot_fill: str
    handle_dot_border: str
    waveform: str
    waveform_edge: str
    waveform_center: str
    waveform_background: str
    waveform_header_text: str
    waveform_db_text: str
    header_letter: str
    header_name: str
    header_icon: str
    header_hover: str
    translation_clip: str
    translation_clip_border: str
    translation_clip_text: str
    translation_dot: str
    selection_rect: str
    selection_fill: str
    inline_editor_bg: str
    inline_editor_border: str
    inline_editor_text: str
    speaker_accents: tuple[str, ...] = field(default_factory=tuple)
    # Main video lane hue; empty keeps the historical clip_selected_border.
    video_accent: str = ""
    video_clip: str = ""
    video_clip_border: str = ""

    def clip_fill(self, speaker: QColor, selected: bool = False) -> QColor:
        fill = mix(speaker, self.track_background, self.clip_fill_mix).lighter(
            self.clip_fill_lighten + (8 if selected else 0)
        )
        return fill

    def clip_border(self, speaker: QColor) -> QColor:
        border = mix(speaker, QColor(self.clip_selected_border), self.clip_border_shade)
        return border


WARM_TIMELINE = TimelinePalette(
    key="warm",
    dark=False,
    background="#f7f3eb",
    header="#f5f0e7",
    ruler="#d2c3ae",
    grid_major="#c9bdab",
    grid_minor="#baae9c",
    track_background="#fffefa",
    track_alternate="#fbf8f2",
    track_header="#f5f0e7",
    playhead="#cf4b43",
    playhead_label_text="#ffffff",
    time_label="#4e5a52",
    clip_text="#26302a",
    clip_selected_border="#1f6a3d",
    clip_selected_glow="rgba(226,244,226,235)",
    clip_multi_border="#78a882",
    clip_border_shade=0.0,
    clip_fill_mix=0.0,
    clip_fill_lighten=135,
    handle_dot_fill="#fffdf9",
    handle_dot_border="#3d8658",
    waveform="rgba(62,94,68,165)",
    waveform_edge="#385640",
    waveform_center="#9e9a90",
    waveform_background="#eee5d7",
    waveform_header_text="#313733",
    waveform_db_text="#74766f",
    header_letter="#70766f",
    header_name="#29302c",
    header_icon="#667069",
    header_hover="#e3e5de",
    translation_clip="#f1d6b8",
    translation_clip_border="#c58b55",
    translation_clip_text="#554333",
    translation_dot="#c68a52",
    selection_rect="#4f8a61",
    selection_fill="rgba(105,157,112,38)",
    inline_editor_bg="#fffefa",
    inline_editor_border="#3d8658",
    inline_editor_text="#1f2923",
    speaker_accents=("#638d85", "#9a7f62", "#687f9c", "#7e8363", "#906c76"),
)

# 五十二轮：随 ui_theme 的 plum→暖夜炭重设同步（key 保留）。播放头保持
# 暖珊瑚红（NLE 惯例：与绿色字幕块/选中色区分），选中/描边走低饱和绿。
PLUM_TIMELINE = TimelinePalette(
    key="plum",
    dark=True,
    background="#242220",
    header="#2b2722",
    ruler="#211f1c",
    grid_major="#3a3630",
    grid_minor="#332f2a",
    track_background="#2c2925",
    track_alternate="#302c27",
    track_header="#2b2722",
    playhead="#e88a6a",
    playhead_label_text="#241a14",
    time_label="#b3ab96",
    clip_text="#f1ebdc",
    clip_selected_border="#8fb98c",
    clip_selected_glow="rgba(143,185,140,60)",
    clip_multi_border="#b9c7a4",
    clip_border_shade=0.25,
    clip_fill_mix=0.62,
    clip_fill_lighten=104,
    handle_dot_fill="#f4efe2",
    handle_dot_border="#8fb98c",
    waveform="rgba(196,186,158,150)",
    waveform_edge="#b3ab96",
    waveform_center="#6b6656",
    waveform_background="#26231f",
    waveform_header_text="#d7cfba",
    waveform_db_text="#a59d89",
    header_letter="#9d9683",
    header_name="#e9e2d0",
    header_icon="#a59d89",
    header_hover="#35312b",
    translation_clip="#4a4234",
    translation_clip_border="#8d7c58",
    translation_clip_text="#e6dcc4",
    translation_dot="#b39464",
    selection_rect="#8fb98c",
    selection_fill="rgba(143,185,140,34)",
    inline_editor_bg="#201d19",
    inline_editor_border="#8fb98c",
    inline_editor_text="#f1ebdc",
    speaker_accents=("#93bfa5", "#c2a878", "#94a7c7", "#a8a06e", "#bd8f96"),
)

LAVENDER_TIMELINE = TimelinePalette(
    key="lavender",
    dark=True,
    background="#2c2940",
    header="#353149",
    ruler="#262338",
    grid_major="#464165",
    grid_minor="#3e3a59",
    track_background="#37334e",
    track_alternate="#3c3857",
    track_header="#353149",
    playhead="#f2749b",
    playhead_label_text="#241826",
    time_label="#d5d0ea",
    clip_text="#f3f0fb",
    clip_selected_border="#c19bea",
    clip_selected_glow="rgba(193,155,234,66)",
    clip_multi_border="#b7b1dd",
    clip_border_shade=0.25,
    clip_fill_mix=0.6,
    clip_fill_lighten=104,
    handle_dot_fill="#f4effc",
    handle_dot_border="#c19bea",
    waveform="rgba(170,181,220,150)",
    waveform_edge="#a9b3dc",
    waveform_center="#5d5a78",
    waveform_background="#322f49",
    waveform_header_text="#d8d4ee",
    waveform_db_text="#a29ec2",
    header_letter="#b8b3d8",
    header_name="#efedfa",
    header_icon="#c3bedf",
    header_hover="#474263",
    translation_clip="#453f5e",
    translation_clip_border="#7d75a8",
    translation_clip_text="#e2def5",
    translation_dot="#a794d8",
    selection_rect="#c19bea",
    selection_fill="rgba(193,155,234,34)",
    inline_editor_bg="#37334e",
    inline_editor_border="#c19bea",
    inline_editor_text="#f3f0fb",
    speaker_accents=("#b49ae0", "#8fb7d9", "#dd9cb0", "#93cdb8", "#d1b078"),
)

SLATE_TIMELINE = TimelinePalette(
    key="slate",
    dark=True,
    background="#1f292e",
    header="#243036",
    ruler="#192228",
    grid_major="#35464e",
    grid_minor="#2d3e46",
    track_background="#263238",
    track_alternate="#2a373e",
    track_header="#243036",
    playhead="#ff7a59",
    playhead_label_text="#20161a",
    time_label="#c9d6da",
    clip_text="#eef4f5",
    clip_selected_border="#e39a73",
    clip_selected_glow="rgba(227,154,115,66)",
    clip_multi_border="#a3bcc4",
    clip_border_shade=0.25,
    clip_fill_mix=0.6,
    clip_fill_lighten=104,
    handle_dot_fill="#f5efe9",
    handle_dot_border="#e39a73",
    waveform="rgba(140,180,190,150)",
    waveform_edge="#8cb4be",
    waveform_center="#56707a",
    waveform_background="#222d33",
    waveform_header_text="#d2dee2",
    waveform_db_text="#9db0b6",
    header_letter="#b4c4ca",
    header_name="#e8f0f2",
    header_icon="#bccdd2",
    header_hover="#39484f",
    translation_clip="#2f4149",
    translation_clip_border="#5d747d",
    translation_clip_text="#d8e4e8",
    translation_dot="#88b6c4",
    selection_rect="#e39a73",
    selection_fill="rgba(227,154,115,34)",
    inline_editor_bg="#263238",
    inline_editor_border="#e39a73",
    inline_editor_text="#eef4f5",
    speaker_accents=("#8fc0b8", "#a3a7d1", "#d9a08f", "#c4c58e", "#9db6c9"),
)

# 2026-10-07 visual system: grape follows the new neutral grape-graphite
# tokens (ui_theme.THEMES["grape"]). Speaker accent defaults are unchanged so
# existing speaker/clip identity colours stay recognisable.
GRAPE_TIMELINE = TimelinePalette(
    key="grape", dark=True,
    background="#17131a", header="#1e1a22", ruler="#141117",
    grid_major="#3c3443", grid_minor="#2a2430",
    track_background="#1f1b24", track_alternate="#231e29", track_header="#1e1a22",
    playhead="#ec8db0", playhead_label_text="#19151c", time_label="#c9bfc8",
    clip_text="#f4eee9", clip_selected_border="#f3dbe5",
    clip_selected_glow="rgba(236,141,176,56)", clip_multi_border="#b49aaa",
    clip_border_shade=0.22, clip_fill_mix=0.5, clip_fill_lighten=100,
    handle_dot_fill="#f4eee9", handle_dot_border="#ec8db0",
    waveform="rgba(110,196,214,150)", waveform_edge="#6ec4d6", waveform_center="#2f4a52",
    waveform_background="#1b171e", waveform_header_text="#d0c6cd", waveform_db_text="#a69ba6",
    header_letter="#a69ba6", header_name="#f4eee9", header_icon="#c9bfc8", header_hover="#2f2935",
    translation_clip="#2f2935", translation_clip_border="#5d5266", translation_clip_text="#f4eee9",
    translation_dot="#ec8db0", selection_rect="#ec8db0", selection_fill="rgba(236,141,176,30)",
    inline_editor_bg="#252028", inline_editor_border="#86b4f7", inline_editor_text="#f4eee9",
    # 2026-10-07: distinct speaker hues (UI fallback only; a speaker's own
    # colour in the project always wins) and a slate-blue main video lane.
    speaker_accents=("#a990e0", "#e0809f", "#dc9a7c", "#c9b27e", "#7fb8c2"),
    video_accent="#7f97c2", video_clip="#4a536b", video_clip_border="#7f97c2",
)

def _rgba(color: str, alpha: int) -> str:
    value = QColor(color)
    return f"rgba({value.red()},{value.green()},{value.blue()},{int(alpha)})"


def _blend(first: str, second: str, ratio: float) -> str:
    return mix(first, second, ratio).name()


# Per-theme painting character for derived palettes: playhead (must stand
# apart from the selection colour), waveform hue, main video lane and five
# speaker fallbacks (a project's own speaker colours always win).
TIMELINE_TUNING: dict[str, dict] = {
    "frost": dict(playhead="#e5484d", waveform="#3d5f8f", video="#3a6fd0",
                  speakers=("#6f8fb8", "#5f9a93", "#8f80b5", "#a8906a", "#a87a8c")),
    "sand": dict(playhead="#2f63b0", waveform="#7a5c43", video="#3a6fb2",
                 speakers=("#7f9a86", "#b08a62", "#7d8fb0", "#a37b86", "#8f9a64")),
    "paper": dict(playhead="#c62828", waveform="#3a3a3a", video="#0a5bd3",
                  speakers=("#6d8fb3", "#6c9a7e", "#a3876a", "#9479a6", "#a57272")),
    "obsidian": dict(playhead="#ffd24f", waveform="#a9b4bf", video="#6fb3c9",
                     speakers=("#d9b45a", "#6fb3c9", "#c98f6d", "#9ec27a", "#b49ad6")),
    "midnight": dict(playhead="#ff8f6b", waveform="#6fb7e8", video="#7dd3fc",
                     speakers=("#7aa8ff", "#5fd0b5", "#c6a0ff", "#f0b46b", "#ef8fb0")),
    "verdant": dict(playhead="#ff9a6b", waveform="#7fc8b4", video="#7cc4ea",
                    speakers=("#5fc7a8", "#8fb8e0", "#d8b26a", "#c99ad6", "#e08f86")),
    "neon": dict(playhead="#4fd8ff", waveform="#a98cf0", video="#7f8cff",
                 speakers=("#a57cff", "#4fd8ff", "#ff7fb0", "#3fdcae", "#ffc56b")),
    "cinema": dict(playhead="#ff6b57", waveform="#d6a08a", video="#8fb4ea",
                   speakers=("#e0875a", "#d9b66b", "#8fb4ea", "#b98ac9", "#7fcb9b")),
    "graphite": dict(playhead="#8ab4f8", waveform="#a8a8ad", video="#9fb4d1",
                     speakers=("#9fb4d1", "#a9c4a1", "#d1b38a", "#c49fb6", "#9fc7c4")),
    "contrast": dict(playhead="#ffd23f", waveform="#3cd0ff", video="#3cd0ff", fill_mix=0.45,
                     speakers=("#3cd0ff", "#52f29e", "#ffb02e", "#ff7ad9", "#b4a7ff")),
}


def _ink_on(color: str, theme) -> str:
    from .ui_theme import contrast_ratio

    dark_ink = theme.text if theme.is_light else theme.app_background
    return "#ffffff" if contrast_ratio("#ffffff", color) >= contrast_ratio(dark_ink, color) else dark_ink


def derive_timeline_palette(theme, tuning: dict | None = None) -> TimelinePalette:
    """A full timeline palette from ui_theme tokens (light or dark rules)."""
    tune = dict(TIMELINE_TUNING.get(theme.key, {}), **(tuning or {}))
    accent = theme.accent_text
    playhead = tune.get("playhead") or accent
    waveform = tune.get("waveform") or theme.text_muted
    video = tune.get("video") or theme.info
    speakers = tuple(tune.get("speakers") or ("#638d85", "#9a7f62", "#687f9c", "#7e8363", "#906c76"))
    if theme.is_light:
        return TimelinePalette(
            key=theme.key, dark=False,
            background=theme.timeline, header=theme.panel,
            ruler=_blend(theme.border, theme.border_strong, 0.35),
            grid_major=_blend(theme.border, theme.border_strong, 0.55), grid_minor=theme.border,
            track_background=theme.surface, track_alternate=_blend(theme.surface, theme.panel, 0.6),
            track_header=theme.panel,
            playhead=playhead, playhead_label_text=_ink_on(playhead, theme),
            time_label=theme.text_secondary, clip_text=theme.text,
            clip_selected_border=theme.accent_pressed, clip_selected_glow=_rgba(theme.accent_soft, 235),
            clip_multi_border=_blend(theme.accent, theme.surface, 0.4),
            clip_border_shade=0.0, clip_fill_mix=float(tune.get("fill_mix", 0.0)), clip_fill_lighten=135,
            handle_dot_fill=theme.surface_elevated, handle_dot_border=theme.accent,
            waveform=_rgba(waveform, 165), waveform_edge=waveform, waveform_center=theme.border_strong,
            waveform_background=_blend(theme.panel, theme.border, 0.35),
            waveform_header_text=theme.text_secondary, waveform_db_text=theme.text_muted,
            header_letter=theme.text_muted, header_name=theme.text, header_icon=theme.text_muted,
            header_hover=theme.selected,
            translation_clip=_blend(theme.surface, theme.warning, 0.22),
            translation_clip_border=_blend(theme.warning, theme.surface, 0.25),
            translation_clip_text=theme.text_secondary, translation_dot=theme.warning,
            selection_rect=theme.accent, selection_fill=_rgba(theme.accent, 38),
            inline_editor_bg=theme.surface_elevated, inline_editor_border=theme.accent,
            inline_editor_text=theme.text,
            speaker_accents=speakers,
            video_accent=video, video_clip=_blend(theme.surface, video, 0.28), video_clip_border=video,
        )
    return TimelinePalette(
        key=theme.key, dark=True,
        background=theme.timeline, header=theme.panel, ruler=theme.shell,
        grid_major=_blend(theme.border, theme.border_strong, 0.5), grid_minor=theme.border,
        track_background=_blend(theme.panel, theme.surface, 0.5),
        track_alternate=_blend(theme.panel, theme.surface, 0.9), track_header=theme.panel,
        playhead=playhead, playhead_label_text=_ink_on(playhead, theme),
        time_label=_blend(theme.text_secondary, theme.text_muted, 0.4), clip_text=theme.text,
        clip_selected_border=_blend(accent, theme.text, 0.55), clip_selected_glow=_rgba(accent, 60),
        clip_multi_border=_blend(theme.text_muted, accent, 0.35),
        clip_border_shade=0.22, clip_fill_mix=float(tune.get("fill_mix", 0.55)), clip_fill_lighten=102,
        handle_dot_fill=theme.text, handle_dot_border=accent,
        waveform=_rgba(waveform, 150), waveform_edge=waveform,
        waveform_center=_blend(theme.timeline, waveform, 0.3), waveform_background=theme.input_surface,
        waveform_header_text=theme.text_secondary, waveform_db_text=theme.text_muted,
        header_letter=theme.text_muted, header_name=theme.text,
        header_icon=_blend(theme.text_secondary, theme.text_muted, 0.4), header_hover=theme.surface_elevated,
        translation_clip=theme.surface_elevated,
        translation_clip_border=_blend(theme.border_strong, theme.text_muted, 0.3),
        translation_clip_text=theme.text, translation_dot=accent,
        selection_rect=accent, selection_fill=_rgba(accent, 32),
        inline_editor_bg=theme.surface, inline_editor_border=theme.focus, inline_editor_text=theme.text,
        speaker_accents=speakers,
        video_accent=video, video_clip=_blend(theme.surface, video, 0.3), video_clip_border=video,
    )


_HAND_TUNED: dict[str, TimelinePalette] = {
    GRAPE_TIMELINE.key: GRAPE_TIMELINE,
    WARM_TIMELINE.key: WARM_TIMELINE,
    PLUM_TIMELINE.key: PLUM_TIMELINE,
    LAVENDER_TIMELINE.key: LAVENDER_TIMELINE,
    SLATE_TIMELINE.key: SLATE_TIMELINE,
}


def _all_palettes() -> dict[str, TimelinePalette]:
    from .ui_theme import THEMES

    return {key: _HAND_TUNED.get(key) or derive_timeline_palette(theme) for key, theme in THEMES.items()}


TIMELINE_PALETTES: dict[str, TimelinePalette] = _all_palettes()


def timeline_palette(key: str | None = None) -> TimelinePalette:
    if key is None:
        from .theme_manager import theme_key

        key = theme_key()
    palette = TIMELINE_PALETTES.get(str(key))
    if palette is None:
        from .ui_theme import theme_definition

        palette = TIMELINE_PALETTES.get(theme_definition(key).key) or derive_timeline_palette(theme_definition(key))
    return palette
