# 申请与设置 阿里云百炼 · 通义千问（文字 AI）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译。**只发送字幕文字，不上传音频** |
| 在哪里填 | 「AI 智能断句设置」→“AI 服务”选 **阿里云百炼（保留）** |
| 要花钱吗 | 新开通百炼的账户，华北2（北京）地域的模型通常各有 100 万 token、90 天的免费额度；用完后要实名认证并按量付费 |
| 地址怎么填 | 这张卡片**只有一个“Base URL”栏**，不会帮你换算“API Host”。预填的是北京旧域名 `https://dashscope.aliyuncs.com/compatible-mode/v1`，可以直接用；官方建议换成你自己的“业务空间专属域名”，写法见下文 |
| 和录音文件识别共用 Key 吗 | 可以共用同一地域的 API Key |
| 兔白验证状态 | 已有接入；本轮未用真实密钥重新实测 |

## 它在兔白里做什么

- **AI 断句**：把识别出的整段文字切成适合看的字幕句子（“全文断句使用 AI”）。
- **字幕校对**：修正错别字、专有名词、标点（“字幕校对使用 AI”）。
- **翻译**：日语任务识别后翻成中文，以及字幕工作室里的“翻译 / 生成双语字幕”。翻译用的是“字幕校对模型”那一套设置。
- 同一套设置也用于术语整理、字幕工作室的“AI 设计”等辅助功能。
- 服务名后面的“（保留）”表示这是兔白早期就有、继续保留的选项，用法和其他服务一样。

## 官方链接

| 用途 | 网址 | 说明 |
| --- | --- | --- |
| 注册阿里云账号 | <https://account.aliyun.com/register/qr_register.htm> | 公开页 |
| 开通百炼（模型广场） | <https://bailian.console.aliyun.com/model/market> | 需登录，待核实。官方：用主账号打开，阅读并同意协议后自动开通 |
| API Key 页面（北京） | <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key> | 需登录，待核实 |
| 业务空间管理（看 API Host） | <https://bailian.console.aliyun.com/cn-beijing/settings/workspace> | 需登录，待核实 |
| 个人实名认证说明 | <https://help.aliyun.com/zh/account/verify-your-identity-individual-account> | 用手机支付宝扫码 |
| 获取 API Key 说明 | <https://help.aliyun.com/zh/model-studio/get-api-key> | |
| 地域与接入域名 | <https://help.aliyun.com/zh/model-studio/regions> | 专属域名与旧域名 |
| OpenAI 兼容接口说明 | <https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope> | 各地域 Base URL |
| 新人免费额度 | <https://help.aliyun.com/zh/model-studio/new-free-quota> | |
| 模型价格 | <https://help.aliyun.com/zh/model-studio/model-pricing> | |
| 错误码 | <https://help.aliyun.com/zh/model-studio/error-code> | |

## 从未注册开始

1. **注册**：没有阿里云账号先注册 <https://account.aliyun.com/register/qr_register.htm>。
2. **开通百炼**：用**主账号**打开 <https://bailian.console.aliyun.com/model/market>，官方说“阅读并同意协议后，将自动开通阿里云百炼”；没有弹出协议说明已经开通过。如果提示“您尚未进行实名认证”，先完成实名（官方推荐用手机支付宝扫码认证）。
3. **选地域**：API Key 页面右上角先选地域。想用免费额度请选 **华北2（北京）**——官方：只有北京地域的模型有免费额度。每个地域的接入地址、API Key 和模型列表都是分开的，不能混用。
4. **创建 API Key**：在 API Key 页面点“创建 API Key”。官方说明弹窗里有“归属账号”（默认主账号）、“归属业务空间”（默认“默认业务空间”）、“权限”（建议“全部”），点“确定”后在列表里点复制图标复制 Key。官方：Key 没有失效时间；每个账号每个地域最多 50 个。完整 Key 能否在列表里再次查看：需要登录才能确认，待核实。
5. **记下 API Host（想用专属域名时）**：官方说可以在“创建 API Key 后的弹窗”里复制 API Host，或在“业务空间管理”页的“API Host”一列复制。它形如 `llm-xxx.cn-beijing.maas.aliyuncs.com`（`llm-xxx` 是你的业务空间 ID；控制台显示时是否带 `https://`，以实际显示为准）。
6. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选百炼）
7. 在“AI 服务”下拉里选 **阿里云百炼（保留）**（新安装时默认选的是“Grok Account”，记得改）。
8. 把 Key 贴进“API 密钥”。想用专属域名的话，展开“进阶设置：Base URL、协议与输出能力”，按下一节改 Base URL。
9. 点“测试连接”，看到“连接测试通过”后点对话框右下角“保存设置”。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务、各自填密钥。

## Base URL 到底填什么

这张卡片只认 **Base URL**，兔白会在后面自动加 `/chat/completions`。**不要只贴 API Host**，也不要贴录音文件识别用的 `/api/v1` 地址——那样请求会发到错误的路径而失败。

| 名称 | 旧域名（兔白预填） | 业务空间专属域名（官方推荐） |
| --- | --- | --- |
| 官方网站 | 百炼控制台 <https://bailian.console.aliyun.com/model/market>（需登录，待核实） | 同左 |
| API Host | `dashscope.aliyuncs.com` | `llm-xxx.cn-beijing.maas.aliyuncs.com`（从控制台复制） |
| **Base URL（填进兔白）** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| 完整请求 Endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions` |

换算方法：`https://` ＋ 你的 API Host ＋ `/compatible-mode/v1`。如果控制台复制出来的 API Host 已经带 `https://`，就不要再加一次。

两种域名的区别（官方地域页）：

- 专属域名“推荐用于生产环境”。
- 旧域名：“存量业务兼容，建议迁移至业务空间专属域名”；并且“DashScope 域名（dashscope.aliyuncs.com）自2026年9月30日起不再支持新特性”。官方没有写旧域名的停用日期。
- 所以：预填的旧域名现在可以直接用；想长期稳定或要用新功能，换成专属域名。

不是北京地域的 Key：官方 OpenAI 兼容说明列出了新加坡 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`、弗吉尼亚 `https://{WorkspaceId}.us-east-1.maas.aliyuncs.com/compatible-mode/v1`、东京 `https://{WorkspaceId}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1`（`{WorkspaceId}` 换成你的业务空间 ID）。中国香港、法兰克福的聊天地址该页没有列出，待核实。这些地域没有免费额度；兔白预填的模型在这些地域能否使用，兔白未实测。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 开通百炼 | 需要（主账号同意协议即开通） |
| 实名认证 | 开通时如有提示就需要。官方：领取和使用新人免费额度**不需要**实名；免费额度用完后要继续按量付费，**必须**实名并充值 |
| 免费额度 | 首次开通百炼时自动发放，每个模型独立，通常 100 万 token（输入输出合计），有效期 90 天，**仅华北2（北京）地域** |
| 用完以后 | 未实名：直接停用（“免费额度用完即停”对未实名账户强制开启，报 403 `AllocationQuota.FreeTierOnly`）。已实名：默认自动转为按量付费；也可以自己打开“免费额度用完即停” |
| 模型权限 | 默认业务空间的 Key 可调用所有标准模型；子业务空间的 Key 只能调用该空间授权的模型 |
| OSS 等储存空间 | 不需要（只发文字） |

## 兔白里的每一栏

| 栏位 | 做什么用 | 例子 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- | --- |
| AI 服务 | 选用哪家服务 | `阿里云百炼（保留）` | 下拉选择 | 需要自己选 |
| API 密钥 | 证明是你的账户在调用 | 以 `sk-` 开头的一串字符（官方错误码页：确认 Key 以 sk- 开头、没有多余空格） | API Key 页面 | 否。如果你已在「申请与设置 API」为“百炼 · 录音文件识别”保存过 Key，且用的是同一个域名，这里会直接显示“已配置：…”，不用再贴 |
| 模型 | 用哪个模型 | `qwen3.7-flash-2026-07-15`（预填）；更强更贵的 `qwen3.7-max` | 官方价格页 | 是 |
| Base URL（进阶） | 服务地址 | 见上一节 | 控制台 API Host 换算 | 是（北京旧域名）。用专属域名时要改 |
| 协议 / Protocol（进阶） | 请求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（进阶） | 要求模型按固定格式回答 | 勾选 | — | 已勾选，不用改 |
| stream（进阶） | 灰色不可选；兔白目前不用流式 | — | — | — |

## 测试时会看到什么

**测试连接**：兔白用这张卡片上的服务、模型、地址和密钥（刚贴进去还没保存的密钥也会用）发一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。会消耗极少量免费额度或费用。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · 兼容 JSON／本地校验 · 1.23s`（最后是用时）。如果卡片上选的服务和上次保存的不同，后面还会加“尚未保存：点击保存后 AI 设计才会使用此 Provider”。
- 首页 AI 卡片下方会显示“连接正常”；失败显示“连接失败”；还没测过显示“尚未测试连接”。
- 失败时状态行显示服务商的错误，例如 `HTTP 401：……InvalidApiKey……`，对照下表处理。

**刷新模型**：读取百炼的模型列表（不让模型生成文字）。官方兼容接口说明没有写模型列表接口；读不到时会提示“可手动输入模型 ID”，直接在“模型”里输入即可。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “当前模型（bailian）缺少 API 密钥……” | 还没贴密钥 | 把 Key 贴进“API 密钥”再测 |
| `HTTP 401` + `InvalidApiKey` | Key 复制错、多了空格，或 **Key 和地址不是同一地域**（例如北京的 Key 配了新加坡地址） | 重新复制 Key；北京的 Key 配北京的 Base URL |
| `HTTP 401` “Access denied: Either you are not authorized to access this workspace…”，或 `404` “WorkSpace can not be found.” | 专属域名里的业务空间 ID 写错，或你的账号不在这个业务空间 | 回控制台“业务空间管理”页重新复制 API Host，按上一节重新拼 Base URL |
| 请求失败，Base URL 里没有 `/compatible-mode/v1` | 只贴了 API Host，或贴了录音文件识别的 `/api/v1` 地址 | 改成 `https://<API Host>/compatible-mode/v1` |
| `HTTP 403` + `AccessDenied.Unpurchased` | 百炼还没开通 | 用主账号打开模型广场同意协议开通；按提示完成实名 |
| `HTTP 403` + `AllocationQuota.FreeTierOnly` | 免费额度用完，而且未实名或开着“免费额度用完即停” | 完成实名并充值；已实名的关掉“免费额度用完即停”。仍失败时官方建议重置或新建 Key |
| `HTTP 403` + `Model.AccessDenied` | 子业务空间的 Key 没有这个模型的权限 | 给该业务空间授权这个模型，或改用默认业务空间的 Key |
| `HTTP 404` “The model … does not exist.” | 模型名写错 | “模型”改回下拉里的 `qwen3.7-flash-2026-07-15` |
| `HTTP 400` + `Arrearage` | 账户欠费 | 到费用中心充值，等几分钟再测 |
| `HTTP 429` | 请求太频繁或超过限流 | 等一会儿再试；少开几个同时跑的任务 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 按上表查原因（多半是额度或限流），处理后重新识别；只差少量字幕时，可在字幕工作室“字幕列表”上方点“AI 校对”看修改建议 |

## 隐私与费用

- **传到哪里**：你在 Base URL 里填的百炼地址（北京：`dashscope.aliyuncs.com` 或你的 `….cn-beijing.maas.aliyuncs.com`）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作室的“AI 设计”在模型支持看图时，可能附带画面截图或字幕效果预览图。
- **密钥**：只保存在本机。Windows 用 DPAPI 加密；macOS 存在“钥匙串”，钥匙串不可用时只保留到退出软件，绝不存明文。不写进工程、日志或导出文件。
- **费用**（官方价格页，华北2（北京），2026-10-14 核对，单位：元 / 百万 token）：

| 模型 | 单次请求输入长度 | 输入 | 输出 |
| --- | --- | --- | --- |
| `qwen3.7-flash-2026-07-15` | 0–32K / 32K–256K / 256K–1M | 0.2 / 0.6 / 1.2 | 0.8 / 2.4 / 4.8 |
| `qwen3.7-max` | 0–1M | 12 | 36 |

这两个模型思考模式和非思考模式价格相同。按单次请求的输入长度分档计价；一段视频要花多少取决于字幕字数和重试次数，兔白没有固定数字。免费额度用完、已实名的账户会自动转按量付费；不想被扣费请打开“免费额度用完即停”。价格以官方页面为准。

## 进阶（一般使用者可跳过）

- 兔白发送 `POST {Base URL}/chat/completions`，带 `Authorization: Bearer <密钥>`；需要按 JSON 回答时附 `response_format: {"type": "json_object"}`，服务端若回 400 并提到这个参数，兔白会自动去掉它重试一次。测试连接的内容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 个输出 token。
- “刷新模型”调用 `GET {Base URL}/models`。2026-10-14 不带密钥访问旧域名的这个地址回“需要认证”（HTTP 401），说明地址存在；带密钥能否列出模型，兔白本轮未实测。
- 密钥按“服务 + 域名”分开保存。改用专属域名后，之前在旧域名下保存的百炼 Key 仍会被找到。
- 本机没有保存百炼密钥时，兔白也会读取环境变量 `DASHSCOPE_API_KEY`、`2BYTEASR_DASHSCOPE_API_KEY` 等旧名称；已保存的密钥优先。
- 官方价格页还有更新的 `qwen3.8-max` 等模型，可以在“模型”里手动输入；兔白没有为它们预设，也未实测。

## 来源（2026-10-14 核对）

- 地域与接入域名：<https://help.aliyun.com/zh/model-studio/regions>
- OpenAI 兼容接口：<https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- 获取 API Key：<https://help.aliyun.com/zh/model-studio/get-api-key>
- 首次调用（注册、开通、实名提示、创建 Key）：<https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen>
- 新人免费额度：<https://help.aliyun.com/zh/model-studio/new-free-quota>
- 模型价格：<https://help.aliyun.com/zh/model-studio/model-pricing>
- 错误码：<https://help.aliyun.com/zh/model-studio/error-code>
- 个人实名认证：<https://help.aliyun.com/zh/account/verify-your-identity-individual-account>
- 注册页：<https://account.aliyun.com/register/qr_register.htm>（只读到“注册账号”标题）
- 百炼控制台各页面需要登录，本次没有看到里面的内容。
