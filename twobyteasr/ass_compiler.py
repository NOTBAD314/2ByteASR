"""Deterministic ASS and plain-text compiler for Subtitle Studio projects."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .studio_project import SubtitleProject, SubtitleStyle, StudioCue
from .style_resolution import resolve_cue_visual_from_records
from .studio_revisions import thaw_json
from .style_recipe import StyleRecipe, recipe_payload_for_style
from .effect_dsl import (
    compile_effect_override,
    compile_effect_text,
    compile_position_motion_segments,
    validate_effect,
)


ASS_FORMAT_VERSION = "v4.00+"
_ASS_COLOR = re.compile(r"^&H([0-9A-Fa-f]{8})&?$")
_HEX_COLOR = re.compile(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


def _ass_number(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _ass_color(value: str, default: str) -> str:
    text = str(value or default).strip()
    match = _ASS_COLOR.fullmatch(text)
    if match:
        return f"&H{match.group(1).upper()}"
    match = _HEX_COLOR.fullmatch(text)
    if not match:
        match = _HEX_COLOR.fullmatch(default)
    digits = match.group(1).upper()
    if len(digits) == 6:
        alpha, red, green, blue = "00", digits[0:2], digits[2:4], digits[4:6]
    else:
        # Qt emits extended colors as #AARRGGBB (alpha first), while ASS
        # stores transparency as inverse alpha: 00 opaque, FF invisible.
        qt_alpha, red, green, blue = (
            int(digits[0:2], 16), digits[2:4], digits[4:6], digits[6:8]
        )
        alpha = f"{255 - qt_alpha:02X}"
    return f"&H{alpha}{blue}{green}{red}"


def _ass_time(milliseconds: int) -> str:
    centiseconds = max(0, int(milliseconds)) // 10
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _ass_name(value: str, fallback: str) -> str:
    cleaned = str(value or fallback).replace(",", " ").replace("\r", " ").replace("\n", " ").strip()
    return cleaned or fallback


def _ass_style_name(style_id: str) -> str:
    """Map the internal default id to libass's canonical built-in name.

    A lowercase ``default`` style is parsed but libass can still resolve
    events to its built-in ``Default`` style, silently discarding FontSize.
    """
    name = _ass_name(style_id, "Default")
    return "Default" if name.casefold() == "default" else name


def escape_ass_text(value: str) -> str:
    """Keep cue text out of ASS override-tag syntax."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "｛").replace("}", "｝")
    return text.replace("\n", r"\N")


def _style_line(style: SubtitleStyle) -> str:
    # ASS carries a single Outline per Style. With two stroke layers the wider
    # one is the closest single-layer approximation; the full stack renders in
    # the Qt/Remotion previews and the advanced renderer.
    outline_color = style.outline_color
    outline_width = style.outline_width
    if style.outline2_width > style.outline_width:
        outline_color = style.outline2_color or outline_color
        outline_width = style.outline2_width
    values = (
        _ass_style_name(style.id),
        _ass_name(style.font_family, "Microsoft YaHei UI"),
        _ass_number(style.font_size),
        _ass_color(style.primary_color, "#FFFFFF"),
        _ass_color(style.primary_color, "#FFFFFF"),
        _ass_color(outline_color, "#000000"),
        _ass_color(style.back_color, "#000000"),
        str(style.font_weight) if style.font_weight else ("-1" if style.bold else "0"),
        "-1" if style.italic else "0",
        "-1" if style.underline else "0",
        "0",
        _ass_number(style.scale_x),
        _ass_number(style.scale_y),
        _ass_number(style.spacing),
        "0",
        str(style.border_style),
        _ass_number(outline_width),
        _ass_number(style.shadow),
        str(style.alignment),
        str(style.margin_l),
        str(style.margin_r),
        str(style.margin_v),
        "1",
    )
    return "Style: " + ",".join(values)


def _cue_style_id(project: SubtitleProject, cue: StudioCue, known_styles: set[str]) -> str:
    if cue.style_id in known_styles:
        return cue.style_id
    speaker_styles = {speaker.id: speaker.style_id for speaker in project.speakers}
    speaker_style = speaker_styles.get(cue.speaker_id, "default")
    return speaker_style if speaker_style in known_styles else "default"


def _style_position_override(style: SubtitleStyle, effect_override: str) -> str:
    if style.position_x is None or style.position_y is None:
        return ""
    if r"\pos" in effect_override or r"\move" in effect_override:
        return ""
    return rf"\pos({_ass_number(style.position_x)},{_ass_number(style.position_y)})"


def _cue_transform_override(cue: Any, effect_override: str, resolved_style=None) -> str:
    raw = getattr(cue, "transform", {})
    transform = thaw_json(raw)
    if not isinstance(transform, Mapping):
        return ""
    tags: list[str] = []
    x, y = transform.get("position_x"), transform.get("position_y")
    if x is not None and y is not None and r"\pos" not in effect_override and r"\move" not in effect_override:
        x, y = (resolved_style.position_x, resolved_style.position_y) if resolved_style else (x, y)
        tags.append(rf"\pos({_ass_number(x)},{_ass_number(y)})")
    if transform.get("scale_x") is not None:
        tags.append(rf"\fscx{_ass_number(float(transform['scale_x']))}")
    if transform.get("scale_y") is not None:
        tags.append(rf"\fscy{_ass_number(float(transform['scale_y']))}")
    if transform.get("rotation") is not None:
        tags.append(rf"\frz{_ass_number(float(transform['rotation']))}")
    if transform.get("font_size") is not None:
        size = resolved_style.font_size if resolved_style else float(transform['font_size'])
        tags.append(rf"\fs{_ass_number(size)}")
    return "".join(tags)


def _style_anchor_position(
    style: SubtitleStyle, play_res_x: int, play_res_y: int
) -> tuple[int, int]:
    if style.position_x is not None and style.position_y is not None:
        return style.position_x, style.position_y
    horizontal = (style.margin_l, play_res_x // 2, play_res_x - style.margin_r)
    vertical = (play_res_y - style.margin_v, play_res_y // 2, style.margin_v)
    return (horizontal[(style.alignment - 1) % 3], vertical[(style.alignment - 1) // 3])


def _dialogue_line(
    *, start_ms: int, end_ms: int, style_id: str, speaker: str, text: str, frame_rate=None
) -> str:
    from .caption_frame_time import ass_frame_ms
    display_start=ass_frame_ms(start_ms,frame_rate)
    display_end=ass_frame_ms(end_ms,frame_rate)
    if start_ms%10 or end_ms%10:
        # ASS event headers only carry centiseconds. Its fade envelope carries
        # milliseconds: keep the exact half-open interval inside a containing
        # event, including a real one-millisecond gap at a video frame.
        display_start=int(start_ms)//10*10
        display_end=(int(end_ms)+9)//10*10
        offset=int(start_ms)-display_start
        stop=int(end_ms)-display_start
        fades=re.findall(r'\\fad\((\d+),(\d+)\)',text)
        if not re.search(r'\\fade\(',text):
            fade_in,fade_out=map(int,fades[-1]) if fades else (0,0)
            text=re.sub(r'\\fad\(\d+,\d+\)','',text)
            text=('{'+rf'\fade(255,0,255,{offset},{min(stop,offset+fade_in)},'
                  +f'{max(offset,stop-fade_out)},{stop})'+'}'+text)
    return "Dialogue: 0,{start},{end},{style},{speaker},0,0,0,,{text}".format(
        start=_ass_time(display_start),
        end=_ass_time(display_end),
        style=_ass_style_name(style_id),
        speaker=speaker,
        text=text,
    )


def compile_ass(project: SubtitleProject, *, frame_rate=None, cues: Sequence[Any] | None = None) -> str:
    project.validate()
    play_res_x = max(1, int(project.render_settings.get("play_res_x", 1920)))
    play_res_y = max(1, int(project.render_settings.get("play_res_y", 1080)))
    metadata = getattr(project, "generation_metadata", None)
    translations = metadata.get("translations") if isinstance(metadata, Mapping) else None
    state = getattr(project, "studio_state", None)
    bilingual = bool(state.get("bilingual_mode")) if isinstance(state, Mapping) else False
    from .caption_frame_time import project_frame_rate
    if frame_rate is None:frame_rate=project_frame_rate(project)
    from .subtitle_stacking import project_stack_layout
    return _compile_ass_records(
        cues=cues if cues is not None else project.cues,
        frame_rate=frame_rate,
        styles=project.styles,
        speakers=project.speakers,
        effects=project.effects,
        style_recipes=project.style_recipes,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        translations=translations if (bilingual and isinstance(translations, Mapping)) else None,
        stacking_enabled=project.studio_state.get('auto_subtitle_stacking',True),
        stack_offsets=project_stack_layout(project).offsets,
    )


def compile_ass_revision(revision: "SubtitleRenderRevision") -> str:
    """Compile one immutable worker DTO without touching a live project."""

    from .studio_revisions import thaw_json

    effects = thaw_json(revision.effects)
    recipes = thaw_json(revision.style_recipes)
    state = thaw_json(revision.studio_state) if getattr(revision, "studio_state", "") else {}
    bilingual = bool(state.get("bilingual_mode")) if isinstance(state, Mapping) else False
    metadata = thaw_json(revision.generation_metadata) if getattr(revision, "generation_metadata", "") else {}
    translations = metadata.get("translations") if isinstance(metadata, Mapping) else None
    return _compile_ass_records(
        cues=revision.cues,
        frame_rate=getattr(revision,'frame_rate',None),
        styles=revision.styles,
        speakers=revision.speakers,
        effects=effects if isinstance(effects, Mapping) else {},
        style_recipes=recipes if isinstance(recipes, Mapping) else {},
        play_res_x=revision.play_res_x,
        play_res_y=revision.play_res_y,
        translations=translations if (bilingual and isinstance(translations, Mapping)) else None,
        stacking_enabled=state.get('auto_subtitle_stacking',True),
    )


def _compile_ass_records(
    *,
    cues: Sequence[Any],
    styles: Sequence[Any],
    speakers: Sequence[Any],
    effects: Mapping[str, Any],
    style_recipes: Mapping[str, Any],
    play_res_x: int,
    play_res_y: int,
    translations: Mapping[str, str] | None = None,
    frame_rate=None,
    stacking_enabled=True,
    stack_offsets=None,
) -> str:
    styles = sorted(styles, key=lambda item: (item.id != "default", item.id))
    known_styles = {style.id for style in styles}
    styles_by_id = {style.id: style for style in styles}
    speaker_styles = {speaker.id: speaker.style_id for speaker in speakers}
    lines = [
        "[Script Info]",
        "; Generated by 2ByteASR Subtitle Studio",
        f"ScriptType: {ASS_FORMAT_VERSION}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "",
        f"[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    from .resolved_caption_style import resolve_caption_style
    resolved_captions = {cue.id: resolve_caption_style(styles,speakers,cue,style_recipes,play_res_x) for cue in cues}
    # 2026-09-19：抢话字幕自动分层——同时显示的多条字幕按开始时间上下
    # 排布（先开始的在下）。偏移是纯显示布局：只进派生 resolved 样式
    # 的 per-event \pos，绝不写回用户样式/cue transform。
    from .subtitle_stacking import compute_stack_layout
    stack_layout = compute_stack_layout(
        cues,
        resolve_one=lambda cue: resolved_captions[cue.id],
        play_res_y=play_res_y,
        play_res_x=play_res_x,
        enabled=stacking_enabled,
        effect_for=lambda cue:effects.get(cue.effect_id,{}),
    )
    if stack_offsets is not None:
        from .subtitle_stacking import StackLayout
        stack_layout=StackLayout(stack_offsets)
    cue_styles = {}
    lines.extend(_style_line(style) for style in styles)
    for cue in cues:
        caption = resolved_captions[cue.id]
        from .ass_font_units import ass_font_style
        effective = ass_font_style(caption.style, play_res_x, play_res_y)
        stack_offset = stack_layout.offset_for(cue.id)
        if stack_offset:
            effective.position_y = max(4.0, float(effective.position_y) - stack_offset)
        effective.id = f"resolved-{caption.style_hash[:20]}"
        cue_styles[cue.id] = effective
    lines.extend(_style_line(style) for style in {style.id:style for style in cue_styles.values()}.values())
    lines.extend(
        [
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms, item.id)):
        if cue.style_id in known_styles:
            style_id = cue.style_id
        else:
            candidate = speaker_styles.get(cue.speaker_id, "default")
            style_id = candidate if candidate in known_styles else "default"
        speaker = _ass_name(cue.speaker_id, "S00")
        caption = resolved_captions[cue.id]
        text = escape_ass_text(caption.text)
        recipe_payload = recipe_payload_for_style(style_recipes, style_id)
        style_id = cue_styles[cue.id].id
        ass_override = (
            StyleRecipe.from_dict(recipe_payload).ass.to_override()
            if recipe_payload else ""
        )
        effect = effects.get(cue.effect_id, effects.get("none", {}))
        cue_duration = cue.end_ms - cue.start_ms
        text = compile_effect_text(text, effect, cue_duration_ms=cue_duration)
        resolved_style = cue_styles[cue.id]
        lines.append(f"; CaptionStyle cue={cue.id} hash={caption.style_hash} lines={caption.line_count} width={caption.measured_width:g}")
        # Static appearance belongs to the resolved style; legacy recipe tags
        # may animate placement/opacity but cannot repaint fill/stroke/shadow.
        ass_override = rf"\q2\b{resolved_style.font_weight}\fs{_ass_number(resolved_style.font_size)}"
        target_position = _style_anchor_position(resolved_style, play_res_x, play_res_y)
        motion_segments = compile_position_motion_segments(
            effect,
            cue_duration_ms=cue_duration,
            target_position=target_position,
        )
        if motion_segments:
            for relative_start, relative_end, segment_override in motion_segments:
                segment_text = "{" + ass_override + segment_override + "}" + text
                lines.append(
                    _dialogue_line(
                        start_ms=cue.start_ms + relative_start,
                        end_ms=cue.start_ms + relative_end,
                        style_id=style_id,
                        speaker=speaker,
                        text=segment_text,
                        frame_rate=frame_rate,
                    )
                )
            settled_at = motion_segments[-1][1]
            if settled_at < cue_duration:
                normalized = validate_effect(effect)
                settled_effect = {
                    "entry": {"type": "none"},
                    "exit": normalized["exit"],
                }
                if "word_highlight" in normalized:
                    settled_effect["word_highlight"] = normalized["word_highlight"]
                settled_override = compile_effect_override(
                    settled_effect,
                    cue_duration_ms=cue_duration - settled_at,
                    play_res_x=play_res_x,
                    play_res_y=play_res_y,
                    target_position=target_position,
                )
                settled_override = ass_override + settled_override
                settled_override = _cue_transform_override(cue, settled_override, resolved_style) + settled_override
                settled_override = _style_position_override(resolved_style, settled_override) + settled_override
                settled_text = ("{" + settled_override + "}" + text) if settled_override else text
                lines.append(
                    _dialogue_line(
                        start_ms=cue.start_ms + settled_at,
                        end_ms=cue.end_ms,
                        style_id=style_id,
                        speaker=speaker,
                        text=settled_text,
                        frame_rate=frame_rate,
                    )
                )
            continue
        override = compile_effect_override(
            effect,
            cue_duration_ms=cue_duration,
            play_res_x=play_res_x,
            play_res_y=play_res_y,
            target_position=target_position,
        )
        override = ass_override + override
        override = _cue_transform_override(cue, override, resolved_style) + override
        override = _style_position_override(resolved_style, override) + override
        if override:
            text = "{" + override + "}" + text
        lines.append(
            _dialogue_line(
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                style_id=style_id,
                speaker=speaker,
                text=text,
                frame_rate=frame_rate,
            )
        )
        if translations:
            translation = str(translations.get(cue.id, "") or "").strip()
            if translation:
                # 双语第二行：主文本上方、约 0.66 缩放、轻微降透明度，
                # 与主行同起止时间（跟随 bilingual_mode 开关）。
                sub_size = max(8.0, float(resolved_style.font_size) * 0.66)
                offset = float(resolved_style.font_size) * 1.06
                pos_x, pos_y = target_position
                sub_override = (
                    f"\\fs{sub_size:g}"
                    f"\\pos({pos_x:g},{max(4.0, pos_y - offset):g})"
                    "\\alpha&H48&"
                )
                lines.append(
                    _dialogue_line(
                        start_ms=cue.start_ms,
                        end_ms=cue.end_ms,
                        style_id=style_id,
                        speaker=speaker,
                        text="{" + sub_override + "}" + escape_ass_text(translation),
                        frame_rate=frame_rate,
                    )
                )
    return "\n".join(lines) + "\n"


def compile_txt(project: SubtitleProject, *, cues=None) -> str:
    project.validate()
    ordered: Iterable[StudioCue] = sorted(
        cues if cues is not None else project.cues, key=lambda item: (item.start_ms, item.end_ms, item.id)
    )
    return "\n".join(cue.text.replace("\r", " ").replace("\n", " ") for cue in ordered) + "\n"
