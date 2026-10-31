"""One bilingual layout for preview and export: original, translation or both.

Display settings live in ``studio_state["bilingual"]``; the older boolean
``studio_state["bilingual_mode"]`` still means "show both" with the old look.
Translations are ``generation_metadata["translations"]`` (cue id -> text).

``display_cues`` turns project cues into the cues that are drawn: in
bilingual mode every translated cue gets a companion cue ``<id>#tr`` with the
translation, its own font family/size and a position computed from the
original's resolved style, so the ASS compiler and the live caption scene
draw the same two blocks. The pair is laid out as one block at the cue's own
anchor: the lower line stays on the anchor, the upper line sits above it.
Swapping the order moves the original (with its effects) to the upper line.
Cue timing, speaker and the original text are never changed.
"""
from __future__ import annotations

import copy
import functools
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

COMPANION_SUFFIX = "#tr"
MODES = ("original", "translation", "bilingual")
ORDERS = ("translation_first", "original_first")


@dataclass(frozen=True)
class BilingualSettings:
    mode: str = "original"
    order: str = "translation_first"      # translation (Chinese) above the original
    original_scale: float = 0.78
    translation_scale: float = 1.0
    translation_font: str = ""
    gap_ratio: float = 0.18
    legacy: bool = False                  # old boolean switch: keep the old look
    # "" = 2026-10-12 evening layout (nominal 1.2 em line boxes + gap_ratio em);
    # "ink_v1" = compact group from glyph ink + outline + shadow, gap_ratio em
    # of visible space. Never changed on open; set for new bilingual projects
    # and by the explicit "apply compact bilingual layout" command.
    layout: str = ""
    group_transform: dict = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        value = {"mode": self.mode, "order": self.order, "original_scale": self.original_scale,
                 "translation_scale": self.translation_scale, "translation_font": self.translation_font,
                 "gap_ratio": self.gap_ratio}
        if self.layout:
            value["layout"] = self.layout
        return value


LAYOUTS = ("", "ink_v1")
COMPACT_GAP_EM = 0.13


def compact_defaults() -> dict[str, Any]:
    """Layout fields of a new bilingual state (and of the explicit compact command)."""
    return {"layout": "ink_v1", "gap_ratio": COMPACT_GAP_EM}


def settings_from_state(state: Mapping[str, Any] | None) -> BilingualSettings:
    state = state if isinstance(state, Mapping) else {}
    raw = state.get("bilingual")
    if isinstance(raw, Mapping):
        mode = raw.get("mode") if raw.get("mode") in MODES else "original"
        order = raw.get("order") if raw.get("order") in ORDERS else "translation_first"

        def number(key, default, low, high):
            try:
                return min(high, max(low, float(raw.get(key, default))))
            except (TypeError, ValueError):
                return default
        return BilingualSettings(mode, order, number("original_scale", 0.78, 0.4, 1.6),
                                 number("translation_scale", 1.0, 0.4, 1.6), str(raw.get("translation_font") or ""),
                                 number("gap_ratio", 0.18, 0.0, 1.0),
                                 layout=raw.get("layout") if raw.get("layout") in LAYOUTS else "",
                                 group_transform=copy.deepcopy(state.get('caption_group_transform') or {}))
    if state.get("bilingual_mode"):
        # Projects from before 2026-10-12: translation above, 0.66 size, original untouched.
        return BilingualSettings("bilingual", "translation_first", 1.0, 0.66, "", 0.06, legacy=True,
            group_transform=copy.deepcopy(state.get('caption_group_transform') or {}))
    return BilingualSettings(group_transform=copy.deepcopy(state.get('caption_group_transform') or {}))


def translations_of(metadata: Mapping[str, Any] | None) -> Mapping[str, str]:
    value = (metadata or {}).get("translations") if isinstance(metadata, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def translation_for_cue(translations: Mapping, cue_id: str):
    """Resolve a projected instance without losing its source cue's translation."""
    from ..timeline.studio_edit_sequence import source_cue_id_of
    if cue_id in translations:
        return translations[cue_id]
    return translations.get(source_cue_id_of(cue_id))


def is_companion(cue_id: str) -> bool:
    return str(cue_id).endswith(COMPANION_SUFFIX)


def companion_id(cue_id: str) -> str:
    return f"{cue_id}{COMPANION_SUFFIX}"


def _anchor(style, play_res_x, play_res_y):
    horizontal = (style.margin_l, play_res_x // 2, play_res_x - style.margin_r)
    vertical = (play_res_y - style.margin_v, play_res_y // 2, style.margin_v)
    return (float(style.position_x if style.position_x is not None else horizontal[(style.alignment-1) % 3]),
            float(style.position_y if style.position_y is not None else vertical[(style.alignment-1) // 3]))


def _block_height(caption) -> float:
    import json
    recipe = json.loads(caption.recipe_json) if getattr(caption, "recipe_json", "") else {}
    layout = recipe.get("layout") or {}
    style = caption.style
    line_height = float(layout.get("lineHeightPx") or style.font_size * 1.2)
    return line_height * max(1, int(caption.line_count or 1)) * float(style.scale_y or 100) / 100.0


def _with_transform(cue, **values):
    clone = copy.deepcopy(cue)
    transform = dict(clone.transform or {})
    transform.update(values)
    clone.transform = transform
    return clone


def ink_block(caption) -> tuple[float, float, float, float]:
    """(ink height, ink width, outline extent, drop shadow) of a resolved caption, in play-res px.

    Ink is the glyph outline box of the wrapped text, the anchoring contract of
    LIVE's glyph path; outline and shadow extend it on screen.
    """
    from .resolved_caption_style import visible_glyph_size
    style = caption.style
    width, height = visible_glyph_size(caption.text, style.font_family, style.bold, float(style.font_size),
                                       float(style.spacing), style.font_weight, style.font_style_name,
                                       style.font_file, style.font_face_index)
    return (height * float(style.scale_y or 100) / 100.0, width * float(style.scale_x or 100) / 100.0,
            float(style.outline_width) + float(style.outline2_width), max(0.0, float(style.shadow)))


def motion_ink_block(caption, cue, language, effects):
    """Reserve the breathing envelope once, while preparing the cue pair."""
    return reserve_motion_block(ink_block(caption),cue,language,effects)


def breathing_scale(effect):
    loop=(effect or {}).get('loop') or {}
    if loop.get('type')!='loop_breathe':return 1.
    from .motion_catalog import STRENGTH
    return 1.+.065*STRENGTH.get(loop.get('strength','medium'),1.)


def motion_layout_cue(cue,effect):
    """Render-only wrap allowance, independent of the current motion phase."""
    scale=breathing_scale(effect)
    if scale==1. and '_motion_layout_scale' not in cue.transform:return cue
    shown=copy.copy(cue);shown.transform=dict(cue.transform or {})
    if scale>1.:shown.transform['_motion_layout_scale']=scale
    else:shown.transform.pop('_motion_layout_scale',None)
    return shown


def motion_layout_layer(cue,language,effects):
    effects=effects or {}
    effect_id=cue.transform.get('language_motion',{}).get('translation_effect_id','none') if language=='translation' else cue.effect_id
    return motion_layout_cue(cue,effects.get(effect_id))


def reserve_motion_block(block,cue,language,effects):
    if not effects:return block
    effect_id=(cue.transform or {}).get('language_motion',{}).get('translation_effect_id','none') if language=='translation' else cue.effect_id
    expansion=breathing_scale(effects.get(effect_id))-1.
    if not expansion:return block
    height,width,outline,shadow=block
    # The affine loop pivots at the ink center, so half its additional
    # height reaches either edge. Outline/shadow scale with the same tile.
    return height,width,outline+(height*.5+outline+shadow)*expansion,shadow


def automatic_group_layout(cue):
    transform=cue.transform or {}
    return not ({'position_x','position_y'} & transform.keys() or any(
        {'position_x','position_y'} & set(fields) for fields in transform.get('language_layers',{}).values()))


def group_positions(anchor_y: float, row: int, top_block, bottom_block, gap_px: float, canvas_height=None) -> tuple[float, float]:
    """Anchor y of the top and bottom block of a two-line group anchored at ``anchor_y``.

    ``row`` is the alignment row (0 bottom, 1 middle, 2 top); blocks are
    ``ink_block`` tuples. The visible space between the two blocks (outline
    and the top block's shadow included) is ``gap_px``.
    """
    fraction = (1.0, 0.5, 0.0)[row]
    h_top, _, o_top, s_top = top_block
    h_bottom, _, o_bottom, _ = bottom_block
    inner = o_top + s_top + gap_px + o_bottom
    group_top = anchor_y - fraction * (h_top + inner + h_bottom)
    top_y = group_top + fraction * h_top
    bottom_y = group_top + h_top + inner + fraction * h_bottom
    if canvas_height is not None:
        visible_top=group_top-o_top
        visible_bottom=group_top+h_top+inner+h_bottom+o_bottom+bottom_block[3]
        # If the complete automatic group fits, move it only as far as its
        # visual envelope requires. Explicit authored anchors stay untouched.
        # An oversized group keeps its requested type size/overflow semantics.
        if visible_bottom-visible_top<=canvas_height-8:
            shift=max(4-visible_top,min(0.,canvas_height-4-visible_bottom))
            top_y+=shift;bottom_y+=shift
    return top_y, bottom_y


def group_extra(original_block, companion_block, gap_px: float, translation_on_top: bool = True) -> float:
    """Height the translation line adds to the single original caption (overlap avoidance)."""
    top, bottom = (companion_block, original_block) if translation_on_top else (original_block, companion_block)
    return companion_block[0] + top[2] + top[3] + gap_px + bottom[2]


# A translation line in another script than the original needs glyphs the
# subtitle face may lack: the usual faces (YaHei, ZCOOL, Cubic) have no Hangul
# and some have no kana, so Korean/Japanese lines would draw boxes and the PIL
# measuring of line breaks would be wrong. The bundled Source Han Sans covers
# Hangul, kana, Han and Latin (2026-10-14). Only used without a translation font.
SCRIPT_FALLBACK_FONT = "Source Han Sans SC"
# One character stands for each script block: a face with one carries the block.
_SCRIPT_SAMPLES = (("\uac00", "\ud7a3", "\uac00"),    # Hangul syllables
                   ("\u3041", "\u309f", "\u3042"),    # hiragana
                   ("\u30a1", "\u30fa", "\u30a2"))    # katakana


@functools.lru_cache(maxsize=128)
def _face_has(family: str, weight: int, bold: bool, character: str) -> bool:
    try:
        from .font_metadata import has_character, resolve_local_face
        face, _warning = resolve_local_face(family, weight, bold=bold)
        return has_character(face.file, face.index, character)
    except Exception:  # noqa: BLE001 - a font that cannot be read keeps the style font
        return True


def _translation_font(settings: BilingualSettings, text: str, style) -> str:
    if settings.translation_font:
        return settings.translation_font
    for low, high, sample in _SCRIPT_SAMPLES:
        if any(low <= char <= high for char in text) and not _face_has(
                str(style.font_family), int(getattr(style, "font_weight", 0) or 0),
                bool(getattr(style, "bold", False)), sample):
            return SCRIPT_FALLBACK_FONT
    return ""


def _translation_appearance(cue, shown):
    layer = cue.appearance_override.get('translation', {})
    shown.appearance_override = copy.deepcopy(shown.appearance_override)
    shown.appearance_override.pop('text_marks', None)
    shown.appearance_override.pop('translation', None)
    shown.appearance_override.update(copy.deepcopy(layer.get('style', {})))
    shown.appearance_override['text_marks'] = copy.deepcopy(layer.get('text_marks', []))
    shown.appearance_override['_translation_display'] = True
    if layer.get('recipe'): shown.appearance_override['_recipe_patch'] = copy.deepcopy(layer['recipe'])
    if 'recipe_base' in layer: shown.appearance_override['_recipe_base'] = copy.deepcopy(layer['recipe_base'])
    shown.evidence_refs = []
    if 'font_size' in layer.get('style', {}):
        shown.transform['font_size'] = layer['style']['font_size']
    for key in ('position_x', 'position_y', 'scale_x', 'scale_y'):
        if key in layer.get('style', {}): shown.transform[key] = layer['style'][key]
    return shown


@functools.lru_cache(maxsize=128)
def _translation_placeholder(html):
    import re
    return bool(re.search(r'\{\{\s*translation\s*\}\}', html))


def theme_owns_translation(recipes, cue):
    theme=(recipes.get(cue.style_id) or {}).get('webTheme') or {}
    return _translation_placeholder(str(theme.get('cueHtml','')))


class CaptionPreparationCancelled(Exception):
    """A retired preview must not return an incomplete display project."""


def _check_preparation_cancelled(cancel_check):
    if cancel_check is not None and cancel_check():
        raise CaptionPreparationCancelled()


def layout_layer(cue, language):
    """Apply the layer's measured face/size/scale before automatic arrangement.

    Absolute layer anchors remain a final manual override; they never become
    the shared group anchor or the other language's position.
    """
    from .caption_layer_transform import layer_values
    values=layer_values(cue,language)
    if not values:return cue
    shown=copy.copy(cue);shown.transform=dict(cue.transform or {})
    shown.transform.update({k:v for k,v in values.items() if k in {'font_size','scale_x','scale_y','rotation'}})
    if values.get('style_id'):shown.style_id=str(values['style_id'])
    return shown


def _display_cues(cues: Iterable[Any], *, translations: Mapping[str, str], settings: BilingualSettings,
                 styles, speakers, style_recipes, play_res_x: int = 1920, play_res_y: int = 1080,
                  show_speaker_names: bool = False, cancel_check=None, effects=None) -> list:
    """Cues to draw for ``settings`` (originals possibly adjusted, plus companions)."""
    cues = list(cues)
    from .caption_layer_transform import materialize_layer
    from .speaker_names import decorate, constrain_layout
    if show_speaker_names:
        cues=constrain_layout(cues,styles,speakers,play_res_x,play_res_y)
    if settings.mode == "original" or not translations:
        out = []
        for cue in cues:
            _check_preparation_cancelled(cancel_check)
            cue=motion_layout_layer(cue,'original',effects)
            out.append(materialize_layer(decorate(cue, speakers) if show_speaker_names else cue, 'original'))
        return out
    from .resolved_caption_style import resolve_caption_style
    out = []
    for cue in cues:
        _check_preparation_cancelled(cancel_check)
        text = str(translation_for_cue(translations, cue.id) or "").strip()
        group = cue.appearance_override.get('translation_group', {})
        if group: text = str(group.get('text') or text)
        if not text:
            cue=motion_layout_layer(cue,'original',effects)
            out.append(materialize_layer(decorate(cue, speakers) if show_speaker_names else cue,'original'))
            continue
        if settings.mode == 'bilingual' and theme_owns_translation(style_recipes, cue):
            shown=copy.deepcopy(cue)
            shown.appearance_override['_theme_translation']=text
            out.append(materialize_layer(shown,'original'))
            continue
        if show_speaker_names and settings.mode == 'bilingual' and settings.order == 'original_first':
            cue = decorate(cue, speakers)
        caption = resolve_caption_style(styles, speakers, cue, style_recipes, play_res_x, play_res_y)
        base = caption.style
        if settings.mode == "translation":
            shown = copy.deepcopy(cue)
            shown.text = text
            if show_speaker_names:
                shown = decorate(shown, speakers)
            shown = _with_transform(shown, font_size=round(base.font_size * settings.translation_scale, 2))
            font = _translation_font(settings, text, base)
            if font:
                shown.appearance_override = dict(shown.appearance_override or {}, font_family=font)
            _translation_appearance(cue, shown)
            shown=motion_layout_layer(shown,'translation',effects)
            out.append(materialize_layer(shown,'translation'))
            continue
        original = cue if settings.legacy else _with_transform(
            cue, font_size=cue.appearance_override.get('original', {}).get('font_size', round(base.font_size * settings.original_scale, 2)))
        original=motion_layout_layer(layout_layer(original,'original'),'original',effects)
        original_caption = caption if settings.legacy else resolve_caption_style(
            styles, speakers, original, style_recipes, play_res_x, play_res_y)
        companion = copy.deepcopy(cue)
        companion.id = companion_id(cue.id)
        companion.text = text
        # Exactly one prefix, on the top language line. Decorate before
        # measuring so long names participate in wrapping and group height.
        companion.__dict__.pop('_speaker_name_prefix', None)
        companion.__dict__.pop('_speaker_name_body', None)
        if show_speaker_names and settings.order == 'translation_first':
            companion = decorate(companion, speakers)
        companion.effect_id = "none"
        companion.raw_ass_override = ""
        companion.transform = {k: v for k, v in dict(cue.transform or {}).items() if k not in ("initial_layout",)}
        companion.transform["font_size"] = round(base.font_size * settings.translation_scale, 2)
        font = _translation_font(settings, text, base)
        if font:
            companion.appearance_override = dict(cue.appearance_override or {}, font_family=font)
        _translation_appearance(cue, companion)
        companion=motion_layout_layer(layout_layer(companion,'translation'),'translation',effects)
        companion_caption = resolve_caption_style(styles, speakers, companion, style_recipes, play_res_x, play_res_y)
        x, y = _anchor(original_caption.style, play_res_x, play_res_y)
        row = (int(base.alignment) - 1) // 3          # 0 bottom, 1 middle, 2 top
        if settings.layout == "ink_v1" and not settings.legacy:
            # One group: shared anchor and alignment, visible gap from real ink.
            original_block=motion_ink_block(original_caption,cue,'original',effects)
            companion_block=motion_ink_block(companion_caption,cue,'translation',effects)
            em = max(float(original_caption.style.font_size), float(companion_caption.style.font_size))
            translation_on_top = settings.order == "translation_first"
            top, bottom = ((companion_block, original_block) if translation_on_top else (original_block, companion_block))
            top_y, bottom_y = group_positions(y, row, top, bottom, settings.gap_ratio * em,
                play_res_y if automatic_group_layout(cue) else None)
            companion_y, original_y = (top_y, bottom_y) if translation_on_top else (bottom_y, top_y)
            clamp = lambda value: round(max(4.0, min(play_res_y - 4.0, value)))
            companion.transform.update(position_x=round(x), position_y=clamp(companion_y))
            original = _with_transform(original, position_x=round(x), position_y=clamp(original_y))
            out.extend((materialize_layer(original,'original'), materialize_layer(companion,'translation')))
            continue
        gap = settings.gap_ratio * float(companion_caption.style.font_size)
        original_h, companion_h = _block_height(original_caption), _block_height(companion_caption)
        upper_is_translation = settings.order == "translation_first"
        if row == 2:
            # Top-anchored: the upper line stays on the anchor, the lower moves down.
            if upper_is_translation:
                companion_y, original_y = y, y + companion_h + gap
            else:
                original_y, companion_y = y, y + original_h + gap
        else:
            # Bottom (and middle) anchored: the lower line stays on the anchor.
            if upper_is_translation:
                original_y, companion_y = y, y - original_h - gap
            else:
                companion_y, original_y = y, y - companion_h - gap
        companion.transform.update(position_x=round(x), position_y=round(max(4.0, min(play_res_y - 4.0, companion_y))))
        if original_y != y:
            original = _with_transform(original, position_x=round(x),
                                       position_y=round(max(4.0, min(play_res_y - 4.0, original_y))))
        out.extend((materialize_layer(original,'original'), materialize_layer(companion,'translation')))
    return out


def display_cues(cues, *, translations, settings, styles, speakers, style_recipes,
                 play_res_x=1920, play_res_y=1080, show_speaker_names=False, cancel_check=None,effects=None):
    source=list(cues)
    defaults=settings.group_transform.get('defaults',{})
    if defaults:
        updated=[]
        for cue in source:
            _check_preparation_cancelled(cancel_check)
            cue=copy.deepcopy(cue)
            layers=cue.transform.setdefault('language_layers',{})
            for language,fields in defaults.items():
                target=layers.setdefault(language,{})
                for key,value in fields.items():target.setdefault(key,value)
            updated.append(cue)
        source=updated
    rows=_display_cues(source,translations=translations,settings=settings,styles=styles,
        speakers=speakers,style_recipes=style_recipes,play_res_x=play_res_x,play_res_y=play_res_y,
        show_speaker_names=show_speaker_names,cancel_check=cancel_check,effects=effects)
    _check_preparation_cancelled(cancel_check)
    from .caption_group_transform import apply_display
    return apply_display(rows,source,settings.group_transform,styles,speakers,style_recipes,play_res_x,play_res_y)


def project_display_cues(project, cues=None, *, cancel_check=None) -> list:
    # The project's punctuation style (保留原文 / 添加标点 / 不加标点) applies to
    # everything drawn: live preview, ASS export and burn-in share this path.
    from ..subtitle_rules.punctuation_style import style_cues, style_translations
    from .speaker_names import enabled
    _check_preparation_cancelled(cancel_check)
    styled = style_cues(project, cues if cues is not None else project.cues)
    from ..glossary.visual_emphasis import visual_cues, snapshot_active
    snapshot = getattr(project, '_visual_glossary_snapshot', None)
    if snapshot is None:
        snapshot = snapshot_active(project)
    styled = visual_cues(styled, snapshot)
    return display_cues(styled,
                        translations=style_translations(project.studio_state,
                                                        translations_of(project.generation_metadata)),
                        settings=settings_from_state(project.studio_state), styles=project.styles,
                        show_speaker_names=enabled(project.studio_state),
                        speakers=project.speakers, style_recipes=project.style_recipes,effects=project.effects,
                        play_res_x=int(project.render_settings.get("play_res_x", 1920)),
                        play_res_y=int(project.render_settings.get("play_res_y", 1080)), cancel_check=cancel_check)


def materialize_display_project(project):
    """Freeze bilingual geometry once before splitting native/advanced exports.

    Preview already draws companion cues. Advanced export must receive those
    same cues, including translated text and font/position overrides. The copy
    is worker-local; its original mode prevents a later ASS pass adding a
    second companion or applying the font scale twice.
    """
    from .speaker_names import enabled
    names = enabled(project.studio_state)
    layers = any(c.transform.get('language_layers') or c.transform.get('language_motion') for c in project.cues)
    if settings_from_state(project.studio_state).mode == "original" and not names and not layers:
        return project
    if not translations_of(project.generation_metadata) and not names and not layers:
        return project
    from ..subtitle_rules.punctuation_style import mark_cues_styled
    result = copy.deepcopy(project)
    result.__dict__.pop("_studio_state_runtime", None)
    result.cues = project_display_cues(result)
    mark_cues_styled(result)
    result.studio_state["bilingual"] = {"mode": "original"}
    result.studio_state["bilingual_mode"] = False
    result.studio_state['show_speaker_names'] = False
    return result


def group_extra_for(project, cue, play_res_x: int = 1920) -> float:
    """Extra height (play-res px) a cue's translation line adds in the compact bilingual layout; 0 otherwise."""
    settings = settings_from_state(project.studio_state)
    text = str(translation_for_cue(translations_of(project.generation_metadata), cue.id) or "").strip()
    if settings.mode != "bilingual" or settings.layout != "ink_v1" or settings.legacy or not text:
        return 0.0
    from .resolved_caption_style import resolve_caption_style
    play_res_y = int(project.render_settings.get('play_res_y', 1080))
    base = resolve_caption_style(project.styles, project.speakers, cue, project.style_recipes, play_res_x, play_res_y).style
    original = _with_transform(cue, font_size=round(base.font_size * settings.original_scale, 2))
    companion = copy.deepcopy(cue)
    companion.text = text
    companion.transform = {k: v for k, v in dict(cue.transform or {}).items() if k != "initial_layout"}
    companion.transform["font_size"] = round(base.font_size * settings.translation_scale, 2)
    font = _translation_font(settings, text, base)
    if font:
        companion.appearance_override = dict(cue.appearance_override or {}, font_family=font)
    original_caption = resolve_caption_style(project.styles, project.speakers, original, project.style_recipes, play_res_x, play_res_y)
    companion_caption = resolve_caption_style(project.styles, project.speakers, companion, project.style_recipes, play_res_x, play_res_y)
    em = max(float(original_caption.style.font_size), float(companion_caption.style.font_size))
    return group_extra(ink_block(original_caption), ink_block(companion_caption), settings.gap_ratio * em,
                       settings.order == "translation_first")
