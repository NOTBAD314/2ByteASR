# 申请与设置 Qwen Cloud（Qwen 官方国际站）· 录音文件识别

最后核对：2026-10-14（中国站说明 2026-10-25 补充）。来源见文末。标“待核实”的地方需要登录控制台才能确认，兔白所在电脑没有 Qwen Cloud 账号。2026-10-28 起音频默认交给服务商临时空间，不用建 OSS（临时上传的官方说明当天重新核对）。

## 一眼看懂

| 项目 | 内容 |
| --- | --- |
| 在兔白里做什么 | 云端识别长录音（单个文件 ≤12 小时、≤2 GB），不需要显卡或本地模型。服务在新加坡 |
| 两个模型（同一把 Key） | **Qwen-Audio-3.1-ASR-Flash**（推荐）：字/词级时间 + 说话人（官方建议 2 小时内），支持热词与上下文。**Qwen3-ASR-Flash**：字/词级时间，不分说话人，不支持热词 |
| 需要什么 | Qwen Cloud 账号 + 补全付款信息 + 按量付费 API Key。**不用建 OSS** |
| 音频怎么交给服务商 | 这个接口只收“服务端读得到的音频网址”（官方：Publicly accessible file URL, 1 per request）。兔白默认先把本次音频传到 Qwen Cloud 提供的免费临时空间（48 小时后失效、不能续期），再把 `oss://` 临时地址交给服务商识别。单个文件的大小上限按模型不同，超过会在上传时报错 |
| 想自己保管音频 | 可以改选“我自己的阿里云 OSS 私有存储”（见“可选：改用自己的 OSS”）：音频放进你的私有 Bucket，用限时签名链接交给服务商，取得结果后删除 |
| 费用 | 按音频用量计费，以 Qwen Cloud 账单为准；补全付款信息后每个模型有 90 天免费额度（2026-10-13 核对）；用自己的 OSS 时另有很少的存储与流量费用 |

> **关于服务商临时空间**：Qwen Cloud 和百炼共用一套临时上传机制。官方写明临时地址 48 小时有效，上传凭证接口每个账号每个模型限 100 QPS，并说“Do not use it in production”（阿里云中文说明：“请勿用于生产环境”）。它不适合的是服务器那种高并发、批量的生产处理；兔白每个识别任务只上传一个文件、上传后马上提交。经常大量识别、想自己保管音频，或者临时空间上传一直失败，可以改用自己的 OSS。

### 先分清几个入口

Qwen 官方 API 有两个站：中国站“千问AI平台”（platform.qianwenai.com，服务在北京）和国际站 Qwen Cloud（本页）。兔白里是同一项，“申请与设置 API…”窗口顶部可以切换“中国站（千问AI平台）/ 国际站（Qwen Cloud）”；简体中文界面默认中国站，大陆用户一般选中国站，教程见“千问AI平台 · 录音文件识别”。

| 入口 | 能不能给兔白识别字幕 |
| --- | --- |
| Qwen 官网聊天（qwen.ai / chat.qwen.ai） | **不能**。聊天登录只用于网页聊天，没有给第三方软件的授权方式 |
| **Qwen Cloud（本页，home.qwencloud.com）** | **能**。用按量付费 API Key，不需要 Workspace ID |
| 千问AI平台（中国站，platform.qianwenai.com） | 能，在同一窗口切到“中国站”。Key 与 Qwen Cloud **不能互换** |
| 阿里云百炼（中国站） | 能，见“阿里云百炼 · 录音文件识别”。Key 与 Qwen Cloud **不能互换** |

## 跟着做

1. **注册并登录**：<https://home.qwencloud.com/>（登录用阿里云国际账号）。
2. **补全付款信息**：<https://home.qwencloud.com/billing/overview?target=payment>。官方说明补全后才解锁新用户免费额度；没补全时调用会报“Access to model denied”。可在 <https://home.qwencloud.com/benefits> 打开“仅使用免费额度”开关：免费额度用完会直接停止，不扣钱。
3. **创建 API Key**：<https://home.qwencloud.com/api-keys> → “Create API key” → 填描述（例如“兔白字幕”）→ “Generate Key”，**立刻复制**（官方：完整 Key 只显示一次）。官方文档写按量付费 Key 形如 `sk-xxxxx`（控制台是否显示为 `sk-ws-` 开头：**待核实**）。**不要用 Token Plan 订阅 Key（`sk-sp-` 开头）**，它不能做录音文件识别。
4. **贴到兔白**：首页右上角“说明”→“申请与设置 API…”→ 右上角“换一家”选“Qwen Cloud 录音文件识别”，确认顶部选的是“国际站（Qwen Cloud）”。窗口一步一页：注册登录 › 付款信息 › 创建 Key › 贴上检查，每一步的按钮直接打开对应页面。
5. **检查**：点“免费检查”（不上传音频）；想确认真的能识别，再点“试识别一小段…”。
6. 点“**保存并用于识别**”。

### 可选：改用自己的 OSS

想自己保管音频、经常大量识别，或者临时空间上传一直失败时再做，只做一次：

- 已经为“阿里云百炼 · 录音文件识别”设置过 OSS 的，**直接共用**。
- 没有的话，任选一个阿里云 OSS：国际站控制台 <https://oss.console.alibabacloud.com/>（与 Qwen Cloud 同一国际账号能否直接开通 OSS：**待核实**），或中国站控制台 <https://oss.console.aliyun.com/>。地域建议选新加坡（`ap-southeast-1`），离服务近。
- 建私有 Bucket、建只管 `asr-temp/` 目录的 RAM 子用户与 AccessKey、加最小权限策略与生命周期清理，步骤和权限策略与百炼教程“第四部分”完全相同（国际站 RAM 控制台 <https://ram.console.alibabacloud.com/>）。
- 在“贴上检查”页把“音频交给服务商的方式”改成“我自己的阿里云 OSS 私有存储”：窗口多出“建 OSS”一步和 OSS 几栏，填好后再点“检查 OSS（上传很小的测试文件后删除）”。

## 兔白里的每一栏

| 栏位 | 填什么 | 已预填？ |
| --- | --- | --- |
| 模型 | 两选一（见上表） | 已预选 Qwen-Audio-3.1 |
| API Key | 第 3 步复制的 Key | 否 |
| 服务地址（灰色，按“修改”才能改） | `https://maas.qwencloudapi.com` | **已预填，不用改**；官方命令行工具使用的 `https://dashscope-intl.aliyuncs.com` 也可以 |
| 音频交给服务商的方式 | “服务商临时空间（默认，不用建 OSS）” | **已预选临时空间**；之前设好自己 OSS 的保留 OSS |
| OSS 地域 / Bucket 名称 / AccessKey ID / Secret（选了自己的 OSS 才出现） | “可选：改用自己的 OSS”的结果 | 否（与百炼共用同一组设置） |
| 临时目录（灰色，选了自己的 OSS 才出现） | `asr-temp/` | **已预填** |

服务地址不用你判断：官方网站 `https://home.qwencloud.com/`、API Host `maas.qwencloudapi.com`、Base URL `https://maas.qwencloudapi.com/api/v1`、完整请求 Endpoint `https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription`（按“修改”后可在“将使用”一行和它的提示里看到）。

## 测试会看到什么

| 结果行 | 成功时 | 会不会上传 / 收费 |
| --- | --- | --- |
| 设置格式 | ✓（Key 没有空格、不是 Token Plan Key、地址是 https） | 只在本机检查 |
| 服务可以连线 / 认证成功（API Key 有效） | ✓ | 不上传、不收费 |
| 指定模型可用 | 常显示“?”：这个接口的模型列表不列出录音文件识别模型，以实际识别为准 | 不上传、不收费 |
| 音频上传方式 | ✓ 服务商同意为这个模型发放临时上传凭证（没有上传任何文件）；选了自己的 OSS 时按“检查 OSS”：可以上传、生成签名链接并删除测试对象 | 临时空间：不上传；自己的 OSS：只上传十几个字节的测试文件 |
| 实际短音频识别 / 回传时间戳 / 回传说话人 | ✓ 识别出文字、有字/词级时间；单人测试音频的说话人常显示“—” | **上传测试音频，可能收费** |

## 常见失败与下一步

| 现象 | 原因 | 下一步 |
| --- | --- | --- |
| 服务商不认这把 API Key | 复制不完整、多了空格、Key 已删除，或用了千问AI平台 / 百炼的 Key | 回 API Key 页面重新创建并复制；用千问AI平台的 Key 就把窗口顶部切到“中国站” |
| 这是 Token Plan 订阅专用的 Key | `sk-sp-` 开头 | 在同一页面创建按量付费 Key |
| 账户还没补全付款信息 | `AccessDenied.Unpurchased` | 到账单页补全付款信息 |
| 免费额度已用完，且开着“仅使用免费额度” | `AllocationQuota.FreeTierOnly` | 要继续付费使用就关掉该开关；不想付费就停在这里 |
| 账户欠费或余额不足 | `Arrearage` | 到账单页处理 |
| 这把 Key 没有调用模型的权限 | 子业务空间没授权这个模型 | 给子业务空间授权，或用默认业务空间的 Key |
| 请求太频繁 | `Throttling` | 稍等再试 |
| 音频上传方式 ✗（临时上传凭证被拒、上传到临时空间失败） | Key 或模型不对、网络中断 | 先确认前几项都 ✓，检查网络后再试；一直失败可以改用自己的 OSS |
| 音频上传方式 ✗“OSS 设置不完整” | 填了 Bucket，但 AccessKey 没保存 | 补全 AccessKey；或把“音频交给服务商的方式”改回“服务商临时空间” |
| 服务端没能读取音频 | 签名链接读不到（Bucket 白名单）或临时地址已过期 | 用自己的 OSS 时先“检查 OSS”；再在完成页重试（会重新上传） |
| 连不上 maas.qwencloudapi.com | 网络或代理 | 检查网络；大陆网络连新加坡可能需要稳定的国际线路 |

## 识别时会发生什么

- 默认：音频（16 kHz 单声道 WAV，只有声音）→ 向服务商申请这个模型的临时上传凭证 → 上传到服务商临时空间 → 用 `oss://` 临时地址提交异步任务 → **立即保存任务编号** → 定时查询 → 下载结果 → 写入工程。临时空间里的音频 48 小时后由服务商清理；上传后超过约 40 小时还没提交的会重新上传。
- 选了自己的 OSS：音频 → 你的 OSS → 限时签名链接 → 提交 → 保存任务编号 → 查询 → 下载结果 → 写入工程 → 删除 OSS 临时音频。
- 断网后重新识别：先查询原任务，**不会**自动重新提交、不会重复收费。只有排队中（PENDING）的任务能在云端取消；已在执行的任务，按“取消”只停止本机等待，服务端仍可能完成并计费，兔白会如实显示。
- 服务端返回的多字词（如“阿里云”）作为一个实测单位保存，剃刀不会在词中间按估算时间切。

## 隐私与费用

- 会上传：本次识别范围的音频（默认到服务商临时空间，48 小时后清理；选了自己的 OSS 时先到你的 OSS）。不会上传：画面、工程、其他素材。
- API Key、AccessKey 只存本机（Windows DPAPI 加密；Mac 钥匙串，不可用时只留本次会话、不写明文）。
- 兔白本身免费；Qwen Cloud 是第三方付费服务，临时空间官方说明是免费的；用自己的 OSS 时 OSS 另计费。

## 来源（2026-10-14 核对；临时上传两页 2026-10-28 重新核对）

- 语音识别模型、音频输入方式与限制：<https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models>
- 获取 API Key（Key 类型、只显示一次）：<https://docs.qwencloud.com/api-reference/preparation/api-key>
- 录音文件识别 HTTP API：<https://docs.qwencloud.com/api-reference/speech-recognition/fun-asr-recording/restful-api>
- 业务空间：<https://docs.qwencloud.com/developer-guides/administration/workspace>
- 新用户免费额度：<https://docs.qwencloud.com/resources/free-quota>
- 错误码：<https://docs.qwencloud.com/api-reference/preparation/error-messages>
- 异步任务查询与取消：<https://docs.qwencloud.com/api-reference/more/manage-asynchronous-tasks>
- 临时上传（Temporary file URL：免费、48 小时、100 QPS、上传与调用须是同一模型、“Do not use it in production”）：<https://docs.qwencloud.com/api-reference/more/upload-file-get-temporary-url>
- 临时上传的阿里云中文说明（“请勿用于生产环境”）：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- 国际站 OSS / RAM：<https://www.alibabacloud.com/help/en/oss/user-guide/create-a-bucket-4>、<https://www.alibabacloud.com/help/en/ram/user-guide/create-a-ram-user>、<https://www.alibabacloud.com/help/en/oss/user-guide/common-examples-of-ram-policies>、<https://www.alibabacloud.com/help/en/oss/user-guide/lifecycle-rules-based-on-the-last-modified-time>、<https://www.alibabacloud.com/help/en/oss/pricing-overview>
