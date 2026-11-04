# 申请与设置 OpenAI（文字 AI）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译。**只发送字幕文字，不上传音频** |
| 在哪里填 | 「AI 智能断句设置」→“AI 服务”选 **OpenAI API** |
| 地区 | 官方 API 支持国家 / 地区列表里**没有中国大陆、香港、澳门**（有台湾）。在不支持的地区使用会报 403，官方还说账户可能被封禁或停用 |
| 要花钱吗 | 要。预付额度（prepaid credits）用完会报错；最低充值金额本次没能打开官方帮助页确认，待核实 |
| 兔白预填的模型 | `gpt-4.1-mini`：官方仍在列、没有停用通知 |
| 和《OpenAI 转写》共用 Key 吗 | 可以，同一个 OpenAI API Key |
| 兔白验证状态 | 已有接入；本轮未用真实密钥重新实测 |

## 它在兔白里做什么

- **AI 断句**：把识别出的整段文字切成适合看的字幕句子（“全文断句使用 AI”）。
- **字幕校对**：修正错别字、专有名词、标点（“字幕校对使用 AI”）。
- **翻译**：日语任务识别后翻成中文，以及字幕工作室里的“翻译 / 生成双语字幕”。翻译用的是“字幕校对模型”那一套设置。
- 同一套设置也用于术语整理、字幕工作室的“AI 设计”等辅助功能。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| API 平台（注册 / 登录） | <https://platform.openai.com/> | 本次打开时被网站的机器人验证拦下，待核实 |
| API Key 页面 | <https://platform.openai.com/settings/organization/api-keys> | 需登录，待核实（官方 API 参考与错误码页链接到这里） |
| 账单（充值） | <https://platform.openai.com/settings/organization/billing> | 需登录，待核实 |
| 支持的国家 / 地区 | <https://developers.openai.com/api/docs/supported-countries> | |
| 模型 `gpt-4.1-mini` | <https://developers.openai.com/api/docs/models/gpt-4.1-mini> | |
| 价格 | <https://developers.openai.com/api/docs/pricing> | |
| 错误码 | <https://developers.openai.com/api/docs/guides/error-codes> | |
| API 参考（认证方式） | <https://developers.openai.com/api/reference/overview> | |

## 从未注册开始

1. 先确认你所在的国家 / 地区在官方支持列表里（见上表）。
2. 打开 <https://platform.openai.com/> 注册并登录。注册需要什么（邮箱、手机号验证等）：需要登录才能看到，待核实。
3. **充值**：在账单页面 <https://platform.openai.com/settings/organization/billing> 购买预付额度。官方错误码页写明，额度用完时报“Your organization has no prepaid credits remaining”。最低金额、付款方式、是否自动续充：本次没能打开官方帮助中心（有机器人验证），待核实。
4. **创建 API Key**：打开 <https://platform.openai.com/settings/organization/api-keys> 创建一个 Key 并复制。按钮名称、完整 Key 是否只显示一次：需要登录才能看到，待核实。建议一创建就复制下来。
5. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选 OpenAI）
6. 在“AI 服务”下拉里选 **OpenAI API**（新安装时默认选的是“Grok Account”，记得改）。
7. 把 Key 贴进“API 密钥”，点“测试连接”。
8. 看到“连接测试通过”后，点对话框右下角“保存设置”。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务、各自填密钥。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 单独开通、申请模型权限 | 官方模型页没有提到需要申请 `gpt-4.1-mini` |
| 组织（organization） | 官方错误码：账户不属于任何组织会报 401，需要被邀请加入或联系 OpenAI |
| 充值 | 需要（预付额度） |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| AI 服务 | 选用哪家服务 | `OpenAI API` | 下拉选择 | 需要自己选 |
| API 密钥 | 证明是你的账户在调用 | 一长串字符（输入框提示“请输入 API Key”） | API Key 页面 | 否。如果你已在「申请与设置 API」保存过《OpenAI 转写》的 Key，这里会直接显示“已配置：…”，不用再贴 |
| 模型 | 用哪个模型 | `gpt-4.1-mini` | 官方模型页 | 是 |
| Base URL（在“进阶设置：Base URL、协议与输出能力”里） | 服务地址 | `https://api.openai.com/v1` | 官方 API 参考 | 是，不用改 |
| 协议 / Protocol（进阶） | 请求格式 | `Auto` | — | 是，不用改。对 OpenAI，Auto 会用 Responses 接口 |
| JSON Mode、Structured Output（进阶） | 要求模型按固定格式回答 | 勾选 | — | 已勾选，不用改 |
| stream（进阶） | 灰色不可选；兔白目前不用流式 | — | — | — |

地址说明（这张卡片只有“Base URL”一栏，兔白会自己补上后面的路径）：

| 名称 | 值 |
| --- | --- |
| 官方网站 | <https://platform.openai.com/> |
| API Host | `api.openai.com` |
| Base URL（填在兔白里的） | `https://api.openai.com/v1`（预填，不用改） |
| 完整请求 Endpoint | `https://api.openai.com/v1/responses`（协议为 Auto 或“Responses API”时）；选“Chat Completions”时是 `https://api.openai.com/v1/chat/completions` |

注意：协议为 Auto 时，进阶区“实际请求：”一行目前显示的是 `…/chat/completions`，但兔白对 OpenAI 实际发到 `…/responses`。两种接口官方都支持 `gpt-4.1-mini`，不影响使用。

## 测试时会看到什么

**测试连接**：兔白用这张卡片上的服务、模型、地址和密钥（刚贴进去还没保存的密钥也会用）发一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。会产生极少量费用。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · 原生 JSON Schema＋本地校验 · 1.23s`（最后是用时）。如果卡片上选的服务和上次保存的不同，后面还会加“尚未保存：点击保存后 AI 设计才会使用此 Provider”。
- 首页 AI 卡片下方会显示“连接正常”；失败显示“连接失败”；还没测过显示“尚未测试连接”。
- 失败时状态行显示服务商的错误，例如 `Responses API HTTP 401：……`，对照下表处理。

**刷新模型**：读取你账户能用的模型列表（不让模型生成文字）。成功显示“已发现 N 个模型 · 可搜索选择或手动输入”。填完密钥、离开输入框时也会自动读一次。列表里会有很多非文字模型，请选文字聊天模型。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “当前模型（openai）缺少 API 密钥……” | 还没贴密钥 | 把 Key 贴进“API 密钥”再测 |
| `HTTP 401`，内容含 “Incorrect API key provided” 或 “Invalid Authentication” | Key 填错或已删除 | 到 API Key 页面新建一个，重新贴入 |
| `HTTP 401`，内容含 “You must be a member of an organization” | 账户不属于任何组织 | 请组织管理员邀请你加入，或联系 OpenAI |
| `HTTP 403`，内容含 “Country, region, or territory not supported” | 你所在地区不在官方支持列表 | 无法在本地区使用；改用 DeepSeek、阿里云百炼等其他服务 |
| `HTTP 429`，内容含 `credit_balance_exhausted` | 预付额度用完（官方：重试没有用，要先充值） | 到账单页面充值后再测 |
| `HTTP 429`，内容含 “Rate limit reached” | 请求太快 | 等一会儿再试；少开几个同时跑的任务 |
| `HTTP 404` 或提示模型不存在 | 模型名写错，或账户无权使用该模型 | “模型”改回 `gpt-4.1-mini`，或点“刷新模型”从列表里选 |
| `HTTP 500` / `HTTP 503`（`server_is_overloaded`） | 服务端故障或模型过载 | 稍后再试 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 按上表查原因，处理后重新识别；只差少量字幕时，可在字幕工作室“字幕列表”上方点“AI 校对”看修改建议 |

## 隐私与费用

- **传到哪里**：`api.openai.com`（OpenAI，境外）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作室的“AI 设计”在模型支持看图时，可能附带画面截图或字幕效果预览图。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只保留到退出软件，绝不存明文。不写进工程、日志或导出文件。
- **费用**（官方价格页，标准档，2026-10-14 核对，单位：美元 / 百万 token）：

| 模型 | 输入 | 缓存输入 | 输出 |
| --- | --- | --- | --- |
| `gpt-4.1-mini`（兔白预填） | 0.40 | 0.10 | 1.60 |
| `gpt-5-mini`（官方模型页建议复杂任务先试它；兔白未预设、未实测） | 0.25 | 0.025 | 2.00 |

价格页没有为这些模型列出免费额度。一段视频要花多少取决于字幕字数和重试次数，兔白没有固定数字。价格以官方页面为准。

## 进阶（一般使用者可跳过）

- 协议 Auto 时，兔白对 OpenAI 发送 `POST https://api.openai.com/v1/responses`，带 `Authorization: Bearer <密钥>`，按 JSON Schema 要求结构化输出。改选“Chat Completions”时发送 `POST …/chat/completions`。测试连接的内容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 个输出 token。
- “刷新模型”调用 `GET https://api.openai.com/v1/models`。
- 本机没有保存密钥时，兔白也会读取环境变量 `OPENAI_API_KEY`；已保存的密钥优先。

## 来源（2026-10-14 核对）

- 支持的国家 / 地区：<https://developers.openai.com/api/docs/supported-countries>
- 模型 `gpt-4.1-mini`：<https://developers.openai.com/api/docs/models/gpt-4.1-mini>
- 价格：<https://developers.openai.com/api/docs/pricing>
- 错误码：<https://developers.openai.com/api/docs/guides/error-codes>（页面链接了 API Key 页、账单页、组织设置页）
- API 参考（认证）：<https://developers.openai.com/api/reference/overview>
- 快速开始：<https://developers.openai.com/api/docs/quickstart>
- 未能打开：<https://platform.openai.com/>（机器人验证）；帮助中心的预付账单说明（机器人验证）。API Key 页、账单页需要登录。
