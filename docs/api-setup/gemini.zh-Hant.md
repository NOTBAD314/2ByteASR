<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 Google Gemini（文字 AI）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯。**只發送字幕文字，不上傳音訊** |
| 在哪裡填 | 「AI 智慧斷句設定」→“AI 服務”選 **Gemini API** |
| 地區 | 官方“可用地區”頁列出的國家和地區裡**有 Taiwan（臺灣）**；**沒有中國大陸、Hong Kong（香港）、Macao（澳門）**。不在列表裡的地區不能用 Google AI Studio 和 Gemini API。另外官方要求年滿 18 歲 |
| 要花錢嗎 | 兔白預填的三個模型都有免費檔（輸入、輸出均“Free of charge”），但免費檔的內容會被用於改進 Google 產品。要更高額度或不讓內容被使用，需在 AI Studio 設定付費（預付最少 5 美元） |
| 兔白預填的模型 | `gemini-3.8-flash`：官方穩定版，官方建議新專案用 3.8 Flash 或 3.5 Flash-Lite |
| 兔白驗證狀態 | 已有接入；本輪未用真實金鑰重新實測 |

## 它在兔白裡做什麼

- **AI 斷句**：把識別出的整段文字切成適合看的字幕句子（“全文斷句使用 AI”）。
- **字幕校對**：修正錯別字、專有名詞、標點（“字幕校對使用 AI”）。
- **翻譯**：日語任務識別後翻成中文，以及字幕工作室裡的“翻譯 / 生成雙語字幕”。翻譯用的是“字幕校對模型”那一套設定。
- 同一套設定也用於術語整理、字幕工作室的“AI 設計”等輔助功能。
- 兔白通過 Gemini 的 “OpenAI 相容介面” 呼叫。官方說明這套相容介面“仍處於 beta”。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| 建立 / 檢視 API Key（Google AI Studio） | <https://aistudio.google.com/apikey> | 會跳轉到 Google 登入，需登入，待核實 |
| API Key 說明 | <https://ai.google.dev/gemini-api/docs/api-key> | |
| 可用地區 | <https://ai.google.dev/gemini-api/docs/available-regions> | |
| OpenAI 相容介面 | <https://ai.google.dev/gemini-api/docs/openai> | Base URL |
| 模型列表 | <https://ai.google.dev/gemini-api/docs/models> | |
| 價格與免費檔 | <https://ai.google.dev/gemini-api/docs/pricing> | |
| 付費設定（預付 / 後付） | <https://ai.google.dev/gemini-api/docs/billing> | |
| 錯誤碼 | <https://ai.google.dev/gemini-api/docs/api-errors> | |
| 故障排查 | <https://ai.google.dev/gemini-api/docs/troubleshooting> | |

## 從未註冊開始

1. 先確認你所在的國家 / 地區在官方可用地區列表裡（見上文），並且已滿 18 歲。官方說如果 Google 賬戶還沒驗證年齡，也會打不開 AI Studio。
2. 用 Google 賬戶登入 <https://aistudio.google.com/apikey>。
3. 點“Create API key”（官方說明裡的按鈕名）。官方：每個 Key 都屬於一個 Google Cloud 專案；新使用者 AI Studio 會自動建一個預設專案和 Key；已有 Google Cloud 賬戶的使用者不會自動建，需要先匯入一個專案再建 Key。官方還說，自 2026-05-28 起在 AI Studio 新建的 Key 都是“auth key”（授權金鑰）。完整 Key 是否只顯示一次：需要登入才能看到，待核實。
4. 只用免費檔的話，到這裡就可以了。要付費：在 AI Studio 點“Set up billing”（官方說明裡的按鈕名），繫結 Cloud Billing 賬戶並預付額度（見下一節）。
5. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選 Gemini）
6. 在“AI 服務”下拉里選 **Gemini API**（新安裝時預設選的是“Grok Account”，記得改）。
7. 把 Key 貼進“API 金鑰”，點“測試連線”。
8. 看到“連線測試通過”後，點對話方塊右下角“儲存設定”。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務、各自填金鑰。

## 需不需要開通服務、付費或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| Google Cloud 專案 | 每個 Key 都屬於一個專案；新使用者由 AI Studio 自動建立 |
| 付費 | 免費檔不需要。付費檔：在 AI Studio 點“Set up billing”。新使用者預設是預付方式，最少預付 5 美元（或等值其他貨幣），最多 5000 美元；也有月底結算的後付方式 |
| 預付額度用完 | 官方：餘額為 0 時，這個結算賬戶下所有專案的所有 Key 會同時停用，請求報 402；不會自動退回免費檔，要麼充值，要麼關掉付費 |
| 免費檔的資料 | 官方價格頁：免費檔“Content used to improve our products”；付費檔“not used” |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| AI 服務 | 選用哪家服務 | `Gemini API` | 下拉選擇 | 需要自己選 |
| API 金鑰 | 證明是你的賬戶在呼叫 | AI Studio 裡建立的 Key（輸入框提示“請輸入 API Key”） | <https://aistudio.google.com/apikey> | 否 |
| 模型 | 用哪個模型 | `gemini-3.8-flash`（預填）；也可選 `gemini-3.6-flash`、`gemini-3.5-flash-lite`（更便宜） | 官方模型頁 | 是 |
| Base URL（在“進階設定：Base URL、協議與輸出能力”裡） | 服務地址 | `https://generativelanguage.googleapis.com/v1beta/openai` | 官方 OpenAI 相容說明 | 是，不用改 |
| 協議 / Protocol（進階） | 請求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（進階） | 要求模型按固定格式回答 | 勾選 | — | 已勾選，不用改 |
| stream（進階） | 灰色不可選；兔白目前不用流式 | — | — | — |

地址說明（這張卡片只有“Base URL”一欄，兔白會自己補上後面的路徑）：

| 名稱 | 值 |
| --- | --- |
| 官方網站 | Google AI Studio <https://aistudio.google.com/apikey>（需登入）；文件 <https://ai.google.dev/gemini-api/docs/openai> |
| API Host | `generativelanguage.googleapis.com` |
| Base URL（填在兔白裡的） | `https://generativelanguage.googleapis.com/v1beta/openai`（預填，不用改）。官方示例末尾多一個 `/`，兔白會自動去掉，寫不寫都一樣 |
| 完整請求 Endpoint | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` |

## 測試時會看到什麼

**測試連線**：兔白用這張卡片上的服務、模型、地址和金鑰（剛貼進去還沒儲存的金鑰也會用）發一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。免費檔不收費；付費檔會產生極少量費用。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · 相容 JSON／本地校驗 · 1.23s`（最後是用時）。如果卡片上選的服務和上次儲存的不同，後面還會加“尚未儲存：點選儲存後 AI 設計才會使用此 Provider”。
- 首頁 AI 卡片下方會顯示“連線正常”；失敗顯示“連線失敗”；還沒測過顯示“尚未測試連線”。
- 失敗時狀態行顯示服務商的錯誤，例如 `HTTP 403：……`，對照下表處理。

**重新整理模型**：讀取你的 Key 能用的 Gemini 模型列表（不讓模型生成文字）。成功顯示“已發現 N 個模型 · 可搜尋選擇或手動輸入”。填完金鑰、離開輸入框時也會自動讀一次。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “當前模型（gemini）缺少 API 金鑰……” | 還沒貼金鑰 | 把 Key 貼進“API 金鑰”再測 |
| 開啟 AI Studio 顯示 “Google AI Studio is not available in your region” | 所在地區不在官方列表 | 無法在本地區使用；改用 DeepSeek、阿里雲百鍊等其他服務 |
| `HTTP 400`，內容含 `failed_precondition` | 前置條件不滿足，官方舉例“結算未啟用” | 到 AI Studio 檢查這個專案的付費狀態 |
| `HTTP 401` 或 `HTTP 403` | Key 無效、過期，或沒有許可權；官方還說 Gemini API 會拒絕“未加限制的標準 Key” | 回 AI Studio 新建一個 Key 再貼入（新建的 Key 預設就是 auth key） |
| `HTTP 402` | 預付額度用完 | 在 AI Studio 充值或開啟自動充值；官方說充值前重試沒有用 |
| `HTTP 404`，提示模型不存在 | 模型名寫錯，或模型已下線 | “模型”改回 `gemini-3.8-flash`，或點“重新整理模型”從列表裡選 |
| `HTTP 429` | 每分鐘請求數 / token 超限，或當天額度用完 | 等一會兒再試；當天額度用完要等額度重置，或申請提高額度 |
| `HTTP 500` / `503` / `504` | 服務端故障、過載或超時 | 稍後再試 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 按上表查原因（多半是限流或額度），處理後重新識別；只差少量字幕時，可在字幕工作室“字幕列表”上方點“AI 校對”看修改建議 |

## 隱私與費用

- **傳到哪裡**：`generativelanguage.googleapis.com`（Google，境外）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作室的“AI 設計”在模型支援看圖時，可能附帶畫面截圖或字幕效果預覽圖。用免費檔時，官方說這些內容會被用於改進 Google 產品。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只保留到退出軟體，絕不存明文。不寫進工程、日誌或匯出檔案。
- **費用**（官方價格頁，標準檔，文字，2026-10-14 核對，單位：美元 / 百萬 token）：

| 模型 | 免費檔 | 付費：輸入 | 付費：輸出（含思考） |
| --- | --- | --- | --- |
| `gemini-3.8-flash` | 免費 | 0.75（至 2026-12-31）；1.50（2027-01-01 起） | 3.75（至 2026-12-31）；7.50（2027-01-01 起） |
| `gemini-3.6-flash` | 免費 | 同上 | 同上 |
| `gemini-3.5-flash-lite` | 免費 | 0.30 | 2.50 |

免費檔的用量限制本次沒有在價格頁上查到具體數字；官方可能調整免費檔，不要當作永久免費。一段影片要花多少取決於字幕字數和重試次數，兔白沒有固定數字。

## 進階（一般使用者可跳過）

- 兔白髮送 `POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`，帶 `Authorization: Bearer <金鑰>`；需要按 JSON 回答時附 `response_format: {"type": "json_object"}`。測試連線的內容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 個輸出 token。
- “重新整理模型”不走相容介面，而是呼叫 Gemini 原生的 `GET https://generativelanguage.googleapis.com/v1beta/models`，金鑰放在 `x-goog-api-key` 頭裡。
- 帶 `-high` 的名字（如 `gemini-3.8-flash-high`）是兔白“Google Antigravity”選項用的名字，不是 Gemini API 的模型名，不要填在這裡。
- 2026-05-28 起的新 Key 是 auth key。用這種 Key 呼叫 OpenAI 相容介面，官方相容說明的示例仍是直接填 Key；兔白本輪未用新 Key 實測。
- 本機沒有儲存金鑰時，兔白也會讀取環境變數 `GEMINI_API_KEY`；已儲存的金鑰優先。

## 來源（2026-10-14 核對）

- 可用地區：<https://ai.google.dev/gemini-api/docs/available-regions>（逐項核對了 C、H、M、S、T 開頭的國家 / 地區）
- API Key：<https://ai.google.dev/gemini-api/docs/api-key>
- OpenAI 相容介面：<https://ai.google.dev/gemini-api/docs/openai>
- 模型：<https://ai.google.dev/gemini-api/docs/models>
- 價格：<https://ai.google.dev/gemini-api/docs/pricing>
- 付費設定：<https://ai.google.dev/gemini-api/docs/billing>
- 錯誤碼：<https://ai.google.dev/gemini-api/docs/api-errors>
- 故障排查：<https://ai.google.dev/gemini-api/docs/troubleshooting>
- <https://aistudio.google.com/apikey> 跳轉到 Google 登入，本次沒有看到裡面的內容。
