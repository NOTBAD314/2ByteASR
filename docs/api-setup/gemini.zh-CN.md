# 申请与设置 Google Gemini（文字 AI）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译。**只发送字幕文字，不上传音频** |
| 在哪里填 | 「AI 智能断句设置」→“AI 服务”选 **Gemini API** |
| 地区 | 官方“可用地区”页列出的国家和地区里**有 Taiwan（台湾）**；**没有中国大陆、Hong Kong（香港）、Macao（澳门）**。不在列表里的地区不能用 Google AI Studio 和 Gemini API。另外官方要求年满 18 岁 |
| 要花钱吗 | 兔白预填的三个模型都有免费档（输入、输出均“Free of charge”），但免费档的内容会被用于改进 Google 产品。要更高额度或不让内容被使用，需在 AI Studio 设置付费（预付最少 5 美元） |
| 兔白预填的模型 | `gemini-3.8-flash`：官方稳定版，官方建议新项目用 3.8 Flash 或 3.5 Flash-Lite |
| 兔白验证状态 | 已有接入；本轮未用真实密钥重新实测 |

## 它在兔白里做什么

- **AI 断句**：把识别出的整段文字切成适合看的字幕句子（“全文断句使用 AI”）。
- **字幕校对**：修正错别字、专有名词、标点（“字幕校对使用 AI”）。
- **翻译**：日语任务识别后翻成中文，以及字幕工作室里的“翻译 / 生成双语字幕”。翻译用的是“字幕校对模型”那一套设置。
- 同一套设置也用于术语整理、字幕工作室的“AI 设计”等辅助功能。
- 兔白通过 Gemini 的 “OpenAI 兼容接口” 调用。官方说明这套兼容接口“仍处于 beta”。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| 创建 / 查看 API Key（Google AI Studio） | <https://aistudio.google.com/apikey> | 会跳转到 Google 登录，需登录，待核实 |
| API Key 说明 | <https://ai.google.dev/gemini-api/docs/api-key> | |
| 可用地区 | <https://ai.google.dev/gemini-api/docs/available-regions> | |
| OpenAI 兼容接口 | <https://ai.google.dev/gemini-api/docs/openai> | Base URL |
| 模型列表 | <https://ai.google.dev/gemini-api/docs/models> | |
| 价格与免费档 | <https://ai.google.dev/gemini-api/docs/pricing> | |
| 付费设置（预付 / 后付） | <https://ai.google.dev/gemini-api/docs/billing> | |
| 错误码 | <https://ai.google.dev/gemini-api/docs/api-errors> | |
| 故障排查 | <https://ai.google.dev/gemini-api/docs/troubleshooting> | |

## 从未注册开始

1. 先确认你所在的国家 / 地区在官方可用地区列表里（见上文），并且已满 18 岁。官方说如果 Google 账户还没验证年龄，也会打不开 AI Studio。
2. 用 Google 账户登录 <https://aistudio.google.com/apikey>。
3. 点“Create API key”（官方说明里的按钮名）。官方：每个 Key 都属于一个 Google Cloud 项目；新用户 AI Studio 会自动建一个默认项目和 Key；已有 Google Cloud 账户的用户不会自动建，需要先导入一个项目再建 Key。官方还说，自 2026-05-28 起在 AI Studio 新建的 Key 都是“auth key”（授权密钥）。完整 Key 是否只显示一次：需要登录才能看到，待核实。
4. 只用免费档的话，到这里就可以了。要付费：在 AI Studio 点“Set up billing”（官方说明里的按钮名），绑定 Cloud Billing 账户并预付额度（见下一节）。
5. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选 Gemini）
6. 在“AI 服务”下拉里选 **Gemini API**（新安装时默认选的是“Grok Account”，记得改）。
7. 把 Key 贴进“API 密钥”，点“测试连接”。
8. 看到“连接测试通过”后，点对话框右下角“保存设置”。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务、各自填密钥。

## 需不需要开通服务、付费或储存空间

| 项目 | 是否需要 |
| --- | --- |
| Google Cloud 项目 | 每个 Key 都属于一个项目；新用户由 AI Studio 自动创建 |
| 付费 | 免费档不需要。付费档：在 AI Studio 点“Set up billing”。新用户默认是预付方式，最少预付 5 美元（或等值其他货币），最多 5000 美元；也有月底结算的后付方式 |
| 预付额度用完 | 官方：余额为 0 时，这个结算账户下所有项目的所有 Key 会同时停用，请求报 402；不会自动退回免费档，要么充值，要么关掉付费 |
| 免费档的数据 | 官方价格页：免费档“Content used to improve our products”；付费档“not used” |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| AI 服务 | 选用哪家服务 | `Gemini API` | 下拉选择 | 需要自己选 |
| API 密钥 | 证明是你的账户在调用 | AI Studio 里创建的 Key（输入框提示“请输入 API Key”） | <https://aistudio.google.com/apikey> | 否 |
| 模型 | 用哪个模型 | `gemini-3.8-flash`（预填）；也可选 `gemini-3.6-flash`、`gemini-3.5-flash-lite`（更便宜） | 官方模型页 | 是 |
| Base URL（在“进阶设置：Base URL、协议与输出能力”里） | 服务地址 | `https://generativelanguage.googleapis.com/v1beta/openai` | 官方 OpenAI 兼容说明 | 是，不用改 |
| 协议 / Protocol（进阶） | 请求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（进阶） | 要求模型按固定格式回答 | 勾选 | — | 已勾选，不用改 |
| stream（进阶） | 灰色不可选；兔白目前不用流式 | — | — | — |

地址说明（这张卡片只有“Base URL”一栏，兔白会自己补上后面的路径）：

| 名称 | 值 |
| --- | --- |
| 官方网站 | Google AI Studio <https://aistudio.google.com/apikey>（需登录）；文档 <https://ai.google.dev/gemini-api/docs/openai> |
| API Host | `generativelanguage.googleapis.com` |
| Base URL（填在兔白里的） | `https://generativelanguage.googleapis.com/v1beta/openai`（预填，不用改）。官方示例末尾多一个 `/`，兔白会自动去掉，写不写都一样 |
| 完整请求 Endpoint | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |

## 测试时会看到什么

**测试连接**：兔白用这张卡片上的服务、模型、地址和密钥（刚贴进去还没保存的密钥也会用）发一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。免费档不收费；付费档会产生极少量费用。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · 兼容 JSON／本地校验 · 1.23s`（最后是用时）。如果卡片上选的服务和上次保存的不同，后面还会加“尚未保存：点击保存后 AI 设计才会使用此 Provider”。
- 首页 AI 卡片下方会显示“连接正常”；失败显示“连接失败”；还没测过显示“尚未测试连接”。
- 失败时状态行显示服务商的错误，例如 `HTTP 403：……`，对照下表处理。

**刷新模型**：读取你的 Key 能用的 Gemini 模型列表（不让模型生成文字）。成功显示“已发现 N 个模型 · 可搜索选择或手动输入”。填完密钥、离开输入框时也会自动读一次。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “当前模型（gemini）缺少 API 密钥……” | 还没贴密钥 | 把 Key 贴进“API 密钥”再测 |
| 打开 AI Studio 显示 “Google AI Studio is not available in your region” | 所在地区不在官方列表 | 无法在本地区使用；改用 DeepSeek、阿里云百炼等其他服务 |
| `HTTP 400`，内容含 `failed_precondition` | 前置条件不满足，官方举例“结算未启用” | 到 AI Studio 检查这个项目的付费状态 |
| `HTTP 401` 或 `HTTP 403` | Key 无效、过期，或没有权限；官方还说 Gemini API 会拒绝“未加限制的标准 Key” | 回 AI Studio 新建一个 Key 再贴入（新建的 Key 默认就是 auth key） |
| `HTTP 402` | 预付额度用完 | 在 AI Studio 充值或开启自动充值；官方说充值前重试没有用 |
| `HTTP 404`，提示模型不存在 | 模型名写错，或模型已下线 | “模型”改回 `gemini-3.8-flash`，或点“刷新模型”从列表里选 |
| `HTTP 429` | 每分钟请求数 / token 超限，或当天额度用完 | 等一会儿再试；当天额度用完要等额度重置，或申请提高额度 |
| `HTTP 500` / `503` / `504` | 服务端故障、过载或超时 | 稍后再试 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 按上表查原因（多半是限流或额度），处理后重新识别；只差少量字幕时，可在字幕工作室“字幕列表”上方点“AI 校对”看修改建议 |

## 隐私与费用

- **传到哪里**：`generativelanguage.googleapis.com`（Google，境外）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作室的“AI 设计”在模型支持看图时，可能附带画面截图或字幕效果预览图。用免费档时，官方说这些内容会被用于改进 Google 产品。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只保留到退出软件，绝不存明文。不写进工程、日志或导出文件。
- **费用**（官方价格页，标准档，文字，2026-10-14 核对，单位：美元 / 百万 token）：

| 模型 | 免费档 | 付费：输入 | 付费：输出（含思考） |
| --- | --- | --- | --- |
| `gemini-3.8-flash` | 免费 | 0.75（至 2026-12-31）；1.50（2027-01-01 起） | 3.75（至 2026-12-31）；7.50（2027-01-01 起） |
| `gemini-3.6-flash` | 免费 | 同上 | 同上 |
| `gemini-3.5-flash-lite` | 免费 | 0.30 | 2.50 |

免费档的用量限制本次没有在价格页上查到具体数字；官方可能调整免费档，不要当作永久免费。一段视频要花多少取决于字幕字数和重试次数，兔白没有固定数字。

## 进阶（一般使用者可跳过）

- 兔白发送 `POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`，带 `Authorization: Bearer <密钥>`；需要按 JSON 回答时附 `response_format: {"type": "json_object"}`。测试连接的内容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 个输出 token。
- “刷新模型”不走兼容接口，而是调用 Gemini 原生的 `GET https://generativelanguage.googleapis.com/v1beta/models`，密钥放在 `x-goog-api-key` 头里。
- 带 `-high` 的名字（如 `gemini-3.8-flash-high`）是兔白“Google Antigravity”选项用的名字，不是 Gemini API 的模型名，不要填在这里。
- 2026-05-28 起的新 Key 是 auth key。用这种 Key 调用 OpenAI 兼容接口，官方兼容说明的示例仍是直接填 Key；兔白本轮未用新 Key 实测。
- 本机没有保存密钥时，兔白也会读取环境变量 `GEMINI_API_KEY`；已保存的密钥优先。

## 来源（2026-10-14 核对）

- 可用地区：<https://ai.google.dev/gemini-api/docs/available-regions>（逐项核对了 C、H、M、S、T 开头的国家 / 地区）
- API Key：<https://ai.google.dev/gemini-api/docs/api-key>
- OpenAI 兼容接口：<https://ai.google.dev/gemini-api/docs/openai>
- 模型：<https://ai.google.dev/gemini-api/docs/models>
- 价格：<https://ai.google.dev/gemini-api/docs/pricing>
- 付费设置：<https://ai.google.dev/gemini-api/docs/billing>
- 错误码：<https://ai.google.dev/gemini-api/docs/api-errors>
- 故障排查：<https://ai.google.dev/gemini-api/docs/troubleshooting>
- <https://aistudio.google.com/apikey> 跳转到 Google 登录，本次没有看到里面的内容。
