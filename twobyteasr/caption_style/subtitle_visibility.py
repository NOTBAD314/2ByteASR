"""Independent original-speaker and generated-translation visibility."""
from .bilingual_layout import settings_from_state, translations_of, translation_for_cue, is_companion


def translation_key(project):
    from ..subtitle_rules.subtitle_translation import container_target
    return 'translation:'+container_target(project)


def layer_visible(project,cue,layer='original'):
    state=getattr(project,'studio_state',{}).get('subtitle_track_visibility',{})
    if not state.get('speaker:'+cue.speaker_id,True):
        return False
    from ..recognition.speaker_roles import GROUP_KEY, state_of
    # A group gate does not rewrite any child's original/translation eye.
    # Materialized translation companions retain their source speaker ID.
    roles = state_of(project)
    role = (roles.get('manual') or {}).get(cue.speaker_id) or (roles.get('auto') or {}).get(cue.speaker_id)
    if roles.get('grouped') and role == 'secondary' and not state.get(GROUP_KEY, True):
        return False
    if layer=='translation':
        return state.get(translation_key(project),state.get('translation',True))
    return state.get(cue.speaker_id,True) and cue.speaker_id not in getattr(project,'hidden_speaker_ids',lambda:())()


def any_layer_visible(project,cue,*,mode=None):
    layer=(cue.transform or {}).get('_language_materialized')
    if layer or is_companion(cue.id):
        return layer_visible(project,cue,layer or 'translation')
    mode=mode or settings_from_state(project.studio_state).mode
    translated=bool(translation_for_cue(translations_of(project.generation_metadata),cue.id))
    return (layer_visible(project,cue,'original') and (mode!='translation' or not translated)
            or mode in {'bilingual','translation'} and translated and layer_visible(project,cue,'translation'))


def display_layer_visible(project,cue):
    layer=(cue.transform or {}).get('_language_materialized') or ('translation' if is_companion(cue.id) else 'original')
    return layer_visible(project,cue,layer)
