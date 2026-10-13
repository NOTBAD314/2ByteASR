# 申请与设置 API：教程目录

最后核对：2026-10-14。这些教程与程序里「申请与设置 API」对话框“详细说明与教程”里显示的是同一份文字（打包时一起带上）。每篇都写了：它在兔白里做什么、官方链接、从零申请的步骤、要不要开通服务 / 充值 / 额外存储、兔白里每一栏填什么、哪些已预填、测试成功时看到什么、常见失败与下一步。需要登录才能看到的页面标为“待核实”，不编按钮名称。

## 先选哪一个（语音识别，会上传音频）

| 你的情况 | 建议 | 教程 |
| --- | --- | --- |
| 没有显卡，**只想填一把 Key** 就开始 | MOSS-Transcribe-Diarize Pro 云端（MOSI）：直接上传本地音频，有说话人；只有句段时间（要逐字时间再装本地对齐模型） | [教程](mosi-moss-pro.zh-CN.md) |
| 需要字/词级时间，愿意设置一次 OSS 私有存储 | 阿里云百炼 · 录音文件识别（中国站）或 Qwen Cloud（国际站，新加坡） | [百炼](bailian-filetrans.zh-CN.md)、[Qwen Cloud](qwen-cloud-filetrans.zh-CN.md) |
| 已有讯飞 / Groq / OpenAI 账号 | 讯飞 Spark-ASR 2.0（每约 55 秒一段文字）、Groq Whisper（句段时间）、OpenAI（默认模型不回时间戳） | [讯飞](iflytek-spark.zh-CN.md)、[Groq](groq.zh-CN.md)、[OpenAI](openai-transcribe.zh-CN.md) |
| 进阶：OpenRouter、Azure OpenAI 部署、自定义兼容接口 | 需要自己判断模型与部署；兔白未用真实密钥实测 | [OpenRouter](openrouter.zh-CN.md)、[Azure](azure.zh-CN.md)、[自定义](custom-asr.zh-CN.md) |

百炼和 Qwen Cloud 的录音文件识别只接受“服务商能读到的音频网址”。正式使用要你自己的 OSS 私有存储（兔白上传、生成限时签名链接、取得结果后删除）。服务商的临时上传官方写明“请勿用于生产环境”，兔白只把它当作明确选择的“仅供试用”。

## 文字 AI（断句、校对、翻译；只发送字幕文字）

| 服务 | 教程 |
| --- | --- |
| DeepSeek | [教程](deepseek.zh-CN.md) |
| 阿里云百炼 · 通义千问 | [教程](bailian-text.zh-CN.md) |
| OpenAI | [教程](openai-text.zh-CN.md) |
| Google Gemini | [教程](gemini.zh-CN.md) |
| xAI Grok API | [教程](xai.zh-CN.md) |
| 进阶：自定义兼容服务、账号登录类 CLI | [自定义](custom-text.zh-CN.md)、[账号登录类](cli-accounts.zh-CN.md) |

各平台能做什么、哪些已实测，见[没有 NVIDIA 显卡时能做什么](../architecture/platform-support.md)。
