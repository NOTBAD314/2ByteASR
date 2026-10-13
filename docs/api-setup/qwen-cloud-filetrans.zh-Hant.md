<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 Qwen Cloud（Qwen 官方 API）· 錄音檔案識別

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入控制台才能確認，兔白所在電腦沒有 Qwen Cloud 賬號。

## 一眼看懂

| 專案 | 內容 |
| --- | --- |
| 在兔白裡做什麼 | 雲端識別長錄音（單個檔案 ≤12 小時、≤2 GB），不需要顯示卡或本地模型。服務在新加坡 |
| 兩個模型（同一把 Key） | **Qwen-Audio-3.1-ASR-Flash**（推薦）：字/詞級時間 + 說話人（官方建議 2 小時內），支援熱詞與上下文。**Qwen3-ASR-Flash**：字/詞級時間，不分說話人，不支援熱詞 |
| 需要什麼 | Qwen Cloud 賬號 + 補全付款資訊 + 按量付費 API Key，**以及一個 OSS 私有儲存**（設定一次） |
| 為什麼要 OSS | 這個介面只收“服務端讀得到的音訊網址”（官方：Publicly accessible file URL, 1 per request）。兔白把音訊放進你的私有 Bucket，用限時簽名連結交給服務商，取得結果後刪除 |
| 不想碰 OSS | 改用“MOSS Pro 雲端（MOSI）”：只要一把 Key，直接上傳本地音訊（只有句段時間，有說話人） |
| 費用 | 按音訊用量計費，以 Qwen Cloud 賬單為準；補全付款資訊後每個模型有 90 天免費額度（2026-10-13 核對） |

> **關於“服務商臨時上傳”**：Qwen Cloud 和百鍊共用一套臨時上傳機制。阿里雲官方原文寫明“臨時 URL 有效期48小時，過期後無法使用，請勿用於生產環境”。兔白只把它當作“先試試看”的選項，不會自動替你選：只有你在“音訊交給服務商的方式”裡明確選“服務商臨時上傳（僅供試用）”才會使用。

### 先分清三個入口

| 入口 | 能不能給兔白識別字幕 |
| --- | --- |
| Qwen 官網聊天（qwen.ai / chat.qwen.ai） | **不能**。聊天登入只用於網頁聊天，沒有給第三方軟體的授權方式 |
| **Qwen Cloud（本頁，home.qwencloud.com）** | **能**。用按量付費 API Key，不需要 Workspace ID |
| 阿里雲百鍊（中國站） | 能，見“阿里雲百鍊 · 錄音檔案識別”。Key 與 Qwen Cloud **不能互換** |

## 跟著做

1. **註冊並登入**：<https://home.qwencloud.com/>（登入用阿里雲國際賬號）。
2. **補全付款資訊**：<https://home.qwencloud.com/billing/overview?target=payment>。官方說明補全後才解鎖新使用者免費額度；沒補全時呼叫會報“Access to model denied”。可在 <https://home.qwencloud.com/benefits> 開啟“僅使用免費額度”開關：免費額度用完會直接停止，不扣錢。
3. **建立 API Key**：<https://home.qwencloud.com/api-keys> → “Create API key” → 填描述（例如“兔白字幕”）→ “Generate Key”，**立刻複製**（官方：完整 Key 只顯示一次）。官方文件寫按量付費 Key 形如 `sk-xxxxx`（控制台是否顯示為 `sk-ws-` 開頭：**待核實**）。**不要用 Token Plan 訂閱 Key（`sk-sp-` 開頭）**，它不能做錄音檔案識別。
4. **準備 OSS 私有儲存**（只做一次）：
   - 已經為“阿里雲百鍊 · 錄音檔案識別”設定過 OSS 的，**直接共用**，跳過這一步。
   - 沒有的話，任選一個阿里雲 OSS：國際站控制台 <https://oss.console.alibabacloud.com/>（與 Qwen Cloud 同一國際賬號能否直接開通 OSS：**待核實**），或中國站控制台 <https://oss.console.aliyun.com/>。地域建議選新加坡（`ap-southeast-1`），離服務近。
   - 建私有 Bucket、建只管 `asr-temp/` 目錄的 RAM 子使用者與 AccessKey、加最小許可權策略與生命週期清理，步驟和許可權策略與百鍊教程“第二部分”完全相同（國際站 RAM 控制台 <https://ram.console.alibabacloud.com/>）。
5. **貼到兔白**：首頁右上角“說明”→“申請與設定 API…”→ 左側選“Qwen Cloud”。步驟卡依次是：註冊並登入 › 建立 API Key › 建私有 OSS 與 AccessKey › 貼到下面 › 檢查並儲存，每張卡的“開啟網頁”直接開啟對應頁面。
6. **檢查**：點“免費檢查（不上傳音訊）”和“檢查 OSS（上傳很小的測試檔案後刪除）”；想確認真的能識別，再點“試識別一小段…”。
7. 點“**儲存並用於識別**”。

## 兔白裡的每一欄

| 欄位 | 填什麼 | 已預填？ |
| --- | --- | --- |
| 模型 | 兩選一（見上表） | 已預選 Qwen-Audio-3.1 |
| API Key | 第 3 步複製的 Key | 否 |
| 服務地址（灰色，按“修改”才能改） | `https://maas.qwencloudapi.com` | **已預填，不用改**；官方命令列工具使用的 `https://dashscope-intl.aliyuncs.com` 也可以 |
| 音訊交給服務商的方式 | “我自己的阿里雲 OSS 私有儲存（正式使用）” | **已預選 OSS** |
| OSS 地域 / Bucket 名稱 / AccessKey ID / Secret | 第 4 步的結果 | 否（與百鍊共用同一組設定） |
| 臨時目錄（灰色） | `asr-temp/` | **已預填** |

服務地址不用你判斷：官方網站 `https://home.qwencloud.com/`、API Host `maas.qwencloudapi.com`、Base URL `https://maas.qwencloudapi.com/api/v1`、完整請求 Endpoint `https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription`（按“修改”後可在“將使用”一行和它的提示裡看到）。

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
| 服務商不認這把 API Key | 複製不完整、多了空格、Key 已刪除，或用了百鍊（中國站）的 Key | 回 API Key 頁面重新建立並複製 |
| 這是 Token Plan 訂閱專用的 Key | `sk-sp-` 開頭 | 在同一頁面建立按量付費 Key |
| 賬戶還沒補全付款資訊 | `AccessDenied.Unpurchased` | 到賬單頁補全付款資訊 |
| 免費額度已用完，且開著“僅使用免費額度” | `AllocationQuota.FreeTierOnly` | 要繼續付費使用就關掉該開關；不想付費就停在這裡 |
| 賬戶欠費或餘額不足 | `Arrearage` | 到賬單頁處理 |
| 這把 Key 沒有呼叫模型的許可權 | 子業務空間沒授權這個模型 | 給子業務空間授權，或用預設業務空間的 Key |
| 請求太頻繁 | `Throttling` | 稍等再試 |
| 音訊上傳方式 ✗“還沒有設定音訊交給服務商的方式” | 沒填 OSS，也沒選臨時上傳 | 按第 4 步設定 OSS；或改用 MOSS Pro 雲端 |
| 服務端沒能讀取音訊 | 簽名連結讀不到（Bucket 白名單）或臨時上傳已過期 | 先“檢查 OSS”；再在完成頁重試（會重新上傳） |
| 連不上 maas.qwencloudapi.com | 網路或代理 | 檢查網路；大陸網路連新加坡可能需要穩定的國際線路 |

## 識別時會發生什麼

- 音訊（16 kHz 單聲道 WAV，只有聲音）→ 你的 OSS → 限時簽名連結 → 提交非同步任務 → **立即儲存任務編號** → 定時查詢 → 下載結果 → 寫入工程 → 刪除 OSS 臨時音訊。
- 斷網後重新識別：先查詢原任務，**不會**自動重新提交、不會重複收費。只有排隊中（PENDING）的任務能在雲端取消；已在執行的任務，按“取消”只停止本機等待，服務端仍可能完成並計費，兔白會如實顯示。
- 服務端返回的多字詞（如“阿里雲”）作為一個實測單位儲存，剃刀不會在詞中間按估算時間切。

## 隱私與費用

- 會上傳：本次識別範圍的音訊。不會上傳：畫面、工程、其他素材。
- API Key、AccessKey 只存本機（Windows DPAPI 加密；Mac 鑰匙串，不可用時只留本次會話、不寫明文）。
- 兔白本身免費；Qwen Cloud 與 OSS 都是第三方付費服務。

## 來源（2026-10-14 核對）

- 語音識別模型、音訊輸入方式與限制：<https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models>
- 獲取 API Key（Key 型別、只顯示一次）：<https://docs.qwencloud.com/api-reference/preparation/api-key>
- 錄音檔案識別 HTTP API：<https://docs.qwencloud.com/api-reference/speech-recognition/fun-asr-recording/restful-api>
- 業務空間：<https://docs.qwencloud.com/developer-guides/administration/workspace>
- 新使用者免費額度：<https://docs.qwencloud.com/resources/free-quota>
- 錯誤碼：<https://docs.qwencloud.com/api-reference/preparation/error-messages>
- 非同步任務查詢與取消：<https://docs.qwencloud.com/api-reference/more/manage-asynchronous-tasks>
- 臨時上傳的官方限制：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- 國際站 OSS / RAM：<https://www.alibabacloud.com/help/en/oss/user-guide/create-a-bucket-4>、<https://www.alibabacloud.com/help/en/ram/user-guide/create-a-ram-user>、<https://www.alibabacloud.com/help/en/oss/user-guide/common-examples-of-ram-policies>、<https://www.alibabacloud.com/help/en/oss/user-guide/lifecycle-rules-based-on-the-last-modified-time>、<https://www.alibabacloud.com/help/en/oss/pricing-overview>
