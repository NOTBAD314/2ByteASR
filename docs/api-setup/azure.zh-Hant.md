<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# Azure OpenAI 部署式轉寫（進階，不建議一般使用者）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先說結論

- **一般使用者請不要選這一項**，改用列表裡的官方雲端服務（MOSS Pro 雲端、阿里雲百鍊、Qwen Cloud 等）或本地模型。
- 兔白把這一項標成“MAI 2.1”，**這與微軟現狀不符**：微軟官方頁面列出的轉寫模型是 MAI-Transcribe-2 和 MAI-Transcribe-1.5（MAI-Transcribe-1 已於 2026-08-20 棄用），沒有 MAI-Transcribe-2.1；名字帶 2.1 的 MAI-Voice-2.1 是“文字變語音”的模型。
- MAI-Transcribe 走的是 Azure Speech 的另一種介面，**不需要、也不能“部署”**。兔白這一項呼叫的是 **Azure OpenAI 的“部署式”轉寫介面**，只能用你在 Azure 部署的 OpenAI 轉寫模型（例如 `whisper`）。所以，**兔白目前不能通過這一項使用 MAI-Transcribe**。
- 如果你已經有 Azure OpenAI 資源並部署了 whisper，可以試：預計只有句段時間，沒有逐字時間和說話人。兔白未實測。
- 兔白驗證狀態：已有接入；本輪未用真實金鑰重新實測。

## 它在兔白裡做什麼

語音識別（生成字幕）。兔白按人聲把音訊切成小段（主力轉寫每段約 10 秒以內，文字複核約 25 秒以內），逐段上傳到你自己的 Azure OpenAI 資源，取回文字和句段時間。

## 官方連結

| 用途 | 地址 | 需要登入 |
| --- | --- | --- |
| 註冊 Azure（免費賬戶說明） | <https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account> | 否 |
| Azure 門戶（建資源、看 Key 與 Endpoint） | <https://portal.azure.com/> | 是（待核實） |
| Microsoft Foundry 門戶（部署模型） | <https://ai.azure.com/> | 是（待核實） |
| 建資源與部署模型（官方教程，經典版） | <https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource> | 否 |
| 轉寫快速入門（地址格式、Key 位置） | <https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart> | 否 |
| 轉寫介面說明（2024-10-21 版） | <https://learn.microsoft.com/en-us/azure/foundry/openai/reference> | 否 |
| 可部署的轉寫模型 | <https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?tabs=standard-audio> | 否 |
| 各區域能部署哪些模型 | <https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability> | 否 |
| 價格 | <https://azure.microsoft.com/en-us/pricing/details/azure-openai/> | 否 |
| MAI-Transcribe（兔白目前不能呼叫） | <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe> | 否 |

視窗頂部如果沒有“開啟網頁”按鈕，直接用上表的連結。

## 從未註冊開始

以下按鈕名稱來自微軟官方教程（英文介面）；門戶實際畫面需要登入才能看到（待核實），新版 Foundry 門戶的選單可能不同。

1. **註冊 Azure 賬號。** 免費賬戶頁寫明：需要微軟或 GitHub 賬號、手機號碼、信用卡或簽帳金融卡（不能用預付卡），註冊時可能有約 1 美元的臨時授權，之後撤銷。免費賬戶含 30 天內可用的 200 美元額度，之後要轉成按量付費才能繼續用。這筆額度能否用於 Azure OpenAI，頁面沒有寫明。
2. **建 Azure OpenAI 資源。** 在 Azure 門戶選 **Create a resource**，搜尋 **Azure OpenAI** →**Create**。在 **Basics** 填 Subscription、Resource group、Region、Name、Pricing Tier（目前只有 Standard）。網路選項保留預設（所有網路可訪問）即可。最後 **Review + submit** →**Create**。Region 要選能部署你想用的模型的區域（看“各區域能部署哪些模型”，whisper 只在部分割槽域提供）。
3. **部署轉寫模型。** 在 Microsoft Foundry 門戶找到你的資源，進 **Deployments** →**+ Deploy model** →**Deploy base model**，選模型（建議 `whisper`），在 **Deployment name** 填一個名字（例如 `my-whisper`，區分大小寫，之後要用）→**Deploy**。狀態變成 *Succeeded* 才算完成。
4. **取得 Endpoint 和 Key。** 在 Azure 門戶開啟這個資源，**Resource Management** 下的 **Keys & Endpoint**：Endpoint 形如 `https://<資源名>.openai.azure.com/`，Key 用 KEY1 或 KEY2 都可以。
5. **拼出兔白要的“部署地址”**（見下一節）。

## 需不需要開通服務、綁卡、額外儲存

- 需要：Azure 訂閱（要綁卡）、一個 Azure OpenAI 資源、一個轉寫模型部署。
- 不需要 OSS 或 Azure 儲存：音訊直接放在請求裡。微軟寫明單個音訊檔案上限 25 MB；兔白每段約 10 秒，遠小於上限。

## 兔白裡的欄位

開啟「申請與設定 API」（首頁右上角“說明”選單 →“申請與設定 API…”），在左側列表點“顯示進階選項（自架介面、待驗證服務）”，再選 Azure 那一項（標有“進階”）。“填寫”區有三欄，都沒有預填：

| 欄位 | 用途 | 例子 | 從哪裡拿 |
| --- | --- | --- | --- |
| 部署地址 | 兔白實際發請求的完整地址，必須帶 `api-version` | `https://myres.openai.azure.com/openai/deployments/my-whisper/audio/transcriptions?api-version=2024-10-21` | 用 Endpoint 和部署名稱拼出來（見下表） |
| API Key | 資源的金鑰 | 整串貼上，前後不要有空格 | Azure 門戶 **Keys & Endpoint** 的 KEY1 或 KEY2 |
| 部署名稱 | 顯示用，兔白要求不能空；兔白不會把它放進請求，實際呼叫哪個部署只看“部署地址” | `my-whisper` | 部署時自己取的 **Deployment name** |

地址怎麼分：

| 名稱 | 例子 | 說明 |
| --- | --- | --- |
| 官方網站 | `https://portal.azure.com/` | 只用來登入管理，不要填進兔白 |
| 資源 Endpoint（相當於 Base URL） | `https://myres.openai.azure.com/` | 門戶裡顯示的 Endpoint，不能直接填進兔白 |
| 完整請求 Endpoint（兔白的“部署地址”） | `https://myres.openai.azure.com/openai/deployments/my-whisper/audio/transcriptions?api-version=2024-10-21` | 資源 Endpoint + `openai/deployments/` + 部署名稱 + `/audio/transcriptions?api-version=2024-10-21` |

- 兔白不會幫你補任何路徑，也不會自動加 `/v1`。
- 門戶顯示的 Endpoint 如果不是 `openai.azure.com` 結尾，照門戶顯示的域名拼即可；其他域名格式兔白未實測。
- Azure 新版 v1 地址（`/openai/v1/audio/transcriptions`）不適合這一項：v1 要在請求裡寫部署名，而兔白這一項不傳送（兔白未實測）。

## 已預填、不用改

- 三欄都要自己填。
- 兔白會自動要求帶句段時間的回傳格式（`verbose_json`），服務拒絕時自動改用普通格式（`json`）。

## 測試：成功時會看到什麼

1. 點“免費檢查（不上傳音訊）”：只在本機核對格式。設定格式 ✓；認證成功（API Key 有效）顯示 ?：“這個服務沒有可用的免費檢查；請用“實際短音訊識別”確認。”這是正常的，Key 是否有效要看下一步。
2. 點“試識別一小段…”。確認框會寫明上傳到你的資源域名（例如 `myres.openai.azure.com`），費用“無法事先估算”。選“上傳自帶測試音訊”（約 6 秒英文合成語音，不含你的素材）或“選擇我的音訊…”（60 秒以內）。部署 whisper 時預計看到：
   - 實際短音訊識別 ✓“識別出 N 段文字。”
   - 回傳時間戳 ?“只有句段起止時間，沒有逐字時間；需要精細剪輯時請再配本地對齊。”
   - 回傳說話人 —“這次結果沒有說話人標籤……”
3. 結果滿意再點“儲存”或“儲存並用於識別”。

## 能拿到什麼（時間、說話人）

| 部署的模型 | 時間 | 說話人 |
| --- | --- | --- |
| `whisper` | 句段時間（兔白不請求逐詞時間） | 無（微軟寫明 Azure OpenAI 轉寫模型不支援說話人區分） |
| `gpt-transcribe`、`gpt-4o-transcribe`、`gpt-4o-mini-transcribe` | 是否接受帶時間的回傳格式，官方檔案未寫明，兔白未實測；若被拒，兔白退回只要文字，每段（約 10 秒）只有一個起止時間 | 無 |
| `gpt-4o-transcribe-diarize` | 兔白未實測 | 兔白不請求這個模型的說話人格式，拿不到 |

需要逐字時間或說話人，請改用阿里雲百鍊或 Qwen Cloud 的錄音檔案識別。

## 費用

- Azure 按部署的模型計費，以 Azure 賬單為準。
- 2026-10-14 開啟 Azure OpenAI 價格頁，轉寫模型的單價都顯示為“$-”（頁面沒有直接顯示數字），**本次未能確定單價**。請在瀏覽器打開價格頁檢視，或用 Azure 價格計算器。
- 免費賬戶的 200 美元額度 30 天內有效，能否抵扣 Azure OpenAI 未寫明。

## 隱私：會傳送什麼

- 每段音訊（16 kHz 單聲道 WAV，只有聲音，不含畫面）和一段提示文字 → 你自己的 Azure 資源。提示文字包括字幕場景、**素材檔名**和你確認過的專名寫法，最多 900 字。
- API Key 加密儲存在本機（Windows 用 DPAPI；macOS 用鑰匙串，鑰匙串不可用時只在本次執行期間儲存，不寫成明文），不寫進工程、日誌或匯出檔案。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 提示“ASR API 缺少模型名稱。” | 部署名稱空著 | 填部署時取的 Deployment name |
| 設定格式 ✗“服務地址無效：需要 https 開頭的完整地址。” | 只填了資源名，或不是 https 開頭 | 按上面的格式填完整部署地址 |
| HTTP 401 | Key 錯，或 Key 與部署地址不屬於同一個資源 | 回 **Keys & Endpoint** 重新複製 KEY1；確認部署地址裡的資源名就是這個資源 |
| HTTP 404 / 找不到部署 | 部署名稱拼錯（區分大小寫），或部署還沒完成 | 對照 Foundry 門戶 **Deployments** 裡的名字；等狀態變成 *Succeeded* |
| HTTP 400，提到 api-version | 地址缺 `api-version` 或版本不支援 | 地址末尾用 `?api-version=2024-10-21` |
| 其他 HTTP 400 | 部署的模型不接受兔白的請求（兔白已自動退回仍失敗） | 改部署 `whisper` 再試 |
| HTTP 429 | 超過這個部署的速率配額 | 兔白會自動等待重試；仍失敗就在 Azure 調高該部署的配額（具體位置需登入，待核實） |
| 回傳時間戳 顯示 ? | whisper 只給句段時間，或模型沒給時間 | 需要逐字時間就改用百鍊或 Qwen Cloud 錄音檔案識別 |
| 想用 MAI-Transcribe，填 Speech 地址後失敗 | 兔白這一項不支援 Azure Speech 的介面 | 目前無法在兔白使用 MAI-Transcribe；改用其他服務 |

## 進階（一般使用者可跳過）

- 兔白的請求：`POST` 到“部署地址”，頭 `api-key: <Key>`，表單上傳（multipart）`file`（chunk.wav）、`prompt`（最多 900 字）、`response_format=verbose_json`（HTTP 400 時改 `json` 再試一次）。不傳送 `model`、`timestamp_granularities`、`language`。遇到 429 / 5xx 會等待後重試，同一段最多嘗試 6 次。
- MAI-Transcribe 的官方介面（兔白尚未支援）：`POST https://<資源名>.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15`，頭 `Ocp-Apim-Subscription-Key`，表單 `audio` + `definition`（`enhancedMode.enabled: true`、`enhancedMode.model: "MAI-Transcribe-2"`；可選 `diarization.enabled`、`modelOptions.timestamps` 取 `word` / `segment` / `none`（預設 `none`）、`modelOptions.transcribeStyle`、`phraseList.phrases`、`locales`）。前提是 Azure 訂閱加一個 Microsoft Foundry 的 Speech 資源。目前是公開預覽，沒有 SLA，官方不建議用於生產。
- 程式位置：請求在 `twobyteasr/asr.py` 的 `call_qwen_asr_api`（`azure_transcription` 分支）；地址允許帶 `?api-version=` 的規則在 `twobyteasr/llm_config.py` 的 `validate_qwen_asr_endpoint`。

## 來源（2026-10-14 核對）

- MAI-Transcribe（Azure Speech）：<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe>
- OpenAI 轉寫模型：Azure OpenAI 與 Azure Speech 的區別：<https://learn.microsoft.com/en-us/azure/ai-services/speech-service/transcribe-overview>
- 轉寫快速入門：<https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart>
- 轉寫介面說明（2024-10-21）：<https://learn.microsoft.com/en-us/azure/foundry/openai/reference>
- 建資源與部署模型（經典版）：<https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource>
- 可部署的模型：<https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?tabs=standard-audio>
- 區域可用性：<https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability>
- 價格頁（轉寫單價顯示為“$-”）：<https://azure.microsoft.com/en-us/pricing/details/azure-openai/>
- 免費賬戶：<https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account>
- MAI-Voice-2.1 屬於“文字變語音”：<https://openrouter.ai/api/v1/models?output_modalities=speech>
- Azure 門戶與 Foundry 門戶需要登入，本次未能檢視內部畫面。
