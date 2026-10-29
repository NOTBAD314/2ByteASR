# 申请与设置 Claude API（文字 AI）

最后核对：2026-10-18。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译，以及字幕工作台的 AI 特效字幕。**只发送字幕文字，不上传音频**（AI 特效字幕可能附带画面截图） |
| 在哪里填 | 「AI 智能断句设置」→“AI 服务”选 **Claude API**；字幕工作台「AI 特效字幕」的服务下拉也能选 |
| 要花钱吗 | 要。按用量计费，需要在 Claude Console 绑定付款方式或充值；官方文件没有提到长期免费额度 |
| 地区 | 官方“支持的国家和地区”列出了台湾；**中国大陆、香港、澳门不在列表里**，在这些地区注册和调用都不受支持 |
| 兔白预填的模型 | `claude-opus-5-5`（预填）；更便宜的 `claude-sonnet-5-5`、最便宜最快的 `claude-haiku-5-5` |
| 接入方式 | 兔白自己的网络层直接调用 Anthropic Messages API（`POST /v1/messages`），没有另装 Anthropic 的软件包 |
| 兔白验证状态 | 2026-10-18 新接入；请求格式、流式读取、错误处理已用本机测试替身验证，**还没有用真实密钥实测** |

## 它在兔白里做什么

- **AI 断句**：把识别出的整段文字切成适合看的字幕句子（“全文断句使用 AI”）。
- **字幕校对**：修正错别字、专有名词、标点（“字幕校对使用 AI”）。
- **翻译**：日语任务识别后翻成中文，以及字幕工作台里的“翻译 / 生成双语字幕”。翻译用的是“字幕校对模型”那一套设置。
- **AI 特效字幕**：字幕工作台里按描述生成字幕效果；模型会看到当前画面的截图来配色和排版。
- 同一套设置也用于术语整理等辅助功能。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| Claude Console（注册 / 登录） | <https://platform.claude.com/> | 公开页 |
| API Keys 页面 | <https://platform.claude.com/settings/keys> | 需登录（官方“获取 API Key”说明给出的地址） |
| 账单与充值 | <https://platform.claude.com/settings/billing> | 需登录，待核实 |
| 获取 API Key 说明 | <https://platform.claude.com/docs/en/get-api-key> | 建 Key 的步骤 |
| 支持的国家和地区 | <https://www.anthropic.com/supported-countries> | |
| 价格 | <https://platform.claude.com/docs/en/about-claude/pricing> | |
| 错误码 | <https://platform.claude.com/docs/en/api/errors> | |

## 从未注册开始

1. 打开 <https://platform.claude.com/>，注册并登录 Claude Console。注册方式与验证步骤需要在注册流程里才能看到，待核实。
2. **充值 / 绑定付款**：在 Console 的账单页（<https://platform.claude.com/settings/billing>）设置付款方式或购买额度。最低金额、付款方式：需要登录才能看到，待核实。没有可用额度时，请求会被拒绝（见下方“常见失败”）。
3. **创建 API Key**：打开 <https://platform.claude.com/settings/keys>，点 **Create key**，起个名字、选有效期，然后复制。官方：完整的 Key 以 `sk-ant-` 开头，**只在创建时显示一次**，丢了只能新建。
4. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选 Claude API）
5. 在“AI 服务”下拉里选 **Claude API**。
6. 把 Key 贴进“API 密钥”，点“测试连接”。
7. 看到“连接测试通过”后，点对话框右下角“保存设置”。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务、各自填密钥。

**字幕工作台的 AI 特效字幕**：工具面板「AI 设计」里的服务下拉选 **Claude API**，用的是同一个密钥（在上面的设置里填一次即可）。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 单独开通、申请模型权限 | 官方文件没有提到；`claude-opus-5-5` 等模型建好 Key 即可调用 |
| 充值 / 付款方式 | 需要 |
| 组织角色 | 官方：API Keys 页的 **Create key** 按钮是灰的，说明你的角色不能建 Key，请组织管理员调整或代建 |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| AI 服务 | 选用哪家服务 | `Claude API` | 下拉选择 | 需要自己选 |
| API 密钥 | 证明是你的账户在调用 | `sk-ant-api03-…` 一长串 | API Keys 页面 | 否 |
| 模型 | 用哪个模型 | `claude-opus-5-5`（预填）；`claude-sonnet-5-5`、`claude-haiku-5-5` | 官方价格页、模型列表 | 是 |
| Base URL（在“进阶设置：Base URL、协议与输出能力”里） | 服务地址 | `https://api.anthropic.com/v1` | 官方文档 | 是，不用改 |
| 协议 / Protocol（进阶） | 请求格式 | `Auto`（Claude 一律用 Messages API） | — | 是，不用改 |
| JSON Mode、Structured Output（进阶） | 要求模型按固定格式回答 | 勾选 | — | 已勾选，不用改 |

地址说明（这张卡片只有“Base URL”一栏，兔白会自己补上后面的路径）：

| 名称 | 值 |
| --- | --- |
| 官方网站 | <https://platform.claude.com/> |
| API Host | `api.anthropic.com` |
| Base URL（填在兔白里的） | `https://api.anthropic.com/v1`（预填，不用改） |
| 完整请求 Endpoint | `https://api.anthropic.com/v1/messages` |

## 测试时会看到什么

**测试连接**：兔白用这张卡片上的服务、模型、地址和密钥（刚贴进去还没保存的密钥也会用）发一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。会产生极少量费用。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · 兼容 JSON／本地校验 · 1.23s`（最后是用时）。
- 首页 AI 卡片下方会显示“连接正常”；失败显示“连接失败”；还没测过显示“尚未测试连接”。
- 失败时状态行显示服务商的错误，例如 `Provider HTTP 401：……`，对照下表处理。

**刷新模型**：读取你账户能用的模型列表（`GET /v1/models`，不让模型生成文字）。成功显示“已发现 N 个模型 · 可搜索选择或手动输入”。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “Claude 缺少 API Key……” | 还没贴密钥 | 把 Key 贴进“API 密钥”再测 |
| `HTTP 401`（authentication_error） | 官方：Key 格式不对、已撤销或已过期 | 到 API Keys 页面新建一个 Key，重新贴入 |
| `HTTP 402`（billing_error） | 官方：账单或付款信息有问题 | 到 Console 账单页检查付款方式、充值 |
| `HTTP 403`（permission_error） | 官方：这个 Key 没有权限用这项资源 | 请组织管理员检查工作区和权限，或换自己能用的 Key |
| `HTTP 404`（not_found_error） | 模型名或地址不对，或你的组织不能用这个模型 | Base URL 改回 `https://api.anthropic.com/v1`，模型改回 `claude-opus-5-5` 或点“刷新模型”选 |
| `HTTP 400`（invalid_request_error） | 请求内容不被接受；官方：达到你自己设的花费上限时也会返回 400 | 先把模型、Base URL 改回预填值再测；检查 Console 里的花费上限 |
| `HTTP 429`（rate_limit_error） | 官方：达到限速，或达到当前等级的月度花费上限 | 等一会儿再试；少开几个同时跑的任务；一直 429 就到 Console 看用量等级 |
| `HTTP 529`（overloaded_error）或 `HTTP 500` | 官方：服务暂时过载或内部错误 | 稍后重试；兔白会按普通网络问题处理，任务里失败的批次保留原文 |
| “Claude 拒绝了这次请求（安全分类：…）” | 模型的安全分类器拒绝了这段内容。Opus 5.5 / Sonnet 5.5 的请求已允许服务端自动换模型重试，仍被拒才会出现 | 检查这批字幕是否包含敏感内容；可换另一个模型再试 |
| “Claude 输出达到长度上限” | 一批内容太长 | 重新识别时会自动分批；只差少量字幕时可在字幕工作台“字幕列表”上方点“AI 校对” |
| 连不上（超时、无法连接） | 网络到不了 `api.anthropic.com`，或你所在地区不受支持 | 换一个能打开 platform.claude.com 的网络再试；不行就改用 DeepSeek、阿里云百炼等其他服务 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 按上表查原因，处理后重新识别 |

## 隐私与费用

- **传到哪里**：`api.anthropic.com`（境外）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作台的“AI 特效字幕”会附带画面截图或字幕效果预览图。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只保留到退出软件，绝不存明文。不写进工程、日志或导出文件。本机没有保存密钥时，兔白也会读取环境变量 `ANTHROPIC_API_KEY`；已保存的密钥优先。
- **费用**（官方价格页，2026-10-18 核对，单位：美元 / 百万 token）：

| 模型 | 输入 | 缓存命中 | 输出 | 备注 |
| --- | --- | --- | --- | --- |
| `claude-opus-5-5`（预填） | 4.00 | 0.20 | 20.00 | |
| `claude-sonnet-5-5` | 2.00 | 0.10 | 10.00 | |
| `claude-haiku-5-5` | 0.10 | 0.01 | 0.50 | 单次提示超过 10 万 token 时：输入 0.50、输出 2.50 |

一段视频要花多少取决于字幕字数和重试次数，兔白没有固定数字。价格以官方页面为准。字幕校对、断句这类批量工作用 `claude-sonnet-5-5` 或 `claude-haiku-5-5` 会便宜很多。

## 进阶（一般使用者可跳过）

- 兔白发送 `POST https://api.anthropic.com/v1/messages`，带 `x-api-key: <密钥>` 和 `anthropic-version: 2023-06-01`，并以流式（`stream: true`）读取回答；系统提示放在 `system`，截图转成图片块。
- 这几款模型不接受 `temperature` 等采样参数，兔白不发送；思考是自适应的（不能关），字幕校对、断句、翻译这类批量工作附 `output_config.effort: "low"` 以加快速度、少用 token，AI 特效字幕用模型默认值。
- 用 `claude-opus-5-5`、`claude-sonnet-5-5` 时附 `fallbacks: "default"`（beta 标头 `server-side-fallback-2026-07-01`）：被安全分类器拒绝时由 Anthropic 服务端换成推荐的模型重试；`claude-haiku-5-5` 没有这项功能。
- 需要按 JSON 回答时，兔白在系统提示里要求“只回一个 JSON 对象”，再从回答里取出 JSON 并本地校验。
- “刷新模型”调用 `GET https://api.anthropic.com/v1/models`（分页参数 `after_id`）。

## 来源（2026-10-18 核对）

- 获取 API Key：<https://platform.claude.com/docs/en/get-api-key>
- 入门（第一个请求）：<https://platform.claude.com/docs/en/get-started>
- 价格：<https://platform.claude.com/docs/en/about-claude/pricing>
- 错误码：<https://platform.claude.com/docs/en/api/errors>
- 支持的国家和地区：<https://www.anthropic.com/supported-countries>
- API Keys 页面、账单页需要登录，本次没有看到里面的内容。
