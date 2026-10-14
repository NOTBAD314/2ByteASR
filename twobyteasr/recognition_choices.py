"""Plan choices that match this computer, and what a run will actually use (2026-10-13).

``host_profile`` is cheap (no PyTorch, no network): OS, CPU architecture,
whether NVIDIA tooling exists, whether the local model runtime and an MLX
runtime are registered. ``plan_options`` turns that plus installed models and
saved cloud keys into the plans a user can pick; unavailable plans carry a
reason instead of disappearing silently. ``run_disclosure`` is the pre-run
summary: engine, speaker source, timestamp source, upload destination, cost.
Nothing here switches providers or plans on failure; it only describes.
"""
from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass, field

CUDA_TIMELINE = {'local'}             # FireRed AED
CUDA_REVIEW = {'local', 'firered_llm'}
CPU_TIMELINE = {'qwen_aligner', 'whisper_turbo', 'paraformer'}
# 2026-10-14: on an Apple Silicon Mac MOSS and FireRed AED run on the Apple GPU
# (MPS) once the model workshop prepared them (macos_model_prepare.prepare_local).
APPLE_GPU_PRIMARY = {'moss', 'firered'}
APPLE_GPU_TIMELINE = {'local'}
APPLE_GPU_PLAN_MODELS = frozenset({'moss', 'firered_vad', 'speaker_embedding', 'firered_aed'})
MLX_PRIMARY = {'mlx_qwen3_asr': 'Apple Silicon 本地 Qwen3-ASR 0.6B（MLX）',
               'mlx_qwen3_asr_1_7b': 'Apple Silicon 本地 Qwen3-ASR 1.7B（MLX）'}
REVIEW_LABELS = {'api': '云端识别服务', 'whisper_turbo': 'Whisper', 'sensevoice': 'SenseVoice',
                 'funasr_nano': 'Fun-ASR Nano', 'firered_llm': 'FireRed LLM'}


@dataclass(frozen=True)
class HostProfile:
    system: str
    machine: str
    nvidia_tool: bool
    main_runtime: bool
    mlx_runtime: bool
    moss_runtime: bool = False

    @property
    def apple_silicon(self) -> bool:
        return self.system == 'darwin' and self.machine in {'arm64', 'aarch64'}

    @property
    def intel_mac(self) -> bool:
        return self.system == 'darwin' and not self.apple_silicon

    @property
    def cuda_possible(self) -> bool:
        return self.system != 'darwin' and self.nvidia_tool


def host_profile() -> HostProfile:
    from .runtime_registry import resolve_runtime_python
    import os

    def exists(role):
        try:
            python = resolve_runtime_python(role)
        except Exception:
            return False
        return bool(python) and os.path.isfile(python)

    return HostProfile(sys.platform, platform.machine().lower(), bool(shutil.which('nvidia-smi')),
                       exists('main'), exists('mlx') if _role_known('mlx') else False, exists('moss'))


def _role_known(role):
    try:
        from .runtime_registry import RUNTIME_ROLES
        return role in RUNTIME_ROLES
    except Exception:
        return False


CUDA_PRIMARY = {'moss', 'firered', 'qwen_local', 'firered_llm'}


def unavailable_on_host(role: str, backend: str, host: HostProfile | None = None) -> str:
    """Why this installed component cannot run on this computer ('' if it can).

    Cheap (no PyTorch): used before a run starts so a user without an NVIDIA
    GPU sees the limit and a workable plan instead of a failure after start.
    """
    host = host or host_profile()
    needs_cuda = {'primary': CUDA_PRIMARY, 'timeline': CUDA_TIMELINE, 'review': CUDA_REVIEW}.get(role, set())
    if backend in needs_cuda and not host.cuda_possible:
        if host.system == 'darwin' and backend in {'primary': APPLE_GPU_PRIMARY,
                                                   'timeline': APPLE_GPU_TIMELINE}.get(role, set()):
            return '' if host.apple_silicon else '只能在 Apple Silicon Mac 上运行'
        return '需要 NVIDIA 显卡'
    if backend in {'mlx_qwen3_asr', 'mlx_qwen3_asr_1_7b', 'mlx_qwen_aligner'} and not host.apple_silicon:
        return '只能在 Apple Silicon Mac 上运行'
    return ''


def cloud_followups(models: dict, installed: set, host: HostProfile) -> tuple[dict, list]:
    """Timeline/review values that can actually run once the primary is cloud.

    A valid existing choice is kept. A CUDA-only choice on a machine without
    NVIDIA, or a choice whose model is missing, becomes "off" (cloud times
    only) — or the installed CPU aligner, which never uploads anything.
    """
    patch, notes = {}, []
    timeline = str(models.get('firered_asr_backend', 'local'))
    needs = {'local': 'firered_aed', 'qwen_aligner': 'qwen_aligner', 'whisper_turbo': 'whisper_turbo',
             'paraformer': 'paraformer', 'mlx_qwen_aligner': 'mlx_qwen_aligner'}
    mlx_aligner_ready = 'mlx_qwen_aligner' in installed and host.apple_silicon and host.mlx_runtime
    aligner_ready = 'qwen_aligner' in installed and host.main_runtime
    firered_on_mac = host.apple_silicon and 'firered_aed' in installed and host.main_runtime
    if timeline in CUDA_TIMELINE and not host.cuda_possible and not firered_on_mac:
        fallback = 'mlx_qwen_aligner' if mlx_aligner_ready else 'qwen_aligner' if aligner_ready else 'off'
        patch['firered_asr_backend'] = fallback
        notes.append(('FireRed 字幕时间轴还没有在模型工坊准备好（Apple 芯片 GPU）；已改为' if host.apple_silicon
                      else '这台电脑没有 NVIDIA 显卡，FireRed 字幕时间轴不能运行；已改为')
                     + {'mlx_qwen_aligner': '本地 Qwen3 对齐（Apple Silicon）。',
                        'qwen_aligner': '本地 Qwen3 对齐（CPU）。'}.get(fallback, '只用云端返回的时间。'))
    elif timeline == 'mlx_qwen_aligner' and not host.apple_silicon:
        patch['firered_asr_backend'] = 'qwen_aligner' if aligner_ready else 'off'
        notes.append('MLX 对齐只能在 Apple Silicon Mac 上运行；已改为'
                     + ('本地 Qwen3 对齐（CPU）。' if aligner_ready else '只用云端返回的时间。'))
    elif timeline in needs and needs[timeline] not in installed:
        patch['firered_asr_backend'] = 'off'
        notes.append('所选字幕时间轴模型没有安装；已改为只用云端返回的时间。')
    review = str(models.get('qwen_asr_backend', 'off'))
    if review in CUDA_REVIEW and not host.cuda_possible:
        patch['qwen_asr_backend'] = 'off'
        notes.append('文字复核模型需要 NVIDIA 显卡，已关闭文字复核。')
    return patch, notes


def cloud_asr_readiness(models: dict, *, typed_key: str = '') -> tuple[bool, str]:
    """Can the saved cloud ASR provider run now? (ready, plain reason if not).

    More than "a key is saved": a Token Plan key cannot run 录音文件识别, and a
    user who chose their own OSS needs the bucket and AccessKey.
    """
    from .llm_config import read_asr_api_key
    from .dashscope_service import is_token_plan_key
    models = models or {}
    provider = str(models.get('qwen_asr_api_provider') or 'qwen31_filetrans')
    url = str(models.get('qwen_asr_api_url') or '')
    key = typed_key.strip() or read_asr_api_key(provider, url)[0]
    if not key:
        return False, '还没有填写云端识别服务的 API Key。'
    if str(models.get('qwen_asr_api_protocol') or '') == 'dashscope_filetrans':
        if is_token_plan_key(key):
            return False, '保存的是 Token Plan 订阅 Key（sk-sp-），不能做录音文件识别；请换成按量付费的 API Key。'
        from .api_setup_catalog import MISSING_UPLOAD_MESSAGE, UPLOAD_MISSING, UPLOAD_OWN_OSS, resolve_upload_mode
        mode = resolve_upload_mode(models, provider)
        if mode == UPLOAD_MISSING:
            return False, MISSING_UPLOAD_MESSAGE
        if mode == UPLOAD_OWN_OSS:
            from .llm_config import read_oss_credentials
            if not str(models.get('oss_bucket') or '').strip() or not all(read_oss_credentials()):
                return False, '选了“我自己的 OSS 私有存储”，但 Bucket 或 AccessKey 还没填完整。'
    return True, ''


@dataclass
class PlanOption:
    key: str
    title: str
    summary: str
    available: bool
    reason: str = ''
    patch: dict = field(default_factory=dict)


def plan_options(settings: dict, installed: set, host: HostProfile, cloud_ready: dict) -> list[PlanOption]:
    """Plans for this computer. ``cloud_ready`` maps provider -> key saved."""
    models = (settings or {}).get('models', {})
    provider = str(models.get('qwen_asr_api_provider') or '')
    cloud_ok = bool(cloud_ready.get(provider))
    aligner_ok = 'qwen_aligner' in installed and host.main_runtime
    mlx_models = [key for key in ('mlx_qwen3_asr_0_6b', 'mlx_qwen3_asr_1_7b') if key in installed]
    mlx_ok = host.apple_silicon and host.mlx_runtime and bool(mlx_models)
    options = [
        PlanOption('cloud_only', '云端识别，不下载本地模型',
                   '音频上传到你选的云服务；不需要显卡、PyTorch 或本地模型。时间精度取决于服务（句段或字/词级）。',
                   cloud_ok, '' if cloud_ok else '还没有设置云端识别服务的 API Key（模型工坊 →“在线 API”）。',
                   {'primary_asr_backend': 'api', 'firered_asr_backend': 'off', 'qwen_asr_backend': 'off'}),
        PlanOption('cloud_plus_align', '云端识别 + 本地精细对齐',
                   '云端负责文字与说话人，本机 Qwen3 对齐模型（可用 CPU）补上字级时间；对齐不上传任何东西。',
                   cloud_ok and aligner_ok,
                   '' if cloud_ok and aligner_ok else '需要云端 API Key，并在模型工坊“字幕时间轴”页安装 Qwen3 对齐模型。',
                   {'primary_asr_backend': 'api', 'firered_asr_backend': 'qwen_aligner', 'qwen_asr_backend': 'off'}),
    ]
    if host.system == 'darwin':
        options.append(PlanOption(
            'apple_local', 'Apple Silicon 本地识别（MLX）',
            '在本机用 MLX 运行 Qwen3-ASR 与对齐模型，不上传音频。社区 MLX 实现，兔白尚未在真机完成验收。',
            mlx_ok, '' if mlx_ok else ('Intel Mac 不能使用 MLX。' if host.intel_mac
                                     else '需要在模型工坊安装 MLX 版 Qwen3-ASR（Apple Silicon）。'),
            {'primary_asr_backend': 'mlx_qwen3_asr' if mlx_models[:1] != ['mlx_qwen3_asr_1_7b']
             else 'mlx_qwen3_asr_1_7b', 'firered_asr_backend': 'mlx_qwen_aligner'
             if 'mlx_qwen_aligner' in installed else 'off', 'qwen_asr_backend': 'off'}))
        gpu_ok = (host.apple_silicon and host.main_runtime and host.moss_runtime
                  and APPLE_GPU_PLAN_MODELS <= set(installed))
        options.append(PlanOption(
            'apple_gpu_local', 'Apple 芯片本地高质量（MOSS + FireRed）',
            '在本机 Apple 芯片 GPU（MPS）上运行 MOSS（文字与说话人）和 FireRed（字级时间），不上传音频；'
            '建议 16 GB 以上内存，速度比 NVIDIA 显卡慢。',
            gpu_ok, '' if gpu_ok else ('Intel Mac 没有 Apple 芯片 GPU。' if host.intel_mac
                                     else '需要在模型工坊准备 MOSS 与 FireRed（Apple 芯片 GPU）。'),
            {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}))
    else:
        cuda_ok = host.cuda_possible and {'moss', 'firered_aed'} <= installed
        options.append(PlanOption(
            'windows_cuda', 'NVIDIA 显卡本地高质量（MOSS + FireRed + Qwen）',
            '全部在本机运行，不上传音频；需要 NVIDIA 显卡与已下载的模型。', cuda_ok,
            '' if cuda_ok else ('这台电脑没有检测到 NVIDIA 显卡工具。' if not host.cuda_possible
                                else '需要先在模型工坊下载 MOSS 与 FireRed。'),
            {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'local'}))
    cpu_ok = 'sensevoice' in installed and host.main_runtime
    options.append(PlanOption(
        'cpu_local', 'CPU 本地识别（SenseVoice）',
        '不需要显卡、不上传音频；速度较慢，没有说话人区分。', cpu_ok,
        '' if cpu_ok else '需要在模型工坊准备 SenseVoice（CPU）。',
        {'primary_asr_backend': 'sensevoice', 'firered_asr_backend': 'qwen_aligner' if aligner_ok else 'off',
         'qwen_asr_backend': 'off'}))
    return options


def run_disclosure(settings: dict) -> dict:
    """What this recognition run will use — shown before it starts."""
    models = (settings or {}).get('models', {})
    switches = (settings or {}).get('switches', {})
    primary = str(models.get('primary_asr_backend', 'moss'))
    timeline = str(models.get('firered_asr_backend', 'off'))
    review = str(models.get('qwen_asr_backend', 'off'))
    info = {'engine': primary, 'speakers': '', 'timestamps': '', 'uploads': [], 'cost': [], 'local': []}
    if primary == 'api':
        from .api_setup_catalog import guide_for, model_choice
        from urllib.parse import urlsplit
        provider = str(models.get('qwen_asr_api_provider') or '')
        model = str(models.get('qwen_asr_api_model') or '')
        guide = guide_for(provider, 'asr')
        label = guide.title if guide else provider
        info['engine'] = f"{label} · {model}"
        choice = model_choice(guide, model) if guide else None
        host = urlsplit(str(models.get('qwen_asr_api_url') or '')).hostname or ''
        info['uploads'].append(f"音频 → {label}（{host}）")
        from .api_setup_catalog import FILETRANS_GUIDES, UPLOAD_OWN_OSS, UPLOAD_PROVIDER, resolve_upload_mode
        if guide is not None and guide.key in FILETRANS_GUIDES:
            mode = resolve_upload_mode(models, guide.key)
            if mode == UPLOAD_OWN_OSS:
                info['uploads'].append(f"音频先放到你的 OSS 私有存储：{models.get('oss_bucket') or '（未设置）'}，"
                                       '服务商用限时签名链接读取，取回结果后删除')
            elif mode == UPLOAD_PROVIDER:
                info['uploads'].append('音频先上传到服务商临时空间（你选的“仅供试用”方式：48 小时后由服务商删除，'
                                       '官方说明勿用于生产）')
            else:
                info['uploads'].append('还没有设置音频交给服务商的方式：开始前会停下，不上传')
        if guide is not None and guide.cost:
            info['cost'].append(guide.cost)
        if choice is not None:
            info['speakers'] = '云端模型返回的说话人' if choice.speakers else '没有说话人区分（单轨）'
            native = '云端返回的字/词级时间' if choice.timestamps == 'word' else '云端返回的句段时间（不是逐字时间）'
        else:
            info['speakers'] = '取决于服务返回'
            native = '云端返回的时间'
    elif primary == 'moss':
        info['engine'] = '本地 MOSS'
        info['speakers'] = 'MOSS 原生说话人'
        native = 'MOSS 句段时间'
        info['local'].append('MOSS（Apple 芯片 GPU）' if sys.platform == 'darwin' else 'MOSS（需要 NVIDIA 显卡）')
    elif primary in MLX_PRIMARY:
        info['engine'] = MLX_PRIMARY[primary]
        info['speakers'] = '没有说话人区分（单轨）'
        native = '语音段（VAD 窗口）范围，不是逐字时间'
        info['local'].append(MLX_PRIMARY[primary])
    else:
        info['engine'] = f'本地 {primary}'
        info['speakers'] = '没有说话人区分（单轨）' if primary in {'sensevoice', 'whisper_turbo', 'paraformer'} else '取决于模型'
        native = '模型自带的时间'
        info['local'].append(primary)
    if timeline in {'qwen_aligner', 'mlx_qwen_aligner'}:
        info['timestamps'] = '本地 Qwen3 对齐模型实测的字/词时间（对不上的地方保留' + native + '并标为估算）'
        info['local'].append('Qwen3 对齐模型（Apple Silicon 用 MLX）' if timeline == 'mlx_qwen_aligner'
                             else 'Qwen3 对齐模型（无 NVIDIA 显卡时用 CPU）')
    elif timeline == 'local':
        info['timestamps'] = ('FireRed 字级时间轴（Apple 芯片 GPU）' if sys.platform == 'darwin'
                              else 'FireRed 字级时间轴（需要 NVIDIA 显卡）')
        info['local'].append('FireRed')
    elif timeline == 'off':
        info['timestamps'] = native
    else:
        info['timestamps'] = f'{timeline} 时间轴'
        info['local'].append(timeline)
    info['notes'] = []
    if review == 'local':
        info['local'].append('文字复核：本地 Qwen3-ASR（需要 NVIDIA 显卡）')
    elif review == 'api' and primary != 'api':
        # 2026-10-14: the review stage runs again (probe fix). A cloud review
        # sends the whole task audio to the saved cloud service once more.
        from .api_setup_catalog import guide_for
        provider = str(models.get('qwen_asr_api_provider') or '')
        guide = guide_for(provider, 'asr')
        label = guide.title if guide else (provider or '云端识别服务')
        # Starts with “音频” on purpose: the home page asks once before any
        # “音频…” upload line (``_confirm_run_disclosure``).
        info['uploads'].append(f'音频（文字复核，整段）→ {label}（另计一次识别费用）')
        if guide is not None and guide.cost:
            info['cost'].append('文字复核：' + guide.cost)
    elif review not in {'off', 'api', primary}:
        info['local'].append(f'文字复核：本地 {REVIEW_LABELS.get(review, review)}')
    text_ai = [label for key, label in (('enable_ai_polish', 'AI 校对'), ('use_ai_grouping', 'AI 断句'))
               if switches.get(key)]
    if text_ai:
        info['uploads'].append('字幕文字 → 文字 AI 服务（' + '、'.join(text_ai) + '）')
    info['paid'] = bool(info['cost'] or primary == 'api' or text_ai)
    return info


def disclosure_text(settings: dict) -> str:
    info = run_disclosure(settings)
    lines = [f"识别引擎：{info['engine']}", f"说话人：{info['speakers']}", f"时间戳：{info['timestamps']}"]
    lines.append('会上传：' + ('；'.join(info['uploads']) if info['uploads'] else '不上传（全部在本机运行）'))
    lines.extend(info.get('notes') or ())
    if info['cost']:
        lines.append('费用：' + '；'.join(info['cost']))
    elif info['paid']:
        lines.append('费用：按所选服务商的规则计费')
    else:
        lines.append('费用：不产生云端费用')
    lines.append('失败时：不会自动改用其他云服务或付费服务；本地失败也不会偷偷改用云端。')
    return '\n'.join(lines)
