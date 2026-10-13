<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 阿里雲百鍊 · 通義千問（文字 AI）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯。**只發送字幕文字，不上傳音訊** |
| 在哪裡填 | 「AI 智慧斷句設定」→“AI 服務”選 **阿里雲百鍊（保留）** |
| 要花錢嗎 | 新開通百鍊的賬戶，華北2（北京）地域的模型通常各有 100 萬 token、90 天的免費額度；用完後要實名認證並按量付費 |
| 地址怎麼填 | 這張卡片**只有一個“Base URL”欄**，不會幫你換算“API Host”。預填的是北京舊域名 `https://dashscope.aliyuncs.com/compatible-mode/v1`，可以直接用；官方建議換成你自己的“業務空間專屬域名”，寫法見下文 |
| 和錄音檔案識別共用 Key 嗎 | 可以共用同一地域的 API Key |
| 兔白驗證狀態 | 已有接入；本輪未用真實金鑰重新實測 |

## 它在兔白裡做什麼

- **AI 斷句**：把識別出的整段文字切成適合看的字幕句子（“全文斷句使用 AI”）。
- **字幕校對**：修正錯別字、專有名詞、標點（“字幕校對使用 AI”）。
- **翻譯**：日語任務識別後翻成中文，以及字幕工作室裡的“翻譯 / 生成雙語字幕”。翻譯用的是“字幕校對模型”那一套設定。
- 同一套設定也用於術語整理、字幕工作室的“AI 設計”等輔助功能。
- 服務名後面的“（保留）”表示這是兔白早期就有、繼續保留的選項，用法和其他服務一樣。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| 註冊阿里雲賬號 | <https://account.aliyun.com/register/qr_register.htm> | 公開頁 |
| 開通百鍊（模型廣場） | <https://bailian.console.aliyun.com/model/market> | 需登入，待核實。官方：用主賬號開啟，閱讀並同意協議後自動開通 |
| API Key 頁面（北京） | <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key> | 需登入，待核實 |
| 業務空間管理（看 API Host） | <https://bailian.console.aliyun.com/cn-beijing/settings/workspace> | 需登入，待核實 |
| 個人實名認證說明 | <https://help.aliyun.com/zh/account/verify-your-identity-individual-account> | 用手機支付寶掃碼 |
| 獲取 API Key 說明 | <https://help.aliyun.com/zh/model-studio/get-api-key> | |
| 地域與接入域名 | <https://help.aliyun.com/zh/model-studio/regions> | 專屬域名與舊域名 |
| OpenAI 相容介面說明 | <https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope> | 各地域 Base URL |
| 新人免費額度 | <https://help.aliyun.com/zh/model-studio/new-free-quota> | |
| 模型價格 | <https://help.aliyun.com/zh/model-studio/model-pricing> | |
| 錯誤碼 | <https://help.aliyun.com/zh/model-studio/error-code> | |

## 從未註冊開始

1. **註冊**：沒有阿里雲賬號先註冊 <https://account.aliyun.com/register/qr_register.htm>。
2. **開通百鍊**：用**主賬號**開啟 <https://bailian.console.aliyun.com/model/market>，官方說“閱讀並同意協議後，將自動開通阿里雲百鍊”；沒有彈出協議說明已經開通過。如果提示“您尚未進行實名認證”，先完成實名（官方推薦用手機支付寶掃碼認證）。
3. **選地域**：API Key 頁面右上角先選地域。想用免費額度請選 **華北2（北京）**——官方：只有北京地域的模型有免費額度。每個地域的接入地址、API Key 和模型列表都是分開的，不能混用。
4. **建立 API Key**：在 API Key 頁面點“建立 API Key”。官方說明彈窗裡有“歸屬賬號”（預設主賬號）、“歸屬業務空間”（預設“預設業務空間”）、“許可權”（建議“全部”），點“確定”後在列表裡點複製圖示複製 Key。官方：Key 沒有失效時間；每個賬號每個地域最多 50 個。完整 Key 能否在列表裡再次檢視：需要登入才能確認，待核實。
5. **記下 API Host（想用專屬域名時）**：官方說可以在“建立 API Key 後的彈窗”裡複製 API Host，或在“業務空間管理”頁的“API Host”一列複製。它形如 `llm-xxx.cn-beijing.maas.aliyuncs.com`（`llm-xxx` 是你的業務空間 ID；控制台顯示時是否帶 `https://`，以實際顯示為準）。
6. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選百鍊）
7. 在“AI 服務”下拉里選 **阿里雲百鍊（保留）**（新安裝時預設選的是“Grok Account”，記得改）。
8. 把 Key 貼進“API 金鑰”。想用專屬域名的話，展開“進階設定：Base URL、協議與輸出能力”，按下一節改 Base URL。
9. 點“測試連線”，看到“連線測試通過”後點對話方塊右下角“儲存設定”。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務、各自填金鑰。

## Base URL 到底填什麼

這張卡片只認 **Base URL**，兔白會在後面自動加 `/chat/completions`。**不要只貼 API Host**，也不要貼錄音檔案識別用的 `/api/v1` 地址——那樣請求會發到錯誤的路徑而失敗。

| 名稱 | 舊域名（兔白預填） | 業務空間專屬域名（官方推薦） |
| --- | --- | --- |
| 官方網站 | 百鍊控制台 <https://bailian.console.aliyun.com/model/market>（需登入，待核實） | 同左 |
| API Host | `dashscope.aliyuncs.com` | `llm-xxx.cn-beijing.maas.aliyuncs.com`（從控制台複製） |
| **Base URL（填進兔白）** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| 完整請求 Endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions` |

換算方法：`https://` ＋ 你的 API Host ＋ `/compatible-mode/v1`。如果控制台複製出來的 API Host 已經帶 `https://`，就不要再加一次。

兩種域名的區別（官方地域頁）：

- 專屬域名“推薦用於生產環境”。
- 舊域名：“存量業務相容，建議遷移至業務空間專屬域名”；並且“DashScope 域名（dashscope.aliyuncs.com）自2026年9月30日起不再支援新特性”。官方沒有寫舊域名的停用日期。
- 所以：預填的舊域名現在可以直接用；想長期穩定或要用新功能，換成專屬域名。

不是北京地域的 Key：官方 OpenAI 相容說明列出了新加坡 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`、維吉尼亞 `https://{WorkspaceId}.us-east-1.maas.aliyuncs.com/compatible-mode/v1`、東京 `https://{WorkspaceId}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1`（`{WorkspaceId}` 換成你的業務空間 ID）。中國香港、法蘭克福的聊天地址該頁沒有列出，待核實。這些地域沒有免費額度；兔白預填的模型在這些地域能否使用，兔白未實測。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 開通百鍊 | 需要（主賬號同意協議即開通） |
| 實名認證 | 開通時如有提示就需要。官方：領取和使用新人免費額度**不需要**實名；免費額度用完後要繼續按量付費，**必須**實名並充值 |
| 免費額度 | 首次開通百鍊時自動發放，每個模型獨立，通常 100 萬 token（輸入輸出合計），有效期 90 天，**僅華北2（北京）地域** |
| 用完以後 | 未實名：直接停用（“免費額度用完即停”對未實名賬戶強制開啟，報 403 `AllocationQuota.FreeTierOnly`）。已實名：預設自動轉為按量付費；也可以自己開啟“免費額度用完即停” |
| 模型許可權 | 預設業務空間的 Key 可呼叫所有標準模型；子業務空間的 Key 只能呼叫該空間授權的模型 |
| OSS 等儲存空間 | 不需要（只發文字） |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| AI 服務 | 選用哪家服務 | `阿里雲百鍊（保留）` | 下拉選擇 | 需要自己選 |
| API 金鑰 | 證明是你的賬戶在呼叫 | 以 `sk-` 開頭的一串字元（官方錯誤碼頁：確認 Key 以 sk- 開頭、沒有多餘空格） | API Key 頁面 | 否。如果你已在「申請與設定 API」為“百鍊 · 錄音檔案識別”儲存過 Key，且用的是同一個域名，這裡會直接顯示“已配置：…”，不用再貼 |
| 模型 | 用哪個模型 | `qwen3.7-flash-2026-07-15`（預填）；更強更貴的 `qwen3.7-max` | 官方價格頁 | 是 |
| Base URL（進階） | 服務地址 | 見上一節 | 控制台 API Host 換算 | 是（北京舊域名）。用專屬域名時要改 |
| 協議 / Protocol（進階） | 請求格式 | `Auto` | — | 是，不用改 |
| JSON Mode、Structured Output（進階） | 要求模型按固定格式回答 | 勾選 | — | 已勾選，不用改 |
| stream（進階） | 灰色不可選；兔白目前不用流式 | — | — | — |

## 測試時會看到什麼

**測試連線**：兔白用這張卡片上的服務、模型、地址和金鑰（剛貼進去還沒儲存的金鑰也會用）發一句很短的固定文字，要求模型只回一小段 JSON，最多等 45 秒。會消耗極少量免費額度或費用。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · 相容 JSON／本地校驗 · 1.23s`（最後是用時）。如果卡片上選的服務和上次儲存的不同，後面還會加“尚未儲存：點選儲存後 AI 設計才會使用此 Provider”。
- 首頁 AI 卡片下方會顯示“連線正常”；失敗顯示“連線失敗”；還沒測過顯示“尚未測試連線”。
- 失敗時狀態行顯示服務商的錯誤，例如 `HTTP 401：……InvalidApiKey……`，對照下表處理。

**重新整理模型**：讀取百鍊的模型列表（不讓模型生成文字）。官方相容介面說明沒有寫模型列表介面；讀不到時會提示“可手動輸入模型 ID”，直接在“模型”裡輸入即可。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| “當前模型（bailian）缺少 API 金鑰……” | 還沒貼金鑰 | 把 Key 貼進“API 金鑰”再測 |
| `HTTP 401` + `InvalidApiKey` | Key 複製錯、多了空格，或 **Key 和地址不是同一地域**（例如北京的 Key 配了新加坡地址） | 重新複製 Key；北京的 Key 配北京的 Base URL |
| `HTTP 401` “Access denied: Either you are not authorized to access this workspace…”，或 `404` “WorkSpace can not be found.” | 專屬域名裡的業務空間 ID 寫錯，或你的賬號不在這個業務空間 | 回控制台“業務空間管理”頁重新複製 API Host，按上一節重新拼 Base URL |
| 請求失敗，Base URL 裡沒有 `/compatible-mode/v1` | 只貼了 API Host，或貼了錄音檔案識別的 `/api/v1` 地址 | 改成 `https://<API Host>/compatible-mode/v1` |
| `HTTP 403` + `AccessDenied.Unpurchased` | 百鍊還沒開通 | 用主賬號開啟模型廣場同意協議開通；按提示完成實名 |
| `HTTP 403` + `AllocationQuota.FreeTierOnly` | 免費額度用完，而且未實名或開著“免費額度用完即停” | 完成實名並充值；已實名的關掉“免費額度用完即停”。仍失敗時官方建議重置或新建 Key |
| `HTTP 403` + `Model.AccessDenied` | 子業務空間的 Key 沒有這個模型的許可權 | 給該業務空間授權這個模型，或改用預設業務空間的 Key |
| `HTTP 404` “The model … does not exist.” | 模型名寫錯 | “模型”改回下拉里的 `qwen3.7-flash-2026-07-15` |
| `HTTP 400` + `Arrearage` | 賬戶欠費 | 到費用中心充值，等幾分鐘再測 |
| `HTTP 429` | 請求太頻繁或超過限流 | 等一會兒再試；少開幾個同時跑的任務 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 按上表查原因（多半是額度或限流），處理後重新識別；只差少量字幕時，可在字幕工作室“字幕列表”上方點“AI 校對”看修改建議 |

## 隱私與費用

- **傳到哪裡**：你在 Base URL 裡填的百鍊地址（北京：`dashscope.aliyuncs.com` 或你的 `….cn-beijing.maas.aliyuncs.com`）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作室的“AI 設計”在模型支援看圖時，可能附帶畫面截圖或字幕效果預覽圖。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只保留到退出軟體，絕不存明文。不寫進工程、日誌或匯出檔案。
- **費用**（官方價格頁，華北2（北京），2026-10-14 核對，單位：元 / 百萬 token）：

| 模型 | 單次請求輸入長度 | 輸入 | 輸出 |
| --- | --- | --- | --- |
| `qwen3.7-flash-2026-07-15` | 0–32K / 32K–256K / 256K–1M | 0.2 / 0.6 / 1.2 | 0.8 / 2.4 / 4.8 |
| `qwen3.7-max` | 0–1M | 12 | 36 |

這兩個模型思考模式和非思考模式價格相同。按單次請求的輸入長度分檔計價；一段影片要花多少取決於字幕字數和重試次數，兔白沒有固定數字。免費額度用完、已實名的賬戶會自動轉按量付費；不想被扣費請開啟“免費額度用完即停”。價格以官方頁面為準。

## 進階（一般使用者可跳過）

- 兔白髮送 `POST {Base URL}/chat/completions`，帶 `Authorization: Bearer <金鑰>`；需要按 JSON 回答時附 `response_format: {"type": "json_object"}`，服務端若回 400 並提到這個引數，兔白會自動去掉它重試一次。測試連線的內容是一句要求回 `{"ok":true,"text":"兔白字幕"}` 的提示，最多 80 個輸出 token。
- “重新整理模型”呼叫 `GET {Base URL}/models`。2026-10-14 不帶金鑰訪問舊域名的這個地址回“需要認證”（HTTP 401），說明地址存在；帶金鑰能否列出模型，兔白本輪未實測。
- 金鑰按“服務 + 域名”分開儲存。改用專屬域名後，之前在舊域名下儲存的百鍊 Key 仍會被找到。
- 本機沒有儲存百鍊金鑰時，兔白也會讀取環境變數 `DASHSCOPE_API_KEY`、`2BYTEASR_DASHSCOPE_API_KEY` 等舊名稱；已儲存的金鑰優先。
- 官方價格頁還有更新的 `qwen3.8-max` 等模型，可以在“模型”裡手動輸入；兔白沒有為它們預設，也未實測。

## 來源（2026-10-14 核對）

- 地域與接入域名：<https://help.aliyun.com/zh/model-studio/regions>
- OpenAI 相容介面：<https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- 獲取 API Key：<https://help.aliyun.com/zh/model-studio/get-api-key>
- 首次呼叫（註冊、開通、實名提示、建立 Key）：<https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen>
- 新人免費額度：<https://help.aliyun.com/zh/model-studio/new-free-quota>
- 模型價格：<https://help.aliyun.com/zh/model-studio/model-pricing>
- 錯誤碼：<https://help.aliyun.com/zh/model-studio/error-code>
- 個人實名認證：<https://help.aliyun.com/zh/account/verify-your-identity-individual-account>
- 註冊頁：<https://account.aliyun.com/register/qr_register.htm>（只讀到“註冊賬號”標題）
- 百鍊控制台各頁面需要登入，本次沒有看到裡面的內容。
