<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 自定義 OpenAI 相容轉寫（進階）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先說結論

- **一般使用者不需要這一項。** 用官方雲端服務（MOSS Pro 雲端、阿里雲百鍊、Qwen Cloud、訊飛等）或本地模型，都不用自己架伺服器。自己架設介面只是進階選擇，從來不是必需步驟。
- 適合：你自己架了，或在別處買了一個“OpenAI 相容”的轉寫介面，並且手上有它的完整請求地址、模型名和 Key。
- 能拿到什麼時間、有沒有說話人，完全取決於那個服務回什麼；兔白不會替它補。
- 兔白驗證狀態：已有接入；本輪未用真實金鑰重新實測。

## 它在兔白裡做什麼

語音識別（生成字幕）。兔白按人聲把音訊切成小段（主力轉寫每段約 10 秒以內，文字複核約 25 秒以內），逐段上傳到你填寫的地址，取回文字和時間。

## “OpenAI 相容 /audio/transcriptions”是什麼意思

OpenAI 定義了一種“上傳音訊、拿回文字”的請求格式，地址以 `/audio/transcriptions` 結尾。很多服務和開源軟體照這個格式做了自己的介面。只要對方按這個格式收音訊、回 JSON，兔白就能用。

兔白每段傳送的內容：

| 內容 | 兔白髮什麼 |
| --- | --- |
| 方式 | `POST`，表單上傳（multipart/form-data） |
| `file` | 一小段音訊：16 kHz 單聲道 WAV，檔名 `chunk.wav` |
| `model` | 你在“模型”欄填的名字 |
| `prompt` | 提示文字：字幕場景、素材檔名、你確認過的專名寫法，最多 900 字 |
| `response_format` | `verbose_json`；服務回 HTTP 400 時自動改成 `json` 再試一次 |
| 驗證 | 請求頭 `Authorization: Bearer <API Key>` |
| 不傳送 | `timestamp_granularities`、`language`、`temperature` |

兔白能讀懂的回應（必須是 JSON）：

| 回應裡有什麼 | 兔白得到什麼 |
| --- | --- |
| 只有 `text` | 文字可用，但每段只有一個起止時間（就是這一小段的範圍） |
| `segments`（每項有 `start`、`end`（秒）、`text`） | 句段時間 |
| `words`（頂層，或每個 segment 裡；每項有 `word` 或 `text`、`start`、`end`） | 字/詞級時間 |
| segment 或 word 裡有 `speaker` | 說話人標籤 |

回 `text`、`srt`、`vtt` 這類純文字格式時，兔白讀不了。兔白不請求逐詞時間（不傳送 `timestamp_granularities`），所以服務要在 `verbose_json` 裡**預設**就帶上 `words`，兔白才拿得到逐詞時間。

## 官方連結

這一項沒有固定的服務商。請向你使用的服務（或你架設所用軟體的說明）取得地址、模型名和 Key。下面是介面格式的原始說明，一般使用者不用看：

| 用途 | 地址 | 需要登入 |
| --- | --- | --- |
| OpenAI 轉寫介面格式說明 | <https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create> | 否 |

## 從頭開始的步驟

1. 向服務提供者取得三樣東西：完整請求 Endpoint、模型名、API Key。要不要註冊、實名、綁卡或充值，由那個服務決定，兔白這邊無法確認。
2. 開啟「申請與設定 API」（首頁右上角“說明”選單 →“申請與設定 API…”），在左側列表點“顯示進階選項（自架介面、待驗證服務）”，再選“自定義 OpenAI 相容轉寫”那一項（標有“進階”）。
3. 按下表填三欄，先測試再儲存。

## 需不需要開通服務、充值、額外儲存

- 兔白這邊不需要 OSS 或其他儲存：音訊直接放在請求裡。
- 服務那邊是否要開通、充值、有沒有單個檔案大小限制，看服務的說明。兔白每段約 10 秒（WAV 約 0.3 MB）。

## 兔白裡的欄位

三欄都沒有預填，都要填：

| 欄位 | 用途 | 例子 | 從哪裡拿 |
| --- | --- | --- | --- |
| 完整請求 Endpoint | 兔白把音訊發到這個地址，原樣使用 | `https://asr.example.com/v1/audio/transcriptions` | 服務的說明檔案 |
| 模型 | 放進請求的 `model` 名稱，不能空 | `whisper-1`（以服務要求為準） | 服務的說明檔案，或它的模型列表 |
| API Key | 放進 `Authorization: Bearer` | 服務給你的 Key | 服務的控制台；服務不檢查 Key 時也要隨便填一串（例如 `local`），因為兔白要求這一欄不能空 |

### Base URL 和 完整請求 Endpoint 的區別

| 名稱 | 例子 | 兔白要不要 |
| --- | --- | --- |
| 官方網站 | `https://example.com` | 不要 |
| Base URL（服務根地址，常以 `/v1` 結尾） | `https://asr.example.com/v1` | 不要 |
| 完整請求 Endpoint（Base URL + `/audio/transcriptions`） | `https://asr.example.com/v1/audio/transcriptions` | **要這個** |

- 兔白**不會**自動加 `/v1`，也**不會**自動加 `/audio/transcriptions`。服務說明寫的完整地址是什麼就填什麼；說明只給 Base URL 時，自己在後面接上 `/audio/transcriptions`。
- 地址必須是 `https://` 開頭，不能帶 `?引數`、`#片段` 或賬號密碼。
- 本機服務（`http://127.0.0.1` 或 `http://localhost`）：儲存和實際識別接受，但對話方塊裡的兩個測試按鈕只接受 https，會顯示設定格式 ✗。兔白未實測本機 http 服務。

## 已預填、不用改

沒有預填欄位。

## 測試：成功時會看到什麼

1. 點“免費檢查（不上傳音訊）”。兔白去掉地址末尾的 `/audio/transcriptions`，帶著 Key 讀取 `/models` 列表（例如 `https://asr.example.com/v1/models`）：
   - 設定格式 ✓、服務可以連線 ✓。
   - 認證成功（API Key 有效）✓；服務拒絕 Key 時顯示 ✗“服務拒絕了這個 API Key（HTTP 401）。”；服務沒有模型列表時顯示 ?“模型列表返回 HTTP 404；無法判斷金鑰是否有效。”（不影響使用）。
   - 指定模型可用 ✓ 表示列表裡有你填的模型；✗“模型列表裡沒有 …”表示名字對不上。
2. 點“試識別一小段…”。確認框會寫明上傳到你填的域名，費用“無法事先估算”。選“上傳自帶測試音訊”（約 6 秒英文合成語音，不含你的素材）或“選擇我的音訊…”（60 秒以內）。
   - 實際短音訊識別 ✓“識別出 N 段文字。”表示能用。
   - 回傳時間戳 ✓“有字/詞級時間（N 個時間片）”表示服務回了 `words`；顯示 ? 和“只有句段起止時間……”表示沒有逐詞時間（可能只有句段時間，也可能完全沒有）。
   - 回傳說話人 ✓ 表示服務回了 `speaker`；— 表示沒有。
3. 結果滿意再點“儲存”或“儲存並用於識別”。

## 費用

由你使用的服務決定，兔白無法估算（確認框會寫“無法事先估算”）。自己架設時，費用是你自己的電腦或伺服器、電費和頻寬。

## 隱私：會傳送什麼

- 每段音訊（16 kHz 單聲道 WAV，只有聲音，不含畫面）和一段提示文字 → 你填寫的地址。提示文字包括字幕場景、**素材檔名**和你確認過的專名寫法，最多 900 字。
- 對方怎麼儲存這些資料，由那個服務決定。
- API Key 加密儲存在本機（Windows 用 DPAPI；macOS 用鑰匙串，鑰匙串不可用時只在本次執行期間儲存，不寫成明文），不寫進工程、日誌或匯出檔案。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 設定格式 ✗“還沒有填寫 API Key。” | Key 欄空著 | 服務不檢查 Key 時也隨便填一串，例如 `local` |
| 設定格式 ✗“服務地址無效：需要 https 開頭的完整地址。” | 地址不是 https；或是本機 http 服務 | 改用 https 地址；本機 http 服務可直接儲存，再用一小段真實素材試跑 |
| 提示地址“不能包含賬號、密碼、查詢引數或片段” | 地址裡有 `?…`、`#…` 或 `使用者名稱:密碼@` | 刪掉這些部分；必須靠查詢引數驗證的服務，這一項用不了 |
| 提示“ASR API 缺少模型名稱。” | 模型欄空著 | 填服務要求的模型名 |
| 服務可以連線 ✗“連不上服務：…” | 域名寫錯、服務沒開、網路或防火牆攔截 | 在瀏覽器開啟 Base URL 看有沒有回應；確認服務正在執行 |
| 認證成功 ✗（HTTP 401 / 403） | Key 錯或已失效 | 到服務那邊重新複製 Key |
| 指定模型可用 ✗ | 模型名與服務列表不一致 | 照列表裡的寫法填（區分大小寫、斜槓） |
| 試識別 HTTP 404 | 地址路徑不對，常見是少了或多了 `/v1` | 對照服務說明，填完整請求 Endpoint |
| 試識別 HTTP 400 或 422 | 服務不接受表單裡的 `file` / WAV / `prompt`（兔白已自動改 `json` 仍失敗） | 確認服務支援 OpenAI 格式的表單上傳和 WAV |
| 多次重試後失敗，錯誤裡有“Expecting value”之類的字樣 | 服務回的不是 JSON：可能是地址路徑不對、對方回了網頁，也可能服務只回純文字 | 先按“HTTP 404”那一行核對地址；地址正確就讓服務回 JSON（`json` 或 `verbose_json`） |
| 識別成功，但回傳時間戳 顯示 ? | 服務只回 `text`，或只有 `segments` | 讓服務在 `verbose_json` 裡預設帶 `words`；否則主力轉寫改用有字/詞級時間的服務 |

## 進階（一般使用者可跳過）

- 失敗重試：HTTP 429 / 500 / 502 / 503 / 504 或連線錯誤會等待後重試，同一段最多嘗試 6 次；其他錯誤碼直接失敗。
- 時間換算：服務回的 `start` / `end` 以秒計、從這一小段開頭算起，兔白再加上這段在整片裡的位置。
- 免費檢查用的地址：去掉末尾的 `/audio/transcriptions`；剩下的路徑不為空就接 `/models`，為空就接 `/v1/models`。
- 程式位置：請求在 `twobyteasr/asr.py` 的 `call_qwen_asr_api`（`openai_transcription` 分支），回應解析在同一檔案的 `_extract_transcription_segments` / `_extract_transcription_words`；地址規則在 `twobyteasr/llm_config.py` 的 `validate_transport_url`；測試按鈕在 `twobyteasr/cloud_api_test.py`。

## 來源（2026-10-14 核對）

- OpenAI 轉寫介面格式（請求欄位、`verbose_json` 的 `segments` / `words`）：<https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create>
- 兔白當前程式碼（只讀核對）：`twobyteasr/asr.py`、`twobyteasr/llm_config.py`、`twobyteasr/cloud_api_test.py`、`twobyteasr/api_setup_catalog.py`、`twobyteasr/ui.py`（`ASR_API_PRESETS`）。
