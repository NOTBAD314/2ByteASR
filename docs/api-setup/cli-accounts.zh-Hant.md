<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 賬號登入類文字 AI（Grok Account / OpenAI Codex CLI / Google Antigravity，進階）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 文字 AI：AI 斷句、字幕校對、翻譯。**只發送字幕文字，不上傳音訊** |
| 和 API Key 方式的區別 | 不填 API Key。兔白呼叫你電腦上**已安裝、已登入**的官方命令列工具（CLI），用你的賬號額度完成請求 |
| 在哪裡填 | 「AI 智慧斷句設定」→“AI 服務”選 **Grok Account**、**OpenAI Codex CLI** 或 **Google Antigravity** |
| 要先做什麼 | 先在電腦上安裝對應的官方命令列工具。安裝要在 PowerShell 裡執行一行官方命令（見文末“進階”）；兔白不會替你安裝 |
| 適合誰 | 已經在用這些工具、熟悉命令列的人。一般使用者更推薦 DeepSeek、阿里雲百鍊等 API Key 方式：設定更簡單、費用更清楚 |
| 兔白驗證狀態 | 已有接入；本輪未用真實賬號重新實測 |

新安裝的兔白，“AI 服務”預設選的就是 **Grok Account**。沒裝 Grok 命令列工具的話，請改選其他服務。

## 三種方式分別是什麼

| 兔白裡的名字 | 官方工具 | 程式名 | 登入方式（官方） | 賬號與額度（官方，2026-10-14） |
| --- | --- | --- | --- | --- |
| Grok Account | Grok Build（SpaceXSI / x.ai） | `grok` | 第一次啟動時開啟瀏覽器驗證 | 官方頁面沒有寫需要哪種訂閱，待核實 |
| OpenAI Codex CLI | Codex CLI（OpenAI） | `codex` | `codex login` 後在瀏覽器完成登入；可選“Sign in with ChatGPT” | ChatGPT Free、Go、Plus、Pro、Business、Edu、Enterprise 方案都含 Codex，可用次數隨方案、模型和任務不同 |
| Google Antigravity | Antigravity CLI（Google） | `agy` | 在瀏覽器用個人 Google 賬戶登入，或選 Business account（Gemini Enterprise） | 個人免費方案有“基礎的每週用量限制”；Google AI Pro / Ultra 限額更高。個人方案是否包含 CLI，官方價格頁沒寫，待核實 |

地區限制由各服務自己決定，官方 CLI 頁面沒有列出可用國家 / 地區，待核實。

## 官方連結

| 用途 | 網址 |
| --- | --- |
| Grok Build 入門（安裝、登入） | <https://docs.x.ai/build/overview> |
| Grok Build 命令參考（`grok login`、`grok update`） | <https://docs.x.ai/build/cli/reference> |
| Codex CLI 介紹與安裝 | <https://learn.chatgpt.com/docs/codex/cli> |
| Codex 登入方式 | <https://learn.chatgpt.com/docs/auth> |
| Codex 方案與價格 | <https://learn.chatgpt.com/docs/pricing> |
| Antigravity 首頁 | <https://antigravity.google/> |
| Antigravity 下載（含 CLI 安裝命令） | <https://antigravity.google/download> |
| Antigravity CLI 入門（安裝位置、登入） | <https://antigravity.google/docs/getting-started?tab=cli> |
| Antigravity 方案與價格 | <https://antigravity.google/pricing> |

## 從零開始

1. **安裝官方工具**：按上表的官方頁面安裝（PowerShell 命令見文末“進階”）。裝好後最好重新開啟兔白，讓它找到新裝的程式。
2. 開啟兔白的「AI 智慧斷句設定」，任選一種方式：
   - 首頁“AI 智慧斷句”卡片上的“設定 AI”按鈕（或直接點這張卡片）
   - 模型工坊 →“AI 模型 / 智慧斷句”
   - 「申請與設定 API」裡這篇教程下方的“去填寫這家服務的金鑰”（開啟後仍要在“AI 服務”裡自己選）
3. 在“AI 服務”下拉里選 **Grok Account**、**OpenAI Codex CLI** 或 **Google Antigravity**。卡片會變成命令列頁面，顯示“CLI：未檢測”和“請先檢測 CLI 與登入狀態”。
4. 點 **重新檢測**。找到程式時會顯示版本和程式位置，以及“登入/憑據：……”。沒找到時會出現 **安裝幫助** 按鈕（只是一段說明，兔白不會自動安裝）。
5. 點登入按鈕：Grok 是 **管理 Grok 登入**，Codex 是 **開啟官方 Codex 登入**，Antigravity 是 **開啟 Google 登入**。瀏覽器會開啟官方登入頁；狀態行會顯示“在瀏覽器完成登入即可（視窗會自動收尾，無需保持任何外部視窗）”和登入連結。Codex 登入時還會彈出一個命令列小窗，登入完成後會自動關閉。
6. 登入完成後顯示“……：登入流程完成；當前配置請求仍需測試”，兔白會自動重新整理可用模型列表。
7. 點 **測試連線**，看到“連線測試通過”後，點對話方塊右下角 **儲存設定**。

**一張卡片還是兩張**：對話方塊上方的開關“同一雲端模型負責字幕校對與全文斷句（推薦）”預設開啟，這時只有一張卡片，標題是“統一校對與斷句模型”。關掉後會出現“字幕校對模型”和“全文斷句模型”兩張卡片，各自選服務。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 賬號 | 需要對應服務的賬號（見上文“三種方式”） |
| 訂閱 / 充值 | 由各服務的方案決定；兔白不收費，也看不到你的剩餘額度 |
| API Key | 不需要 |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 / 按鈕 | 做什麼用 | 例子 | 已預填？ |
| --- | --- | --- | --- |
| AI 服務 | 選用哪種方式 | `OpenAI Codex CLI` | 新安裝預設是 `Grok Account` |
| 重新檢測 | 找本機的官方程式、讀版本、看登入狀態 | — | — |
| 登入按鈕 | 開啟官方登入（名字見上文第 5 步）；登入成功後 Codex 的按鈕變成“重新登入或切換賬號” | — | — |
| 安裝幫助 | 沒找到程式時出現，只顯示說明 | — | — |
| 更新 CLI / 檢視方法 | 只有 Grok 有。用官方安裝程式裝在 `.grok\bin` 的，確認後執行官方自更新；其他安裝方式只顯示說明 | — | — |
| 退出 Codex 登入 | 只有 Codex 有，執行官方的退出登入 | — | — |
| 複製診斷資訊 / 展開診斷詳情 | 出問題時把檢測結果複製下來反饋 | — | — |
| 模型 | 用哪個模型；留空表示用該工具自己的預設模型（輸入框提示“預設模型”） | Antigravity 下拉里有 `gemini-3.8-flash-high`、`gemini-3.7-flash-high` | 留空 |
| 重新整理模型 | 讓命令列工具列出可用模型 | — | — |
| 進階設定：Base URL、協議與輸出能力 | 命令列方式只用到其中的 JSON Mode、Structured Output，保持勾選即可 | — | 已勾選 |

## 測試時會看到什麼

**重新檢測**：只檢查程式和登入狀態，不讓模型生成文字。例如 Codex 已登入時顯示“Codex CLI 已登入（模型呼叫待真實請求驗證）”；未登入顯示“Codex CLI 未登入；點選官方登入完成 OAuth 後重新檢測。”

**測試連線**：通過命令列工具發一句很短的固定文字，要求只回一小段 JSON，會消耗極少量賬號額度。

- 成功時狀態行顯示：`連線測試通過 · 中文 JSON 欄位正確 · …… · 3.21s`（中間一段說明 JSON 方式，最後是用時），卡片上的“請求：”一行變成“連線測試通過（中文 JSON）”。
- 超過 5 秒還沒回應時顯示“模型響應較慢，仍在等待… N 秒 · 可取消”，按鈕變成“取消測試”。命令列工具冷啟動較慢，多等一會兒是正常的。
- 首頁 AI 卡片下方會顯示“使用賬號登入”和“連線正常 / 連線失敗”。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 重新檢測後仍是“未檢測到”，出現“安裝幫助” | 程式沒裝，或裝在兔白找不到的位置 | 按官方頁面安裝後重新開啟兔白再檢測。兔白找的位置見文末“進階”；Codex 在 Windows 上只認 `codex.exe` |
| “未安裝官方 Codex CLI；請選擇安裝幫助。” | 同上（Codex） | 用官方安裝方式裝好 Codex，再點“重新檢測” |
| “……尚未登入”“登入未完成，請重新檢測” | 還沒登入，或瀏覽器裡沒完成登入 | 點登入按鈕，在瀏覽器完成登入後點“重新檢測” |
| 登入視窗一直沒反應 | 瀏覽器沒有彈出，或登入被取消 | 狀態行裡有登入連結時，複製到瀏覽器開啟；仍不行就再點一次登入按鈕（執行中再點一次會取消） |
| “需更新 CLI；本次請求失敗” | 命令列工具版本太舊 | Grok：點“更新 CLI / 檢視方法”；Codex、Antigravity：按官方頁面更新後點“重新檢測” |
| 測試很慢或超時 | 工具冷啟動慢、網路慢或服務繁忙 | 再測一次；仍超時就改用 API Key 方式 |
| 提示用量用完、需要升級方案之類 | 賬號的方案額度用完 | 等額度恢復，或升級方案；也可改用 API Key 方式 |
| 任務完成頁寫“原文回退 N 批” | 任務中這些批次的 AI 請求失敗，兔白保留了原文 | 先“重新檢測”和“測試連線”看原因，處理後重新識別 |

## 隱私與費用

- **傳到哪裡**：由命令列工具發到它自己的服務（Grok → x.ai；Codex → OpenAI；Antigravity → Google）。
- **傳什麼**：字幕文字，以及你填寫的遊戲 / 內容名稱和術語提示。**不傳送音訊**。字幕工作室的“AI 設計”在模型支援看圖時，可能附帶畫面截圖或字幕效果預覽圖。
- **賬號憑據**：兔白不儲存你的賬號密碼，也不讀取或儲存登入令牌；登入狀態由官方工具自己儲存。例如 Codex 官方說明它把登入資訊存在本機 `~/.codex/auth.json`（明文檔案）或系統憑據庫裡。
- **費用**：計入你在該服務的方案額度，兔白看不到也不替你計費。

## 進階（一般使用者可跳過）

**安裝命令（來自官方頁面，2026-10-14 核對）**

- Grok Build（<https://docs.x.ai/build/overview>）：Windows PowerShell 執行 `irm https://x.ai/cli/install.ps1 | iex`；macOS / Linux 執行 `curl -fsSL https://x.ai/cli/install.sh | bash`。
- Codex CLI（<https://learn.chatgpt.com/docs/codex/cli>）：macOS / Linux 執行 `curl -fsSL https://chatgpt.com/codex/install.sh | sh`。頁面上還有 Windows、npm、Homebrew 分頁，本次沒能讀到這些分頁裡的命令，請在官方頁面檢視。
- Antigravity CLI（<https://antigravity.google/download>）：Windows PowerShell 執行 `irm https://antigravity.google/cli/install.ps1 | iex`；macOS / Linux 執行 `curl -fsSL https://antigravity.google/cli/install.sh | bash`。官方說 Windows 上裝在 `C:\Users\<使用者名稱>\AppData\Local\agy\bin`。

**兔白去哪裡找程式**

- Grok：PATH 裡的 `grok`，或 `%USERPROFILE%\.grok\bin\grok.exe`。
- Codex（Windows）：`%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`，或 PATH 裡的 `codex.exe`。只有 `.cmd` 包裝、沒有 `codex.exe` 的安裝方式會被判定為未安裝。
- Antigravity：PATH 裡的 `agy.exe`，或 `%LOCALAPPDATA%\agy\bin\agy.exe`。

**兔白執行的官方命令**

- 登入：Grok `grok login --oauth`；Codex `codex login`（檢測時 `codex login status`，退出時 `codex logout`）；Antigravity 直接啟動 `agy`，由它帶出登入流程。
- 請求時，兔白對 Grok 關掉聯網搜尋和全部工具、對 Codex 關掉執行命令、瀏覽器、外掛等功能，只讓它回答文字；給 Antigravity 的命令只額外加了關閉斜槓命令的 `--disable-slash-commands`。
- “安裝幫助”的說明裡寫著“完成後回到這裡點選‘檢測 CLI’”，對應的按鈕實際叫“重新檢測”。

## 來源（2026-10-14 核對）

- Grok Build 入門：<https://docs.x.ai/build/overview>
- Grok Build 命令參考：<https://docs.x.ai/build/cli/reference>
- Codex CLI：<https://learn.chatgpt.com/docs/codex/cli>（原地址 <https://developers.openai.com/codex/cli> 已永久跳轉到這裡；網頁需要瀏覽器執行指令碼，用瀏覽器開啟讀取）
- Codex 登入：<https://learn.chatgpt.com/docs/auth>
- Codex 方案與價格：<https://learn.chatgpt.com/docs/pricing>
- Antigravity 首頁：<https://antigravity.google/>
- Antigravity 下載：<https://antigravity.google/download>
- Antigravity CLI 入門：<https://antigravity.google/docs/getting-started?tab=cli>
- Antigravity CLI 產品頁：<https://antigravity.google/product/antigravity-cli>
- Antigravity 方案與價格：<https://antigravity.google/pricing>
