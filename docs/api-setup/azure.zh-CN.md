# Azure OpenAI 部署式转写（进阶，不建议一般使用者）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先说结论

- **一般使用者请不要选这一项**，改用列表里的官方云端服务（MOSS Pro 云端、阿里云百炼、Qwen Cloud 等）或本地模型。
- 兔白把这一项标成“MAI 2.1”，**这与微软现状不符**：微软官方页面列出的转写模型是 MAI-Transcribe-2 和 MAI-Transcribe-1.5（MAI-Transcribe-1 已于 2026-08-20 弃用），没有 MAI-Transcribe-2.1；名字带 2.1 的 MAI-Voice-2.1 是“文字变语音”的模型。
- MAI-Transcribe 走的是 Azure Speech 的另一种接口，**不需要、也不能“部署”**。兔白这一项调用的是 **Azure OpenAI 的“部署式”转写接口**，只能用你在 Azure 部署的 OpenAI 转写模型（例如 `whisper`）。所以，**兔白目前不能通过这一项使用 MAI-Transcribe**。
- 如果你已经有 Azure OpenAI 资源并部署了 whisper，可以试：预计只有句段时间，没有逐字时间和说话人。兔白未实测。
- 兔白验证状态：已有接入；本轮未用真实密钥重新实测。

## 它在兔白里做什么

语音识别（生成字幕）。兔白按人声把音频切成小段（主力转写每段约 10 秒以内，文字复核约 25 秒以内），逐段上传到你自己的 Azure OpenAI 资源，取回文字和句段时间。

## 官方链接

| 用途 | 地址 | 需要登录 |
| --- | --- | --- |
| 注册 Azure（免费账户说明） | <https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account> | 否 |
| Azure 门户（建资源、看 Key 与 Endpoint） | <https://portal.azure.com/> | 是（待核实） |
| Microsoft Foundry 门户（部署模型） | <https://ai.azure.com/> | 是（待核实） |
| 建资源与部署模型（官方教程，经典版） | <https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource> | 否 |
| 转写快速入门（地址格式、Key 位置） | <https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart> | 否 |
| 转写接口说明（2024-10-21 版） | <https://learn.microsoft.com/en-us/azure/foundry/openai/reference> | 否 |
| 可部署的转写模型 | <https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?tabs=standard-audio> | 否 |
| 各区域能部署哪些模型 | <https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability> | 否 |
| 价格 | <https://azure.microsoft.com/en-us/pricing/details/azure-openai/> | 否 |
| MAI-Transcribe（兔白目前不能调用） | <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe> | 否 |

窗口顶部如果没有“打开网页”按钮，直接用上表的链接。

## 从未注册开始

以下按钮名称来自微软官方教程（英文界面）；门户实际画面需要登录才能看到（待核实），新版 Foundry 门户的菜单可能不同。

1. **注册 Azure 账号。** 免费账户页写明：需要微软或 GitHub 账号、手机号码、信用卡或借记卡（不能用预付卡），注册时可能有约 1 美元的临时授权，之后撤销。免费账户含 30 天内可用的 200 美元额度，之后要转成按量付费才能继续用。这笔额度能否用于 Azure OpenAI，页面没有写明。
2. **建 Azure OpenAI 资源。** 在 Azure 门户选 **Create a resource**，搜索 **Azure OpenAI** →**Create**。在 **Basics** 填 Subscription、Resource group、Region、Name、Pricing Tier（目前只有 Standard）。网络选项保留默认（所有网络可访问）即可。最后 **Review + submit** →**Create**。Region 要选能部署你想用的模型的区域（看“各区域能部署哪些模型”，whisper 只在部分区域提供）。
3. **部署转写模型。** 在 Microsoft Foundry 门户找到你的资源，进 **Deployments** →**+ Deploy model** →**Deploy base model**，选模型（建议 `whisper`），在 **Deployment name** 填一个名字（例如 `my-whisper`，区分大小写，之后要用）→**Deploy**。状态变成 *Succeeded* 才算完成。
4. **取得 Endpoint 和 Key。** 在 Azure 门户打开这个资源，**Resource Management** 下的 **Keys & Endpoint**：Endpoint 形如 `https://<资源名>.openai.azure.com/`，Key 用 KEY1 或 KEY2 都可以。
5. **拼出兔白要的“部署地址”**（见下一节）。

## 需不需要开通服务、绑卡、额外储存

- 需要：Azure 订阅（要绑卡）、一个 Azure OpenAI 资源、一个转写模型部署。
- 不需要 OSS 或 Azure 储存：音频直接放在请求里。微软写明单个音频文件上限 25 MB；兔白每段约 10 秒，远小于上限。

## 兔白里的栏位

打开「申请与设置 API」（首页右上角“说明”菜单 →“申请与设置 API…”），在左侧列表点“显示进阶选项（自架接口、待验证服务）”，再选 Azure 那一项（标有“进阶”）。“填写”区有三栏，都没有预填：

| 栏位 | 用途 | 例子 | 从哪里拿 |
| --- | --- | --- | --- |
| 部署地址 | 兔白实际发请求的完整地址，必须带 `api-version` | `https://myres.openai.azure.com/openai/deployments/my-whisper/audio/transcriptions?api-version=2024-10-21` | 用 Endpoint 和部署名称拼出来（见下表） |
| API Key | 资源的密钥 | 整串贴上，前后不要有空格 | Azure 门户 **Keys & Endpoint** 的 KEY1 或 KEY2 |
| 部署名称 | 显示用，兔白要求不能空；兔白不会把它放进请求，实际调用哪个部署只看“部署地址” | `my-whisper` | 部署时自己取的 **Deployment name** |

地址怎么分：

| 名称 | 例子 | 说明 |
| --- | --- | --- |
| 官方网站 | `https://portal.azure.com/` | 只用来登录管理，不要填进兔白 |
| 资源 Endpoint（相当于 Base URL） | `https://myres.openai.azure.com/` | 门户里显示的 Endpoint，不能直接填进兔白 |
| 完整请求 Endpoint（兔白的“部署地址”） | `https://myres.openai.azure.com/openai/deployments/my-whisper/audio/transcriptions?api-version=2024-10-21` | 资源 Endpoint + `openai/deployments/` + 部署名称 + `/audio/transcriptions?api-version=2024-10-21` |

- 兔白不会帮你补任何路径，也不会自动加 `/v1`。
- 门户显示的 Endpoint 如果不是 `openai.azure.com` 结尾，照门户显示的域名拼即可；其他域名格式兔白未实测。
- Azure 新版 v1 地址（`/openai/v1/audio/transcriptions`）不适合这一项：v1 要在请求里写部署名，而兔白这一项不发送（兔白未实测）。

## 已预填、不用改

- 三栏都要自己填。
- 兔白会自动要求带句段时间的回传格式（`verbose_json`），服务拒绝时自动改用普通格式（`json`）。

## 测试：成功时会看到什么

1. 点“免费检查（不上传音频）”：只在本机核对格式。设置格式 ✓；认证成功（API Key 有效）显示 ?：“这个服务没有可用的免费检查；请用“实际短音频识别”确认。”这是正常的，Key 是否有效要看下一步。
2. 点“试识别一小段…”。确认框会写明上传到你的资源域名（例如 `myres.openai.azure.com`），费用“无法事先估算”。选“上传自带测试音频”（约 6 秒英文合成语音，不含你的素材）或“选择我的音频…”（60 秒以内）。部署 whisper 时预计看到：
   - 实际短音频识别 ✓“识别出 N 段文字。”
   - 回传时间戳 ?“只有句段起止时间，没有逐字时间；需要精细剪辑时请再配本地对齐。”
   - 回传说话人 —“这次结果没有说话人标签……”
3. 结果满意再点“保存”或“保存并用于识别”。

## 能拿到什么（时间、说话人）

| 部署的模型 | 时间 | 说话人 |
| --- | --- | --- |
| `whisper` | 句段时间（兔白不请求逐词时间） | 无（微软写明 Azure OpenAI 转写模型不支持说话人区分） |
| `gpt-transcribe`、`gpt-4o-transcribe`、`gpt-4o-mini-transcribe` | 是否接受带时间的回传格式，官方文件未写明，兔白未实测；若被拒，兔白退回只要文字，每段（约 10 秒）只有一个起止时间 | 无 |
| `gpt-4o-transcribe-diarize` | 兔白未实测 | 兔白不请求这个模型的说话人格式，拿不到 |

需要逐字时间或说话人，请改用阿里云百炼或 Qwen Cloud 的录音文件识别。

## 费用

- Azure 按部署的模型计费，以 Azure 账单为准。
- 2026-10-14 打开 Azure OpenAI 价格页，转写模型的单价都显示为“$-”（页面没有直接显示数字），**本次未能确定单价**。请在浏览器打开价格页查看，或用 Azure 价格计算器。
- 免费账户的 200 美元额度 30 天内有效，能否抵扣 Azure OpenAI 未写明。

## 隐私：会传送什么

- 每段音频（16 kHz 单声道 WAV，只有声音，不含画面）和一段提示文字 → 你自己的 Azure 资源。提示文字包括字幕场景、**素材文件名**和你确认过的专名写法，最多 900 字。
- API Key 加密保存在本机（Windows 用 DPAPI；macOS 用钥匙串，钥匙串不可用时只在本次运行期间保存，不写成明文），不写进工程、日志或导出文件。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 提示“ASR API 缺少模型名称。” | 部署名称空着 | 填部署时取的 Deployment name |
| 设置格式 ✗“服务地址无效：需要 https 开头的完整地址。” | 只填了资源名，或不是 https 开头 | 按上面的格式填完整部署地址 |
| HTTP 401 | Key 错，或 Key 与部署地址不属于同一个资源 | 回 **Keys & Endpoint** 重新复制 KEY1；确认部署地址里的资源名就是这个资源 |
| HTTP 404 / 找不到部署 | 部署名称拼错（区分大小写），或部署还没完成 | 对照 Foundry 门户 **Deployments** 里的名字；等状态变成 *Succeeded* |
| HTTP 400，提到 api-version | 地址缺 `api-version` 或版本不支持 | 地址末尾用 `?api-version=2024-10-21` |
| 其他 HTTP 400 | 部署的模型不接受兔白的请求（兔白已自动退回仍失败） | 改部署 `whisper` 再试 |
| HTTP 429 | 超过这个部署的速率配额 | 兔白会自动等待重试；仍失败就在 Azure 调高该部署的配额（具体位置需登录，待核实） |
| 回传时间戳 显示 ? | whisper 只给句段时间，或模型没给时间 | 需要逐字时间就改用百炼或 Qwen Cloud 录音文件识别 |
| 想用 MAI-Transcribe，填 Speech 地址后失败 | 兔白这一项不支持 Azure Speech 的接口 | 目前无法在兔白使用 MAI-Transcribe；改用其他服务 |

## 进阶（一般使用者可跳过）

- 兔白的请求：`POST` 到“部署地址”，头 `api-key: <Key>`，表单上传（multipart）`file`（chunk.wav）、`prompt`（最多 900 字）、`response_format=verbose_json`（HTTP 400 时改 `json` 再试一次）。不发送 `model`、`timestamp_granularities`、`language`。遇到 429 / 5xx 会等待后重试，同一段最多尝试 6 次。
- MAI-Transcribe 的官方接口（兔白尚未支持）：`POST https://<资源名>.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15`，头 `Ocp-Apim-Subscription-Key`，表单 `audio` + `definition`（`enhancedMode.enabled: true`、`enhancedMode.model: "MAI-Transcribe-2"`；可选 `diarization.enabled`、`modelOptions.timestamps` 取 `word` / `segment` / `none`（默认 `none`）、`modelOptions.transcribeStyle`、`phraseList.phrases`、`locales`）。前提是 Azure 订阅加一个 Microsoft Foundry 的 Speech 资源。目前是公开预览，没有 SLA，官方不建议用于生产。
- 程序位置：请求在 `twobyteasr/asr.py` 的 `call_qwen_asr_api`（`azure_transcription` 分支）；地址允许带 `?api-version=` 的规则在 `twobyteasr/llm_config.py` 的 `validate_qwen_asr_endpoint`。

## 来源（2026-10-14 核对）

- MAI-Transcribe（Azure Speech）：<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe>
- OpenAI 转写模型：Azure OpenAI 与 Azure Speech 的区别：<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/transcribe-overview>
- 转写快速入门：<https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart>
- 转写接口说明（2024-10-21）：<https://learn.microsoft.com/en-us/azure/foundry/openai/reference>
- 建资源与部署模型（经典版）：<https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource>
- 可部署的模型：<https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?tabs=standard-audio>
- 区域可用性：<https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability>
- 价格页（转写单价显示为“$-”）：<https://azure.microsoft.com/en-us/pricing/details/azure-openai/>
- 免费账户：<https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account>
- MAI-Voice-2.1 属于“文字变语音”：<https://openrouter.ai/api/v1/models?output_modalities=speech>
- Azure 门户与 Foundry 门户需要登录，本次未能查看内部画面。
