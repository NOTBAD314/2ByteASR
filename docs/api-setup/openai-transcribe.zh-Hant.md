<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->
# 申請與設定 OpenAI 轉寫

最後核對：2026-10-14。來源見文末。標“待核實”的地方需要登入才能確認。

## 先看結論

| 問題 | 回答 |
| --- | --- |
| 在兔白裡做什麼 | 語音識別（生成字幕）：把有人聲的音訊短塊上傳到 OpenAI 轉成文字 |
| 預設模型 | `gpt-transcribe`（OpenAI 當前推薦的錄音轉寫模型） |
| 時間戳 | 預設模型**只回文字**，每塊（10 秒以內）只有一個起止時間；改用 `whisper-1` 可得到句段時間。兔白不要逐詞時間 |
| 說話人 | **沒有**。OpenAI 只有 `gpt-4o-transcribe-diarize` 能分說話人，兔白沒有適配它 |
| 費用 | 先充值後使用；`gpt-transcribe` 約 $0.0045 / 分鐘（2026-10-14 核對） |
| 地區 | **中國大陸、香港、澳門不在 OpenAI 支援地區內**，在這些地方使用會被拒絕，賬戶也可能被停用 |
| 兔白驗證狀態 | 已有接入；本輪未用真實金鑰重新實測 |

## 它在兔白裡做什麼

- 用於語音識別，可以當“主力轉寫”，也可以當“複核”來源。
- 兔白先在本機找出有人聲的片段，切成短塊：當主力時每塊 10 秒以內，當複核時 25 秒以內。每塊轉成 16 kHz 單聲道 WAV 上傳，預設 4 塊同時進行。
- 兔白向 OpenAI 要“帶句段時間”的結果。官方說只有 `whisper-1` 提供時間戳，所以：
  - 用 `gpt-transcribe`（預設）、`gpt-4o-transcribe`、`gpt-4o-mini-transcribe`：只拿到文字，整塊共用一個起止時間；
  - 用 `whisper-1`：拿到句段起止時間。
  - 需要按字剪輯時，請在模型工坊配一個本地字幕時間軸（對齊）模型。
- 每次上傳還會附一段文字提示，幫助拼對專有名詞：當前字幕場景、素材檔名，以及你在詞庫裡確認過的專名（最多 64 個）。
- 某一塊失敗時，兔白會自動等一會兒再試，最後再把失敗的塊逐個補一遍。仍失敗的部分會提示“約 N 秒素材無字幕，可重跑識別補齊”。
- 這裡只管語音識別。用 OpenAI 做 AI 斷句、校對、翻譯，要另外在「AI 智慧斷句設定」裡填寫，見“OpenAI”文字 AI 教程。

## 官方連結

| 用途 | 網址 | 說明 |
| --- | --- | --- |
| 開發者文件：快速開始 | <https://developers.openai.com/api/docs/quickstart> | 建立 Key、免費測試請求、加值 |
| API Key 頁面 | <https://platform.openai.com/settings/organization/api-keys> | 需登入，待核實（網址來自官方 API 參考頁） |
| 用量檔位與限額 | <https://platform.openai.com/settings/organization/limits> | 需登入，待核實（網址來自官方速率限制頁） |
| 語音轉文字說明 | <https://developers.openai.com/api/docs/guides/speech-to-text> | 各模型差別、時間戳只限 `whisper-1` |
| `gpt-transcribe` 模型頁 | <https://developers.openai.com/api/docs/models/gpt-transcribe> | |
| 價格 | <https://developers.openai.com/api/docs/pricing> | |
| 支援的國家和地區 | <https://developers.openai.com/api/docs/supported-countries> | |
| 錯誤碼 | <https://developers.openai.com/api/docs/guides/error-codes> | |
| 速率限制與用量檔位 | <https://developers.openai.com/api/docs/guides/rate-limits> | |

## 從未註冊開始

1. 先確認你所在的地區在官方支援列表裡（見上表）。中國大陸、香港、澳門不在列表中。
2. 註冊並登入 OpenAI 開發者平台（platform.openai.com）。註冊頁面和需要填寫的資料：需要登入才能看到，待核實。
3. 充值：OpenAI API 用預付額度。官方快速開始說可以先做一次免費測試請求，要更高額度需在 Billing 加值；累計購買滿 $5 會升到 Build 檔。沒有充值時轉寫能不能用，官方未寫明，兔白未實測，建議先加值。加值頁面的位置和最低金額：需要登入才能看到，待核實。
4. 開啟 API Key 頁面，建立一把 Key（官方：“create an API key in the dashboard”）。按鈕名稱、是否需要選專案、完整 Key 是否只顯示一次：需要登入才能看到，待核實。建議建好後立刻複製。
5. 開啟兔白的「申請與設定 API」，在左側“語音識別（生成字幕）”下選 **OpenAI 轉寫**。開啟方式任選一種：
   - 首頁右上角“說明”選單 →“申請與設定 API…”
   - 模型工坊 →“線上 API”頁 →“OpenAI Transcribe API”卡片上的設定按鈕
   - 首頁識別方案卡片上的“配置 API”
6. 貼入“API Key”。“模型”可以留空（等於 `gpt-transcribe`），見下表。
7. 點“免費檢查（不上傳音訊）”；想確認真的能識別，再點“試識別一小段…”。
8. 點“儲存”；要馬上用它做主力轉寫，點“儲存並用於識別”。

這一頁目前沒有“① 在官網建立 API Key [開啟網頁]”那一排提示，請用上面表格裡的連結開啟官網。

## 需不需要開通服務、充值或儲存空間

| 專案 | 是否需要 |
| --- | --- |
| 單獨開通語音服務 | 官方檔案沒有提到；模型頁列出的預設限額從 Build 檔開始 |
| 充值 | 需要（預付額度）。額度用完時請求會被拒絕 |
| 地區 | 必須在官方支援地區使用；官方說在不支援的地區使用，賬戶可能被封鎖或停用 |
| OSS 等儲存空間 | 不需要 |

## 兔白裡的每一欄

| 欄位 | 做什麼用 | 例子 | 從哪裡來 | 已預填？ |
| --- | --- | --- | --- | --- |
| API Key | 證明是你的賬戶在呼叫 | 欄位示例為 `sk-…`（官方頁面本次沒寫明格式） | OpenAI 的 API Key 頁面 | 否。儲存後再開啟會顯示“已儲存（···後四位）；留空表示不修改” |
| 模型 | 用哪個轉寫模型 | `gpt-transcribe` 或 `whisper-1` | 官方語音轉文字說明 | **新使用者看到的是空白框**，下面的提示寫著“預設值需按 OpenAI 當前文件核對。”。留空儲存，兔白就用 `gpt-transcribe`；儲存後再開啟會顯示已儲存的模型名 |

怎麼選模型（價格為官方價格頁 2026-10-14 的估算值）：

| 模型 | 約每分鐘 | 兔白拿到的時間 |
| --- | --- | --- |
| `gpt-transcribe`（預設，官方推薦） | $0.0045 | 每塊一個起止時間 |
| `gpt-4o-mini-transcribe` | $0.003 | 每塊一個起止時間 |
| `gpt-4o-transcribe` | $0.006 | 每塊一個起止時間 |
| `whisper-1` | $0.006 | 句段起止時間 |

地址在這一頁**不顯示**，已經預設好，一般不用改。要改請點“進階設定…”，在「配置線上 ASR API」裡改“API 地址”。

| 專案 | 預設值 |
| --- | --- |
| 官方網站 | developers.openai.com（文件）、platform.openai.com（控制台，需登入） |
| API Host | `api.openai.com` |
| Base URL | `https://api.openai.com/v1` |
| 完整請求 Endpoint | `https://api.openai.com/v1/audio/transcriptions` |

“API 地址”裡存的是**完整請求 Endpoint**（最後一項，含 `/audio/transcriptions`），不是 Base URL。

## 測試時會看到什麼

**免費檢查（不上傳音訊）**：兔白用你的 Key 讀取 OpenAI 的模型列表，不上傳音訊、不收費。全部正常時：

| 結果行 | 顯示 |
| --- | --- |
| 設定格式 | ✓ 格式正確（地址 api.openai.com）。這一步只在本機檢查，沒有聯絡服務商。 |
| 服務可以連線 | ✓ 通過 |
| 認證成功（API Key 有效） | ✓ 通過 |
| 指定模型可用 | ✓ 通過（模型列表裡有你選的模型；列表裡是否一定列出 `gpt-transcribe`，兔白未實測） |
| 實際短音訊識別、回傳時間戳、回傳說話人 | — 尚未檢查 |

免費檢查全 ✓ 也不代表賬戶有餘額，餘額要靠試識別確認。

**試識別一小段…**：先彈出確認，寫明會上傳到 `api.openai.com`、可能產生費用。選“上傳自帶測試音訊”（兔白自帶約 6 秒英文合成語音，不含你的素材）或“選擇我的音訊…”（60 秒以內）。按 `gpt-transcribe` 折算約 $0.0005（官方沒寫最小計費單位）。成功時：

| 結果行 | 顯示 | 說明 |
| --- | --- | --- |
| 實際短音訊識別 | ✓ 識別出 N 段文字。 | 真的能用了 |
| 回傳時間戳 | ? 只有句段起止時間，沒有逐字時間…… | 正常結果。用 `gpt-transcribe` 時實際上整塊只有一個時間 |
| 回傳說話人 | — 這次結果沒有說話人標籤…… | 兔白不取 OpenAI 的說話人 |

## 常見失敗與下一步

| 現象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 設定格式 ✗“還沒有填寫 API Key”或“API Key 裡有空格或換行” | 沒貼上，或多複製了空格 | 回 Key 頁面重新複製那一串字元 |
| 服務可以連線 ✗“連不上服務：……” | 電腦網路到不了 `api.openai.com` | 檢查網路；所在地區不受支援時請改用其他服務（如訊飛、阿里雲百鍊） |
| 認證成功 ✗ HTTP 401 | Key 填錯、已刪除，或不屬於任何組織（官方 401 說明） | 新建一把 Key 重新貼入；仍失敗請確認賬戶已加入組織 |
| 認證成功 ✗ HTTP 403 | 兔白這裡顯示成“服務拒絕了這個 API Key”，但最常見的原因是**所在地區不受支援**（官方 403：Country, region, or territory not supported） | 對照官方支援地區列表。兔白不能繞過地區限制，請改用其他服務 |
| 指定模型可用 ✗“模型列表裡沒有 ……” | 模型名打錯，或這把 Key 所在專案不能用這個模型 | 清空“模型”欄（用預設 `gpt-transcribe`）或改填 `whisper-1`；專案的模型許可權設定在控制台裡，需要登入才能看到，待核實 |
| 試識別或正式識別報 HTTP 429，而且等了好幾分鐘 | 預付額度用完、達到組織或專案的花費上限，或請求太快（官方 429 有這幾種） | 兔白目前只顯示 HTTP 429，分不出是哪一種。先到 Billing 看餘額並加值，再看 Limits 頁；然後重試 |
| 試識別報 HTTP 400 | 填的模型不能做轉寫，或請求格式被拒 | 把“模型”改回 `gpt-transcribe` 或 `whisper-1` 後再試 |
| HTTP 500 / 503 | OpenAI 服務端故障或模型過載 | 兔白會自動重試；仍失敗就稍後再跑 |
| 識別完成，但提示“N 個短塊最終失敗（約 X 秒素材無字幕，可重跑識別補齊）” | 部分短塊被限流或網路中斷 | 稍後再識別一次 |

## 隱私與費用

- **傳到哪裡**：`api.openai.com`（OpenAI，境外）。
- **傳什麼**：有人聲的音訊短塊（16 kHz 單聲道 WAV，不含畫面），加一段文字提示（字幕場景、素材檔名、詞庫裡確認過的專名）。
- **金鑰**：只儲存在本機。Windows 用 DPAPI 加密；macOS 存在“鑰匙串”，鑰匙串不可用時只在本次執行期間儲存在記憶體，絕不存明文。不寫進工程、日誌或匯出檔案。
- **費用**：按上面模型表的每分鐘估算價（官方價格頁，2026-10-14 核對），從預付額度扣。實際以 OpenAI 賬單為準。

## 進階（一般使用者可跳過）

- 兔白每塊傳送 `POST https://api.openai.com/v1/audio/transcriptions`（multipart），欄位：`model`、`file`（chunk.wav）、`prompt`（最多 900 字）、`response_format=verbose_json`。不傳送 `timestamp_granularities[]` 和 `language` / `languages`。
- 服務商回 400 時，兔白改用 `response_format=json` 重試一次。`gpt-transcribe` 是否接受 `verbose_json`，官方沒寫，兔白未實測；無論哪種情況都沒有句段時間。
- 重試：429、5xx 和網路錯誤每塊最多 6 次，等待 1.5 秒起倍增、最長 20 秒，會遵守 `Retry-After`；之後對失敗塊逐個補掃最多 4 輪。所以額度用完時，試識別可能要等幾分鐘才報錯。
- 免費檢查呼叫的是 `GET https://api.openai.com/v1/models`。
- 官方單檔案上限 25 MB；兔白每塊只有幾百 KB。

## 來源（2026-10-14 核對）

- 快速開始：<https://developers.openai.com/api/docs/quickstart>
- API 參考總覽（Key 頁面網址）：<https://developers.openai.com/api/reference/overview>
- 語音轉文字：<https://developers.openai.com/api/docs/guides/speech-to-text>
- 轉寫介面參考：<https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create>
- `gpt-transcribe` 模型頁：<https://developers.openai.com/api/docs/models/gpt-transcribe>
- 價格：<https://developers.openai.com/api/docs/pricing>
- 支援的國家和地區：<https://developers.openai.com/api/docs/supported-countries>
- 錯誤碼：<https://developers.openai.com/api/docs/guides/error-codes>
- 速率限制與用量檔位：<https://developers.openai.com/api/docs/guides/rate-limits>
- platform.openai.com 的註冊頁、API Key 頁、幫助中心預付說明本次開啟時都返回 403（需要登入或拒絕抓取），內容未核實。
