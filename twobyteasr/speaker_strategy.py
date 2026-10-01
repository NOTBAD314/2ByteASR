"""One effective selection for views and immutable recognition options."""
from dataclasses import dataclass

LABELS = {'single':'已关闭 · 统一字幕轨', 'nemotron':'Nemotron 3 · 本地',
          'native':'供应商原生标签', 'filetrans':'Filetrans 原生标签',
          'ecapa':'ECAPA · 本地', 'moss':'MOSS · 本地'}


def resolve(settings, override=None):
    value = override if override is not None else settings.get('models', {}).get('speaker_source', 'single')
    value = str(value or 'single')
    if value == 'auto':value = 'single'
    if value not in LABELS:raise ValueError('无效说话人策略：'+value)
    return value


@dataclass(frozen=True)
class SpeakerPlan:
    source: str
    label: str
    steps: tuple[str, ...]


def execution_plan(settings, override=None):
    source=resolve(settings,override)
    steps=('统一分析音频 → 主转写 → 所选字词对齐/复核',)
    if source == 'nemotron':steps+=('Nemotron 加载 → 分析发声区间 → 同一时间基准匹配字幕 → 审阅说话人/选择主播',)
    elif source != 'single':steps+=(LABELS[source]+' → 匹配字幕 → 审阅身份',)
    else:steps+=('保留统一字幕轨，不运行额外说话人模型',)
    return SpeakerPlan(source,LABELS[source],steps)
