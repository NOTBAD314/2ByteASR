# OpenRouter 语音转文字：MAI-Transcribe 2（进阶）

最后核对：2026-10-14（MAI-Transcribe 2 部分 2026-10-25 更新）。来源见文末。标“待核实”的地方需要登录才能确认。

## 先说结论

- 这一项预设微软 **MAI-Transcribe 2**（模型 ID `microsoft/mai-transcribe-2`，$0.10 / 小时音频）：返回字级时间，并区分说话人。
- 兔白验证状态：2026-10-25 用真实 Key 识别了一段 20 秒的中英两人合成录音，字级时间和两位说话人都对。
- 词库：兔白把已确认的词库专名（排在前面的最多 100 个）作为“短语列表”（Azure 的 `phraseList`）交给 MAI-Transcribe 2，帮它认对游戏名、角色名。2026-10-25 实测：一句含“鸣潮、今汐、长离、无妄者、守岸人”的合成录音，不给短语列表时写成“明朝、金犀、长离、无望者、守暗人”，给了之后五个都对。
- 转写风格：跟随识别设置里的“转写风格”（默认“清爽”= `clean`，“逐字”= `verbatim`）。2026-10-25 实测清爽会去掉口误重复（“I- I think”→“I think”），但“嗯、呃、um、uh”这类语气词不一定去掉，兔白后面的成片规则会再处理。2026-10-25 之前兔白把这个选项放错了位置，服务商一直按逐字处理。
- OpenRouter 上没有叫“MAI 2.1”的转写模型（2026-10-25 再查：微软的转写模型只有 `microsoft/mai-transcribe-2` 和 `microsoft/mai-transcribe-1.5`）；名字带 2.1 的 `microsoft/mai-voice-2.1` 是“文字变语音”的模型。兔白以前把这一项标成 MAI 2.1、还拒绝 MAI-Transcribe 2，2026-10-25 起改正。
- 需要先在 OpenRouter 用美元充值；中国大陆用户一般更适合 MOSS Pro 云端、阿里云百炼或千问AI平台。
- 也可以改填其他转写模型的 ID，兔白都没有实测过，能不能拿到时间以“试识别一小段…”的结果为准。

## 它在兔白里做什么

语音识别（生成字幕）。兔白把本次任务的音频切段上传到 OpenRouter，OpenRouter 再转给实际提供该模型的服务商，取回文字，以及服务商给出的时间和说话人。用作主力转写时，每段最长约 3 分钟。

## 官方链接

| 用途 | 地址 | 需要登录 |
| --- | --- | --- |
| 官网（注册 / 登录） | <https://openrouter.ai/> | 否 |
| 创建 API Key | <https://openrouter.ai/keys> | 是（待核实） |
| 充值（Credits） | <https://openrouter.ai/settings/credits> | 是（待核实） |
| 方案与平台费 | <https://openrouter.ai/pricing> | 否 |
| 语音转文字模型列表与单价 | <https://openrouter.ai/collections/speech-to-text-models> | 否 |
| 语音转文字说明 | <https://openrouter.ai/docs/guides/overview/multimodal/stt> | 否 |
| API Key 说明 | <https://openrouter.ai/docs/api_reference/authentication> | 否 |
| 常见问题（付款、退款、额度过期、记录） | <https://openrouter.ai/docs/faq> | 否 |
| 错误码 | <https://openrouter.ai/docs/api_reference/errors-and-debugging> | 否 |

窗口顶部如果没有“打开网页”按钮，直接用上表的链接。

## 从未注册开始

1. 打开 <https://openrouter.ai/> 注册账号。可用哪些登录方式、要不要验证手机，需要进入注册流程才能看到（待核实）。官方公开页面没有提到实名认证。
2. 充值。语音转文字没有免费模型（2026-10-14 列表里 25 个转写模型都标了单价），要先在 Credits 页面买额度。官方价格页写的付款方式：信用卡 / 借记卡、支付宝（AliPay）、加密货币 USDC。充值页的具体按钮需要登录才能看到（待核实）。
3. 创建 Key：打开 <https://openrouter.ai/keys>。官方说明写的是：给 Key 取名，并选择额度上限（也可以不设上限）。官方建议每把 Key 都设上限，避免 Key 外泄后余额被花光。按钮名称需要登录才能看到（待核实）。
4. 复制 Key，贴到兔白的“API Key”栏。完整 Key 是否只显示一次，官方文件没写（待核实），建议创建后马上复制。

## 需不需要开通服务、充值、额外储存

- 不需要单独开通模型，也不需要 OSS 之类的储存：音频直接放在请求里交给 OpenRouter。
- 需要先充值。余额不足或 Key 达到额度上限时，OpenRouter 返回 HTTP 402。

## 兔白里的栏位

打开「申请与设置 API」（首页右上角“说明”菜单 →“申请与设置 API…”），按右上角“换一家”→“更多：自架接口、待验证服务”，再选 OpenRouter 那一项（标有“进阶”）。最后“贴上检查”那一步有两栏：

| 栏位 | 用途 | 例子 | 从哪里拿 |
| --- | --- | --- | --- |
| API Key | 证明是你的账户在付费 | 整串贴上，前后不要有空格 | OpenRouter 的 Keys 页面 |
| 模型 ID | 要用哪个转写模型 | 已预填 `microsoft/mai-transcribe-2`，一般不用改 | 想换别的模型时，从语音转文字模型列表复制“厂商/模型”格式的 ID |

- `microsoft/mai-transcribe-1.5` 可以填，但 OpenRouter 说明它不接受带时间信息的回传格式；兔白会退回只要文字，结果没有可用的时间。

## 已预填、不用改

窗口里没有地址栏位，兔白内置了请求地址，不用填。三种地址的区别：

| 名称 | 地址 |
| --- | --- |
| 官方网站 | `https://openrouter.ai` |
| API Base URL | `https://openrouter.ai/api/v1` |
| 完整请求 Endpoint（兔白实际使用） | `https://openrouter.ai/api/v1/audio/transcriptions` |

## 测试：成功时会看到什么

1. 点“免费检查”（不上传音频）：
   - 设置格式 ✓、服务可以连线 ✓。
   - 认证成功（API Key 有效）显示 ?：“OpenRouter 的模型列表不需要密钥，不能证明密钥有效；请用实际短音频识别确认。”这是正常的。
   - 指定模型可用 目前会显示 ✗“模型列表里没有 …”。原因是兔白查的是 OpenRouter 的一般模型列表，而这个列表不含任何转写模型（2026-10-14 核对）。这是兔白检查方式的问题，不代表你填错；以下一步为准。
2. 点“试识别一小段…”。确认框会写明上传到 `openrouter.ai`，费用“无法事先估算”。选“上传自带测试音频”（约 6 秒英文合成语音，不含你的素材）或“选择我的音频…”（60 秒以内）。
   - 实际短音频识别 ✓“识别出 N 段文字。”表示能用。
   - 回传时间戳 ✓“有字/词级时间（N 个时间片）”表示拿到了逐词时间；显示 ? 和“只有句段起止时间……”表示没有逐词时间（可能只有句段时间，也可能完全没有）。
   - 回传说话人 ✓ 表示有说话人标签；— 表示这次没有。
3. 结果满意再点“保存”或“保存并用于识别”。

## 能拿到什么（时间、说话人）

- OpenRouter 官方：逐词时间只在 `verbose_json` 回传格式下提供，而且取决于实际转给的服务商；`openai/gpt-4o-transcribe` 和 `microsoft/mai-transcribe-1.5` 会拒绝这种格式。
- 被拒时兔白退回只要文字。这时一整段（主力转写最长约 3 分钟）只有一个起止时间，不适合直接做字幕。
- 说话人：兔白向 Azure 提供的模型请求说话人区分；MAI-Transcribe 2 由 Azure 提供，2026-10-25 实测能分出两位说话人。其他模型：官方文件未写明，兔白未实测。
- MAI-Transcribe 2 的逐词结果常常不带标点，兔白按词拼成一行（中文字直接相连，英文词之间加空格），标点由后面的断句步骤补上。

## 费用

按模型单价计费，美元，2026-10-14 从 OpenRouter 公开模型列表读取（MAI-Transcribe 2 于 2026-10-25 再核对），以账单为准：

| 模型 ID | 单价 | 在兔白里 |
| --- | --- | --- |
| `microsoft/mai-transcribe-2` | $0.10 / 小时音频 | 预设；2026-10-25 实测可用 |
| `microsoft/mai-transcribe-1.5` | $0.36 / 小时 | 拿不到时间 |
| `openai/whisper-large-v3-turbo` | $0.00000333 / 秒（约 $0.012 / 小时） | 未实测 |
| `openai/whisper-1` | $0.0001 / 秒（约 $0.36 / 小时） | 未实测 |

- 买额度时另收平台费：按量付费的标准方案 5.5%（常见问题页写最低 $0.80）。
- 常见问题页写明：OpenRouter 保留在购买一年后让未用额度过期的权利。
- MAI-Transcribe 2 的模型页写明失败的请求不收费；其他模型未逐一核对。

## 隐私：会传送什么

- 音频：本次任务的音频（16 kHz 单声道 WAV，只有声音，不含画面）→ OpenRouter（openrouter.ai）→ 实际提供模型的服务商（例如 Azure、DeepInfra、Groq，按模型而定）。
- 这一项不附带素材文件名或术语表：兔白对 OpenRouter 不发送提示文字。
- OpenRouter 常见问题写：默认只记录请求的基本信息（时间、模型、用量），不记录提示和回复内容；音频是否同样处理，页面没有单独写。上游服务商有各自的数据政策。
- API Key 加密保存在本机（Windows 用 DPAPI；macOS 用钥匙串，钥匙串不可用时只在本次运行期间保存，不写成明文），不写进工程、日志或导出文件。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 提示“ASR API 缺少模型名称。” | 模型 ID 被清空了 | 填回 `microsoft/mai-transcribe-2`，或从语音转文字模型列表复制一个 ID 贴上 |
| 指定模型可用 ✗“模型列表里没有 …” | 兔白查的列表不含转写模型（已知问题） | 确认 ID 与官方列表完全一致（含斜杠、大小写），然后用“试识别一小段…”判断 |
| 认证成功 显示 ? | OpenRouter 模型列表公开，无法验证 Key | 正常，用“试识别一小段…”确认 |
| HTTP 401 | Key 无效、被停用或没复制完整 | 回 Keys 页面确认 Key 状态，重新复制整串贴上 |
| HTTP 402 | 余额不足，或 Key 达到额度上限 | 到 Credits 页面充值，或在 Key 页面调高上限 |
| HTTP 403 | 权限不足，或内容被审核拦截 | 换一段测试音频再试；仍失败就换模型或服务 |
| HTTP 400 | 模型不接受这种请求（兔白已自动退回仍失败），或 ID 写错 | 核对 ID；换一个转写模型 |
| HTTP 404 | 模型 ID 不存在，或没有服务商能处理这次请求 | 从官方列表重新复制 ID |
| HTTP 408 | 上游处理超时（官方说上游每次请求 60 秒超时） | 再试一次；反复出现就改用其他服务 |
| HTTP 429 / 502 / 503 | 限流或上游暂时不可用 | 兔白会自动等待重试；仍失败就稍后再试或换模型 |
| 回传时间戳 显示 ? | 这个模型或服务商没给逐词时间 | 不要用它做主力转写；改用有字/词级时间的服务（阿里云百炼、Qwen Cloud 录音文件识别） |

## 进阶（一般使用者可跳过）

- 兔白的请求：`POST https://openrouter.ai/api/v1/audio/transcriptions`，头 `Authorization: Bearer <Key>`，JSON 正文含 `model`、`input_audio`（`data` 为 WAV 的 base64，`format: "wav"`）、`response_format: "verbose_json"`、`timestamp_granularities: ["segment", "word"]`，以及 `provider.options.azure`：`diarization.enabled: true`；`enhancedMode.modelOptions.transcribeStyle` 取兔白的转写风格设置，默认 `clean`；`phraseList.phrases` 为词库专名（只对 `microsoft/mai-transcribe-2` 发送）。写法依据微软 MAI-Transcribe 文档，OpenRouter 原样转给 Azure；2026-10-25 实测 `transcribeStyle` 放在顶层 `modelOptions` 时不生效。
- 遇到 HTTP 400 依次退回：去掉短语列表 → 去掉 `timestamp_granularities` → 改用 `json` → 去掉 `provider` 选项。
- 分段：主力转写每段最长 180 秒；文字复核按人声切成最长约 25 秒的段。
- 兔白读取回应里的 `segments`（`start`、`end`、`text`、`speaker`）和 `words`（顶层或 segment 内；`word`、`start`、`end`、`speaker`）。
- “免费检查”读的是 `GET https://openrouter.ai/api/v1/models`；这个列表默认不含转写模型（官方说明要加 `output_modalities=transcription` 才列出），所以“指定模型可用”会误报 ✗。
- 程序位置：请求在 `twobyteasr/recognition/asr.py` 的 `call_qwen_asr_api`，回应整理成字幕行在同一文件的 `_api_transcription_rows`；预设模型在 `twobyteasr/app/ui.py` 的 `ASR_API_PRESETS["openrouter_word"]`。

## 来源（2026-10-14 核对，2026-10-25 补核 MAI-Transcribe 2）

- 微软 MAI-Transcribe 文档（diarization、modelOptions.timestamps / transcribeStyle、phraseList.phrases、locales）：<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe>
- OpenRouter 语音转文字说明：<https://openrouter.ai/docs/guides/overview/multimodal/stt>
- OpenRouter 语音转文字模型列表：<https://openrouter.ai/collections/speech-to-text-models>
- OpenRouter 转写模型公开清单（JSON）：<https://openrouter.ai/api/v1/models?output_modalities=transcription>；文字变语音清单：<https://openrouter.ai/api/v1/models?output_modalities=speech>；一般模型清单：<https://openrouter.ai/api/v1/models>
- MAI-Transcribe 2 模型页：<https://openrouter.ai/microsoft/mai-transcribe-2>
- API Key 说明：<https://openrouter.ai/docs/api_reference/authentication>
- 方案与平台费：<https://openrouter.ai/pricing>
- 常见问题：<https://openrouter.ai/docs/faq>
- 错误码：<https://openrouter.ai/docs/api_reference/errors-and-debugging>
- Keys 与 Credits 页面需要登录，本次只确认会转到登录，内容待核实。
