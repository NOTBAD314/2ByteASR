<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 Claude API（文字 AI）

最後核對：2026-10-18。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯，以及字幕工作台的 AI 特效字幕。**只發送字幕文字，不上傳音訊**（AI 特效字幕可能附帶畫面截圖） |
| 在哪裡填 | 「AI 智慧斷句設定」→“AI 服務”選 **Claude API**；字幕工作台「AI 特效字幕」的服務下拉也能選 |
| 要花錢嗎 | 要。按用量計費，需要在 Claude Console 繫結付款方式或充值；官方檔案沒有提到長期免費額度 |
| 地區 | 官方“支援的國家和地區”列出了臺灣；**中國大陸、香港、澳門不在列表裡**，在這些地區註冊和呼叫都不受支援 |
| 兔白預填的模型 | `claude-opus-5-5`（預填）；更便宜的 `claude-sonnet-5-5`、最便宜最快的 `claude-haiku-5-5` |
| 接入方式 | 兔白自己的網路層直接呼叫 Anthropic Messages API（`POST /v1/messages`），沒有另裝 Anthropic 的軟體包 |
| 兔白驗證狀態 | 2026-10-18 新接入；請求格式、流式讀取、錯誤處理已用本機測試替身驗證，**還沒有用真實金鑰實測** |

## 它在兔白裡做什麼

- **AI 斷句**：把識別出的整段文字切成適合看的字幕句子（“全文斷句使用 AI”）。
- **字幕校對**：修正錯別字、專有名詞、標點（“字幕校對使用 AI”）。
- **翻譯**：日語任務識別後翻成中文，以及字幕工作台裡的“翻譯 / 生成雙語字幕”。翻譯用的是“字幕校對模型”那一套設定。
- **AI 特效字幕**：字幕工作台裡按描述生成字幕效果；模型會看到當前畫面的截圖來配色和排版。
- 同一套設定也用於術語整理等輔助功能。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| Claude Console（註冊 / 登入） | <https://platform.claude.com/> | 公開頁 |
| API Keys 頁面 | <https://platform.claude.com/settings/keys> | 需登入（官方“獲取 API Key”說明給出的地址） |
| 賬單與充值 | <https://platform.claude.com/settings/billing> | 需登入，待核實 |
| 獲取 API Key 說明 | <https://platform.claude.com/docs/en/get-api-key> | 建 Key 的步驟 |
| 支援的國家和地區 | <https://www.anthropic.com/supported-countries> | |
| 價格 | <https://platform.claude.com/docs/en/about-claude/pricing> | |
| 錯誤碼 | <https://platform.claude.com/docs/en/api/errors> | |

## 從未註冊開始

1. 開啟 <https://platform.claude.com/>，註冊並登入 Claude Console。註冊方式與驗證步驟需要在註冊流程裡才能看到，待核實。
2. **充值 / 繫結付款**：在 Console 的賬單頁（<https://platform.claude.com/settings/billing>）設定付款方式或購買額度。最低金額、付款方式：需要登入才能看到，待核實。沒有可用額度時，請求會被拒絕（見下方“常見失敗”）。
3. **建立 API Key**：開啟 <https://platform.claude.com/settings/keys>，點 **Create key**，起個名字、選有效期，然後複製。官方：完整的 Key 以 `sk-ant-` 開頭，**只在建立時顯示一次**，丟了只能新建。
4. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選 Claude API）
5. 在“AI 服務”下拉里選 **Claude API**。
6. 把 Key 貼進“API 金鑰”，點“測試連線”。
7. 看到“連線測試通過”後，點對話方塊右下角“儲存設定”。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務、各自填金鑰。

**字幕工作台的 AI 特效字幕**：工具面板「AI 設計」裡的服務下拉選 **Claude API**，用的是同一個金鑰（在上面的設定裡填一次即可）。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 單獨開通、申請模型許可權 | 官方檔案沒有提到；`claude-opus-5-5` 等模型建好 Key 即可呼叫 |
| 充值 / 付款方式 | 需要 |
| 組織角色 | 官方：API Keys 頁的 **Create key** 按鈕是灰的，說明你的角色不能建 Key，請組織管理員調整或代建 |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| AI 服務 | 選用哪家服務 | `Claude API` | 下拉選擇 | 需要自己選 |
| API 金鑰 | 證明是你的賬戶在呼叫 | `sk-ant-api03-…` 一長串 | API Keys 頁面 | 否 |
| 模型 | 用哪個模型 | `claude-opus-5-5`（預填）；`claude-sonnet-5-5`、`claude-haiku-5-5` | 官方價格頁、模型列表 | 是 |
| Base URL（在“進階設定：Base URL、協議與輸出能力”裡） | 服務地址 | `https://api.anthropic.com/v1` | 官方文件 | 是，不用改 |
| 協議 / Protocol（進階） | 請求格式 | `Auto`（Claude 一律用 Messages API） | — | 是，不用改 |
| JSON Mode、Structured Output（進階） | 要求模型按固定格式回答 | 勾選 | — | 已勾選，不用改 |

地址說明（這張卡片只有“Base URL”一欄，兔白會自己補上後面的路徑）：

| 名稱 | 值 |
| --- | --- |
| 官方網站 | <https://platform.claude.com/> |
| API Host | `api.anthropic.com` |
| Base URL（填在兔白裡的） | `https://api.anthropic.com/v1`（預填，不用改） |
| 完整請求 Endpoint | `https://api.anthropic.com/v1/messages` |

## 測試時會看到什麼

**測試連線**：兔白用這張卡片上的服務、模型、地址和金鑰（剛貼進去還沒儲存的金鑰也會用）發一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。會產生極少量費用。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · 相容 JSON／本地校驗 · 1.23s`（最後是用時）。
- 首頁 AI 卡片下方會顯示“連線正常”；失敗顯示“連線失敗”；還沒測過顯示“尚未測試連線”。
- 失敗時狀態行顯示服務商的錯誤，例如 `Provider HTTP 401：……`，對照下表處理。

**重新整理模型**：讀取你賬戶能用的模型列表（`GET /v1/models`，不讓模型生成文字）。成功顯示“已發現 N 個模型 · 可搜尋選擇或手動輸入”。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “Claude 缺少 API Key……” | 還沒貼金鑰 | 把 Key 貼進“API 金鑰”再測 |
| `HTTP 401`（authentication_error） | 官方：Key 格式不對、已撤銷或已過期 | 到 API Keys 頁面新建一個 Key，重新貼入 |
| `HTTP 402`（billing_error） | 官方：賬單或付款資訊有問題 | 到 Console 賬單頁檢查付款方式、充值 |
| `HTTP 403`（permission_error） | 官方：這個 Key 沒有許可權用這項資源 | 請組織管理員檢查工作區和許可權，或換自己能用的 Key |
| `HTTP 404`（not_found_error） | 模型名或地址不對，或你的組織不能用這個模型 | Base URL 改回 `https://api.anthropic.com/v1`，模型改回 `claude-opus-5-5` 或點“重新整理模型”選 |
| `HTTP 400`（invalid_request_error） | 請求內容不被接受；官方：達到你自己設的花費上限時也會返回 400 | 先把模型、Base URL 改回預填值再測；檢查 Console 裡的花費上限 |
| `HTTP 429`（rate_limit_error） | 官方：達到限速，或達到當前等級的月度花費上限 | 等一會兒再試；少開幾個同時跑的任務；一直 429 就到 Console 看用量等級 |
| `HTTP 529`（overloaded_error）或 `HTTP 500` | 官方：服務暫時過載或內部錯誤 | 稍後重試；兔白會按普通網路問題處理，任務裡失敗的批次保留原文 |
| “Claude 拒絕了這次請求（安全分類：…）” | 模型的安全分類器拒絕了這段內容。Opus 5.5 / Sonnet 5.5 的請求已允許服務端自動換模型重試，仍被拒才會出現 | 檢查這批字幕是否包含敏感內容；可換另一個模型再試 |
| “Claude 輸出達到長度上限” | 一批內容太長 | 重新識別時會自動分批；只差少量字幕時可在字幕工作台“字幕列表”上方點“AI 校對” |
| 連不上（超時、無法連線） | 網路到不了 `api.anthropic.com`，或你所在地區不受支援 | 換一個能開啟 platform.claude.com 的網路再試；不行就改用 DeepSeek、阿里雲百鍊等其他服務 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 按上表查原因，處理後重新識別 |

## 隱私與費用

- **傳到哪裡**：`api.anthropic.com`（境外）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作台的“AI 特效字幕”會附帶畫面截圖或字幕效果預覽圖。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只保留到退出軟體，絕不存明文。不寫進工程、日誌或匯出檔案。本機沒有儲存金鑰時，兔白也會讀取環境變數 `ANTHROPIC_API_KEY`；已儲存的金鑰優先。
- **費用**（官方價格頁，2026-10-18 核對，單位：美元 / 百萬 token）：

| 模型 | 輸入 | 快取命中 | 輸出 | 備註 |
| --- | --- | --- | --- | --- |
| `claude-opus-5-5`（預填） | 4.00 | 0.20 | 20.00 | |
| `claude-sonnet-5-5` | 2.00 | 0.10 | 10.00 | |
| `claude-haiku-5-5` | 0.10 | 0.01 | 0.50 | 單次提示超過 10 萬 token 時：輸入 0.50、輸出 2.50 |

一段影片要花多少取決於字幕字數和重試次數，兔白沒有固定數字。價格以官方頁面為準。字幕校對、斷句這類批次工作用 `claude-sonnet-5-5` 或 `claude-haiku-5-5` 會便宜很多。

## 進階（一般使用者可跳過）

- 兔白髮送 `POST https://api.anthropic.com/v1/messages`，帶 `x-api-key: <金鑰>` 和 `anthropic-version: 2023-06-01`，並以流式（`stream: true`）讀取回答；系統提示放在 `system`，截圖轉成圖片塊。
- 這幾款模型不接受 `temperature` 等取樣引數，兔白不傳送；思考是自適應的（不能關），字幕校對、斷句、翻譯這類批次工作附 `output_config.effort: "low"` 以加快速度、少用 token，AI 特效字幕用模型預設值。
- 用 `claude-opus-5-5`、`claude-sonnet-5-5` 時附 `fallbacks: "default"`（beta 標頭 `server-side-fallback-2026-07-01`）：被安全分類器拒絕時由 Anthropic 服務端換成推薦的模型重試；`claude-haiku-5-5` 沒有這項功能。
- 需要按 JSON 回答時，兔白在系統提示裡要求“只回一個 JSON 物件”，再從回答裡取出 JSON 並本地校驗。
- “重新整理模型”呼叫 `GET https://api.anthropic.com/v1/models`（分頁引數 `after_id`）。

## 來源（2026-10-18 核對）

- 獲取 API Key：<https://platform.claude.com/docs/en/get-api-key>
- 入門（第一個請求）：<https://platform.claude.com/docs/en/get-started>
- 價格：<https://platform.claude.com/docs/en/about-claude/pricing>
- 錯誤碼：<https://platform.claude.com/docs/en/api/errors>
- 支援的國家和地區：<https://www.anthropic.com/supported-countries>
- API Keys 頁面、賬單頁需要登入，本次沒有看到裡面的內容。
