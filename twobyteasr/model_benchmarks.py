"""Verified same-protocol benchmark groups and relative scoring for the Model Workshop.

数据与评分规则（P0）：

- 一个比较组（comparison group）只能来自**同一来源、同一协议**的一张评测表；
  不同数据集 / 指标 / 硬件 / 归一化流程的数字绝不合并成一个组。
- 组内相对分：错误率类（CER/WER/AAS，越低越好）
  ``score = round(100 * sqrt(组内最佳 / 当前值))``；
  吞吐类（RTFx，越高越好）``score = round(100 * sqrt(当前值 / 组内最佳))``。
  分数是 2ByteASR 的相对指数：100 = 该基准组相对最佳，不是识别正确率。
- “组内最佳”取全表（含未注册的外部系统，如 Doubao/GPT-4o/闭源模型），
  保证“100 = 同表最佳”语义成立；未注册系统仅在技术说明里作参考行。
- 缺失、非法、跨协议记录不计分；组内只有本模型一行且无外部参照时不显示分数
  （避免“只有一行数据也拿 100”的误导）。
- 评分绑定：比较场景 + 基准组 + 参照集合 + 公式版本（SCORE_FORMULA_VERSION）。
  搜索 / 筛选 / 只看已安装不改变任何分数。
- 本模块是纯数据 + 纯函数，无 Qt、无网络；评测快照随包内置，断网可用。

全部数字于 2026-09-18 联网核对，来源见各组的 source_name / source_url。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SCORE_FORMULA_VERSION = "rel-sqrt-v1"
VERIFIED_DATE = "2026-09-18"


@dataclass(frozen=True)
class ReferenceRow:
    """同表外部系统（未在工坊注册）的成绩行，只作展示参照。"""

    label: str
    value: float


@dataclass(frozen=True)
class ComparisonGroup:
    group_id: str
    scene: str
    kind: str  # "accuracy" | "speed"
    label: str
    label_en: str
    metric: str
    unit: str
    direction: str  # "lower" | "higher"
    protocol: str
    source_name: str
    source_url: str
    source_type: str  # official_same_table | official_card | independent_leaderboard | paper
    verified: str
    entries: dict[str, float] = field(default_factory=dict)
    reference_rows: tuple[ReferenceRow, ...] = ()
    notes: str = ""
    # 每个（场景 × 指标）只允许一个 card_score 主组上卡片；同场景其它组只在
    # 技术说明里展示原始值，避免不同评测管线的数字被读成一张排行榜。
    card_score: bool = False


SCENES: dict[str, tuple[str, str]] = {
    "zh": ("中文通用识别", "Chinese general transcription"),
    "zh_long": ("中文长音频 / 多人", "Long-form Chinese / multi-speaker"),
    "zh_dialect": ("中文方言 / 口音", "Chinese dialects and accents"),
    "en": ("英语", "English"),
    "align": ("字幕时间轴 / 强制对齐", "Subtitle timing / forced alignment"),
}
DEFAULT_SCENE = "zh"

_FIRERED_URL = "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"
_QWEN_URL = "https://github.com/QwenLM/Qwen3-ASR#evaluation"
_MOSS_URL = "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation"

GROUPS: tuple[ComparisonGroup, ...] = (
    # ── 中文通用（zh）────────────────────────────────────────────
    ComparisonGroup(
        group_id="zh_mandarin4_firered",
        scene="zh",
        kind="accuracy",
        label="中文普通话 4 集均值（AISHELL-1/2 + WenetSpeech net/meeting）",
        label_en="Mandarin 4-set average (AISHELL-1/2 + WenetSpeech net/meeting)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="FireRedASR2 官方 README 同表评测（各模型同一评测管线）",
        source_name="FireRedASR2S README",
        source_url=_FIRERED_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"firered_llm": 2.89, "firered": 3.05, "qwen_local": 3.76},
        reference_rows=(
            ReferenceRow("Doubao-ASR（API，未接入）", 3.69),
            ReferenceRow("Fun-ASR 7.7B（闭源，未开放）", 4.16),
        ),
        card_score=True,
    ),
    ComparisonGroup(
        group_id="zh_ws_net_qwen",
        scene="zh",
        kind="accuracy",
        label="WenetSpeech test_net（网络视频口语）",
        label_en="WenetSpeech test_net",
        metric="WER",
        unit="%",
        direction="lower",
        protocol="Qwen3-ASR 官方 README 同表评测（vLLM/bfloat16/greedy，不指定语言）",
        source_name="Qwen3-ASR README",
        source_url=_QWEN_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"qwen_local": 4.97, "funasr_nano": 6.35},
        reference_rows=(
            ReferenceRow("Qwen3-ASR-0.6B", 5.97),
            ReferenceRow("Whisper-large-v3（非本工程 turbo checkpoint）", 9.86),
            ReferenceRow("Gemini-2.5-Pro（API）", 14.43),
            ReferenceRow("GPT-4o-Transcribe（API）", 15.30),
        ),
    ),
    ComparisonGroup(
        group_id="zh_ws_meeting_qwen",
        scene="zh",
        kind="accuracy",
        label="WenetSpeech test_meeting（会议多人）",
        label_en="WenetSpeech test_meeting",
        metric="WER",
        unit="%",
        direction="lower",
        protocol="Qwen3-ASR 官方 README 同表评测（vLLM/bfloat16/greedy，不指定语言）",
        source_name="Qwen3-ASR README",
        source_url=_QWEN_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"qwen_local": 5.88},
        reference_rows=(
            ReferenceRow("Gemini-2.5-Pro（API）", 13.47),
            ReferenceRow("Whisper-large-v3（非本工程 turbo checkpoint）", 19.11),
            ReferenceRow("GPT-4o-Transcribe（API）", 32.27),
        ),
    ),
    ComparisonGroup(
        group_id="zh_fleurs_zh_qwen",
        scene="zh",
        kind="accuracy",
        label="FLEURS 中文（zh）",
        label_en="FLEURS Chinese",
        metric="WER",
        unit="%",
        direction="lower",
        protocol="Qwen3-ASR 官方 README 同表评测；funasr_nano 取该表复测值 3.51"
        "（Fun 自报 2.56 属另一协议，见技术说明）",
        source_name="Qwen3-ASR README",
        source_url=_QWEN_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"qwen_local": 2.41, "funasr_nano": 3.51},
        reference_rows=(
            ReferenceRow("GPT-4o-Transcribe（API）", 2.44),
            ReferenceRow("Gemini-2.5-Pro（API）", 2.71),
            ReferenceRow("Doubao-ASR（API，未接入）", 2.69),
            ReferenceRow("Whisper-large-v3（非本工程 turbo checkpoint）", 4.09),
        ),
    ),
    # 单模型来源组：同表没有本工程其它注册模型，也不显示分数，仅保留原始值。
    ComparisonGroup(
        group_id="zh_aishell1_sensevoice_paper",
        scene="zh",
        kind="accuracy",
        label="AISHELL-1 test（SenseVoice 技术报告）",
        label_en="AISHELL-1 test (SenseVoice report)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="FunAudioLLM SenseVoice 技术报告 Table 6；同表对照为 Whisper-Small/Large-v3",
        source_name="SenseVoice 论文 arXiv 2407.04051",
        source_url="https://arxiv.org/html/2407.04051v3",
        source_type="paper",
        verified=VERIFIED_DATE,
        entries={"sensevoice": 2.96},
        reference_rows=(
            ReferenceRow("Whisper-Small（对照）", 10.04),
            ReferenceRow("Whisper-Large-v3（对照，非本工程 turbo checkpoint）", 5.14),
        ),
        notes="solo_source",
    ),
    ComparisonGroup(
        group_id="zh_aishell1_paraformer_card",
        scene="zh",
        kind="accuracy",
        label="AISHELL-1 test（Paraformer 官方卡）",
        label_en="AISHELL-1 test (Paraformer model card)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="ModelScope 官方模型卡 w/o LM 解码；同表对照为 Espnet/WeNet 等学术系统",
        source_name="Paraformer-large ModelScope 模型卡",
        source_url="https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary",
        source_type="official_card",
        verified=VERIFIED_DATE,
        entries={"paraformer": 1.95},
        reference_rows=(
            ReferenceRow("Wenet（对照，w/ LM 4.36）", 4.61),
        ),
        notes="solo_source",
    ),
    ComparisonGroup(
        group_id="zh_aishell1_funasr_card",
        scene="zh",
        kind="accuracy",
        label="AISHELL-1（Fun-ASR-Nano 官方卡）",
        label_en="AISHELL-1 (Fun-ASR-Nano model card)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="Fun-ASR-Nano-2512 HF 模型卡自报",
        source_name="Fun-ASR-Nano-2512 模型卡",
        source_url="https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512",
        source_type="official_card",
        verified=VERIFIED_DATE,
        entries={"funasr_nano": 1.80},
        reference_rows=(
            ReferenceRow("Fun-ASR 7.7B（闭源，对照）", 1.22),
        ),
        notes="solo_source",
    ),
    # ── 中文长音频 / 多人（zh_long）──────────────────────────────
    ComparisonGroup(
        group_id="zh_long_aishell4_moss",
        scene="zh_long",
        kind="accuracy",
        label="AISHELL-4（长音频多说话人）",
        label_en="AISHELL-4 (long-form multi-speaker)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="MOSS-Transcribe-Diarize 官方 README 同表客观评测（含说话人归属的联合转写）",
        source_name="MOSS-Transcribe-Diarize README",
        source_url=_MOSS_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"moss": 14.84},
        reference_rows=(
            ReferenceRow("Gemini 3 Pro（API）", 22.75),
            ReferenceRow("VIBEVOICE ASR", 21.40),
            ReferenceRow("Doubao-ASR（API）", 18.18),
            ReferenceRow("ElevenLabs Scribe（API）", 19.58),
            ReferenceRow("Gemini 2.5 Pro（API）", 42.70),
        ),
        card_score=True,
    ),
    ComparisonGroup(
        group_id="zh_long_alimeeting_moss",
        scene="zh_long",
        kind="accuracy",
        label="Alimeeting（会议多说话人）",
        label_en="Alimeeting (multi-speaker meetings)",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="MOSS-Transcribe-Diarize 官方 README 同表客观评测",
        source_name="MOSS-Transcribe-Diarize README",
        source_url=_MOSS_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"moss": 24.86},
        reference_rows=(
            ReferenceRow("Doubao-ASR（API）", 25.25),
            ReferenceRow("ElevenLabs Scribe（API）", 25.70),
            ReferenceRow("Gemini 3 Pro（API）", 26.75),
            ReferenceRow("VIBEVOICE ASR", 27.40),
            ReferenceRow("Gemini 2.5 Pro（API）", 27.43),
        ),
    ),
    # ── 中文方言 / 口音（zh_dialect）────────────────────────────
    ComparisonGroup(
        group_id="zh_dialect19_firered",
        scene="zh_dialect",
        kind="accuracy",
        label="中文方言 / 口音 19 集均值",
        label_en="Chinese dialects / accents, 19-set average",
        metric="CER",
        unit="%",
        direction="lower",
        protocol="FireRedASR2 官方 README 同表评测（粤语/四川/上海/吴语/闽南等 19 个公开集）",
        source_name="FireRedASR2S README",
        source_url=_FIRERED_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"firered_llm": 11.55, "firered": 11.67, "qwen_local": 11.85},
        reference_rows=(
            ReferenceRow("Fun-ASR 7.7B（闭源，未开放）", 12.76),
            ReferenceRow("Doubao-ASR（API，未接入）", 15.39),
        ),
        card_score=True,
    ),
    # ── 英语（en）──────────────────────────────────────────────
    ComparisonGroup(
        group_id="en_librispeech_clean_qwen",
        scene="en",
        kind="accuracy",
        label="LibriSpeech test-clean",
        label_en="LibriSpeech test-clean",
        metric="WER",
        unit="%",
        direction="lower",
        protocol="Qwen3-ASR 官方 README 同表评测（英语 WER，不代表中文 CER）",
        source_name="Qwen3-ASR README",
        source_url=_QWEN_URL,
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"qwen_local": 1.63, "funasr_nano": 1.68},
        reference_rows=(
            ReferenceRow("GPT-4o-Transcribe（API）", 1.39),
            ReferenceRow("Whisper-large-v3（非本工程 turbo checkpoint）", 1.51),
            ReferenceRow("Doubao-ASR（API，未接入）", 2.78),
            ReferenceRow("Gemini-2.5-Pro（API）", 2.89),
        ),
    ),
    ComparisonGroup(
        group_id="en_openasr_wer",
        scene="en",
        kind="accuracy",
        label="HF OpenASR 榜单 8 集均值（英语）",
        label_en="HF OpenASR leaderboard mean (English)",
        metric="WER",
        unit="%",
        direction="lower",
        protocol="Hugging Face OpenASR 榜单口径（8 个英语集，whisper-normalizer）；"
        "数值为各官方模型卡自报的同榜结果",
        source_name="官方模型卡所载 OpenASR 结果（canary / GLM / whisper-turbo）",
        source_url="https://huggingface.co/spaces/hf-audio/open_asr_leaderboard",
        source_type="independent_leaderboard",
        verified=VERIFIED_DATE,
        entries={"canary_qwen": 5.63, "glm_asr_nano": 7.03, "whisper": 7.83, "groq_api": 7.83},
        reference_rows=(),
        notes="groq_api 与 whisper 共用同一 large-v3-turbo checkpoint，准确度随模型转移；"
        "托管侧服务速度另计，不互推。",
        card_score=True,
    ),
    ComparisonGroup(
        group_id="en_openasr_rtfx",
        scene="en",
        kind="speed",
        label="HF OpenASR 榜单 RTFx（英语）",
        label_en="HF OpenASR leaderboard RTFx (English)",
        metric="RTFx",
        unit="×实时",
        direction="higher",
        protocol="HF OpenASR 榜单统一评测环境；RTFx=1/RTF，越高越快",
        source_name="官方模型卡所载 OpenASR 结果（canary / GLM / whisper-turbo）",
        source_url="https://huggingface.co/spaces/hf-audio/open_asr_leaderboard",
        source_type="independent_leaderboard",
        verified=VERIFIED_DATE,
        entries={"canary_qwen": 418.0, "glm_asr_nano": 145.28, "whisper": 200.19},
        notes="榜单统一环境（A100 级）的参考吞吐，不代表本机速度；本机速度以“待本机实测”为准。",
        card_score=True,
    ),
    # ── 字幕时间轴 / 强制对齐（align）───────────────────────────
    ComparisonGroup(
        group_id="align_aas_zh_qwen",
        scene="align",
        kind="accuracy",
        label="强制对齐平均偏差 AAS · 中文（MFA Raw 标注）",
        label_en="Forced alignment AAS, Chinese (MFA Raw labels)",
        metric="AAS",
        unit="ms",
        direction="lower",
        protocol="Qwen3-ForcedAligner 官方 README 对齐评测；AAS 只衡量给定文本的对齐，"
        "不代表从零转写准确率，不与 CER/WER 混算",
        source_name="Qwen3-ASR README",
        source_url="https://github.com/QwenLM/Qwen3-ASR#qwen3-forcedaligner",
        source_type="official_same_table",
        verified=VERIFIED_DATE,
        entries={"qwen_aligner": 33.1},
        reference_rows=(
            ReferenceRow("NFA（对照）", 109.8),
            ReferenceRow("Monotonic-Aligner / MFA（对照）", 161.1),
        ),
        notes="WhisperX 在该表中文列无数值（默认对齐模型不含中文）。",
        card_score=True,
    ),
)


# ══════════════════════════════════════════════════════════════════
# 第三层：2ByteASR 参考指数（产品参考分，主卡片默认显示）
#
# 目标：基于公开资料、尽可能覆盖全部已知模型、便于实际选择的 1–100 相对参考分。
# 与第二层（严格同组）的关系：第二层只认"同来源同协议的一张表"；第三层在原始
# 证据（第一层，即 GROUPS/profiles 中的数字）之上，允许三种可解释推导：
#   direct      公开基准换算——同一张公开评测表内的严格换算（含独立评测平台）。
#   calibrated  跨表校准——两表存在共同参照模型时，先在各自表内形成相对关系，
#               再经共同参照换算（明确标注，不冒充同台实测）。
#   tier        综合档位估算——仅有间接证据（同系对照/官方定性/区间证据）时给
#               5 分粒度档位，展示"约 N"，附区间或理由。
# 每条分数必须携带 label/reason/sources；估算永不伪装成官方成绩；未知必须写明缺口。
# 参照集合固定为本评分版本的全部适用模型目录，不随搜索/筛选/安装态/是否配置 API 变化。
# ══════════════════════════════════════════════════════════════════

REFERENCE_INDEX_VERSION = "ref-v2-2026-09-18"

_AA_URL = "https://artificialanalysis.ai/speech-to-text/non-streaming"
_AA_NOTE = "Artificial Analysis 非流式榜单（AA-WER v2；英语 ~8h：AgentTalk 50%+VoxPopuli 25%+Earnings22 25%，whisper 归一化；Speed Factor=音频时长/API 响应耗时，含网络，7 天中位）"
# 跨榜校准锚：whisper-large-v3-turbo 同时出现在 OpenASR 与 AA。
# OpenASR Mean WER 7.83 vs AA 4.6 → 同模型跨榜 WER 比 1.70；RTFx 200.19 vs SF 170.9 → 1.17。
_AA_WER_BRIDGE = 7.83 / 4.6
_AA_SF_BRIDGE = 200.19 / 170.9

BASIS_LABELS = {
    "direct": "公开基准换算",
    "direct_aa": "独立评测（AA 实测）",
    "official": "官方环境参考",
    "calibrated": "跨表校准估算",
    "tier": "综合档位估算",
    "same_family": "同系换算估算",
}
# 需要展示"约 N"的估算类依据（档位/跨表/同系/跨硬件推导）；direct/direct_aa 为公开表换算。
_ESTIMATE_BASES = {"calibrated", "tier", "same_family", "official"}


def _ref(score, basis, label, reason, detail, sources, approx=None):
    return {
        "score": int(score),
        "basis": basis,
        "label": label,
        "reason": reason,
        "detail": detail,
        "sources": tuple(sources),
        "approx": approx if approx is not None else basis in _ESTIMATE_BASES,
    }


# key: (model_key, kind) → {"scenes": {scene: entry}, "default": entry|None,
#                            "unsupported": {scene: 说明}, "gap": str}
_REFERENCE_INDEX: dict[tuple[str, str], dict] = {
    # ── 本地 · 中文第一梯队（第一手同表直接换算）──────────────
    ("firered_llm", "accuracy"): {
        "scenes": {
            "zh": _ref(100, "direct", "FireRed 官方同表",
                "普通话 4 集均值 CER 2.89%，该表最佳",
                "FireRedASR2 官方 README 评测表：普通话 4 集（AISHELL-1/2+WenetSpeech net/meeting）均值 CER 2.89%（LLM），同表含 FireRed-AED 3.05 / Qwen3-ASR-1.7B 3.76 / Doubao 3.69 / Fun-ASR-7.7B(闭源) 4.16。sqrt 相对分=组内最佳 100。",
                [_FIRERED_URL]),
            "zh_dialect": _ref(100, "direct", "FireRed 官方同表",
                "方言 19 集均值 CER 11.55%，该表最佳",
                "FireRedASR2 官方表：19 个方言/口音公开集均值 CER 11.55%（LLM），同表 AED 11.67 / Qwen3 11.85 / Fun-ASR-7.7B 12.76 / Doubao 15.39。",
                [_FIRERED_URL]),
        },
        "default": None, "unsupported": {}, "gap": "英语无公开成绩",
    },
    ("firered_llm", "speed"): {
        "scenes": {},
        "default": _ref(25, "tier", "官方示例+档位估算",
            "官方示例 RTF 0.0681；vLLM 服务化更快但无公开数值",
            "FireRedASR2-LLM 官方 hello 示例输出 RTF 0.0681（硬件未声明，非正式基准）；官方推荐 vLLM 服务化（PR #35727）但未公布吞吐。按自回归 LLM-ASR 档位估 25（区间 15-40）。8B+ 权重、17.57 GiB 下载。",
            [_FIRERED_URL]),
        "unsupported": {}, "gap": "",
    },
    ("firered", "accuracy"): {
        "scenes": {
            "zh": _ref(97, "direct", "FireRed 官方同表",
                "普通话 4 集均值 CER 3.05%（同表第 2）",
                "FireRedASR2-AED 官方表普通话 4 集均值 3.05%；sqrt(2.89/3.05)=97。",
                [_FIRERED_URL]),
            "zh_dialect": _ref(99, "direct", "FireRed 官方同表",
                "方言 19 集均值 CER 11.67%（同表第 2）",
                "方言 19 集均值 11.67%；sqrt(11.55/11.67)=99（与 Qwen3 11.85 同为 99，未取整 99.5 vs 98.7）。",
                [_FIRERED_URL]),
        },
        "default": None, "unsupported": {}, "gap": "英语无公开成绩",
    },
    ("firered", "speed"): {
        "scenes": {},
        "default": _ref(30, "tier", "官方示例+TensorRT 区间",
            "示例 RTF 0.087（PyTorch）；TensorRT-LLM 官方加速 12.7x（H20）",
            "AED 官方示例 RTF 0.0870（硬件未声明）；NVIDIA 贡献的 TensorRT-LLM 在 AISHELL-1 上 12.7x 加速（单张 H20）→ 约 RTF 0.0069。折算区间约 RTFx 12-145，取中低档 30。2ByteASR 本地走 PyTorch 路径。",
            [_FIRERED_URL]),
        "unsupported": {}, "gap": "",
    },
    ("qwen_local", "accuracy"): {
        "scenes": {
            "zh": _ref(88, "direct", "FireRed 官方同表",
                "普通话 4 集均值 CER 3.76%（FireRed 复测 Qwen3-ASR-1.7B）",
                "FireRed 官方表对 Qwen3-ASR-1.7B 的同管线复测：普通话均值 3.76%；sqrt(2.89/3.76)=88。Qwen 自家表中文集更优（WenetSpeech net 4.97 / Fleurs-zh 2.41 同表最佳）。",
                [_FIRERED_URL, _QWEN_URL]),
            "zh_dialect": _ref(99, "direct", "FireRed 官方同表",
                "方言 19 集均值 CER 11.85%（同表第 3，与 AED 同为 99）",
                "方言均值 11.85%；sqrt(11.55/11.85)=99。官方另列 22 种中文方言支持。",
                [_FIRERED_URL]),
            "en": _ref(78, "calibrated", "跨榜校准（AA 统一尺度）",
                "LibriSpeech clean WER 1.63%（Qwen 官方表）经 turbo 锚换算到 AA 尺度",
                "统一到 AA 英語尺度：turbo 同模型跨榜 WER 比 7.83/4.6=1.70。Qwen3-ASR-1.7B LibriSpeech clean 1.63%（Qwen 官方表，与 AA 集不同）→ AA 等效约 2.8% → sqrt(2.0/2.8)×100≈84，考虑测试集差异取约 78。AA 榜单未收录 Qwen3-ASR。",
                [_QWEN_URL, _AA_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("qwen_local", "speed"): {
        "scenes": {},
        "default": _ref(30, "tier", "同级类推估算",
            "1.7B 自回归 LLM-ASR；无官方 RTF",
            "官方未公布 RTF；按同级自回归 LLM-ASR（FireRed-LLM 示例 0.068 / MOSS H100 0.0197）档位估 30（区间 20-40）。vLLM 批量推理会更快。",
            [_QWEN_URL]),
        "unsupported": {}, "gap": "",
    },
    ("moss", "accuracy"): {
        "scenes": {
            "zh_long": _ref(100, "direct", "MOSS 官方同表",
                "AISHELL-4 CER 14.84%，长音频多说话人同表最佳",
                "MOSS-Transcribe-Diarize 官方表：AISHELL-4 14.84 / Alimeeting 24.86（同表最佳），对照 Gemini 3 Pro 22.75/26.75、Doubao 18.18/25.25、ElevenLabs 19.58/25.70、Gemini 2.5 Pro 42.70/27.43。",
                [_MOSS_URL]),
            "zh": _ref(80, "tier", "综合档位估算",
                "AISHELL-4 同表最佳，但属长音频多人口径，与朗读集不可直比",
                "MOSS 的公开成绩都在长音频/多说话人集（AISHELL-4/Alimeeting/Podcast/Movies），无普通话朗读集数字。其胜出对象含通用 API（Doubao/Gemini），中文能力属第一梯队；按档位估 80（区间 75-85）。说话人区分能力不计入文字准确度。",
                [_MOSS_URL]),
            "zh_dialect": _ref(70, "tier", "通用参考（方言未验证）",
                "中文长音频证据迁移；无方言集成绩",
                "官方表未含方言测试集；以中文整体表现给通用档位 70，方言单独未验证。",
                [_MOSS_URL]),
        },
        "default": None, "unsupported": {}, "gap": "英语无公开成绩",
    },
    ("moss", "speed"): {
        "scenes": {},
        "default": _ref(35, "official", "官方环境参考",
            "RTF 0.0197（单张 H100 · SGLang Omni · 长音频 · 并发 1）",
            "官方 SGLang Omni 吞吐表：aishell4_long 并发 1 RTF 0.0197（≈RTFx 51，H100）。跨硬件按统一速度尺度折算约 35（区间 25-45）。不代表本机速度。",
            [_MOSS_URL]),
        "unsupported": {}, "gap": "",
    },
    # ── 本地 · 有跨表或档位证据 ─────────────────────────────
    ("funasr_nano", "accuracy"): {
        "scenes": {
            "zh": _ref(78, "calibrated", "跨表校准（Qwen 官方表）",
                "WenetSpeech net 6.35%（Qwen 表复测）经 Qwen3-ASR 锚换算",
                "Qwen 官方表同表：Fun-ASR-Nano WS net 6.35 vs Qwen3-ASR-1.7B 4.97；Qwen 中文锚分 88（FireRed 表）→ 88×sqrt(4.97/6.35)=78。Fun 自报同集 6.01（另一管线），Fleurs-zh 自报 2.56 vs Qwen 表 3.51，两套来源分行保留。官方卡 TODO：2512 版无时间戳/说话人。",
                [_QWEN_URL, "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"]),
            "zh_dialect": _ref(75, "tier", "官方卡行业集+方言覆盖",
                "官方 7 方言覆盖；行业方言集 28.18%（vs 闭源 7.7B 15.21）",
                "Fun-ASR-Nano 官方卡：吴粤闽客赣湘晋 7 方言+26 口音；行业 Dialect 集 28.18%。档位估 75。",
                ["https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"]),
            "en": _ref(70, "tier", "官方卡英语集",
                "LibriSpeech clean 1.76% / other 4.33%（自报）",
                "官方卡英语自报成绩良好但未入 AA 榜；按档位估 70。",
                ["https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("funasr_nano", "speed"): {
        "scenes": {},
        "default": _ref(35, "tier", "档位估算",
            "0.8B 端到端；官方称低延迟实时转写，无公开 RTF",
            "官方卡无 RTF 数值，标注 low-latency real-time；按 0.8B 端到端 LLM-ASR 档位估 35（区间 25-45）。",
            ["https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"]),
        "unsupported": {}, "gap": "",
    },
    ("sensevoice", "accuracy"): {
        "scenes": {
            "zh": _ref(75, "tier", "技术报告同表对照",
                "AISHELL-1 2.96% / WS 7.44·7.84%，同表全面优于 Whisper-Large-v3",
                "SenseVoice 技术报告 Table 6：AISHELL-1 2.96 vs Whisper-L-v3 5.14；WS meeting 7.44 vs 18.87；WS net 7.84 vs 10.48。经 whisper-v3 锚（约 60）换算区间 63-95，测试集难度差异大，取档位 75（区间 70-83）。",
                ["https://arxiv.org/html/2407.04051v3"]),
            "zh_dialect": _ref(60, "tier", "粤语专项优化",
                "官方主打中文/粤语；无方言集数值",
                "checkpoint 语言集含粤语且官方称中文粤语有优势；未核到方言测试集数字，档位估 60。",
                ["https://github.com/FunAudioLLM/SenseVoice"]),
        },
        "default": None, "unsupported": {}, "gap": "英语公开证据有限（论文 LS clean 3.15%）",
    },
    ("sensevoice", "speed"): {
        "scenes": {},
        "default": _ref(60, "tier", "官方速度图示+论文延迟",
            "官方称 >15x Whisper-Large；论文 10s 音频 70ms（RTF≈0.007）",
            "README 图示（硬件见图注）：>5x Whisper-Small、>15x Whisper-Large；论文 Table 7 十秒音频 70ms。折算 RTFx 约 50-180（跨环境），档位估 60（区间 55-70）。CPU 可用。",
            ["https://github.com/FunAudioLLM/SenseVoice", "https://arxiv.org/html/2407.04051v3"]),
        "unsupported": {}, "gap": "",
    },
    ("paraformer", "accuracy"): {
        "scenes": {
            "zh": _ref(70, "tier", "官方卡跨集区间",
                "AISHELL-1 1.95% / WS meeting 6.97%，跨集表现差异大",
                "官方卡：AISHELL-1 1.95（w/o LM；w/ LM 1.68）、WS meeting 6.97、net 6.74。对照 FireRed 同集 0.57/4.53 换算区间约 52-78，取中低档 70（区间 65-75）。2018-2022 代模型，新模型已普遍超越。",
            ["https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"]),
            "zh_dialect": _ref(55, "tier", "官方卡未列方言",
                "模型卡无方言集数值",
                "官方卡未提供方言覆盖证据；档位估 55。",
            ["https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"]),
        },
        "default": None, "unsupported": {}, "gap": "英语不支持（中文专用模型）",
    },
    ("paraformer", "speed"): {
        "scenes": {},
        "default": _ref(50, "tier", "官方 RTF+120x 声明",
            "RTF 0.0251（V100·batch1）；HF 卡称 GPU 120x 实时",
            "官方卡 indexing：V100 batch1 RTF 0.0251（≈RTFx 40，旧卡）；HF 卡称非自回归 GPU 120x 实时（≈RTFx 120）。跨代硬件折算档位 50（区间 35-55）。",
            ["https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary", "https://huggingface.co/funasr/paraformer-zh"]),
        "unsupported": {}, "gap": "",
    },
    ("whisper", "accuracy"): {
        "scenes": {
            "en": _ref(66, "calibrated", "跨榜校准（AA 统一尺度）",
                "AA 实测 Groq turbo WER 4.6%；OpenASR 7.83% 同模型",
                "统一 AA 尺度：榜内最佳 MAI-Transcribe-2 2.0% → turbo 4.6% = 66。OpenASR 尺度下 turbo 为 85（该组最佳 canary 5.63）——两榜测试集不同，卡片用 AA 统一尺度，技术说明保留两组原始数字。",
                [_AA_URL, "https://huggingface.co/openai/whisper-large-v3-turbo"]),
            "zh": _ref(60, "tier", "large-v3 同表外推",
                "无 turbo 专属中文数据；large-v3 经 Qwen 表换算约 62，turbo 略降",
                "Qwen 官方表（large-v3，非本工程 turbo）：WS net 9.86 / meeting 19.11 / Fleurs-zh 4.09 / KeSpeech 28.79。经 Qwen 锚换算中文约 62；turbo 为 v3 剪枝微调（官方称轻微退化）→ 档位 60。中文是 Whisper 相对弱项。",
                [_QWEN_URL, "https://huggingface.co/openai/whisper-large-v3-turbo"]),
            "zh_dialect": _ref(35, "tier", "large-v3 KeSpeech 外推",
                "large-v3 KeSpeech 28.79%（Qwen 表）——方言显著偏弱",
                "KeSpeech（方言）large-v3 28.79 vs Qwen3 5.10；经锚换算约 40，turbo 再降 → 档位 35。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("whisper", "speed"): {
        "scenes": {},
        "default": _ref(69, "direct", "OpenASR RTFx",
            "RTFx 200.19（OpenASR 榜单统一环境）",
            "官方 HF 卡所载 OpenASR：RTFx 200.19（≈RTF 0.005，榜单统一环境）。统一尺度：canary 418=100 → turbo 69。不代表本机速度；torch.compile 另有 4.5x 官方声明。",
            ["https://huggingface.co/openai/whisper-large-v3-turbo"]),
        "unsupported": {}, "gap": "",
    },
    ("glm_asr_nano", "accuracy"): {
        "scenes": {
            "en": _ref(70, "calibrated", "跨榜校准（OpenASR→AA）",
                "OpenASR Mean WER 7.03%；经 turbo 锚换算 AA 尺度",
                "OpenASR 7.03 → AA 等效 7.03/1.70=4.13% → sqrt(2.0/4.13)×100≈70。",
                ["https://huggingface.co/zai-org/GLM-ASR-Nano-2512", _AA_URL]),
            "zh": _ref(75, "tier", "通用参考·中文证据有限",
                "官方称同类开源均错最低 4.10；中文成绩图为图片无文本数值",
                "官方模型卡 benchmark 图无文本数字（无法转录），正文称 avg error 4.10 最低；Qwen 多语表 GLM 落后 whisper-v3 约 1.5 倍错误率。中文证据有限，档位估 75。",
                ["https://huggingface.co/zai-org/GLM-ASR-Nano-2512"]),
            "zh_dialect": _ref(75, "tier", "官方主打粤语/方言",
                "官方模型卡主打粤语与方言优化",
                "官方称对粤语、方言、低音量语音优化；无逐集数值，档位估 75。",
                ["https://huggingface.co/zai-org/GLM-ASR-Nano-2512"]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("glm_asr_nano", "speed"): {
        "scenes": {},
        "default": _ref(59, "direct", "OpenASR RTFx",
            "RTFx 145.28（官方卡自报同榜结果）",
            "OpenASR 榜单口径 RTFx 145.28（≈RTF 0.0069）。统一尺度 canary 418=100 → 59。",
            ["https://huggingface.co/zai-org/GLM-ASR-Nano-2512"]),
        "unsupported": {}, "gap": "",
    },
    ("canary_qwen", "accuracy"): {
        "scenes": {
            "en": _ref(78, "calibrated", "跨榜校准（OpenASR→AA）",
                "OpenASR Mean WER 5.63%；经 turbo 锚换算 AA 尺度",
                "OpenASR 5.63 → AA 等效 5.63/1.70=3.31% → sqrt(2.0/3.31)×100≈78。OpenASR 组内它仍是最佳（严格分 100，见技术说明）。",
                ["https://huggingface.co/nvidia/canary-qwen-2.5b", _AA_URL]),
        },
        "default": None,
        "unsupported": {"zh": "官方明确仅可靠支持 English（英语专用模型）",
                        "zh_dialect": "官方明确仅可靠支持 English",
                        "zh_long": "官方明确仅可靠支持 English"},
        "gap": "",
    },
    ("canary_qwen", "speed"): {
        "scenes": {},
        "default": _ref(100, "direct", "OpenASR RTFx",
            "RTFx 418（OpenASR 榜单，全目录最快）",
            "OpenASR RTFx 418（≈RTF 0.0024，榜单统一环境）——本参考目录内公开速度最佳，定标 100。",
            ["https://huggingface.co/nvidia/canary-qwen-2.5b"]),
        "unsupported": {}, "gap": "",
    },
    ("omni_asr_llm_7b", "accuracy"): {
        "scenes": {},
        "default": None, "unsupported": {},
        "gap": "HF 卡无逐语言准确率表；论文/演示榜未核到中文逐集成绩（1600+ 语言为覆盖声明）",
    },
    ("omni_asr_llm_7b", "speed"): {
        "scenes": {},
        "default": _ref(15, "official", "官方环境参考",
            "RTF 0.092（A100 · BF16 · batch1 · 30s）≈RTFx 11",
            "官方卡脚注：RTF 0.092（~1x 实时）。统一尺度 sqrt(10.9/418)≈16 → 15。同家族 CTC 版本（300M-7B）RTF 0.001-0.006 远快于 LLM 版。",
            ["https://huggingface.co/facebook/omniASR-LLM-7B"]),
        "unsupported": {}, "gap": "",
    },
    ("qwen_aligner", "accuracy"): {
        "scenes": {
            "align": _ref(100, "direct", "Qwen 官方同表",
                "AAS 中文 33.1ms，同表最佳（NFA 109.8 / MFA 161.1）",
                "Qwen3-ForcedAligner 官方对齐评测：中文 Raw AAS 33.1ms。AAS 只衡量给定文本对齐，不代表从零转写准确率。",
                ["https://github.com/QwenLM/Qwen3-ASR#qwen3-forcedaligner"]),
        },
        "default": None,
        "unsupported": {},
        "gap": "非从零转写模型：准确度不适用（对齐模型）",
    },
    ("qwen_aligner", "speed"): {
        "scenes": {},
        "default": None, "unsupported": {},
        "gap": "无公开对齐速度数据（AAS 表未含吞吐）",
    },
    # ── 在线 API（按实际解析型号给分；密钥未配置不影响公开参考分）──
    ("qwen_api", "accuracy"): {
        "scenes": {
            "zh": _ref(85, "same_family", "同系换算估算",
                "托管 qwen3-asr-flash；本地 1.7B 官方中文 88，托管版未单独公布",
                "DashScope qwen3-asr-flash 与开源 Qwen3-ASR 同系；官方未公布托管版逐集成绩。按 1.7B 官方中文 88 取同系档位 85（托管版可能有差异）。官方称支持传统七大方言+20+口音官话（2026-06 更新版描述）。",
                [_QWEN_URL, "https://help.aliyun.com/zh/model-studio/"]),
            "zh_dialect": _ref(80, "same_family", "官方方言声明",
                "官方称全面支持七大方言体系；无逐集数值",
                "官方文档称 Qwen3/Qwen-Audio 3.0 ASR 支持汉语传统七大方言；无公开方言测试集数字，档位估 80。",
                ["https://help.aliyun.com/zh/model-studio/"]),
            "en": _ref(75, "same_family", "同系换算估算",
                "本地 1.7B 官方 Fleurs-en 3.35%；托管版未公布",
                "同系 1.7B 官方英语集表现良好（LibriSpeech 1.63/3.38、Fleurs-en 3.35）；托管 flash 未单独公布，档位估 75。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("qwen_api", "speed"): {
        "scenes": {},
        "default": _ref(40, "tier", "服务档位估算",
            "云端托管 ASR 中档；未核到官方公开吞吐",
            "DashScope 未公布该模型公开 RTF/吞吐。同步接口单请求 ≤5 分钟内返回（含上传与推理），按云端托管离线转写档位估 40（区间 30-60）。本机/当前路由未实测。",
            ["https://help.aliyun.com/zh/model-studio/"]),
        "unsupported": {}, "gap": "",
    },
    ("qwen_audio_asr_flash", "accuracy"): {
        "scenes": {
            "zh": _ref(85, "same_family", "同系换算估算",
                "qwen-audio-3.0-asr-flash（qwen3-asr-flash 同代新命名）；托管版未单独公布",
                "qwen-audio-3.0-asr-flash 为 Qwen3-ASR 家族托管版命名（同代）。按本地 1.7B 官方中文 88 取 85 档。与 qwen_api 卡的差异是接口/入口而非已证实的模型差异。",
                [_QWEN_URL, "https://help.aliyun.com/zh/model-studio/"]),
            "zh_dialect": _ref(80, "same_family", "官方方言声明",
                "官方称七大方言体系支持；无逐集数值",
                "同 qwen3-asr-flash 方言声明：官方支持汉语传统七大方言，无逐集数值。",
                ["https://help.aliyun.com/zh/model-studio/"]),
            "en": _ref(75, "same_family", "同系换算估算",
                "同系 1.7B 官方英语集良好；托管版未公布",
                "同 qwen3-asr-flash 英语依据（1.7B 官方英语集），档位估 75。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("qwen_audio_asr_flash", "speed"): {
        "scenes": {},
        "default": _ref(40, "tier", "服务档位估算",
            "云端托管中档；未核到官方公开吞吐",
            "同 qwen3-asr-flash：无公开吞吐，档位 40（区间 30-60）。当前路由未实测。",
            ["https://help.aliyun.com/zh/model-studio/"]),
        "unsupported": {}, "gap": "",
    },
    ("qwen_audio_filetrans", "accuracy"): {
        "scenes": {
            "zh": _ref(85, "same_family", "同模型不同接口",
                "filetrans 为 qwen-audio-3.0-asr-flash 的异步录音文件接口",
                "qwen-audio-3.0-asr-flash-filetrans 与同步 flash 同模型家族的文件转写接口（词级时间戳+speaker）；模型层同系 85，接口差异不改变识别质量。",
                ["https://help.aliyun.com/zh/model-studio/"]),
            "zh_dialect": _ref(80, "same_family", "官方方言声明",
                "官方称七大方言体系支持；无逐集数值",
                "同 qwen3-asr-flash 方言声明：官方支持汉语传统七大方言，无逐集数值。",
                ["https://help.aliyun.com/zh/model-studio/"]),
            "en": _ref(75, "same_family", "同系换算估算",
                "同系 1.7B 官方英语集良好；托管版未公布",
                "同 qwen3-asr-flash 英语依据（1.7B 官方英语集），档位估 75。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("qwen_audio_filetrans", "speed"): {
        "scenes": {},
        "default": _ref(35, "tier", "异步端到端档位",
            "吞吐型异步接口；端到端含排队与轮询",
            "filetrans 为异步吞吐接口（单文件 ≤12h）；端到端耗时含上传/排队/轮询，短音频不占优。档位估 35（区间 25-55）。当前路由未实测。",
            ["https://help.aliyun.com/zh/model-studio/"]),
        "unsupported": {}, "gap": "",
    },
    ("groq_api", "accuracy"): {
        "scenes": {
            "en": _ref(66, "direct_aa", "AA 实测（Groq 路由）",
                "AA 实测 Groq Whisper large-v3-turbo WER 4.6%",
                "AA 非流式榜单对 Groq 托管 turbo 的第一手实测：WER 4.6%（当前路由）。与本地 turbo 模型级一致（66）。",
                [_AA_URL]),
            "zh": _ref(60, "tier", "turbo 模型级参考",
                "模型层=whisper-large-v3-turbo；中文无 turbo 专属数据",
                "与本地 turbo 同 checkpoint，准确度随模型转移：中文档位 60（large-v3 外推 62×turbo 降幅）。托管预处理/解码设置差异未验证。",
                [_AA_URL, _QWEN_URL]),
            "zh_dialect": _ref(35, "tier", "turbo 模型级参考",
                "large-v3 KeSpeech 28.79% 外推；方言显著偏弱", "同本地 turbo 方言依据。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("groq_api", "speed"): {
        "scenes": {},
        "default": _ref(69, "direct_aa", "AA 实测（Groq 路由）",
            "AA 实测 Speed Factor 170.9（含网络）",
            "AA 对 Groq 路由实测 SF 170.9（音频时长/API 响应耗时，7 天中位）；经 turbo 锚（OpenASR RTFx 200.19）一致。当前路由端到端已含网络。",
            [_AA_URL]),
        "unsupported": {}, "gap": "",
    },
    ("mai_transcribe_2_word", "accuracy"): {
        "scenes": {
            "en": _ref(100, "direct_aa", "AA 实测",
                "AA 实测 MAI-Transcribe-2 WER 2.0%，榜内最佳",
                "AA 非流式榜单：MAI-Transcribe-2 WER 2.0%（榜内最佳；对照 Scribe v2 2.2 / Gemini 3.5 2.6 / GPT Transcribe 3.3）。OpenRouter 路由未验证。",
                [_AA_URL]),
            "zh": _ref(75, "tier", "通用参考·中文证据有限",
                "多语言服务；AA 为英语集，中文未验证",
                "AA 榜单仅英语。MAI-Transcribe-2 支持多语言转写（含说话人分离与字级时间戳），但未核到中文公开成绩；以英语榜最佳给通用档位 75（区间 70-80）。",
                [_AA_URL, "https://openrouter.ai/microsoft/mai-transcribe-2"]),
            "zh_dialect": _ref(70, "tier", "通用参考·中文证据有限",
                "同中文口径，方言更未验证",
                "中文证据仅英语榜间接，方言单独未验证，档位估 70。",
                [_AA_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("mai_transcribe_2_word", "speed"): {
        "scenes": {},
        "default": _ref(95, "direct_aa", "AA 实测",
            "AA 实测 Speed Factor 323.6（AA 榜第 2 快）",
            "AA 非流式：SF 323.6（含网络，7 天中位；对照 Deepgram Nova-3 543.8 榜首）。统一尺度 sqrt(379/418)≈95。OpenRouter 中转路由未实测——中转会增加延迟。",
            [_AA_URL]),
        "unsupported": {}, "gap": "OpenRouter 中转路由速度未实测",
    },
    ("openai_api", "accuracy"): {
        "scenes": {
            "en": _ref(78, "direct_aa", "AA 实测",
                "AA 实测 GPT Transcribe WER 3.3%",
                "AA 非流式：OpenAI GPT Transcribe 3.3% / GPT-4o Transcribe 4.0% / mini 4.5%。当前默认 gpt-transcribe → 78。",
                [_AA_URL]),
            "zh": _ref(65, "tier", "中文证据两极（4o 系）",
                "GPT-4o-Transcribe 中文集：Fleurs-zh 2.44 优 / WS 15.30·32.27 差",
                "Qwen 官方表 GPT-4o-Transcribe 中文集两极分化（干净朗读近最佳、真实网络视频差）；gpt-transcribe 为更新型号（AA 英语更优）间接迁移。档位估 65（区间 55-80，视音频类型）。",
                [_QWEN_URL, _AA_URL]),
            "zh_dialect": _ref(50, "tier", "中文证据有限",
                "4o 系 KeSpeech 26.87%（Qwen 表）；方言偏弱", "KeSpeech（方言）26.87 vs Qwen3 5.10；档位估 50。",
                [_QWEN_URL]),
        },
        "default": None, "unsupported": {}, "gap": "",
    },
    ("openai_api", "speed"): {
        "scenes": {},
        "default": _ref(34, "direct_aa", "AA 实测",
            "AA 实测 GPT Transcribe SF 40.8（含网络）",
            "AA 非流式：GPT Transcribe 40.8 / GPT-4o 36.3 / mini 43.1。OpenAI 转写吞吐中档偏低。",
            [_AA_URL]),
        "unsupported": {}, "gap": "",
    },
    ("custom_asr_api", "accuracy"): {"scenes": {}, "default": None, "unsupported": {},
        "gap": "自定义入口：配置已知型号后自动匹配参考分（依据所配模型）"},
    ("custom_asr_api", "speed"): {"scenes": {}, "default": None, "unsupported": {},
        "gap": "自定义入口：配置已知型号后自动匹配参考分（依据所配模型）"},
}

# API 型号别名 → 参考条目 key（模型层共享，路由差异由调用方标注）。
API_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "qwen3-asr-flash": ("qwen_api", "accuracy"),
    "qwen-audio-3.0-asr-flash": ("qwen_audio_asr_flash", "accuracy"),
    "qwen-audio-3.0-asr-flash-filetrans": ("qwen_audio_filetrans", "accuracy"),
    "whisper-large-v3-turbo": ("whisper", "accuracy"),
    "gpt-transcribe": ("openai_api", "accuracy"),
    "gpt-4o-transcribe": ("openai_api", "accuracy"),
    "gpt-4o-mini-transcribe": ("openai_api", "accuracy"),
    "microsoft/mai-transcribe-2": ("mai_transcribe_2_word", "accuracy"),
    "mai-transcribe-2": ("mai_transcribe_2_word", "accuracy"),
}


def _speed_key(accuracy_key: tuple[str, str]) -> tuple[str, str]:
    return (accuracy_key[0], "speed")


def reference_entry(model_key: str, kind: str, scene: str) -> dict | None:
    """第三层参考分：返回 {score,basis,label,reason,detail,sources,approx} 或 None。

    scenes 优先 → default 兜底；unsupported 场景返回带 reason 的不可用标记。
    分数与参照集合绑定 REFERENCE_INDEX_VERSION，不随筛选/安装态变化。
    """
    record = _REFERENCE_INDEX.get((model_key, kind))
    if record is None:
        return None
    unsupported = record.get("unsupported") or {}
    if scene in unsupported:
        return {"unsupported": True, "reason": unsupported[scene]}
    entry = (record.get("scenes") or {}).get(scene) or record.get("default")
    if entry is None:
        return None
    return dict(entry)


def reference_gap(model_key: str, kind: str) -> str:
    record = _REFERENCE_INDEX.get((model_key, kind))
    return str(record.get("gap") or "") if record else ""


def reference_api_model(model_id: str, kind: str, scene: str) -> dict | None:
    """自定义/可配置入口：按用户配置的 model id 匹配已知模型参考分。"""
    needle = str(model_id or "").strip().lower()
    if not needle:
        return None
    for alias, accuracy_key in API_MODEL_ALIASES.items():
        if alias in needle or needle in alias:
            key = accuracy_key if kind == "accuracy" else (accuracy_key[0], "speed")
            record = _REFERENCE_INDEX.get(key)
            if record is None:
                return None
            unsupported = record.get("unsupported") or {}
            if scene in unsupported:
                return {"unsupported": True, "reason": unsupported[scene]}
            entry = (record.get("scenes") or {}).get(scene) or record.get("default")
            if entry is None:
                return None
            entry = dict(entry)
            entry["matched_model"] = alias
            return entry
    return None


def reference_coverage() -> list[tuple[str, str, str]]:
    """(model_key, kind, status) 覆盖清单：score=有参考分 / gap=有明确缺口。"""
    rows = []
    for (model_key, kind), record in _REFERENCE_INDEX.items():
        has_score = bool(record.get("scenes")) or record.get("default") is not None
        if not has_score and not record.get("unsupported"):
            continue  # 纯 gap 条目
        rows.append((model_key, kind, "score" if has_score else "gap"))
    return rows


def _valid(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _ratio_score(value: float, best: float, direction: str) -> float | None:
    """Unrounded 1..100 relative score; None when the pair cannot be scored."""
    if direction == "lower":
        if value <= 0 and best <= 0:
            return 100.0
        if best <= 0:
            # 最佳错误率为 0：其它模型没有可解释的比值 → 退到下限并保持单调。
            return 100.0 if value <= 0 else 1.0
        if value <= 0:
            return 100.0
        ratio = best / value
    else:
        if best <= 0:
            return None
        ratio = value / best
    if ratio <= 0:
        return None
    return max(1.0, min(100.0, 100.0 * math.sqrt(ratio)))


def score_in_group(group: ComparisonGroup, model_key: str) -> dict | None:
    """Score one model inside one group, or None when it must not be scored."""
    value = group.entries.get(model_key)
    if not _valid(value):
        return None
    solo = len([v for v in group.entries.values() if _valid(v)]) == 1 and not group.reference_rows
    values = [
        float(v)
        for v in list(group.entries.values()) + [row.value for row in group.reference_rows]
        if _valid(v)
    ]
    if not values:
        return None
    best = min(values) if group.direction == "lower" else max(values)
    exact = _ratio_score(float(value), best, group.direction)
    if exact is None:
        return None
    return {
        "score": int(round(exact)),
        "exact": exact,
        "value": float(value),
        "solo": solo,
        "group": group,
        "formula": SCORE_FORMULA_VERSION,
    }


def groups_for(scene: str, kind: str | None = None) -> list[ComparisonGroup]:
    return [
        group
        for group in GROUPS
        if group.scene == scene and (kind is None or group.kind == kind)
    ]


def groups_for_model(model_key: str) -> list[ComparisonGroup]:
    return [group for group in GROUPS if model_key in group.entries]


def best_score(model_key: str, kind: str, scene: str) -> dict | None:
    """Card score for the model in this scene.

    Only the scene's single primary (card_score) group is eligible, so one
    scene never mixes scores from different evaluation harnesses on cards.
    """
    for group in groups_for(scene, kind):
        if not group.card_score:
            continue
        result = score_in_group(group, model_key)
        if result is not None and not result["solo"]:
            return result
    return None


def secondary_record(model_key: str, kind: str, scene: str) -> ComparisonGroup | None:
    """First non-primary group holding a raw value for this model in the scene.

    Used as a display hint（“另有 … 同表数据”）; never scored on cards.
    """
    for group in groups_for(scene, kind):
        if group.card_score:
            continue
        if model_key in group.entries and _valid(group.entries[model_key]):
            return group
    return None


def assert_primary_groups_unique() -> None:
    """Invariant: at most one card_score group per (scene, kind)."""
    seen: set[tuple[str, str]] = set()
    for group in GROUPS:
        if not group.card_score:
            continue
        key = (group.scene, group.kind)
        if key in seen:
            raise ValueError(f"duplicate card_score group for {key}: {group.group_id}")
        seen.add(key)


def scene_label(scene: str, language: str = "zh") -> str:
    pair = SCENES.get(scene)
    if pair is None:
        return scene
    from .i18n import translate
    return pair[1] if language == "en" else translate(pair[0], language)


SOURCE_TYPE_LABELS = {
    "official_same_table": ("官方同表评测", "Official same-table evaluation"),
    "official_card": ("官方模型卡自报", "Official model card"),
    "independent_leaderboard": ("独立评测（榜单口径，官方卡自报）", "Independent leaderboard (self-reported)"),
    "paper": ("官方技术报告", "Official technical report"),
}


def source_type_label(source_type: str, language: str = "zh") -> str:
    pair = SOURCE_TYPE_LABELS.get(source_type, (source_type, source_type))
    from .i18n import translate
    return pair[1] if language == "en" else translate(pair[0], language)


__all__ = [
    "API_MODEL_ALIASES",
    "BASIS_LABELS",
    "ComparisonGroup",
    "GROUPS",
    "REFERENCE_INDEX_VERSION",
    "SCENES",
    "DEFAULT_SCENE",
    "SCORE_FORMULA_VERSION",
    "ReferenceRow",
    "VERIFIED_DATE",
    "assert_primary_groups_unique",
    "best_score",
    "groups_for",
    "groups_for_model",
    "reference_api_model",
    "reference_coverage",
    "reference_entry",
    "reference_gap",
    "scene_label",
    "score_in_group",
    "secondary_record",
    "source_type_label",
]
