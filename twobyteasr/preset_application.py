"""Authored preset patches; no inspector pixels or resolved fallbacks enter here."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from .studio_commands import SetCuesPresentationCommand
from .studio_project import SubtitleStyle
from .style_resolution import resolve_cue_visual, appearance_overrides_for_style

GEOMETRY = frozenset(('alignment', 'margin_l', 'margin_r', 'margin_v',
                      'position_x', 'position_y', 'scale_x', 'scale_y'))


def _merge(base, patch):
    result = deepcopy(base)
    for key, value in patch.items():
        result[key] = _merge(result.get(key, {}), value) if isinstance(value, dict) else deepcopy(value)
    return result


def preset_command(project, cue_ids, patch, *, apply_geometry=False, changed=None):
    """Only explicitly supplied fields overwrite; absent fields retain each cue."""
    fields = set(SubtitleStyle.__dataclass_fields__)
    preset_id = str(patch['id'])
    base = SubtitleStyle(**{k: v for k, v in patch.items() if k in fields})
    base.validate()
    styles = {s.id: deepcopy(s) for s in project.styles}
    # A changed library preset must not mutate unselected cues through a shared id.
    if preset_id in styles and styles[preset_id] != base and any(c.id not in cue_ids and (c.base_preset_id or c.style_id) == preset_id for c in project.cues):
        base.id = preset_id + '-revision-' + hashlib.sha256(json.dumps(asdict(base),sort_keys=True).encode()).hexdigest()[:10]
    styles[base.id] = base
    recipes = deepcopy(project.style_recipes)
    mapped = {}; overrides = {}; effects = {}
    for cue in project.cues:
        if cue.id not in cue_ids: continue
        authored = resolve_cue_visual(project, cue).style
        for key, value in patch.items():
            if key in fields - {'id', 'name'} and (apply_geometry or key not in GEOMETRY):
                setattr(authored, key, deepcopy(value))
        authored.name = base.name
        authored.validate()
        # A complete recipe replaces appearance/motion explicitly; a sparse
        # recipe merges only the sections/keys its author supplied.
        recipe = _merge(recipes.get(cue.style_id, {}), patch.get('recipe', {}))
        if recipe and 'primary_color' in patch and 'fill' not in patch.get('recipe', {}).get('colors', {}):
            # A supplied native solid fill is explicit too. A previous gradient
            # cannot survive merely because it equals the new preset base.
            recipe.setdefault('colors', {})['fill'] = authored.primary_color
        if recipe:
            recipe.setdefault('name', base.name)
        if not apply_geometry:
            layout = recipe.setdefault('layout', {}) if recipe else {}
            layout.update(alignment=authored.alignment, marginL=authored.margin_l,
                marginR=authored.margin_r, marginV=authored.margin_v,
                positionX=authored.position_x, positionY=authored.position_y)
        if recipe:
            from .style_recipe import StyleRecipe
            recipe = StyleRecipe.from_dict(recipe).to_dict()
        identity = asdict(authored); identity.pop('id')
        key = hashlib.sha256(json.dumps([identity, recipe],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
        authored.id = base.id if all(getattr(authored,k)==getattr(base,k) for k in fields-{'id'}) else preset_id+'-applied-'+key
        mapped[cue.id] = authored.id; styles[authored.id] = authored
        overrides[cue.id] = appearance_overrides_for_style(base, authored)
        if recipe: recipes[authored.id] = recipe
        effects[cue.id] = 'none' if 'motion' in patch.get('recipe', {}) else cue.effect_id
    command = SetCuesPresentationCommand(project, cue_ids, style_id=base.id, effect_id='none',
        style_ids=mapped, base_preset_id=base.id, appearance_overrides=overrides,
        effect_ids=effects, styles=list(styles.values()), style_recipes=recipes,
        merge_enabled=False,
        text='应用字幕预设', changed=changed)
    if command.before == command.after and command.before_styles == command.after_styles and command.before_style_recipes == command.after_style_recipes:
        return None
    return command
