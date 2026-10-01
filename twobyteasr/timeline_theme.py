"""Tokenized color palettes for the Studio Timeline's custom painting.

The WaveformTimeline paints everything with QPainter, so it cannot follow
QSS theming. This module gives every painted surface an explicit token per
theme (warm cream / plum + coral / lavender workspace / slate editorial).
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

GRAPE_TIMELINE = TimelinePalette(
    key="grape", dark=True,
    background="#211a26", header="#281e2e", ruler="#1b141f",
    grid_major="#503a56", grid_minor="#392b40",
    track_background="#2b2131", track_alternate="#302637", track_header="#281e2e",
    playhead="#ed8796", playhead_label_text="#211826", time_label="#dcc2d2",
    clip_text="#fff1f6", clip_selected_border="#e8b8cf",
    clip_selected_glow="rgba(168,62,96,60)", clip_multi_border="#bd859f",
    clip_border_shade=0.22, clip_fill_mix=0.64, clip_fill_lighten=104,
    handle_dot_fill="#fff1f6", handle_dot_border="#e8b8cf",
    waveform="rgba(218,184,201,170)", waveform_edge="#dab8c9", waveform_center="#795570",
    waveform_background="#241b2a", waveform_header_text="#e5ccd9", waveform_db_text="#bc9bad",
    header_letter="#bc9bad", header_name="#fff1f6", header_icon="#d5b5c8", header_hover="#49344c",
    translation_clip="#493042", translation_clip_border="#b67e99", translation_clip_text="#fff1f6",
    translation_dot="#d89ab4", selection_rect="#e8b8cf", selection_fill="rgba(168,62,96,38)",
    inline_editor_bg="#302337", inline_editor_border="#e8b8cf", inline_editor_text="#fff1f6",
    speaker_accents=("#ad95cc", "#d99ab2", "#91b7c4", "#b9bc95", "#bd8f82"),
)

TIMELINE_PALETTES: dict[str, TimelinePalette] = {
    GRAPE_TIMELINE.key: GRAPE_TIMELINE,
    WARM_TIMELINE.key: WARM_TIMELINE,
    PLUM_TIMELINE.key: PLUM_TIMELINE,
    LAVENDER_TIMELINE.key: LAVENDER_TIMELINE,
    SLATE_TIMELINE.key: SLATE_TIMELINE,
}


def timeline_palette(key: str | None = None) -> TimelinePalette:
    if key is None:
        from .theme_manager import theme_key

        key = theme_key()
    return TIMELINE_PALETTES.get(str(key), WARM_TIMELINE)
