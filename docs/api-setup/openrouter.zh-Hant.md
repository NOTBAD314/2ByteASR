<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# OpenRouter 語音轉文字（進階，不建議一般使用者）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先說結論

- **一般使用者請不要選這一項**，改用列表裡的官方雲端服務（MOSS Pro 雲端、阿里雲百鍊、Qwen Cloud 等）或本地模型。
- 兔白把這一項標成“MAI 2.1”，**這與官方現狀不符**：2026-10-14 查 OpenRouter 公開的語音轉文字模型列表，微軟的轉寫模型只有 `microsoft/mai-transcribe-2` 和 `microsoft/mai-transcribe-1.5`，沒有叫 MAI 2.1 的轉寫模型。名字帶 2.1 的 `microsoft/mai-voice-2.1` 是“文字變語音”的模型，不能轉寫。
- 兔白目前會**拒絕** `microsoft/mai-transcribe-2`（提示“舊 MAI 2 模型不能作為新版執行……”），而它正是 OpenRouter 現在的 MAI 轉寫模型。這條規則和官方現狀不符，已記入已知問題，本輪沒有改程式。
- 所以現在只能填其他轉寫模型的 ID。這些模型兔白都沒有實測過，能不能拿到時間，以“試識別一小段…”的結果為準。
- 兔白驗證狀態：已有接入；本輪未用真實金鑰重新實測。

## 它在兔白裡做什麼

語音識別（生成字幕）。兔白把本次任務的音訊切段上傳到 OpenRouter，OpenRouter 再轉給實際提供該模型的服務商，取回文字，以及服務商給出的時間和說話人。用作主力轉寫時，每段最長約 3 分鐘。

## 官方連結

| 用途 | 地址 | 需要登入 |
| --- | --- | --- |
| 官網（註冊 / 登入） | <https://openrouter.ai/> | 否 |
| 建立 API Key | <https://openrouter.ai/keys> | 是（待核實） |
| 充值（Credits） | <https://openrouter.ai/settings/credits> | 是（待核實） |
| 方案與平台費 | <https://openrouter.ai/pricing> | 否 |
| 語音轉文字模型列表與單價 | <https://openrouter.ai/collections/speech-to-text-models> | 否 |
| 語音轉文字說明 | <https://openrouter.ai/docs/guides/overview/multimodal/stt> | 否 |
| API Key 說明 | <https://openrouter.ai/docs/api_reference/authentication> | 否 |
| 常見問題（付款、退款、額度過期、記錄） | <https://openrouter.ai/docs/faq> | 否 |
| 錯誤碼 | <https://openrouter.ai/docs/api_reference/errors-and-debugging> | 否 |

視窗頂部如果沒有“開啟網頁”按鈕，直接用上表的連結。

## 從未註冊開始

1. 開啟 <https://openrouter.ai/> 註冊賬號。可用哪些登入方式、要不要驗證手機，需要進入註冊流程才能看到（待核實）。官方公開頁面沒有提到實名認證。
2. 充值。語音轉文字沒有免費模型（2026-10-14 列表裡 25 個轉寫模型都標了單價），要先在 Credits 頁面買額度。官方價格頁寫的付款方式：信用卡 / 簽帳金融卡、支付寶（AliPay）、加密貨幣 USDC。充值頁的具體按鈕需要登入才能看到（待核實）。
3. 建立 Key：開啟 <https://openrouter.ai/keys>。官方說明寫的是：給 Key 取名，並選擇額度上限（也可以不設上限）。官方建議每把 Key 都設上限，避免 Key 外洩後餘額被花光。按鈕名稱需要登入才能看到（待核實）。
4. 複製 Key，貼到兔白的“API Key”欄。完整 Key 是否只顯示一次，官方檔案沒寫（待核實），建議建立後馬上覆制。

## 需不需要開通服務、充值、額外儲存

- 不需要單獨開通模型，也不需要 OSS 之類的儲存：音訊直接放在請求裡交給 OpenRouter。
- 需要先充值。餘額不足或 Key 達到額度上限時，OpenRouter 返回 HTTP 402。

## 兔白裡的欄位

開啟「申請與設定 API」（首頁右上角“說明”選單 →“申請與設定 API…”），在左側列表點“顯示進階選項（自架介面、待驗證服務）”，再選 OpenRouter 那一項（標有“進階”）。“填寫”區有兩欄：

| 欄位 | 用途 | 例子 | 從哪裡拿 |
| --- | --- | --- | --- |
| API Key | 證明是你的賬戶在付費 | 整串貼上，前後不要有空格 | OpenRouter 的 Keys 頁面 |
| 模型 ID | 要用哪個轉寫模型，必須填 | `openai/whisper-large-v3-turbo`（兔白未實測） | 語音轉文字模型列表，複製“廠商/模型”格式的 ID |

- 不能填 `microsoft/mai-transcribe-2`：兔白目前會拒絕（見“先說結論”）。
- `microsoft/mai-transcribe-1.5` 可以填，但 OpenRouter 說明它不接受帶時間資訊的回傳格式；兔白會退回只要文字，結果沒有可用的時間。

## 已預填、不用改

窗口裡沒有位址列位，兔白內建了請求地址，不用填。三種地址的區別：

| 名稱 | 地址 |
| --- | --- |
| 官方網站 | `https://openrouter.ai` |
| API Base URL | `https://openrouter.ai/api/v1` |
| 完整請求 Endpoint（兔白實際使用） | `https://openrouter.ai/api/v1/audio/transcriptions` |

## 測試：成功時會看到什麼

1. 點“免費檢查（不上傳音訊）”：
   - 設定格式 ✓、服務可以連線 ✓。
   - 認證成功（API Key 有效）顯示 ?：“OpenRouter 的模型列表不需要金鑰，不能證明金鑰有效；請用實際短音訊識別確認。”這是正常的。
   - 指定模型可用 目前會顯示 ✗“模型列表裡沒有 …”。原因是兔白查的是 OpenRouter 的一般模型列表，而這個列表不含任何轉寫模型（2026-10-14 核對）。這是兔白檢查方式的問題，不代表你填錯；以下一步為準。
2. 點“試識別一小段…”。確認框會寫明上傳到 `openrouter.ai`，費用“無法事先估算”。選“上傳自帶測試音訊”（約 6 秒英文合成語音，不含你的素材）或“選擇我的音訊…”（60 秒以內）。
   - 實際短音訊識別 ✓“識別出 N 段文字。”表示能用。
   - 回傳時間戳 ✓“有字/詞級時間（N 個時間片）”表示拿到了逐詞時間；顯示 ? 和“只有句段起止時間……”表示沒有逐詞時間（可能只有句段時間，也可能完全沒有）。
   - 回傳說話人 ✓ 表示有說話人標籤；— 表示這次沒有。
3. 結果滿意再點“儲存”或“儲存並用於識別”。

## 能拿到什麼（時間、說話人）

- OpenRouter 官方：逐詞時間只在 `verbose_json` 回傳格式下提供，而且取決於實際轉給的服務商；`openai/gpt-4o-transcribe` 和 `microsoft/mai-transcribe-1.5` 會拒絕這種格式。
- 被拒時兔白退回只要文字。這時一整段（主力轉寫最長約 3 分鐘）只有一個起止時間，不適合直接做字幕。
- 說話人：兔白只向 Azure 提供的模型請求說話人區分，而 Azure 提供的 MAI-Transcribe 2 目前被兔白拒絕。其他模型：官方檔案未寫明，兔白未實測。

## 費用

按模型單價計費，美元，2026-10-14 從 OpenRouter 公開模型列表讀取，以賬單為準：

| 模型 ID | 單價 | 在兔白裡 |
| --- | --- | --- |
| `microsoft/mai-transcribe-2` | $0.10 / 小時音訊 | 目前被拒絕 |
| `microsoft/mai-transcribe-1.5` | $0.36 / 小時 | 拿不到時間 |
| `openai/whisper-large-v3-turbo` | $0.00000333 / 秒（約 $0.012 / 小時） | 未實測 |
| `openai/whisper-1` | $0.0001 / 秒（約 $0.36 / 小時） | 未實測 |

- 買額度時另收平台費：按量付費的標準方案 5.5%（常見問題頁寫最低 $0.80）。
- 常見問題頁寫明：OpenRouter 保留在購買一年後讓未用額度過期的權利。
- MAI-Transcribe 2 的模型頁寫明失敗的請求不收費；其他模型未逐一核對。

## 隱私：會傳送什麼

- 音訊：本次任務的音訊（16 kHz 單聲道 WAV，只有聲音，不含畫面）→ OpenRouter（openrouter.ai）→ 實際提供模型的服務商（例如 Azure、DeepInfra、Groq，按模型而定）。
- 這一項不附帶素材檔名或術語表：兔白對 OpenRouter 不傳送提示文字。
- OpenRouter 常見問題寫：預設只記錄請求的基本資訊（時間、模型、用量），不記錄提示和回覆內容；音訊是否同樣處理，頁面沒有單獨寫。上游服務商有各自的資料政策。
- API Key 加密儲存在本機（Windows 用 DPAPI；macOS 用鑰匙串，鑰匙串不可用時只在本次執行期間儲存，不寫成明文），不寫進工程、日誌或匯出檔案。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 提示“舊 MAI 2 模型不能作為新版執行……” | 填了 `microsoft/mai-transcribe-2`，兔白目前拒絕 | 換其他模型 ID，或改用列表裡的官方雲端服務 |
| 提示“ASR API 缺少模型名稱。” | 模型 ID 空著 | 從語音轉文字模型列表複製一個 ID 貼上 |
| 指定模型可用 ✗“模型列表裡沒有 …” | 兔白查的列表不含轉寫模型（已知問題） | 確認 ID 與官方列表完全一致（含斜槓、大小寫），然後用“試識別一小段…”判斷 |
| 認證成功 顯示 ? | OpenRouter 模型列表公開，無法驗證 Key | 正常，用“試識別一小段…”確認 |
| HTTP 401 | Key 無效、被停用或沒複製完整 | 回 Keys 頁面確認 Key 狀態，重新複製整串貼上 |
| HTTP 402 | 餘額不足，或 Key 達到額度上限 | 到 Credits 頁面充值，或在 Key 頁面調高上限 |
| HTTP 403 | 許可權不足，或內容被稽核攔截 | 換一段測試音訊再試；仍失敗就換模型或服務 |
| HTTP 400 | 模型不接受這種請求（兔白已自動退回仍失敗），或 ID 寫錯 | 核對 ID；換一個轉寫模型 |
| HTTP 404 | 模型 ID 不存在，或沒有服務商能處理這次請求 | 從官方列表重新複製 ID |
| HTTP 408 | 上游處理超時（官方說上游每次請求 60 秒超時） | 再試一次；反覆出現就改用其他服務 |
| HTTP 429 / 502 / 503 | 限流或上游暫時不可用 | 兔白會自動等待重試；仍失敗就稍後再試或換模型 |
| 回傳時間戳 顯示 ? | 這個模型或服務商沒給逐詞時間 | 不要用它做主力轉寫；改用有字/詞級時間的服務（阿里雲百鍊、Qwen Cloud 錄音檔案識別） |

## 進階（一般使用者可跳過）

- 兔白的請求：`POST https://openrouter.ai/api/v1/audio/transcriptions`，頭 `Authorization: Bearer <Key>`，JSON 正文含 `model`、`input_audio`（`data` 為 WAV 的 base64，`format: "wav"`）、`response_format: "verbose_json"`、`timestamp_granularities: ["segment", "word"]`，以及 `provider.options.azure`（`diarization.enabled: true`；`modelOptions.transcribeStyle` 取兔白的轉寫風格設定，預設 `clean`）。
- 遇到 HTTP 400 依次退回：去掉 `timestamp_granularities` → 改用 `json` → 去掉 `provider` 選項。
- 分段：主力轉寫每段最長 180 秒；文字複核按人聲切成最長約 25 秒的段。
- 兔白讀取回應裡的 `segments`（`start`、`end`、`text`、`speaker`）和 `words`（頂層或 segment 內；`word`、`start`、`end`、`speaker`）。
- “免費檢查”讀的是 `GET https://openrouter.ai/api/v1/models`；這個列表預設不含轉寫模型（官方說明要加 `output_modalities=transcription` 才列出），所以“指定模型可用”會誤報 ✗。
- 程式位置：請求在 `twobyteasr/asr.py` 的 `call_qwen_asr_api`；拒絕規則在 `twobyteasr/llm_config.py` 的 `validate_qwen_asr_endpoint`；讀取設定時 `twobyteasr/settings.py` 會把這一項裡的 `microsoft/mai-transcribe-2` 清空。

## 來源（2026-10-14 核對）

- OpenRouter 語音轉文字說明：<https://openrouter.ai/docs/guides/overview/multimodal/stt>
- OpenRouter 語音轉文字模型列表：<https://openrouter.ai/collections/speech-to-text-models>
- OpenRouter 轉寫模型公開清單（JSON）：<https://openrouter.ai/api/v1/models?output_modalities=transcription>；文字變語音清單：<https://openrouter.ai/api/v1/models?output_modalities=speech>；一般模型清單：<https://openrouter.ai/api/v1/models>
- MAI-Transcribe 2 模型頁：<https://openrouter.ai/microsoft/mai-transcribe-2>
- API Key 說明：<https://openrouter.ai/docs/api_reference/authentication>
- 方案與平台費：<https://openrouter.ai/pricing>
- 常見問題：<https://openrouter.ai/docs/faq>
- 錯誤碼：<https://openrouter.ai/docs/api_reference/errors-and-debugging>
- Keys 與 Credits 頁面需要登入，本次只確認會轉到登入，內容待核實。
