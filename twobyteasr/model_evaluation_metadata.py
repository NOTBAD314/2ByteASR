"""Traceable official ASR evaluation metadata for Technical Info pages.

Rules (P0):
- Only use data from official GitHub/HF/ModelScope pages or linked papers/technical reports.
- Never cite MMAU/MMAR or audio-reasoning leaderboards as transcription accuracy.
- ASR transcription accuracy uses CER/WER/RTF on speech recognition sets with documented conditions (dataset split, language, hardware if stated).
- Every number must carry its condition and a source URL (or repo path) so it is traceable.
- 2ByteASR stars + rationale are product workflow selection judgments, not official uniform scores.
  Always surface the disclaimer: "这是 2ByteASR 的工作流选型评价，不是官方统一跑分。"

This module is UI data only. It does not affect recognition pipelines or downloads.
"""

from __future__ import annotations

from copy import deepcopy

# Authoritative technical profiles used by ModelTechnicalDialog and workshop.
# Keys match WorkshopModel.key.
# Keep structure stable; UI renders sections from these fields.

_TECHNICAL_PROFILES: dict[str, dict] = {
    "moss": {
        "purpose": "中文长音频的第一遍转写与说话人区分。",
        "responsibility": "在 2ByteASR 中先生成完整文字骨架、说话人标签和片段时间信息；FireRed 再细化字词边界，Qwen3-ASR 再提供独立文字证据。",
        "principles": "Whisper-Medium 音频编码器提取 16 kHz、80 维 mel 特征，经 4 倍时间合并和 MLP 适配器送入 Qwen3-0.6B 风格因果解码器；模型以单条序列联合生成时间戳、说话人标签、正文和可选声学事件。",
        "strengths": "先保留完整语义，再向后续时间轴与文字复核提供稳定骨架。",
        "limits": "需要 NVIDIA CUDA；说话人标签是区分依据，不等同于自动识别真实姓名。",
        "io": "输入本地音频；输出初稿文本、分段和说话人证据。",
        "source": "2ByteASR 内置 MOSS 转写与说话人工作进程。",
        "url": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        "official": {
            "developer": "MOSI.AI / OpenMOSS",
            "series": "MOSS-Transcribe-Diarize",
            "params": "0.9B（端到端长音频多说话人模型）",
            "languages": ["50+ 语言"],
            "architecture": "Whisper-Medium encoder + Qwen3-0.6B-style causal decoder",
            "dialects": "官方未单独列出方言清单",
            "audio_type": "长音频、多说话人、会议/播客/视频",
            "license": "Apache-2.0",
            "runtime": "Transformers 5.x / SGLang Omni / vLLM",
            "repo": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        },
        "capabilities": ["长音频", "说话人区分", "时间戳", "事件感知"],
        "benchmarks": [
            {
                "metric": "CER",
                "value": "14.84%", "dataset": "AISHELL-4",
                "condition": "MOSS Transcribe Diarize 0.9B；长音频多说话人客观评测",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "cpCER", "value": "15.83%", "dataset": "AISHELL-4",
                "condition": "拼接后最小排列字符错误率；MOSS 0.9B",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "CER", "value": "24.86%", "dataset": "Alimeeting",
                "condition": "MOSS Transcribe Diarize 0.9B；长音频多说话人客观评测",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "cpCER", "value": "22.17%", "dataset": "Alimeeting",
                "condition": "拼接后最小排列字符错误率；MOSS 0.9B",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "CER", "value": "5.97%", "dataset": "Podcast",
                "condition": "MOSS Transcribe Diarize 0.9B；长音频多说话人客观评测",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "cpCER", "value": "7.37%", "dataset": "Podcast",
                "condition": "拼接后最小排列字符错误率；MOSS 0.9B",
                "hardware": "准确度表未声明硬件", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-15 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#evaluation",
            },
            {
                "metric": "RTF", "value": "0.0197", "dataset": "AISHELL-4 long",
                "condition": "SGLang Omni；concurrency=1；长序列多说话人 ASR",
                "hardware": "单张 NVIDIA H100", "direction": "越低越好",
                "source_updated": "官方 README（仓库 2026-08-16 状态）",
                "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize#serve-with-sglang-omni",
            },
        ],
        "condition": "官方 SGLang Omni 吞吐表使用单张 H100；上方准确度表未声明硬件。2ByteASR 本地路径使用 NVIDIA CUDA。",
        "resources": "官方推荐 Python 3.12 + Transformers 5.x；SGLang Omni 面向 CUDA 13，vLLM 同时给出 CUDA 12/13 路径。2ByteASR 使用独立 MOSS 环境。",
        "paper": "https://arxiv.org/abs/2601.01554",
        "twobyte": {
            "position": "主力转写",
            "reason": "中文长音频 + 说话人区分，适合作为第一遍主力转写保留完整语义骨架。",
        },
    },
    "firered": {
        "purpose": "中文/方言语音识别与细粒度时间轴。",
        "responsibility": "在 2ByteASR 中接收 MOSS 已保留的语义骨架，提供独立文字结果、字词级时间戳和置信度，主要用于第二阶段时间边界。",
        "principles": "FireRedASR2-AED 采用 Attention-based Encoder-Decoder，在单一高效模型中完成声学编码与自回归解码；官方接口可返回词级时间戳与置信度，2ByteASR 只把它用于时间轴和交叉证据。",
        "strengths": "擅长补足字词首尾边界，适合作为 MOSS 初稿之后的时间轴阶段。",
        "limits": "本机运行需要 CUDA；时间戳质量仍会受原始音频、多人重叠说话影响。",
        "io": "输入音频；输出识别文字与可用于字幕切分的时间边界。",
        "source": "FireRedASR 官方项目。",
        "url": "https://github.com/FireRedTeam/FireRedASR2S",
        "hf": "https://huggingface.co/FireRedTeam/FireRedASR2-AED",
        "official": {
            "developer": "FireRedTeam",
            "series": "FireRedASR2-AED",
            "params": "官方 README 未单列 AED 参数量",
            "languages": ["中文", "20+ 方言/口音", "English", "中英混说"],
            "architecture": "Attention-based Encoder-Decoder (AED)",
            "dialects": "粤语、四川、上海、吴语、闽南等 20+",
            "audio_type": "语音、歌唱、歌词",
            "license": "Apache-2.0",
            "runtime": "PyTorch / TensorRT-LLM",
            "repo": "https://github.com/FireRedTeam/FireRedASR2S",
        },
        "capabilities": ["时间戳", "长音频", "方言", "歌词识别"],
        "benchmarks": [
            {"metric": "CER", "value": "3.05%", "dataset": "Mandarin 4 集平均", "condition": "FireRedASR2-AED；AISHELL-1/2 + WenetSpeech net/meeting", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "CER", "value": "11.67%", "dataset": "中文方言/口音 19 集平均", "condition": "FireRedASR2-AED；19 个公开方言/口音测试集", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "CER", "value": "0.57%", "dataset": "AISHELL-1", "condition": "FireRedASR2-AED", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "CER", "value": "2.51%", "dataset": "AISHELL-2", "condition": "FireRedASR2-AED", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "CER", "value": "4.53%", "dataset": "WenetSpeech meeting", "condition": "FireRedASR2-AED", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "CER", "value": "3.60%", "dataset": "KeSpeech", "condition": "FireRedASR2-AED", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "FireRedASR2S README（仓库 2026-08-15 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S#fireredasr2"},
            {"metric": "相对推理速度", "value": "12.7x", "dataset": "AISHELL-1 test", "condition": "FireRedASR2-AED TensorRT-LLM 对比 PyTorch baseline", "hardware": "单张 NVIDIA H20", "direction": "越高越好", "source_updated": "官方 README（仓库 2026-08-16 状态）", "source": "https://github.com/FireRedTeam/FireRedASR2S"},
        ],
        "condition": "官方准确度评测覆盖 24 个公开测试集；中文用 CER、英文用 WER，均越低越好。TensorRT 12.7x 加速数据使用单张 H20，不与准确度指标混算。",
        "resources": "官方仅验证 Ubuntu 22.04；AED 单段建议不超过 60 秒，超过 200 秒会触发位置编码错误。2ByteASR 已在 UI 外的现有分块流程中满足该限制。",
        "paper": "https://arxiv.org/abs/2603.10420",
        "twobyte": {
            "position": "字幕时间轴",
            "reason": "时间边界能力更适合第二阶段字幕时间轴。",
        },
    },
    "qwen_local": {
        "purpose": "多语言文字复核与术语证据补充。",
        "responsibility": "在 2ByteASR 第三阶段对同一音频提供独立多语言转写结果，用于发现 MOSS 主稿中的文字、专名和混合语种差异；它不覆盖 MOSS 的说话人身份，也不直接重写时间轴。",
        "principles": "Qwen3-ASR 是统一流式/离线的自回归语音识别模型，基于 Qwen3-Omni 的音频理解能力，同时完成语种识别和转写；需要时间戳时再配合独立的 Qwen3-ForcedAligner 非自回归对齐模型。",
        "strengths": "对专名、多语言片段和文字差异提供第二路本地参考。",
        "limits": "下载体积与显存占用较高；它在本项目中是复核角色，不替代完整任务流程。",
        "io": "输入已分段的音频/文本上下文；输出文字候选和复核证据。",
        "source": "Qwen3-ASR 官方发布版本与 2ByteASR 本地适配。",
        "url": "https://github.com/QwenLM/Qwen3-ASR",
        "hf": "https://huggingface.co/Qwen/Qwen3-ASR-1.7B",
        "official": {
            "developer": "Qwen Team / Alibaba",
            "series": "Qwen3-ASR",
            "params": "1.7B",
            "languages": ["30 种语言", "22 种中文方言"],
            "architecture": "Qwen3-Omni-derived autoregressive ASR",
            "dialects": "22 种中文方言/口音",
            "audio_type": "语音、歌唱、带 BGM 歌曲",
            "license": "Apache-2.0",
            "runtime": "Transformers / qwen-asr / vLLM",
            "repo": "https://github.com/QwenLM/Qwen3-ASR",
        },
        "capabilities": ["多语言", "方言", "语种识别", "流式/离线", "长音频", "歌唱识别"],
        "benchmarks": [
            {"metric": "WER", "value": "2.71%", "dataset": "AISHELL-2 test", "condition": "Qwen3-ASR-1.7B；官方同表中文评测（同表 Whisper-large-v3 5.06 / GPT-4o 4.24 / Doubao 2.85）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "4.97%", "dataset": "WenetSpeech test_net", "condition": "Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 9.86 / Gemini-2.5-Pro 14.43）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "5.88%", "dataset": "WenetSpeech test_meeting", "condition": "Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 19.11 / Gemini-2.5-Pro 13.47）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "2.88%", "dataset": "SpeechIO", "condition": "Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 7.56 / Doubao 2.93）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "2.41%", "dataset": "Fleurs-zh", "condition": "Qwen3-ASR-1.7B；离线模式；统一官方评测设置", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "5.35%", "dataset": "CommonVoice zh", "condition": "Qwen3-ASR-1.7B；官方同表", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "5.10%", "dataset": "KeSpeech（方言）", "condition": "Qwen3-ASR-1.7B；官方同表（同表 Whisper-large-v3 28.79）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "3.98%", "dataset": "Fleurs-yue（粤语）", "condition": "Qwen3-ASR-1.7B；官方同表", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "1.63%", "dataset": "LibriSpeech test-clean", "condition": "Qwen3-ASR-1.7B；vLLM；bfloat16；max_new_tokens=1024；greedy；不指定语言（英语 WER，不代表中文 CER）", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "3.38%", "dataset": "LibriSpeech test-other", "condition": "Qwen3-ASR-1.7B；vLLM；bfloat16；max_new_tokens=1024；greedy；不指定语言", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "8.55%", "dataset": "MLS（8 语种）", "condition": "Qwen3-ASR-1.7B；官方多语言公开集汇总", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（仓库 2026-08-15 状态）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "9.18%", "dataset": "CommonVoice（13 语种）", "condition": "Qwen3-ASR-1.7B；官方多语言公开集汇总", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（仓库 2026-08-15 状态）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "5.98%", "dataset": "M4Singer", "condition": "Qwen3-ASR-1.7B；歌唱转写评测", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（仓库 2026-08-15 状态）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
        ],
        "condition": "官方统一使用 vLLM、bfloat16、max_new_tokens=1024、greedy decoding，且测试不指定语言参数。中文集行为 2026-09-18 补核；LibriSpeech/MLS/CommonVoice 为英语或多语 WER，不与中文 CER 混排。",
        "resources": "官方建议独立 Python 3.12 环境，并推荐 FlashAttention 2；Transformers 与 vLLM 均支持 CUDA，本地 1.7B 仍需按批大小控制显存。",
        "paper": "https://arxiv.org/abs/2601.21337",
        "twobyte": {
            "position": "文字复核",
            "reason": "文字准确度与专名复核能力适合作为第三阶段复核。",
        },
    },
    "sensevoice": {
        "purpose": "轻量多语言语音识别与文字复核。",
        "responsibility": "作为低资源本地后端，为中文、粤语和常见多语种提供第二路文字证据；独立 SenseVoiceSmall checkpoint 不承担说话人分离。",
        "principles": "SenseVoiceSmall 采用非自回归端到端框架，一次前向同时输出转写、语种、情感和音频事件标签；长音频通过 FunASR 的独立 VAD 分段处理。",
        "strengths": "CPU 也可使用，对中文、粤语和常见多语种较友好。",
        "limits": "当前不提供 MOSS 的多人说话人骨架；更适合做独立文字证据。",
        "io": "输入音频；输出多语言文字结果及可选事件/情感信息。",
        "source": "FunAudioLLM SenseVoice 官方项目。",
        "url": "https://github.com/FunAudioLLM/SenseVoice",
        "hf": "https://huggingface.co/FunAudioLLM/SenseVoiceSmall",
        "official": {
            "developer": "FunAudioLLM (Alibaba)",
            "series": "SenseVoiceSmall",
            "params": "约 234M（与 Whisper-Small 同级）",
            "languages": ["中文", "粤语", "English", "日本語", "한국어"],
            "architecture": "非自回归端到端音频理解模型",
            "dialects": "粤语；其它中文方言未由该 checkpoint 单列",
            "audio_type": "语音 + 情感/事件标签",
            "license": "代码 MIT；权重为 FunASR 模型协议",
            "runtime": "FunASR / ONNX / libtorch / llama.cpp",
            "repo": "https://github.com/FunAudioLLM/SenseVoice",
        },
        "capabilities": ["多语言", "LID", "情感", "音频事件"],
        "benchmarks": [
            {"metric": "CER", "value": "2.96%", "dataset": "AISHELL-1 test", "condition": "SenseVoice 技术报告 Table 6（同表 Whisper-Small 10.04 / Whisper-Large-v3 5.14）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "CER", "value": "3.80%", "dataset": "AISHELL-2 test_ios", "condition": "SenseVoice 技术报告 Table 6", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "CER", "value": "7.44%", "dataset": "WenetSpeech test_meeting", "condition": "SenseVoice 技术报告 Table 6", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "CER", "value": "7.84%", "dataset": "WenetSpeech test_net", "condition": "SenseVoice 技术报告 Table 6", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "WER", "value": "3.15%", "dataset": "LibriSpeech test_clean", "condition": "SenseVoice 技术报告 Table 6（英语 WER，不代表中文 CER）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "WER", "value": "7.18%", "dataset": "LibriSpeech test_other", "condition": "SenseVoice 技术报告 Table 6", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "推理延迟", "value": "70ms", "dataset": "10 秒音频端到端延迟", "condition": "SenseVoice 技术报告 Table 7；延迟指标，不与 RTF/吞吐互换", "hardware": "报告实验环境", "direction": "越低越好", "source_updated": "arXiv 2407.04051v3（2026-09-18 核对）", "source": "https://arxiv.org/html/2407.04051v3"},
            {"metric": "相对推理速度", "value": ">5x", "dataset": "官方 inference benchmark", "condition": "SenseVoiceSmall 对比 Whisper-Small；同一官方图示条件", "hardware": "具体硬件见官方 benchmark 图", "direction": "越高越好", "source_updated": "SenseVoice README（仓库 2026-09-18 状态）", "source": "https://github.com/QwenAudio/SenseVoice#benchmarks"},
            {"metric": "相对推理速度", "value": ">15x", "dataset": "官方 inference benchmark", "condition": "SenseVoiceSmall 对比 Whisper-Large；同一官方图示条件", "hardware": "具体硬件见官方 benchmark 图", "direction": "越高越好", "source_updated": "SenseVoice README（仓库 2026-09-18 状态）", "source": "https://github.com/QwenAudio/SenseVoice#benchmarks"},
        ],
        "condition": "准确率数值来自 SenseVoice 技术报告 Table 6（2026-09-18 核对）；README 的详细准确率表仍以图片发布、无法逐项核对，速度倍数仅引用 README 明文。同表 Whisper-Large-v3 数值（AISHELL-1 5.14 等）属对照系统且非本工程 turbo checkpoint，只在此备注、不并入其卡片。",
        "resources": "支持 CUDA、ONNX、libtorch 与 llama.cpp/GGUF CPU 路径；说话人分离需另配 FSMN-VAD + CAM++，不是 checkpoint 原生能力。",
        "paper": "https://arxiv.org/abs/2407.04051",
        "twobyte": {
            "position": "文字复核",
            "reason": "轻量多语言，适合作为独立文字证据或低资源场景的备选。",
        },
    },
    "paraformer": {
        "purpose": "中文长音频识别与轻量时间轴后端。",
        "responsibility": "在 2ByteASR 中作为可选中文时间轴后端，以非自回归识别和时间戳补充 MOSS 初稿；它不替代 MOSS 的多人说话人骨架。",
        "principles": "Paraformer 是非自回归端到端 ASR：编码器提取声学表示，预测器估计目标长度并生成声学向量，解码器并行输出文字；FunASR 再组合 VAD、标点和热词形成长音频 pipeline。",
        "strengths": "非自回归路线、支持热词，可与 VAD/标点组件配合，速度取向明显。",
        "limits": "当前 2ByteASR 将它用于时间轴角色；主力多人转写仍以 MOSS 为准。",
        "io": "输入音频与可选热词；输出中文文字和后端提供的时间信息。",
        "source": "ModelScope FunASR 官方项目。",
        "url": "https://github.com/modelscope/FunASR",
        "modelscope": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary",
        "official": {
            "developer": "FunASR / ModelScope",
            "series": "Paraformer Large",
            "params": "约 220M",
            "languages": ["中文"],
            "architecture": "Paraformer 非自回归端到端 ASR",
            "dialects": "官方模型卡未单列方言覆盖",
            "audio_type": "16 kHz 中文语音；长音频由 VAD pipeline 分段",
            "license": "模型页所列 Apache-2.0",
            "runtime": "FunASR / ModelScope / ONNX Runtime",
            "repo": "https://github.com/modelscope/FunASR",
        },
        "capabilities": ["热词", "时间戳", "长音频"],
        "benchmarks": [
            {"metric": "CER", "value": "1.95%", "dataset": "AISHELL-1 test", "condition": "Paraformer Large 官方卡 w/o LM 解码（w/ LM 1.68）；同表对照 Espnet 4.90 / WeNet 4.61", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对，卡片 v2.0.4）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "CER", "value": "2.80%", "dataset": "AISHELL-2 dev_ios", "condition": "Paraformer Large 官方卡（同表 WeNet test_ios 5.39）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "CER", "value": "2.85%", "dataset": "AISHELL-2 test_ios", "condition": "Paraformer Large 官方卡（test_android 3.13 / test_mic 3.06）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "CER", "value": "3.57%", "dataset": "WenetSpeech dev", "condition": "Paraformer Large 官方卡 w/o LM", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "CER", "value": "6.97%", "dataset": "WenetSpeech test_meeting", "condition": "Paraformer Large 官方卡 w/o LM（同表 Espnet 15.90 / WeNet 17.34 / K2 13.41）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "CER", "value": "6.74%", "dataset": "WenetSpeech test_net", "condition": "Paraformer Large 官方卡 w/o LM", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
            {"metric": "RTF", "value": "0.0251", "dataset": "官方卡 indexing 结果", "condition": "GPU 推理 V100、batch_size=1；官方参考速度，与本机或其它硬件不可直接互比", "hardware": "NVIDIA V100", "direction": "越低越好", "source_updated": "官方 ModelScope 模型卡（2026-09-18 核对）", "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary"},
        ],
        "condition": "数值来自 Paraformer Large 官方模型卡当前表格（2026-09-18 核对，卡片 v2.0.4）；不同 pipeline 组件、热词和音频分段策略会改变实际结果。RTF 为官方 V100 参考值，不参与跨模型速度排名。",
        "resources": "官方支持 CPU/CUDA 与 ONNX 路径；2ByteASR 实际建议按现有独立 FunASR 环境运行，长音频继续使用既有 VAD 分块。",
        "paper": "https://arxiv.org/abs/2206.08317",
        "twobyte": {
            "position": "字幕时间轴",
            "reason": "非自回归 + 热词，速度取向，适合时间轴/轻量中文场景。",
        },
    },
    "whisper": {
        "purpose": "通用多语言语音转写与复核。",
        "responsibility": "在 2ByteASR 中作为可选多语种文字复核或时间轴证据，适合中文之外及混合语种片段；不承担 MOSS 的说话人区分。",
        "principles": "Whisper 是编码器-解码器 Transformer：把音频转成 log-Mel 频谱，由多任务序列 token 同时表达语种、转写/翻译与时间戳。large-v3-turbo 缩短了解码器以换取更快推理。",
        "strengths": "语言覆盖广，适合混合语种或非中文内容提供第二路证据。",
        "limits": "不包含 MOSS 的说话人区分；不同硬件上的速度差异较大。",
        "io": "输入音频；输出转写文字和片段级时间信息。",
        "source": "OpenAI Whisper 官方项目。",
        "url": "https://github.com/openai/whisper",
        "hf": "https://huggingface.co/openai/whisper-large-v3-turbo",
        "official": {
            "developer": "OpenAI",
            "series": "Whisper large-v3-turbo",
            "params": "809M",
            "languages": ["多语言（99 种语言训练覆盖）"],
            "architecture": "Encoder-decoder Transformer",
            "dialects": "官方未提供独立方言清单",
            "audio_type": "通用语音；30 秒窗口与长音频滑窗",
            "license": "MIT",
            "runtime": "PyTorch / Transformers / faster-whisper",
            "repo": "https://github.com/openai/whisper",
        },
        "capabilities": ["多语言", "时间戳"],
        "benchmarks": [
            {"metric": "WER", "value": "7.83%", "dataset": "HF OpenASR 榜单 8 集均值（英语）", "condition": "whisper-large-v3-turbo；官方 HF 模型卡所载 OpenASR 榜单结果（whisper-normalizer 口径）", "hardware": "OpenASR 榜单统一环境", "direction": "越低越好", "source_updated": "openai/whisper-large-v3-turbo HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/openai/whisper-large-v3-turbo"},
            {"metric": "WER", "value": "2.10%", "dataset": "LibriSpeech test-clean（OpenASR）", "condition": "whisper-large-v3-turbo；英语 WER", "hardware": "OpenASR 榜单统一环境", "direction": "越低越好", "source_updated": "openai/whisper-large-v3-turbo HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/openai/whisper-large-v3-turbo"},
            {"metric": "WER", "value": "4.24%", "dataset": "LibriSpeech test-other（OpenASR）", "condition": "whisper-large-v3-turbo；英语 WER", "hardware": "OpenASR 榜单统一环境", "direction": "越低越好", "source_updated": "openai/whisper-large-v3-turbo HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/openai/whisper-large-v3-turbo"},
            {"metric": "RTFx", "value": "200.19", "dataset": "HF OpenASR 榜单（英语）", "condition": "whisper-large-v3-turbo；RTFx=1/RTF，越高越快；榜单统一环境参考，不代表本机速度", "hardware": "OpenASR 榜单统一环境", "direction": "越高越好", "source_updated": "openai/whisper-large-v3-turbo HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/openai/whisper-large-v3-turbo"},
        ],
        "condition": "官方 large-v3-turbo 模型卡未发布逐中文数据集数值表；此处英语成绩来自官方卡所载 OpenASR 榜单（独立评测口径），中文能力没有同协议横评数据，不在中文场景评分。",
        "resources": "官方模型卡列出约 6 GB 相对显存需求；2ByteASR 可使用现有 CUDA 后端，本机速度仍取决于实现与音频长度。",
        "paper": "https://arxiv.org/abs/2212.04356",
        "twobyte": {
            "position": "文字复核",
            "reason": "多语言覆盖广，适合非中文或混合语种的第二路证据。",
        },
    },
    "qwen_aligner": {
        "purpose": "依据已有文字生成字/词级时间边界。",
        "responsibility": "在 2ByteASR 中可替换 FireRed 的时间轴角色：接收已经确认的文字和音频，只计算字词对齐，不重新决定字幕内容。",
        "principles": "Qwen3-ForcedAligner 是非自回归强制对齐模型，同时读取音频和给定文本，直接预测每个字符或单词的时间位置；它不是从零开始的语音转写模型。",
        "strengths": "当主稿可靠时能把文字稳定映射到多语种字词时间戳，避免对齐阶段再次改写原文。",
        "limits": "必须先有可靠文本；错字、漏字、多人重叠和强噪声会直接影响对齐，且本地运行需要 CUDA。",
        "io": "输入音频 + 已有文字；输出字符/单词的起止时间。",
        "source": "Qwen3-ForcedAligner 官方模型卡。",
        "url": "https://github.com/QwenLM/Qwen3-ASR",
        "hf": "https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B",
        "official": {
            "developer": "Qwen Team / Alibaba",
            "series": "Qwen3-ForcedAligner",
            "params": "0.6B",
            "languages": ["11 种语言"],
            "architecture": "非自回归 forced alignment",
            "dialects": "随支持语言对齐；官方未单列方言 Benchmark",
            "audio_type": "语音 + 已知转写文本",
            "license": "Apache-2.0",
            "runtime": "qwen-asr / Transformers",
            "repo": "https://github.com/QwenLM/Qwen3-ASR",
        },
        "capabilities": ["字级对齐", "词级对齐", "多语言", "原文保留"],
        "benchmarks": [
            {"metric": "AAS", "value": "33.1 ms", "dataset": "MFA Raw 中文", "condition": "Qwen3-ForcedAligner-0.6B；官方 alignment 评测", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Qwen3-ASR README（仓库 2026-08-15 状态）", "source": "https://github.com/QwenLM/Qwen3-ASR#qwen3-forcedaligner"},
            {"metric": "AAS", "value": "37.5 ms", "dataset": "MFA Raw 英文", "condition": "Qwen3-ForcedAligner-0.6B；官方 alignment 评测", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Qwen3-ASR README（仓库 2026-08-15 状态）", "source": "https://github.com/QwenLM/Qwen3-ASR#qwen3-forcedaligner"},
        ],
        "condition": "AAS 表示平均对齐偏差，单位毫秒，越低越好；该指标只衡量给定文本的对齐，不代表从零转写准确率。",
        "resources": "官方 qwen-asr 路径使用 CUDA；2ByteASR 实际建议把它放在可靠主稿之后，避免把文本错误传递给对齐阶段。",
        "paper": "https://arxiv.org/abs/2601.21337",
        "twobyte": {"position": "字幕时间轴", "reason": "只对齐已有文字，适合在不改写主稿的前提下生成多语种字词时间戳。"},
    },
    "funasr_nano": {
        "purpose": "中文方言与多语种的本地文字复核。",
        "responsibility": "在 2ByteASR 中作为可选本地复核后端，为中文方言和多语种片段提供第二路文字证据；不承担多人说话人骨架。",
        "principles": "Fun-ASR-Nano 采用音频编码器连接语言模型的端到端路线，直接生成转写文本，并通过可配置上下文增强专名与热词；2ByteASR 仅消费其独立文字证据。",
        "strengths": "兼顾中文方言、多语种和上下文增强，适合专名较多的游戏内容复核。",
        "limits": "0.8B 本地模型仍需要独立运行环境和显存；作为复核后端不提供 MOSS 的说话人区分。",
        "io": "输入音频与可选上下文；输出多语言/方言转写文字。",
        "source": "FunAudioLLM Fun-ASR 官方项目。",
        "url": "https://github.com/FunAudioLLM/Fun-ASR",
        "hf": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512",
        "official": {
            "developer": "FunAudioLLM (Alibaba)",
            "series": "Fun-ASR-Nano-2512",
            "params": "0.8B",
            "languages": ["多语言", "中文方言"],
            "architecture": "音频编码器 + LLM 的端到端 ASR",
            "dialects": "覆盖多种中文方言；以官方模型卡清单为准",
            "audio_type": "语音、长音频分块",
            "license": "以官方模型卡协议为准",
            "runtime": "FunASR / Transformers",
            "repo": "https://github.com/FunAudioLLM/Fun-ASR",
        },
        "capabilities": ["中文方言", "多语言", "上下文增强", "长音频"],
        "benchmarks": [
            {"metric": "CER", "value": "1.80%", "dataset": "AISHELL-1", "condition": "Fun-ASR-Nano-2512 官方模型卡自报（同表 Fun-ASR 7.7B 1.22，闭源）", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "CER", "value": "2.75%", "dataset": "AISHELL-2", "condition": "Fun-ASR-Nano-2512 官方模型卡自报", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "CER", "value": "2.56%", "dataset": "Fleurs-zh", "condition": "Fun-ASR-Nano-2512 官方模型卡自报；Qwen3-ASR 官方表同集复测为 3.51，两来源并列保留、不合并", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "WER", "value": "3.51%", "dataset": "Fleurs-zh（Qwen3-ASR 官方表复测）", "condition": "Qwen3-ASR README 同表对 Fun-ASR-Nano 的复测值；与 Fun 自报 2.56 属不同评测管线", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "6.35%", "dataset": "WenetSpeech test_net（Qwen3-ASR 官方表复测）", "condition": "Qwen3-ASR README 同表复测；Fun 自报同集 6.01", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "1.68%", "dataset": "LibriSpeech test-clean（Qwen3-ASR 官方表复测）", "condition": "Qwen3-ASR README 同表复测；Fun 自报 1.76", "hardware": "官方未声明具体 GPU", "direction": "越低越好", "source_updated": "Qwen3-ASR README（2026-09-18 核对）", "source": "https://github.com/QwenLM/Qwen3-ASR#evaluation"},
            {"metric": "WER", "value": "1.76%", "dataset": "LibriSpeech test-clean", "condition": "Fun-ASR-Nano-2512 官方模型卡自报", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "WER", "value": "4.33%", "dataset": "LibriSpeech test-other", "condition": "Fun-ASR-Nano-2512 官方模型卡自报", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "CER", "value": "6.60%", "dataset": "WenetSpeech meeting", "condition": "Fun-ASR-Nano-2512 官方模型卡自报", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
            {"metric": "CER", "value": "6.01%", "dataset": "WenetSpeech net", "condition": "Fun-ASR-Nano-2512 官方模型卡自报", "hardware": "准确度表未声明硬件", "direction": "越低越好", "source_updated": "Fun-ASR HF 模型卡（2026-09-18 核对）", "source": "https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512"},
        ],
        "condition": "Fun 自报值与 Qwen3-ASR 官方表复测值是两套评测管线，同名数据集数字有差异（Fleurs-zh 2.56 vs 3.51），按来源分行保留、绝不合并成一张榜。官方模型卡 TODO 明示：时间戳与说话人分离能力暂未随 2512 checkpoint 提供。",
        "resources": "官方提供 FunASR/Transformers 路径；2ByteASR 实际建议使用现有独立模型环境，并按本机显存控制批量。",
        "twobyte": {"position": "文字复核", "reason": "方言与多语种覆盖适合为游戏专名和口音片段补一份独立文字证据。"},
    },
    "firered_llm": {
        "purpose": "面向中文、方言与中英混说的高精度主力转写候选。",
        "responsibility": "作为高级用户可选的主力转写模型；不替代默认 MOSS / FireRed AED / Qwen 组合，也不承担默认时间轴角色。",
        "principles": "8B+ Encoder-Adapter-LLM：语音编码器经 Adapter 接入 Qwen2-7B-Instruct，利用语言模型完成端到端转写。",
        "strengths": "官方中文普通话与 19 组方言评测均优于同表对比模型，并支持中英混说、语音与歌唱。",
        "limits": "单段音频最多 40 秒，权重和显存占用明显高于 AED；长视频仍必须由 2ByteASR 分块。",
        "io": "输入最长 40 秒音频块；输出转写文本。",
        "source": "FireRedASR2-LLM 官方 Hugging Face Model Card。",
        "url": "https://github.com/FireRedTeam/FireRedASR2S",
        "hf": "https://huggingface.co/FireRedTeam/FireRedASR2-LLM",
        "official": {"developer": "FireRedTeam", "series": "FireRedASR2-LLM", "params": "8B+", "languages": ["中文普通话", "English"], "architecture": "Encoder-Adapter-LLM (Qwen2-7B-Instruct)", "dialects": "20+ 中文方言/口音", "audio_type": "语音、歌唱、中英混说", "license": "Apache-2.0", "runtime": "FireRedASR2S / PyTorch", "repo": "https://github.com/FireRedTeam/FireRedASR2S"},
        "capabilities": ["中文", "方言", "English", "Code Switching", "歌唱"],
        "benchmarks": [
            {"metric": "CER", "value": "2.89%", "dataset": "Mandarin, 4-set average", "condition": "FireRedASR2 官方 Model Card 汇总", "hardware": "官方准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 Model Card（revision 2c5e0f4）", "source": "https://huggingface.co/FireRedTeam/FireRedASR2-LLM"},
            {"metric": "CER", "value": "11.55%", "dataset": "Chinese dialects, 19-set average", "condition": "FireRedASR2 官方 Model Card 汇总", "hardware": "官方准确度表未声明硬件", "direction": "越低越好", "source_updated": "官方 Model Card（revision 2c5e0f4）", "source": "https://huggingface.co/FireRedTeam/FireRedASR2-LLM"},
            {"metric": "RTF", "value": "0.0681", "dataset": "Official hello_zh / hello_en examples", "condition": "官方示例返回值；不是统一批量 Benchmark", "hardware": "官方示例未声明", "direction": "越低越好", "source_updated": "官方 Model Card（revision 2c5e0f4）", "source": "https://huggingface.co/FireRedTeam/FireRedASR2-LLM"},
        ],
        "condition": "两项 CER 来自同一官方 Model Card 表。RTF 0.0681 来自 hello_zh / hello_en 样例输出，硬件未声明，因此只按官方示例展示，不用于跨模型精确比较。",
        "resources": "官方权重文件约 17.57 GiB；独立 .venv-firered-llm Runtime。已在 RTX 5070 Ti 16 GB 上通过 20 秒中文及中英混合 fixture；推理时显存接近满载。",
        "twobyte": {"position": "高级主力转写候选", "reason": "中文普通话 4 集均值同表最佳（CER 2.89%）；速度暂无同组数据，本机未实测。"},
    },
    "glm_asr_nano": {
        "purpose": "中文、英文、粤语与方言场景的轻量主力转写候选。",
        "responsibility": "作为高级用户可选的主力转写模型，通过独立 GLM Adapter 运行，不改变默认 Pipeline。",
        "principles": "官方描述为 1.5B 参数语音识别模型，使用 Transformers 的 GLM-ASR 条件生成架构。",
        "strengths": "面向粤语、方言、低音量和安静语音优化，并覆盖 17 种高可用语言。",
        "limits": "官方当前要求 Transformers 源码/5.x 路径，与主环境锁定版本不兼容，必须隔离。",
        "io": "输入音频；输出带规范文本的转写。",
        "source": "Z.ai GLM-ASR-Nano-2512 官方 Model Card。",
        "hf": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512",
        "official": {"developer": "Z.ai", "series": "GLM-ASR-Nano-2512", "params": "1.5B 官方描述；HF metadata 2,257,843,200", "languages": ["中文", "English", "粤语", "17 种高可用语言"], "architecture": "GLM-ASR conditional generation", "dialects": "粤语与其它方言优化", "audio_type": "语音，包含低音量/安静语音", "license": "MIT", "runtime": "Transformers 5.x / SGLang（规划）", "repo": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512"},
        "capabilities": ["中文", "English", "粤语", "方言", "低音量语音"],
        "benchmarks": [
            {"metric": "Average error", "value": "4.10", "dataset": "Official repository benchmark", "condition": "官方仓库汇总；与 OpenASR 不是同一评测", "hardware": "官方摘要未声明", "direction": "越低越好", "source_updated": "官方 Model Card（revision 61ba4e0）", "source": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512"},
            {"metric": "Mean WER", "value": "7.03%", "dataset": "Hugging Face OpenASR", "condition": "OpenASR leaderboard 评测", "hardware": "OpenASR 条件见评测 YAML", "direction": "越低越好", "source_updated": "官方仓库 .eval_results", "source": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512/blob/main/.eval_results/open_asr_leaderboard.yaml"},
            {"metric": "RTFx", "value": "145.28", "dataset": "Hugging Face OpenASR", "condition": "OpenASR leaderboard 评测", "hardware": "OpenASR 条件见评测 YAML", "direction": "越高越好", "source_updated": "官方仓库 .eval_results", "source": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512/blob/main/.eval_results/open_asr_leaderboard.yaml"},
        ],
        "condition": "Official Repo Benchmark 与 Hugging Face OpenASR 是两套来源，页面分行展示。官方正文称 1.5B，HF safetensors metadata 当前统计 2,257,843,200 parameters，两者原样并列，不擅自改写。",
        "resources": "官方仓库必需文件约 4.21 GiB；独立 .venv-glm-asr Runtime，不升级 .venv-main。",
        "twobyte": {"position": "高级主力转写候选", "reason": "英语 OpenASR 榜单口径 Mean WER 7.03%（官方卡自报）；中文无同表数据，不做跨场景推断。"},
    },
    "canary_qwen": {
        "purpose": "English 专用的高吞吐主力转写候选。",
        "responsibility": "只用于官方支持的 English ASR 场景，通过独立 NVIDIA NeMo Runtime 运行。",
        "principles": "Speech-Augmented Language Model，组合 FastConformer speech encoder 与 Qwen language model。",
        "strengths": "英文 ASR 支持标点和大小写，官方 OpenASR 表给出高 RTFx。",
        "limits": "仅可靠支持 English；训练最大音频长度 40 秒，长输入精度可能下降；NeMo 依赖较重。",
        "io": "输入 English 音频块；输出带标点和大小写的英文文本。",
        "source": "NVIDIA Canary-Qwen-2.5B 官方 Model Card。",
        "hf": "https://huggingface.co/nvidia/canary-qwen-2.5b",
        "official": {"developer": "NVIDIA", "series": "Canary-Qwen-2.5B", "params": "2.5B", "languages": ["English"], "architecture": "FastConformer + Qwen Speech-Augmented Language Model", "dialects": "官方未单列", "audio_type": "English speech, max training duration 40s", "license": "CC-BY-4.0", "runtime": "NVIDIA NeMo 2.5+", "repo": "https://huggingface.co/nvidia/canary-qwen-2.5b"},
        "capabilities": ["English ASR", "Punctuation", "Capitalization"],
        "benchmarks": [
            {"metric": "Mean WER", "value": "5.63%", "dataset": "Hugging Face OpenASR", "condition": "whisper-normalizer 0.1.12", "hardware": "NVIDIA A100（官方 Model Card）", "direction": "越低越好", "source_updated": "官方 Model Card（revision b1469e1）", "source": "https://huggingface.co/nvidia/canary-qwen-2.5b"},
            {"metric": "WER", "value": "1.60%", "dataset": "LibriSpeech test-clean", "condition": "官方 OpenASR 表", "hardware": "NVIDIA A100（官方 Model Card）", "direction": "越低越好", "source_updated": "官方 Model Card（revision b1469e1）", "source": "https://huggingface.co/nvidia/canary-qwen-2.5b"},
            {"metric": "RTFx", "value": "418", "dataset": "Hugging Face OpenASR", "condition": "官方 OpenASR 表", "hardware": "NVIDIA A100（官方 Model Card）", "direction": "越高越好", "source_updated": "官方 Model Card（revision b1469e1）", "source": "https://huggingface.co/nvidia/canary-qwen-2.5b"},
        ],
        "condition": "英语成绩仅适用于官方支持的 English ASR。官方卡正文称 2.5B、HF 元数据统计约 3B，两者原样并列；推理验证环境含 A6000/A100/RTX 5090。",
        "resources": "官方权重约 4.77 GiB；独立 .venv-canary-qwen NeMo Runtime，不向主 UI 环境安装 NeMo。",
        "twobyte": {"position": "高级 English 主力转写候选", "reason": "英语 OpenASR 榜单 Mean WER 5.63% / RTFx 418（同表最佳）；仅限 English 场景，不代表多语言能力。"},
    },
    "omni_asr_llm_7b": {
        "purpose": "为极广语言覆盖提供 1600+ 语言主力转写候选。",
        "responsibility": "作为高级多语言模型独立运行，不替换默认中文工作流。",
        "principles": "Omnilingual ASR LLM 7B 支持可选语言条件，官方参数量 7,801,041,536。",
        "strengths": "覆盖 1600+ 语言，适合其它模型未覆盖的低资源语言。",
        "limits": "模型约 30 GiB，BF16 推理约需 17 GiB 显存；官方 RTF 接近实时，不适合低显存机器。",
        "io": "输入音频与可选 language conditioning；输出对应语言文字。",
        "source": "Meta Omnilingual ASR 官方 Model Card 与论文。",
        "hf": "https://huggingface.co/facebook/omniASR-LLM-7B",
        "paper": "https://ai.meta.com/research/publications/omnilingual-asr-open-source-multilingual-speech-recognition-for-1600-languages/",
        "official": {"developer": "Meta", "series": "omniASR-LLM-7B", "params": "7,801,041,536", "languages": ["1600+ 语言"], "architecture": "Omnilingual wav2vec2 + LLM ASR", "dialects": "按官方语言 ID 清单", "audio_type": "Speech with optional language conditioning", "license": "Apache-2.0", "runtime": "omnilingual-asr / fairseq2", "repo": "https://github.com/facebookresearch/omnilingual-asr"},
        "capabilities": ["1600+ 语言", "可选语言条件", "低资源语言"],
        "benchmarks": [
            {"metric": "RTF", "value": "0.092", "dataset": "Official runtime measurement", "condition": "batch=1, audio_len=30s, BF16", "hardware": "NVIDIA A100", "direction": "越低越好", "source_updated": "官方 Model Card（revision 4b0bada）", "source": "https://huggingface.co/facebook/omniASR-LLM-7B"},
        ],
        "condition": "官方 RTF 条件为 A100、batch 1、30 秒音频、BF16；不能外推为其它 GPU 的速度。",
        "resources": "官方 Download Size 30.0 GiB；HF 必需文件实测 29.06 GiB；BF16 VRAM 约 17 GiB。独立 .venv-omni-asr Runtime。",
        "twobyte": {"position": "高级多语言主力转写候选", "reason": "官方模型卡未提供可比准确率表（未找到可核实数据）；RTF 0.092（A100/BF16/batch1/30s）为官方参考。"},
    },
    "qwen_api": {
        "purpose": "免下载的 Qwen3-ASR-Flash 在线转写。",
        "responsibility": "在 2ByteASR 中作为在线文字复核来源，按短音频块返回独立文字；不提供本地模型资产，也不替代 MOSS 的说话人骨架。",
        "principles": "通过阿里云百炼 DashScope 多模态语音接口调用托管模型。底层推理、扩缩容与模型更新由服务商管理，客户端只提交音频并读取转写结果。",
        "strengths": "无需下载和占用本地显存，配置密钥后可快速开始。",
        "limits": "依赖网络、账户额度、服务可达性与云端模型版本；数据处理受服务条款约束。",
        "io": "上传分块音频；返回在线转写文字。",
        "source": "阿里云百炼 Qwen 语音识别官方文档。",
        "url": "https://help.aliyun.com/zh/model-studio/qwen-audio",
        "official": {"developer": "Alibaba Cloud / Qwen", "series": "qwen3-asr-flash", "params": "云服务未公开", "languages": ["以当前官方模型文档为准"], "architecture": "托管 ASR 服务；底层参数未公开", "dialects": "以当前官方模型文档为准", "audio_type": "在线音频转写", "license": "阿里云服务条款", "runtime": "DashScope API", "repo": "官方未提供独立开源仓库"},
        "capabilities": ["免下载", "在线转写", "低本地占用"],
        "benchmarks": [],
        "condition": "云服务文档未提供一组可与本地模型统一条件横向比较的公开数值；服务版本可能随平台更新。",
        "resources": "官方要求可用的 DashScope 账户、API Key 与网络；2ByteASR 本机无需模型显存，但需要稳定上传带宽。",
        "twobyte": {"position": "在线文字复核", "reason": "免下载且启动快，适合本地资源不足时补充一份在线文字证据。"},
    },
    "groq_api": {
        "purpose": "通过 GroqCloud 调用 Whisper large-v3-turbo。",
        "responsibility": "在 2ByteASR 中作为在线多语种复核来源，按短块提供独立转写；不参与本地说话人区分。",
        "principles": "使用 OpenAI 风格 audio/transcriptions 协议，把音频发送到 Groq 托管的 Whisper large-v3-turbo；模型仍是编码器-解码器 Transformer，推理由 GroqCloud 执行。",
        "strengths": "本地零模型占用，服务侧推理速度取向明显。",
        "limits": "依赖境外网络、Groq 账户额度和服务支持的文件/时长限制。",
        "io": "上传音频块；返回多语言转写文字。",
        "source": "GroqCloud Speech-to-Text 官方文档与 OpenAI Whisper 官方模型。",
        "url": "https://console.groq.com/docs/speech-to-text",
        "official": {"developer": "Groq（托管）/ OpenAI（模型）", "series": "whisper-large-v3-turbo", "params": "809M（模型）", "languages": ["多语言"], "architecture": "Whisper encoder-decoder Transformer", "dialects": "服务文档未单列", "audio_type": "在线音频转写", "license": "Groq 服务条款 / Whisper MIT", "runtime": "GroqCloud API", "repo": "https://github.com/openai/whisper"},
        "capabilities": ["免下载", "多语言", "在线加速"],
        "benchmarks": [],
        "condition": "Groq 官方页面强调服务吞吐与延迟，但当前 metadata 没有找到与其它模型统一条件的公开准确率数值，因此不转写营销数字。",
        "resources": "需要 Groq API Key、额度和可用网络；本机不占模型显存。",
        "twobyte": {"position": "在线文字复核", "reason": "适合已有 Groq 额度、希望减少本地模型占用的多语种复核。"},
    },
    "openai_api": {
        "purpose": "通过 OpenAI 音频转写接口提供在线复核。",
        "responsibility": "在 2ByteASR 中作为可配置在线文字证据，对分块音频返回独立转写；不会替代主时间轴和说话人流程。",
        "principles": "使用 OpenAI audio/transcriptions 协议调用账户可用的转写模型。模型实现与版本由服务端管理，2ByteASR 只维护请求、结果映射和失败处理。",
        "strengths": "无需本地下载，通用多语种能力和上下文提示适合复核。",
        "limits": "依赖境外服务、账户额度、隐私策略和当前模型可用性。",
        "io": "上传音频块；返回在线转写文字。",
        "source": "OpenAI Speech-to-Text 官方文档。",
        "url": "https://platform.openai.com/docs/guides/speech-to-text",
        "official": {"developer": "OpenAI", "series": "Transcribe API（模型可配置）", "params": "服务未公开", "languages": ["多语言"], "architecture": "托管语音转写模型", "dialects": "官方未单列", "audio_type": "在线音频转写", "license": "OpenAI 服务条款", "runtime": "OpenAI API", "repo": "官方未提供服务端模型仓库"},
        "capabilities": ["免下载", "多语言", "上下文提示"],
        "benchmarks": [],
        "condition": "官方文档未提供一个与本页其它本地模型同条件、可直接比较的逐数据集数值表。",
        "resources": "需要 OpenAI API Key、账户额度与可用网络；本机不占模型显存。",
        "twobyte": {"position": "在线文字复核", "reason": "适合已有 OpenAI API 的用户增加一份通用多语种文字证据。"},
    },
    "custom_asr_api": {
        "purpose": "连接用户自备的 OpenAI 兼容音频转写服务。",
        "responsibility": "在 2ByteASR 中只承担可配置在线/自托管文字复核入口，具体能力取决于用户选择的服务和模型。",
        "principles": "按 OpenAI audio/transcriptions 兼容协议提交音频、模型名和鉴权信息；该入口没有固定模型，因此无法声明统一架构或 Benchmark。",
        "strengths": "服务商、模型名和地址均可配置，也可连接自托管服务。",
        "limits": "兼容性、准确率、隐私、费用和稳定性均由目标服务决定；需要用户自行核对。",
        "io": "上传音频块；读取兼容服务返回的转写文字。",
        "source": "用户配置的服务文档。",
        "official": {"developer": "用户配置", "series": "OpenAI 兼容 ASR", "params": "取决于模型", "languages": ["取决于模型"], "architecture": "取决于模型", "dialects": "取决于模型", "audio_type": "取决于服务", "license": "取决于服务", "runtime": "OpenAI 兼容 audio/transcriptions API", "repo": "无统一官方仓库"},
        "capabilities": ["自定义地址", "自定义模型", "在线或自托管"],
        "benchmarks": [],
        "condition": "没有固定模型或统一官方来源，无法提供可核对的公共 Benchmark；请以所配置服务的官方资料为准。",
        "resources": "需要兼容服务、模型名、URL 和密钥；硬件与网络要求取决于目标服务。",
        "twobyte": {"position": "自定义文字复核", "reason": "为已有第三方或自托管 ASR 的用户保留兼容入口，不对未知模型作统一评分承诺。"},
    },
}

_TECHNICAL_PROFILES_EN: dict[str, dict] = {
    "firered_llm": {
        "purpose": "High-accuracy primary transcription candidate for Mandarin, dialects and English.",
        "responsibility": "Advanced optional primary model; it does not replace the default MOSS / FireRed AED / Qwen workflow.",
        "principles": "An 8B+ Encoder-Adapter-LLM that connects a speech encoder to Qwen2-7B-Instruct.",
        "strengths": "Strong official Mandarin and dialect CER results with code-switching and singing support.",
        "limits": "Audio input is limited to 40 seconds, so long media still requires chunking.",
        "io": "Input: audio chunks up to 40 seconds. Output: transcript text.",
        "condition": "CER values come from the official model card; no cross-hardware speed comparison is implied.",
        "resources": "About 17.57 GiB of required files and an isolated .venv-firered-llm runtime.",
        "capabilities": ["Mandarin", "Chinese dialects", "English", "Code switching", "Singing"],
    },
    "glm_asr_nano": {
        "purpose": "Compact primary transcription candidate for Chinese, English, Cantonese and dialects.",
        "responsibility": "Runs through an isolated GLM adapter without changing the default pipeline.",
        "principles": "Officially described as a 1.5B GLM-ASR conditional-generation model.",
        "strengths": "Optimized for Cantonese, dialects and quiet or low-volume speech across 17 high-usability languages.",
        "limits": "The current official path requires Transformers source / 5.x and must stay outside the main environment.",
        "io": "Input: audio. Output: normalized transcript text.",
        "condition": "The official repository benchmark and Hugging Face OpenASR evaluation are separate sources.",
        "resources": "About 4.21 GiB of required files and an isolated .venv-glm-asr runtime.",
        "capabilities": ["Chinese", "English", "Cantonese", "Dialects", "Quiet speech"],
    },
    "canary_qwen": {
        "purpose": "High-throughput English-only primary transcription candidate.",
        "responsibility": "Runs only for supported English ASR scenarios in an isolated NVIDIA NeMo runtime.",
        "principles": "A FastConformer plus Qwen Speech-Augmented Language Model.",
        "strengths": "English ASR with punctuation and capitalization and a high official OpenASR RTFx.",
        "limits": "English only; maximum training audio duration was 40 seconds and NeMo is a heavy dependency.",
        "io": "Input: English audio chunks. Output: punctuated and capitalized English text.",
        "condition": "Reference scores apply only to supported English ASR scenarios.",
        "resources": "About 4.77 GiB of weights and an isolated .venv-canary-qwen runtime.",
        "capabilities": ["English ASR", "Punctuation", "Capitalization"],
    },
    "omni_asr_llm_7b": {
        "purpose": "Primary transcription candidate for exceptionally broad 1600+ language coverage.",
        "responsibility": "An advanced multilingual option that does not replace the default Chinese workflow.",
        "principles": "A 7,801,041,536-parameter Omnilingual ASR LLM with optional language conditioning.",
        "strengths": "Covers more than 1600 languages, including many low-resource languages.",
        "limits": "Roughly 30 GiB on disk and about 17 GiB BF16 VRAM; official speed is near real time.",
        "io": "Input: audio with optional language conditioning. Output: transcript text.",
        "condition": "Official RTF uses an A100, batch 1, 30-second audio and BF16.",
        "resources": "29.06 GiB of required HF files; official download size 30.0 GiB; isolated .venv-omni-asr runtime.",
        "capabilities": ["1600+ languages", "Language conditioning", "Low-resource languages"],
    },
    "moss": {
        "purpose": "First-pass transcription and speaker separation for long Chinese audio.",
        "strengths": "Keeps a complete semantic backbone for later timeline and text-review stages.",
        "limits": "Requires NVIDIA CUDA. Speaker labels distinguish voices; they do not identify real people.",
        "io": "Input: local audio. Output: draft transcript, segments and speaker evidence.",
        "source": "2ByteASR's bundled MOSS transcription and speaker worker.",
        "url": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        "official": {
            "developer": "OpenMOSS",
            "series": "MOSS-Transcribe-Diarize",
            "params": "0.9B (end-to-end long-form multi-speaker)",
            "languages": ["Chinese"],
            "repo": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        },
        "capabilities": ["Long audio", "Speaker separation", "Timestamp", "Event awareness"],
        "benchmarks": [
            {"metric": "CER", "value": "Reported on internal long-form multi-speaker sets per technical report Table 5", "dataset": "Internal long-form multi-speaker sets", "condition": "End-to-end joint modeling", "hardware": "Official test env", "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize"}
        ],
        "resources": "Official uniform hardware requirements not published (2ByteASR requires NVIDIA CUDA)",
        "twobyte": {
            "position": "Primary transcription",
            "reason": "Long-form Chinese + speaker separation; best first-pass backbone.",
        },
    },
    "firered": {
        "purpose": "Chinese / dialect recognition with fine-grained subtitle timing.",
        "strengths": "Improves word-boundary timing after a MOSS draft.",
        "limits": "Local use requires CUDA; timestamp quality still depends on the audio and overlapping speakers.",
        "io": "Input: audio. Output: recognized text and subtitle-ready time boundaries.",
        "source": "FireRedASR official project.",
        "url": "https://github.com/FireRedTeam/FireRedASR",
        "hf": "https://huggingface.co/FireRedTeam/FireRedASR2-AED",
        "official": {
            "developer": "FireRedTeam",
            "series": "FireRedASR / FireRedASR2-AED",
            "params": "AED",
            "languages": ["Chinese", "Dialects", "English"],
            "repo": "https://github.com/FireRedTeam/FireRedASR",
        },
        "capabilities": ["Timestamp", "Long audio", "Dialect", "Lyrics"],
        "benchmarks": [
            {"metric": "SOTA claim", "value": "New SOTA on public Mandarin ASR benchmarks", "dataset": "Public Mandarin ASR", "condition": "Official report", "hardware": "Official test env", "source": "https://github.com/FireRedTeam/FireRedASR"}
        ],
        "resources": "Official hardware requirements not uniformly published (2ByteASR uses CUDA locally)",
        "twobyte": {
            "position": "Subtitle timeline",
            "reason": "Strong timestamp capability for the timeline stage.",
        },
    },
    "qwen_local": {
        "purpose": "Multilingual text review and terminology evidence.",
        "strengths": "Offers a second local reference for named entities, multilingual clips and wording differences.",
        "limits": "Needs a large download and GPU memory; it is a review role here, not a replacement for the full workflow.",
        "io": "Input: segmented audio/text context. Output: text candidates and review evidence.",
        "source": "Qwen3-ASR official release + 2ByteASR local adapter.",
        "url": "https://github.com/QwenLM/Qwen3-ASR",
        "hf": "https://huggingface.co/Qwen/Qwen3-ASR-1.7B",
        "official": {
            "developer": "Qwen Team / Alibaba",
            "series": "Qwen3-ASR",
            "params": "1.7B",
            "languages": ["Multilingual"],
            "repo": "https://github.com/QwenLM/Qwen3-ASR",
        },
        "capabilities": ["Multilingual", "Text precision"],
        "benchmarks": [
            {"metric": "CER (replication)", "value": "Varies by set (see UltraEval-Audio replication)", "dataset": "CV / AISHELL etc.", "condition": "Third-party replication on official weights", "hardware": "Varies", "source": "https://raw.githubusercontent.com/OpenBMB/UltraEval-Audio/main/replication/qwen3_asr.md"}
        ],
        "resources": "Official hardware requirements not uniformly published (local run needs CUDA, higher VRAM)",
        "twobyte": {
            "position": "Text review",
            "reason": "Strong text accuracy and named-entity handling for the review stage.",
        },
    },
}

# Complete English copy for every production Workshop entry.  Benchmark names
# and formal metric identifiers remain unchanged; prose is localized below.
_P13_EN_COPY: dict[str, dict] = {
    "moss": {
        "purpose": "First-pass transcription and speaker separation for long-form audio.",
        "responsibility": "Builds the complete transcript, speaker labels and segment timing before the timeline and text-review stages add independent evidence.",
        "principles": "A Whisper-Medium audio encoder feeds a Qwen3-0.6B-style causal decoder through temporal merging and an MLP adaptor, jointly emitting timestamps, speaker labels, text and optional acoustic events.",
        "strengths": "Preserves long-form meaning and a stable speaker-aware backbone.",
        "limits": "Requires NVIDIA CUDA. Speaker labels distinguish voices but do not identify real names.",
        "io": "Input: local audio. Output: draft text, segments and speaker evidence.",
        "condition": "Official accuracy tables cover long-form multi-speaker sets; the published SGLang Omni speed result uses one H100.",
        "resources": "The official project recommends Python 3.12 and Transformers 5.x. 2ByteASR uses its existing isolated MOSS environment.",
        "capabilities": ["Long audio", "Speaker separation", "Timestamps", "Acoustic events"],
    },
    "firered": {
        "purpose": "Chinese and dialect recognition with fine-grained subtitle timing.",
        "responsibility": "Adds independent text, word timestamps and confidence after the MOSS backbone, primarily for second-stage subtitle boundaries.",
        "principles": "FireRedASR2-AED uses an attention-based encoder-decoder and can return word-level timestamps and confidence in one model.",
        "strengths": "Strong word-boundary evidence for the timeline stage.",
        "limits": "Local use requires CUDA; overlap and source audio quality still affect timestamps.",
        "io": "Input: audio. Output: recognized text and subtitle-ready boundaries.",
        "condition": "Official accuracy evaluation covers 24 public sets. The 12.7x TensorRT figure uses AISHELL-1 on one H20 and is not mixed with accuracy metrics.",
        "resources": "Official support targets Ubuntu 22.04. AED segments should stay below the documented duration limit; 2ByteASR keeps its existing chunking path.",
        "capabilities": ["Word timestamps", "Long audio", "Dialects", "Lyrics"],
    },
    "qwen_local": {
        "purpose": "Multilingual text review and terminology evidence.",
        "responsibility": "Produces an independent transcript for the same audio to reveal wording, named-entity and mixed-language differences without replacing speaker identity or the timeline.",
        "principles": "Qwen3-ASR is a unified streaming/offline autoregressive recognizer derived from Qwen3-Omni; timestamps are handled by the separate forced aligner.",
        "strengths": "Strong independent evidence for names and multilingual passages.",
        "limits": "Requires a substantial download and GPU memory; it remains a review stage in this workflow.",
        "io": "Input: segmented audio and optional text context. Output: text candidates and review evidence.",
        "condition": "Official evaluation uses vLLM, bfloat16, greedy decoding and no explicit language parameter.",
        "resources": "The official project recommends an isolated Python 3.12 environment and FlashAttention 2 where available.",
        "capabilities": ["30 languages", "22 Chinese dialects", "Language ID", "Streaming/offline", "Long audio", "Singing"],
    },
    "sensevoice": {
        "purpose": "Lightweight multilingual recognition and text review.",
        "responsibility": "Provides a low-resource second transcript for Chinese, Cantonese, English, Japanese and Korean; the checkpoint itself does not perform speaker separation.",
        "principles": "A non-autoregressive model emits transcription, language, emotion and audio-event labels in one pass; FunASR VAD handles long audio separately.",
        "strengths": "CPU-capable and especially practical for Chinese and Cantonese.",
        "limits": "Does not provide the MOSS multi-speaker backbone.",
        "io": "Input: audio. Output: multilingual text with optional emotion and event labels.",
        "condition": "The official README publishes the detailed accuracy table as an image; this page only uses directly verifiable text values.",
        "resources": "Supports CUDA, ONNX, libtorch and llama.cpp/GGUF CPU paths. Speaker labels require separate VAD and CAM++ models.",
        "capabilities": ["Five languages", "Language ID", "Emotion", "Audio events"],
    },
    "paraformer": {
        "purpose": "Chinese long-audio recognition and a lightweight timeline backend.",
        "responsibility": "Provides optional Chinese text and timestamps after the MOSS draft; it does not replace the multi-speaker backbone.",
        "principles": "A non-autoregressive encoder, predictor and decoder generate text in parallel; FunASR composes VAD, punctuation and hot words for long audio.",
        "strengths": "Fast non-autoregressive inference with hot-word support.",
        "limits": "The installed checkpoint is Chinese-specific, not the multilingual Paraformer family.",
        "io": "Input: audio and optional hot words. Output: Chinese text and timing evidence.",
        "condition": "Values come from the official Paraformer Large model card; VAD, punctuation and hot-word settings can change real results.",
        "resources": "Official CPU, CUDA and ONNX paths are available; 2ByteASR keeps its existing isolated FunASR environment.",
        "capabilities": ["Chinese", "Hot words", "Timestamps", "Long audio"],
    },
    "whisper": {
        "purpose": "General multilingual transcription and review.",
        "responsibility": "Adds multilingual text or timing evidence for non-Chinese and mixed-language clips without speaker separation.",
        "principles": "An encoder-decoder Transformer predicts language, transcription or translation and timestamp tokens from log-Mel audio features.",
        "strengths": "Broad language coverage and mature runtime support.",
        "limits": "No MOSS-style speaker separation; speed varies substantially by hardware and runtime.",
        "io": "Input: audio. Output: text and segment-level timing.",
        "condition": "The turbo model card does not provide one directly comparable per-dataset table for the models on this page.",
        "resources": "The official card lists about 6 GB relative VRAM; actual local speed depends on runtime and audio length.",
        "capabilities": ["Multilingual", "Timestamps", "Language ID"],
    },
    "qwen_aligner": {
        "purpose": "Character and word timing from existing text.",
        "responsibility": "Can replace the timeline backend by aligning confirmed text to audio without deciding the transcript again.",
        "principles": "A non-autoregressive forced aligner reads audio and supplied text and predicts character or word positions.",
        "strengths": "Preserves trusted text while generating multilingual fine timing.",
        "limits": "Requires reliable input text; omissions, overlap and noise directly affect alignment.",
        "io": "Input: audio plus existing text. Output: character or word boundaries.",
        "condition": "AAS is average alignment deviation in milliseconds and does not represent transcription accuracy.",
        "resources": "The official qwen-asr path uses CUDA and should run after a reliable transcript is available.",
        "capabilities": ["Character alignment", "Word alignment", "11 languages", "Text preservation"],
    },
    "funasr_nano": {
        "purpose": "Local review for Chinese dialects, English and Japanese.",
        "responsibility": "Provides independent text evidence for Chinese dialects, regional accents, English and Japanese; it does not create the multi-speaker backbone.",
        "principles": "An audio encoder connects to a language model for end-to-end transcription with optional context and hot-word enhancement.",
        "strengths": "Strong checkpoint-specific Chinese dialect coverage plus lyrics and rap recognition.",
        "limits": "The installed Nano checkpoint is not the separate 31-language MLT-Nano checkpoint and has no native speaker separation.",
        "io": "Input: audio and optional context. Output: Chinese, English, Japanese and dialect text.",
        "condition": "Official public-set values apply to Fun-ASR-Nano-2512; runtime and batching are not uniform with other models here.",
        "resources": "Requires an isolated FunASR environment; local GPU memory depends on runtime and batching.",
        "capabilities": ["Chinese", "English", "Japanese", "7 dialects", "26 accents", "Lyrics and rap"],
    },
    "qwen_api": {
        "purpose": "Hosted transcription without a local model download.",
        "responsibility": "Provides an optional online transcription or review source through DashScope.",
        "principles": "Audio is sent to the configured hosted ASR API; the server-side model can change independently of this application.",
        "strengths": "Fast setup and no local model storage.",
        "limits": "Requires network access, a key, quota and acceptance of the provider's data policy.",
        "io": "Input: uploaded audio. Output: hosted transcription text.",
        "condition": "No fixed public benchmark is directly comparable with the local checkpoints on this page.",
        "resources": "Requires a DashScope key, quota and network access.",
        "capabilities": ["No download", "Hosted ASR"],
    },
    "groq_api": {
        "purpose": "Hosted Whisper transcription through GroqCloud.",
        "responsibility": "Provides an optional fast online text-review source.",
        "principles": "Uses the OpenAI-compatible transcription protocol with a Groq-hosted Whisper checkpoint.",
        "strengths": "Low local resource use and fast hosted inference.",
        "limits": "Requires network access, a Groq key and available quota.",
        "io": "Input: uploaded audio blocks. Output: hosted transcript text.",
        "condition": "Provider speed claims are not a same-device benchmark against local 2ByteASR models.",
        "resources": "Requires a Groq API key, quota and reachable service.",
        "capabilities": ["No download", "Multilingual", "Hosted Whisper"],
    },
    "openai_api": {
        "purpose": "Configurable OpenAI speech-to-text review source.",
        "responsibility": "Adds an optional independent hosted transcript for users with an OpenAI account.",
        "principles": "Uploads audio through the official speech-to-text API using the selected hosted model.",
        "strengths": "General hosted transcription with context support where the selected model provides it.",
        "limits": "Model capability, pricing and availability depend on the configured service model.",
        "io": "Input: uploaded audio blocks. Output: hosted transcript text.",
        "condition": "No fixed model and same-condition public table is available for comparison here.",
        "resources": "Requires an OpenAI API key, quota and network access.",
        "capabilities": ["No download", "Configurable model", "Context prompt"],
    },
    "custom_asr_api": {
        "purpose": "Connect a user-provided OpenAI-compatible transcription service.",
        "responsibility": "Acts only as a configurable online or self-hosted review endpoint.",
        "principles": "Submits audio, model name and authentication through the compatible audio/transcriptions protocol.",
        "strengths": "Provider, endpoint and model name are user controlled.",
        "limits": "Accuracy, privacy, price and reliability all depend on the configured service.",
        "io": "Input: uploaded audio. Output: compatible service response.",
        "condition": "There is no fixed checkpoint or unified official benchmark.",
        "resources": "Requires a compatible endpoint, model name and key; hardware and networking are service dependent.",
        "capabilities": ["Custom endpoint", "Custom model", "Online or self-hosted"],
    },
}


_LOCAL_BENCHMARK_TEMPLATE = {
    "status": "not_run",
    "gpu": "",
    "cpu": "",
    "runtime": "",
    "audio_length_seconds": None,
    "inference_seconds": None,
    "realtime_factor": None,
}


# Checkpoint-specific language audit.  These records intentionally separate
# an official summary from a complete enumeration so the UI never expands a
# family-level claim into capabilities that were not published for the actual
# model used by 2ByteASR.
_LANGUAGE_AUDIT: dict[str, dict] = {
    "firered_llm": {
        "zh": ("中文 / English · 20+ 方言口音", ["中文（普通话）", "English"], "20+ 中文方言/口音", "支持中英混说", "支持语音与歌唱"),
        "en": ("Chinese / English · 20+ dialects and accents", ["Chinese (Mandarin)", "English"], "20+ Chinese dialects and accents", "Chinese-English code switching", "Speech and singing"),
        "source": "https://huggingface.co/FireRedTeam/FireRedASR2-LLM",
        "fully_enumerated": False,
    },
    "glm_asr_nano": {
        "zh": ("17 种高可用语言", ["中文", "English", "粤语", "其它官方支持语言"], "粤语与其它方言优化", "官方未单列", "官方未单列"),
        "en": ("17 high-usability languages", ["Chinese", "English", "Cantonese", "Other officially supported languages"], "Optimized for Cantonese and other dialects", "Not stated", "Not stated"),
        "source": "https://huggingface.co/zai-org/GLM-ASR-Nano-2512",
        "fully_enumerated": False,
    },
    "canary_qwen": {
        "zh": ("English", ["English"], "官方未单列", "不支持多语言场景", "官方未单列"),
        "en": ("English", ["English"], "Not separately listed", "Not intended for multilingual use", "Not stated"),
        "source": "https://huggingface.co/nvidia/canary-qwen-2.5b",
        "fully_enumerated": True,
    },
    "omni_asr_llm_7b": {
        "zh": ("1600+ 语言", ["完整语言 ID 由官方运行库提供"], "随语言覆盖；官方未单列统一方言数", "可选语言条件", "官方未单列"),
        "en": ("1600+ languages", ["The complete language ID list is provided by the official runtime"], "Covered within the language inventory; no unified dialect count", "Optional language conditioning", "Not stated"),
        "source": "https://huggingface.co/facebook/omniASR-LLM-7B",
        "fully_enumerated": False,
    },
    "moss": {
        "zh": ("50+ 语言", ["官方仅公布 50+ 语言摘要"], "官方未逐项公开完整语言或方言清单", "官方未单列", "官方未单列"),
        "en": ("50+ languages", ["Official 50+ language summary"], "The official project does not enumerate the full language or dialect list", "Not stated", "Not stated"),
        "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize",
        "fully_enumerated": False,
    },
    "firered": {
        "zh": ("中文 / English · 20+ 方言口音", ["中文（普通话）", "English"], "20+ 中文方言/口音；官方列举粤语、四川、上海、吴语、闽南等", "支持中英混说", "支持语音与歌唱转写"),
        "en": ("Chinese / English · 20+ dialects & accents", ["Chinese (Mandarin)", "English"], "20+ Chinese dialects and accents; official examples include Cantonese, Sichuan, Shanghai, Wu and Minnan", "Chinese-English code-switching supported", "Speech and singing transcription supported"),
        "source": "https://github.com/FireRedTeam/FireRedASR2S",
        "fully_enumerated": False,
    },
    "qwen_local": {
        "zh": ("30 种语言 · 22 种中文方言", ["中文", "English", "粤语", "阿拉伯语", "德语", "法语", "西班牙语", "葡萄牙语", "印尼语", "意大利语", "韩语", "俄语", "泰语", "越南语", "日语", "土耳其语", "印地语", "马来语", "荷兰语", "瑞典语", "丹麦语", "芬兰语", "波兰语", "捷克语", "菲律宾语", "波斯语", "希腊语", "匈牙利语", "马其顿语", "罗马尼亚语"], "22 种中文方言/口音，官方 README 已逐项列出", "官方未单独声明 code-switching 范围", "支持歌唱与带 BGM 歌曲"),
        "en": ("30 languages · 22 Chinese dialects", ["Chinese", "English", "Cantonese", "Arabic", "German", "French", "Spanish", "Portuguese", "Indonesian", "Italian", "Korean", "Russian", "Thai", "Vietnamese", "Japanese", "Turkish", "Hindi", "Malay", "Dutch", "Swedish", "Danish", "Finnish", "Polish", "Czech", "Filipino", "Persian", "Greek", "Hungarian", "Macedonian", "Romanian"], "22 Chinese dialects and accents, fully listed in the official README", "Code-switching scope is not stated separately", "Singing voice and songs with BGM supported"),
        "source": "https://github.com/QwenLM/Qwen3-ASR",
        "fully_enumerated": True,
    },
    "sensevoice": {
        "zh": ("中 / 粤 / 英 / 日 / 韩", ["中文", "粤语", "English", "日本語", "한국어"], "粤语；该 checkpoint 未单列其它中文方言", "官方未单列", "官方未单列"),
        "en": ("Chinese / Cantonese / English / Japanese / Korean", ["Chinese", "Cantonese", "English", "Japanese", "Korean"], "Cantonese; no other Chinese dialects are listed for this checkpoint", "Not stated", "Not stated"),
        "source": "https://github.com/QwenAudio/SenseVoice",
        "fully_enumerated": True,
    },
    "paraformer": {
        "zh": ("中文", ["中文"], "官方模型卡未单列方言覆盖", "官方未单列", "官方未单列"),
        "en": ("Chinese", ["Chinese"], "The official model card does not list dialect coverage", "Not stated", "Not stated"),
        "source": "https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary",
        "fully_enumerated": True,
    },
    "whisper": {
        "zh": ("多语言（99 种语言训练覆盖）", ["官方 tokenizer 列出的多语言集合"], "官方未提供独立方言清单", "官方未单列", "官方未将歌唱列为独立能力"),
        "en": ("Multilingual (trained on 99 languages)", ["Official tokenizer language set"], "No separate official dialect list", "Not stated", "Singing is not listed as a separate capability"),
        "source": "https://github.com/openai/whisper",
        "fully_enumerated": False,
    },
    "qwen_aligner": {
        "zh": ("11 种语言", ["中文", "English", "粤语", "法语", "德语", "意大利语", "日语", "韩语", "葡萄牙语", "俄语", "西班牙语"], "官方未单列方言；对齐输入必须已有文字", "官方未单列", "仅声明 Speech"),
        "en": ("11 languages", ["Chinese", "English", "Cantonese", "French", "German", "Italian", "Japanese", "Korean", "Portuguese", "Russian", "Spanish"], "No dialect list; alignment requires existing text", "Not stated", "Speech only"),
        "source": "https://github.com/QwenLM/Qwen3-ASR",
        "fully_enumerated": True,
    },
    "funasr_nano": {
        "zh": ("中 / 英 / 日 · 7 方言 · 26 地域口音", ["中文", "English", "日本語"], "吴、粤、闽、客家、赣、湘、晋 7 大方言；26 种地域口音", "官方未单列", "支持歌词与说唱识别"),
        "en": ("Chinese / English / Japanese · 7 dialects · 26 accents", ["Chinese", "English", "Japanese"], "Wu, Cantonese, Min, Hakka, Gan, Xiang and Jin; 26 regional accents", "Not stated", "Lyrics and rap recognition supported"),
        "source": "https://github.com/QwenAudio/Fun-ASR",
        "fully_enumerated": True,
    },
    "qwen_api": {
        "zh": ("以当前 DashScope 模型文档为准", ["服务端模型可变"], "以当前服务文档为准", "以当前服务文档为准", "以当前服务文档为准"),
        "en": ("See the current DashScope model documentation", ["Hosted model may change"], "See current service documentation", "See current service documentation", "See current service documentation"),
        "source": "https://help.aliyun.com/zh/model-studio/qwen-audio",
        "fully_enumerated": False,
    },
    "groq_api": {
        "zh": ("Whisper 多语言", ["取决于 Groq 当前托管的 Whisper checkpoint"], "服务文档未单列", "官方未单列", "官方未单列"),
        "en": ("Whisper multilingual", ["Depends on the Whisper checkpoint currently hosted by Groq"], "Not listed by the service", "Not stated", "Not stated"),
        "source": "https://console.groq.com/docs/speech-to-text",
        "fully_enumerated": False,
    },
    "openai_api": {
        "zh": ("取决于所选 OpenAI 转写模型", ["服务端模型可配置"], "以当前模型文档为准", "以当前模型文档为准", "以当前模型文档为准"),
        "en": ("Depends on the selected OpenAI transcription model", ["Hosted model is configurable"], "See current model documentation", "See current model documentation", "See current model documentation"),
        "source": "https://platform.openai.com/docs/guides/speech-to-text",
        "fully_enumerated": False,
    },
    "custom_asr_api": {
        "zh": ("取决于用户配置的模型", ["无固定 checkpoint"], "取决于模型", "取决于模型", "取决于模型"),
        "en": ("Depends on the user-configured model", ["No fixed checkpoint"], "Model dependent", "Model dependent", "Model dependent"),
        "source": "用户配置 / User configured",
        "source_en": "User configured",
        "fully_enumerated": False,
    },
}


def _normalized_profile(profile: dict, key: str = "", language: str = "zh") -> dict:
    """Return UI metadata with stable evidence and local benchmark fields."""
    result = deepcopy(profile)
    for item in result.get("benchmarks", []):
        item.setdefault("runtime", "官方未声明")
        item.setdefault("batch_concurrency", "官方未声明")
        item.setdefault("source_url", item.get("source", ""))
        item.setdefault("source_version", item.get("source_updated", "官方页面当前版本"))
        item.setdefault("comparison_group", "")
    audit = _LANGUAGE_AUDIT.get(key)
    if audit:
        summary, languages, dialects, code_switching, singing_support = audit.get(
            "en" if language == "en" else "zh"
        )
        official = result.setdefault("official", {})
        official.update({
            "language_summary": summary,
            "languages": list(languages),
            "dialects": dialects,
            "code_switching": code_switching,
            "singing_support": singing_support,
            "language_source": audit.get("source_en", audit["source"]) if language == "en" else audit["source"],
            "languages_fully_enumerated": bool(audit["fully_enumerated"]),
        })
    result.setdefault("local_benchmark", deepcopy(_LOCAL_BENCHMARK_TEMPLATE))
    return result


def get_profile(key: str, language: str = "zh") -> dict:
    profile = _normalized_profile(_TECHNICAL_PROFILES.get(key, {}), key, language)
    if language != "en":
        return _localized_profile_copy(profile, language)

    # Localized prose must not reintroduce stale third-party benchmark data.
    localized = deepcopy(_TECHNICAL_PROFILES_EN.get(key, {}))
    localized.update(deepcopy(_P13_EN_COPY.get(key, {})))
    for field in ("benchmarks", "url", "hf", "paper", "modelscope"):
        if field in profile:
            localized[field] = deepcopy(profile[field])
    official = deepcopy(profile.get("official", {}))
    official.update({
        "developer": {
            "qwen_api": "Alibaba Cloud / Qwen",
            "groq_api": "Groq (hosting) / OpenAI (model)",
            "custom_asr_api": "User configured",
        }.get(key, official.get("developer", "")),
        "series": {
            "openai_api": "Transcription API (configurable model)",
            "custom_asr_api": "OpenAI-compatible ASR",
        }.get(key, official.get("series", "")),
        "params": {
            "moss": "0.9B (end-to-end long-form multi-speaker)",
            "firered": "Not separately published for the AED checkpoint",
            "qwen_local": "1.7B", "sensevoice": "Approx. 234M",
            "paraformer": "Approx. 220M", "whisper": "809M",
            "qwen_aligner": "0.6B", "funasr_nano": "0.8B",
            "qwen_api": "Not published for the hosted service",
            "groq_api": "809M model", "openai_api": "Not public for the hosted service",
            "custom_asr_api": "Model dependent",
            "firered_llm": "8B+",
            "glm_asr_nano": "1.5B official description; 2,257,843,200 in HF safetensors metadata",
            "canary_qwen": "2.5B",
            "omni_asr_llm_7b": "7,801,041,536",
        }.get(key, official.get("params", "")),
        "architecture": {
            "moss": "Whisper-Medium encoder + Qwen3-0.6B-style causal decoder",
            "firered": "Attention-based Encoder-Decoder (AED)",
            "qwen_local": "Qwen3-Omni-derived autoregressive ASR",
            "sensevoice": "Non-autoregressive end-to-end audio understanding",
            "paraformer": "Paraformer non-autoregressive end-to-end ASR",
            "whisper": "Encoder-decoder Transformer",
            "qwen_aligner": "Non-autoregressive forced alignment",
            "funasr_nano": "Audio encoder + LLM end-to-end ASR",
            "qwen_api": "Hosted ASR service; server architecture is not public",
            "groq_api": "Hosted Whisper encoder-decoder Transformer",
            "openai_api": "Hosted transcription model",
            "custom_asr_api": "Model dependent",
            "firered_llm": "Encoder-Adapter-LLM with Qwen2-7B-Instruct",
            "glm_asr_nano": "GLM-ASR conditional generation",
            "canary_qwen": "FastConformer plus Qwen Speech-Augmented Language Model",
            "omni_asr_llm_7b": "Omnilingual wav2vec2 plus LLM ASR",
        }.get(key, official.get("architecture", "")),
        "audio_type": {
            "moss": "Long-form, multi-speaker meetings, podcasts and video",
            "firered": "Speech, singing and lyrics",
            "qwen_local": "Speech, singing voice and songs with BGM",
            "sensevoice": "Speech with optional emotion and event labels",
            "paraformer": "16 kHz Chinese speech; VAD handles long audio",
            "whisper": "General speech in 30-second windows",
            "qwen_aligner": "Speech plus known transcript text",
            "funasr_nano": "Speech and long-audio chunks",
            "qwen_api": "Hosted audio transcription",
            "groq_api": "Hosted audio transcription",
            "openai_api": "Hosted audio transcription",
            "custom_asr_api": "Service dependent",
            "firered_llm": "Speech, singing and Chinese-English code switching",
            "glm_asr_nano": "Speech including quiet and low-volume speech",
            "canary_qwen": "English speech; maximum training duration 40 seconds",
            "omni_asr_llm_7b": "Speech with optional language conditioning",
        }.get(key, official.get("audio_type", "")),
        "license": {
            "moss": "Apache-2.0", "firered": "Apache-2.0",
            "qwen_local": "Apache-2.0",
            "sensevoice": "MIT code; FunASR model license for weights",
            "paraformer": "Apache-2.0 as listed on the model card",
            "whisper": "MIT", "qwen_aligner": "Apache-2.0",
            "funasr_nano": "See the official checkpoint model card",
            "qwen_api": "Alibaba Cloud service terms",
            "groq_api": "Groq service terms / Whisper MIT",
            "openai_api": "OpenAI service terms",
            "custom_asr_api": "Service dependent",
        }.get(key, official.get("license", "")),
        "runtime": {
            "custom_asr_api": "OpenAI-compatible audio/transcriptions API",
            "firered_llm": "FireRedASR2S / PyTorch",
            "glm_asr_nano": "Transformers 5.x / planned SGLang support",
            "canary_qwen": "NVIDIA NeMo 2.5+",
            "omni_asr_llm_7b": "omnilingual-asr / fairseq2",
        }.get(key, official.get("runtime", "")),
        "repo": {
            "qwen_api": "No separate open-source repository",
            "openai_api": "No repository for the hosted server model",
            "custom_asr_api": "No single official repository",
        }.get(key, official.get("repo", "")),
    })
    localized["official"] = official
    for benchmark in localized.get("benchmarks", []):
        metric = str(benchmark.get("metric") or "")
        if metric == "相对推理速度":
            benchmark["metric"] = "Relative inference speed"
        elif metric == "推理延迟":
            benchmark["metric"] = "Inference latency"
        dataset = str(benchmark.get("dataset") or "")
        for zh, en in (
            ("HF OpenASR 榜单 8 集均值（英语）", "HF OpenASR leaderboard mean, 8 sets (English)"),
            ("HF OpenASR 榜单（英语）", "HF OpenASR leaderboard (English)"),
            ("官方卡 indexing 结果", "Official model card indexing results"),
            ("10 秒音频端到端延迟", "10-second audio end-to-end latency"),
            ("Qwen3-ASR 官方表复测）", "Qwen3-ASR table retest)"),
            ("（OpenASR）", " (OpenASR)"),
            ("KeSpeech（方言）", "KeSpeech (dialects)"),
            ("Fleurs-yue（粤语）", "Fleurs-yue (Cantonese)"),
            ("Mandarin 4 集平均", "Mandarin, 4-set average"),
            ("中文方言/口音 19 集平均", "Chinese dialects/accents, 19-set average"),
            ("MLS（8 语种）", "MLS (8 languages)"),
            ("CommonVoice（13 语种）", "CommonVoice (13 languages)"),
            ("官方 inference benchmark", "Official inference benchmark"),
            ("MFA Raw 中文", "MFA Raw Chinese"),
            ("MFA Raw 英文", "MFA Raw English"),
        ):
            dataset = dataset.replace(zh, en)
        # 残余全角括号归一为半角，保证英文页无中文字符。
        dataset = dataset.replace("（", " (").replace("）", ")")
        benchmark["dataset"] = dataset
        benchmark["condition"] = "Official checkpoint evaluation; see the source for the exact setup."
        hardware = str(benchmark.get("hardware") or "")
        if "H100" in hardware:
            benchmark["hardware"] = "One NVIDIA H100"
        elif "H20" in hardware:
            benchmark["hardware"] = "One NVIDIA H20"
        elif hardware:
            benchmark["hardware"] = "Not stated in directly comparable form"
        direction = str(benchmark.get("direction") or "")
        benchmark["direction"] = "Higher is better" if "高" in direction else "Lower is better"
        benchmark["source_updated"] = "Official source reviewed 2026-09-18"
        benchmark["source_version"] = "Official source reviewed 2026-09-18"
        benchmark["runtime"] = (
            str(benchmark.get("runtime"))
            if not any("\u4e00" <= char <= "\u9fff" for char in str(benchmark.get("runtime")))
            else "See official source"
        )
        benchmark["batch_concurrency"] = (
            str(benchmark.get("batch_concurrency"))
            if not any("\u4e00" <= char <= "\u9fff" for char in str(benchmark.get("batch_concurrency")))
            else "See official source"
        )
    localized["twobyte"] = deepcopy(profile.get("twobyte", {}))
    if key in {"firered_llm", "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b"}:
        localized["twobyte"] = {
            "position": "Advanced primary transcription candidate",
            "reason": "Card scores are same-group relative indices from audited comparison tables; missing groups stay unscored.",
        }
    if key in _P13_EN_COPY:
        localized["twobyte"] = {
            "position": {
                "moss": "Primary transcription", "firered": "Subtitle timeline",
                "qwen_local": "Text review", "sensevoice": "Text review",
                "paraformer": "Subtitle timeline", "whisper": "Text review",
                "qwen_aligner": "Subtitle timeline", "funasr_nano": "Text review",
                "qwen_api": "Online review", "groq_api": "Online review",
                "openai_api": "Online review", "custom_asr_api": "Custom review",
            }.get(key, "Workflow option"),
            "reason": str(_P13_EN_COPY[key].get("strengths", "Workflow selection for 2ByteASR.")),
        }
    localized["local_benchmark"] = deepcopy(profile["local_benchmark"])
    if key == "custom_asr_api":
        localized["official"]["language_source"] = "User configured"
    return _localized_profile_copy(_normalized_profile(localized or profile, key, language), language)


def _localized_profile_copy(value, language):
    """Translate built-in presentation values only, preserving keys and numbers."""
    from .i18n import translate
    if isinstance(value, str):
        return translate(value, language)
    if isinstance(value, dict):
        return {key: _localized_profile_copy(item, language) for key, item in value.items()}
    if isinstance(value, list):
        return [_localized_profile_copy(item, language) for item in value]
    if isinstance(value, tuple):
        return tuple(_localized_profile_copy(item, language) for item in value)
    return value
