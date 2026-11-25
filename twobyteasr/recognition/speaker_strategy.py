"""Native identities belong to the selected primary ASR, not another model."""
from dataclasses import dataclass

LABELS = {'native': '供应商原生标签', 'moss': 'MOSS 原生标签',
          'single': '单轨', 'ecapa': '本机独立说话人分离'}

def resolve(settings, override=None):
    """Legacy switches are inert; never change the selected primary recognizer."""
    models = settings.get('models', {})
    primary = str(models.get('primary_asr_backend') or 'moss')
    if primary == 'haas_ja':
        return 'ecapa' if models.get('haas_diarization') else 'single'
    return 'moss' if primary == 'moss' else 'native'

def speakers_turned_off(settings):
    """The user turned speakers off for the selected online recognizer: one lane.

    2026-11-22 (user): Qwen Audio 3.1 from the official Qwen API with 区分说话人
    off still gave eight lanes in a 4 h stream. The primary text was all S00;
    every recovered gap had its own ``RECOVERY_<sample>`` label and FireRed's
    extra words under the S00 lines were added as a "second voice".
    """
    models = (settings or {}).get('models', {}) or {}
    if models.get('primary_asr_backend') == 'haas_ja':
        return not models.get('haas_diarization')
    if str(models.get('primary_asr_backend') or 'moss') != 'api':
        return False
    from twobyteasr.providers.asr_api_process import qwen_diarize_hint
    endpoint = dict(provider=str(models.get('qwen_asr_api_provider') or 'qwen31_filetrans').strip(),
                    model=str(models.get('qwen_asr_api_model') or 'qwen-audio-3.1-asr-flash-filetrans').strip())
    return qwen_diarize_hint(endpoint, settings).get('filetrans_diarize') is False

@dataclass(frozen=True)
class SpeakerPlan:
    source: str
    label: str
    steps: tuple[str, ...]

def execution_plan(settings, override=None):
    source=resolve(settings,override)
    steps=(('Haas 转写 → 本机独立分离 → 字词对齐/复核 → 字幕' if source == 'ecapa'
            else '主转写 → 单轨字词对齐/复核 → 字幕' if source == 'single'
            else '主转写原生身份 → 所选字词对齐/复核 → 字幕'),)
    return SpeakerPlan(source,LABELS[source],steps)
