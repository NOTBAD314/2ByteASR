"""Product task semantics; independent of Qt, installation health and scores.

Capability evidence lives in model_evaluation_metadata; benchmark values stay
in model_benchmarks. Pipeline roles (e.g. review) are not model task types.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTask:
    model_type: str
    label: str
    primary_metric: str
    input: str
    operation: str
    output: str
    requires_text: bool = False
    standalone_asr: bool = False
    metric_scope: str = ""


TASKS = {
    "asr": ModelTask("asr", "语音转写", "转写准确度", "音频", "语音识别", "字幕文本",
                     standalone_asr=True),
    "forced_aligner": ModelTask("forced_aligner", "时间对齐", "对齐精度", "音频 + 已有文本",
                                "时间对齐", "字 / 词级时间位置", requires_text=True, metric_scope="align"),
    "diarization": ModelTask("diarization", "说话人", "说话人区分", "音频", "说话人分析", "说话人片段"),
    "text_review": ModelTask("text_review", "文本复核", "文本复核能力", "已有文本", "文本复核", "修订文本",
                             requires_text=True),
    "translation": ModelTask("translation", "翻译", "翻译质量", "已有文本", "翻译", "译文",
                             requires_text=True),
    "other": ModelTask("other", "辅助模型", "任务参考", "见技术说明", "辅助处理", "见技术说明"),
}


def task_for(capabilities: tuple[str, ...], model_type: str = "") -> ModelTask:
    if model_type:
        return TASKS.get(model_type, TASKS["other"])
    for capability, task in (("ASR_TEXT", "asr"), ("ALIGNMENT", "forced_aligner"),
                             ("DIARIZATION", "diarization"), ("TEXT_REVIEW", "text_review"),
                             ("TRANSLATION", "translation")):
        if capability in capabilities:
            return TASKS[task]
    return TASKS["other"]


@dataclass(frozen=True)
class ModelCopy:
    summary: str
    best_for: str = ""
    limitations: str = ""
    workflow_note: str = ""
    advantages: tuple[str, ...] = ()


MODEL_COPY = {
    "moss": ModelCopy("多人语音转写 + 说话人区分，适合直播和多人录音。", "长音频、直播和多人录音",
                      "说话人标签不等于真实姓名", "先生成文字骨架、分段和说话人证据。"),
    "firered": ModelCopy("中文 / 方言高精度转写，并支持细粒度时间轴。", "中文、方言及需要细粒度时间戳的字幕",
                         workflow_note="既可独立转写，也可在组合流程中提供字级时间轴。", advantages=("字级时间轴",)),
    "qwen_local": ModelCopy("多语言高精度转写，适合通用字幕识别。", "通用字幕、多语言和专名复核",
                            workflow_note="可独立转写；复核阶段重新听音频，提供独立文字证据。"),
    "firered_llm": ModelCopy("高精度中文 / 方言转写，质量优先但资源占用更高。", "中文和方言的质量优先转写"),
    "glm_asr_nano": ModelCopy("中文、粤语及英语转写，适合低音量语音素材。", "中文、粤语和低音量语音"),
    "canary_qwen": ModelCopy("英语高吞吐转写，适合批量处理英语素材。", "英语素材批量转写", "不支持中文",
                             advantages=("高吞吐", "不支持中文")),
    "omni_asr_llm_7b": ModelCopy("超多语言覆盖，适合小语种和跨语言素材。", "小语种及跨语言素材",
                                 "上游 fairseq2 不支持原生 Windows；当前仅可下载权重", advantages=("7B", "Windows 仅权重")),
    "sensevoice": ModelCopy("轻量多语言转写，低配置设备也能使用。", "低配置设备上的常见语言转写",
                            advantages=("CPU 可用",)),
    "paraformer": ModelCopy("中文快速转写，并支持时间轴。", "中文快速转写和热词识别"),
    "whisper": ModelCopy("多语言通用转写，适合多种语言的视频字幕。"),
    "funasr_nano": ModelCopy("中文方言与多语言转写，可提供独立文字复核证据。"),
    "qwen_aligner": ModelCopy("已有字幕的高精度字词时间轴对齐。", "ASR 转写与纠错后的最终时间轴精修",
                              "不能独立转写，也不负责识别或纠正字幕内容", "先由 ASR 得到文字，再根据音频定位字词。"),
    "ja_ctc_aligner": ModelCopy("日语字幕句首的第二路对齐证据，与 Qwen 对齐器一致时才校正句首。", "日语字幕的句首时间",
                                "只用于日语句首，不改文字与句尾；对带配乐的对白识别能力弱",
                                "Qwen 对齐器测出字词时间后，再用它核对每句的起点。"),
    "mlx_qwen3_asr_0_6b": ModelCopy("Apple Silicon Mac 本地转写，不需要 NVIDIA 显卡。", "M 系列芯片 Mac 上的离线字幕",
                                    "只按语音段给文字，不给字词时间，不区分说话人", "要字词时间时，再用 MLX 对齐模型补时间。"),
    "mlx_qwen3_asr_1_7b": ModelCopy("Apple Silicon Mac 本地转写（更大更准，更慢）。", "M 系列芯片 Mac 上的离线字幕",
                                    "只按语音段给文字，不给字词时间，不区分说话人", "要字词时间时，再用 MLX 对齐模型补时间。"),
    "mlx_qwen_aligner": ModelCopy("在 Apple Silicon Mac 上给已有字幕配字词时间。", "云端或本地识别后的时间轴精修",
                                  "不是语音识别模型：不能把语音转成文字", "先由识别得到文字，再在本机定位每个字词。"),
    "qwen_api": ModelCopy("云端多语言转写，适合免安装的字幕识别。"),
    "qwen_audio_asr_flash": ModelCopy("云端语音转写，适合中文素材快速识别与复核。"),
    "groq_api": ModelCopy("云端加速转写，适合多语言字幕与短块复核。"),
    "openai_api": ModelCopy("通用云端语音转写，适合多语言字幕识别。"),
    "mai_transcribe_2_word": ModelCopy("云端转写并提供字级时间戳，适合细化字幕时间轴。"),
    "qwen_audio_filetrans": ModelCopy("录音文件转写，提供词级时间戳与说话人信息。"),
    "custom_asr_api": ModelCopy("连接自备语音转写服务，能力取决于配置型号。"),
}

COMPARISON_NOTE = "评分仅在同类任务模型中用于相对比较；不同任务的 100 分不能横向比较，也不是正确率百分比。"
SPEED_NOTE = "速度指数越高越快，100 为参考目录最快档。公开数据的硬件与服务条件不同，实际速度以本机或当前服务为准。"
SIZE_NOTE = "安装大小仅代表本地文件占用，不等同于模型能力或准确率。大小受参数量、权重精度、运行库和附属文件影响。"
