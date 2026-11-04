# 申请与设置 DeepSeek（文字 AI）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译。**只发送字幕文字，不上传音频** |
| 在哪里填 | 「AI 智能断句设置」，不是「申请与设置 API」 |
| 要花钱吗 | 要。按用量（token）从账户余额扣费，用前要充值；在线充值前要先完成实名认证 |
| 兔白预填的模型 | `deepseek-v4-flash`。官方说这是**旧名字**：仍可调用，但实际由 DeepSeek-V4.1-Flash 回答、按 Flash 价格计费。官方推荐新名字 `deepseek-flash`，可在“模型”下拉里改选 |
| 兔白验证状态 | 已有接入；本轮未用真实密钥重新实测 |

## 它在兔白里做什么

- **AI 断句**：把识别出的整段文字切成适合看的字幕句子（“全文断句使用 AI”）。
- **字幕校对**：修正错别字、专有名词、标点（“字幕校对使用 AI”）。
- **翻译**：日语任务识别后翻成中文，以及字幕工作室里的“翻译 / 生成双语字幕”。翻译用的是“字幕校对模型”那一套设置。
- 同一套设置也用于术语整理、字幕工作室的“AI 设计”等辅助功能。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| 开放平台（注册 / 登录） | <https://platform.deepseek.com/sign_in> | 公开页：手机号验证码登录、密码登录、微信扫码登录 |
| API Keys 页面 | <https://platform.deepseek.com/api_keys> | 需登录，待核实 |
| 充值页面 | <https://platform.deepseek.com/top_up> | 需登录，待核实 |
| API 文档 | <https://api-docs.deepseek.com/zh-cn/> | Base URL、模型名 |
| 模型与价格 | <https://api-docs.deepseek.com/zh-cn/quick_start/pricing> | |
| 错误码 | <https://api-docs.deepseek.com/zh-cn/quick_start/error_codes> | |
| 限速说明 | <https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit> | |
| 常见问题（充值、实名、余额） | <https://static.deepseek.com/faq/index.html?lang=zh#/category/4> | |

## 从未注册开始

1. 打开 <https://platform.deepseek.com/sign_in>，用手机号收验证码登录。官方页面写着“未注册的手机号将自动注册”。也可以用密码登录或微信扫码登录。
2. **实名认证**：官方常见问题写明，完成实名认证后才能在“充值”页面用支付宝 / 微信在线充值。个人认证和企业认证的权益没有差别。实名入口和要准备什么，需要登录才能看到，待核实。
3. **充值**：打开 <https://platform.deepseek.com/top_up> 充值。第一次用，充 10 元就够先试一阵（兔白的建议；按用量扣费，用多少扣多少）。最低充值金额需要登录才能看到，待核实。官方说充值余额永久有效、不会过期。
4. **创建 API Key**：打开 <https://platform.deepseek.com/api_keys> 创建一个 Key 并复制。按钮名称、完整 Key 是否只显示一次：需要登录才能看到，待核实。建议一创建就复制下来。
5. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选 DeepSeek）
6. 在“AI 服务”下拉里选 **DeepSeek API**（新安装时默认选的是“Grok Account”，记得改）。
7. 把 Key 贴进“API 密钥”，点“测试连接”。
8. 看到“连接测试通过”后，点对话框右下角“保存设置”。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务、各自填密钥。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 单独开通服务、申请模型权限 | 官方文件没有提到 |
| 实名认证 | 在线充值前需要（官方常见问题） |
| 充值 | 需要。余额用完会报 402。官方：如果同时有赠送余额和充值余额，先扣赠送余额；新账户是否有赠送余额，官方文件没写 |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| AI 服务 | 选用哪家服务 | `DeepSeek API` | 下拉选择 | 需要自己选 |
| API 密钥 | 证明是你的账户在调用 | 一长串字符（输入框提示“请输入 API Key”） | API Keys 页面 | 否。保存后再打开会显示“已配置：Windows DPAPI / …”，留空表示不修改 |
| 模型 | 用哪个模型 | `deepseek-v4-flash`（预填）；建议改选 `deepseek-flash`；更强更贵的是 `deepseek-v4-pro` | 官方价格页 | 是 |
| Base URL（在“进阶设置：Base URL、协议与输出能力”里） | 服务地址 | `https://api.deepseek.com/v1` | 官方文档 | 是，不用改 |
| 协议 / Protocol（进阶） | 请求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（进阶） | 要求模型按固定格式回答 | 勾选 | — | 已勾选，不用改 |
| stream（进阶） | 灰色不可选；兔白目前不用流式 | — | — | — |

地址说明（这张卡片只有“Base URL”一栏，兔白会自己补上后面的路径）：

| 名称 | 值 |
| --- | --- |
| 官方网站 | <https://platform.deepseek.com/> |
| API Host | `api.deepseek.com` |
| Base URL（填在兔白里的） | `https://api.deepseek.com/v1`（预填，不用改）。官方文档现在写的是不带 `/v1` 的 `https://api.deepseek.com`；只有带 `/v1` 的地址报 404 时才需要改成它（见文末进阶）。兔白不会拼出 `/v1/v1` |
| 完整请求 Endpoint | `https://api.deepseek.com/v1/chat/completions`（进阶区“实际请求：”一行会显示） |

## 测试时会看到什么

**测试连接**：兔白用这张卡片上的服务、模型、地址和密钥（刚贴进去还没保存的密钥也会用）发一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。会产生极少量费用。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · 兼容 JSON／本地校验 · 1.23s`（最后是用时）。如果卡片上选的服务和上次保存的不同，后面还会加“尚未保存：点击保存后 AI 设计才会使用此 Provider”。
- 首页 AI 卡片下方会显示“连接正常”；失败显示“连接失败”；还没测过显示“尚未测试连接”。
- 失败时状态行显示服务商的错误，例如 `HTTP 401：……`，对照下表处理。

**刷新模型**：读取 DeepSeek 的模型列表（不让模型生成文字）。成功显示“已发现 N 个模型 · 可搜索选择或手动输入”。填完密钥、离开输入框时也会自动读一次。列表读不到时仍可手动输入模型名。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “当前模型（deepseek）缺少 API 密钥……” | 还没贴密钥 | 把 Key 贴进“API 密钥”再测 |
| “当前模型的 API 地址无效……” | Base URL 被改坏 | 进阶设置里把 Base URL 改回 `https://api.deepseek.com/v1` |
| `HTTP 401` | Key 填错，或已在平台删除（官方：API key 错误，认证失败） | 到 API Keys 页面重新复制，或新建一个 |
| `HTTP 402` | 余额不足 | 到充值页面充值；还没实名的先完成实名 |
| `HTTP 400` 或 `HTTP 422` | 请求格式或参数不被接受，常见是模型名写错 | “模型”改回下拉里的 `deepseek-flash`，Base URL 改回预填值，再测 |
| `HTTP 429` | 请求太快或同时请求太多（官方：并发上限 `deepseek-flash` 2500、`deepseek-v4-pro` 500，按账户计） | 等一会儿再试；少开几个同时跑的任务 |
| `HTTP 500` 或 `HTTP 503` | 服务器故障或繁忙 | 稍后再试 |
| 测试等了很久才失败 | 服务繁忙时官方会先返回空行等待；10 分钟还没开始推理会断开 | 测试最多等 45 秒；稍后再测 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 按上表查原因（多半是余额或限流），处理后重新识别；只差少量字幕时，可在字幕工作室“字幕列表”上方点“AI 校对”看修改建议 |

## 隐私与费用

- **传到哪里**：`api.deepseek.com`（DeepSeek）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作室的“AI 设计”在模型支持看图时，可能附带画面截图或字幕效果预览图。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只保留到退出软件，绝不存明文。不写进工程、日志或导出文件。
- **费用**（官方价格页，2026-10-14 核对，单位：元 / 百万 token，闲时 / 峰时）：

| 模型 | 输入（缓存命中） | 输入（缓存未命中） | 输出 |
| --- | --- | --- | --- |
| `deepseek-flash`（DeepSeek-V4.1-Flash） | 0.02 / 0.04 | 1 / 2 | 4 / 8 |
| `deepseek-v4-pro`（DeepSeek-V4-Pro-0813） | 0.15 / 0.30 | 4.5 / 9.0 | 13.5 / 27.0 |

峰时是北京时间周一至周五（法定节假日除外）9:00–12:00 和 14:00–18:00，其余时间（含周末、节假日）是闲时，闲时价格为峰时的一半。预填的旧名 `deepseek-v4-flash` 按 Flash 价格计费。一段视频要花多少，取决于字幕字数和重试次数，兔白没有固定数字。官方说价格可能调整，请以价格页为准。

## 进阶（一般使用者可跳过）

- 兔白发送 `POST {Base URL}/chat/completions`，带 `Authorization: Bearer <密钥>`；需要按 JSON 回答时附 `response_format: {"type": "json_object"}`。测试连接的内容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 个输出 token。
- “刷新模型”调用 `GET {Base URL}/models`。
- 关于 `/v1`：2026-10-14 不带密钥访问 `https://api.deepseek.com/v1/models` 和 `https://api.deepseek.com/models`，两者都回“需要认证”（HTTP 401），不是“找不到”。官方文档没有再提 `/v1` 写法；如果哪天带 `/v1` 的地址报 404，把 Base URL 改成 `https://api.deepseek.com`。
- 本机没有保存密钥时，兔白也会读取环境变量 `DEEPSEEK_API_KEY`；已保存的密钥优先。
- 兔白把 `deepseek-v4-flash-vision-exp` 当作已下线模型拦截；官方说这个旧名仍可调用（同样由 V4.1-Flash 回答）。

## 来源（2026-10-14 核对）

- 注册 / 登录页：<https://platform.deepseek.com/sign_in>（网页需要浏览器执行脚本，用浏览器打开读取）
- API 文档首页：<https://api-docs.deepseek.com/zh-cn/>、<https://api-docs.deepseek.com/>
- 模型与价格：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing>
- 错误码：<https://api-docs.deepseek.com/zh-cn/quick_start/error_codes>（页面里“创建 API key”“充值”链接分别指向 API Keys 页和充值页）
- 限速：<https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit>
- 常见问题“API相关”：<https://static.deepseek.com/faq/index.html?lang=zh#/category/4>（读了“如何充值”“余额是否会过期”“个人实名认证与企业实名认证有什么区别？”“若发现 API key 泄漏怎么办”）
- API Keys 页、充值页需要登录，本次没有看到里面的内容。
