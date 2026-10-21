"""Native identities belong to the selected primary ASR, not another model."""
from dataclasses import dataclass

LABELS = {'native': '供应商原生标签', 'moss': 'MOSS 原生标签'}

def resolve(settings, override=None):
    """Legacy switches are inert; never change the selected primary recognizer."""
    primary = str(settings.get('models', {}).get('primary_asr_backend') or 'moss')
    return 'moss' if primary == 'moss' else 'native'

@dataclass(frozen=True)
class SpeakerPlan:
    source: str
    label: str
    steps: tuple[str, ...]

def execution_plan(settings, override=None):
    source=resolve(settings,override)
    steps=('主转写原生身份 → 所选字词对齐/复核 → 字幕',)
    return SpeakerPlan(source,LABELS[source],steps)
