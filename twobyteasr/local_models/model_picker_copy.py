# SPDX-License-Identifier: GPL-3.0-only
"""Short card copy, prices and role recommendations of the home model picker.

2026-11-12 (user, picker design B): every card says in one line what the
model is good at; cloud cards add their price (only the prices the author
gave are shown; a missing price is left out rather than guessed). Local
models never show a price. Each role has its own recommendations, shown
first and marked 推荐:

- 主力转写: MOSS Pro (cloud, several speakers).
- 字幕时间轴: Qwen3 对齐模型 and FireRedASR2-AED.
- 文字复核: Qwen3-ASR 1.7B only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PickerCopy:
    line: str                      # one short sentence of what it is good at
    price: str = ''                # cloud price per hour of audio; '' = not shown
    tags: tuple[str, ...] = ()     # filter chips it matches: speakers / dialect / multilingual


PICKER_COPY = {
    'mosi_moss_pro': PickerCopy('云端多说话人，中文直播最稳。', '2 元 / 小时', ('speakers',)),
    'qwen_cloud_filetrans': PickerCopy('云端长文件，带字级时间。', '0.1 元 / 小时', ('multilingual',)),
    'spark_asr_v2': PickerCopy('讯飞云端中英听写，响应快。'),
    'qwen31_filetrans': PickerCopy('阿里云百炼录音识别，可选 Qwen3-ASR 或 Audio 3.1。', tags=('multilingual',)),
    'moss': PickerCopy('多说话人，适合中文长直播。', tags=('speakers',)),
    'firered': PickerCopy('中文和方言最准，带字级时间。', tags=('dialect',)),
    'qwen_local': PickerCopy('中日英都能听，多语言首选。', tags=('multilingual',)),
    'firered_llm': PickerCopy('中文质量优先，需要大显存。', tags=('dialect',)),
    'glm_asr_nano': PickerCopy('小声说话也听得清，支持粤语。', tags=('dialect',)),
    'canary_qwen': PickerCopy('英语专用，速度快。'),
    'omni_asr_llm_7b': PickerCopy('1600+ 种语言；Windows 上只能下载权重。', tags=('multilingual',)),
    'sensevoice': PickerCopy('轻量，没有独立显卡也能跑。', tags=('multilingual',)),
    'paraformer': PickerCopy('中文快速转写，支持热词。'),
    'whisper': PickerCopy('多语言通用。', tags=('multilingual',)),
    'funasr_nano': PickerCopy('中文方言加多语言。', tags=('dialect', 'multilingual')),
    'mlx_qwen3_asr_0_6b': PickerCopy('Mac 本机识别，不需要 NVIDIA 显卡。', tags=('multilingual',)),
    'mlx_qwen3_asr_1_7b': PickerCopy('Mac 本机识别，更准但更慢。', tags=('multilingual',)),
    'groq_api': PickerCopy('Whisper 云端加速。', tags=('multilingual',)),
    'openai_api': PickerCopy('通用多语言，可加提示词。', tags=('multilingual',)),
    'mai_latest': PickerCopy('微软 MAI 云端转写，带字级时间。', tags=('multilingual',)),
    'custom_asr_api': PickerCopy('接你自己的转写服务。'),
    'qwen_aligner': PickerCopy('给已有字幕配字词时间，支持 11 种语言。', tags=('multilingual',)),
    'ja_ctc_aligner': PickerCopy('日语句首校正，跟在时间轴后面运行。'),
    'mfa_aligner': PickerCopy('实验：经典强制对齐，只用 CPU。'),
    'mlx_qwen_aligner': PickerCopy('在 Mac 上给已有字幕配字词时间。'),
}

# The same model can be good at something else in another role.
ROLE_LINES = {
    ('firered', 'timeline'): '中文字级时间最准。',
    ('qwen_local', 'review'): '重新听一遍，给出独立的文字证据。',
}

ROLE_RECOMMENDED = {
    'primary': ('mosi_moss_pro',),
    'timeline': ('qwen_aligner', 'firered'),
    'review': ('qwen_local',),
}

FILTERS = {
    'primary': (('all', '全部'), ('cloud', '云端'), ('local', '本机'), ('speakers', '分清说话人'),
                ('dialect', '方言'), ('multilingual', '多语言')),
    'timeline': (('all', '全部'), ('cloud', '云端'), ('local', '本机')),
    'review': (('all', '全部'), ('cloud', '云端'), ('local', '本机'), ('multilingual', '多语言')),
}


def picker_copy(key: str, role: str = 'primary') -> PickerCopy:
    copy = PICKER_COPY.get(key, PickerCopy(''))
    line = ROLE_LINES.get((key, role))
    return PickerCopy(line, copy.price, copy.tags) if line else copy


def recommended_for(role: str) -> tuple[str, ...]:
    return ROLE_RECOMMENDED.get(role, ())


__all__ = ['FILTERS', 'PICKER_COPY', 'PickerCopy', 'ROLE_RECOMMENDED', 'picker_copy', 'recommended_for']
