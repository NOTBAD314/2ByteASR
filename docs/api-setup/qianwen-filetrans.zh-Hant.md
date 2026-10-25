<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 千問AI平台（Qwen 官方中國站）· 錄音檔案識別

最後核對：2026-10-25。來源見文末。千問AI平台是 Qwen 官方 API 的中國站，和國際站 Qwen Cloud 是同一套介面、同一批模型；兔白所在電腦沒有千問AI平台賬號，真實服務尚未驗證。

## 一眼看懂

| 專案 | 內容 |
| --- | --- |
| 在兔白裡做什麼 | 雲端識別長錄音（單個檔案 ≤12 小時、≤2 GB），不需要顯示卡或本地模型。服務在北京，大陸網路直接可用 |
| 兩個模型（同一把 Key） | **Qwen-Audio-3.1-ASR-Flash**（推薦）：字/詞級時間 + 說話人（官方建議 2 小時內），支援熱詞與上下文。**Qwen3-ASR-Flash**：字/詞級時間，不分說話人，不支援熱詞 |
| 需要什麼 | 千問AI平台賬號 + 按量付費 API Key（`sk-ws-` 開頭），**以及一個阿里雲 OSS 私有儲存**（設定一次） |
| 為什麼要 OSS | 這個介面只收“服務端讀得到的音訊網址”（官方：公網可訪問的檔案 URL，單次 1 個）。兔白把音訊放進你的私有 Bucket，用限時簽名連結交給服務商，取得結果後刪除 |
| 不想碰 OSS | 改用“MOSS Pro 雲端（MOSI）”：只要一把 Key，直接上傳本地音訊（只有句段時間，有說話人） |
| 費用 | 按音訊用量計費，以千問AI平台賬單為準；新使用者註冊有體驗額度（哪些模型可用以控制台為準）。單價見官方定價頁 |

> **關於“服務商臨時上傳”**：官方原文寫明“臨時 URL 有效期48小時，過期後無法使用，請勿用於生產環境”。兔白只把它當作“先試試看”的選項，不會自動替你選：只有你在“音訊交給服務商的方式”裡明確選“服務商臨時上傳（僅供試用）”才會使用。

### 中國站還是國際站

在“申請與設定 API…”裡選“千問AI平台 錄音檔案識別”或“Qwen Cloud 錄音檔案識別”都是同一項，視窗頂部有“中國站（千問AI平台）/ 國際站（Qwen Cloud）”切換。簡體中文介面預設中國站；已經儲存過地址的，按儲存的地址顯示。

| 入口 | 能不能給兔白識別字幕 |
| --- | --- |
| 千問 App / 網頁聊天 | **不能**。聊天登入只用於聊天，沒有給第三方軟體的授權方式 |
| **千問AI平台（本頁，platform.qianwenai.com）** | **能**。服務在北京，用按量付費 API Key，不需要 Workspace ID |
| Qwen Cloud（國際站，home.qwencloud.com） | 能，在同一視窗切到“國際站”。服務在新加坡，Key 與千問AI平台**不能互換** |
| 阿里雲百鍊 | 能，見“阿里雲百鍊 · 錄音檔案識別”。Key 與千問AI平台**不能互換** |

## 跟著做

1. **註冊並登入**：<https://platform.qianwenai.com/home> → 右上角“登录”，用手機號或阿里雲賬號登入。
2. **認證與充值**：新使用者註冊即有體驗額度；體驗額度用完後，要先完成實名認證並充值才能繼續呼叫（官方錯誤碼說明）。賬單頁：<https://platform.qianwenai.com/home/billing/overview>。控制台裡有“免費額度用完即停”開關：開著時免費額度用完會直接停止，不扣錢。
3. **建立 API Key**：<https://platform.qianwenai.com/home/api-keys> → “创建 API Key” → 填描述（例如“兔白字幕”）→ 生成，**立刻複製**（官方：完整 Key 只在建立時顯示一次）。按量付費 Key 是 `sk-ws-` 開頭（早期建立的是 `sk-` 開頭）。**不要用 Token Plan 訂閱 Key（`sk-sp-` 開頭）**，它不能做錄音檔案識別。
4. **準備 OSS 私有儲存**（只做一次）：
   - 已經為“阿里雲百鍊 · 錄音檔案識別”設定過 OSS 的，**直接共用**，跳過這一步。
   - 沒有的話，在阿里雲 OSS 控制台 <https://oss.console.aliyun.com/> 建私有 Bucket。地域建議選華北2 北京（`cn-beijing`），離服務近。
   - 建只管 `asr-temp/` 目錄的 RAM 子使用者與 AccessKey（<https://ram.console.aliyun.com/>）、加最小許可權策略與生命週期清理，步驟和許可權策略與百鍊教程“第二部分”完全相同。
5. **貼到兔白**：首頁右上角“說明”→“申請與設定 API…”→ 右上角“換一家”選“千問AI平台 錄音檔案識別”，確認頂部選的是“中國站（千問AI平台）”。視窗一步一頁：註冊登入 › 充值 › 建立 Key › 建 OSS › 貼上檢查，每一步的按鈕直接開啟對應頁面。
6. **檢查**：點“免費檢查”（不上傳音訊）和“檢查 OSS（上傳很小的測試檔案後刪除）”；想確認真的能識別，再點“試識別一小段…”。
7. 點“**儲存並用於識別**”。

## 兔白裡的每一欄

| 欄位 | 填什麼 | 已預填？ |
| --- | --- | --- |
| 模型 | 兩選一（見上表） | 已預選 Qwen-Audio-3.1 |
| API Key | 第 3 步複製的 Key | 否 |
| 服務地址（灰色，按“修改”才能改） | `https://maas.qianwenaiapi.com` | **已預填，不用改** |
| 音訊交給服務商的方式 | “我自己的阿里雲 OSS 私有儲存（正式使用）” | **已預選 OSS** |
| OSS 地域 / Bucket 名稱 / AccessKey ID / Secret | 第 4 步的結果 | 否（與百鍊共用同一組設定） |
| 臨時目錄（灰色） | `asr-temp/` | **已預填** |

服務地址不用你判斷：官方網站 `https://platform.qianwenai.com/home`、API Host `maas.qianwenaiapi.com`、Base URL `https://maas.qianwenaiapi.com/api/v1`、完整請求 Endpoint `https://maas.qianwenaiapi.com/api/v1/services/audio/asr/transcription`（按“修改”後可在“將使用”一行和它的提示裡看到）。

## 測試會看到什麼

| 結果行 | 成功時 | 會不會上傳 / 收費 |
| --- | --- | --- |
| 設定格式 | ✓（Key 沒有空格、不是 Token Plan Key、地址是 https） | 只在本機檢查 |
| 服務可以連線 / 認證成功（API Key 有效） | ✓ | 不上傳、不收費 |
| 指定模型可用 | 常顯示“?”：這個介面的模型列表不列出錄音檔案識別模型，以實際識別為準 | 不上傳、不收費 |
| 音訊上傳方式 | ✓ 可以上傳、生成簽名連結並刪除測試物件（選了臨時上傳時：服務商同意發放上傳憑證，沒有上傳任何檔案） | 只上傳十幾個位元組的測試檔案 |
| 實際短音訊識別 / 回傳時間戳 / 回傳說話人 | ✓ 識別出文字、有字/詞級時間；單人測試音訊的說話人常顯示“—” | **上傳測試音訊，可能收費** |

## 常見失敗與下一步

| 現象 | 原因 | 下一步 |
| --- | --- | --- |
| 服務商不認這把 API Key | 複製不完整、多了空格、Key 已刪除，或用了 Qwen Cloud（國際站）/ 百鍊的 Key | 回 API Key 頁面重新建立並複製；用國際站的 Key 就把視窗頂部切到“國際站” |
| 這是 Token Plan 訂閱專用的 Key | `sk-sp-` 開頭 | 在同一頁面建立按量付費 Key |
| 賬戶還沒完成認證或充值 | 新使用者體驗額度用完 | 在控制台完成實名認證並充值 |
| 免費額度已用完，且開著“免費額度用完即停” | 官方說明：開著這個開關時免費額度用完即停止 | 要繼續付費使用就關掉該開關；不想付費就停在這裡 |
| 賬戶欠費或餘額不足 | `Arrearage` | 到賬單頁充值 |
| 請求太頻繁 | `Throttling` | 稍等再試 |
| 音訊上傳方式 ✗“還沒有設定音訊交給服務商的方式” | 沒填 OSS，也沒選臨時上傳 | 按第 4 步設定 OSS；或改用 MOSS Pro 雲端 |
| 服務端沒能讀取音訊 | 簽名連結讀不到（Bucket 白名單）或臨時上傳已過期 | 先“檢查 OSS”；再在完成頁重試（會重新上傳） |
| 連不上 maas.qianwenaiapi.com | 網路或代理 | 檢查網路或代理設定 |

## 識別時會發生什麼

- 音訊（16 kHz 單聲道 WAV，只有聲音）→ 你的 OSS → 限時簽名連結 → 提交非同步任務 → **立即儲存任務編號** → 定時查詢 → 下載結果 → 寫入工程 → 刪除 OSS 臨時音訊。
- 斷網後重新識別：先查詢原任務，**不會**自動重新提交、不會重複收費。只有排隊中（PENDING）的任務能在雲端取消；已在執行的任務，按“取消”只停止本機等待，服務端仍可能完成並計費，兔白會如實顯示。
- 服務端返回的多字詞（如“阿里雲”）作為一個實測單位儲存，剃刀不會在詞中間按估算時間切。

## 隱私與費用

- 會上傳：本次識別範圍的音訊。不會上傳：畫面、工程、其他素材。
- API Key、AccessKey 只存本機（Windows DPAPI 加密；Mac 鑰匙串，不可用時只留本次會話、不寫明文）。
- 兔白本身免費；千問AI平台與 OSS 都是第三方付費服務。

## 來源（2026-10-25 核對）

- 語音識別模型、音訊輸入方式與限制：<https://platform.qianwenai.com/docs/developer-guides/speech/speech-to-text-models>
- 獲取 API Key（Key 型別、只顯示一次）：<https://platform.qianwenai.com/docs/api-reference/preparation/api-key>
- 錄音檔案識別 HTTP API（提交與查詢地址、臨時 URL 48 小時、結果存放在北京）：<https://platform.qianwenai.com/docs/api-reference/speech-recognition/fun-asr-recording/restful-api>
- 錯誤碼（欠費、認證與充值、免費額度用完即停）：<https://platform.qianwenai.com/docs/api-reference/preparation/error-messages>
- 新使用者體驗額度：<https://www.qianwenai.com/benefits>
- 價格：<https://platform.qianwenai.com/pricing/api>
- 臨時上傳的官方限制：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- OSS / RAM：<https://help.aliyun.com/zh/oss/user-guide/create-a-bucket-4>、<https://help.aliyun.com/zh/ram/user-guide/create-a-ram-user>
