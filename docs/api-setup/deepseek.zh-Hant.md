<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 DeepSeek（文字 AI）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯。**只發送字幕文字，不上傳音訊** |
| 在哪裡填 | 「AI 智慧斷句設定」，不是「申請與設定 API」 |
| 要花錢嗎 | 要。按用量（token）從賬戶餘額扣費，用前要充值；線上充值前要先完成實名認證 |
| 兔白預填的模型 | `deepseek-v4-flash`。官方說這是**舊名字**：仍可呼叫，但實際由 DeepSeek-V4.1-Flash 回答、按 Flash 價格計費。官方推薦新名字 `deepseek-flash`，可在“模型”下拉里改選 |
| 兔白驗證狀態 | 已有接入；本輪未用真實金鑰重新實測 |

## 它在兔白裡做什麼

- **AI 斷句**：把識別出的整段文字切成適合看的字幕句子（“全文斷句使用 AI”）。
- **字幕校對**：修正錯別字、專有名詞、標點（“字幕校對使用 AI”）。
- **翻譯**：日語任務識別後翻成中文，以及字幕工作室裡的“翻譯 / 生成雙語字幕”。翻譯用的是“字幕校對模型”那一套設定。
- 同一套設定也用於術語整理、字幕工作室的“AI 設計”等輔助功能。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| 開放平台（註冊 / 登入） | <https://platform.deepseek.com/sign_in> | 公開頁：手機號驗證碼登入、密碼登入、微信掃碼登入 |
| API Keys 頁面 | <https://platform.deepseek.com/api_keys> | 需登入，待核實 |
| 充值頁面 | <https://platform.deepseek.com/top_up> | 需登入，待核實 |
| API 文件 | <https://api-docs.deepseek.com/zh-cn/> | Base URL、模型名 |
| 模型與價格 | <https://api-docs.deepseek.com/zh-cn/quick_start/pricing> | |
| 錯誤碼 | <https://api-docs.deepseek.com/zh-cn/quick_start/error_codes> | |
| 限速說明 | <https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit> | |
| 常見問題（充值、實名、餘額） | <https://static.deepseek.com/faq/index.html?lang=zh#/category/4> | |

## 從未註冊開始

1. 開啟 <https://platform.deepseek.com/sign_in>，用手機號收驗證碼登入。官方頁面寫著“未註冊的手機號將自動註冊”。也可以用密碼登入或微信掃碼登入。
2. **實名認證**：官方常見問題寫明，完成實名認證後才能在“充值”頁面用支付寶 / 微信線上充值。個人認證和企業認證的權益沒有差別。實名入口和要準備什麼，需要登入才能看到，待核實。
3. **充值**：開啟 <https://platform.deepseek.com/top_up> 充值。最低充值金額需要登入才能看到，待核實。官方說充值餘額永久有效、不會過期。
4. **建立 API Key**：開啟 <https://platform.deepseek.com/api_keys> 建立一個 Key 並複製。按鈕名稱、完整 Key 是否只顯示一次：需要登入才能看到，待核實。建議一建立就複製下來。
5. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選 DeepSeek）
6. 在“AI 服務”下拉里選 **DeepSeek API**（新安裝時預設選的是“Grok Account”，記得改）。
7. 把 Key 貼進“API 金鑰”，點“測試連線”。
8. 看到“連線測試通過”後，點對話方塊右下角“儲存設定”。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務、各自填金鑰。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 單獨開通服務、申請模型許可權 | 官方檔案沒有提到 |
| 實名認證 | 線上充值前需要（官方常見問題） |
| 充值 | 需要。餘額用完會報 402。官方：如果同時有贈送餘額和充值餘額，先扣贈送餘額；新賬戶是否有贈送餘額，官方檔案沒寫 |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| AI 服務 | 選用哪家服務 | `DeepSeek API` | 下拉選擇 | 需要自己選 |
| API 金鑰 | 證明是你的賬戶在呼叫 | 一長串字元（輸入框提示“請輸入 API Key”） | API Keys 頁面 | 否。儲存後再開啟會顯示“已配置：Windows DPAPI / …”，留空表示不修改 |
| 模型 | 用哪個模型 | `deepseek-v4-flash`（預填）；建議改選 `deepseek-flash`；更強更貴的是 `deepseek-v4-pro` | 官方價格頁 | 是 |
| Base URL（在“進階設定：Base URL、協議與輸出能力”裡） | 服務地址 | `https://api.deepseek.com/v1` | 官方文件 | 是，不用改 |
| 協議 / Protocol（進階） | 請求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（進階） | 要求模型按固定格式回答 | 勾選 | — | 已勾選，不用改 |
| stream（進階） | 灰色不可選；兔白目前不用流式 | — | — | — |

地址說明（這張卡片只有“Base URL”一欄，兔白會自己補上後面的路徑）：

| 名稱 | 值 |
| --- | --- |
| 官方網站 | <https://platform.deepseek.com/> |
| API Host | `api.deepseek.com` |
| Base URL（填在兔白裡的） | `https://api.deepseek.com/v1`（預填，不用改）。官方文件現在寫的是不帶 `/v1` 的 `https://api.deepseek.com`；只有帶 `/v1` 的地址報 404 時才需要改成它（見文末進階）。兔白不會拼出 `/v1/v1` |
| 完整請求 Endpoint | `https://api.deepseek.com/v1/chat/completions`（進階區“實際請求：”一行會顯示） |

## 測試時會看到什麼

**測試連線**：兔白用這張卡片上的服務、模型、地址和金鑰（剛貼進去還沒儲存的金鑰也會用）發一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。會產生極少量費用。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · 相容 JSON／本地校驗 · 1.23s`（最後是用時）。如果卡片上選的服務和上次儲存的不同，後面還會加“尚未儲存：點選儲存後 AI 設計才會使用此 Provider”。
- 首頁 AI 卡片下方會顯示“連線正常”；失敗顯示“連線失敗”；還沒測過顯示“尚未測試連線”。
- 失敗時狀態行顯示服務商的錯誤，例如 `HTTP 401：……`，對照下表處理。

**重新整理模型**：讀取 DeepSeek 的模型列表（不讓模型生成文字）。成功顯示“已發現 N 個模型 · 可搜尋選擇或手動輸入”。填完金鑰、離開輸入框時也會自動讀一次。列表讀不到時仍可手動輸入模型名。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “當前模型（deepseek）缺少 API 金鑰……” | 還沒貼金鑰 | 把 Key 貼進“API 金鑰”再測 |
| “當前模型的 API 地址無效……” | Base URL 被改壞 | 進階設定裡把 Base URL 改回 `https://api.deepseek.com/v1` |
| `HTTP 401` | Key 填錯，或已在平台刪除（官方：API key 錯誤，認證失敗） | 到 API Keys 頁面重新複製，或新建一個 |
| `HTTP 402` | 餘額不足 | 到充值頁面充值；還沒實名的先完成實名 |
| `HTTP 400` 或 `HTTP 422` | 請求格式或引數不被接受，常見是模型名寫錯 | “模型”改回下拉里的 `deepseek-flash`，Base URL 改回預填值，再測 |
| `HTTP 429` | 請求太快或同時請求太多（官方：併發上限 `deepseek-flash` 2500、`deepseek-v4-pro` 500，按賬戶計） | 等一會兒再試；少開幾個同時跑的任務 |
| `HTTP 500` 或 `HTTP 503` | 伺服器故障或繁忙 | 稍後再試 |
| 測試等了很久才失敗 | 服務繁忙時官方會先返回空行等待；10 分鐘還沒開始推理會斷開 | 測試最多等 45 秒；稍後再測 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 按上表查原因（多半是餘額或限流），處理後重新識別；只差少量字幕時，可在字幕工作室“字幕列表”上方點“AI 校對”看修改建議 |

## 隱私與費用

- **傳到哪裡**：`api.deepseek.com`（DeepSeek）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作室的“AI 設計”在模型支援看圖時，可能附帶畫面截圖或字幕效果預覽圖。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只保留到退出軟體，絕不存明文。不寫進工程、日誌或匯出檔案。
- **費用**（官方價格頁，2026-10-14 核對，單位：元 / 百萬 token，閒時 / 峰時）：

| 模型 | 輸入（快取命中） | 輸入（快取未命中） | 輸出 |
| --- | --- | --- | --- |
| `deepseek-flash`（DeepSeek-V4.1-Flash） | 0.02 / 0.04 | 1 / 2 | 4 / 8 |
| `deepseek-v4-pro`（DeepSeek-V4-Pro-0813） | 0.15 / 0.30 | 4.5 / 9.0 | 13.5 / 27.0 |

峰時是北京時間週一至週五（法定節假日除外）9:00–12:00 和 14:00–18:00，其餘時間（含週末、節假日）是閒時，閒時價格為峰時的一半。預填的舊名 `deepseek-v4-flash` 按 Flash 價格計費。一段影片要花多少，取決於字幕字數和重試次數，兔白沒有固定數字。官方說價格可能調整，請以價格頁為準。

## 進階（一般使用者可跳過）

- 兔白髮送 `POST {Base URL}/chat/completions`，帶 `Authorization: Bearer <金鑰>`；需要按 JSON 回答時附 `response_format: {"type": "json_object"}`。測試連線的內容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 個輸出 token。
- “重新整理模型”呼叫 `GET {Base URL}/models`。
- 關於 `/v1`：2026-10-14 不帶金鑰訪問 `https://api.deepseek.com/v1/models` 和 `https://api.deepseek.com/models`，兩者都回“需要認證”（HTTP 401），不是“找不到”。官方文件沒有再提 `/v1` 寫法；如果哪天帶 `/v1` 的地址報 404，把 Base URL 改成 `https://api.deepseek.com`。
- 本機沒有儲存金鑰時，兔白也會讀取環境變數 `DEEPSEEK_API_KEY`；已儲存的金鑰優先。
- 兔白把 `deepseek-v4-flash-vision-exp` 當作已下線模型攔截；官方說這個舊名仍可呼叫（同樣由 V4.1-Flash 回答）。

## 來源（2026-10-14 核對）

- 註冊 / 登入頁：<https://platform.deepseek.com/sign_in>（網頁需要瀏覽器執行指令碼，用瀏覽器開啟讀取）
- API 文件首頁：<https://api-docs.deepseek.com/zh-cn/>、<https://api-docs.deepseek.com/>
- 模型與價格：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing>
- 錯誤碼：<https://api-docs.deepseek.com/zh-cn/quick_start/error_codes>（頁面裡“建立 API key”“充值”連結分別指向 API Keys 頁和充值頁）
- 限速：<https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit>
- 常見問題“API相關”：<https://static.deepseek.com/faq/index.html?lang=zh#/category/4>（讀了“如何充值”“餘額是否會過期”“個人實名認證與企業實名認證有什麼區別？”“若發現 API key 洩漏怎麼辦”）
- API Keys 頁、充值頁需要登入，本次沒有看到裡面的內容。
