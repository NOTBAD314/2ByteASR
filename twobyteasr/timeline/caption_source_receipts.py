"""Task-bound source receipts; recovery never replaces an edited cue."""
import copy
from dataclasses import asdict

from .studio_caption_timeline import CLOCK, KEY


def source_span(cue, project):
    info = project.generation_metadata.get('timeline_recognition') or {}
    reference = project.generation_metadata.get('recognition_result') or {}
    instances = []
    for segment in (info.get('sequence') or {}).get('segments', []):
        a, b = max(cue.start_ms, segment['timeline_in_ms']), min(cue.end_ms, segment['timeline_out_ms'])
        if b > a:
            instances.append(dict(clip_id=segment['id'], task_start_ms=a, task_end_ms=b,
                                  source_path=segment['source_path']))
    return dict(source_cue_id=cue.id, source_start_ms=cue.start_ms, source_end_ms=cue.end_ms,
        source_text=cue.text, evidence_refs=list(cue.evidence_refs),
        task_fingerprint=info.get('fingerprint', ''), job_id=reference.get('job_id', ''),
        result_revision=reference.get('result_revision', ''), instances=instances)


def initialize_recognition_receipts(project, result):
    """New task cues are already in captured timeline time, not old source time."""
    from ..recognition.cue_word_alignment import cue_words
    instances = {}
    for cue in result.cues:
        words, reason = cue_words(result, cue)
        rows = [asdict(word) for word in words]
        span = source_span(cue, project)
        instances[cue.id] = dict(span, source_spans=[copy.deepcopy(span)],
            source_path=result.media.path, text=cue.text, words=rows, word_alignment=reason,
            word_base_interval=[cue.start_ms, cue.end_ms], word_base_words=copy.deepcopy(rows),
            word_base_alignment=reason)
        # Task cues and their evidence share the captured timeline clock.
        instances[cue.id][CLOCK] = 0
    project.studio_state[KEY] = dict(version=1, instances=instances,
        source_archive=[asdict(cue) for cue in result.cues])
    project.render_settings['_cue_domain'] = 'timeline'


def recover_caption_sources(project):
    """Read exactly the committed task, verify it, then repair missing ancestry."""
    if project.render_settings.get('_cue_domain') != 'timeline':
        return 0
    state = project.studio_state.setdefault(KEY, dict(version=1, instances={}))
    receipts = state.setdefault('instances', {})
    missing = [c for c in project.cues if not receipts.get(c.id, {}).get('source_spans')
               and not receipts.get(c.id, {}).get('source_end_ms')]
    if not missing:
        return 0
    from ..recognition.recognition_result import verify_result_reference, digest_payload
    reference = project.generation_metadata.get('recognition_result') or {}
    if not reference:
        return 0
    try:
        original = verify_result_reference(reference)
        if original.project_id != project.project_id:
            raise ValueError('任务工程 ID 不一致')
        task = project.generation_metadata.get('timeline_recognition') or {}
        if task.get('fingerprint') != (original.generation_metadata.get('timeline_recognition') or {}).get('fingerprint'):
            raise ValueError('任务时间轴指纹不一致')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        state['source_recovery'] = dict(status='unavailable', reason=str(exc))
        return 0
    sources = {c.id: c for c in original.cues}
    recovered = 0
    for cue in missing:
        receipt = receipts.get(cue.id, {})
        parent_ids = receipt.get('source_cue_ids') or [receipt.get('source_cue_id') or cue.id]
        parents = [sources[key] for key in parent_ids if key in sources]
        refs = set(cue.evidence_refs)
        if (not parents or len(parents) != len(parent_ids) or not refs
                or not refs.issubset({ref for parent in parents for ref in parent.evidence_refs})
                or any(digest_payload(project.asr_evidence.get(ref)) != digest_payload(original.asr_evidence.get(ref)) for ref in refs)):
            continue
        receipt = receipts.setdefault(cue.id, {})
        spans = [source_span(parent, original) for parent in parents]
        receipt['source_spans'] = spans
        receipt['source_cue_ids'] = list(parent_ids)
        receipt['source_start_ms'] = min(parent.start_ms for parent in parents)
        receipt['source_end_ms'] = max(parent.end_ms for parent in parents)
        recovered += 1
    # Archive only the verified immutable result; existing archives remain intact.
    if recovered and not state.get('source_archive'):
        state['source_archive'] = [asdict(cue) for cue in original.cues]
    state['source_recovery'] = dict(status='recovered' if recovered == len(missing) else 'partial',
        recovered=recovered, unresolved=len(missing)-recovered, job_id=reference['job_id'],
        result_revision=reference['result_revision'])
    return recovered
