# SPDX-License-Identifier: GPL-3.0-only
"""Current normal-entry removal checks under the existing owned audit guard."""
from pathlib import Path
import copy
import json


def steps(a, window, output, inputs):
    from PySide6.QtWidgets import QLabel
    from .model_workshop import MODELS, ModelCard
    from .runtime_paths import get_runtime_paths
    from .runtime_registry import RUNTIME_ROLES
    retired = {'vibevoice', 'vibevoice_1_5b', 'vibevoice_7b', 'diarizen', 'diarizen_embedding'}
    output = Path(output)
    a.result['scope'] = 'Normal daily Home/workshop/configuration after model removal; no inference or user project edits'
    a.check('actual intended executable', Path(a.result['executable']).resolve() == Path(inputs['expected_executable']).resolve())
    a.check('latest channel', a.result['identity']['build_channel'] == inputs['expected_channel'])
    a.check('normal Home', window.pages.currentWidget() is window.settings_scroll)
    before = copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
    models = before['models']
    a.result['initial_combination'] = {k:models.get(k) for k in ('primary_asr_backend','qwen_asr_backend','firered_asr_backend','speaker_source')}
    a.check('existing combination preserved', a.result['initial_combination'] == inputs['expected_combination'])
    a.check('Home selected primary agrees', window.primary_asr_backend.currentData() == models['primary_asr_backend'])
    a.check('Home has no retired primary choices', not retired.intersection(window.primary_asr_backend.itemData(i) for i in range(window.primary_asr_backend.count())))
    a.check('Home has no independent Diari choice', not retired.intersection(window.speaker_source.itemData(i) for i in range(window.speaker_source.count())))
    a.shot('daily-home')
    a.click(window.model_workshop_button); yield .5
    page = window.workshop_page
    a.check('actual normal workshop page', window.pages.currentWidget() is page)
    a.check('catalog has no removed models', not retired.intersection(m.key for m in MODELS))
    a.check('cards have no removed models', not retired.intersection(page._cards))
    a.check('existing MOSS and FireRed shared cards', isinstance(page._cards['moss'], ModelCard) and isinstance(page._cards['firered'], ModelCard))
    a.check('no remaining model names in workshop labels', not any(('DiariZen' in x.text() or 'VibeVoice' in x.text()) for x in page.findChildren(QLabel)))
    a.check('no removed runtime registration roles', not {'diarizen','vibevoice'}.intersection(RUNTIME_ROLES))
    lock = json.loads((get_runtime_paths().install_root/'dependencies.lock.json').read_text('utf-8-sig'))
    a.check('actual frozen install/download inventory excludes retired keys', not retired.intersection(lock['models']))
    a.shot('daily-workshop')
    # The initial detail already shows MOSS. Clicking its selected card is
    # the production cancel-use action, not a passive detail selection.
    a.check('MOSS detail selection retained', page.detail_model_key == 'moss')
    a.shot('daily-moss-detail')
    a.check('opening workshop does not rewrite model selection', window.legacy.RUNTIME_SETTINGS['models'] == before['models'])
    for rel in ('optional_model_worker.py', 'workers/optional_model_worker.py', 'third_party/DiariZen', 'third_party/VibeVoice', 'requirements-diarizen.lock', 'requirements-vibevoice.lock'):
        a.check('removed from actual bundle '+rel, not (get_runtime_paths().install_root/rel).exists())
