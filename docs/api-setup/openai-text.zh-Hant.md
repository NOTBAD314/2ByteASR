<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 OpenAI（文字 AI）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯。**只發送字幕文字，不上傳音訊** |
| 在哪裡填 | 「AI 智慧斷句設定」→“AI 服務”選 **OpenAI API** |
| 地區 | 官方 API 支援國家 / 地區列表裡**沒有中國大陸、香港、澳門**（有臺灣）。在不支援的地區使用會報 403，官方還說賬戶可能被封禁或停用 |
| 要花錢嗎 | 要。預付額度（prepaid credits）用完會報錯；最低充值金額本次沒能開啟官方幫助頁確認，待核實 |
| 兔白預填的模型 | `gpt-4.1-mini`：官方仍在列、沒有停用通知 |
| 和《OpenAI 轉寫》共用 Key 嗎 | 可以，同一個 OpenAI API Key |
| 兔白驗證狀態 | 已有接入；本輪未用真實金鑰重新實測 |

## 它在兔白裡做什麼

- **AI 斷句**：把識別出的整段文字切成適合看的字幕句子（“全文斷句使用 AI”）。
- **字幕校對**：修正錯別字、專有名詞、標點（“字幕校對使用 AI”）。
- **翻譯**：日語任務識別後翻成中文，以及字幕工作室裡的“翻譯 / 生成雙語字幕”。翻譯用的是“字幕校對模型”那一套設定。
- 同一套設定也用於術語整理、字幕工作室的“AI 設計”等輔助功能。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| API 平台（註冊 / 登入） | <https://platform.openai.com/> | 本次開啟時被網站的機器人驗證攔下，待核實 |
| API Key 頁面 | <https://platform.openai.com/settings/organization/api-keys> | 需登入，待核實（官方 API 參考與錯誤碼頁連結到這裡） |
| 賬單（充值） | <https://platform.openai.com/settings/organization/billing> | 需登入，待核實 |
| 支援的國家 / 地區 | <https://developers.openai.com/api/docs/supported-countries> | |
| 模型 `gpt-4.1-mini` | <https://developers.openai.com/api/docs/models/gpt-4.1-mini> | |
| 價格 | <https://developers.openai.com/api/docs/pricing> | |
| 錯誤碼 | <https://developers.openai.com/api/docs/guides/error-codes> | |
| API 參考（認證方式） | <https://developers.openai.com/api/reference/overview> | |

## 從未註冊開始

1. 先確認你所在的國家 / 地區在官方支援列表裡（見上表）。
2. 開啟 <https://platform.openai.com/> 註冊並登入。註冊需要什麼（郵箱、手機號驗證等）：需要登入才能看到，待核實。
3. **充值**：在賬單頁面 <https://platform.openai.com/settings/organization/billing> 購買預付額度。官方錯誤碼頁寫明，額度用完時報“Your organization has no prepaid credits remaining”。最低金額、付款方式、是否自動續充：本次沒能開啟官方幫助中心（有機器人驗證），待核實。
4. **建立 API Key**：開啟 <https://platform.openai.com/settings/organization/api-keys> 建立一個 Key 並複製。按鈕名稱、完整 Key 是否只顯示一次：需要登入才能看到，待核實。建議一建立就複製下來。
5. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選 OpenAI）
6. 在“AI 服務”下拉里選 **OpenAI API**（新安裝時預設選的是“Grok Account”，記得改）。
7. 把 Key 貼進“API 金鑰”，點“測試連線”。
8. 看到“連線測試通過”後，點對話方塊右下角“儲存設定”。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務、各自填金鑰。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 單獨開通、申請模型許可權 | 官方模型頁沒有提到需要申請 `gpt-4.1-mini` |
| 組織（organization） | 官方錯誤碼：賬戶不屬於任何組織會報 401，需要被邀請加入或聯絡 OpenAI |
| 充值 | 需要（預付額度） |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| AI 服務 | 選用哪家服務 | `OpenAI API` | 下拉選擇 | 需要自己選 |
| API 金鑰 | 證明是你的賬戶在呼叫 | 一長串字元（輸入框提示“請輸入 API Key”） | API Key 頁面 | 否。如果你已在「申請與設定 API」儲存過《OpenAI 轉寫》的 Key，這裡會直接顯示“已配置：…”，不用再貼 |
| 模型 | 用哪個模型 | `gpt-4.1-mini` | 官方模型頁 | 是 |
| Base URL（在“進階設定：Base URL、協議與輸出能力”裡） | 服務地址 | `https://api.openai.com/v1` | 官方 API 參考 | 是，不用改 |
| 協議 / Protocol（進階） | 請求格式 | `Auto` | — | 是，不用改。對 OpenAI，Auto 會用 Responses 介面 |
| JSON Mode、Structured Output（進階） | 要求模型按固定格式回答 | 勾選 | — | 已勾選，不用改 |
| stream（進階） | 灰色不可選；兔白目前不用流式 | — | — | — |

地址說明（這張卡片只有“Base URL”一欄，兔白會自己補上後面的路徑）：

| 名稱 | 值 |
| --- | --- |
| 官方網站 | <https://platform.openai.com/> |
| API Host | `api.openai.com` |
| Base URL（填在兔白裡的） | `https://api.openai.com/v1`（預填，不用改） |
| 完整請求 Endpoint | `https://api.openai.com/v1/responses`（協議為 Auto 或“Responses API”時）；選“Chat Completions”時是 `https://api.openai.com/v1/chat/completions` |

注意：協議為 Auto 時，進階區“實際請求：”一行目前顯示的是 `…/chat/completions`，但兔白對 OpenAI 實際發到 `…/responses`。兩種介面官方都支援 `gpt-4.1-mini`，不影響使用。

## 測試時會看到什麼

**測試連線**：兔白用這張卡片上的服務、模型、地址和金鑰（剛貼進去還沒儲存的金鑰也會用）發一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。會產生極少量費用。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · 原生 JSON Schema＋本地校驗 · 1.23s`（最後是用時）。如果卡片上選的服務和上次儲存的不同，後面還會加“尚未儲存：點選儲存後 AI 設計才會使用此 Provider”。
- 首頁 AI 卡片下方會顯示“連線正常”；失敗顯示“連線失敗”；還沒測過顯示“尚未測試連線”。
- 失敗時狀態行顯示服務商的錯誤，例如 `Responses API HTTP 401：……`，對照下表處理。

**重新整理模型**：讀取你賬戶能用的模型列表（不讓模型生成文字）。成功顯示“已發現 N 個模型 · 可搜尋選擇或手動輸入”。填完金鑰、離開輸入框時也會自動讀一次。列表裡會有很多非文字模型，請選文字聊天模型。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “當前模型（openai）缺少 API 金鑰……” | 還沒貼金鑰 | 把 Key 貼進“API 金鑰”再測 |
| `HTTP 401`，內容含 “Incorrect API key provided” 或 “Invalid Authentication” | Key 填錯或已刪除 | 到 API Key 頁面新建一個，重新貼入 |
| `HTTP 401`，內容含 “You must be a member of an organization” | 賬戶不屬於任何組織 | 請組織管理員邀請你加入，或聯絡 OpenAI |
| `HTTP 403`，內容含 “Country, region, or territory not supported” | 你所在地區不在官方支援列表 | 無法在本地區使用；改用 DeepSeek、阿里雲百鍊等其他服務 |
| `HTTP 429`，內容含 `credit_balance_exhausted` | 預付額度用完（官方：重試沒有用，要先充值） | 到賬單頁面充值後再測 |
| `HTTP 429`，內容含 “Rate limit reached” | 請求太快 | 等一會兒再試；少開幾個同時跑的任務 |
| `HTTP 404` 或提示模型不存在 | 模型名寫錯，或賬戶無權使用該模型 | “模型”改回 `gpt-4.1-mini`，或點“重新整理模型”從列表裡選 |
| `HTTP 500` / `HTTP 503`（`server_is_overloaded`） | 服務端故障或模型過載 | 稍後再試 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 按上表查原因，處理後重新識別；只差少量字幕時，可在字幕工作室“字幕列表”上方點“AI 校對”看修改建議 |

## 隱私與費用

- **傳到哪裡**：`api.openai.com`（OpenAI，境外）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作室的“AI 設計”在模型支援看圖時，可能附帶畫面截圖或字幕效果預覽圖。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只保留到退出軟體，絕不存明文。不寫進工程、日誌或匯出檔案。
- **費用**（官方價格頁，標準檔，2026-10-14 核對，單位：美元 / 百萬 token）：

| 模型 | 輸入 | 快取輸入 | 輸出 |
| --- | --- | --- | --- |
| `gpt-4.1-mini`（兔白預填） | 0.40 | 0.10 | 1.60 |
| `gpt-5-mini`（官方模型頁建議複雜任務先試它；兔白未預設、未實測） | 0.25 | 0.025 | 2.00 |

價格頁沒有為這些模型列出免費額度。一段影片要花多少取決於字幕字數和重試次數，兔白沒有固定數字。價格以官方頁面為準。

## 進階（一般使用者可跳過）

- 協議 Auto 時，兔白對 OpenAI 傳送 `POST https://api.openai.com/v1/responses`，帶 `Authorization: Bearer <金鑰>`，按 JSON Schema 要求結構化輸出。改選“Chat Completions”時傳送 `POST …/chat/completions`。測試連線的內容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 個輸出 token。
- “重新整理模型”呼叫 `GET https://api.openai.com/v1/models`。
- 本機沒有儲存金鑰時，兔白也會讀取環境變數 `OPENAI_API_KEY`；已儲存的金鑰優先。

## 來源（2026-10-14 核對）

- 支援的國家 / 地區：<https://developers.openai.com/api/docs/supported-countries>
- 模型 `gpt-4.1-mini`：<https://developers.openai.com/api/docs/models/gpt-4.1-mini>
- 價格：<https://developers.openai.com/api/docs/pricing>
- 錯誤碼：<https://developers.openai.com/api/docs/guides/error-codes>（頁面連結了 API Key 頁、賬單頁、組織設定頁）
- API 參考（認證）：<https://developers.openai.com/api/reference/overview>
- 快速開始：<https://developers.openai.com/api/docs/quickstart>
- 未能開啟：<https://platform.openai.com/>（機器人驗證）；幫助中心的預付賬單說明（機器人驗證）。API Key 頁、賬單頁需要登入。
