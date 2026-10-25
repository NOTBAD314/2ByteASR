# 申请与设置 千问AI平台（Qwen 官方中国站）· 录音文件识别

最后核对：2026-10-25。来源见文末。千问AI平台是 Qwen 官方 API 的中国站，和国际站 Qwen Cloud 是同一套接口、同一批模型；兔白所在电脑没有千问AI平台账号，真实服务尚未验证。

## 一眼看懂

| 项目 | 内容 |
| --- | --- |
| 在兔白里做什么 | 云端识别长录音（单个文件 ≤12 小时、≤2 GB），不需要显卡或本地模型。服务在北京，大陆网络直接可用 |
| 两个模型（同一把 Key） | **Qwen-Audio-3.1-ASR-Flash**（推荐）：字/词级时间 + 说话人（官方建议 2 小时内），支持热词与上下文。**Qwen3-ASR-Flash**：字/词级时间，不分说话人，不支持热词 |
| 需要什么 | 千问AI平台账号 + 按量付费 API Key（`sk-ws-` 开头），**以及一个阿里云 OSS 私有存储**（设置一次） |
| 为什么要 OSS | 这个接口只收“服务端读得到的音频网址”（官方：公网可访问的文件 URL，单次 1 个）。兔白把音频放进你的私有 Bucket，用限时签名链接交给服务商，取得结果后删除 |
| 不想碰 OSS | 改用“MOSS Pro 云端（MOSI）”：只要一把 Key，直接上传本地音频（只有句段时间，有说话人） |
| 费用 | 按音频用量计费，以千问AI平台账单为准；新用户注册有体验额度（哪些模型可用以控制台为准）。单价见官方定价页 |

> **关于“服务商临时上传”**：官方原文写明“临时 URL 有效期48小时，过期后无法使用，请勿用于生产环境”。兔白只把它当作“先试试看”的选项，不会自动替你选：只有你在“音频交给服务商的方式”里明确选“服务商临时上传（仅供试用）”才会使用。

### 中国站还是国际站

在“申请与设置 API…”里选“千问AI平台 录音文件识别”或“Qwen Cloud 录音文件识别”都是同一项，窗口顶部有“中国站（千问AI平台）/ 国际站（Qwen Cloud）”切换。简体中文界面默认中国站；已经保存过地址的，按保存的地址显示。

| 入口 | 能不能给兔白识别字幕 |
| --- | --- |
| 千问 App / 网页聊天 | **不能**。聊天登录只用于聊天，没有给第三方软件的授权方式 |
| **千问AI平台（本页，platform.qianwenai.com）** | **能**。服务在北京，用按量付费 API Key，不需要 Workspace ID |
| Qwen Cloud（国际站，home.qwencloud.com） | 能，在同一窗口切到“国际站”。服务在新加坡，Key 与千问AI平台**不能互换** |
| 阿里云百炼 | 能，见“阿里云百炼 · 录音文件识别”。Key 与千问AI平台**不能互换** |

## 跟着做

1. **注册并登录**：<https://platform.qianwenai.com/home> → 右上角“登录”，用手机号或阿里云账号登录。
2. **认证与充值**：新用户注册即有体验额度；体验额度用完后，要先完成实名认证并充值才能继续调用（官方错误码说明）。账单页：<https://platform.qianwenai.com/home/billing/overview>。控制台里有“免费额度用完即停”开关：开着时免费额度用完会直接停止，不扣钱。
3. **创建 API Key**：<https://platform.qianwenai.com/home/api-keys> → “创建 API Key” → 填描述（例如“兔白字幕”）→ 生成，**立刻复制**（官方：完整 Key 只在创建时显示一次）。按量付费 Key 是 `sk-ws-` 开头（早期创建的是 `sk-` 开头）。**不要用 Token Plan 订阅 Key（`sk-sp-` 开头）**，它不能做录音文件识别。
4. **准备 OSS 私有存储**（只做一次）：
   - 已经为“阿里云百炼 · 录音文件识别”设置过 OSS 的，**直接共用**，跳过这一步。
   - 没有的话，在阿里云 OSS 控制台 <https://oss.console.aliyun.com/> 建私有 Bucket。地域建议选华北2 北京（`cn-beijing`），离服务近。
   - 建只管 `asr-temp/` 目录的 RAM 子用户与 AccessKey（<https://ram.console.aliyun.com/>）、加最小权限策略与生命周期清理，步骤和权限策略与百炼教程“第二部分”完全相同。
5. **贴到兔白**：首页右上角“说明”→“申请与设置 API…”→ 右上角“换一家”选“千问AI平台 录音文件识别”，确认顶部选的是“中国站（千问AI平台）”。窗口一步一页：注册登录 › 充值 › 创建 Key › 建 OSS › 贴上检查，每一步的按钮直接打开对应页面。
6. **检查**：点“免费检查”（不上传音频）和“检查 OSS（上传很小的测试文件后删除）”；想确认真的能识别，再点“试识别一小段…”。
7. 点“**保存并用于识别**”。

## 兔白里的每一栏

| 栏位 | 填什么 | 已预填？ |
| --- | --- | --- |
| 模型 | 两选一（见上表） | 已预选 Qwen-Audio-3.1 |
| API Key | 第 3 步复制的 Key | 否 |
| 服务地址（灰色，按“修改”才能改） | `https://maas.qianwenaiapi.com` | **已预填，不用改** |
| 音频交给服务商的方式 | “我自己的阿里云 OSS 私有存储（正式使用）” | **已预选 OSS** |
| OSS 地域 / Bucket 名称 / AccessKey ID / Secret | 第 4 步的结果 | 否（与百炼共用同一组设置） |
| 临时目录（灰色） | `asr-temp/` | **已预填** |

服务地址不用你判断：官方网站 `https://platform.qianwenai.com/home`、API Host `maas.qianwenaiapi.com`、Base URL `https://maas.qianwenaiapi.com/api/v1`、完整请求 Endpoint `https://maas.qianwenaiapi.com/api/v1/services/audio/asr/transcription`（按“修改”后可在“将使用”一行和它的提示里看到）。

## 测试会看到什么

| 结果行 | 成功时 | 会不会上传 / 收费 |
| --- | --- | --- |
| 设置格式 | ✓（Key 没有空格、不是 Token Plan Key、地址是 https） | 只在本机检查 |
| 服务可以连线 / 认证成功（API Key 有效） | ✓ | 不上传、不收费 |
| 指定模型可用 | 常显示“?”：这个接口的模型列表不列出录音文件识别模型，以实际识别为准 | 不上传、不收费 |
| 音频上传方式 | ✓ 可以上传、生成签名链接并删除测试对象（选了临时上传时：服务商同意发放上传凭证，没有上传任何文件） | 只上传十几个字节的测试文件 |
| 实际短音频识别 / 回传时间戳 / 回传说话人 | ✓ 识别出文字、有字/词级时间；单人测试音频的说话人常显示“—” | **上传测试音频，可能收费** |

## 常见失败与下一步

| 现象 | 原因 | 下一步 |
| --- | --- | --- |
| 服务商不认这把 API Key | 复制不完整、多了空格、Key 已删除，或用了 Qwen Cloud（国际站）/ 百炼的 Key | 回 API Key 页面重新创建并复制；用国际站的 Key 就把窗口顶部切到“国际站” |
| 这是 Token Plan 订阅专用的 Key | `sk-sp-` 开头 | 在同一页面创建按量付费 Key |
| 账户还没完成认证或充值 | 新用户体验额度用完 | 在控制台完成实名认证并充值 |
| 免费额度已用完，且开着“免费额度用完即停” | 官方说明：开着这个开关时免费额度用完即停止 | 要继续付费使用就关掉该开关；不想付费就停在这里 |
| 账户欠费或余额不足 | `Arrearage` | 到账单页充值 |
| 请求太频繁 | `Throttling` | 稍等再试 |
| 音频上传方式 ✗“还没有设置音频交给服务商的方式” | 没填 OSS，也没选临时上传 | 按第 4 步设置 OSS；或改用 MOSS Pro 云端 |
| 服务端没能读取音频 | 签名链接读不到（Bucket 白名单）或临时上传已过期 | 先“检查 OSS”；再在完成页重试（会重新上传） |
| 连不上 maas.qianwenaiapi.com | 网络或代理 | 检查网络或代理设置 |

## 识别时会发生什么

- 音频（16 kHz 单声道 WAV，只有声音）→ 你的 OSS → 限时签名链接 → 提交异步任务 → **立即保存任务编号** → 定时查询 → 下载结果 → 写入工程 → 删除 OSS 临时音频。
- 断网后重新识别：先查询原任务，**不会**自动重新提交、不会重复收费。只有排队中（PENDING）的任务能在云端取消；已在执行的任务，按“取消”只停止本机等待，服务端仍可能完成并计费，兔白会如实显示。
- 服务端返回的多字词（如“阿里云”）作为一个实测单位保存，剃刀不会在词中间按估算时间切。

## 隐私与费用

- 会上传：本次识别范围的音频。不会上传：画面、工程、其他素材。
- API Key、AccessKey 只存本机（Windows DPAPI 加密；Mac 钥匙串，不可用时只留本次会话、不写明文）。
- 兔白本身免费；千问AI平台与 OSS 都是第三方付费服务。

## 来源（2026-10-25 核对）

- 语音识别模型、音频输入方式与限制：<https://platform.qianwenai.com/docs/developer-guides/speech/speech-to-text-models>
- 获取 API Key（Key 类型、只显示一次）：<https://platform.qianwenai.com/docs/api-reference/preparation/api-key>
- 录音文件识别 HTTP API（提交与查询地址、临时 URL 48 小时、结果存放在北京）：<https://platform.qianwenai.com/docs/api-reference/speech-recognition/fun-asr-recording/restful-api>
- 错误码（欠费、认证与充值、免费额度用完即停）：<https://platform.qianwenai.com/docs/api-reference/preparation/error-messages>
- 新用户体验额度：<https://www.qianwenai.com/benefits>
- 价格：<https://platform.qianwenai.com/pricing/api>
- 临时上传的官方限制：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- OSS / RAM：<https://help.aliyun.com/zh/oss/user-guide/create-a-bucket-4>、<https://help.aliyun.com/zh/ram/user-guide/create-a-ram-user>
