"""Translate an immutable text version while acoustic timing is refined."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace


def binding(cues, context):
    material = [context.task_language, context.subtitle_output, context.translation_script,
                [(str(cue.cue_id), cue.text, str(getattr(cue, 'speaker', 'S00'))) for cue in cues]]
    return hashlib.sha256(json.dumps(material,ensure_ascii=False).encode('utf-8')).hexdigest()


class TranslationTask:
    def __init__(self, cues, context, legacy):
        from .run_context import ContextExecutor
        self.context, self.legacy = context, legacy
        self.binding = binding(cues, context)
        # Only translation's actual inputs: no project/evidence deep copy.
        frozen = [SimpleNamespace(cue_id=cue.cue_id, text=cue.text, start=cue.start, end=cue.end,
                                  speaker=str(getattr(cue,'speaker','S00'))) for cue in cues]
        self.pool = ContextExecutor(max_workers=1,thread_name_prefix='ready-translation')
        self.future = self.pool.submit(self._run, frozen)

    def _run(self, cues):
        from .pipeline_activity import work
        from ..subtitle_rules.recognition_translation import translate_runtime_cues
        with self.legacy.capture_review_items() as reviews:
            with work(self.legacy, 'translation', '字幕翻译', total=len(cues)):
                result = translate_runtime_cues(cues, self.context, self.legacy)
        return result, list(reviews)

    def result(self, cues):
        from .run_context import context_is_current
        value, reviews = self.future.result()
        if not context_is_current(self.context) or binding(cues,self.context) != self.binding:
            self.legacy.record_run_event('translation_late_result_rejected', input_version=self.binding)
            return None
        self.legacy.extend_review_items(reviews)
        return value

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


def start(cues, context, legacy):
    if context.subtitle_output == 'original' or not cues:
        return None
    return TranslationTask(cues,context,legacy)
