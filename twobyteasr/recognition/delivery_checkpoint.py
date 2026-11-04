"""Retry final translation/project/report publication without repeating ASR."""
from __future__ import annotations

import copy
import hashlib
import json
import time

from .task_journal import public_config, digest

_FIELDS = ('task_language', 'requested_language', 'language_evidence', 'language_mode', 'language_decision',
           'review_items', 'speaker_recovery', 'transcript_acceptance', 'terminology_status', 'polishing_summary',
           'asr_manifest_key', 'asr_provisional_cues', 'recognition_snapshot', 'media_identity', 'studio_project_path')


def dependency(context):
    import subtitle_core
    from ..providers.asr_provider_snapshot import GROUP_CACHE_VERSION,GROUP_PROMPT_VERSION,POLISH_PROMPT_VERSION
    from ..subtitle_rules.segmentation_profiles import VERSION as LANGUAGE_RULE_VERSION
    from ..subtitle_rules.number_fidelity import RULE_VERSION as NUMBER_RULE_VERSION
    from .transcript_fidelity import RULE_VERSION as FIDELITY_RULE_VERSION
    settings = public_config(context.asr_settings_snapshot)
    # Throughput and rerun switches do not change the already computed text.
    for key in ('performance', 'cache', 'updates', 'ui', 'storage'):
        settings.pop(key, None)
    return {'version': 2, 'input': context.media_identity.get('fingerprint'),
            'rules':{'group_cache':GROUP_CACHE_VERSION,'group_prompt':GROUP_PROMPT_VERSION,
                     'polish_prompt':POLISH_PROMPT_VERSION,'language':LANGUAGE_RULE_VERSION,
                     'numbers':NUMBER_RULE_VERSION,'fidelity':FIDELITY_RULE_VERSION,
                     'timing':getattr(subtitle_core,'TIMING_LOGIC_VERSION','')},
            'settings': settings, 'language': context.requested_language,
            'output': context.subtitle_output, 'translation': context.translation_script,
            'script': context.chinese_script, 'glossary': (context.glossary_snapshot.to_dict()
                if context.glossary_snapshot is not None else {})}


def save(context, legacy, arguments, *, translation=None):
    journal = getattr(context, 'task_journal', None)
    if journal is None:
        return
    values = {k:v for k,v in arguments.items() if k not in {'legacy','runtime_context','started','cues','segments'}}
    values['cues'] = legacy.serialize_cues(arguments['cues'])
    for row, cue in zip(values['cues'], arguments['cues']):
        if hasattr(cue, 'forced_alignment'):
            row['forced_alignment'] = copy.deepcopy(cue.forced_alignment)
    values['segments'] = legacy.serialize_segments(arguments['segments'])
    for row, segment in zip(values['segments'], arguments['segments']):
        if hasattr(segment, 'caption_arbitration'):
            row['caption_arbitration'] = copy.deepcopy(segment.caption_arbitration)
    report = getattr(legacy.task_reporting, '_active_report', None) or {}
    payload = {'arguments': values, 'context': {k:copy.deepcopy(getattr(context,k)) for k in _FIELDS if hasattr(context,k)},
               'report': {k:copy.deepcopy(v) for k,v in report.items() if k != 'events'}, 'translation': translation}
    journal.publish(f'delivery:{context.media_index}', payload, dependency(context))


def load(context):
    journal = getattr(context, 'task_journal', None)
    if not journal or not getattr(context, 'resume', False) or context.retry_incomplete:
        return None
    return journal.load_artifact(f'delivery:{context.media_index}', dependency(context))


def resume(context, legacy, payload):
    from .pipeline_runtime import complete_media_run
    arguments = dict(payload['arguments'])
    arguments['cues'] = legacy.deserialize_cues(arguments['cues'])
    arguments['segments'] = legacy.deserialize_segments(arguments['segments'])
    for cue, row in zip(arguments['cues'], payload['arguments']['cues']):
        if 'forced_alignment' in row:
            cue.forced_alignment = row['forced_alignment']
    for segment, row in zip(arguments['segments'], payload['arguments']['segments']):
        if 'caption_arbitration' in row:
            segment.caption_arbitration = row['caption_arbitration']
    for key, value in payload['context'].items():
        setattr(context, key, value)
    # The compatibility facade keeps aliases to mutable runtime lists. Rebind
    # them after restoring a checkpoint, or review/failure records disappear
    # from the final report even though they still exist on the context.
    from .run_context import sync_legacy_runtime
    sync_legacy_runtime(legacy,context)
    from .shard_identity import repair_terminal
    if repair_terminal(arguments['segments'],arguments['cues'],context.task_journal.record['task'].get('remote_requests',{})):
        from pathlib import Path
        context.studio_project_path=str(Path(context.studio_project_path).parent/'recovered-evidence'/'project.2byteproj')
        legacy.record_run_event('delivery_source_ids_recovered',segments=len(arguments['segments']),model_calls=0)
    legacy.task_reporting._active_report = dict(payload['report'], events=[])
    legacy.task_reporting._active_report['status'] = 'running'
    if context.polishing_summary:
        legacy.task_reporting._active_report['polishing_summary']=copy.deepcopy(context.polishing_summary)
    if payload.get('translation') is not None:
        binding = hashlib.sha256(json.dumps([(str(c.cue_id),c.text,c.speaker) for c in arguments['cues']],
            ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()
        context.translation_ready = {'binding': binding, 'metadata': payload['translation']}
    arguments.update(legacy=legacy,runtime_context=context,started=time.perf_counter())
    legacy.record_run_event('delivery_checkpoint_resumed', cues=len(arguments['cues']), model_calls=0)
    return complete_media_run(**arguments)


def all_ready(context, paths):
    """Check the real input before bypassing model/environment preparation."""
    if not context.resume or context.recognition_snapshot or not paths:
        return False
    from .recognition_result import media_identity_for_task
    previous=(context.media_index,context.media_identity)
    try:
        for index,path in enumerate(paths,1):
            context.media_index=index
            context.media_identity=media_identity_for_task(path,context)
            if load(context) is None:
                return False
        return True
    finally:
        context.media_index,context.media_identity=previous
