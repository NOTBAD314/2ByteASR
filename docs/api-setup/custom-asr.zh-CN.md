# 自定义 OpenAI 兼容转写（进阶）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先说结论

- **一般使用者不需要这一项。** 用官方云端服务（MOSS Pro 云端、阿里云百炼、Qwen Cloud、讯飞等）或本地模型，都不用自己架服务器。自己架设接口只是进阶选择，从来不是必需步骤。
- 适合：你自己架了，或在别处买了一个“OpenAI 兼容”的转写接口，并且手上有它的完整请求地址、模型名和 Key。
- 能拿到什么时间、有没有说话人，完全取决于那个服务回什么；兔白不会替它补。
- 兔白验证状态：已有接入；本轮未用真实密钥重新实测。

## 它在兔白里做什么

语音识别（生成字幕）。兔白按人声把音频切成小段（主力转写每段约 10 秒以内，文字复核约 25 秒以内），逐段上传到你填写的地址，取回文字和时间。

## “OpenAI 兼容 /audio/transcriptions”是什么意思

OpenAI 定义了一种“上传音频、拿回文字”的请求格式，地址以 `/audio/transcriptions` 结尾。很多服务和开源软件照这个格式做了自己的接口。只要对方按这个格式收音频、回 JSON，兔白就能用。

兔白每段发送的内容：

| 内容 | 兔白发什么 |
| --- | --- |
| 方式 | `POST`，表单上传（multipart/form-data） |
| `file` | 一小段音频：16 kHz 单声道 WAV，文件名 `chunk.wav` |
| `model` | 你在“模型”栏填的名字 |
| `prompt` | 提示文字：字幕场景、素材文件名、你确认过的专名写法，最多 900 字 |
| `response_format` | `verbose_json`；服务回 HTTP 400 时自动改成 `json` 再试一次 |
| 验证 | 请求头 `Authorization: Bearer <API Key>` |
| 不发送 | `timestamp_granularities`、`language`、`temperature` |

兔白能读懂的回应（必须是 JSON）：

| 回应里有什么 | 兔白得到什么 |
| --- | --- |
| 只有 `text` | 文字可用，但每段只有一个起止时间（就是这一小段的范围） |
| `segments`（每项有 `start`、`end`（秒）、`text`） | 句段时间 |
| `words`（顶层，或每个 segment 里；每项有 `word` 或 `text`、`start`、`end`） | 字/词级时间 |
| segment 或 word 里有 `speaker` | 说话人标签 |

回 `text`、`srt`、`vtt` 这类纯文字格式时，兔白读不了。兔白不请求逐词时间（不发送 `timestamp_granularities`），所以服务要在 `verbose_json` 里**默认**就带上 `words`，兔白才拿得到逐词时间。

## 官方链接

这一项没有固定的服务商。请向你使用的服务（或你架设所用软件的说明）取得地址、模型名和 Key。下面是接口格式的原始说明，一般使用者不用看：

| 用途 | 地址 | 需要登录 |
| --- | --- | --- |
| OpenAI 转写接口格式说明 | <https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create> | 否 |

## 从头开始的步骤

1. 向服务提供者取得三样东西：完整请求 Endpoint、模型名、API Key。要不要注册、实名、绑卡或充值，由那个服务决定，兔白这边无法确认。
2. 打开「申请与设置 API」（首页右上角“说明”菜单 →“申请与设置 API…”），在左侧列表点“显示进阶选项（自架接口、待验证服务）”，再选“自定义 OpenAI 兼容转写”那一项（标有“进阶”）。
3. 按下表填三栏，先测试再保存。

## 需不需要开通服务、充值、额外储存

- 兔白这边不需要 OSS 或其他储存：音频直接放在请求里。
- 服务那边是否要开通、充值、有没有单个文件大小限制，看服务的说明。兔白每段约 10 秒（WAV 约 0.3 MB）。

## 兔白里的栏位

三栏都没有预填，都要填：

| 栏位 | 用途 | 例子 | 从哪里拿 |
| --- | --- | --- | --- |
| 完整请求 Endpoint | 兔白把音频发到这个地址，原样使用 | `https://asr.example.com/v1/audio/transcriptions` | 服务的说明文件 |
| 模型 | 放进请求的 `model` 名称，不能空 | `whisper-1`（以服务要求为准） | 服务的说明文件，或它的模型列表 |
| API Key | 放进 `Authorization: Bearer` | 服务给你的 Key | 服务的控制台；服务不检查 Key 时也要随便填一串（例如 `local`），因为兔白要求这一栏不能空 |

### Base URL 和 完整请求 Endpoint 的区别

| 名称 | 例子 | 兔白要不要 |
| --- | --- | --- |
| 官方网站 | `https://example.com` | 不要 |
| Base URL（服务根地址，常以 `/v1` 结尾） | `https://asr.example.com/v1` | 不要 |
| 完整请求 Endpoint（Base URL + `/audio/transcriptions`） | `https://asr.example.com/v1/audio/transcriptions` | **要这个** |

- 兔白**不会**自动加 `/v1`，也**不会**自动加 `/audio/transcriptions`。服务说明写的完整地址是什么就填什么；说明只给 Base URL 时，自己在后面接上 `/audio/transcriptions`。
- 地址必须是 `https://` 开头，不能带 `?参数`、`#片段` 或账号密码。
- 本机服务（`http://127.0.0.1` 或 `http://localhost`）：保存和实际识别接受，但对话框里的两个测试按钮只接受 https，会显示设置格式 ✗。兔白未实测本机 http 服务。

## 已预填、不用改

没有预填栏位。

## 测试：成功时会看到什么

1. 点“免费检查（不上传音频）”。兔白去掉地址末尾的 `/audio/transcriptions`，带着 Key 读取 `/models` 列表（例如 `https://asr.example.com/v1/models`）：
   - 设置格式 ✓、服务可以连线 ✓。
   - 认证成功（API Key 有效）✓；服务拒绝 Key 时显示 ✗“服务拒绝了这个 API Key（HTTP 401）。”；服务没有模型列表时显示 ?“模型列表返回 HTTP 404；无法判断密钥是否有效。”（不影响使用）。
   - 指定模型可用 ✓ 表示列表里有你填的模型；✗“模型列表里没有 …”表示名字对不上。
2. 点“试识别一小段…”。确认框会写明上传到你填的域名，费用“无法事先估算”。选“上传自带测试音频”（约 6 秒英文合成语音，不含你的素材）或“选择我的音频…”（60 秒以内）。
   - 实际短音频识别 ✓“识别出 N 段文字。”表示能用。
   - 回传时间戳 ✓“有字/词级时间（N 个时间片）”表示服务回了 `words`；显示 ? 和“只有句段起止时间……”表示没有逐词时间（可能只有句段时间，也可能完全没有）。
   - 回传说话人 ✓ 表示服务回了 `speaker`；— 表示没有。
3. 结果满意再点“保存”或“保存并用于识别”。

## 费用

由你使用的服务决定，兔白无法估算（确认框会写“无法事先估算”）。自己架设时，费用是你自己的电脑或服务器、电费和带宽。

## 隐私：会传送什么

- 每段音频（16 kHz 单声道 WAV，只有声音，不含画面）和一段提示文字 → 你填写的地址。提示文字包括字幕场景、**素材文件名**和你确认过的专名写法，最多 900 字。
- 对方怎么保存这些数据，由那个服务决定。
- API Key 加密保存在本机（Windows 用 DPAPI；macOS 用钥匙串，钥匙串不可用时只在本次运行期间保存，不写成明文），不写进工程、日志或导出文件。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 设置格式 ✗“还没有填写 API Key。” | Key 栏空着 | 服务不检查 Key 时也随便填一串，例如 `local` |
| 设置格式 ✗“服务地址无效：需要 https 开头的完整地址。” | 地址不是 https；或是本机 http 服务 | 改用 https 地址；本机 http 服务可直接保存，再用一小段真实素材试跑 |
| 提示地址“不能包含账号、密码、查询参数或片段” | 地址里有 `?…`、`#…` 或 `用户名:密码@` | 删掉这些部分；必须靠查询参数验证的服务，这一项用不了 |
| 提示“ASR API 缺少模型名称。” | 模型栏空着 | 填服务要求的模型名 |
| 服务可以连线 ✗“连不上服务：…” | 域名写错、服务没开、网络或防火墙拦截 | 在浏览器打开 Base URL 看有没有回应；确认服务正在运行 |
| 认证成功 ✗（HTTP 401 / 403） | Key 错或已失效 | 到服务那边重新复制 Key |
| 指定模型可用 ✗ | 模型名与服务列表不一致 | 照列表里的写法填（区分大小写、斜杠） |
| 试识别 HTTP 404 | 地址路径不对，常见是少了或多了 `/v1` | 对照服务说明，填完整请求 Endpoint |
| 试识别 HTTP 400 或 422 | 服务不接受表单里的 `file` / WAV / `prompt`（兔白已自动改 `json` 仍失败） | 确认服务支持 OpenAI 格式的表单上传和 WAV |
| 多次重试后失败，错误里有“Expecting value”之类的字样 | 服务回的不是 JSON：可能是地址路径不对、对方回了网页，也可能服务只回纯文字 | 先按“HTTP 404”那一行核对地址；地址正确就让服务回 JSON（`json` 或 `verbose_json`） |
| 识别成功，但回传时间戳 显示 ? | 服务只回 `text`，或只有 `segments` | 让服务在 `verbose_json` 里默认带 `words`；否则主力转写改用有字/词级时间的服务 |

## 进阶（一般使用者可跳过）

- 失败重试：HTTP 429 / 500 / 502 / 503 / 504 或连线错误会等待后重试，同一段最多尝试 6 次；其他错误码直接失败。
- 时间换算：服务回的 `start` / `end` 以秒计、从这一小段开头算起，兔白再加上这段在整片里的位置。
- 免费检查用的地址：去掉末尾的 `/audio/transcriptions`；剩下的路径不为空就接 `/models`，为空就接 `/v1/models`。
- 程序位置：请求在 `twobyteasr/asr.py` 的 `call_qwen_asr_api`（`openai_transcription` 分支），回应解析在同一文件的 `_extract_transcription_segments` / `_extract_transcription_words`；地址规则在 `twobyteasr/llm_config.py` 的 `validate_transport_url`；测试按钮在 `twobyteasr/cloud_api_test.py`。

## 来源（2026-10-14 核对）

- OpenAI 转写接口格式（请求字段、`verbose_json` 的 `segments` / `words`）：<https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create>
- 兔白当前代码（只读核对）：`twobyteasr/asr.py`、`twobyteasr/llm_config.py`、`twobyteasr/cloud_api_test.py`、`twobyteasr/api_setup_catalog.py`、`twobyteasr/ui.py`（`ASR_API_PRESETS`）。
