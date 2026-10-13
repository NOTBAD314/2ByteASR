<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 阿里雲百鍊 · 錄音檔案識別（Qwen3-ASR / Qwen-Audio-3.1）

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入控制台才能確認。

## 一眼看懂

| 專案 | 內容 |
| --- | --- |
| 在兔白裡做什麼 | 雲端識別長錄音（單個檔案 ≤12 小時、≤2 GB），不需要顯示卡或本地模型 |
| 兩個模型（同一把 Key） | **Qwen3-ASR-Flash**：字/詞級時間，不分說話人，不支援熱詞。**Qwen-Audio-3.1-ASR-Flash**：字/詞級時間 + 說話人（官方建議 2 小時內），支援熱詞與上下文 |
| 需要什麼 | 阿里雲賬號、百鍊 API Key + API Host，**以及你自己的 OSS 私有儲存**（設定一次） |
| 為什麼要 OSS | 這個介面不收本地檔案，只收“服務商能讀到的音訊網址”。兔白把音訊放進你的私有 Bucket，生成限時簽名連結交給百鍊，取得結果後刪除 |
| 不想碰 OSS | 改用“MOSS Pro 雲端（MOSI）”：只要一把 Key，直接上傳本地音訊（只有句段時間，有說話人） |
| 費用 | 百鍊按音訊時長計費（“試識別一小段”時顯示官方模型列表介面返回的單價）；OSS 另有很少的儲存與流量費用 |

> **關於“服務商臨時上傳”**：百鍊有一個臨時上傳功能，兔白可以用它“先試試看”，但官方原文寫明“臨時 URL 有效期48小時，過期後無法使用，請勿用於生產環境”，上傳憑證介面“限流為 100 QPS 且不支援擴容”。所以兔白不把它當正式方式，也不會自動替你選；只有你在“音訊交給百鍊的方式”裡明確選“服務商臨時上傳（僅供試用）”才會使用。

## 第一部分：百鍊 API Key 與 API Host

1. **註冊並登入**阿里雲：<https://account.aliyun.com/register/qr_register.htm>（已有賬號直接登入）。
2. 開啟百鍊控制台 <https://bailian.console.aliyun.com/>，右上角選地域（建議“華北2（北京）”），按頁面提示同意協議、開通服務。**金鑰、API Host、模型按地域區分，不能跨地域混用。**
3. **實名認證**：官方說明領取和使用新人免費額度不需要實名；免費額度用完後繼續按量付費**必須實名**（未實名會報 `AllocationQuota.FreeTierOnly`）。
4. **建立 API Key**：北京地域的 API Key 頁面 <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key>。已有可用的 Key 就直接複製；要新建就點“建立 API Key”，歸屬業務空間可用預設業務空間，再點 Key 旁的複製圖示。
5. **複製 API Host**：建立 Key 後的彈窗裡，或“業務空間管理”頁的 API Host 列，形如 `llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com`（彈窗與列的確切位置以控制台為準：**待核實**）。

## 第二部分：自己的 OSS 私有儲存（正式使用，只做一次）

1. **建 Bucket**：OSS 控制台 <https://oss.console.aliyun.com/> →“Bucket 列表”→“建立 Bucket”。名稱例如 `2byte-asr-temp`，地域例如華東1（杭州）。**保持“私有”，不要改成公共讀**（官方預設就是私有並開啟“阻止公共訪問”）。名稱和地域建好後不能改。
2. **自動清理（建議）**：該 Bucket 的“資料管理”→“生命週期”→“建立規則”：按字首 `asr-temp/`，指定天數 `1`，動作“資料刪除”。兔白識別成功後本來就會刪除，這條規則保證意外中斷留下的檔案也會被清掉。
3. **建一個只管這個目錄的子賬號**：RAM 訪問控制 <https://ram.console.aliyun.com/> → 身份管理 → 使用者 → 建立使用者，訪問方式選“使用永久 AccessKey 訪問”。**AccessKey Secret 只在建立時顯示一次**，立刻儲存。**不要用主賬號 AccessKey；百鍊 API Key 不能代替它。**
4. **只給最小許可權**：在 RAM 裡新建“自定義許可權策略”，內容如下（把 `你的Bucket名` 換成第 1 步的名稱），授權給這個子使用者。這是按官方規則改寫的示例，不是官方原文：

   ```json
   {"Version": "1", "Statement": [
     {"Effect": "Allow", "Action": ["oss:PutObject", "oss:GetObject", "oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:你的Bucket名/asr-temp/*"]},
     {"Effect": "Allow", "Action": ["oss:ListObjects"], "Resource": ["acs:oss:*:*:你的Bucket名"],
      "Condition": {"StringLike": {"oss:Prefix": ["asr-temp/*"]}}}
   ]}
   ```

   兔白只用這四個動作：上傳本次音訊、生成簽名連結並自檢、識別後刪除、清理 48 小時前殘留的臨時檔案。

## 第三部分：貼回兔白

首頁右上角“說明”→“申請與設定 API…”→ 左側選“阿里雲百鍊 · 錄音檔案識別”。上方步驟卡依次是：註冊並登入 › 建立 API Key › 建私有 OSS 與 AccessKey › 貼到下面 › 檢查並儲存，每張卡的“開啟網頁”直接開啟對應的官方頁面。

| 欄位 | 填什麼 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- |
| 模型 | 兩選一（見上表） | — | 已預選 Qwen3-ASR（之前用 3.1 的保留 3.1） |
| API Host | `llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com` | 第一部分第 5 步 | 否。整段網址（含 `https://`、`/api/v1`，甚至聊天用的 `/compatible-mode/v1`）也可以，會自動換算 |
| API Key | `sk-…` | 第一部分第 4 步 | 否 |
| 音訊交給百鍊的方式 | “我自己的阿里雲 OSS 私有儲存（正式使用）” | — | **已預選 OSS** |
| OSS 地域 | 例如 `cn-hangzhou` | 第二部分第 1 步 | 下拉選擇 |
| OSS Bucket 名稱 | 例如 `2byte-asr-temp` | 第二部分第 1 步 | 否 |
| 臨時目錄（灰色） | `asr-temp/` | — | **已預填，不用改** |
| AccessKey ID / Secret | `LTAI…` / 一串字元 | 第二部分第 3 步 | 否 |
| 識別成功後自動刪除 OSS 臨時音訊 | 勾選 | — | **預設勾選** |

“將使用”一行顯示地域和 Base URL；把滑鼠停在上面能看到四種地址分開列出（官方網站 `https://bailian.console.aliyun.com/`、API Host、Base URL `https://llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com/api/v1`、完整請求 Endpoint `…/api/v1/services/audio/asr/transcription`，查詢任務用 `…/api/v1/tasks/{task_id}`），不用你判斷要不要加 `/v1`。舊設定裡的 `https://dashscope.aliyuncs.com/…`（舊共用域名）照樣能用，兔白會提示官方建議換成工作空間專屬的 API Host。

## 測試會看到什麼

1. **免費檢查（不上傳音訊）**：本機檢查格式 → 調官方“查詢模型列表”介面。成功時：設定格式 ✓、服務可以連線 ✓、認證成功（API Key 有效）✓、指定模型可用 ✓。
2. **檢查 OSS（上傳很小的測試檔案後刪除）**：上傳十幾個位元組的測試檔案，生成簽名連結、讀回、刪除。成功時“音訊上傳方式 ✓ 可以上傳、生成簽名連結並刪除測試物件”。
3. **試識別一小段…**：先確認上傳物件與可能費用，再上傳約 6 秒的兔白自帶英文合成語音（或你選的 60 秒以內音訊）。成功時：實際短音訊識別 ✓、回傳時間戳 ✓（字/詞級）。Qwen3-ASR 的“回傳說話人”顯示“—”，這是模型能力限制，不是錯誤。

只有第 3 步成功，才說明真的能用。

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 認證失敗（401 `InvalidApiKey`） | 複製不完整，或 Key 與 API Host 不是同一地域 | 在同一地域重新複製 Key 和 API Host，再做免費檢查 |
| 403 `AccessDenied.Unpurchased` | 還沒開通百鍊 | 回第一部分第 2 步開通 |
| 403 `AllocationQuota.FreeTierOnly` | 免費額度用完且未實名 | 完成實名認證並開通按量付費 |
| 400 `Arrearage` | 欠費 | 充值後重試 |
| 429 `Throttling…` | 限流 | 等幾分鐘再試 |
| 模型列表裡沒有該模型 | 地域不提供，或模型名不對 | 換北京地域的 API Host，或核對模型名 |
| 音訊上傳方式 ✗“還沒有設定音訊交給服務商的方式” | 沒填 OSS，也沒選臨時上傳 | 按第二部分設定 OSS；或改用 MOSS Pro 雲端 |
| 檢查 OSS 失敗 | AccessKey 錯、許可權策略沒授權、Bucket 名或地域不對 | 重做第二部分第 3、4 步，確認地域選對 |
| 任務失敗 `FILE_403_FORBIDDEN` | 百鍊讀不到音訊連結 | 先“檢查 OSS”；Bucket 不要設白名單攔截 |
| “查不到這個任務” | 任務記錄超過官方保留的 24 小時 | 在完成頁重試（會重新計費，需要你確認） |

## 識別時會發生什麼

- 兔白把本次識別範圍轉成 16 kHz 單聲道 WAV（只有聲音）→ 上傳到你的 OSS → 生成 24 小時簽名連結 → 提交非同步任務 → **立即儲存任務編號** → 定時查詢 → 下載結果檔案（結果連結 24 小時有效）→ 解析時間戳寫入工程 → 刪除 OSS 臨時音訊。
- 斷網後重新識別：先查詢原任務，**不會**重新上傳收費。提交時斷網、無法確認是否受理：停下並請你核對，**不會**自動重提。
- 取消：只有排隊中（PENDING）的任務能在雲端取消；已在識別中的任務取消後仍可能計費，兔白會如實提示。
- 時間：服務端返回的詞可能是多個字（如“阿里雲”）。兔白把每個詞當成一個實測單位儲存，剃刀不會在詞中間按估算時間切；詞內的逐字顯示只是均分的顯示效果。
- 術語庫：Qwen-Audio-3.1 會把規範詞作為熱詞與上下文提示傳送（保持原寫法）；Qwen3-ASR 官方不支援熱詞，不傳送。熱詞只是提示，識別後的詞庫校對照常進行。
- 選了“服務商臨時上傳（僅供試用）”時：音訊上傳到百鍊臨時空間（48 小時後由百鍊刪除），上傳後超過約 40 小時還沒提交的會重新上傳。

## 隱私與費用

- 會上傳：本次識別範圍的音訊（先到你的 OSS，再由百鍊讀取）。不會上傳：畫面、工程、其他素材。
- 費用：百鍊按音訊時長計費；新使用者在北京地域有免費額度（具體額度以控制台為準：**待核實**）。OSS 標準儲存約 0.12 元/GB/月（本地冗餘），外網流出流量閒時 0.25 元/GB、忙時 0.50 元/GB（中國內地按量價，2026-10-13 核對）；1 小時 16 kHz 單聲道 WAV 約 115 MB，識別後即刪除。百鍊讀取 OSS 是否按外網流出計費：官方未寫明，**待核實**。
- 金鑰與 AccessKey 只儲存在本機（Windows DPAPI 加密；Mac 鑰匙串，不可用時只留本次會話、不寫明文），不寫進工程、日誌或匯出檔案。

## 來源（2026-10-14 核對）

- 臨時上傳的官方限制（48 小時、勿用於生產、100 QPS）：<https://help.aliyun.com/zh/model-studio/get-temporary-file-url>
- Qwen-ASR API（Filetrans 提交 / 查詢、`enable_words`、結果欄位）：<https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference>
- 模型與能力（12 小時 / 2 GB、說話人、熱詞、公網 URL 輸入）：<https://help.aliyun.com/zh/model-studio/asr-model>
- 地域與域名：<https://help.aliyun.com/zh/model-studio/regions>
- 獲取 API Key：<https://help.aliyun.com/zh/model-studio/get-api-key>
- 錄音檔案識別說明：<https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide>
- 新人免費額度與實名：<https://help.aliyun.com/zh/model-studio/new-free-quota>
- 查詢模型列表：<https://help.aliyun.com/zh/model-studio/list-models>
- 錯誤碼：<https://help.aliyun.com/zh/model-studio/error-code>
- OSS 建立 Bucket：<https://help.aliyun.com/zh/oss/user-guide/create-a-bucket-4>
- RAM 使用者 / AccessKey：<https://help.aliyun.com/zh/ram/user-guide/create-a-ram-user>、<https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair>
- OSS 許可權策略示例：<https://help.aliyun.com/zh/oss/user-guide/common-examples-of-ram-policies>
- 生命週期規則：<https://help.aliyun.com/zh/oss/user-guide/lifecycle-rules-based-on-the-last-modified-time>
- OSS 價格：<https://www.aliyun.com/price/detail/oss>
