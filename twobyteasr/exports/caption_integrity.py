"""Do not silently treat a previously nonempty source as an intended blank."""


def require_confirmed_empty_sources(project, cues=None, *, start_ms=None, end_ms=None):
    from ..subtitle_rules.current_issues import DECISIONS, reviewed_version
    from ..timeline.studio_edit_sequence import source_cue_id_of
    from ..caption_style.bilingual_layout import settings_from_state,translations_of,translation_for_cue
    decisions=project.studio_state.get(DECISIONS,{})
    if not isinstance(decisions,dict):decisions={}
    canonical={cue.id:cue for cue in project.cues}
    hidden=project.hidden_speaker_ids()
    visibility=project.studio_state.get('subtitle_track_visibility',{})
    translation_only=settings_from_state(project.studio_state).mode=='translation'
    translations=translations_of(project.generation_metadata) if translation_only else {}
    uncertain={}
    for view in project.cues if cues is None else cues:
        if (view.id.endswith('#tr') or view.speaker_id in hidden or not visibility.get(view.speaker_id,True)
                or start_ms is not None and view.end_ms<=start_ms
                or end_ms is not None and view.start_ms>=end_ms):
            continue
        cue=canonical.get(view.id) or canonical.get(source_cue_id_of(view.id)) or view
        if translation_only:
            text=translation_for_cue(translations,cue.id)
            text=(cue.appearance_override.get('translation_group') or {}).get('text') or text
            if str(text or '').strip():continue  # This mode does not display the original.
        if str(cue.text).strip() or not str(cue.original_text).strip():
            continue
        reviewed=decisions.get('reviewed:'+cue.id,{})
        if not isinstance(reviewed,dict):reviewed={}
        if (reviewed.get('status')=='resolved' and reviewed.get('input_version')==reviewed_version(project,cue)):
            continue
        uncertain[cue.id]=cue
    if uncertain:
        ids='、'.join(list(uncertain)[:3])
        raise ValueError(f'有 {len(uncertain)} 条原文为空，但保留着非空原稿（ID {ids}）。'
                         '为避免漏烧，尚未开始导出；请核对并恢复，或明确审核确认这条空字幕后重试。')
