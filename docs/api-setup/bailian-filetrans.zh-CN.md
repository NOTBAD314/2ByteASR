# 申请与设置 阿里云百炼 · 录音文件识别（Qwen3-ASR / Qwen-Audio-3.1）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录控制台才能确认。

## 一眼看懂

| 项目 | 内容 |
| --- | --- |
| 在兔白里做什么 | 云端识别长录音（单个文件 ≤12 小时、≤2 GB），不需要显卡或本地模型 |
| 两个模型（同一把 Key） | **Qwen3-ASR-Flash**：字/词级时间，不分说话人，不支持热词。**Qwen-Audio-3.1-ASR-Flash**：字/词级时间 + 说话人（官方建议 2 小时内），支持热词与上下文 |
| 需要什么 | 阿里云账号、百炼 API Key + API Host，**以及你自己的 OSS 私有存储**（设置一次） |
| 为什么要 OSS | 这个接口不收本地文件，只收“服务商能读到的音频网址”。兔白把音频放进你的私有 Bucket，生成限时签名链接交给百炼，取得结果后删除 |
| 不想碰 OSS | 改用“MOSS Pro 云端（MOSI）”：只要一把 Key，直接上传本地音频（只有句段时间，有说话人） |
| 费用 | 百炼按音频时长计费（“试识别一小段”时显示官方模型列表接口返回的单价）；OSS 另有很少的存储与流量费用 |

> **关于“服务商临时上传”**：百炼有一个临时上传功能，兔白可以用它“先试试看”，但官方原文写明“临时 URL 有效期48小时，过期后无法使用，请勿用于生产环境”，上传凭证接口“限流为 100 QPS 且不支持扩容”。所以兔白不把它当正式方式，也不会自动替你选；只有你在“音频交给百炼的方式”里明确选“服务商临时上传（仅供试用）”才会使用。

## 第一部分：百炼 API Key 与 API Host

1. **注册并登录**阿里云：<https://account.aliyun.com/register/qr_register.htm>（已有账号直接登录）。
2. 打开百炼控制台 <https://bailian.console.aliyun.com/>，右上角选地域（建议“华北2（北京）”），按页面提示同意协议、开通服务。**密钥、API Host、模型按地域区分，不能跨地域混用。**
3. **实名认证**：官方说明领取和使用新人免费额度不需要实名；免费额度用完后继续按量付费**必须实名**（未实名会报 `AllocationQuota.FreeTierOnly`）。
4. **创建 API Key**：北京地域的 API Key 页面 <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key>。已有可用的 Key 就直接复制；要新建就点“创建 API Key”，归属业务空间可用默认业务空间，再点 Key 旁的复制图标。
5. **复制 API Host**：创建 Key 后的弹窗里，或“业务空间管理”页的 API Host 列，形如 `llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com`（弹窗与列的确切位置以控制台为准：**待核实**）。

## 第二部分：自己的 OSS 私有存储（正式使用，只做一次）

1. **建 Bucket**：OSS 控制台 <https://oss.console.aliyun.com/> →“Bucket 列表”→“创建 Bucket”。名称例如 `2byte-asr-temp`，地域例如华东1（杭州）。**保持“私有”，不要改成公共读**（官方默认就是私有并开启“阻止公共访问”）。名称和地域建好后不能改。
2. **自动清理（建议）**：该 Bucket 的“数据管理”→“生命周期”→“创建规则”：按前缀 `asr-temp/`，指定天数 `1`，动作“数据删除”。兔白识别成功后本来就会删除，这条规则保证意外中断留下的文件也会被清掉。
3. **建一个只管这个目录的子账号**：RAM 访问控制 <https://ram.console.aliyun.com/> → 身份管理 → 用户 → 创建用户，访问方式选“使用永久 AccessKey 访问”。**AccessKey Secret 只在创建时显示一次**，立刻保存。**不要用主账号 AccessKey；百炼 API Key 不能代替它。**
4. **只给最小权限**：在 RAM 里新建“自定义权限策略”，内容如下（把 `你的Bucket名` 换成第 1 步的名称），授权给这个子用户。这是按官方规则改写的示例，不是官方原文：

   ```json
   {"Version": "1", "Statement": [
     {"Effect": "Allow", "Action": ["oss:PutObject", "oss:GetObject", "oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:你的Bucket名/asr-temp/*"]},
     {"Effect": "Allow", "Action": ["oss:ListObjects"], "Resource": ["acs:oss:*:*:你的Bucket名"],
      "Condition": {"StringLike": {"oss:Prefix": ["asr-temp/*"]}}}
   ]}
   ```

   兔白只用这四个动作：上传本次音频、生成签名链接并自检、识别后删除、清理 48 小时前残留的临时文件。

## 第三部分：贴回兔白

首页右上角“说明”→“申请与设置 API…”→ 左侧选“阿里云百炼 · 录音文件识别”。上方步骤卡依次是：注册并登录 › 创建 API Key › 建私有 OSS 与 AccessKey › 贴到下面 › 检查并保存，每张卡的“打开网页”直接打开对应的官方页面。

| 栏位 | 填什么 | 从哪里来 | 已预填？ |
| --- | --- | --- | --- |
| 模型 | 两选一（见上表） | — | 已预选 Qwen3-ASR（之前用 3.1 的保留 3.1） |
| API Host | `llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com` | 第一部分第 5 步 | 否。整段网址（含 `https://`、`/api/v1`，甚至聊天用的 `/compatible-mode/v1`）也可以，会自动换算 |
| API Key | `sk-…` | 第一部分第 4 步 | 否 |
| 音频交给百炼的方式 | “我自己的阿里云 OSS 私有存储（正式使用）” | — | **已预选 OSS** |
| OSS 地域 | 例如 `cn-hangzhou` | 第二部分第 1 步 | 下拉选择 |
| OSS Bucket 名称 | 例如 `2byte-asr-temp` | 第二部分第 1 步 | 否 |
| 临时目录（灰色） | `asr-temp/` | — | **已预填，不用改** |
| AccessKey ID / Secret | `LTAI…` / 一串字符 | 第二部分第 3 步 | 否 |
| 识别成功后自动删除 OSS 临时音频 | 勾选 | — | **默认勾选** |

“将使用”一行显示地域和 Base URL；把鼠标停在上面能看到四种地址分开列出（官方网站 `https://bailian.console.aliyun.com/`、API Host、Base URL `https://llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com/api/v1`、完整请求 Endpoint `…/api/v1/services/audio/asr/transcription`，查询任务用 `…/api/v1/tasks/{task_id}`），不用你判断要不要加 `/v1`。旧设置里的 `https://dashscope.aliyuncs.com/…`（旧共用域名）照样能用，兔白会提示官方建议换成工作空间专属的 API Host。

## 测试会看到什么

1. **免费检查（不上传音频）**：本机检查格式 → 调官方“查询模型列表”接口。成功时：设置格式 ✓、服务可以连线 ✓、认证成功（API Key 有效）✓、指定模型可用 ✓。
2. **检查 OSS（上传很小的测试文件后删除）**：上传十几个字节的测试文件，生成签名链接、读回、删除。成功时“音频上传方式 ✓ 可以上传、生成签名链接并删除测试对象”。
3. **试识别一小段…**：先确认上传对象与可能费用，再上传约 6 秒的兔白自带英文合成语音（或你选的 60 秒以内音频）。成功时：实际短音频识别 ✓、回传时间戳 ✓（字/词级）。Qwen3-ASR 的“回传说话人”显示“—”，这是模型能力限制，不是错误。

只有第 3 步成功，才说明真的能用。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 认证失败（401 `InvalidApiKey`） | 复制不完整，或 Key 与 API Host 不是同一地域 | 在同一地域重新复制 Key 和 API Host，再做免费检查 |
| 403 `AccessDenied.Unpurchased` | 还没开通百炼 | 回第一部分第 2 步开通 |
| 403 `AllocationQuota.FreeTierOnly` | 免费额度用完且未实名 | 完成实名认证并开通按量付费 |
| 400 `Arrearage` | 欠费 | 充值后重试 |
| 429 `Throttling…` | 限流 | 等几分钟再试 |
| 模型列表里没有该模型 | 地域不提供，或模型名不对 | 换北京地域的 API Host，或核对模型名 |
| 音频上传方式 ✗“还没有设置音频交给服务商的方式” | 没填 OSS，也没选临时上传 | 按第二部分设置 OSS；或改用 MOSS Pro 云端 |
| 检查 OSS 失败 | AccessKey 错、权限策略没授权、Bucket 名或地域不对 | 重做第二部分第 3、4 步，确认地域选对 |
| 任务失败 `FILE_403_FORBIDDEN` | 百炼读不到音频链接 | 先“检查 OSS”；Bucket 不要设白名单拦截 |
| “查不到这个任务” | 任务记录超过官方保留的 24 小时 | 在完成页重试（会重新计费，需要你确认） |

## 识别时会发生什么

- 兔白把本次识别范围转成 16 kHz 单声道 WAV（只有声音）→ 上传到你的 OSS → 生成 24 小时签名链接 → 提交异步任务 → **立即保存任务编号** → 定时查询 → 下载结果文件（结果链接 24 小时有效）→ 解析时间戳写入工程 → 删除 OSS 临时音频。
- 断网后重新识别：先查询原任务，**不会**重新上传收费。提交时断网、无法确认是否受理：停下并请你核对，**不会**自动重提。
- 取消：只有排队中（PENDING）的任务能在云端取消；已在识别中的任务取消后仍可能计费，兔白会如实提示。
- 时间：服务端返回的词可能是多个字（如“阿里云”）。兔白把每个词当成一个实测单位保存，剃刀不会在词中间按估算时间切；词内的逐字显示只是均分的显示效果。
- 术语库：Qwen-Audio-3.1 会把规范词作为热词与上下文提示发送（保持原写法）；Qwen3-ASR 官方不支持热词，不发送。热词只是提示，识别后的词库校对照常进行。
- 选了“服务商临时上传（仅供试用）”时：音频上传到百炼临时空间（48 小时后由百炼删除），上传后超过约 40 小时还没提交的会重新上传。

## 隐私与费用

- 会上传：本次识别范围的音频（先到你的 OSS，再由百炼读取）。不会上传：画面、工程、其他素材。
- 费用：百炼按音频时长计费；新用户在北京地域有免费额度（具体额度以控制台为准：**待核实**）。OSS 标准存储约 0.12 元/GB/月（本地冗余），外网流出流量闲时 0.25 元/GB、忙时 0.50 元/GB（中国内地按量价，2026-10-13 核对）；1 小时 16 kHz 单声道 WAV 约 115 MB，识别后即删除。百炼读取 OSS 是否按外网流出计费：官方未写明，**待核实**。
- 密钥与 AccessKey 只保存在本机（Windows DPAPI 加密；Mac 钥匙串，不可用时只留本次会话、不写明文），不写进工程、日志或导出文件。

## 来源（2026-10-14 核对）

- 临时上传的官方限制（48 小时、勿用于生产、100 QPS）：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- Qwen-ASR API（Filetrans 提交 / 查询、`enable_words`、结果字段）：<https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference>
- 模型与能力（12 小时 / 2 GB、说话人、热词、公网 URL 输入）：<https://help.aliyun.com/zh/model-studio/asr-model>
- 地域与域名：<https://help.aliyun.com/zh/model-studio/regions>
- 获取 API Key：<https://help.aliyun.com/zh/model-studio/get-api-key>
- 录音文件识别说明：<https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide>
- 新人免费额度与实名：<https://help.aliyun.com/zh/model-studio/new-free-quota>
- 查询模型列表：<https://help.aliyun.com/zh/model-studio/list-models>
- 错误码：<https://help.aliyun.com/zh/model-studio/error-code>
- OSS 创建 Bucket：<https://help.aliyun.com/zh/oss/user-guide/create-a-bucket-4>
- RAM 用户 / AccessKey：<https://help.aliyun.com/zh/ram/user-guide/create-a-ram-user>、<https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair>
- OSS 权限策略示例：<https://help.aliyun.com/zh/oss/user-guide/common-examples-of-ram-policies>
- 生命周期规则：<https://help.aliyun.com/zh/oss/user-guide/lifecycle-rules-based-on-the-last-modified-time>
- OSS 价格：<https://www.aliyun.com/price/detail/oss>
