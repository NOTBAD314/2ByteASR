# 申请与设置 OpenAI 转写

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 语音识别（生成字幕）：把有人声的音频短块上传到 OpenAI 转成文字 |
| 默认模型 | `gpt-transcribe`（OpenAI 当前推荐的录音转写模型） |
| 时间戳 | 默认模型**只回文字**，每块（10 秒以内）只有一个起止时间；改用 `whisper-1` 可得到句段时间。兔白不要逐词时间 |
| 说话人 | **没有**。OpenAI 只有 `gpt-4o-transcribe-diarize` 能分说话人，兔白没有适配它 |
| 费用 | 先充值后使用；`gpt-transcribe` 约 $0.0045 / 分钟（2026-10-14 核对） |
| 地区 | **中国大陆、香港、澳门不在 OpenAI 支持地区内**，在这些地方使用会被拒绝，账户也可能被停用 |
| 兔白验证状态 | 已有接入；本轮未用真实密钥重新实测 |

## 它在兔白里做什么

- 用于语音识别，可以当“主力转写”，也可以当“复核”来源。
- 兔白先在本机找出有人声的片段，切成短块：当主力时每块 10 秒以内，当复核时 25 秒以内。每块转成 16 kHz 单声道 WAV 上传，默认 4 块同时进行。
- 兔白向 OpenAI 要“带句段时间”的结果。官方说只有 `whisper-1` 提供时间戳，所以：
  - 用 `gpt-transcribe`（默认）、`gpt-4o-transcribe`、`gpt-4o-mini-transcribe`：只拿到文字，整块共用一个起止时间；
  - 用 `whisper-1`：拿到句段起止时间。
  - 需要按字剪辑时，请在模型工坊配一个本地字幕时间轴（对齐）模型。
- 每次上传还会附一段文字提示，帮助拼对专有名词：当前字幕场景、素材文件名，以及你在词库里确认过的专名（最多 64 个）。
- 某一块失败时，兔白会自动等一会儿再试，最后再把失败的块逐个补一遍。仍失败的部分会提示“约 N 秒素材无字幕，可重跑识别补齐”。
- 这里只管语音识别。用 OpenAI 做 AI 断句、校对、翻译，要另外在「AI 智能断句设置」里填写，见“OpenAI”文字 AI 教程。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| 开发者文档：快速开始 | <https://developers.openai.com/api/docs/quickstart> | 创建 Key、免费测试请求、加值 |
| API Key 页面 | <https://platform.openai.com/settings/organization/api-keys> | 需登录，待核实（网址来自官方 API 参考页） |
| 用量档位与限额 | <https://platform.openai.com/settings/organization/limits> | 需登录，待核实（网址来自官方速率限制页） |
| 语音转文字说明 | <https://developers.openai.com/api/docs/guides/speech-to-text> | 各模型差别、时间戳只限 `whisper-1` |
| `gpt-transcribe` 模型页 | <https://developers.openai.com/api/docs/models/gpt-transcribe> | |
| 价格 | <https://developers.openai.com/api/docs/pricing> | |
| 支持的国家和地区 | <https://developers.openai.com/api/docs/supported-countries> | |
| 错误码 | <https://developers.openai.com/api/docs/guides/error-codes> | |
| 速率限制与用量档位 | <https://developers.openai.com/api/docs/guides/rate-limits> | |

## 从未注册开始

1. 先确认你所在的地区在官方支持列表里（见上表）。中国大陆、香港、澳门不在列表中。
2. 注册并登录 OpenAI 开发者平台（platform.openai.com）。注册页面和需要填写的资料：需要登录才能看到，待核实。
3. 充值：OpenAI API 用预付额度。官方快速开始说可以先做一次免费测试请求，要更高额度需在 Billing 加值；累计购买满 $5 会升到 Build 档。没有充值时转写能不能用，官方未写明，兔白未实测，建议先加值。加值页面的位置和最低金额：需要登录才能看到，待核实。
4. 打开 API Key 页面，创建一把 Key（官方：“create an API key in the dashboard”）。按钮名称、是否需要选项目、完整 Key 是否只显示一次：需要登录才能看到，待核实。建议建好后立刻复制。
5. 打开兔白的「申请与设置 API」，在左侧“语音识别（生成字幕）”下选 **OpenAI 转写**。打开方式任选一种：
   - 首页右上角“说明”菜单 →“申请与设置 API…”
   - 模型工坊 →“在线 API”页 →“OpenAI Transcribe API”卡片上的设置按钮
   - 首页识别方案卡片上的“配置 API”
6. 贴入“API Key”。“模型”可以留空（等于 `gpt-transcribe`），见下表。
7. 点“免费检查（不上传音频）”；想确认真的能识别，再点“试识别一小段…”。
8. 点“保存”；要马上用它做主力转写，点“保存并用于识别”。

这一页目前没有“① 在官网创建 API Key [打开网页]”那一排提示，请用上面表格里的链接打开官网。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 单独开通语音服务 | 官方文件没有提到；模型页列出的默认限额从 Build 档开始 |
| 充值 | 需要（预付额度）。额度用完时请求会被拒绝 |
| 地区 | 必须在官方支持地区使用；官方说在不支持的地区使用，账户可能被封锁或停用 |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| API Key | 证明是你的账户在调用 | 栏位示例为 `sk-…`（官方页面本次没写明格式） | OpenAI 的 API Key 页面 | 否。保存后再打开会显示“已保存（···后四位）；留空表示不修改” |
| 模型 | 用哪个转写模型 | `gpt-transcribe` 或 `whisper-1` | 官方语音转文字说明 | **新用户看到的是空白框**，下面的提示写着“默认值需按 OpenAI 当前文档核对。”。留空保存，兔白就用 `gpt-transcribe`；保存后再打开会显示已保存的模型名 |

怎么选模型（价格为官方价格页 2026-10-14 的估算值）：

| 模型 | 约每分钟 | 兔白拿到的时间 |
| --- | --- | --- |
| `gpt-transcribe`（默认，官方推荐） | $0.0045 | 每块一个起止时间 |
| `gpt-4o-mini-transcribe` | $0.003 | 每块一个起止时间 |
| `gpt-4o-transcribe` | $0.006 | 每块一个起止时间 |
| `whisper-1` | $0.006 | 句段起止时间 |

地址在这一页**不显示**，已经预设好，一般不用改。要改请点“进阶设置…”，在「配置在线 ASR API」里改“API 地址”。

| 项目 | 预设值 |
| --- | --- |
| 官方网站 | developers.openai.com（文档）、platform.openai.com（控制台，需登录） |
| API Host | `api.openai.com` |
| Base URL | `https://api.openai.com/v1` |
| 完整请求 Endpoint | `https://api.openai.com/v1/audio/transcriptions` |

“API 地址”里存的是**完整请求 Endpoint**（最后一项，含 `/audio/transcriptions`），不是 Base URL。

## 测试时会看到什么

**免费检查（不上传音频）**：兔白用你的 Key 读取 OpenAI 的模型列表，不上传音频、不收费。全部正常时：

| 结果行 | 显示 |
| --- | --- |
| 设置格式 | ✓ 格式正确（地址 api.openai.com）。这一步只在本机检查，没有联系服务商。 |
| 服务可以连线 | ✓ 通过 |
| 认证成功（API Key 有效） | ✓ 通过 |
| 指定模型可用 | ✓ 通过（模型列表里有你选的模型；列表里是否一定列出 `gpt-transcribe`，兔白未实测） |
| 实际短音频识别、回传时间戳、回传说话人 | — 尚未检查 |

免费检查全 ✓ 也不代表账户有余额，余额要靠试识别确认。

**试识别一小段…**：先弹出确认，写明会上传到 `api.openai.com`、可能产生费用。选“上传自带测试音频”（兔白自带约 6 秒英文合成语音，不含你的素材）或“选择我的音频…”（60 秒以内）。按 `gpt-transcribe` 折算约 $0.0005（官方没写最小计费单位）。成功时：

| 结果行 | 显示 | 说明 |
| --- | --- | --- |
| 实际短音频识别 | ✓ 识别出 N 段文字。 | 真的能用了 |
| 回传时间戳 | ? 只有句段起止时间，没有逐字时间…… | 正常结果。用 `gpt-transcribe` 时实际上整块只有一个时间 |
| 回传说话人 | — 这次结果没有说话人标签…… | 兔白不取 OpenAI 的说话人 |

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 设置格式 ✗“还没有填写 API Key”或“API Key 里有空格或换行” | 没贴上，或多复制了空格 | 回 Key 页面重新复制那一串字符 |
| 服务可以连线 ✗“连不上服务：……” | 电脑网络到不了 `api.openai.com` | 检查网络；所在地区不受支持时请改用其他服务（如讯飞、阿里云百炼） |
| 认证成功 ✗ HTTP 401 | Key 填错、已删除，或不属于任何组织（官方 401 说明） | 新建一把 Key 重新贴入；仍失败请确认账户已加入组织 |
| 认证成功 ✗ HTTP 403 | 兔白这里显示成“服务拒绝了这个 API Key”，但最常见的原因是**所在地区不受支持**（官方 403：Country, region, or territory not supported） | 对照官方支持地区列表。兔白不能绕过地区限制，请改用其他服务 |
| 指定模型可用 ✗“模型列表里没有 ……” | 模型名打错，或这把 Key 所在项目不能用这个模型 | 清空“模型”栏（用默认 `gpt-transcribe`）或改填 `whisper-1`；项目的模型权限设置在控制台里，需要登录才能看到，待核实 |
| 试识别或正式识别报 HTTP 429，而且等了好几分钟 | 预付额度用完、达到组织或项目的花费上限，或请求太快（官方 429 有这几种） | 兔白目前只显示 HTTP 429，分不出是哪一种。先到 Billing 看余额并加值，再看 Limits 页；然后重试 |
| 试识别报 HTTP 400 | 填的模型不能做转写，或请求格式被拒 | 把“模型”改回 `gpt-transcribe` 或 `whisper-1` 后再试 |
| HTTP 500 / 503 | OpenAI 服务端故障或模型过载 | 兔白会自动重试；仍失败就稍后再跑 |
| 识别完成，但提示“N 个短块最终失败（约 X 秒素材无字幕，可重跑识别补齐）” | 部分短块被限流或网络中断 | 稍后再识别一次 |

## 隐私与费用

- **传到哪里**：`api.openai.com`（OpenAI，境外）。
- **传什么**：有人声的音频短块（16 kHz 单声道 WAV，不含画面），加一段文字提示（字幕场景、素材文件名、词库里确认过的专名）。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只在本次运行期间保存在内存，绝不存明文。不写进工程、日志或导出文件。
- **费用**：按上面模型表的每分钟估算价（官方价格页，2026-10-14 核对），从预付额度扣。实际以 OpenAI 账单为准。

## 进阶（一般使用者可跳过）

- 兔白每块发送 `POST https://api.openai.com/v1/audio/transcriptions`（multipart），字段：`model`、`file`（chunk.wav）、`prompt`（最多 900 字）、`response_format=verbose_json`。不发送 `timestamp_granularities[]` 和 `language` / `languages`。
- 服务商回 400 时，兔白改用 `response_format=json` 重试一次。`gpt-transcribe` 是否接受 `verbose_json`，官方没写，兔白未实测；无论哪种情况都没有句段时间。
- 重试：429、5xx 和网络错误每块最多 6 次，等待 1.5 秒起倍增、最长 20 秒，会遵守 `Retry-After`；之后对失败块逐个补扫最多 4 轮。所以额度用完时，试识别可能要等几分钟才报错。
- 免费检查调用的是 `GET https://api.openai.com/v1/models`。
- 官方单文件上限 25 MB；兔白每块只有几百 KB。

## 来源（2026-10-14 核对）

- 快速开始：<https://developers.openai.com/api/docs/quickstart>
- API 参考总览（Key 页面网址）：<https://developers.openai.com/api/reference/overview>
- 语音转文字：<https://developers.openai.com/api/docs/guides/speech-to-text>
- 转写接口参考：<https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create>
- `gpt-transcribe` 模型页：<https://developers.openai.com/api/docs/models/gpt-transcribe>
- 价格：<https://developers.openai.com/api/docs/pricing>
- 支持的国家和地区：<https://developers.openai.com/api/docs/supported-countries>
- 错误码：<https://developers.openai.com/api/docs/guides/error-codes>
- 速率限制与用量档位：<https://developers.openai.com/api/docs/guides/rate-limits>
- platform.openai.com 的注册页、API Key 页、帮助中心预付说明本次打开时都返回 403（需要登录或拒绝抓取），内容未核实。
